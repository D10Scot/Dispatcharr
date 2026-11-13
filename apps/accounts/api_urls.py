from django.urls import path, include
from rest_framework.routers import DefaultRouter, SimpleRouter
from .oidc.api_views import (
    OIDCCallbackView,
    OIDCExchangeView,
    OIDCIdentityAdminViewSet,
    OIDCLinkStartView,
    OIDCProviderAdminViewSet,
    OIDCPublicProvidersView,
    OIDCSettingsView,
    OIDCStartView,
)
from .api_views import (
    AuthViewSet,
    UserViewSet,
    GroupViewSet,
    APIKeyViewSet,
    TokenObtainPairView,
    TokenRefreshView,
    list_permissions,
    initialize_superuser,
)
from rest_framework_simplejwt import views as jwt_views

app_name = "accounts"

# 🔹 Register ViewSets with a Router
router = DefaultRouter()
router.register(r"users", UserViewSet, basename="user")
router.register(r"groups", GroupViewSet, basename="group")
router.register(r"api-keys", APIKeyViewSet, basename="api-key")

# OIDC admin API (SSO spec 3.1).
oidc_router = SimpleRouter()
oidc_router.register(r"providers-admin", OIDCProviderAdminViewSet, basename="oidc-provider")
oidc_router.register(r"identities", OIDCIdentityAdminViewSet, basename="oidc-identity")

# 🔹 Custom Authentication Endpoints
auth_view = AuthViewSet.as_view({"post": "login"})

logout_view = AuthViewSet.as_view({"post": "logout"})

# 🔹 Define API URL patterns
urlpatterns = [
    # Authentication
    path("auth/login/", auth_view, name="user-login"),
    path("auth/logout/", logout_view, name="user-logout"),
    # Superuser API
    path("initialize-superuser/", initialize_superuser, name="initialize_superuser"),
    # Permissions API
    path("permissions/", list_permissions, name="list-permissions"),
    path("token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    # OIDC
    path("oidc/settings/", OIDCSettingsView.as_view(), name="oidc-settings"),
    # The login flow (SSO spec 3.1). Fixed segments come before the router and the slug
    # routes; a provider slug can never equal one of them (RESERVED_SLUGS).
    path("oidc/providers/", OIDCPublicProvidersView.as_view(), name="oidc-providers"),
    path("oidc/exchange/", OIDCExchangeView.as_view(), name="oidc-exchange"),
    path("oidc/", include(oidc_router.urls)),
    path("oidc/<slug:slug>/start/", OIDCStartView.as_view(), name="oidc-start"),
    path("oidc/<slug:slug>/link/start/", OIDCLinkStartView.as_view(), name="oidc-link-start"),
    path("oidc/<slug:slug>/callback/", OIDCCallbackView.as_view(), name="oidc-callback"),
]

# 🔹 Include ViewSet routes
urlpatterns += router.urls
