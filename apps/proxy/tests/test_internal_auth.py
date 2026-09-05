"""The two internal HMACs (Phase 1 D11) and the predicates that check them."""

from django.test import SimpleTestCase, override_settings

from apps.proxy import internal_auth


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
