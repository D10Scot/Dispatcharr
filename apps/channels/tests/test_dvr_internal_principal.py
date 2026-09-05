"""The DVR's internal principal, and the argv log that must not print it.

run_recording fetches /proxy/ts/stream/<uuid> through ffmpeg with no
credential of any kind. From Phase 1 PR 4 that fetch goes through nginx
(get_dvr_stream_base_url's AIO branch), and from PR 5 nginx authorizes it —
so without an internal principal every recording of a hidden, adult or
profile-gated channel would break silently.
"""

from django.test import SimpleTestCase, override_settings

from apps.channels.tasks import _dvr_build_ffmpeg_cmd, _dvr_redact_cmd
from apps.proxy.internal_auth import internal_principal_token


@override_settings(SECRET_KEY="dvr-test-secret")
class DvrInternalPrincipalTests(SimpleTestCase):
    def _cmd(self, token=None):
        return _dvr_build_ffmpeg_cmd(
            "http://127.0.0.1:9191/proxy/ts/stream/abc",
            7,
            "/data/recordings/x.m3u8",
            "/data/recordings/x%05d.ts",
            0,
            internal_token=token,
        )

    def test_the_header_precedes_the_input(self):
        cmd = self._cmd(internal_principal_token())
        self.assertIn("-headers", cmd)
        self.assertLess(cmd.index("-headers"), cmd.index("-i"))

    def test_the_header_value_ends_in_real_control_characters(self):
        # ffmpeg splits -headers on CR LF and does not unescape a literal
        # backslash-r backslash-n; a header built with escaped text is sent
        # as one malformed line and silently ignored.
        value = self._cmd(internal_principal_token())[
            self._cmd(internal_principal_token()).index("-headers") + 1
        ]
        self.assertTrue(value.endswith("\r\n"))
        self.assertNotIn("\\r\\n", value)
        self.assertTrue(value.startswith("X-Dispatcharr-Internal: "))

    def test_no_token_means_no_headers_argument(self):
        self.assertNotIn("-headers", self._cmd(None))

    def test_redaction_masks_the_token_and_keeps_the_rest(self):
        cmd = self._cmd(internal_principal_token())
        redacted = _dvr_redact_cmd(cmd)
        self.assertNotIn(internal_principal_token(), " ".join(redacted))
        self.assertIn("ffmpeg", redacted)
        self.assertIn("X-Dispatcharr-Internal: ***\r\n", redacted)

    def test_redaction_masks_credentials_in_the_input_url(self):
        cmd = _dvr_build_ffmpeg_cmd(
            "http://host.invalid/live/theuser/thepass/9.ts", 7, "a", "b", 0,
        )
        self.assertNotIn("thepass", " ".join(_dvr_redact_cmd(cmd)))

    def test_redaction_returns_a_list_the_caller_can_join(self):
        self.assertIsInstance(_dvr_redact_cmd(self._cmd(None)), list)
