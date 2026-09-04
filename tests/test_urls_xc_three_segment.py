"""dispatcharr/urls.py must route a three-segment path to the Xtream stream_xc
view only when the final segment is a plausible channel id (digits, optionally
with an extension) — never for an arbitrary SPA-shaped deep link of the same
three-segment, no-trailing-slash shape. See docs/superpowers/specs/
2026-09-04-phase1-process-split-design.md's "three-segment regex trap" (D7)
and this plan's Task 1 for why: stream_xc's get_object_or_404(User, ...) is
the first statement in the view, and Http404 never escapes DRF's own
exception_handler to reach Django's catch-all, so the URL pattern itself is
the only lever outside apps/proxy/live_proxy/.
"""

from django.test import SimpleTestCase
from django.urls import resolve

from dispatcharr.utils import redact_url


class XcThreeSegmentRoutingTests(SimpleTestCase):
    def test_numeric_channel_id_still_resolves_to_stream_xc(self):
        match = resolve("/user/pass/12345")
        self.assertEqual(match.url_name, "xc_stream_endpoint")
        self.assertEqual(match.kwargs["channel_id"], "12345")

    def test_numeric_channel_id_with_extension_still_resolves_to_stream_xc(self):
        match = resolve("/user/pass/12345.ts")
        self.assertEqual(match.url_name, "xc_stream_endpoint")
        self.assertEqual(match.kwargs["channel_id"], "12345.ts")

    def test_live_prefixed_numeric_channel_id_still_resolves_to_stream_xc(self):
        match = resolve("/live/user/pass/12345")
        self.assertEqual(match.url_name, "xc_live_stream_endpoint")
        self.assertEqual(match.kwargs["channel_id"], "12345")

    def test_non_numeric_three_segment_path_falls_to_spa_catch_all(self):
        match = resolve("/settings/example/page")
        self.assertIsNone(match.url_name)
        self.assertEqual(match.kwargs, {"unused_path": "settings/example/page"})

    def test_resolver_and_redact_url_agree_on_credential_shape(self):
        # Both consumers build their regex from the same
        # dispatcharr.utils.XC_STREAM_ID_PATTERN (Step 2), so a path either
        # both treat as an XC credential or neither does.
        spa_path = "/settings/example/page"
        xc_path = "/user/pass/12345.ts"

        self.assertIsNone(resolve(spa_path).url_name)
        self.assertEqual(redact_url(spa_path), spa_path)  # nothing to mask

        match = resolve(xc_path)
        self.assertEqual(match.url_name, "xc_stream_endpoint")
        self.assertNotEqual(redact_url(xc_path), xc_path)  # username/password masked
