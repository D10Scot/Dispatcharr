# core/admin.py

from django import forms
from django.contrib import admin, messages
from .models import UserAgent, StreamProfile, CoreSettings, AUTH_SETTINGS_KEY

@admin.register(UserAgent)
class UserAgentAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "user_agent",
        "description",
        "is_active",
        "created_at",
        "updated_at",
    )
    search_fields = ("name", "user_agent", "description")
    list_filter = ("is_active",)
    readonly_fields = ("created_at", "updated_at")

@admin.register(StreamProfile)
class StreamProfileAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "command",
        "is_active",
        "user_agent",
    )
    search_fields = ("name", "command", "user_agent")
    list_filter = ("is_active",)

class CoreSettingsAdminForm(forms.ModelForm):
    class Meta:
        model = CoreSettings
        fields = "__all__"

    def clean_key(self):
        key = self.cleaned_data["key"]
        # Covers adding the row and renaming another row into it.
        if key == AUTH_SETTINGS_KEY and (
            self.instance.pk is None or self.instance.key != AUTH_SETTINGS_KEY
        ):
            raise forms.ValidationError(
                "auth_settings is edited on the Single sign-on settings page."
            )
        return key


@admin.register(CoreSettings)
class CoreSettingsAdmin(admin.ModelAdmin):
    """
    Because CoreSettings is typically a single 'singleton' row,
    you can either allow multiple or restrict it. For now, we
    just list and allow editing of any instance.

    ``auth_settings`` is the exception (SSO spec 5.1): it holds the password-login toggle,
    so it is view-only here whatever nginx does with ``/admin``.
    """
    form = CoreSettingsAdminForm
    list_display = (
        "key",
        "value",
    )

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.key == AUTH_SETTINGS_KEY:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.key == AUTH_SETTINGS_KEY:
            return False
        return super().has_delete_permission(request, obj)

    def delete_queryset(self, request, queryset):
        if queryset.filter(key=AUTH_SETTINGS_KEY).exists():
            self.message_user(
                request,
                "auth_settings cannot be deleted; nothing was deleted.",
                level=messages.ERROR,
            )
            return
        super().delete_queryset(request, queryset)
