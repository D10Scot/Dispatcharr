from django.test import SimpleTestCase

from core.models import REDIRECT_PROFILE_NAME, StreamProfile


class StreamProfileBuildCommandTests(SimpleTestCase):
    def _profile(self, parameters):
        return StreamProfile(
            name="Test Profile",
            command="ffmpeg",
            parameters=parameters,
            locked=False,
        )

    def test_substitutes_all_tokens(self):
        profile = self._profile(
            '-i {streamUrl} -user_agent {userAgent} -metadata channel={channelId}'
        )
        cmd = profile.build_command(
            "http://example.com/stream.ts", "Mozilla/5.0", channel_id=42
        )
        self.assertEqual(
            cmd,
            [
                "ffmpeg",
                "-i",
                "http://example.com/stream.ts",
                "-user_agent",
                "Mozilla/5.0",
                "-metadata",
                "channel=42",
            ],
        )

    def test_channel_id_defaults_to_empty_string(self):
        profile = self._profile('-metadata channel={channelId}')
        cmd = profile.build_command("http://example.com/stream.ts", "Mozilla/5.0")
        self.assertEqual(cmd, ["ffmpeg", "-metadata", "channel="])

    def test_no_channel_id_placeholder_unaffected(self):
        profile = self._profile('-i {streamUrl}')
        cmd = profile.build_command(
            "http://example.com/stream.ts", "Mozilla/5.0", channel_id=7
        )
        self.assertEqual(cmd, ["ffmpeg", "-i", "http://example.com/stream.ts"])

    def test_redirect_profile_builds_no_command(self):
        # Belt-and-braces (Phase 1 PR 5 re-review): callers are expected to
        # treat Redirect like Proxy and never reach build_command for it,
        # but the locked Redirect profile's command/parameters are empty
        # strings, so without this it would return [""] — an empty
        # executable — rather than [].
        profile = StreamProfile(
            name=REDIRECT_PROFILE_NAME,
            command="",
            parameters="",
            locked=True,
        )
        self.assertEqual(
            profile.build_command("http://example.com/stream.ts", "Mozilla/5.0"), []
        )
