"""The gate on /api/relay/... — both internal headers, never a principal.

Phase 1 PR 6. The static X-Dispatcharr-Internal token says "part of this
deployment" and is long-lived; issue #181 asks for a bound form before it
becomes the sole gate on a control API. X-Dispatcharr-Internal-Request adds
the binding: method, path, body and a 120s window.
"""

import time

from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.proxy.internal_auth import (
    INTERNAL_REQUEST_WINDOW_SECONDS,
    internal_principal_token,
    internal_request_token,
    request_is_internal_request,
)
from apps.proxy.permissions import IsInternalRelay

BODY = b'{"reason": "failover"}'
PATH = "/api/relay/channels/abc/next-source"


def _request(factory, *, static=True, bound=True, timestamp=None, path=PATH, body=BODY):
    headers = {}
    if static:
        headers["HTTP_X_DISPATCHARR_INTERNAL"] = internal_principal_token()
    if bound:
        ts = int(time.time()) if timestamp is None else timestamp
        headers["HTTP_X_DISPATCHARR_INTERNAL_REQUEST"] = (
            f"v1.{ts}." + internal_request_token("POST", path, body, ts)
        )
    return factory.post(
        path, data=body, content_type="application/json", **headers
    )


class InternalRequestTokenTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_a_correctly_signed_request_is_accepted(self):
        self.assertTrue(request_is_internal_request(_request(self.factory)))

    def test_the_signature_is_bound_to_the_path(self):
        request = _request(self.factory, path=PATH)
        request.path = "/api/relay/events"
        self.assertFalse(request_is_internal_request(request))

    def test_the_signature_is_bound_to_the_body(self):
        request = _request(self.factory, body=b'{"reason": "failover"}')
        request._body = b'{"reason": "tamper"}'
        self.assertFalse(request_is_internal_request(request))

    def test_an_expired_timestamp_is_refused(self):
        stale = int(time.time()) - INTERNAL_REQUEST_WINDOW_SECONDS - 5
        self.assertFalse(
            request_is_internal_request(_request(self.factory, timestamp=stale))
        )

    def test_a_future_timestamp_beyond_the_window_is_refused(self):
        ahead = int(time.time()) + INTERNAL_REQUEST_WINDOW_SECONDS + 5
        self.assertFalse(
            request_is_internal_request(_request(self.factory, timestamp=ahead))
        )

    def test_a_malformed_header_is_refused_rather_than_raising(self):
        request = self.factory.post(PATH, data=BODY, content_type="application/json")
        for value in ("", "v1", "v1.notanint.abc", "v2.1.abc", "\udcff"):
            request.META["HTTP_X_DISPATCHARR_INTERNAL_REQUEST"] = value
            self.assertFalse(request_is_internal_request(request))

    def test_a_token_from_another_secret_is_refused(self):
        # Signed under a different SECRET_KEY, verified under this test's
        # actual one -- proving a token from a deployment with a different
        # key is refused, not merely an arbitrary wrong string. The token
        # is computed INSIDE the override (so it is genuinely signed under
        # "a-different-secret-entirely") and verified OUTSIDE it (so
        # request_is_internal_request checks it against the real SECRET_KEY
        # this test runs under).
        request = self.factory.post(PATH, data=BODY, content_type="application/json")
        ts = int(time.time())
        with override_settings(SECRET_KEY="a-different-secret-entirely"):
            other = internal_request_token("POST", PATH, BODY, ts)
        request.META["HTTP_X_DISPATCHARR_INTERNAL_REQUEST"] = f"v1.{ts}.{other}"
        self.assertFalse(request_is_internal_request(request))

    def test_a_token_signed_for_a_different_method_is_refused(self):
        # Bound to method as well as path/body/timestamp: a token signed
        # for POST must not validate a PUT carrying the same path, body
        # and timestamp.
        signed_as_post = _request(self.factory)
        headers = {
            k: v for k, v in signed_as_post.META.items() if k.startswith("HTTP_")
        }
        sent_as_put = self.factory.generic(
            "PUT", PATH, data=BODY, content_type="application/json", **headers
        )
        self.assertFalse(request_is_internal_request(sent_as_put))


class IsInternalRelayTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.permission = IsInternalRelay()

    def test_both_headers_are_required(self):
        self.assertTrue(
            self.permission.has_permission(_request(self.factory), None)
        )

    def test_the_static_token_alone_is_not_enough(self):
        self.assertFalse(
            self.permission.has_permission(
                _request(self.factory, bound=False), None
            )
        )

    def test_the_bound_token_alone_is_not_enough(self):
        self.assertFalse(
            self.permission.has_permission(
                _request(self.factory, static=False), None
            )
        )

    def test_an_authenticated_admin_without_the_headers_is_refused(self):
        request = self.factory.post(PATH, data=BODY, content_type="application/json")

        class _Admin:
            is_authenticated = True
            user_level = 10

        request.user = _Admin()
        self.assertFalse(self.permission.has_permission(request, None))
