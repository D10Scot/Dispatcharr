from django.contrib import admin
from django.contrib.auth.admin import UserAdmin, GroupAdmin
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.models import Group
from django.http import HttpResponseForbidden
from django.views.decorators.cache import never_cache

from . import password_login
from .models import User
from .throttling import enforce_login_rate_limit


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = (
        (None, {'fields': ('username', 'password', 'avatar_config', 'groups')}),
        ('Permissions', {'fields': ('is_staff', 'is_superuser', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )

# Unregister default Group admin and re-register it.
admin.site.unregister(Group)
admin.site.register(Group, GroupAdmin)

# Defense in depth: if /admin/login/ is reachable (e.g. nginx rule missed),
# share the same per-IP "login" throttle budget as JWT token obtain.
if not getattr(admin.site, "_dispatcharr_login_rate_limited", False):
    _original_admin_login = admin.site.login

    @never_cache
    @login_not_required
    def _rate_limited_admin_login(request, extra_context=None):
        if request.method == "POST":
            throttled = enforce_login_rate_limit(request)
            if throttled is not None:
                return throttled
            # SSO spec 5.3: the admin site is reached only by a password and a Django
            # session, so while password login is off its login refuses outright.
            if not password_login.allowed():
                return HttpResponseForbidden("Password sign-in is turned off.")
        return _original_admin_login(request, extra_context=extra_context)

    admin.site.login = _rate_limited_admin_login
    admin.site._dispatcharr_login_rate_limited = True

# SSO spec 5.3: a session made before password login was switched off would otherwise
# outlive the switch. While it is off (and break-glass is not on) no session has permission
# on the admin site; the admin then redirects to its login page. Enforced here, in Django,
# because three-segment admin paths escape nginx's /admin redirect. The stored value is read
# only for a request that would otherwise have permission, so an anonymous request runs no
# extra query.
if not getattr(admin.site, "_mino_password_gate", False):
    _original_has_permission = admin.site.has_permission

    def _password_gated_has_permission(request):
        return _original_has_permission(request) and password_login.allowed()

    admin.site.has_permission = _password_gated_has_permission
    admin.site._mino_password_gate = True

