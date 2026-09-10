"""Tests for the 2a subprocess harness's fake upstream, asset and faults."""

import urllib.error
import urllib.request

from django.test import SimpleTestCase

from .harness.asset import TS_PACKET_SIZE, TS_SYNC_BYTE, assert_ts_aligned, synthetic_ts
from .harness.faults import NOT_PORTED, PORTED_FAULTS, FaultStore
from .harness.upstream import FakeUpstream


class SyntheticAssetTests(SimpleTestCase):
    def test_asset_is_a_whole_number_of_packets(self):
        data = synthetic_ts(packets=7)
        self.assertEqual(len(data), 7 * TS_PACKET_SIZE)

    def test_every_packet_starts_with_the_sync_byte(self):
        data = synthetic_ts(packets=16)
        for offset in range(0, len(data), TS_PACKET_SIZE):
            self.assertEqual(data[offset], TS_SYNC_BYTE, f"packet at {offset}")

    def test_continuity_counter_increments_and_wraps_at_16(self):
        data = synthetic_ts(packets=20)
        counters = [data[i + 3] & 0x0F for i in range(0, len(data), TS_PACKET_SIZE)]
        self.assertEqual(counters[:17], [i % 16 for i in range(17)])

    def test_pid_is_carried_in_the_low_thirteen_bits(self):
        data = synthetic_ts(packets=2, pid=0x1FF)
        pid = ((data[1] & 0x1F) << 8) | data[2]
        self.assertEqual(pid, 0x1FF)

    def test_assert_ts_aligned_accepts_a_clean_stream(self):
        assert_ts_aligned(synthetic_ts(packets=4))

    def test_assert_ts_aligned_rejects_a_shifted_stream(self):
        with self.assertRaises(AssertionError):
            assert_ts_aligned(b"\x00" + synthetic_ts(packets=4))


class FaultVocabularyTests(SimpleTestCase):
    def test_the_vocabulary_covers_all_twelve_upstream_faults(self):
        self.assertEqual(len(PORTED_FAULTS), 8)
        self.assertEqual(len(NOT_PORTED), 4)
        self.assertEqual(set(PORTED_FAULTS) & set(NOT_PORTED), set())

    def test_every_not_ported_fault_carries_a_reason(self):
        for name, reason in NOT_PORTED.items():
            self.assertTrue(reason.strip(), f"{name} has no reason")

    def test_arming_an_unknown_fault_is_an_error(self):
        with self.assertRaises(ValueError):
            FaultStore().arm("no-such-fault")

    def test_arming_a_not_ported_fault_names_the_reason(self):
        with self.assertRaises(ValueError) as caught:
            FaultStore().arm("range-unsupported")
        self.assertIn("VOD", str(caught.exception))

    def test_arm_then_clear_round_trips(self):
        store = FaultStore()
        self.assertFalse(store.is_active("dead-air"))
        store.arm("dead-air")
        self.assertTrue(store.is_active("dead-air"))
        store.clear("dead-air")
        self.assertFalse(store.is_active("dead-air"))

    def test_config_of_returns_the_armed_configuration(self):
        store = FaultStore()
        store.arm("slow-trickle", rate=0.25)
        self.assertEqual(store.config_of("slow-trickle")["rate"], 0.25)

    def test_config_of_an_unarmed_fault_is_empty(self):
        self.assertEqual(FaultStore().config_of("slow-trickle"), {})


class FakeUpstreamTests(SimpleTestCase):
    def test_serves_ts_bytes(self):
        with FakeUpstream(payload=synthetic_ts(packets=32)) as up:
            with urllib.request.urlopen(up.url, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Content-Type"], "video/mp2t")
                body = response.read(32 * TS_PACKET_SIZE)
        assert_ts_aligned(body)

    def test_loops_the_payload_rather_than_ending(self):
        with FakeUpstream(payload=synthetic_ts(packets=4)) as up:
            with urllib.request.urlopen(up.url, timeout=5) as response:
                body = response.read(4 * TS_PACKET_SIZE * 3)
        self.assertEqual(len(body), 4 * TS_PACKET_SIZE * 3)
        assert_ts_aligned(body)

    def test_counts_requests(self):
        with FakeUpstream(payload=synthetic_ts(packets=2)) as up:
            self.assertEqual(up.request_count, 0)
            for _ in range(2):
                with urllib.request.urlopen(up.url, timeout=5) as response:
                    response.read(TS_PACKET_SIZE)
            self.assertEqual(up.request_count, 2)

    def test_not_found_fault_answers_404(self):
        with FakeUpstream() as up:
            up.faults.arm("not-found")
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(up.url, timeout=5)
            self.assertEqual(caught.exception.code, 404)

    def test_auth_failure_fault_answers_401(self):
        with FakeUpstream() as up:
            up.faults.arm("auth-failure")
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(up.url, timeout=5)
            self.assertEqual(caught.exception.code, 401)

    def test_connection_limit_fault_answers_429(self):
        with FakeUpstream() as up:
            up.faults.arm("connection-limit")
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(up.url, timeout=5)
            self.assertEqual(caught.exception.code, 429)

    def test_redirect_chain_fault_lands_on_the_stream(self):
        with FakeUpstream(payload=synthetic_ts(packets=2)) as up:
            up.faults.arm("redirect-chain", depth=3)
            with urllib.request.urlopen(up.url, timeout=5) as response:
                body = response.read(2 * TS_PACKET_SIZE)
        assert_ts_aligned(body)
        # One request for each hop plus the final one that serves bytes.
        self.assertEqual(up.request_count, 4)

    def test_non_ts_bytes_fault_answers_200_with_html(self):
        with FakeUpstream() as up:
            up.faults.arm("non-ts-bytes")
            with urllib.request.urlopen(up.url, timeout=5) as response:
                self.assertEqual(response.status, 200)
                body = response.read()
        self.assertNotEqual(body[:1], b"\x47")
        self.assertIn(b"<html", body.lower())

    def test_disconnect_fault_truncates_after_the_configured_bytes(self):
        with FakeUpstream(payload=synthetic_ts(packets=64)) as up:
            up.faults.arm("disconnect", after_bytes=4 * TS_PACKET_SIZE)
            with urllib.request.urlopen(up.url, timeout=5) as response:
                body = response.read()
        self.assertEqual(len(body), 4 * TS_PACKET_SIZE)

    def test_dead_air_fault_sends_headers_and_no_body(self):
        with FakeUpstream(payload=synthetic_ts(packets=8)) as up:
            up.faults.arm("dead-air")
            response = urllib.request.urlopen(up.url, timeout=5)
            try:
                self.assertEqual(response.status, 200)
                response.fp.raw._sock.settimeout(0.5)
                with self.assertRaises(OSError):
                    response.read(TS_PACKET_SIZE)
            finally:
                response.close()

    def test_every_ported_fault_can_be_armed_on_a_running_server(self):
        with FakeUpstream() as up:
            for fault in PORTED_FAULTS:
                up.faults.arm(fault)
                up.faults.clear(fault)
