"""Property tests for the provider catch-up URL builders.

Surfaces (``file:line`` at a54b09a9), all in apps/timeshift/helpers.py:

- ``build_timeshift_url_format_a`` (:412, QUERY layout) and
  ``build_timeshift_url_format_b`` (:424, PATH layout): the reserved profile's
  credentials are percent-encoded with ``quote(..., safe='')``, so a password
  containing ``&``, ``=``, ``/``, ``?`` or ``#`` cannot add a query parameter or a
  path segment to the provider URL.
- ``client_timeshift_url_layout`` (:436) and ``build_timeshift_redirect_url`` (:449).
- ``build_timeshift_candidate_urls`` (:466): seven candidates, every PATH form
  before every QUERY form.

Closes the URL-builder scope of #192 (survivor), #260 and #55.
"""

from datetime import datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlsplit

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.timeshift.helpers import (
    TimeshiftCredentials,
    build_timeshift_candidate_urls,
    build_timeshift_redirect_url,
    build_timeshift_url_format_a,
    build_timeshift_url_format_b,
    client_timeshift_url_layout,
    parse_catchup_timestamp,
)

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# Credentials a hostile or careless provider account could carry, weighted toward
# URL-structural characters.
credential = st.text(max_size=24) | st.text(alphabet="&=/?#%+ ;:@a1", max_size=12)
server_url = st.builds(
    lambda host, port, slashes: f"http://{host}{port}{'/' * slashes}",
    st.from_regex(r"[a-z][a-z0-9.-]{0,20}", fullmatch=True),
    st.sampled_from(["", ":8080", ":80"]),
    st.integers(min_value=0, max_value=3),
)
creds_strategy = st.builds(TimeshiftCredentials, server_url, credential, credential)
stream_ids = st.integers(min_value=1, max_value=10**9)
durations = st.integers(min_value=1, max_value=480)
provider_timestamps = st.datetimes(
    min_value=datetime(2000, 1, 1), max_value=datetime(2099, 12, 31)
).map(lambda d: d.strftime("%Y-%m-%d:%H-%M"))


def _path_segments_after_host(url):
    return urlsplit(url).path.split("/")[1:]


class ProviderUrlLayoutProperties(SimpleTestCase):
    @given(creds=creds_strategy, stream_id=stream_ids, ts=provider_timestamps, dur=durations)
    def test_query_layout_carries_exactly_the_five_params_with_credentials_intact(
        self, creds, stream_id, ts, dur,
    ):
        url = build_timeshift_url_format_a(creds, stream_id, ts, dur)
        parts = urlsplit(url)
        self.assertEqual(parts.path.rsplit("/", 2)[-2:], ["streaming", "timeshift.php"])
        self.assertEqual(parts.fragment, "")
        params = parse_qs(parts.query, keep_blank_values=True, strict_parsing=False)
        self.assertEqual(
            params,
            {
                "username": [creds.username],
                "password": [creds.password],
                "stream": [str(stream_id)],
                "start": [ts],
                "duration": [str(dur)],
            },
        )

    @given(creds=creds_strategy, stream_id=stream_ids, ts=provider_timestamps, dur=durations)
    def test_path_layout_is_exactly_six_segments_with_credentials_intact(
        self, creds, stream_id, ts, dur,
    ):
        url = build_timeshift_url_format_b(creds, stream_id, ts, dur)
        self.assertEqual(urlsplit(url).fragment, "")
        self.assertEqual(urlsplit(url).query, "")
        segments = _path_segments_after_host(url)
        self.assertEqual(len(segments), 6, url)
        self.assertEqual(segments[0], "timeshift")
        self.assertEqual(unquote(segments[1]), creds.username)
        self.assertEqual(unquote(segments[2]), creds.password)
        self.assertEqual(segments[3:], [str(dur), ts, f"{stream_id}.ts"])

    @given(creds=creds_strategy, stream_id=stream_ids, ts=provider_timestamps, dur=durations)
    def test_trailing_slashes_on_server_url_never_double_the_separator(
        self, creds, stream_id, ts, dur,
    ):
        host = creds.server_url.rstrip("/")
        for url in (
            build_timeshift_url_format_a(creds, stream_id, ts, dur),
            build_timeshift_url_format_b(creds, stream_id, ts, dur),
        ):
            self.assertTrue(url.startswith(host + "/"))
            self.assertFalse(url[len(host):].startswith("//"))

    @given(path=st.text(max_size=40), inject=st.booleans(),
           spelling=st.sampled_from(["timeshift.php", "TIMESHIFT.PHP", "TimeShift.Php"]))
    def test_layout_is_query_exactly_when_the_path_names_timeshift_php(
        self, path, inject, spelling,
    ):
        if inject:
            path = f"/streaming/{spelling}{path}"
        request = SimpleNamespace(path=path)
        expected = "query" if "timeshift.php" in path.lower() else "path"
        self.assertEqual(client_timeshift_url_layout(request), expected)

    @given(creds=creds_strategy, stream_id=stream_ids, ts=provider_timestamps,
           dur=durations, layout=st.sampled_from(["query", "path", "", None, "other"]))
    def test_redirect_url_mirrors_the_client_layout(self, creds, stream_id, ts, dur, layout):
        url = build_timeshift_redirect_url(creds, stream_id, ts, dur, layout)
        if layout == "query":
            self.assertEqual(url, build_timeshift_url_format_a(creds, stream_id, ts, dur))
        else:
            self.assertEqual(url, build_timeshift_url_format_b(creds, stream_id, ts, dur))


class CandidateUrlProperties(SimpleTestCase):
    @given(creds=creds_strategy, stream_id=stream_ids,
           ts=provider_timestamps | st.text(max_size=30), dur=durations)
    def test_seven_candidates_every_path_form_before_every_query_form(
        self, creds, stream_id, ts, dur,
    ):
        urls = build_timeshift_candidate_urls(creds, stream_id, ts, dur)
        self.assertEqual(len(urls), 7)
        kinds = [
            "query" if urlsplit(u).path.endswith("/streaming/timeshift.php") else "path"
            for u in urls
        ]
        self.assertEqual(kinds, ["path"] * 3 + ["query"] * 4)

    @given(creds=creds_strategy, stream_id=stream_ids, ts=provider_timestamps, dur=durations)
    def test_parseable_timestamp_is_offered_in_the_four_documented_shapes(
        self, creds, stream_id, ts, dur,
    ):
        dt = parse_catchup_timestamp(ts)
        colon_dash = dt.strftime("%Y-%m-%d:%H-%M")
        underscore = dt.strftime("%Y-%m-%d_%H-%M")
        colon_seconds = dt.strftime("%Y-%m-%d:%H:%M:%S")
        sql = dt.strftime("%Y-%m-%d %H:%M:%S")
        urls = build_timeshift_candidate_urls(creds, stream_id, ts, dur)
        path_starts = [_path_segments_after_host(u)[4] for u in urls[:3]]
        query_starts = [parse_qs(urlsplit(u).query)["start"][0] for u in urls[3:]]
        self.assertEqual(path_starts, [colon_dash, underscore, colon_seconds])
        self.assertEqual(query_starts, [underscore, sql, colon_dash, colon_seconds])

    @given(creds=creds_strategy, stream_id=stream_ids,
           ts=st.text(alphabet="abcxyz!~-_", min_size=1, max_size=20), dur=durations)
    def test_unparseable_timestamp_is_passed_through_verbatim_to_every_candidate(
        self, creds, stream_id, ts, dur,
    ):
        if parse_catchup_timestamp(ts) is not None:
            return
        urls = build_timeshift_candidate_urls(creds, stream_id, ts, dur)
        self.assertEqual([_path_segments_after_host(u)[4] for u in urls[:3]], [ts] * 3)
        self.assertEqual([parse_qs(urlsplit(u).query)["start"][0] for u in urls[3:]], [ts] * 4)
