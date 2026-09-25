"""The VOD proxy's Range answers describe the bytes it actually sends.

Each test drives ``stream_content_with_session`` end to end against an
in-memory Redis and a scripted upstream, and names the defect it pins:
#64 (suffix ranges served as prefixes), #66 (a Range-ignoring provider's
head served under a 206 for the slice), #98 (a provider 416 answered 500).
"""

from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase
from requests.structures import CaseInsensitiveDict

from apps.proxy.vod_proxy import multi_worker_connection_manager as mwcm
from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
    LockAwareFakeRedis,
    _clear_script_cache,
)
from apps.vod.models import Movie

ASSET = bytes(i % 251 for i in range(1000))


class FakeUpstream:
    """A requests.Response stand-in that serves ASSET the way a provider would."""

    def __init__(self, status, body=b"", headers=None):
        self.status_code = status
        self._body = body
        self.headers = CaseInsensitiveDict(headers or {})
        self.url = "http://provider.example/movie/u/p/1.mp4"
        self.closed = False

    def iter_content(self, chunk_size=8192):
        for i in range(0, len(self._body), 97):  # odd chunking exercises the slicer
            yield self._body[i:i + 97]

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code} for url: {self.url}")

    def close(self):
        self.closed = True


def ranged(range_header):
    """What an RFC-compliant provider answers for ``range_header``."""
    from apps.proxy.vod_proxy.byte_range import UNSATISFIABLE, resolve_range

    if not range_header:
        return FakeUpstream(200, ASSET, {"Content-Length": str(len(ASSET))})
    resolved = resolve_range(range_header, len(ASSET))
    if resolved is UNSATISFIABLE:
        return FakeUpstream(416, b"", {"Content-Range": f"bytes */{len(ASSET)}"})
    start, end = resolved
    return FakeUpstream(206, ASSET[start:end + 1], {
        "Content-Range": f"bytes {start}-{end}/{len(ASSET)}",
        "Content-Length": str(end - start + 1),
    })


class VodRangeResponseTests(SimpleTestCase):
    SESSION = "vod_1_1"

    def setUp(self):
        _clear_script_cache()
        self.redis = LockAwareFakeRedis()
        self.sent_ranges = []
        self.answer = ranged  # per-test override
        patches = [
            patch.object(mwcm.MultiWorkerVODConnectionManager, "find_matching_idle_session", return_value=None),
            patch.object(mwcm.MultiWorkerVODConnectionManager, "_check_and_reserve_profile_slot", return_value=True),
            patch.object(mwcm.MultiWorkerVODConnectionManager, "_decrement_profile_connections"),
            patch.object(mwcm.MultiWorkerVODConnectionManager, "_send_vod_event"),
            patch.object(mwcm.requests, "Session", side_effect=self._session),
        ]
        self.mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.decrement_profile = self.mocks[2]
        self.manager = mwcm.MultiWorkerVODConnectionManager.__new__(mwcm.MultiWorkerVODConnectionManager)
        self.manager.redis_client = self.redis
        self.manager.worker_id = "worker-test"
        self.profile = MagicMock(id=7, max_streams=5)
        self.profile.name = "p"
        self.profile.m3u_account.get_user_agent_string.return_value = "ua"
        self.movie = Movie(name="M")

    def _session(self):
        session = MagicMock()

        def get(url, headers=None, **kwargs):
            rng = (headers or {}).get("Range")
            self.sent_ranges.append(rng)
            return self.answer(rng)

        session.get.side_effect = get
        return session

    def _establish(self):
        """A full first request, so the session knows the size (1000)."""
        response = self._get(None)
        self.assertEqual(response.status_code, 200)
        b"".join(response.streaming_content)
        self.sent_ranges.clear()

    def _get(self, range_header):
        request = RequestFactory().get("/proxy/vod/movie/x/" + self.SESSION)
        return self.manager.stream_content_with_session(
            self.SESSION, self.movie, "http://provider.example/movie/u/p/1.mp4",
            self.profile, "1.2.3.4", "agent", request, range_header=range_header,
        )

    # --- #98 ---------------------------------------------------------------

    def test_a_provider_416_on_a_first_request_was_a_500(self):
        response = self._get("bytes=99999999-")
        self.assertEqual(self.sent_ranges, ["bytes=99999999-"])  # the provider was asked
        self.assertEqual(response.status_code, 416)
        self.assertEqual(response.content, b"Requested Range Not Satisfiable")
        self.decrement_profile.assert_called_once_with(7)
        self.assertEqual(self.redis.hgetall(f"vod_persistent_connection:{self.SESSION}"), {})

    def test_an_unsatisfiable_range_on_an_established_session_is_still_416(self):
        self._establish()
        response = self._get("bytes=99999999-")
        self.assertEqual(response.status_code, 416)
        self.assertEqual(self.sent_ranges, [])  # refused before asking the provider

    # --- #64 ---------------------------------------------------------------

    def test_a_suffix_range_on_an_established_session_was_served_as_a_prefix(self):
        self._establish()
        response = self._get("bytes=-100")
        self.assertEqual(self.sent_ranges, ["bytes=900-999"])
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Range"], "bytes 900-999/1000")
        self.assertEqual(response["Content-Length"], "100")
        self.assertEqual(b"".join(response.streaming_content), ASSET[900:])

    def test_a_suffix_range_on_a_first_request_got_a_prefix_content_range(self):
        response = self._get("bytes=-100")
        self.assertEqual(self.sent_ranges, ["bytes=-100"])
        self.assertEqual(response["Content-Range"], "bytes 900-999/1000")
        self.assertEqual(response["Content-Length"], "100")
        self.assertEqual(b"".join(response.streaming_content), ASSET[900:])

    # --- #66 ---------------------------------------------------------------

    def test_a_range_ignoring_provider_had_its_head_served_as_the_requested_slice(self):
        self._establish()
        self.answer = lambda rng: FakeUpstream(200, ASSET, {"Content-Length": "1000"})
        response = self._get("bytes=100-199")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Range"], "bytes 100-199/1000")
        self.assertEqual(response["Content-Length"], "100")
        self.assertEqual(b"".join(response.streaming_content), ASSET[100:200])

    def test_a_range_ignoring_provider_with_no_length_is_served_as_an_honest_200(self):
        self.answer = lambda rng: FakeUpstream(200, ASSET, {})
        response = self._get("bytes=100-199")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Content-Range", response)
        self.assertEqual(b"".join(response.streaming_content), ASSET)

    def test_a_provider_206_is_relayed_with_its_own_content_range(self):
        self._establish()
        response = self._get("bytes=100-199")
        self.assertEqual(self.sent_ranges, ["bytes=100-199"])
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Range"], "bytes 100-199/1000")
        self.assertEqual(b"".join(response.streaming_content), ASSET[100:200])

    # --- Round 2/3 (bot review) ---------------------------------------------

    def _seek_state(self):
        return mwcm.RedisBackedVODConnection(self.SESSION, self.redis)._get_connection_state()

    # The pre-fix rule was suffix vs. non-suffix, not first-request vs.
    # established: the old header block re-derived `start` from the client's
    # raw, unresolved Range string, and a suffix's empty start_str always
    # produced start=0, so `if start > 0:` never fired for a suffix -- on a
    # first request OR an established session. It DID fire for a non-suffix
    # range (e.g. bytes=100-199) on a first request too, because
    # state.content_length is already populated by the time the header block
    # runs (get_stream() captures it from the provider's own
    # Content-Range/Content-Length before returning). The four tests below
    # pin all four cells of that suffix x established matrix.

    def test_a_first_request_suffix_range_does_not_record_seek_info(self):
        response = self._get("bytes=-100")
        b"".join(response.streaming_content)
        state = self._seek_state()
        self.assertEqual(state.last_seek_byte, 0)
        self.assertEqual(state.last_seek_percentage, 0.0)

    def test_an_established_session_suffix_range_does_not_record_seek_info(self):
        self._establish()
        response = self._get("bytes=-100")
        b"".join(response.streaming_content)
        state = self._seek_state()
        self.assertEqual(state.last_seek_byte, 0)
        self.assertEqual(state.last_seek_percentage, 0.0)

    def test_a_first_request_non_suffix_range_records_seek_info(self):
        response = self._get("bytes=100-199")
        b"".join(response.streaming_content)
        state = self._seek_state()
        self.assertEqual(state.last_seek_byte, 100)
        self.assertEqual(state.last_seek_percentage, 10.0)

    def test_an_established_session_non_suffix_range_records_seek_info(self):
        self._establish()
        response = self._get("bytes=100-199")
        b"".join(response.streaming_content)
        state = self._seek_state()
        self.assertEqual(state.last_seek_byte, 100)
        self.assertEqual(state.last_seek_percentage, 10.0)

    def test_a_range_ignoring_provider_had_its_unread_remainder_closed_once_the_slice_completed(self):
        self._establish()
        upstream = FakeUpstream(200, ASSET, {"Content-Length": "1000"})
        self.answer = lambda rng: upstream
        response = self._get("bytes=100-199")
        self.assertFalse(upstream.closed)
        b"".join(response.streaming_content)
        self.assertTrue(upstream.closed)
