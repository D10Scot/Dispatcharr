"""OIDC API: the admin side (SSO spec 3.1, 5.1, 5.2) and the login flow (3.1-3.3a).

The flow endpoints (``providers/``, ``start``, ``link/start``, ``callback``, ``exchange``) are
thin: ``flow.py`` holds the protocol. Nothing here establishes a Django session.
"""

import hmac
import logging
import re

from django.db import transaction
from django.db.models import ProtectedError
from django.http import HttpResponse, HttpResponseRedirect
from urllib.parse import urlencode
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import OIDCIdentity, OIDCProvider
from apps.accounts.permissions import Authenticated, IsAdmin, IsStandardUser
from apps.accounts.throttling import OIDCRateThrottle
from core.models import CoreSettings

from . import audit, auth_settings, certificates, discovery, expiry, flow, redirect
from . import secrets as oidc_secrets
from .errors import CodedError
from .serializers import (
    AuthSettingsReadSerializer,
    AuthSettingsWriteSerializer,
    CertificateActivateSerializer,
    CodedErrorSerializer,
    ExchangeRequestSerializer,
    ExchangeResponseSerializer,
    LinkStartRequestSerializer,
    LinkStartResponseSerializer,
    PublicAuthConfigSerializer,
    OIDCIdentityDetailSerializer,
    OIDCIdentitySerializer,
    OIDCProviderSerializer,
    ProviderTestResultSerializer,
)

logger = logging.getLogger(__name__)


_THUMBPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


def _actor(request):
    return getattr(request.user, "username", None) or "unknown"


class OIDCProviderAdminViewSet(viewsets.ModelViewSet):
    """Provider CRUD, the discovery/JWKS ``test`` action and the certificate actions."""

    queryset = OIDCProvider.objects.all()
    serializer_class = OIDCProviderSerializer
    permission_classes = [IsAdmin]
    pagination_class = None
    # Spec 3.1 lists GET, POST, PATCH and DELETE; there is no PUT.
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        slug = instance.slug
        try:
            with transaction.atomic():
                instance.delete()
                audit.record_config_change(
                    audit.ACTION_PROVIDER_DELETED,
                    user=_actor(request),
                    provider=slug,
                    fields=[],
                )
        except ProtectedError:
            raise CodedError("provider_has_identities", status_code=status.HTTP_409_CONFLICT)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=None,
        responses={200: ProviderTestResultSerializer},
        description=(
            "Fetch and validate discovery and JWKS fresh and report fixed problem codes. "
            "Writes nothing."
        ),
    )
    @action(detail=True, methods=["post"], url_path="test")
    def test(self, request, pk=None):
        provider = self.get_object()
        problems = []
        serializer = OIDCProviderSerializer(provider)
        if serializer.data["credential_unreadable"]:
            problems.append("credential_unreadable")
        base = CoreSettings.get_auth_settings().get("public_base_url", "")
        if not base:
            problems.append("public_base_url_unset")
        else:
            try:
                redirect.ensure_entra_redirect_fits(base, [(provider.slug, provider.kind)])
            except CodedError:
                problems.append("redirect_uri_too_long")
        problems.extend(discovery.run_test(provider))
        result = {
            "ok": not problems,
            "redirect_uri": redirect.redirect_uri(base, provider.slug) if base else None,
            "problems": problems,
        }
        return Response(result)

    @extend_schema(
        methods=["GET"],
        parameters=[OpenApiParameter("slot", str, enum=["active", "pending"])],
        responses={(200, "application/x-pem-file"): bytes},
        description="Download a slot's public certificate as PEM, for upload to the IdP.",
    )
    @extend_schema(
        methods=["POST"],
        request=None,
        responses={200: {"type": "object"}},
        description=(
            "Generate a pending key pair and self-signed certificate. Answers the "
            "certificate, never the key. The active pair is untouched."
        ),
    )
    @action(detail=True, methods=["get", "post"], url_path="certificate")
    def certificate(self, request, pk=None):
        if request.method == "GET":
            return self._download_certificate(request)
        return self._generate_certificate(request)

    def _download_certificate(self, request):
        provider = self.get_object()
        slot = request.query_params.get("slot", "active")
        if slot not in ("active", "pending"):
            raise CodedError("invalid_slot")
        pem = provider.client_cert_pem if slot == "active" else provider.pending_client_cert_pem
        if not pem:
            raise CodedError("certificate_not_found", status_code=status.HTTP_404_NOT_FOUND)
        response = HttpResponse(pem, content_type="application/x-pem-file")
        response["Content-Disposition"] = (
            f'attachment; filename="mino-oidc-{provider.slug}-{slot}.pem"'
        )
        response["Cache-Control"] = "no-store"
        return response

    def _generate_certificate(self, request):
        # Load first (404 and permission), generate the key outside any lock (RSA keygen is
        # slow), then re-read the row under the lock and write only the pending columns.
        loaded = self.get_object()
        key_pem, cert_pem = certificates.generate_pair(loaded.slug)
        with transaction.atomic():
            provider = OIDCProvider.objects.select_for_update().filter(pk=loaded.pk).first()
            if provider is None:
                raise CodedError("not_found", status_code=status.HTTP_404_NOT_FOUND)
            OIDCProvider.update_columns(
                provider.pk,
                {
                    "pending_client_key_encrypted": oidc_secrets.encrypt(
                        key_pem, oidc_secrets.CLIENT_KEY
                    ),
                    "pending_client_cert_pem": cert_pem,
                },
            )
            audit.record_config_change(
                audit.ACTION_PROVIDER_UPDATED,
                user=_actor(request),
                provider=provider.slug,
                fields=["pending_client_certificate"],
            )
        return Response(
            {"slot": "pending", "certificate_pem": cert_pem, **certificates.describe(cert_pem)}
        )

    @extend_schema(
        request=CertificateActivateSerializer,
        responses={200: OIDCProviderSerializer},
        description=(
            "Promote the pending certificate to active if it is still the one named by "
            "thumbprint_sha256; 409 pending_certificate_changed otherwise."
        ),
    )
    @action(detail=True, methods=["post"], url_path="certificate/activate")
    def certificate_activate(self, request, pk=None):
        body = CertificateActivateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        named = (body.validated_data.get("thumbprint_sha256") or "").strip().lower()
        # A non-numeric id is a 404 like every other route (get_object), before any lock.
        loaded = self.get_object()
        with transaction.atomic():
            provider = OIDCProvider.objects.select_for_update().filter(pk=loaded.pk).first()
            if provider is None:
                raise CodedError("not_found", status_code=status.HTTP_404_NOT_FOUND)
            pending = ""
            if provider.pending_client_cert_pem and provider.pending_client_key_encrypted:
                pending = certificates.thumbprint_sha256(provider.pending_client_cert_pem)
            # Anything that is not 64 lowercase hex characters cannot name a certificate;
            # it is the same refusal as a different thumbprint (and compare_digest would
            # raise TypeError on non-ASCII text).
            if (
                not _THUMBPRINT_RE.match(named)
                or not pending
                or not hmac.compare_digest(named, pending)
            ):
                raise CodedError(
                    "pending_certificate_changed", status_code=status.HTTP_409_CONFLICT
                )
            OIDCProvider.update_columns(
                provider.pk,
                {
                    "client_key_encrypted": provider.pending_client_key_encrypted,
                    "client_cert_pem": provider.pending_client_cert_pem,
                    "pending_client_key_encrypted": "",
                    "pending_client_cert_pem": "",
                    "client_auth_method": OIDCProvider.AUTH_PRIVATE_KEY_JWT,
                },
            )
            audit.record_config_change(
                audit.ACTION_PROVIDER_UPDATED,
                user=_actor(request),
                provider=provider.slug,
                fields=["client_certificate", "client_auth_method"],
            )
        refreshed = OIDCProvider.objects.get(pk=loaded.pk)
        return Response(OIDCProviderSerializer(refreshed, context={"request": request}).data)


class OIDCIdentityAdminViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """List (optionally ``?user=<id>``), inspect and unlink SSO identities."""

    queryset = OIDCIdentity.objects.select_related("user", "provider")
    permission_classes = [IsAdmin]
    pagination_class = None

    def get_serializer_class(self):
        if self.action == "retrieve":
            return OIDCIdentityDetailSerializer
        return OIDCIdentitySerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.query_params.get("user")
        if user is not None:
            if not user.isdigit():
                raise CodedError("invalid_user")
            qs = qs.filter(user_id=int(user))
        return qs

    def perform_destroy(self, instance):
        username = instance.user.username
        slug = instance.provider.slug
        admin = _actor(self.request)

        def _event():
            from core.utils import log_system_event

            log_system_event(
                "login_success", user=username, method="oidc_unlink", provider=slug, admin=admin
            )

        with transaction.atomic():
            instance.delete()
            transaction.on_commit(_event)


class OIDCSettingsView(APIView):
    """``auth_settings``: ``public_base_url`` and the (not yet switchable) password toggle."""

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsStandardUser()]
        return [IsAdmin()]

    def _payload(self, request, values):
        payload = {
            "public_base_url": values["public_base_url"],
            "password_login_enabled": values["password_login_enabled"],
        }
        if request.user.user_level >= 10:
            payload["credential_warnings"] = expiry.credential_warnings()
        return payload

    @extend_schema(responses={200: AuthSettingsReadSerializer})
    def get(self, request):
        return Response(self._payload(request, CoreSettings.get_auth_settings()))

    @extend_schema(request=AuthSettingsWriteSerializer, responses={200: AuthSettingsReadSerializer})
    def patch(self, request):
        body = AuthSettingsWriteSerializer(data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        if data.get("password_login_enabled") is False:
            # The guard (5.5), its enforcement (5.3) and break-glass (5.6) land together in
            # PR S4. Until then no state can record "passwords off" while passwords work.
            raise CodedError("password_toggle_unavailable", status_code=status.HTTP_409_CONFLICT)

        with transaction.atomic():
            row = auth_settings.lock_row()
            values = auth_settings.row_values(row)
            changed = []
            new_base = data.get("public_base_url")
            if new_base is not None and new_base != values["public_base_url"]:
                pairs = list(OIDCProvider.objects.values_list("slug", "kind"))
                redirect.ensure_entra_redirect_fits(new_base, pairs)
                values["public_base_url"] = new_base
                changed.append("public_base_url")
            enabled = data.get("password_login_enabled")
            if enabled is not None and enabled != values["password_login_enabled"]:
                values["password_login_enabled"] = enabled
                changed.append("password_login_enabled")
            if changed:
                row.value = values
                row.save(update_fields=["value"])
                audit.record_config_change(
                    audit.ACTION_SETTINGS_UPDATED,
                    user=_actor(request),
                    provider=None,
                    fields=changed,
                )
        return Response(self._payload(request, values))


# ---- the login flow (PR S2) ------------------------------------------------------------


class UINetworkAllowed(BasePermission):
    """The UI network ACL for the unauthenticated flow endpoints."""

    def has_permission(self, request, view):
        from dispatcharr.utils import network_access_allowed

        return network_access_allowed(request, "UI")


class _ThrottleUnavailable(Exception):
    """The ``oidc`` throttle could not reach its cache: Redis is down."""


class _FlowView(APIView):
    """Base for start, link/start, callback and exchange: ACL, ``oidc`` throttle, headers.

    No authenticator runs (``link/start`` overrides that): a stale bearer header must not
    turn a login into a 401.
    """

    authentication_classes = []
    permission_classes = [UINetworkAllowed]
    throttle_classes = [OIDCRateThrottle]

    def check_throttles(self, request):
        # The throttle's cache is the Redis the transaction store needs too, so with it down
        # no login can complete: answer sso_unavailable rather than a 500.
        try:
            super().check_throttles(request)
        except discovery.CACHE_ERRORS as exc:
            logger.warning("OIDC throttle cache unavailable: %s", type(exc).__name__)
            raise _ThrottleUnavailable() from None

    def handle_exception(self, exc):
        if isinstance(exc, _ThrottleUnavailable):
            # GET start and callback are browser navigations: send them to the login page.
            base = flow.public_base_url() if self.request.method == "GET" else ""
            if base:
                return HttpResponseRedirect(
                    f"{base}/login?{urlencode({'sso_error': 'sso_unavailable'})}"
                )
            return Response({"code": "sso_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return super().handle_exception(exc)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        for name, value in flow.NO_STORE_HEADERS.items():
            response[name] = value
        return response


def _provider_and_base(slug):
    provider = flow.enabled_provider(slug)
    if provider is None:
        raise CodedError("not_found", status_code=status.HTTP_404_NOT_FOUND)
    base = flow.public_base_url()
    if not base:
        raise CodedError("sso_not_configured", status_code=status.HTTP_409_CONFLICT)
    return provider, base


class OIDCPublicProvidersView(APIView):
    """``GET providers/``: the login page's configuration. No issuer, client id or secret."""

    authentication_classes = []
    permission_classes = [UINetworkAllowed]

    @extend_schema(responses={200: PublicAuthConfigSerializer})
    def get(self, request):
        providers = list(
            OIDCProvider.objects.filter(enabled=True).order_by("id").values("slug", "display_name")
        )
        payload = {
            "providers": providers,
            "password_login_enabled": bool(
                CoreSettings.get_auth_settings().get("password_login_enabled", True)
            ),
        }
        return Response(PublicAuthConfigSerializer(payload).data)


class OIDCStartView(_FlowView):
    """``GET <slug>/start/?next=``: a LOGIN transaction, answered with a 302 to the IdP.

    It takes no ``intent`` parameter: a GET start can never link.
    """

    @extend_schema(
        parameters=[OpenApiParameter("next", str, required=False)],
        responses={302: None, 404: CodedErrorSerializer, 409: CodedErrorSerializer},
    )
    def get(self, request, slug):
        provider, base = _provider_and_base(slug)
        try:
            started = flow.begin(
                request,
                provider,
                base,
                intent=flow.INTENT_LOGIN,
                link_user_id=None,
                next_value=request.query_params.get("next"),
            )
            return started.apply_cookies(HttpResponseRedirect(started.authorize_url))
        except (discovery.DiscoveryError, flow.FlowError) as exc:
            code = "provider_unavailable" if isinstance(exc, discovery.DiscoveryError) else exc.code
            flow.login_failed(request, code, provider.slug)
        except Exception as exc:  # noqa: BLE001 - the last resort; see flow.log_unexpected
            flow.log_unexpected("start", exc)
            code = "provider_unavailable"
            flow.login_failed(request, code, provider.slug, unexpected=flow.UNEXPECTED_MARKER)
        return HttpResponseRedirect(f"{base}/login?{urlencode({'sso_error': code})}")


class OIDCLinkStartView(_FlowView):
    """``POST <slug>/link/start/``: a LINK transaction for the authenticated caller.

    The binding cookie is set on this same-origin response, so the link exists only in the
    browser of the user who asked for it. ``link_user_id`` is the caller, never a parameter.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [Authenticated]

    @extend_schema(
        request=LinkStartRequestSerializer,
        responses={
            200: LinkStartResponseSerializer,
            404: CodedErrorSerializer,
            409: CodedErrorSerializer,
            502: CodedErrorSerializer,
        },
    )
    def post(self, request, slug):
        body = LinkStartRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        provider, base = _provider_and_base(slug)
        try:
            started = flow.begin(
                request,
                provider,
                base,
                intent=flow.INTENT_LINK,
                link_user_id=request.user.pk,
                next_value=body.validated_data.get("next"),
            )
            response = Response(
                LinkStartResponseSerializer({"authorize_url": started.authorize_url}).data
            )
            return started.apply_cookies(response)
        except discovery.DiscoveryError:
            raise CodedError("provider_unavailable", status_code=status.HTTP_502_BAD_GATEWAY)
        except flow.FlowError as exc:
            raise CodedError(exc.code, status_code=exc.status)
        except Exception as exc:  # noqa: BLE001 - the last resort; see flow.log_unexpected
            flow.log_unexpected("link_start", exc)
            raise CodedError("provider_unavailable", status_code=status.HTTP_502_BAD_GATEWAY) from None


class OIDCCallbackView(_FlowView):
    """``GET <slug>/callback/``: the redirect URI. Always a 302 once the provider resolves."""

    @extend_schema(responses={302: None, 404: CodedErrorSerializer, 409: CodedErrorSerializer})
    def get(self, request, slug):
        provider, base = _provider_and_base(slug)
        return flow.callback(request, provider, base)


class OIDCExchangeView(_FlowView):
    """``POST exchange/ {code}``: redeem the one-time handoff for the token pair."""

    @extend_schema(
        request=ExchangeRequestSerializer,
        responses={200: ExchangeResponseSerializer, 400: CodedErrorSerializer},
    )
    def post(self, request):
        body = ExchangeRequestSerializer(data=request.data)
        if not body.is_valid():
            return Response({"code": "handoff_invalid"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            payload, cookie_name, base = flow.exchange(request, body.validated_data["code"])
        except flow.FlowError as exc:
            response = Response({"code": exc.code}, status=exc.status)
            cookie_name = getattr(exc, "cookie_name", None)
            if cookie_name:
                flow.delete_binding_cookie(response, cookie_name, exc.base_url)
            return response
        response = Response(ExchangeResponseSerializer(payload).data)
        response["Pragma"] = "no-cache"
        if cookie_name:
            flow.delete_binding_cookie(response, cookie_name, base)
        return response
