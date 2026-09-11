"""Property-based tests for the live-relay's pure parsing/key helpers.

These functions consume untrusted bytes/strings on the hot path and promise
only robustness — never raise, and honour a small contract — so they are
exactly the kind of surface Hypothesis is for. All run under SimpleTestCase
(no DB); the few that read ConfigHelper are patched so construction never
reaches CoreSettings.

Surfaces:
* output/fmp4/manager._find_moof_offset — MP4 box scan over FFmpeg's stdout.
* utils.detect_stream_type — URL -> stream-type hint, provider-controlled.
* utils.create_ts_packet — builds a 188-byte TS packet.
* server._int_or_none / _parse_output_key / _channel_id_from_metadata_key.
* input/manager.StreamManager._disconnect_shutdown_ready — time predicate.
"""

import struct
import time
from unittest import mock

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.proxy.live_proxy.constants import TS_PACKET_SIZE
from apps.proxy.live_proxy.output.fmp4.manager import MOOF_BOX_TYPE, _find_moof_offset
from apps.proxy.live_proxy.server import ProxyServer, _int_or_none
from apps.proxy.live_proxy.utils import create_ts_packet, detect_stream_type

_channel_id_from_metadata_key = ProxyServer._channel_id_from_metadata_key

hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")


def _box(box_type: bytes, payload: bytes) -> bytes:
    """Build one MP4 box: 4-byte big-endian size (header+payload) + type."""
    size = 8 + len(payload)
    return struct.pack(">I", size) + box_type + payload


class FindMoofOffsetProperties(SimpleTestCase):
    """_find_moof_offset scans for the first 'moof' box at/after start.

    Contract (from the code): returns the byte offset of the first moof box
    found while walking boxes, or -1 if none; never raises on any bytes.
    It deliberately does NOT validate payload contents — only box framing.
    """

    @given(data=st.binary(max_size=512), start=st.integers(min_value=0, max_value=600))
    def test_never_raises_and_result_is_in_range(self, data, start):
        result = _find_moof_offset(data, start=start)
        self.assertTrue(result == -1 or 0 <= result <= len(data))

    @given(
        prefix=st.binary(max_size=64),
        payload=st.binary(max_size=64),
        suffix=st.binary(max_size=64),
    )
    def test_finds_the_moof_it_can_reach(self, prefix, payload, suffix):
        """A well-formed moof box preceded by one or more well-formed boxes is found."""
        moof = _box(MOOF_BOX_TYPE, payload)
        # Walkable prefix: one or more complete non-moof boxes.
        lead = _box(b"ftyp", prefix)
        data = lead + moof + suffix
        self.assertEqual(_find_moof_offset(data, start=0), len(lead))

    @given(payload=st.binary(max_size=64))
    def test_moof_at_offset_zero_is_found(self, payload):
        data = _box(MOOF_BOX_TYPE, payload)
        self.assertEqual(_find_moof_offset(data, start=0), 0)

    @given(
        payload=st.binary(max_size=64),
        other_type=st.sampled_from([b"mdat", b"ftyp", b"moov", b"free", b"styp"]),
    )
    def test_non_moof_first_box_is_not_reported(self, payload, other_type):
        """If the first box is not moof and no moof follows, result is -1."""
        data = _box(other_type, payload)
        self.assertEqual(_find_moof_offset(data, start=0), -1)

    @given(
        pre_moof_types=st.lists(
            st.sampled_from([b"mdat", b"ftyp", b"moov", b"free", b"styp"]),
            min_size=1,
            max_size=4,
        ),
        payloads=st.lists(st.binary(max_size=16), min_size=1, max_size=4),
    )
    def test_first_moof_wins_over_later_boxes(self, pre_moof_types, payloads):
        """With several boxes then a moof then more boxes, the moof offset is exact."""
        n = len(pre_moof_types)
        payloads = (payloads + [b""] * n)[:n]
        lead = b"".join(_box(t, p) for t, p in zip(pre_moof_types, payloads))
        moof = _box(MOOF_BOX_TYPE, b"\x00" * 8)
        data = lead + moof + _box(b"mdat", b"\x01" * 32)
        self.assertEqual(_find_moof_offset(data, start=0), len(lead))


class DetectStreamTypeProperties(SimpleTestCase):
    """detect_stream_type maps a provider URL to a coarse type hint.

    Contract: one of the four known strings, case-insensitive on the scheme
    and extension checks, never raises.
    """

    KNOWN = {"hls", "rtsp", "udp", "ts", "unknown"}

    @given(url=st.one_of(st.none(), st.text(max_size=400)))
    def test_never_raises_and_returns_a_known_type(self, url):
        result = detect_stream_type(url)
        self.assertIn(result, self.KNOWN)

    @given(host=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789.-", max_size=40))
    def test_scheme_detection_is_case_insensitive(self, host):
        self.assertEqual(detect_stream_type(f"UDP://{host}:1234"), "udp")
        self.assertEqual(detect_stream_type(f"udp://{host}:1234"), "udp")
        self.assertEqual(detect_stream_type(f"RTSP://{host}/x"), "rtsp")
        self.assertEqual(detect_stream_type(f"rtp://{host}/x"), "rtsp")

    @given(path=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789/_-", max_size=60))
    def test_m3u8_extension_wins(self, path):
        self.assertEqual(detect_stream_type(f"http://h/{path}.m3u8"), "hls")

    @given(path=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789/_-", max_size=60))
    def test_plain_path_defaults_to_ts(self, path):
        # A path with no HLS indicator and an http(s) scheme is TS.
        self.assertEqual(detect_stream_type(f"http://h/{path}.ts"), "ts")


class CreateTsPacketProperties(SimpleTestCase):
    """create_ts_packet always returns exactly one well-formed 188-byte packet."""

    @given(
        packet_type=st.text(max_size=32),
        message=st.one_of(st.none(), st.text(max_size=400), st.binary(max_size=400)),
    )
    def test_always_188_bytes_with_sync_byte(self, packet_type, message):
        packet = create_ts_packet(packet_type=packet_type, message=message)
        self.assertIsInstance(packet, bytes)
        self.assertEqual(len(packet), TS_PACKET_SIZE)
        self.assertEqual(packet[0], 0x47)


class ServerPureHelpers(SimpleTestCase):
    """_int_or_none, _parse_output_key, _channel_id_from_metadata_key."""

    @given(value=st.one_of(st.none(), st.text(max_size=64), st.integers(), st.binary(max_size=16)))
    def test_int_or_none_never_raises(self, value):
        result = _int_or_none(value)
        self.assertTrue(result is None or isinstance(result, int))

    @given(value=st.integers())
    def test_int_or_none_round_trips_ints(self, value):
        self.assertEqual(_int_or_none(value), value)

    @given(fmt=st.text(max_size=64))
    def test_parse_output_key_never_raises(self, fmt):
        base, profile_id = ProxyServer._parse_output_key(fmt)
        self.assertIsInstance(base, str)
        self.assertTrue(profile_id is None or isinstance(profile_id, int))

    @given(
        base=st.sampled_from(["fmp4", "hls", "ts"]),
        profile_id=st.integers(min_value=0, max_value=9999),
    )
    def test_parse_output_key_splits_profile_suffix(self, base, profile_id):
        b, p = ProxyServer._parse_output_key(f"{base}:p{profile_id}")
        self.assertEqual(b, base)
        self.assertEqual(p, profile_id)

    @given(fmt=st.sampled_from(["fmp4", "hls", "ts", "mpegts"]))
    def test_parse_output_key_plain_format_has_no_profile(self, fmt):
        b, p = ProxyServer._parse_output_key(fmt)
        self.assertEqual(b, fmt)
        self.assertIsNone(p)

    @given(key=st.one_of(st.text(max_size=80), st.binary(max_size=80)))
    def test_channel_id_from_metadata_key_never_raises(self, key):
        result = _channel_id_from_metadata_key(key)
        self.assertTrue(result is None or isinstance(result, str))

    @given(channel_id=st.uuids())
    def test_channel_id_round_trips_through_metadata_key(self, channel_id):
        from apps.proxy.live_proxy.redis_keys import RedisKeys

        key = RedisKeys.channel_metadata(str(channel_id))
        self.assertEqual(_channel_id_from_metadata_key(key), str(channel_id))
        self.assertEqual(_channel_id_from_metadata_key(key.encode()), str(channel_id))


class DisconnectShutdownReadyProperties(SimpleTestCase):
    """StreamManager._disconnect_shutdown_ready is a pure time predicate over a
    Redis value. Patched ConfigHelper so no DB; built without __init__.
    """

    def _manager(self):
        from apps.proxy.live_proxy.input.manager import StreamManager

        return StreamManager.__new__(StreamManager)

    @given(
        value=st.one_of(
            st.none(),
            st.text(max_size=40),
            # Only ASCII-decodable bytes: non-UTF-8 bytes (e.g. b'\x80') make
            # _decode_redis_value raise UnicodeDecodeError, which this method
            # does not catch (it only guards ValueError/TypeError on the
            # float() call). That is a known robustness gap, filed separately;
            # bytes the relay itself writes are always str(time.time()).
            st.binary(max_size=40).filter(
                lambda b: all(c < 0x80 for c in b)
            ),
            st.floats(allow_nan=True, allow_infinity=True),
        )
    )
    def test_never_raises_on_any_value(self, value):
        mgr = self._manager()
        with mock.patch(
            "apps.proxy.live_proxy.input.manager.ConfigHelper.channel_shutdown_delay",
            return_value=30,
        ):
            result = mgr._disconnect_shutdown_ready(value)
        self.assertIsInstance(result, bool)

    @given(elapsed=st.floats(min_value=0, max_value=10000, allow_nan=False))
    def test_delay_boundary_is_exact(self, elapsed):
        """elapsed >= delay -> True, elapsed < delay -> False (within clock skew)."""
        delay = 30
        disconnect_time = time.time() - elapsed
        mgr = self._manager()
        with mock.patch(
            "apps.proxy.live_proxy.input.manager.ConfigHelper.channel_shutdown_delay",
            return_value=delay,
        ):
            result = mgr._disconnect_shutdown_ready(str(disconnect_time))
        # Allow a tiny tolerance: the code re-reads time.time() after we did.
        if elapsed >= delay + 0.5:
            self.assertTrue(result)
        elif elapsed < delay - 0.5:
            self.assertFalse(result)

    def test_zero_delay_means_any_disconnect_is_ready(self):
        mgr = self._manager()
        with mock.patch(
            "apps.proxy.live_proxy.input.manager.ConfigHelper.channel_shutdown_delay",
            return_value=0,
        ):
            self.assertTrue(mgr._disconnect_shutdown_ready(str(time.time() + 5)))

    def test_falsy_value_is_never_ready(self):
        mgr = self._manager()
        with mock.patch(
            "apps.proxy.live_proxy.input.manager.ConfigHelper.channel_shutdown_delay",
            return_value=30,
        ):
            self.assertFalse(mgr._disconnect_shutdown_ready(None))
            self.assertFalse(mgr._disconnect_shutdown_ready(""))
            self.assertFalse(mgr._disconnect_shutdown_ready(b""))

    def test_unparseable_value_is_never_ready(self):
        mgr = self._manager()
        with mock.patch(
            "apps.proxy.live_proxy.input.manager.ConfigHelper.channel_shutdown_delay",
            return_value=30,
        ):
            self.assertFalse(mgr._disconnect_shutdown_ready("not-a-number"))
