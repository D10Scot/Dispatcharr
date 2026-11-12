"""Refresh of an OIDC-issued token (SSO spec 5.4, D17, D21).

- A refresh token with ``auth_method == "oidc"`` is refused when its provider is disabled or
  deleted.
- When the provider's ``version`` still equals the token's ``oidc_provider_version`` nothing
  else is read: one indexed provider read on top of the password-refresh baseline.
- Otherwise the level is recomputed from the claim values stored on the identity at its last
  login, under the CURRENT mappings. A changed claim path or no match refuses; a level at or
  above the stored one writes nothing (refresh never promotes); a lower one enters the
  locked block below, which re-reads everything and decides on the reloaded user only.

Locks: advisory, then the token's user (sfu). The provider and identity are re-read with
plain queries under the user lock, never with an identity row lock: identity-after-user is
the order spec 4.4's table forbids.
"""

from django.db import transaction
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.settings import api_settings

from apps.accounts.admin_floor import admin_floor_lock
from apps.accounts.models import OIDCIdentity, OIDCProvider, User

from . import mapping

ADMIN = User.UserLevel.ADMIN


class LastAdminRefused(Exception):
    def __init__(self, username, provider_slug):
        super().__init__("last_admin")
        self.username = username
        self.provider_slug = provider_slug


def _recompute(provider, identity, user_id):
    """The recomputed level, or None when any check of spec 5.4 fails."""
    if provider is None or not provider.enabled:
        return None
    # simplejwt stores the user id claim as a string (``for_user`` calls ``str``).
    if identity is None or str(identity.user_id) != str(user_id):
        return None
    if identity.mapping_claim_path != provider.claim_path:
        # The stored values were read from a different claim; never reinterpret them.
        return None
    values = identity.mapping_claim_values if isinstance(identity.mapping_claim_values, list) else []
    return mapping.level_for(provider.mappings, values)


def load_user(user_id):
    """The user as the view loads it, before any lock. A seam for the stale-object tests."""
    return User.objects.filter(pk=user_id).first()


def check(payload):
    """Raise ``InvalidToken`` (401 ``token_not_valid``) or ``LastAdminRefused``; else return."""
    user_id = payload.get(api_settings.USER_ID_CLAIM)
    provider = OIDCProvider.objects.filter(pk=payload.get("oidc_provider")).first()
    if provider is None or not provider.enabled:
        raise InvalidToken()
    if provider.version == payload.get("oidc_provider_version"):
        return

    identity = OIDCIdentity.objects.filter(pk=payload.get("oidc_identity")).first()
    level = _recompute(provider, identity, user_id)
    if level is None:
        raise InvalidToken()
    user = load_user(user_id)
    if user is None:
        raise InvalidToken()
    if not user.is_active or level >= user.user_level:
        # Inactive: simplejwt's own rule refuses it next. At or above: never promote.
        return
    _demote(user, payload)


def _demote(user, payload):
    # Everything above was read without a lock: it is only the reason to enter this block,
    # and nothing read before the lock decides the write.
    refused = None
    with transaction.atomic():
        admin_floor_lock()
        try:
            target = User.objects.select_for_update().get(pk=user.pk)
        except User.DoesNotExist:
            raise InvalidToken() from None
        provider = OIDCProvider.objects.filter(pk=payload.get("oidc_provider")).first()
        identity = OIDCIdentity.objects.filter(pk=payload.get("oidc_identity")).first()
        level = _recompute(provider, identity, target.pk)
        if level is None:
            raise InvalidToken()
        if level >= target.user_level:
            # A sign-in in between promoted the mapping's answer, or the user was lowered
            # meanwhile: no demotion, and never a last_admin refusal.
            return
        if (
            target.is_active
            and target.user_level >= ADMIN
            and not User.objects.filter(is_active=True, user_level__gte=ADMIN)
            .exclude(pk=target.pk)
            .exists()
        ):
            refused = LastAdminRefused(target.username, provider.slug)
        else:
            User.objects.filter(pk=target.pk, user_level__gt=level).update(user_level=level)
    if refused is not None:
        # Raised after the block so the caller's event is not inside a rolled-back
        # transaction; nothing was written.
        raise refused
