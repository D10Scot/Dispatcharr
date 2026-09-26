"""The provider-slot Lua script, against a live Redis (#513 constraint 1; #470; #471).

Every write to profile_connections:{id} and server_group_connections:{g}:{fp}
goes through connection_pool's one script, and every such write bumps
slot_version:<counter> in the same step. These tests run the real script on
the Redis the suite already uses (the same client TestVodActiveStreamsRealRedis
reaches), because atomicity is the property under test and an in-memory fake
cannot show it.

Without Redis they skip -- except under CI, where a missing Redis is a broken
environment and the class fails instead, the way relay/channel's real-ffmpeg
pin fails rather than skips when CI is set.
"""

from __future__ import annotations

import os
import threading
import uuid
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.m3u import connection_pool
from apps.m3u.connection_pool import (
    profile_connections_key,
    profile_credential_release_key,
    read_slot_versions,
    reconcile_counter,
    release_profile_slot,
    reserve_profile_slot,
    slot_version_key,
    switch_profile_slot,
)
from apps.m3u.tests.slot_script_fake import SlotScriptFakeMixin

# CI-deterministic profile, byte-identical to tests/test_redaction.py's.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")


def live_redis():
    from core.utils import RedisClient

    try:
        client = RedisClient.get_client(max_retries=1, retry_interval=0)
        if client is not None and client.ping():
            return client
    except Exception:
        pass
    return None


class LiveRedisTestCase(SimpleTestCase):
    """A per-test key namespace on the live Redis, deleted afterwards."""

    redis = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.redis = live_redis()

    def setUp(self):
        if self.redis is None:
            if os.environ.get("CI"):
                self.fail("Redis is not reachable under CI: these tests must run, not skip")
            self.skipTest("Redis not available")
        # Profile ids and group ids from a range no fixture uses, per test.
        self.base = 900_000 + (uuid.uuid4().int % 90_000) * 10

    def tearDown(self):
        if self.redis is None:
            return
        for pattern in (
            f"*profile_connections:{self.base}*",
            f"*server_group_connections:{self.base}:*",
            f"profile_credential_release:{self.base}*",
            f"stream_profile:{self.base}*",
        ):
            keys = list(self.redis.scan_iter(match=pattern, count=1000))
            if keys:
                self.redis.delete(*keys)

    def profile(self, offset, max_streams, *, login=None):
        """A profile stand-in: in ServerGroup `self.base` when login is set."""
        return SimpleNamespace(
            id=self.base + offset,
            pk=self.base + offset,
            max_streams=max_streams,
            login=login,
        )

    def cred_key(self, login):
        return f"server_group_connections:{self.base}:{login}"

    def patched_logins(self):
        """Resolve the credential counter from the stand-in's `login`, no ORM."""
        return mock.patch.multiple(
            connection_pool,
            get_enforced_server_group_for_profile=lambda p: (
                SimpleNamespace(id=self.base) if p.login else None
            ),
            _credential_counter_key=lambda p, g: self.cred_key(p.login),
            get_profile_credential_fingerprint=lambda p: p.login,
        )

    def value(self, key):
        raw = self.redis.get(key)
        return None if raw is None else int(raw)

    def version(self, key):
        return int(self.redis.get(slot_version_key(key)) or 0)


class SlotScriptVersionTests(LiveRedisTestCase):
    """Every counter write bumps that counter's version, and nothing else does."""

    def test_each_write_bumps_the_version_of_the_counter_it_writes(self):
        p = self.profile(1, 2, login="a")
        pk, ck = profile_connections_key(p.id), self.cred_key("a")
        with self.patched_logins():
            self.assertEqual(reserve_profile_slot(p, self.redis), (True, 1, None))
            self.assertEqual((self.version(pk), self.version(ck)), (1, 1))
            release_profile_slot(p.id, self.redis)
            self.assertEqual((self.value(pk), self.value(ck)), (0, 0))
            self.assertEqual((self.version(pk), self.version(ck)), (2, 2))
            # A release with nothing held writes nothing and bumps nothing.
            release_profile_slot(p.id, self.redis)
            self.assertEqual((self.version(pk), self.version(ck)), (2, 2))

    def test_a_refused_reserve_writes_nothing_and_bumps_nothing(self):
        p = self.profile(1, 1, login="a")
        q = self.profile(2, 1, login="a")  # same login, room of its own
        pk, qk, ck = (
            profile_connections_key(p.id),
            profile_connections_key(q.id),
            self.cred_key("a"),
        )
        with self.patched_logins():
            self.assertTrue(reserve_profile_slot(p, self.redis)[0])
            before = {k: (self.value(k), self.version(k)) for k in (pk, qk, ck)}
            self.assertEqual(reserve_profile_slot(p, self.redis), (False, 1, "profile_full"))
            self.assertEqual(reserve_profile_slot(q, self.redis), (False, 0, "credential_full"))
            after = {k: (self.value(k), self.version(k)) for k in (pk, qk, ck)}
        self.assertEqual(after, before, "a refused reserve wrote a counter or moved a version")

    def test_a_switch_bumps_both_profile_versions_in_one_step(self):
        old, new = self.profile(1, 2, login="a"), self.profile(2, 2, login="b")
        ok, nk = profile_connections_key(old.id), profile_connections_key(new.id)
        sp = f"stream_profile:{self.base}7"
        with self.patched_logins():
            reserve_profile_slot(old, self.redis)
            self.assertTrue(switch_profile_slot(old, new, sp, self.redis))
        self.assertEqual((self.value(ok), self.value(nk)), (0, 1))
        self.assertEqual((self.version(ok), self.version(nk)), (2, 1))
        self.assertEqual((self.value(self.cred_key("a")), self.value(self.cred_key("b"))), (0, 1))
        self.assertEqual(self.redis.get(sp), str(new.id))
        self.assertEqual(
            self.redis.get(profile_credential_release_key(new.id)), self.cred_key("b")
        )

    def test_a_switch_refused_by_the_new_login_writes_nothing(self):
        old, new = self.profile(1, 2, login="a"), self.profile(2, 1, login="b")
        sp = f"stream_profile:{self.base}7"
        with self.patched_logins():
            reserve_profile_slot(old, self.redis)
            self.redis.set(self.cred_key("b"), 1)
            watched = [
                profile_connections_key(old.id),
                profile_connections_key(new.id),
                self.cred_key("a"),
                self.cred_key("b"),
                profile_credential_release_key(old.id),
                sp,
            ]
            before = {k: (self.redis.get(k), self.version(k)) for k in watched}
            self.assertFalse(switch_profile_slot(old, new, sp, self.redis))
            after = {k: (self.redis.get(k), self.version(k)) for k in watched}
        self.assertEqual(after, before)


class SlotScriptRepairTests(LiveRedisTestCase):
    """#471 on the profile counter, #470 on the credential counter."""

    def test_a_negative_profile_counter_does_not_lift_max_streams(self):
        # #471: at the seed the INCR-first check admitted from -3 against a cap of 1.
        p = self.profile(1, 1)
        pk = profile_connections_key(p.id)
        self.redis.set(pk, -3)
        with self.patched_logins():
            results = [reserve_profile_slot(p, self.redis)[0] for _ in range(3)]
        self.assertEqual(results, [True, False, False], "a negative profile counter lifted the cap (#471)")
        self.assertEqual(self.value(pk), 1)

    def test_a_release_repairs_a_negative_profile_counter(self):
        # #471: at the seed `if current > 0` left it negative forever.
        pk = profile_connections_key(self.base + 1)
        self.redis.set(pk, -2)
        release_profile_slot(self.base + 1, self.redis)
        self.assertEqual(self.value(pk), 0)

    def _interleaved(self, first, second, hook_key, hook_op):
        """Run `first` and `second` on two threads, pausing `first` right after
        its `hook_op` on `hook_key` until `second` has finished. The seed's
        Python reserve/release have a gap there; the script has none, so
        under the script the hook never fires and the two simply serialise."""
        real = self.redis
        paused = threading.Event()
        resume = threading.Event()

        class Hooked:
            def __init__(self, owner):
                self._owner = owner

            def __getattr__(self, name):
                attr = getattr(real, name)
                if name != hook_op:
                    return attr

                def hooked(key, *a, **kw):
                    out = attr(key, *a, **kw)
                    if key == hook_key and threading.current_thread().name == "first":
                        paused.set()
                        resume.wait(5)
                    return out

                return hooked

        results = {}
        t1 = threading.Thread(target=lambda: results.update(first=first(Hooked(self))), name="first")
        t1.start()
        paused.wait(0.5)  # under the script nothing pauses; under the seed this is the gap
        results["second"] = second(real)
        resume.set()
        t1.join(5)
        return results

    def test_470_reserve_side_race_admits_one_stream_from_minus_one_with_a_cap_of_one(self):
        # #470's first interleaving: A INCRs to 0, B INCRs to 1 and is admitted,
        # A SETs 1 and is also admitted -- two streams against a cap of one.
        a, b = self.profile(1, 1, login="a"), self.profile(2, 1, login="a")
        ck = self.cred_key("a")
        self.redis.set(ck, -1)
        with self.patched_logins():
            results = self._interleaved(
                lambda r: reserve_profile_slot(a, r)[0],
                lambda r: reserve_profile_slot(b, r)[0],
                hook_key=ck,
                hook_op="incr",
            )
        admitted = [results["first"], results["second"]].count(True)
        self.assertEqual(admitted, 1, f"{admitted} streams admitted against a cap of one (#470)")
        self.assertEqual(self.value(ck), 1)

    def test_470_release_side_race_leaves_the_counter_equal_to_the_streams_held(self):
        # #470's second interleaving: the releaser reads -2, two reserves repair
        # and are admitted, then the releaser SETs 0 -- two live streams, counter 0.
        r_prof = self.profile(1, 5, login="a")
        x, y = self.profile(2, 5, login="a"), self.profile(3, 5, login="a")
        ck = self.cred_key("a")
        self.redis.set(ck, -2)
        self.redis.set(profile_credential_release_key(r_prof.id), ck)

        def two_reserves(r):
            return [reserve_profile_slot(x, r)[0], reserve_profile_slot(y, r)[0]]

        with self.patched_logins():
            results = self._interleaved(
                lambda r: release_profile_slot(r_prof.id, r),
                two_reserves,
                hook_key=ck,
                hook_op="get",
            )
        self.assertEqual(results["second"], [True, True])
        self.assertEqual(self.value(ck), 2, "a release lost two live streams from the count (#470)")


class ReconcileOpTests(LiveRedisTestCase):
    """The op the reconciler writes through: a version-guarded clamp."""

    def test_a_moved_version_blocks_the_write(self):
        p = self.profile(1, 5)
        pk = profile_connections_key(p.id)
        with self.patched_logins():
            reserve_profile_slot(p, self.redis)
            seen = read_slot_versions([pk], self.redis)[pk]
            release_profile_slot(p.id, self.redis)
            reserve_profile_slot(p, self.redis)  # 1 -> 0 -> 1: same value, new version
        self.assertEqual(reconcile_counter(pk, seen, 0, 0, self.redis), (-1, 1, 1))
        self.assertEqual(self.value(pk), 1)

    def test_an_unmoved_version_clamps_and_does_not_bump(self):
        pk = profile_connections_key(self.base + 1)
        self.redis.set(pk, 4)
        seen = read_slot_versions([pk], self.redis)[pk]
        self.assertEqual(reconcile_counter(pk, seen, 1, 2, self.redis), (1, 4, 2))
        self.assertEqual(reconcile_counter(pk, seen, 0, 3, self.redis), (0, 2, 2))
        self.assertEqual(reconcile_counter(pk, seen, 3, 5, self.redis), (1, 2, 3))
        self.assertEqual(self.version(pk), seen)

    def test_an_absent_counter_clamped_to_zero_is_not_created(self):
        pk = profile_connections_key(self.base + 1)
        self.assertEqual(reconcile_counter(pk, 0, 0, 0, self.redis), (0, 0, 0))
        self.assertIsNone(self.redis.get(pk))


class _DictRedis(SlotScriptFakeMixin):
    """The smallest fake the shim runs on: string values, like a decoded client."""

    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None):
        self.data[key] = str(value)

    def delete(self, key):
        self.data.pop(key, None)


class SlotScriptFakeParityTests(LiveRedisTestCase):
    """slot_script_fake.py must answer exactly as the Lua does.

    The same sequence runs through the real script on Redis and through the
    fake, from the same starting values, and both the returns and every key's
    final value must match.
    """

    def _run(self, client, steps):
        a, b, c = self.profile(1, 2, login="a"), self.profile(2, 1, login="b"), self.profile(3, 0)
        profiles = {"a": a, "b": b, "c": c}
        out = []
        with self.patched_logins():
            for step in steps:
                op, *rest = step
                if op == "reserve":
                    out.append(reserve_profile_slot(profiles[rest[0]], client))
                elif op == "release":
                    release_profile_slot(profiles[rest[0]].id, client)
                    out.append(None)
                elif op == "switch":
                    out.append(switch_profile_slot(
                        profiles[rest[0]], profiles[rest[1]], f"stream_profile:{self.base}9", client
                    ))
                elif op == "reconcile":
                    key = profile_connections_key(profiles[rest[0]].id)
                    out.append(reconcile_counter(key, rest[1], rest[2], rest[3], client))
        return out

    def _keys(self):
        ids = [self.base + i for i in (1, 2, 3)]
        keys = []
        for pid in ids:
            keys += [profile_connections_key(pid), profile_credential_release_key(pid)]
        keys += [self.cred_key("a"), self.cred_key("b"), f"stream_profile:{self.base}9"]
        return keys + [slot_version_key(k) for k in list(keys)]

    def _assert_parity(self, start, steps):
        names = {"base": self.base, "p1": self.base + 1, "p3": self.base + 3}
        for key, value in start.items():
            self.redis.set(key.format(**names), value)
        fake = _DictRedis()
        for key, value in start.items():
            fake.set(key.format(**names), value)
        real_out = self._run(self.redis, steps)
        fake_out = self._run(fake, steps)
        self.assertEqual(fake_out, real_out)
        for key in self._keys():
            real_value = self.redis.get(key)
            self.assertEqual(fake.get(key), real_value, key)

    def test_reserve_release_refusal_and_repair_sequences_agree(self):
        self._assert_parity(
            # c is unlimited, so nothing reserves its counter back up from -4:
            # only a release's repair can move it.
            {
                "profile_connections:{p1}": "-2",
                "profile_connections:{p3}": "-4",
                "server_group_connections:{base}:b": "-1",
            },
            [("reserve", "a"), ("reserve", "a"), ("reserve", "a"), ("reserve", "b"),
             ("reserve", "b"), ("reserve", "c"), ("release", "a"), ("release", "a"),
             ("release", "b"), ("release", "c")],
        )

    def test_switch_and_reconcile_sequences_agree(self):
        self._assert_parity(
            {"server_group_connections:{base}:b": "1"},
            [("reserve", "a"), ("switch", "a", "b"), ("release", "b"), ("switch", "a", "b"),
             ("switch", "a", "c"), ("reconcile", "a", 3, 0, 0), ("reconcile", "c", 1, 0, 0),
             ("reconcile", "c", 0, 2, 2)],
        )


# Five profiles: a, b and c share login "x" (so a full shared login refuses a
# reserve and a switch with credential_full), d has login "y", e is in no
# group; c is unlimited, so nothing but a release's repair moves its counter.
_PROFILES = {"a": (1, 2, "x"), "b": (2, 1, "x"), "c": (3, 0, "x"), "d": (4, 1, "y"), "e": (5, 2, None)}
_NAMES = sorted(_PROFILES)
_START = st.none() | st.integers(min_value=-3, max_value=3)
_OPS = st.lists(
    st.one_of(
        st.tuples(st.just("reserve"), st.sampled_from(_NAMES)),
        st.tuples(st.just("release"), st.sampled_from(_NAMES)),
        st.tuples(st.just("switch"), st.sampled_from(_NAMES), st.sampled_from(_NAMES)),
    ),
    max_size=15,
)


class SlotScriptFakeParityProperties(LiveRedisTestCase):
    """The fake answers as the Lua does for any sequence, checked after every step.

    Every counter test that runs on an in-memory fake exercises
    slot_script_fake.py, not the Lua. This property is what ties the two
    together: random reserve/release/switch sequences over a shared login and
    drifted (negative, absent or full) starting counters, run on the real
    script and on the fake, with the return and every key compared after
    each operation.
    """

    @given(
        profile_starts=st.fixed_dictionaries({n: _START for n in _NAMES}),
        cred_starts=st.fixed_dictionaries({"x": _START, "y": _START}),
        ops=_OPS,
    )
    def test_the_fake_matches_the_lua_after_every_step(self, profile_starts, cred_starts, ops):
        self.base += 100  # a fresh namespace per example; tearDown's patterns still cover it
        profiles = {
            n: self.profile(off, cap, login=login) for n, (off, cap, login) in _PROFILES.items()
        }
        keys = []
        for p in profiles.values():
            keys += [profile_connections_key(p.id), profile_credential_release_key(p.id)]
        keys += [self.cred_key("x"), self.cred_key("y"), f"stream_profile:{self.base}9"]
        keys += [slot_version_key(k) for k in list(keys)]
        fake = _DictRedis()
        try:
            for n, value in profile_starts.items():
                if value is not None:
                    self.redis.set(profile_connections_key(profiles[n].id), value)
                    fake.set(profile_connections_key(profiles[n].id), value)
            for login, value in cred_starts.items():
                if value is not None:
                    self.redis.set(self.cred_key(login), value)
                    fake.set(self.cred_key(login), value)
            with self.patched_logins():
                for step, op in enumerate(ops):
                    results = []
                    for client in (self.redis, fake):
                        if op[0] == "reserve":
                            results.append(reserve_profile_slot(profiles[op[1]], client))
                        elif op[0] == "release":
                            results.append(release_profile_slot(profiles[op[1]].id, client))
                        else:
                            results.append(switch_profile_slot(
                                profiles[op[1]], profiles[op[2]], f"stream_profile:{self.base}9", client
                            ))
                    self.assertEqual(results[1], results[0], f"step {step} {op}: the fake answered differently")
                    for key in keys:
                        self.assertEqual(
                            fake.get(key), self.redis.get(key),
                            f"step {step} {op}: {key} differs between the fake and the Lua",
                        )
        finally:
            self.redis.delete(*keys)
