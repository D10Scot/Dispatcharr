"""Regression tests for #80: an unescaped double quote in tvg-name/group-title
broke the #EXTINF line. `apps.output.views._m3u_attr` escapes only `"` (to
`&quot;`); `&` stays literal on purpose, because common IPTV players and
Dispatcharr's own importer (apps.m3u.tasks.parse_extinf_line, which never
unescapes) read M3U attribute values literally, so a general HTML escape
would turn "AT&T" into "AT&amp;T".
"""

from django.test import Client, TestCase
from django.urls import reverse

from apps.channels.models import ChannelGroup
from apps.m3u.tasks import parse_extinf_line
from apps.output.tests.test_views import OutputEndpointTestMixin, _response_text


class M3UAttributeQuotingTests(OutputEndpointTestMixin, TestCase):
    """Built on OutputM3UTest's harness (test_views.py:94-141)."""

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.profile = self._create_isolated_profile("m3u-quote")

    def _m3u_url(self):
        return reverse(
            "output:m3u_endpoint", kwargs={"profile_name": self.profile.name}
        )

    def _entry_for(self, channel, content):
        """Pair each #EXTINF line with the URL beneath it, mirroring
        e2e/fixtures/parse.ts's parseM3u, and return the parsed attributes
        for the line whose paired URL carries this channel's uuid."""
        lines = content.splitlines()
        for line, next_line in zip(lines, lines[1:]):
            if line.startswith("#EXTINF") and str(channel.uuid) in next_line:
                return parse_extinf_line(line)
        return None

    def test_double_quote_in_channel_name_does_not_break_extinf(self):
        # This channel is the only one in the playlist, so an unescaped
        # quote corrupting its own #EXTINF line can't be masked, or
        # confused with another entry's, by a second channel sharing the
        # profile. tvg_id and tvc_guide_stationid also carry a quote, and
        # ?tvg_id_source=tvg_id routes the raw tvg_id value into the
        # tvg-id attribute (the default source is the channel number,
        # which can't carry a quote) — between them, four of the five
        # quotable attributes are exercised (tvg-logo is a URL and is not
        # given a quote here).
        group = ChannelGroup.objects.create(name='World "Feed" News')
        channel = self._add_channel_to_profile(
            self.profile,
            group,
            channel_number=1.0,
            name='Chan "Quoted" Name',
            tvg_id='id-"42"',
            tvc_guide_stationid='station-"7"',
        )

        response = self.client.get(f"{self._m3u_url()}?tvg_id_source=tvg_id")
        self.assertEqual(response.status_code, 200)

        entry = self._entry_for(channel, _response_text(response))
        self.assertIsNotNone(
            entry, "the quoted channel must have a parseable #EXTINF line"
        )

        self.assertEqual(
            entry["attributes"]["tvg-name"], "Chan &quot;Quoted&quot; Name"
        )
        self.assertEqual(
            entry["attributes"]["group-title"], "World &quot;Feed&quot; News"
        )
        self.assertEqual(entry["attributes"]["tvg-id"], "id-&quot;42&quot;")
        self.assertEqual(
            entry["attributes"]["tvc-guide-stationid"], "station-&quot;7&quot;"
        )
        self.assertEqual(
            set(entry["attributes"]),
            {
                "tvg-id",
                "tvg-name",
                "tvg-logo",
                "tvg-chno",
                "tvc-guide-stationid",
                "group-title",
            },
            "no attribute should have spilled from an unescaped quote",
        )
        # The display name after the comma is raw, not escaped: it runs to
        # end of line and is not a quoted attribute value.
        self.assertEqual(entry["display_name"], 'Chan "Quoted" Name')

    def test_ampersand_in_channel_name_is_left_alone(self):
        """Control: & is not HTML-escaped, unlike ". #80's fix must not
        widen into a general html.escape()."""
        group = ChannelGroup.objects.create(name="Sports")
        channel = self._add_channel_to_profile(
            self.profile,
            group,
            channel_number=2.0,
            name="AT&T Sports",
        )

        response = self.client.get(self._m3u_url())
        self.assertEqual(response.status_code, 200)

        entry = self._entry_for(channel, _response_text(response))
        self.assertIsNotNone(entry)
        self.assertEqual(entry["attributes"]["tvg-name"], "AT&T Sports")
        self.assertEqual(entry["display_name"], "AT&T Sports")
