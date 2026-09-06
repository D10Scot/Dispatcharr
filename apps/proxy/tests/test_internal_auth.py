"""The two internal HMACs (Phase 1 D11) and the predicates that check them."""

from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from apps.proxy import internal_auth
from apps.proxy.internal_auth import (
    META_INTERNAL_REQUEST,
    build_internal_request_header,
    request_is_internal_request,
)


class _Req:
    """A request stub: internal_auth only ever reads request.META."""

    def __init__(self, **meta):
        self.META = dict(meta)


@override_settings(SECRET_KEY="unit-test-secret")
class InternalAuthTests(SimpleTestCase):
    def test_tokens_are_hex_sha256_digests(self):
        for token in (internal_auth.relay_trust_token(),
                      internal_auth.internal_principal_token()):
            self.assertEqual(len(token), 64)
            self.assertTrue(all(c in "0123456789abcdef" for c in token))

    def test_the_two_contexts_produce_different_tokens(self):
        # The whole point of two context strings: a marker leaked through
        # the nginx config cannot be replayed as an internal principal.
        self.assertNotEqual(
            internal_auth.relay_trust_token(),
            internal_auth.internal_principal_token(),
        )

    def test_token_changes_with_the_secret_key(self):
        first = internal_auth.relay_trust_token()
        with override_settings(SECRET_KEY="a-different-secret"):
            self.assertNotEqual(first, internal_auth.relay_trust_token())

    def test_relay_trusted_accepts_the_marker_and_nothing_else(self):
        good = _Req(HTTP_X_DISPATCHARR_AUTHORIZED=internal_auth.relay_trust_token())
        self.assertTrue(internal_auth.request_is_relay_trusted(good))
        for value in ("", "1", "true", internal_auth.internal_principal_token()):
            with self.subTest(value=value):
                self.assertFalse(
                    internal_auth.request_is_relay_trusted(
                        _Req(HTTP_X_DISPATCHARR_AUTHORIZED=value)
                    )
                )

    def test_missing_header_is_not_trusted(self):
        self.assertFalse(internal_auth.request_is_relay_trusted(_Req()))
        self.assertFalse(internal_auth.request_is_internal(_Req()))

    def test_internal_accepts_only_the_internal_token(self):
        good = _Req(HTTP_X_DISPATCHARR_INTERNAL=internal_auth.internal_principal_token())
        self.assertTrue(internal_auth.request_is_internal(good))
        self.assertFalse(
            internal_auth.request_is_internal(
                _Req(HTTP_X_DISPATCHARR_INTERNAL=internal_auth.relay_trust_token())
            )
        )

    def test_a_non_string_header_value_is_rejected_not_raised(self):
        # uWSGI hands strings, but a direct in-process caller may not.
        self.assertFalse(
            internal_auth.request_is_relay_trusted(_Req(HTTP_X_DISPATCHARR_AUTHORIZED=1))
        )

    def test_a_non_ascii_header_value_is_rejected_not_raised(self):
        # WSGI/uWSGI hand header values to Django as latin-1 decoded str, so
        # a byte >= 0x80 can reach here from a client that hits uwsgi's
        # :5656 (published in dev/debug) or the relay's own :5657 directly
        # (any compose peer). hmac.compare_digest raises TypeError on
        # non-ASCII str — the predicate must return False, not raise.
        non_ascii = "é" + "a" * 63
        self.assertFalse(
            internal_auth.request_is_relay_trusted(
                _Req(HTTP_X_DISPATCHARR_AUTHORIZED=non_ascii)
            )
        )
        self.assertFalse(
            internal_auth.request_is_internal(
                _Req(HTTP_X_DISPATCHARR_INTERNAL=non_ascii)
            )
        )


class InternalHeaderRedactionTests(SimpleTestCase):
    def test_redact_headers_masks_both_internal_tokens(self):
        from dispatcharr.utils import redact_headers

        masked = redact_headers(
            {
                "X-Dispatcharr-Authorized": "deadbeef",
                "X-Dispatcharr-Internal": "cafebabe",
                "X-Relay-Channel": "a-channel-uuid",
            }
        )
        self.assertNotIn("deadbeef", str(masked))
        self.assertNotIn("cafebabe", str(masked))
        # X-Relay-Channel is a channel uuid, which the product already
        # treats as public-in-URL; it stays readable so a DEBUG log is
        # still worth reading.
        self.assertEqual(masked["X-Relay-Channel"], "a-channel-uuid")

    def test_redact_headers_masks_the_meta_spelling_too(self):
        from dispatcharr.utils import redact_headers

        masked = redact_headers({"HTTP_X_DISPATCHARR_INTERNAL": "cafebabe"})
        self.assertNotIn("cafebabe", str(masked))

    def test_the_original_uri_header_is_redacted_as_a_url(self):
        # It carries the XC path credentials of whatever is being
        # authorized, so it is masked like a URL rather than blanked.
        from dispatcharr.utils import redact_headers

        masked = redact_headers(
            {"HTTP_X_ORIGINAL_URI": "/live/theuser/thepass/9.ts?token=abc"}
        )
        rendered = str(masked)
        self.assertNotIn("thepass", rendered)
        self.assertIn("/live/", rendered)


class BoundTokenCoversTheQueryStringTests(TestCase):
    """PR 7: the bound token signs the full path, query string included.

    PR 6 signed request.path, which no caller of /api/relay/... could
    tell apart from the full path -- none of its three routes takes a
    query parameter. PR 7's GET /proxy/relay/channels does
    (?clients=all, which decides whether the response carries every
    client or the stats surface's first ten), and an unsigned query
    string is a parameter a replay inside the 120s window could flip.
    request.get_full_path() equals request.path when there is no query,
    so PR 6's already-shipped calls verify unchanged.
    """

    def test_a_signature_for_the_bare_path_does_not_clear_a_query_string(self):
        header = build_internal_request_header("GET", "/proxy/relay/channels", b"")
        request = RequestFactory().get(
            "/proxy/relay/channels",
            {"clients": "all"},
            **{META_INTERNAL_REQUEST: header},
        )
        self.assertFalse(request_is_internal_request(request))

    def test_a_signature_for_the_full_path_clears_it(self):
        header = build_internal_request_header(
            "GET", "/proxy/relay/channels?clients=all", b""
        )
        request = RequestFactory().get(
            "/proxy/relay/channels",
            {"clients": "all"},
            **{META_INTERNAL_REQUEST: header},
        )
        self.assertTrue(request_is_internal_request(request))

    def test_a_path_with_no_query_is_unchanged_from_pr_6(self):
        header = build_internal_request_header("POST", "/api/relay/events", b"{}")
        request = RequestFactory().post(
            "/api/relay/events",
            data=b"{}",
            content_type="application/json",
            **{META_INTERNAL_REQUEST: header},
        )
        self.assertTrue(request_is_internal_request(request))
