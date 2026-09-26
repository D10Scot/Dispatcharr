"""The provider-slot reconciler, against a live Redis and the test database (#513).

The eleven tests #513 names, each an interleaving the reconciler must survive
without dropping a slot a live holder owns, plus the derived run spacing and
the beat entry. Redis is real because the property under test is what the
slot script does atomically at write time; the relay is a stub whose answer
each test sets; time is a fake clock the test advances past the run spacing.
Without Redis these skip, except under CI, where they fail.
"""

from __future__ import annotations

import os
import uuid
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase

from apps.channels.models import Channel, ChannelStream, Stream
from apps.m3u.connection_pool import (
    credential_reservation,
    profile_connections_key,
    release_profile_slot,
    reserve_profile_slot,
    slot_version_key,
)
from apps.m3u.models import M3UAccount, M3UAccountProfile, ServerGroup
from apps.proxy import relay_client, slot_reconciler
from apps.proxy.slot_reconciler import (
    LOCK_KEY,
    SNAPSHOT_KEY,
    SlotReconciler,
    in_flight_windows,
    run_spacing_seconds,
)
from apps.proxy.vod_proxy.held_records import HeldRecords, worker_key


def _text_of(value):
    return value.decode() if isinstance(value, bytes) else value


def _live_redis():
    from core.utils import RedisClient

    try:
        client = RedisClient.get_client(max_retries=1, retry_interval=0)
        if client is not None and client.ping():
            return client
    except Exception:
        pass
    return None


class ReconcilerTestCase(TestCase):
    redis = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.redis = _live_redis()

    def setUp(self):
        if self.redis is None:
            if os.environ.get("CI"):
                self.fail("Redis is not reachable under CI: these tests must run, not skip")
            self.skipTest("Redis not available")
        self.tag = uuid.uuid4().hex[:10]
        self.now = 1_000_000.0
        self.channels = []
        self.relay_error = None
        self.relay_answer = None  # when set, returned verbatim instead of the channel list
        self.cleanup = [SNAPSHOT_KEY, LOCK_KEY]
        self.redis.delete(SNAPSHOT_KEY, LOCK_KEY)
        self.addCleanup(self._clean)
        self.group = ServerGroup.objects.create(name=f"g-{self.tag}")
        self.account = M3UAccount.objects.create(
            name=f"acct-{self.tag}", account_type="XC", username="user", password="pass",
            server_url="http://xc.example.com", server_group=self.group, max_streams=10,
        )
        self.p1 = M3UAccountProfile.objects.get(m3u_account=self.account, is_default=True)
        self.p1.max_streams = 5
        self.p1.save()
        self.p2 = M3UAccountProfile.objects.create(
            m3u_account=self.account, name=f"p2-{self.tag}", is_default=False,
            is_active=True, max_streams=5, search_pattern="", replace_pattern="",
        )

    def _clean(self):
        keys = set(self.cleanup)
        for profile in M3UAccountProfile.objects.filter(m3u_account=self.account):
            pk = profile_connections_key(profile.id)
            keys |= {pk, slot_version_key(pk), f"profile_credential_release:{profile.id}"}
            cred, _cap = credential_reservation(profile)
            if cred:
                keys |= {cred, slot_version_key(cred)}
        self.redis.delete(*keys)

    # -- drivers --------------------------------------------------------------

    def list_channels(self):
        if self.relay_error is not None:
            raise self.relay_error
        if self.relay_answer is not None:
            return self.relay_answer
        return {"channels": list(self.channels), "count": len(self.channels)}

    def run_once(self):
        return SlotReconciler(
            self.redis, clock=lambda: self.now, list_channels=self.list_channels
        ).run()

    def tick(self):
        self.now += run_spacing_seconds() + 1

    def live(self, profile, name):
        return {"channel_id": f"{self.tag}-{name}", "state": "active", "m3u_profile_id": profile.id}

    def count(self, profile):
        return int(self.redis.get(profile_connections_key(profile.id)) or 0)

    def vod_hash(self, name, profile, *, active, worker, created_at=None, last_activity=None):
        key = f"vod_persistent_connection:{self.tag}-{name}"
        self.cleanup.append(key)
        self.redis.hset(key, mapping={
            "m3u_profile_id": profile.id,
            "active_streams": active,
            "worker_id": worker,
            "created_at": self.now if created_at is None else created_at,
            "last_activity": self.now if last_activity is None else last_activity,
        })
        return key

    def cred_count(self, profile):
        cred, _cap = credential_reservation(profile)
        return int(self.redis.get(cred) or 0)

    def pool_entry(self, name, profile, *, worker, busy="1"):
        key = f"timeshift:pool:{self.tag}-{name}"
        self.cleanup.append(key)
        self.redis.hset(key, mapping={"profile_id": profile.id, "busy": busy, "worker_id": worker})
        return key

    def live_worker(self, name):
        worker = f"host-{self.tag}-{name}"
        self.cleanup.append(worker_key(worker))
        HeldRecords(self.redis, worker).refresh_once()
        return worker


class OrphanTests(ReconcilerTestCase):
    def test_an_orphan_is_dropped_after_two_absent_runs(self):
        # A relay-go crash: the channel held a slot, the relay restarted
        # empty, and no release will ever come.
        reserve_profile_slot(self.p1, self.redis)
        self.channels = [self.live(self.p1, "a")]
        self.run_once()
        self.channels = []
        self.tick()
        self.run_once()
        self.assertEqual(self.count(self.p1), 1, "an orphan was dropped after one absent run")
        self.tick()
        self.run_once()
        self.assertEqual(self.count(self.p1), 0, "an orphan absent from two runs kept its slot")


class InFlightTests(ReconcilerTestCase):
    """A reservation whose holder is not visible yet must survive a run."""

    def _assert_survives(self, surface, reserve, visible):
        self.channels = [self.live(self.p1, "steady")]
        reserve_profile_slot(self.p1, self.redis)  # the steady holder
        self.run_once()
        self.tick()
        self.run_once()
        self.assertEqual(self.count(self.p1), 1)
        reserve()  # after this run's snapshot: in flight, not visible yet
        self.tick()
        self.run_once()
        self.assertEqual(self.count(self.p1), 2, f"an in-flight {surface} reservation was released")
        visible()
        self.tick()
        self.run_once()
        self.tick()
        self.run_once()
        self.assertEqual(self.count(self.p1), 2)

    def test_an_in_flight_live_reservation_is_not_released(self):
        self._assert_survives(
            "live",
            lambda: reserve_profile_slot(self.p1, self.redis),  # get_stream(), before the relay lists it
            lambda: self.channels.append(self.live(self.p1, "new")),
        )

    def test_an_in_flight_vod_reservation_is_not_released(self):
        worker = self.live_worker("vod")
        self._assert_survives(
            "VOD",
            lambda: reserve_profile_slot(self.p1, self.redis),  # mwcm reserves before creating the hash
            lambda: self.vod_hash("new", self.p1, active=1, worker=worker),
        )

    def test_an_in_flight_catch_up_reservation_is_not_released(self):
        worker = self.live_worker("cu")
        self._assert_survives(
            "catch-up",
            lambda: reserve_profile_slot(self.p1, self.redis),  # reserved; the pool lock not yet taken
            lambda: self.pool_entry("new", self.p1, worker=worker),
        )


class ReleaseThenTuneTests(ReconcilerTestCase):
    def test_a_release_then_a_tune_between_runs_is_not_clobbered(self):
        # R3-1's interleaving, where value stability fails: the counter reads 1
        # at run A and at run B, but it counts a different reservation each
        # time, and neither holder is visible at either run.
        self.run_once()  # the baseline: nothing held
        self.tick()
        reserve_profile_slot(self.p1, self.redis)  # tune x, in flight at A
        self.run_once()  # A: the version moved, so no write; the snapshot records 1
        release_profile_slot(self.p1.id, self.redis)  # x's connect fails
        reserve_profile_slot(self.p1, self.redis)  # tune y, in flight at B
        self.tick()
        self.run_once()  # B
        self.assertEqual(self.count(self.p1), 1, "a release then a tune between runs lost the tune's slot")


class FailoverTests(ReconcilerTestCase):
    def _tuned_channel(self, number=900):
        stream = Stream.objects.create(
            name=f"s-{self.tag}", url="http://xc.example.com/live/user/pass/1.ts",
            m3u_account=self.account,
        )
        channel = Channel.objects.create(channel_number=number, name=f"c-{self.tag}-{number}")
        ChannelStream.objects.create(channel=channel, stream=stream, order=0)
        self.cleanup += [f"channel_stream:{channel.id}", f"stream_profile:{stream.id}"]
        with mock.patch.object(relay_client, "channel_snapshot"):
            _stream_id, profile_id, _err, reserved = channel.get_stream()
        self.assertEqual((profile_id, reserved), (self.p1.id, True))
        return channel

    def test_a_profile_changing_failover_between_runs_is_not_clobbered(self):
        channel = self._tuned_channel(900)
        self.channels = [self.live(self.p1, "c")]
        self.run_once()
        # Failover: next-source's _commit moves the slot to p2. The relay's
        # list still says p1 until it takes up the new answer.
        self.assertTrue(channel.update_stream_profile(self.p2.id))
        self.tick()
        self.run_once()
        self.assertEqual(self.count(self.p2), 1, "a failover's reservation on the new profile was dropped")
        self.assertEqual(self.count(self.p1), 0)

    def test_a_same_login_failover_onto_an_unlimited_profile_keeps_the_shared_counter(self):
        # review round 1, finding 1: switch_profile_slot moves the credential
        # counter only when the fingerprint changes (connection_pool.py's
        # switch op, ARGV[3]). On a same-login failover the old counter keeps
        # the stream's slot, its version does not move, and the new profile's
        # pointer is not set. If the new profile is unlimited, it has no
        # credential counter at all, so a naive re-derivation attributes the
        # holder to nothing and the old counter drops under a live stream
        # two runs later.
        shared = credential_reservation(self.p1)[0]
        self.p2.max_streams = 0
        self.p2.save()
        channel = self._tuned_channel(901)
        self.assertEqual(int(self.redis.get(shared)), 1)
        self.channels = [self.live(self.p1, "c")]
        self.run_once()
        self.tick()
        self.run_once()
        self.assertTrue(channel.update_stream_profile(self.p2.id))
        self.assertEqual(int(self.redis.get(shared)), 1, "switch kept the shared slot (same login)")
        self.channels = [self.live(self.p2, "c")]  # the relay takes up the new answer
        for _ in range(3):
            self.tick()
            self.run_once()
        self.assertEqual(
            int(self.redis.get(shared) or 0), 1,
            "the shared counter dropped under a live stream after a same-login failover",
        )

    def test_a_same_login_failover_onto_a_limited_profile_without_a_pointer_keeps_the_shared_counter(self):
        # Control for the test above: p2 is limited (not unlimited), so its
        # configuration names the shared counter even with no pointer of its
        # own. This already passed before the fix; kept as a control so a
        # future edit cannot silently narrow the fix to the unlimited case.
        shared = credential_reservation(self.p1)[0]
        channel = self._tuned_channel(902)
        self.channels = [self.live(self.p1, "c")]
        self.run_once()
        self.tick()
        self.run_once()
        self.assertTrue(channel.update_stream_profile(self.p2.id))
        self.channels = [self.live(self.p2, "c")]
        for _ in range(3):
            self.tick()
            self.run_once()
        self.assertEqual(int(self.redis.get(shared) or 0), 1)


class RefusedReserveTests(ReconcilerTestCase):
    def test_a_refused_reserve_does_not_trigger_a_write(self):
        self.p1.max_streams = 1
        self.p1.save()
        reserve_profile_slot(self.p1, self.redis)
        self.channels = [self.live(self.p1, "a")]
        self.run_once()
        key = profile_connections_key(self.p1.id)
        version = int(self.redis.get(slot_version_key(key)) or 0)
        self.assertEqual(reserve_profile_slot(self.p1, self.redis)[0], False)
        self.assertEqual(
            int(self.redis.get(slot_version_key(key)) or 0), version,
            "a refused reserve moved the counter's version",
        )
        self.tick()
        result = self.run_once()
        self.assertEqual(result.changes, [], "a refused reserve made the reconciler write")
        self.assertEqual(self.count(self.p1), 1)

    def test_a_refused_reserve_does_not_block_a_due_correction(self):
        # The same refusal, on a counter that has leaked one slot: the leak is
        # still corrected on schedule, because the refusal moved no version.
        self.p1.max_streams = 2
        self.p1.save()
        reserve_profile_slot(self.p1, self.redis)
        reserve_profile_slot(self.p1, self.redis)  # the second one leaked
        self.channels = [self.live(self.p1, "a")]
        self.run_once()
        self.tick()
        # A viewer retrying against the full profile. At the seed each refusal
        # was an INCR then a DECR -- two writes -- so a profile refusing once
        # per interval would never be quiet long enough to correct.
        self.assertFalse(reserve_profile_slot(self.p1, self.redis)[0])
        self.run_once()
        self.assertEqual(self.count(self.p1), 1, "a refused reserve blocked the leak's correction")


class RelayUnreachableTests(ReconcilerTestCase):
    def test_an_unreachable_relay_leaves_every_counter_untouched(self):
        for error in (
            relay_client.RelayUnavailable("down", transport=True),
            relay_client.RelayRefused(403, "/proxy/relay/channels"),
            ImproperlyConfigured("DISPATCHARR_RELAY_BASE_URL"),
        ):
            with self.subTest(error=type(error).__name__):
                self.redis.delete(SNAPSHOT_KEY)
                self.redis.set(profile_connections_key(self.p1.id), 3)  # drifted, no holder anywhere
                self.channels = []
                self.relay_error = None
                self.run_once()
                snapshot = self.redis.get(SNAPSHOT_KEY)
                self.relay_error = error
                for _ in range(3):
                    self.tick()
                    result = self.run_once()
                    self.assertEqual(result.status, "skipped", "an unreachable relay did not skip the run")
                self.assertEqual(self.count(self.p1), 3, "an unreachable relay moved profile_connections")
                self.assertEqual(self.redis.get(SNAPSHOT_KEY), snapshot)


class RelayAnswerTests(ReconcilerTestCase):
    def test_a_relay_answer_without_a_channel_list_skips_the_run(self):
        # A 2xx body with no list must not read as "no live channels".
        for answer in ({}, {"channels": None}, {"channels": "garbled"}, ["not", "an", "object"]):
            with self.subTest(answer=answer):
                self.redis.delete(SNAPSHOT_KEY)
                self.redis.set(profile_connections_key(self.p1.id), 3)
                self.relay_answer = None
                self.run_once()
                snapshot = self.redis.get(SNAPSHOT_KEY)
                self.relay_answer = answer
                for _ in range(3):
                    self.tick()
                    self.assertEqual(
                        self.run_once().status, "skipped",
                        "a relay answer with no channel list was read as an empty live set",
                    )
                self.assertEqual(self.count(self.p1), 3)
                self.assertEqual(self.redis.get(SNAPSHOT_KEY), snapshot)


class ColonSessionIdTests(ReconcilerTestCase):
    """A client chooses both session ids (VOD's path segment, catch-up's
    ?session_id=), and either may contain ':'. Such a holder is still a holder."""

    def _assert_kept(self, surface, make_holder):
        worker = self.live_worker(surface)
        reserve_profile_slot(self.p1, self.redis)
        make_holder(worker)
        for _ in range(3):
            self.run_once()
            self.tick()
        self.assertEqual(
            self.count(self.p1), 1,
            f"a live {surface} holder with ':' in its session id lost its slot",
        )

    def test_a_vod_holder_with_a_colon_in_its_session_id_keeps_its_slot(self):
        self._assert_kept("VOD", lambda w: self.vod_hash("a:b", self.p1, active=1, worker=w))

    def test_a_catch_up_holder_with_a_colon_in_its_session_id_keeps_its_slot(self):
        def holder(worker):
            self.pool_entry("a:b", self.p1, worker=worker)
            # The pool's lock and superseded marker share the key prefix and
            # are strings, not hashes; they must neither count nor break the scan.
            for suffix in ("lock", "superseded"):
                key = f"timeshift:pool:{self.tag}-other:{suffix}"
                self.cleanup.append(key)
                self.redis.set(key, "1")

        self._assert_kept("catch-up", holder)


class CredentialAttributionTests(ReconcilerTestCase):
    """A shared-login counter counts what was reserved against it, not what
    the configuration would reserve against it today."""

    def _two_live_streams_on_one_login(self):
        self.assertEqual(credential_reservation(self.p1)[0], credential_reservation(self.p2)[0])
        reserve_profile_slot(self.p1, self.redis)
        reserve_profile_slot(self.p2, self.redis)
        self.channels = [self.live(self.p1, "a"), self.live(self.p2, "b")]
        self.assertEqual(self.cred_count(self.p2), 2)
        self.run_once()

    def _assert_still_two(self):
        for _ in range(3):
            self.tick()
            self.run_once()
        self.assertEqual(
            self.cred_count(self.p2), 2, "the shared-login counter dropped under two live streams"
        )

    def test_making_a_pooled_profile_unlimited_mid_stream_keeps_its_holders_counted(self):
        self._two_live_streams_on_one_login()
        self.p1.max_streams = 0
        self.p1.save()
        self._assert_still_two()

    def test_deleting_a_pooled_profile_mid_stream_keeps_its_holders_counted(self):
        self._two_live_streams_on_one_login()
        self.cleanup.append(f"profile_credential_release:{self.p1.id}")
        self.p1.delete()
        self._assert_still_two()

    # The release pointer is one key per profile, and the first release on a
    # profile deletes it while the profile's other streams are open (#356).

    def pointer(self, profile):
        return self.redis.get(f"profile_credential_release:{profile.id}")

    def change_login(self, profile, to):
        self.cleanup.append(f"profile_credential_release:{profile.id}")
        profile.search_pattern, profile.replace_pattern = "/user/", f"/{to}/"
        profile.save()
        key, _cap = credential_reservation(profile)
        self.cleanup += [key, slot_version_key(key)]
        return key

    def _one_of_two_streams_ended(self):
        """Two streams on p1, one released: p1's pointer is gone, one stream is open."""
        self.shared = credential_reservation(self.p2)[0]
        self.assertEqual(credential_reservation(self.p1)[0], self.shared)
        reserve_profile_slot(self.p1, self.redis)
        reserve_profile_slot(self.p1, self.redis)
        self.channels = [self.live(self.p1, "a"), self.live(self.p1, "b")]
        self.run_once()
        self.tick()
        release_profile_slot(self.p1.id, self.redis)
        self.channels = [self.live(self.p1, "a")]
        self.assertIsNone(self.pointer(self.p1))
        self.assertEqual(int(self.redis.get(self.shared)), 1)
        self.run_once()

    def _three_spaced_runs(self):
        for _ in range(3):
            self.tick()
            self.run_once()

    def test_making_a_pooled_profile_unlimited_after_one_of_its_two_streams_ended_keeps_the_other_counted(self):
        self._one_of_two_streams_ended()
        self.p1.max_streams = 0
        self.p1.save()
        self._three_spaced_runs()
        self.assertEqual(
            int(self.redis.get(self.shared) or 0), 1,
            "the shared-login counter dropped under a live stream",
        )

    def test_deleting_a_pooled_profile_after_one_of_its_two_streams_ended_keeps_the_other_counted(self):
        self._one_of_two_streams_ended()
        self.cleanup.append(f"profile_credential_release:{self.p1.id}")
        self.p1.delete()
        self._three_spaced_runs()
        self.assertEqual(
            int(self.redis.get(self.shared) or 0), 1,
            "the shared-login counter dropped under a live stream",
        )

    def test_a_holder_absent_for_one_run_keeps_its_attribution_through_an_edit(self):
        # The union keeps a holder's slot across one absent run; the carried
        # attribution must span the same window, or the returning holder is
        # re-derived from the edited configuration.
        self._one_of_two_streams_ended()
        self.p1.max_streams = 0
        self.p1.save()
        self.tick()
        self.run_once()
        survivor = self.channels
        self.channels = []  # missing from one successful relay list
        self.tick()
        self.run_once()
        self.assertEqual(
            int(self.redis.get(self.shared) or 0), 1,
            "the shared counter dropped before the absent holder returned",
        )
        self.channels = survivor
        self._three_spaced_runs()
        self.assertEqual(
            int(self.redis.get(self.shared) or 0), 1,
            "a single-run blip plus a config edit dropped the shared counter under a live stream",
        )

    def test_a_login_change_with_no_reserve_on_the_new_login_moves_nothing(self):
        # Both directions of exactness: the survivor stays on the login it
        # reserved against, and is not counted on one it never touched.
        self._one_of_two_streams_ended()
        new = self.change_login(self.p1, "other")
        self.assertNotEqual(new, self.shared)
        self._three_spaced_runs()
        self.assertEqual(
            int(self.redis.get(self.shared) or 0), 1,
            "the old login's counter dropped under a live stream",
        )
        self.assertEqual(
            int(self.redis.get(new) or 0), 0,
            "a stream was counted on a login it never reserved against",
        )

    def test_a_login_change_then_a_new_stream_keeps_the_old_streams_on_the_old_login(self):
        old = credential_reservation(self.p1)[0]
        reserve_profile_slot(self.p1, self.redis)
        reserve_profile_slot(self.p1, self.redis)
        self.channels = [self.live(self.p1, "a"), self.live(self.p1, "b")]
        self.run_once()
        self.tick()
        self.run_once()
        new = self.change_login(self.p1, "other")
        reserve_profile_slot(self.p1, self.redis)  # the new stream; p1's pointer now names `new`
        self.assertEqual(_text_of(self.pointer(self.p1)), new)
        self.channels.append(self.live(self.p1, "c"))
        self._three_spaced_runs()
        self.assertEqual(
            int(self.redis.get(old) or 0), 2,
            "the old login's counter dropped under the streams still reserved against it",
        )
        # Residual R8: which of the three reserved on the new login since the
        # previous run cannot be told apart, so the old two are counted there
        # too -- one too many each, never one too few.
        self.assertEqual(
            int(self.redis.get(new) or 0), 3,
            "the new login's counter is not the union R8 states",
        )

    def test_a_holder_that_reserved_again_on_its_profiles_new_login_is_counted_there(self):
        # A VOD session re-reserves on reuse under the same identity.
        worker = self.live_worker("w")
        self.vod_hash("v", self.p1, active=1, worker=worker)
        reserve_profile_slot(self.p1, self.redis)
        self.run_once()
        self.tick()
        self.run_once()
        new = self.change_login(self.p1, "other")
        release_profile_slot(self.p1.id, self.redis)
        reserve_profile_slot(self.p1, self.redis)
        self.assertEqual(int(self.redis.get(new) or 0), 1)
        self._three_spaced_runs()
        self.assertEqual(
            int(self.redis.get(new) or 0), 1,
            "a holder that reserved again on its profile's new login lost its slot there",
        )


class WorkerLivenessTests(ReconcilerTestCase):
    def test_a_paused_viewer_is_counted_while_its_worker_lives_and_dropped_two_runs_after_it_dies(self):
        vod_worker = self.live_worker("vod")
        cu_worker = self.live_worker("cu")
        reserve_profile_slot(self.p1, self.redis)
        reserve_profile_slot(self.p2, self.redis)
        # Two hours since either moved a byte: recency would call both dead.
        self.vod_hash("paused", self.p1, active=1, worker=vod_worker, last_activity=self.now - 7200)
        self.pool_entry("paused", self.p2, worker=cu_worker)
        for _ in range(4):
            self.run_once()
            self.tick()
        self.assertEqual(
            (self.count(self.p1), self.count(self.p2)), (1, 1),
            "a paused viewer with a live worker lost its slot",
        )
        self.redis.delete(worker_key(vod_worker), worker_key(cu_worker))  # both processes die
        self.run_once()
        self.assertEqual((self.count(self.p1), self.count(self.p2)), (1, 1),
                         "a dead worker's records dropped after one run")
        self.tick()
        self.run_once()
        self.assertEqual((self.count(self.p1), self.count(self.p2)), (0, 0),
                         "a dead worker's records were still counted two runs after it died")

    def test_a_young_catch_up_entry_without_a_worker_key_yet_keeps_its_slot(self):
        # #513 constraint 4/5: a busy pool entry is stamped with worker_id
        # before its process's first hold(), so its vod:worker:<id> key may
        # not exist yet. The reserve already moved the counter's version, so
        # the reconciler makes no write that interval rather than dropping
        # the entry; the next run, after its first refresh, counts it.
        reserve_profile_slot(self.p1, self.redis)  # steady live holder
        self.channels = [self.live(self.p1, "steady")]
        self.run_once()
        self.tick()
        self.run_once()
        worker = f"host-{self.tag}-young"
        self.cleanup.append(worker_key(worker))
        reserve_profile_slot(self.p1, self.redis)
        self.pool_entry("young", self.p1, worker=worker)  # stamped, no hold() yet: no worker key
        self.tick()
        self.run_once()  # N: entry busy, no worker key; version moved: no write
        HeldRecords(self.redis, worker).refresh_once()  # first chunk, inside the window
        self.tick()
        self.run_once()  # N+1: quiet interval, entry now counted
        self.assertEqual(self.count(self.p1), 2, "a young catch-up entry lost its slot")
        for _ in range(3):
            self.tick()
            self.run_once()
        self.assertEqual(self.count(self.p1), 2)


class SeededHashTests(ReconcilerTestCase):
    def test_a_seeded_never_started_hash_is_not_counted_past_its_window(self):
        window = in_flight_windows()["vod"]
        reserve_profile_slot(self.p1, self.redis)
        self.vod_hash("seeded", self.p1, active=0, worker="host-that-died-1", created_at=self.now)
        self.run_once()
        self.now += window - 1
        self.redis.delete(SNAPSHOT_KEY)  # a fresh baseline inside the window
        self.run_once()
        self.tick()
        self.run_once()
        self.tick()
        self.run_once()
        self.assertEqual(self.count(self.p1), 0, "a seeded hash was counted past the VOD window")

    def test_a_seeded_hash_inside_its_window_is_counted(self):
        self.p1.max_streams = 5
        self.p1.save()
        self.redis.set(profile_connections_key(self.p1.id), 0)  # the reserve's count was lost
        self.vod_hash("seeded", self.p1, active=0, worker="w", created_at=self.now + 10 * run_spacing_seconds())
        self.run_once()
        self.tick()
        self.run_once()
        self.assertEqual(self.count(self.p1), 1, "a seeded hash inside its window was not counted")


class ConcurrentIncrTests(ReconcilerTestCase):
    def test_a_concurrent_incr_is_not_clobbered(self):
        reserve_profile_slot(self.p1, self.redis)  # leaked: nothing ever lists it
        self.run_once()
        self.tick()
        real = slot_reconciler.reconcile_counter

        def racing(key, expected, floor, ceiling, client):
            if key == profile_connections_key(self.p1.id):
                reserve_profile_slot(self.p1, self.redis)  # lands between the reads and the write
            return real(key, expected, floor, ceiling, client)

        with mock.patch.object(slot_reconciler, "reconcile_counter", side_effect=racing):
            self.run_once()
        self.assertEqual(self.count(self.p1), 2, "a concurrent INCR was clobbered")


class SpacingTests(ReconcilerTestCase):
    def test_the_spacing_follows_the_widest_window_including_the_catch_up_timeouts(self):
        from apps.proxy import control_plane
        from apps.proxy.vod_proxy.multi_worker_connection_manager import (
            UPSTREAM_ATTEMPTS,
            UPSTREAM_TIMEOUT,
        )
        from apps.timeshift.views import POOL_LOCK_WAIT_SECONDS

        windows = in_flight_windows()
        # The relay's tuneBudget, from the constants it is built from.
        self.assertAlmostEqual(
            windows["live"],
            control_plane.ATTEMPTS * (control_plane.CONNECT_TIMEOUT + control_plane.READ_TIMEOUT)
            + control_plane.RETRY_DELAY,
        )
        self.assertEqual(windows["vod"], UPSTREAM_ATTEMPTS * sum(UPSTREAM_TIMEOUT))
        self.assertEqual(
            run_spacing_seconds(windows),
            max(slot_reconciler.MIN_SPACING_SECONDS, slot_reconciler.SPACING_FACTOR * max(windows.values())),
        )
        with mock.patch("apps.proxy.config_helper.ConfigHelper.connection_timeout", return_value=60), \
                mock.patch("apps.proxy.config_helper.ConfigHelper.chunk_timeout", return_value=30):
            self.assertEqual(
                run_spacing_seconds(),
                slot_reconciler.SPACING_FACTOR * (POOL_LOCK_WAIT_SECONDS + 60 + 30),
            )

    def test_the_default_spacing_is_80_seconds(self):
        # One literal pin: at the shipped defaults the VOD window (40 s) wins.
        self.assertEqual(run_spacing_seconds(), 80.0)

    def test_a_run_inside_the_spacing_reads_no_row(self):
        self.run_once()
        self.now += run_spacing_seconds() - 1
        run_spacing_seconds()  # anything the spacing itself reads is not the point here
        with self.assertNumQueries(0):
            self.assertEqual(self.run_once().status, "skipped")

    def test_a_run_inside_the_spacing_writes_nothing(self):
        self.redis.set(profile_connections_key(self.p1.id), 2)  # leaked twice, never held
        self.run_once()
        self.now += run_spacing_seconds() - 1
        self.assertEqual(self.run_once().status, "skipped")
        self.assertEqual(self.count(self.p1), 2, "a run inside the spacing wrote a counter")
        self.now += 2
        self.run_once()  # absent at both runs, a full spacing apart
        self.assertEqual(self.count(self.p1), 0)
