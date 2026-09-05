"""The gate on every internal control surface (Phase 1 D11, PR 6).

Not IsAdmin: IsAdmin needs a resolved User, which is exactly what these
hops must not need — the caller is a process in this deployment, not a
person. Two headers are required together. X-Dispatcharr-Internal is the
long-lived identity token PR 5 introduced and the DVR still uses;
X-Dispatcharr-Internal-Request binds one call to one method, path, body
and 120-second window, so a leaked identity token alone opens nothing
here (issue #181).
"""

from rest_framework.permissions import BasePermission

from apps.proxy.internal_auth import (
    request_is_internal,
    request_is_internal_request,
)


class IsInternalRelay(BasePermission):
    message = "Internal endpoint."

    def has_permission(self, request, view):
        http_request = getattr(request, "_request", request)
        return request_is_internal(http_request) and request_is_internal_request(
            http_request
        )
