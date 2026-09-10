"""Tests for the 2a subprocess harness's fake upstream, asset and faults."""

from django.test import SimpleTestCase

from .harness.asset import TS_PACKET_SIZE, TS_SYNC_BYTE, assert_ts_aligned, synthetic_ts
from .harness.faults import NOT_PORTED, PORTED_FAULTS, FaultStore


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
