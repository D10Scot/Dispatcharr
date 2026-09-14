"""Phase 2 PR 2c-4, spec Amendment A4.1: next-source carries the BUILT argv.

The Go relay spawns exactly what StreamProfile.build_command produces for the
same url, user agent and object, because Django builds it and sends it. These
tests pin the builder from the Python side: every migration-shipped parameter
string, the adversarial shapes that made a Go port of shlex the riskier path,
and the three states of the field. The Go side pins presence and refusal
(relay/control/profile_test.go, relay/httpapi/transcode_test.go).

EVERY EXPECTED ARGV IS A LITERAL, never `build_command(...)[1:]` -- that would
be the tautological oracle, the same function computing both sides. The
literals were derived by hand from the parameters and confirmed against
`python3 -c 'import shlex; ...'` while the plan was written.
"""

import json

from django.test import TestCase
from rest_framework.renderers import JSONRenderer

from apps.proxy.config import TSConfig
from apps.proxy.next_source import _stream_profile_ref
from apps.proxy.serializers import StreamProfileRefSerializer
from core.models import PROXY_PROFILE_NAME, REDIRECT_PROFILE_NAME, StreamProfile

URL = "http://provider.example/live/subscriber/hunter2/41.ts?token=s3cr3t"
UA = "Dispatcharr/2c4 (test)"


def profile(command, parameters, **fields):
    """An UNLOCKED row, so core/models.py:78-101's protected-field guard
    never runs; created rather than fetched because a TransactionTestCase
    earlier in the process may have flushed the migration-seeded rows."""
    return StreamProfile.objects.create(
        name=f"argv-{command}-{abs(hash(parameters))}", command=command,
        parameters=parameters, **fields,
    )


class MigrationShippedProfiles(TestCase):
    """Every parameter string core/migrations ships, with its argv."""

    def test_the_locked_ffmpeg_profiles_parameters(self):
        # core/migrations/0006's new_parameters, the locked profile's final shape.
        ref = _stream_profile_ref(
            profile("ffmpeg", "-user_agent {userAgent} -i {streamUrl} -c copy -f mpegts pipe:1"),
            url=URL, user_agent=UA, pk=41,
        )
        self.assertEqual(
            ref["argv"],
            ["-user_agent", UA, "-i", URL, "-c", "copy", "-f", "mpegts", "pipe:1"],
        )
        self.assertEqual(ref["kind"], "transcode")

    def test_migration_0003s_original_ffmpeg_parameters(self):
        ref = _stream_profile_ref(
            profile("ffmpeg", "-i {streamUrl} -c:v copy -c:a copy -f mpegts pipe:1"),
            url=URL, user_agent=UA, pk=41,
        )
        self.assertEqual(ref["argv"], ["-i", URL, "-c:v", "copy", "-c:a", "copy", "-f", "mpegts", "pipe:1"])

    def test_the_streamlink_profiles_parameters(self):
        # core/migrations/0011's final shape: the user agent inside a token.
        ref = _stream_profile_ref(
            profile("streamlink", "{streamUrl} --http-header User-Agent={userAgent} best --stdout"),
            url=URL, user_agent=UA, pk=41,
        )
        self.assertEqual(ref["argv"], [URL, "--http-header", f"User-Agent={UA}", "best", "--stdout"])

    def test_the_vlc_profiles_parameters(self):
        # core/migrations/0019 and 0027: `#standard{...}` is ONE token, because
        # shlex.split runs with comments=False and braces are word characters.
        ref = _stream_profile_ref(
            profile(
                "vlc",
                "-vv -I dummy --no-video-title-show --play-and-exit --http-user-agent {userAgent} "
                "{streamUrl} --sout #standard{access=file,mux=ts,dst=-}",
            ),
            url=URL, user_agent=UA, pk=41,
        )
        self.assertEqual(
            ref["argv"],
            ["-vv", "-I", "dummy", "--no-video-title-show", "--play-and-exit",
             "--http-user-agent", UA, URL, "--sout", "#standard{access=file,mux=ts,dst=-}"],
        )

    def test_proxy_and_redirect_carry_an_empty_list(self):
        for name in (PROXY_PROFILE_NAME, REDIRECT_PROFILE_NAME):
            row, _ = StreamProfile.objects.get_or_create(
                name=name, defaults={"command": "", "parameters": "", "locked": True}
            )
            ref = _stream_profile_ref(row, url=URL, user_agent=UA, pk=41)
            self.assertEqual(ref["argv"], [], name)
            self.assertIn(ref["kind"], ("proxy", "redirect"))


class AdversarialShapes(TestCase):
    """The shlex behaviours a Go port would have had to reproduce exactly."""

    def test_a_placeholder_inside_a_quoted_token_stays_one_token(self):
        ref = _stream_profile_ref(
            profile("ffmpeg", "-headers 'User-Agent: {userAgent}' -i {streamUrl}"),
            url=URL, user_agent=UA, pk=41,
        )
        self.assertEqual(ref["argv"], ["-headers", f"User-Agent: {UA}", "-i", URL])

    def test_a_url_with_spaces_is_substituted_after_splitting_not_before(self):
        # Substitution is per PART (core/models.py:154-158), so a URL with a
        # space stays one argument; a split-after-substitute port would
        # produce two.
        spaced = "http://p/live/a b/1.ts"
        ref = _stream_profile_ref(profile("ffmpeg", "-i {streamUrl}"), url=spaced, user_agent=UA, pk=1)
        self.assertEqual(ref["argv"], ["-i", spaced])

    def test_backslash_escapes_and_double_quote_rules(self):
        # Inside double quotes shlex honours only \\ and \" (posix mode's
        # escapedquotes); `\$` stays two characters.
        ref = _stream_profile_ref(
            profile("ffmpeg", r'-x "a\"b\\c\$d" -metadata title=a\ b'),
            url=URL, user_agent=UA, pk=1,
        )
        self.assertEqual(ref["argv"], ["-x", 'a"b\\c\\$d', "-metadata", "title=a b"])

    def test_a_hash_is_not_a_comment(self):
        ref = _stream_profile_ref(profile("ffmpeg", "-i {streamUrl} # not a comment"), url=URL, user_agent=UA, pk=1)
        self.assertEqual(ref["argv"], ["-i", URL, "#", "not", "a", "comment"])

    def test_tabs_and_newlines_split_like_spaces(self):
        ref = _stream_profile_ref(profile("ffmpeg", "-i\t{streamUrl}\n-f mpegts"), url=URL, user_agent=UA, pk=1)
        self.assertEqual(ref["argv"], ["-i", URL, "-f", "mpegts"])

    def test_unparseable_parameters_render_null_and_keep_the_rest(self):
        ref = _stream_profile_ref(profile("ffmpeg", '-i "{streamUrl}'), url=URL, user_agent=UA, pk=1)
        self.assertIsNone(ref["argv"])
        self.assertEqual(ref["command"], "ffmpeg")
        self.assertEqual(ref["kind"], "transcode")

    def test_a_blank_user_agent_substitutes_the_relays_default(self):
        # input/manager.py:73: `user_agent or Config.DEFAULT_USER_AGENT`.
        ref = _stream_profile_ref(profile("ffmpeg", "-user_agent {userAgent}"), url=URL, user_agent="", pk=1)
        self.assertEqual(ref["argv"], ["-user_agent", TSConfig.DEFAULT_USER_AGENT])
        self.assertNotEqual(TSConfig.DEFAULT_USER_AGENT, "")

    def test_channel_id_is_the_objects_pk_and_empty_without_one(self):
        # core/models.py:150: str(channel_id) if channel_id else "".
        row = profile("ffmpeg", "-metadata channel={channelId}")
        self.assertEqual(_stream_profile_ref(row, url=URL, user_agent=UA, pk=41)["argv"], ["-metadata", "channel=41"])
        self.assertEqual(_stream_profile_ref(row, url=URL, user_agent=UA, pk=None)["argv"], ["-metadata", "channel="])


class TheWire(TestCase):
    def test_the_serializer_renders_a_list_and_a_null_and_never_omits_the_key(self):
        built = StreamProfileRefSerializer(
            _stream_profile_ref(profile("ffmpeg", "-i {streamUrl}"), url=URL, user_agent=UA, pk=1)
        ).data
        self.assertEqual(built["argv"], ["-i", URL])
        broken = StreamProfileRefSerializer(
            _stream_profile_ref(profile("ffmpeg", '-i "{streamUrl}'), url=URL, user_agent=UA, pk=1)
        ).data
        self.assertIn("argv", broken)
        self.assertIsNone(broken["argv"])
        # DRF's JSONRenderer is compact (no space after the colon), so the
        # rendered bytes are decoded rather than substring-matched.
        rendered = JSONRenderer().render(broken)
        self.assertIsNone(json.loads(rendered)["argv"])

    def test_the_answer_serializer_carries_argv_on_both_profile_objects(self):
        # StreamProfileRefSerializer renders stream_profile AND
        # ffmpeg_stream_profile (serializers.py:91), so one field covers both.
        from apps.proxy.serializers import SourceSerializer

        fields = SourceSerializer().fields
        self.assertIn("argv", fields["stream_profile"].fields)
        self.assertIn("argv", fields["ffmpeg_stream_profile"].fields)
