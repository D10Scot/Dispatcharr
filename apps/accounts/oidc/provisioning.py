"""Identity resolution, linking and just-in-time provisioning (SSO spec 4.2, 4.4, D9, D21).

Authorization is decided before any write: step 1 computes the level from the mapping with
no database access, and a refusal there writes nothing. Everything else runs in ONE
``transaction.atomic()`` under the lock protocol of spec 4.4's table:

- below-Admin callbacks: ``admin_floor_lock()`` first, then identity, then user;
- Admin-mapped callbacks skip the mutex (a promotion cannot remove an admin);
- a callback never waits for an identity row while holding a user row. A new identity is
  inserted inside an ATTEMPT SAVEPOINT together with the user row it locks or inserts; on a
  conflict on the (provider, issuer, subject) constraint the savepoint is rolled back, which
  releases that user row, before the winner's identity is locked.

Every decision about a user is made on the row as locked here, never on an object loaded
earlier. The small module-level functions are the seams the concurrency tests hold on.

Nothing here logs a claim value or ``sub``.
"""

import secrets as pysecrets

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.admin_floor import admin_floor_lock
from apps.accounts.models import OIDCIdentity, User

from . import mapping

ADMIN = User.UserLevel.ADMIN
IDENTITY_CONSTRAINT = "oidc_identity_provider_issuer_subject_uniq"
USERNAME_MAX = 150
USERNAME_SUFFIXES = [""] + [f"-{n}" for n in range(2, 21)]
_SAFE_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._@-")


class Refused(Exception):
    """A refusal from the fixed vocabulary. ``username`` only when a user was resolved."""

    def __init__(self, code, username=None):
        super().__init__(code)
        self.code = code
        self.username = username


class Resolved:
    def __init__(self, user, identity, level, created):
        self.user = user
        self.identity = identity
        self.level = level
        self.created = created


# ---- constraint discrimination --------------------------------------------------------


def _constraint_name(exc):
    cause = exc.__cause__
    diag = getattr(cause, "diag", None)
    name = getattr(diag, "constraint_name", None)
    return name or ""


def is_identity_conflict(exc):
    name = _constraint_name(exc)
    if name:
        return name == IDENTITY_CONSTRAINT
    # SQLite (the test fallback) names columns, not constraints.
    text = str(exc)
    return "accounts_oidcidentity.provider_id" in text and "accounts_oidcidentity.subject" in text


def is_username_conflict(exc):
    name = _constraint_name(exc)
    if name:
        return name == User._meta.db_table + "_username_key"
    return str(exc).endswith("accounts_user.username")


# ---- claim-derived fields ---------------------------------------------------------------


def username_base(claims):
    """``preferred_username``, else ``email``, reduced to ``SAFE_CREDENTIAL_RE``'s alphabet.

    Never ``sub``: the username reaches ``SystemEvent`` details. Empty or absent gives
    ``sso-`` plus 8 random hex characters, unrelated to any claim.
    """
    for claim in ("preferred_username", "email"):
        value = claims.get(claim)
        if isinstance(value, str) and value:
            reduced = "".join(c for c in value if c in _SAFE_CHARS)
            if reduced:
                return reduced
            break
    return "sso-" + pysecrets.token_hex(4)


def username_candidates(base):
    for suffix in USERNAME_SUFFIXES:
        yield base[: USERNAME_MAX - len(suffix)] + suffix


def _str_claim(claims, name, limit):
    value = claims.get(name)
    return value[:limit] if isinstance(value, str) else ""


def _identity_fields(provider, claims, values):
    extra = {}
    if provider.kind == "entra":
        for name in ("tid", "oid"):
            if isinstance(claims.get(name), str):
                extra[name] = claims[name][:64]
    display = _str_claim(claims, "name", 255) or _str_claim(claims, "preferred_username", 255)
    return {
        "email_at_last_login": _str_claim(claims, "email", 254),
        "display_name": display,
        "extra": extra,
        "mapping_claim_path": provider.claim_path,
        "mapping_claim_values": mapping.values_to_store(values, provider.mappings),
        "last_login": timezone.now(),
    }


# ---- seams --------------------------------------------------------------------------------


def lookup_identity(provider, issuer, subject):
    return (
        OIDCIdentity.objects.select_for_update()
        .filter(provider=provider, issuer=issuer, subject=subject)
        .first()
    )


def winner_identity(provider, issuer, subject):
    """After an identity conflict: lock the identity another transaction committed."""
    return lookup_identity(provider, issuer, subject)


def lock_user(pk):
    return User.objects.select_for_update().get(pk=pk)


def insert_user(username, claims, level):
    user = User(
        username=username,
        email=_str_claim(claims, "email", 254),
        first_name=_str_claim(claims, "given_name", 150),
        last_name=_str_claim(claims, "family_name", 150),
        user_level=level,
        is_staff=False,
        is_superuser=False,
        stream_limit=0,
    )
    user.set_unusable_password()
    user.save(force_insert=True)
    return user


def insert_identity(provider, issuer, subject, user, fields):
    return OIDCIdentity.objects.create(
        provider=provider, issuer=issuer, subject=subject, user=user, **fields
    )


def other_active_admin_exists(target):
    return (
        User.objects.filter(is_active=True, user_level__gte=ADMIN).exclude(pk=target.pk).exists()
    )


def attempt_link(provider, issuer, subject, link_user_id, fields):
    """Spec 4.2 step 4's attempt savepoint: the user lock and the identity insert together."""
    with transaction.atomic():
        try:
            user = lock_user(link_user_id)
        except User.DoesNotExist:
            raise Refused("inactive") from None
        if not user.is_active:
            raise Refused("inactive", username=user.username)
        identity = insert_identity(provider, issuer, subject, user, fields)
    return user, identity


def attempt_jit(provider, issuer, subject, claims, level, fields):
    """Spec 4.2 step 5's attempt savepoint: BOTH inserts, each username in its own savepoint."""
    with transaction.atomic():
        base = username_base(claims)
        for candidate in username_candidates(base):
            try:
                with transaction.atomic():
                    user = insert_user(candidate, claims, level)
                break
            except IntegrityError as exc:
                if not is_username_conflict(exc):
                    raise
        else:
            raise Refused("provisioning_failed")
        identity = insert_identity(provider, issuer, subject, user, fields)
    return user, identity


# ---- resolution -----------------------------------------------------------------------


def _known(identity, intent, link_user_id):
    """Step 3: the identity row is locked; check ownership, then lock its user."""
    if intent == "link" and identity.user_id != link_user_id:
        # Refused before anything else is decided, without locking the other user's row.
        raise Refused("link_conflict")
    try:
        user = lock_user(identity.user_id)
    except User.DoesNotExist:
        raise Refused("inactive") from None
    if not user.is_active:
        raise Refused("inactive", username=user.username)
    return user


def _after_conflict(provider, issuer, subject, intent, link_user_id):
    identity = winner_identity(provider, issuer, subject)
    if identity is None:
        # The winner's row vanished between its commit and this read (an unlink).
        raise Refused("provisioning_failed")
    return identity, _known(identity, intent, link_user_id)


def resolve(provider, claims, *, intent, link_user_id):
    """Return ``Resolved`` or raise ``Refused``."""
    # Step 1: the level, with no database write and no read.
    try:
        mapping.check_groups_overage(provider, claims)
    except mapping.GroupsOverage:
        raise Refused("groups_overage") from None
    values = mapping.claim_values(claims, provider.claim_path)
    level = mapping.level_for(provider.mappings, values)
    if level is None:
        raise Refused("no_mapping")

    issuer = claims["iss"]
    subject = claims["sub"]
    fields = _identity_fields(provider, claims, values)
    created = False

    with transaction.atomic():
        if level < ADMIN:
            admin_floor_lock()

        identity = lookup_identity(provider, issuer, subject)
        if identity is not None:
            user = _known(identity, intent, link_user_id)
        elif intent == "link":
            try:
                user, identity = attempt_link(provider, issuer, subject, link_user_id, fields)
            except IntegrityError as exc:
                if not is_identity_conflict(exc):
                    raise
                identity, user = _after_conflict(provider, issuer, subject, intent, link_user_id)
        else:
            try:
                user, identity = attempt_jit(provider, issuer, subject, claims, level, fields)
                created = True
            except IntegrityError as exc:
                if not is_identity_conflict(exc):
                    raise
                identity, user = _after_conflict(provider, issuer, subject, intent, link_user_id)

        # Step 6: the level, decided on the row locked above (D9, D21).
        if (
            level < user.user_level
            and user.user_level >= ADMIN
            and user.is_active
            and not other_active_admin_exists(user)
        ):
            raise Refused("last_admin", username=user.username)

        now = timezone.now()
        user_changes = {"last_login": now}
        if user.user_level != level:
            user_changes["user_level"] = level
        User.objects.filter(pk=user.pk).update(**user_changes)
        for name, value in user_changes.items():
            setattr(user, name, value)

        OIDCIdentity.objects.filter(pk=identity.pk).update(**fields)
        for name, value in fields.items():
            setattr(identity, name, value)

    return Resolved(user, identity, level, created)
