"""Property-based tests for the M3U shared-connection-pool counters.

These encode invariants read directly from apps/m3u/connection_pool.py, using
an in-memory Redis stand-in (no DB, no real Redis). The profile under test has
no ServerGroup, so only the per-profile counter is exercised — the credential
pool path is covered separately by the DB-backed tests in
test_connection_pool.py.

Invariants asserted:

- ``reserve_profile_slot`` on an unlimited profile (``max_streams == 0``) never
  increments the profile counter and always succeeds.
- ``reserve_profile_slot`` on a limited profile succeeds exactly
  ``max_streams`` times against a fresh counter, then fails with
  ``failure_reason == "profile_full"`` — and a failed reserve leaves the
  counter at ``max_streams`` (INCR-then-DECR rolls the attempt back).
- Every successful reserve followed by ``release_profile_slot`` returns the
  counter to its prior value (net-zero conservation) and the counter never
  goes negative.
- ``_safe_decr`` never lets *its own* decrement drive a key below 0 and never
  raises, for any starting value (including absent keys). Note: it deliberately
  does not repair a key that was *already* negative — ``current <= 0`` returns
  early and leaves a pre-existing negative value untouched. (A negative counter
  silently disabling the ServerGroup cap is a separate finding, not asserted
  here.)

All tests are ``SimpleTestCase``-based and use a derandomized CI profile so
runs stay fast and reproducible.
"""

from types import SimpleNamespace

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.m3u.connection_pool import (
    _safe_decr,
    profile_connections_key,
    release_profile_slot,
    reserve_profile_slot,
)

# CI-deterministic profile (registered/loaded at import; the Django test runner
# has no pytest-style conftest hook). derandomize keeps runs reproducible;
# deadline=None because CI container timing is noisy.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")


class FakeRedis:
    """Minimal in-memory Redis stand-in matching connection_pool's usage."""

    def __init__(self):
        self._data = {}

    def get(self, key):
        val = self._data.get(key)
        if val is None:
            return None
        return str(val).encode()

    def set(self, key, value, ex=None):
        try:
            self._data[key] = int(value)
        except (ValueError, TypeError):
            self._data[key] = value

    def incr(self, key):
        self._data[key] = self._data.get(key, 0) + 1
        return self._data[key]

    def decr(self, key):
        self._data[key] = self._data.get(key, 0) - 1
        return self._data[key]

    def delete(self, key):
        self._data.pop(key, None)


def _profile(profile_id, max_streams):
    """Profile stand-in with no ServerGroup (server_group attribute absent)."""
    account = SimpleNamespace(server_group=None)
    return SimpleNamespace(
        id=profile_id, max_streams=max_streams, m3u_account=account
    )


def _count(redis, profile_id):
    return int(redis.get(profile_connections_key(profile_id)) or 0)


class ReserveReleaseConservationTests(SimpleTestCase):
    @given(profile_id=st.integers(min_value=1, max_value=1000))
    def test_unlimited_profile_never_increments_counter(self, profile_id):
        redis = FakeRedis()
        profile = _profile(profile_id, max_streams=0)
        for _ in range(5):
            reserved, count, reason = reserve_profile_slot(profile, redis)
            self.assertTrue(reserved)
            self.assertIsNone(reason)
        self.assertEqual(_count(redis, profile_id), 0)

    @given(
        profile_id=st.integers(min_value=1, max_value=1000),
        max_streams=st.integers(min_value=1, max_value=8),
    )
    def test_limited_profile_succeeds_exactly_max_times(self, profile_id, max_streams):
        redis = FakeRedis()
        profile = _profile(profile_id, max_streams)
        for _ in range(max_streams):
            reserved, _, reason = reserve_profile_slot(profile, redis)
            self.assertTrue(reserved)
            self.assertIsNone(reason)
        # Next reserve must fail with profile_full and roll its INCR back.
        reserved, _, reason = reserve_profile_slot(profile, redis)
        self.assertFalse(reserved)
        self.assertEqual(reason, "profile_full")
        self.assertEqual(_count(redis, profile_id), max_streams)

    @given(
        profile_id=st.integers(min_value=1, max_value=1000),
        max_streams=st.integers(min_value=1, max_value=8),
        n_ops=st.integers(min_value=1, max_value=12),
    )
    def test_reserve_release_is_net_zero_and_never_negative(
        self, profile_id, max_streams, n_ops
    ):
        redis = FakeRedis()
        profile = _profile(profile_id, max_streams)
        held = 0
        for _ in range(n_ops):
            reserved, _, _ = reserve_profile_slot(profile, redis)
            if reserved:
                held += 1
                self.assertEqual(_count(redis, profile_id), held)
            # Release everything reserved so far and confirm return to zero.
            for _ in range(held):
                release_profile_slot(profile_id, redis)
            self.assertEqual(_count(redis, profile_id), 0)
            held = 0
        self.assertGreaterEqual(_count(redis, profile_id), 0)


class SafeDecrPropertyTests(SimpleTestCase):
    @given(
        key_seed=st.integers(min_value=0, max_value=10**4),
        start=st.integers(min_value=0, max_value=20),
    )
    def test_own_decr_never_goes_below_zero_and_never_raises(self, key_seed, start):
        """A non-negative key is never driven below 0 by _safe_decr itself."""
        redis = FakeRedis()
        key = f"k:{key_seed}"
        redis._data[key] = start
        _safe_decr(redis, key)
        final = int(redis.get(key) or 0)
        self.assertGreaterEqual(final, 0)
        # A single decr from `start` lands on max(start - 1, 0).
        self.assertEqual(final, max(start - 1, 0))

    @given(key_seed=st.integers(min_value=0, max_value=10**4),
           start=st.integers(min_value=-10, max_value=-1))
    def test_pre_negative_key_is_left_untouched(self, key_seed, start):
        """Documented (non-)behavior: _safe_decr does not repair a key that was
        already negative — it returns early and leaves the value as-is."""
        redis = FakeRedis()
        key = f"k:{key_seed}"
        redis._data[key] = start
        _safe_decr(redis, key)
        self.assertEqual(int(redis.get(key) or 0), start)

    @given(key_seed=st.integers(min_value=0, max_value=10**4))
    def test_absent_key_stays_zero(self, key_seed):
        redis = FakeRedis()
        key = f"absent:{key_seed}"
        _safe_decr(redis, key)
        self.assertEqual(int(redis.get(key) or 0), 0)
