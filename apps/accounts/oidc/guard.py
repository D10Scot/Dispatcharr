"""The password-off lockout guard (SSO spec 5.5, D12, ruling B1).

**The rule.** ``password_login_enabled`` may be switched from true to false only by a request
whose validated access token carries ``auth_method == "oidc"``, an ``oidc_provider`` that
exists and is enabled NOW, and ``oidc_level == 10``. Each failed condition is one reason.

**The floor.** While the STORED value is false, a provider write that would leave no enabled
provider (disabling or deleting the last enabled one) is refused with
``last_enabled_provider``. The floor reads the stored value, never the break-glass override,
so an instance cannot be emptied of providers while the environment variable happens to be
set.

**Serialization.** Every caller takes ``auth_settings.lock_row()`` (``select_for_update`` on
the ``auth_settings`` row) inside ``transaction.atomic()`` first, reloads the row, and only
then calls ``evaluate``; nothing read before the lock decides. The writes that can change
either input in the dangerous direction all take that one lock: every ``auth_settings``
mutation (``PATCH settings/`` and the ``password_login`` command), a provider update whose
validated data sets ``enabled`` to false, and every provider delete. ``evaluate`` reads the
provider rows with plain queries; it locks none.

Everything else is allowed while password login is off, by any admin credential: credential
rotation, mapping and slug edits, enabling, and disabling or deleting a provider while another
stays enabled. Ruling B1 removed the version and redirect proofs, the proposed-state
evaluation and the different-provider rule; none of them is here.
"""

from rest_framework import status

from apps.accounts.models import OIDCProvider, User

from .errors import CodedError

CODE = "lockout_guard"
NOT_SSO_SESSION = "not_sso_session"
PROVIDER_NOT_ENABLED = "provider_not_enabled"
NOT_ADMIN_AT_SIGN_IN = "not_admin_at_sign_in"
LAST_ENABLED_PROVIDER = "last_enabled_provider"


class LockoutRefused(CodedError):
    """409 ``{"code": "lockout_guard", "reasons": [...]}``."""

    def __init__(self, reasons):
        super().__init__(CODE, status_code=status.HTTP_409_CONFLICT, reasons=list(reasons))


def token_claims(request):
    """The validated access token's claims, or ``{}`` for any other credential.

    ``JWTAuthentication`` sets ``request.auth`` to the validated token; an API key, a forced
    test authentication or a session leaves no token, and so no claim.
    """
    payload = getattr(getattr(request, "auth", None), "payload", None)
    return payload if isinstance(payload, dict) else {}


def evaluate(*, password_login_enabled, claims=None, switching_off=False, provider_leaving=None):
    """The guard's decision, as a list of reasons (empty: allowed).

    Called under the ``auth_settings`` row lock with the value reloaded under it.

    - ``switching_off``: the request turns password login from on to off; apply the rule to
      ``claims``.
    - ``provider_leaving``: the pk of an enabled provider the request disables or deletes;
      apply the floor against the stored ``password_login_enabled``.
    """
    reasons = []
    if switching_off:
        claims = claims or {}
        if claims.get("auth_method") != "oidc":
            reasons.append(NOT_SSO_SESSION)
        provider_pk = claims.get("oidc_provider")
        if not (
            type(provider_pk) is int
            and OIDCProvider.objects.filter(pk=provider_pk, enabled=True).exists()
        ):
            reasons.append(PROVIDER_NOT_ENABLED)
        if claims.get("oidc_level") != User.UserLevel.ADMIN:
            reasons.append(NOT_ADMIN_AT_SIGN_IN)
    if provider_leaving is not None and not password_login_enabled:
        others = OIDCProvider.objects.filter(enabled=True).exclude(pk=provider_leaving)
        if not others.exists():
            reasons.append(LAST_ENABLED_PROVIDER)
    return reasons
