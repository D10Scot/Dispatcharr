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
        every XC account through the regex-transform branch, which recovers
        the credentials by splitting the synthetic URL on '/' and indexing
        fixed positions when the credentials themselves were rewritten. A
        literal '/' in the password used to insert an extra path segment
        there and shift the extraction onto the wrong pieces (#370) — the
        credential this function returned was wrong before
        _resolve_live_stream_url's own quoting (#61) ever ran. Fixed by a
        shortcut ahead of the split: when the transformed URL still ends
        with the exact raw "/live/{username}/{password}/1234.ts" suffix —
        true here, since the identity pattern changes nothing — the raw
        credentials are returned directly and the split is never reached.
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
        """Control for #370: a profile whose pattern rewrites only the host
        still gets that transform applied, and the credential segments still
        round-trip intact even though the password contains a '/', because
        the transformed URL still ends with the exact raw credential suffix
        (only the host preceding it changed) and hits the same shortcut as
        the identity-profile case above.
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

    def test_a_simple_mode_credential_swap_matches_the_raw_shape_the_frontend_writes(self):
        """The frontend's "simple" XC profile mode
        (M3uProfileUtils.js's applyXcSimplePatterns) stores search_pattern as
        the literal raw "{username}/{password}" string and replace_pattern as
        the new ones — a credential swap written against RAW credentials, not
        a host rewrite, and the common custom-profile shape (getDetectedMode
        defaults new profiles to "simple"). Percent-encoding the credentials
        before running the profile's regex against them (round 1's rejected
        approach) would have made a raw pattern like this stop matching, so
        the swap silently fell through to the primary account's own
        credentials. The transformed URL here ends with "/live/bob/other/…",
        not the raw suffix built from alice@x.com/secret, so this exercises
        the split-based extraction path, not the shortcut the two tests above
        take.
        """
        account = M3UAccount.objects.create(
            name="Simple mode swap XC",
            account_type="XC",
            server_url="https://myserver.fun/server1",
            username="alice@x.com",
            password="secret",
        )
        profile = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)
        profile.search_pattern = "alice@x.com/secret"
        profile.replace_pattern = "bob/other"
        profile.save()

        server_url, username, password = get_transformed_credentials(account, profile)

        self.assertEqual(server_url, "https://myserver.fun/server1")
        self.assertEqual(username, "bob")
        self.assertEqual(password, "other")

    def test_the_raw_suffix_shortcut_is_exact_not_a_loose_heuristic(self):
        """Round 1 review questioned whether the raw-suffix shortcut in
        get_transformed_credentials could "false-positive" on a profile whose
        output merely happens to end with the raw credential suffix without
        the pattern actually being a credential-preserving rewrite. It
        cannot: the suffix is the literal string "/live/{raw user}/{raw
        pass}/1234.ts", built from the SAME raw fields the function would
        otherwise return, so whenever the transformed URL provably ends with
        it, those are in fact the credentials in the URL — whatever the
        pattern did to everything before that suffix. Two cases:

        1. A host rewrite to a bare hostname, leaving an EMPTY base path.
           The shortcut still fires correctly and returns an empty-path
           server URL, not a false positive.
        2. A pattern that appends a query string AFTER the credential
           suffix. The transformed URL no longer literally ENDS with the raw
           suffix (it ends with the query string instead), so the shortcut
           correctly declines to fire and falls through to the split-based
           extraction — which also recovers the right credentials, because
           urlparse discards the query when rebuilding the server URL. This
           is the case that would risk a false positive if the check were a
           looser heuristic; it isn't one.
        """
        # Case 1: bare-hostname rewrite, empty base path.
        account = M3UAccount.objects.create(
            name="Bare host rewrite XC",
            account_type="XC",
            server_url="https://h",
            username="alice",
            password="secret",
        )
        profile = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)
        profile.search_pattern = r"^https://h(/.*)$"
        profile.replace_pattern = r"https://other$1"
        profile.save()

        server_url, username, password = get_transformed_credentials(account, profile)

        self.assertEqual(server_url, "https://other")
        self.assertEqual(username, "alice")
        self.assertEqual(password, "secret")

        # Case 2: query string appended after the credential suffix.
        account2 = M3UAccount.objects.create(
            name="Query string rewrite XC",
            account_type="XC",
            server_url="https://h",
            username="alice",
            password="secret",
        )
        profile2 = M3UAccountProfile.objects.get(m3u_account=account2, is_default=True)
        profile2.search_pattern = r"^(https://h/live/alice/secret/1234\.ts)$"
        profile2.replace_pattern = r"$1?nocache=1"
        profile2.save()

        server_url2, username2, password2 = get_transformed_credentials(account2, profile2)

        self.assertEqual(server_url2, "https://h")
        self.assertEqual(username2, "alice")
        self.assertEqual(password2, "secret")


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

    def test_live_and_catch_up_quote_the_same_reserved_password_identically(self):
        """_resolve_live_stream_url (apps/proxy/next_source.py:63) and the
        catch-up URL builders (apps/timeshift/helpers.py's
        build_timeshift_url_format_a/_b) both quote with
        quote(str(x), safe=''). The two are only kept in sync by that shared
        call shape and a comment, not by a single implementation, so this
        pins that they produce byte-identical encodings of the same
        reserved-character credential rather than merely trusting the
        comment.
        """
        from apps.timeshift.helpers import (
            TimeshiftCredentials,
            build_timeshift_url_format_b,
        )

        account = M3UAccount.objects.create(
            name="Live vs catch-up encoding XC",
            account_type="XC",
            server_url="https://myserver.fun/server1",
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

        live_url = _resolve_live_stream_url(stream, account, profile)

        creds = TimeshiftCredentials(account.server_url, account.username, account.password)
        catchup_url = build_timeshift_url_format_b(creds, "12345", "2026-05-12:19-00", 40)

        # Both builders put the encoded password in a path segment of its
        # own, at different positions (live: .../{pass}/{id}.ts; catch-up
        # format B: .../{pass}/{duration}/{timestamp}/{id}.ts), so check
        # containment of the exact encoded segment rather than parsing by
        # position.
        expected_encoded_password = "p%2Fss%25w%40rd"
        self.assertIn(f"/{expected_encoded_password}/", live_url)
        self.assertIn(f"/{expected_encoded_password}/", catchup_url)

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
