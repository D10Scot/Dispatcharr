"""Property-based tests for detect_stream_type (apps/proxy/live_proxy/utils.py).

detect_stream_type classifies an upstream URL as hls/rtsp/udp/ts so
StreamManager can pick the right connection strategy. It consumes
provider-controlled URLs, so the properties state what the implementation
promises:

* totality: arbitrary strings (and None/empty) never raise and always return
  one of the five documented classifications;
* scheme dominance: udp:// always classifies 'udp', rtsp:// and rtp:// always
  classify 'rtsp', regardless of any HLS-looking suffix in the rest of the
  URL (the scheme checks run before the HLS heuristics);
* case insensitivity: classification does not depend on URL casing;
* a bare URL with no HLS indicators and no special scheme is 'ts';
* idempotence is trivial (pure function) but classification of '.m3u8'-
  terminated paths is always 'hls' even with query strings.

Runs without Redis or the database (SimpleTestCase, pure function).
"""

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.proxy.live_proxy.utils import detect_stream_type

# CI-deterministic profile — see test_property_find_ts_sync.py for rationale.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

CLASSIFICATIONS = {"hls", "rtsp", "udp", "ts", "unknown"}

# URL-ish text: scheme-looking prefixes, path separators, HLS markers, dots.
url_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        blacklist_characters="\x00",
    ),
    max_size=200,
)


class DetectStreamTypeProperties(SimpleTestCase):
    @given(url=st.one_of(st.none(), st.text(max_size=200), url_text))
    def test_never_raises_and_returns_a_documented_value(self, url):
        result = detect_stream_type(url)
        self.assertIn(result, CLASSIFICATIONS)

    @given(rest=url_text)
    def test_udp_scheme_dominates(self, rest):
        self.assertEqual(detect_stream_type(f"udp://{rest}"), "udp")

    @given(rest=url_text, scheme=st.sampled_from(["rtsp://", "rtp://"]))
    def test_rtsp_rtp_schemes_dominate(self, rest, scheme):
        self.assertEqual(detect_stream_type(f"{scheme}{rest}"), "rtsp")

    @given(rest=url_text)
    def test_scheme_checks_are_case_insensitive(self, rest):
        self.assertEqual(detect_stream_type(f"UDP://{rest}"), "udp")
        self.assertEqual(detect_stream_type(f"RtSp://{rest}"), "rtsp")

    @given(path=url_text)
    def test_m3u8_suffix_is_always_hls(self, path):
        # Any path ending in .m3u8 (query string or not) must classify hls,
        # provided no earlier scheme rule fired.
        url = f"http://host/{path}/index.m3u8"
        self.assertEqual(detect_stream_type(url), "hls")
        self.assertEqual(
            detect_stream_type(f"http://host/{path}/index.m3u8?token=abc"), "hls"
        )

    @given(url=url_text)
    def test_casing_does_not_change_classification(self, url):
        self.assertEqual(detect_stream_type(url), detect_stream_type(url.upper()))
        self.assertEqual(detect_stream_type(url), detect_stream_type(url.lower()))

    @given(
        path=st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N"),
                blacklist_characters="\x00",
            ),
            max_size=60,
        ).filter(lambda p: not any(m in p.lower() for m in ("m3u", "playlist", "manifest", "master")))
    )
    def test_plain_paths_classify_ts(self, path):
        """A plain http URL with no HLS indicators and no special scheme."""
        self.assertEqual(detect_stream_type(f"http://host/{path}/stream"), "ts")
