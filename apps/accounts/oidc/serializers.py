"""Serializers for the OIDC admin API (SSO spec 5.1, 5.2, 3.6, 3.7).

The client secret is ``write_only`` and the private key has no field at all: responses carry
``client_secret_set`` and certificate fingerprints instead. Every provider write is one
column-restricted ``QuerySet.update()`` through ``OIDCProvider.update_columns`` (section 5.1),
never ``instance.save()``.
"""

import re
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.models import OIDCIdentity, OIDCProvider
from core.models import CoreSettings

from . import audit, auth_settings, certificates, expiry, redirect
from . import secrets as oidc_secrets
from .errors import CodedError

GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
SLUG_RE = re.compile(r"^[a-z0-9-]{1,40}$")
CLAIM_PATH_RE = re.compile(r"^[^.\s]+(\.[^.\s]+)*$")
ID_TOKEN_ALGS = {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "EdDSA"}
LEVELS = {0, 1, 10}
# Every literal path segment under /api/accounts/oidc/ in the spec's section 3.1 table: the
# first segments providers, providers-admin, settings, identities and exchange, and the
# second segments link, start and callback. A slug equal to one would make a route ambiguous.
RESERVED_SLUGS = frozenset(
    {"providers", "providers-admin", "settings", "identities", "exchange", "link", "start", "callback"}
)
MAX_MAPPINGS = 50
ENTRA_ISSUER = "https://login.microsoftonline.com/{tenant}/v2.0"
ENTRA_METHODS = (OIDCProvider.AUTH_PRIVATE_KEY_JWT, OIDCProvider.AUTH_SECRET_POST)
IMMUTABLE_WITH_IDENTITIES = ("issuer", "entra_tenant_id", "client_id")
IMMUTABLE_MESSAGE = (
    "cannot be changed while identities are linked; create a new provider, then have each "
    "person link it or unlink and re-provision"
)


def _default(name):
    return OIDCProvider._meta.get_field(name).get_default()


def _validate_issuer(value):
    try:
        parts = urlsplit(value)
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError on a bad port
    except ValueError:
        raise serializers.ValidationError("must be an absolute URL") from None
    scheme = parts.scheme.lower()
    if not host or scheme not in ("http", "https"):
        raise serializers.ValidationError("must be an absolute https URL")
    if scheme == "http" and not settings.OIDC_ALLOW_HTTP:
        raise serializers.ValidationError("must use https")
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise serializers.ValidationError("must have no user information, query or fragment")


class OIDCProviderSerializer(serializers.ModelSerializer):
    client_secret = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=False,
        trim_whitespace=False,
        max_length=2048,
        help_text="Write-only. Omit to keep the stored secret; an empty string is refused.",
    )
    client_secret_set = serializers.SerializerMethodField()
    client_certificate = serializers.SerializerMethodField()
    credential_expiry = serializers.SerializerMethodField()
    credential_unreadable = serializers.SerializerMethodField()
    redirect_uri = serializers.SerializerMethodField()

    class Meta:
        model = OIDCProvider
        fields = [
            "id",
            "slug",
            "display_name",
            "kind",
            "enabled",
            "issuer",
            "entra_tenant_id",
            "client_id",
            "allow_private_network",
            "client_auth_method",
            "client_assertion_alg",
            "client_secret",
            "client_secret_set",
            "client_secret_expires_at",
            "client_certificate",
            "credential_expiry",
            "credential_unreadable",
            "scopes",
            "id_token_alg",
            "claim_path",
            "mappings",
            "prompt_select_account",
            "redirect_uri",
            "version",
            "created",
            "updated",
        ]
        read_only_fields = ["id", "version", "created", "updated"]
        extra_kwargs = {
            "issuer": {"required": False},
            "entra_tenant_id": {"required": False},
        }

    # ---- read side -------------------------------------------------------------------

    def get_client_secret_set(self, obj) -> bool:
        return bool(obj.client_secret_encrypted)

    def get_client_certificate(self, obj) -> dict:
        def _describe(pem):
            try:
                return certificates.describe(pem)
            except ValueError:
                return None

        return {
            "active": _describe(obj.client_cert_pem),
            "pending": _describe(obj.pending_client_cert_pem),
        }

    def get_credential_expiry(self, obj) -> dict:
        return expiry.credential_expiry(obj)

    def get_credential_unreadable(self, obj) -> bool:
        return not (
            oidc_secrets.is_readable(obj.client_secret_encrypted, oidc_secrets.CLIENT_SECRET)
            and oidc_secrets.is_readable(obj.client_key_encrypted, oidc_secrets.CLIENT_KEY)
        )

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_redirect_uri(self, obj):
        base = CoreSettings.get_auth_settings().get("public_base_url", "")
        return redirect.redirect_uri(base, obj.slug) if base else None

    # ---- field validators ------------------------------------------------------------

    def validate_slug(self, value):
        if not SLUG_RE.match(value):
            raise serializers.ValidationError("must match [a-z0-9-] and be 1 to 40 characters")
        if value in RESERVED_SLUGS:
            raise serializers.ValidationError("is reserved")
        return value

    def validate_scopes(self, value):
        parts = value.split()
        if "openid" not in parts:
            raise serializers.ValidationError("must contain openid")
        return " ".join(parts)

    def validate_id_token_alg(self, value):
        if value not in ID_TOKEN_ALGS:
            raise serializers.ValidationError(
                "must be one of " + ", ".join(sorted(ID_TOKEN_ALGS))
            )
        return value

    def validate_claim_path(self, value):
        if value and not CLAIM_PATH_RE.match(value):
            raise serializers.ValidationError("must be a dotted path of non-empty keys")
        return value

    def validate_mappings(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("must be a list")
        if len(value) > MAX_MAPPINGS:
            raise serializers.ValidationError(f"at most {MAX_MAPPINGS} entries")
        seen = set()
        for entry in value:
            if not isinstance(entry, dict) or set(entry) != {"value", "user_level"}:
                raise serializers.ValidationError(
                    "each entry must be an object with value and user_level"
                )
            v, level = entry["value"], entry["user_level"]
            if not isinstance(v, str) or not v.strip() or len(v) > 256:
                raise serializers.ValidationError("value must be a non-blank string of at most 256 characters")
            if type(level) is not int or level not in LEVELS:
                raise serializers.ValidationError("user_level must be 0, 1 or 10")
            if v in seen:
                raise serializers.ValidationError("duplicate value")
            seen.add(v)
        return value

    # ---- object validation -----------------------------------------------------------

    def _current(self, attrs, name):
        if name in attrs:
            return attrs[name]
        if self.instance is not None:
            return getattr(self.instance, name)
        return _default(name)

    def validate(self, attrs):
        inst = self.instance
        kind = self._current(attrs, "kind")

        if kind == OIDCProvider.KIND_ENTRA:
            tenant = (self._current(attrs, "entra_tenant_id") or "").strip().lower()
            if not GUID_RE.match(tenant):
                # common, organizations, consumers and domain names all fail here.
                raise serializers.ValidationError(
                    {"entra_tenant_id": ["must be a tenant GUID"]}
                )
            attrs["entra_tenant_id"] = tenant
            attrs["issuer"] = ENTRA_ISSUER.format(tenant=tenant)
            attrs["client_assertion_alg"] = "PS256"
            if inst is None and "client_auth_method" not in attrs:
                attrs["client_auth_method"] = OIDCProvider.AUTH_SECRET_POST
            if self._current(attrs, "client_auth_method") not in ENTRA_METHODS:
                raise serializers.ValidationError(
                    {"client_auth_method": ["Entra supports private_key_jwt and client_secret_post"]}
                )
            if self._current(attrs, "allow_private_network"):
                raise serializers.ValidationError(
                    {"allow_private_network": ["is not available for the Entra preset"]}
                )
            if inst is None and not attrs.get("claim_path"):
                attrs["claim_path"] = "roles"
        else:
            issuer = self._current(attrs, "issuer")
            if not issuer:
                raise serializers.ValidationError({"issuer": ["This field is required."]})
            try:
                _validate_issuer(issuer)
            except serializers.ValidationError as exc:
                raise serializers.ValidationError({"issuer": exc.detail}) from None

        if inst is not None and inst.identities.exists():
            changed = {
                f: [IMMUTABLE_MESSAGE]
                for f in IMMUTABLE_WITH_IDENTITIES
                if f in attrs and attrs[f] != getattr(inst, f)
            }
            if changed:
                raise serializers.ValidationError(changed)

        if self._current(attrs, "enabled"):
            method = self._current(attrs, "client_auth_method")
            if method == OIDCProvider.AUTH_PRIVATE_KEY_JWT:
                has_credential = bool(
                    inst and inst.client_key_encrypted and inst.client_cert_pem
                )
            else:
                has_credential = "client_secret" in attrs or bool(
                    inst and inst.client_secret_encrypted
                )
            if not has_credential:
                raise CodedError("credential_missing")
        return attrs

    # ---- write side ------------------------------------------------------------------

    @staticmethod
    def _audit_names(names):
        return ["client_secret" if n == "client_secret_encrypted" else n for n in names]

    def create(self, validated_data):
        if settings.RUNTIME_SQLITE:
            # No provider means no SSO session, which the lockout guard needs (section 4.4).
            raise CodedError("requires_postgresql")
        data = dict(validated_data)
        secret = data.pop("client_secret", None)
        if secret is not None:
            data["client_secret_encrypted"] = oidc_secrets.encrypt(secret)
        with transaction.atomic():
            row = auth_settings.lock_row()
            base = auth_settings.row_values(row)["public_base_url"]
            redirect.ensure_entra_redirect_fits(base, [(data["slug"], data.get("kind", OIDCProvider.KIND_GENERIC))])
            instance = OIDCProvider.objects.create(**data)
            audit.record_config_change(
                audit.ACTION_PROVIDER_CREATED,
                user=self._actor(),
                provider=instance.slug,
                fields=self._audit_names(data),
            )
        return instance

    def update(self, instance, validated_data):
        data = dict(validated_data)
        secret = data.pop("client_secret", None)
        if secret is not None:
            data["client_secret_encrypted"] = oidc_secrets.encrypt(secret)
            # A new secret never inherits the old one's expiry date.
            data.setdefault("client_secret_expires_at", None)
        changes = {k: v for k, v in data.items() if getattr(instance, k) != v}

        with transaction.atomic():
            if {"slug", "kind"} & set(changes):
                row = auth_settings.lock_row()
                base = auth_settings.row_values(row)["public_base_url"]
                # Reload under the lock: the instance was loaded before it.
                current = OIDCProvider.objects.get(pk=instance.pk)
                redirect.ensure_entra_redirect_fits(
                    base,
                    [(changes.get("slug", current.slug), changes.get("kind", current.kind))],
                )
            OIDCProvider.update_columns(instance.pk, changes)
            if changes:
                audit.record_config_change(
                    audit.ACTION_PROVIDER_UPDATED,
                    user=self._actor(),
                    provider=changes.get("slug", instance.slug),
                    fields=self._audit_names(changes),
                )
        return OIDCProvider.objects.get(pk=instance.pk)

    def _actor(self):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return getattr(user, "username", None) or "unknown"


class OIDCIdentitySerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    provider_slug = serializers.CharField(source="provider.slug", read_only=True)

    class Meta:
        model = OIDCIdentity
        fields = [
            "id",
            "user",
            "username",
            "provider",
            "provider_slug",
            "issuer",
            "subject",
            "email_at_last_login",
            "display_name",
            "extra",
            "mapping_claim_path",
            "created",
            "last_login",
        ]
        read_only_fields = fields


class OIDCIdentityDetailSerializer(OIDCIdentitySerializer):
    """The admin detail view: the only place ``mapping_claim_values`` is returned."""

    class Meta(OIDCIdentitySerializer.Meta):
        fields = OIDCIdentitySerializer.Meta.fields + ["mapping_claim_values"]
        read_only_fields = fields


class AuthSettingsReadSerializer(serializers.Serializer):
    public_base_url = serializers.CharField(allow_blank=True)
    password_login_enabled = serializers.BooleanField()
    credential_warnings = serializers.ListField(
        child=serializers.DictField(), required=False
    )


class AuthSettingsWriteSerializer(serializers.Serializer):
    public_base_url = serializers.CharField(required=False, allow_blank=True, max_length=2048)
    password_login_enabled = serializers.BooleanField(required=False)

    def validate_public_base_url(self, value):
        return auth_settings.normalize_public_base_url(value)


class CertificateActivateSerializer(serializers.Serializer):
    thumbprint_sha256 = serializers.CharField(required=False, allow_blank=True)


class ProviderTestResultSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    redirect_uri = serializers.CharField(allow_null=True)
    problems = serializers.ListField(child=serializers.CharField())


# ---- the login flow (PR S2) -----------------------------------------------------------


class PublicProviderSerializer(serializers.Serializer):
    slug = serializers.CharField()
    display_name = serializers.CharField()


class PublicAuthConfigSerializer(serializers.Serializer):
    """``GET providers/``: never an issuer, client id or secret."""

    providers = PublicProviderSerializer(many=True)
    password_login_enabled = serializers.BooleanField()


class LinkStartRequestSerializer(serializers.Serializer):
    next = serializers.CharField(required=False, allow_blank=True, max_length=4096)


class LinkStartResponseSerializer(serializers.Serializer):
    authorize_url = serializers.CharField()


class ExchangeRequestSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=256, trim_whitespace=False)


class ExchangeResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    next = serializers.CharField()
    intent = serializers.ChoiceField(choices=["login", "link"])


class CodedErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
