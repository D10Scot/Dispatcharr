# apps/accounts/models.py
from django.db import models
from django.utils import timezone
from django.contrib.auth.models import AbstractUser, Permission, UserManager


class CustomUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('user_level', 10)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    objects = CustomUserManager()
    """
    Custom user model for Dispatcharr.
    Inherits from Django's AbstractUser to add additional fields if needed.
    """

    class UserLevel(models.IntegerChoices):
        STREAMER = 0, "Streamer"
        STANDARD = 1, "Standard User"
        ADMIN = 10, "Admin"

    avatar_config = models.JSONField(default=dict, blank=True, null=True)
    channel_profiles = models.ManyToManyField(
        "dispatcharr_channels.ChannelProfile",
        blank=True,
        related_name="users",
    )
    user_level = models.IntegerField(default=UserLevel.STREAMER)
    custom_properties = models.JSONField(default=dict, blank=True, null=True)
    api_key = models.CharField(max_length=200, blank=True, null=True, db_index=True)
    stream_limit = models.IntegerField(default=0)

    def __str__(self):
        return self.username

    def get_groups(self):
        """
        Returns the groups (roles) the user belongs to.
        """
        return self.groups.all()

    def get_permissions(self):
        """
        Returns the permissions assigned to the user and their groups.
        """
        return self.user_permissions.all() | Permission.objects.filter(group__user=self)


class OIDCProvider(models.Model):
    """An OpenID Connect identity provider (SSO spec section 5.1).

    Lives in its own table rather than in ``CoreSettings`` because every Standard user can
    read ``CoreSettings``. The client credential is stored as Fernet ciphertext
    (``apps/accounts/oidc/secrets.py``) and no serializer field returns it.

    Every write goes through a column-restricted ``QuerySet.update()`` that bumps ``version``
    with ``F("version") + 1`` when a security-relevant column changed. A bare ``save()`` would
    write every column back as the request loaded it.
    """

    KIND_GENERIC = "generic"
    KIND_ENTRA = "entra"
    KIND_CHOICES = [(KIND_GENERIC, "Generic OIDC"), (KIND_ENTRA, "Microsoft Entra ID")]

    AUTH_SECRET_POST = "client_secret_post"
    AUTH_SECRET_BASIC = "client_secret_basic"
    AUTH_PRIVATE_KEY_JWT = "private_key_jwt"
    CLIENT_AUTH_CHOICES = [
        (AUTH_SECRET_POST, "client_secret_post"),
        (AUTH_SECRET_BASIC, "client_secret_basic"),
        (AUTH_PRIVATE_KEY_JWT, "private_key_jwt"),
    ]

    ASSERTION_ALG_CHOICES = [("PS256", "PS256"), ("RS256", "RS256")]

    # Columns whose change bumps ``version`` (section 5.1). ``slug`` is part of the redirect
    # URI. ``display_name``, ``prompt_select_account``, ``client_secret_expires_at`` and the
    # pending pair are not.
    SECURITY_RELEVANT_FIELDS = frozenset(
        {
            "enabled",
            "slug",
            "issuer",
            "entra_tenant_id",
            "client_id",
            "allow_private_network",
            "client_secret_encrypted",
            "client_key_encrypted",
            "client_cert_pem",
            "client_auth_method",
            "client_assertion_alg",
            "scopes",
            "id_token_alg",
            "claim_path",
            "mappings",
        }
    )

    slug = models.CharField(max_length=40, unique=True)
    display_name = models.CharField(max_length=100)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=KIND_GENERIC)
    enabled = models.BooleanField(default=False)

    issuer = models.CharField(max_length=512)
    entra_tenant_id = models.CharField(max_length=36, blank=True, default="")
    client_id = models.CharField(max_length=255)
    allow_private_network = models.BooleanField(default=False)

    client_auth_method = models.CharField(
        max_length=24, choices=CLIENT_AUTH_CHOICES, default=AUTH_SECRET_BASIC
    )
    client_assertion_alg = models.CharField(
        max_length=8, choices=ASSERTION_ALG_CHOICES, default="PS256"
    )
    client_secret_encrypted = models.TextField(blank=True, default="")
    client_key_encrypted = models.TextField(blank=True, default="")
    client_cert_pem = models.TextField(blank=True, default="")
    pending_client_key_encrypted = models.TextField(blank=True, default="")
    pending_client_cert_pem = models.TextField(blank=True, default="")
    client_secret_expires_at = models.DateField(null=True, blank=True)

    scopes = models.CharField(max_length=512, default="openid profile email")
    id_token_alg = models.CharField(max_length=8, default="RS256")
    claim_path = models.CharField(max_length=255, blank=True, default="")
    mappings = models.JSONField(default=list, blank=True)
    prompt_select_account = models.BooleanField(default=False)

    version = models.PositiveIntegerField(default=1)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.slug

    @staticmethod
    def update_columns(pk, changes):
        """The one provider write: ``filter(pk=...).update(...)`` of exactly ``changes``.

        Bumps ``version`` atomically when a security-relevant column is among them. ``updated``
        is set by hand because ``update()`` bypasses ``auto_now``.
        """
        if not changes:
            return
        kwargs = dict(changes)
        if OIDCProvider.SECURITY_RELEVANT_FIELDS & set(kwargs):
            kwargs["version"] = models.F("version") + 1
        kwargs["updated"] = timezone.now()
        OIDCProvider.objects.filter(pk=pk).update(**kwargs)


class OIDCIdentity(models.Model):
    """A user's identity at a provider, keyed on (provider, issuer, subject) (section 4.1).

    Email is never used to match. ``mapping_claim_values`` is what D17 recomputes from on
    token refresh; it is never logged and only the admin ``identities/`` detail returns it.
    """

    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="oidc_identities"
    )
    provider = models.ForeignKey(
        OIDCProvider, on_delete=models.PROTECT, related_name="identities"
    )
    issuer = models.CharField(max_length=512)
    subject = models.CharField(max_length=255)
    email_at_last_login = models.CharField(max_length=254, blank=True, default="")
    display_name = models.CharField(max_length=255, blank=True, default="")
    extra = models.JSONField(default=dict, blank=True)
    mapping_claim_path = models.CharField(max_length=255, blank=True, default="")
    mapping_claim_values = models.JSONField(default=list, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "issuer", "subject"],
                name="oidc_identity_provider_issuer_subject_uniq",
            )
        ]

    def __str__(self):
        return f"{self.provider_id}:{self.pk}"
