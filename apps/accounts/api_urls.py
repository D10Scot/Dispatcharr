from django.urls import path, include
from rest_framework.routers import DefaultRouter, SimpleRouter
from .oidc.api_views import (
    OIDCIdentityAdminViewSet,
    OIDCProviderAdminViewSet,
    OIDCSettingsView,
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

# OIDC admin API (SSO spec 3.1). The login-flow routes arrive with PR S2.
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
    path("oidc/", include(oidc_router.urls)),
]

# 🔹 Include ViewSet routes
urlpatterns += router.urls
