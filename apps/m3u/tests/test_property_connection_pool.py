"""Property tests for the shared-connection-pool counters (issue #145; seam #146).

Surfaces, with their line at seed a54b09a9, all in ``apps/m3u/connection_pool.py``:

- ``_safe_decr`` (``:232``)
- ``reserve_profile_slot`` (``:280``) and its credential half
  ``_reserve_server_group_slot_for_profile`` (``:261``)
- ``release_profile_slot`` (``:316``)

The Redis stand-in is in-module and implements only what these functions call.
The credential fingerprint is patched to a constant, so the tests need no
database. ``get_profile_credential_fingerprint`` reads ``Stream`` rows, and
it is a different surface.

The #146 seam: at seed ``_safe_decr`` returns early on ``current <= 0`` and
leaves a negative counter negative forever (the keys have no TTL). The
INCR-first reservation then admits streams past ``max_streams`` until the
counter climbs back. C-5 repairs the counter in both places.
"""

from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.m3u import connection_pool
from apps.m3u.connection_pool import (
    _safe_decr,
    profile_connections_key,
    release_profile_slot,
    reserve_profile_slot,
    server_group_connections_key,
)

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

FINGERPRINT = "f" * 64
GROUP_ID = 7
CRED_KEY = server_group_connections_key(GROUP_ID, FINGERPRINT)


class FakeRedis:
    """In-memory stand-in for the five commands connection_pool uses."""

    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key):
        value = self.data.get(key)
        return None if value is None else str(value).encode()

    def set(self, key, value, ex=None):
        try:
            self.data[key] = int(value)
        except (TypeError, ValueError):
            self.data[key] = value

    def incr(self, key):
        self.data[key] = int(self.data.get(key, 0)) + 1
        return self.data[key]

    def decr(self, key):
        self.data[key] = int(self.data.get(key, 0)) - 1
        return self.data[key]

    def delete(self, key):
        self.data.pop(key, None)

    def count(self, key):
        return int(self.data.get(key, 0))


def _profile(max_streams, pooled, profile_id=1):
    group = SimpleNamespace(id=GROUP_ID) if pooled else None
    return SimpleNamespace(
        id=profile_id, pk=profile_id, max_streams=max_streams,
        m3u_account=SimpleNamespace(server_group=group),
    )


def _fixed_fingerprint():
    return mock.patch.object(
        connection_pool, "get_profile_credential_fingerprint", return_value=FINGERPRINT
    )


class SafeDecrProperties(SimpleTestCase):
    @given(start=st.none() | st.integers(min_value=-10, max_value=20))
    @example(start=-1)  # #146: shrunk counterexample, left at -1.
    @example(start=-3)  # #146: the issue's drifted credential counter.
    def test_safe_decr_lands_on_one_less_but_never_below_zero(self, start):
        redis = FakeRedis({} if start is None else {"k": start})
        _safe_decr(redis, "k")
        self.assertEqual(redis.count("k"), max((start or 0) - 1, 0))


class ReserveProfileSlotProperties(SimpleTestCase):
    @given(max_streams=st.integers(min_value=1, max_value=6), extra=st.integers(min_value=1, max_value=4))
    def test_a_profile_admits_exactly_max_streams_then_refuses_as_profile_full(self, max_streams, extra):
        redis = FakeRedis()
        profile = _profile(max_streams, pooled=False)
        results = [reserve_profile_slot(profile, redis) for _ in range(max_streams + extra)]
        self.assertEqual([r[0] for r in results], [True] * max_streams + [False] * extra)
        self.assertEqual({r[2] for r in results[max_streams:]}, {"profile_full"})
        self.assertEqual(redis.count(profile_connections_key(profile.id)), max_streams)

    @given(attempts=st.integers(min_value=1, max_value=8), pooled=st.booleans())
    def test_an_unlimited_profile_always_reserves_and_counts_nothing(self, attempts, pooled):
        redis = FakeRedis({CRED_KEY: 3})
        with _fixed_fingerprint():
            for _ in range(attempts):
                self.assertEqual(reserve_profile_slot(_profile(0, pooled), redis), (True, 0, None))
        self.assertEqual(redis.data, {CRED_KEY: 3})

    @given(
        start=st.integers(min_value=-5, max_value=6),
        max_streams=st.integers(min_value=1, max_value=4),
        extra=st.integers(min_value=1, max_value=3),
    )
    @example(start=-3, max_streams=1, extra=3)  # #146: -3 admitted four streams against a cap of one.
    def test_the_credential_cap_holds_whatever_the_counter_drifted_to(self, start, max_streams, extra):
        redis = FakeRedis({CRED_KEY: start})
        admitted = 0
        with _fixed_fingerprint():
            for i in range(max_streams + extra):
                # A distinct profile per attempt, each with room of its own, so
                # only the shared credential counter can refuse.
                ok, _, reason = reserve_profile_slot(_profile(max_streams, True, profile_id=i + 1), redis)
                admitted += ok
                if not ok:
                    self.assertEqual(reason, "credential_full")
        self.assertEqual(admitted, max(0, max_streams - max(start, 0)))


class ReserveReleaseConservationProperties(SimpleTestCase):
    @given(
        start=st.integers(min_value=0, max_value=3),
        ops=st.lists(st.sampled_from(("reserve", "release")), max_size=12),
        profiles=st.integers(min_value=1, max_value=3),
        data=st.data(),
    )
    def test_counters_track_the_streams_held_one_stream_per_profile(self, start, ops, profiles, data):
        """Every release returns exactly what its reserve took, and nothing goes negative.

        The domain is restricted to one stream per profile at a time. At seed,
        ``_remember_credential_release_key`` (``connection_pool.py:241``) keeps
        ONE release key per profile id, and the first release deletes it
        (``:257``). A second stream on the same pooled profile therefore
        never returns its credential slot. That is a defect filed separately
        (#356), not behaviour this test blesses. Widen ``held`` to a
        multiset once it is fixed.
        """
        redis = FakeRedis({CRED_KEY: start})
        held = set()
        with _fixed_fingerprint():
            for op in ops:
                pid = data.draw(st.integers(min_value=1, max_value=profiles))
                if op == "reserve" and pid not in held:
                    ok, _, _ = reserve_profile_slot(_profile(10, True, profile_id=pid), redis)
                    self.assertTrue(ok)
                    held.add(pid)
                elif op == "release":
                    release_profile_slot(pid, redis)
                    held.discard(pid)
                for p in range(1, profiles + 1):
                    self.assertEqual(redis.count(profile_connections_key(p)), int(p in held))
                self.assertEqual(redis.count(CRED_KEY), start + len(held))
