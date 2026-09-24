"""Tests for XC stream URL normalization and on-demand URL building.

_resolve_live_stream_url moved to apps/proxy/next_source.py in Phase 1
PR 6 along with the rest of source resolution; it has no re-export in
apps.proxy.next_source (private, leading underscore; it was
apps.proxy.live_proxy.url_utils until stage 2d-1 moved it), so this
import points at its new home.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.channels.models import Stream
from apps.m3u.models import M3UAccount, M3UAccountProfile
from apps.m3u.tasks import collect_xc_streams, get_transformed_credentials
from apps.proxy.next_source import _resolve_live_stream_url
from apps.vod.models import Episode, M3UEpisodeRelation, M3UMovieRelation, Movie, Series
from core.xtream_codes import normalize_server_url


class NormalizeServerUrlTests(TestCase):
    def test_preserves_sub_path(self):
        url = "https://myserver.fun/server1"
        self.assertEqual(normalize_server_url(url), "https://myserver.fun/server1")

    def test_strips_player_api_php_and_query_params(self):
        url = "https://myserver.fun/server1/player_api.php?username=foo&password=bar"
        self.assertEqual(normalize_server_url(url), "https://myserver.fun/server1")

    def test_strips_trailing_slash(self):
        url = "https://myserver.fun/server1/"
        self.assertEqual(normalize_server_url(url), "https://myserver.fun/server1")

    def test_nested_sub_path_with_php_endpoint(self):
        url = "http://server/Pluto/gb/player_api.php"
        self.assertEqual(normalize_server_url(url), "http://server/Pluto/gb")


class GetTransformedCredentialsTests(TestCase):
    def test_returns_normalized_server_url(self):
        account = M3UAccount.objects.create(
            name="Sub-path XC",
            account_type="XC",
            server_url="https://myserver.fun/server1/player_api.php?username=foo",
            username="alice",
            password="secret",
        )
        profile = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)

        server_url, username, password = get_transformed_credentials(account, profile)

        self.assertEqual(server_url, "https://myserver.fun/server1")
        self.assertEqual(username, "alice")
        self.assertEqual(password, "secret")

    def test_a_slash_in_the_password_round_trips_through_the_default_profile(self):
        """The default profile's identity search/replace pattern still routes
        every XC account through the regex-transform branch, which used to
        recover the credentials by splitting the synthetic URL on '/' and
        indexing fixed positions. A literal '/' in the password inserted an
        extra path segment there and shifted the extraction onto the wrong
        pieces (#370) — the credential this function returned was wrong
        before _resolve_live_stream_url's own quoting (#61) ever ran.
        """
        account = M3UAccount.objects.create(
            name="Slash password XC",
            account_type="XC",
            server_url="https://myserver.fun/server1",
            username="alice",
            password="p/ss%w@rd",
        )
        profile = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)

        server_url, username, password = get_transformed_credentials(account, profile)

        self.assertEqual(server_url, "https://myserver.fun/server1")
        self.assertEqual(username, "alice")
        self.assertEqual(password, "p/ss%w@rd")

    def test_a_custom_profile_transform_still_applies_with_a_slash_in_the_password(self):
        """Control for #370: a profile whose pattern rewrites the host still
        gets that transform applied, and the credential segments still
        round-trip intact even though the password contains a '/'. Only the
        credential-segment extraction changed; the transform mechanism did
        not.
        """
        account = M3UAccount.objects.create(
            name="Custom profile XC",
            account_type="XC",
            server_url="https://myserver.fun/server1",
            username="alice",
            password="p/ss%w@rd",
        )
        profile = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)
        profile.search_pattern = r"^https://myserver\.fun(/.*)$"
        profile.replace_pattern = r"https://mirror.example$1"
        profile.save()

        server_url, username, password = get_transformed_credentials(account, profile)

        self.assertEqual(server_url, "https://mirror.example/server1")
        self.assertEqual(username, "alice")
        self.assertEqual(password, "p/ss%w@rd")


class ResolveLiveStreamUrlTests(TestCase):
    def test_builds_url_from_normalized_base_not_raw_account_url(self):
        account = M3UAccount.objects.create(
            name="Live sub-path",
            account_type="XC",
            server_url="https://myserver.fun/server1/player_api.php?username=foo",
            username="alice",
            password="secret",
        )
        profile = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)
        stream = Stream.objects.create(
            name="Test Channel",
            m3u_account=account,
            stream_id="12345",
            url="https://myserver.fun/server1/live/olduser/oldpass/12345.ts",
        )

        url = _resolve_live_stream_url(stream, account, profile)

        self.assertEqual(
            url,
            "https://myserver.fun/server1/live/alice/secret/12345.ts",
        )

    def test_resolve_live_stream_url_interpolated_a_slash_in_the_password_raw(self):
        account = M3UAccount.objects.create(
            name="Live sub-path",
            account_type="XC",
            server_url="https://myserver.fun/server1/player_api.php?username=foo",
            username="alice",
            password="p/ss%w@rd",
        )
        profile = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)
        stream = Stream.objects.create(
            name="Test Channel",
            m3u_account=account,
            stream_id="12345",
            url="https://myserver.fun/server1/live/olduser/oldpass/12345.ts",
        )

        url = _resolve_live_stream_url(stream, account, profile)

        self.assertEqual(
            url,
            "https://myserver.fun/server1/live/alice/p%2Fss%25w%40rd/12345.ts",
        )

    def test_std_account_uses_stored_stream_url(self):
        account = M3UAccount.objects.create(
            name="STD account",
            account_type="STD",
            server_url="https://example.com/list.m3u",
            username="alice",
            password="secret",
        )
        profile = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)
        stream = Stream.objects.create(
            name="STD Stream",
            m3u_account=account,
            url="https://provider.example/stream/abc123",
        )

        url = _resolve_live_stream_url(stream, account, profile)

        self.assertEqual(url, "https://provider.example/stream/abc123")


class CollectXcStreamsTests(TestCase):
    @patch("apps.m3u.tasks.XCClient")
    def test_collect_xc_streams_stored_a_slash_in_the_password_raw(self, mock_xc_client_cls):
        account = M3UAccount.objects.create(
            name="Live sub-path",
            account_type="XC",
            server_url="https://myserver.fun/server1/player_api.php?username=foo",
            username="alice",
            password="p/ss%w@rd",
        )

        mock_client = MagicMock()
        mock_client.server_url = "https://myserver.fun/server1"
        mock_client.username = "alice"
        mock_client.password = "p/ss%w@rd"
        mock_client.get_all_live_streams.return_value = [
            {"stream_id": 12345, "name": "News 1", "category_id": 7}
        ]
        mock_xc_client_cls.return_value.__enter__.return_value = mock_client

        streams = collect_xc_streams(account.id, {"News": {"xc_id": 7}})

        self.assertEqual(len(streams), 1)
        self.assertEqual(
            streams[0]["url"],
            "https://myserver.fun/server1/live/alice/p%2Fss%25w%40rd/12345.ts",
        )


class VodStreamUrlTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="VOD sub-path",
            account_type="XC",
            server_url="https://myserver.fun/server1/player_api.php?username=foo",
            username="alice",
            password="secret",
        )

    def test_movie_relation_builds_normalized_url(self):
        movie = Movie.objects.create(name="Test Movie")
        relation = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=movie,
            stream_id="999",
            container_extension="mkv",
        )

        url = relation.get_stream_url()

        self.assertEqual(
            url,
            "https://myserver.fun/server1/movie/alice/secret/999.mkv",
        )

    def test_episode_relation_builds_normalized_url(self):
        series = Series.objects.create(name="Test Series")
        episode = Episode.objects.create(
            series=series,
            name="Pilot",
            season_number=1,
            episode_number=1,
        )
        relation = M3UEpisodeRelation.objects.create(
            m3u_account=self.account,
            episode=episode,
            stream_id="888",
            container_extension="mp4",
        )

        url = relation.get_stream_url()

        self.assertEqual(
            url,
            "https://myserver.fun/server1/series/alice/secret/888.mp4",
        )
