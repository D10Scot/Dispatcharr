"""Recompute the provider-slot counters from ground truth (#513).

`profile_connections:{id}` and `server_group_connections:{group}:{fp}` carry
no TTL, no owner lease and, until this module, no reconciliation. They drift
both ways: over-count when a holder dies without releasing (a relay-go crash,
a release POST lost while the API restarts, a relay-uwsgi crash with VOD
sessions open, an abandoned catch-up session) and under-count when a counter
is written down under a live holder (#470, #471, a Redis restart). This
module periodically derives each counter from who actually holds a provider
connection and moves the counter toward that, under rules that keep it from
ever dropping a slot a live holder owns.

Ground truth, per counter:

- live: every channel the relay lists, attributed to the `m3u_profile_id` it
  reports (`GET /proxy/relay/channels`), except a channel whose run has
  already ended (`stopped`/`error`: its slot is released or being released);
- VOD: every `vod_persistent_connection:*` hash with `active_streams > 0`
  whose worker's liveness key exists, plus a seeded-never-started hash
  (`active_streams == 0`) while `now - created_at` is inside the VOD
  in-flight window (#513 constraint 6);
- catch-up: every `timeshift:pool:*` entry with `busy == "1"` whose worker's
  liveness key exists.

Records are selected by Redis type (a hash), never by the shape of the key:
both session ids reach the key verbatim from the client (VOD's
`<str:session_id>` path segment, catch-up's `?session_id=`), so a `:` in one
must not hide a live holder.

A credential counter's holders are attributed per holder and remembered in
the snapshot. A holder seen for the first time is attributed to the counter
its profile's release pointer (`profile_credential_release:{id}`, what that
profile's last reserve or switch counted against) names, else to the one its
configuration names today. A holder seen at the previous run on the same
profile keeps what it was attributed to then, because the pointer is one key
per profile and the first release on a profile deletes it while the
profile's other streams are still open (#356): re-deriving it every run would
let an admin making a pooled profile unlimited, changing its login or
deleting it mid-stream lower the shared counter under those streams. Such a
holder also gains the counter its profile's pointer or configuration names
now, when that differs and its version moved since the previous run: the
holder may have reserved again there (a VOD session re-reserves on reuse),
and an unmoved version proves it did not. Every ambiguity is resolved toward
counting a holder on one counter too many, never one too few. The carry
spans the same window as the write rule below: a holder absent from one run
keeps its slot (rule 2), so it keeps its attribution for that run too, and
one that returns next run is not re-derived as if first seen.

A VOD or catch-up record's worker is alive while `vod:worker:<worker_id>`
exists (apps/proxy/vod_proxy/held_records.py). Recency is never the signal.

The write rule, per counter K, at run N+1 against the snapshot run N saved:

1. K's version (slot_version:K) must be unchanged since run N read it, and
   the check is made by the slot script at write time, atomically with the
   write (connection_pool.reconcile_counter). Every writer bumps the version,
   so "unchanged" means nobody reserved, released or switched on K since run
   N -- and runs are spaced wider than the longest in-flight window on any
   surface (run_spacing_seconds), so every reservation K still holds is
   older than that window and its holder is visible now, or it leaked.
2. The counter moves only into [|V_N ∩ V_N+1|, |V_N ∪ V_N+1|], where V is
   the set of holder identities attributed to K at a run. A holder keeps its
   slot until it has been absent from two consecutive runs -- #513
   constraints 4 (a missing worker key) and 7 (a record whose holder is not
   visible) -- and earns a slot the counter lacks only once present at two
   consecutive runs. That also absorbs the two short races a single snapshot
   would lose: a holder that vanished just before its release lands (the
   relay unregisters a channel before its release POST; a VOD session drops
   to active_streams 0 a moment before its release), and a holder that
   became visible just before its reserve lands (a VOD session reused by a
   second request increments active_streams before it re-reserves).

An unreachable relay skips the run entirely and leaves the snapshot alone
(#513 constraint 3). relay_client.live_connections fails open by design, and
here that rule inverts: an empty live set would lower every live profile to
its VOD and catch-up share and lift the cap for every running channel.

Runs on the worker role, from a beat entry (dispatcharr/settings.py) every
BEAT_INTERVAL_SECONDS; the spacing is enforced here against Redis's own
clock, so an edited beat interval, a backlog of queued runs or two worker
containers can make runs no closer than run_spacing_seconds() apart.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from django.core.exceptions import ImproperlyConfigured

from apps.m3u.connection_pool import (
    credential_reservation,
    profile_connections_key,
    profile_credential_release_key,
    read_slot_versions,
    reconcile_counter,
)

logger = logging.getLogger(__name__)

SNAPSHOT_KEY = "slot_reconciler:snapshot"
LOCK_KEY = "slot_reconciler:lock"
LOCK_TTL_SECONDS = 120
BEAT_INTERVAL_SECONDS = 30.0
MIN_SPACING_SECONDS = 60.0
SPACING_FACTOR = 2
SNAPSHOT_TTL_RUNS = 10

VOD_KEY_PATTERN = "vod_persistent_connection:*"
_ENDED_RELAY_STATES = frozenset({"stopped", "error"})


def in_flight_windows() -> dict:
    """The longest a reservation can go unseen on each surface, in seconds.

    live:     the relay's tune budget, the bound on the next-source call inside
              which Channel.get_stream() reserves and after which the relay
              lists the channel (relay/httpapi/stream.go's tuneBudget, from
              the same constants apps/proxy/control_plane.py exports).
    vod:      the upstream connect-plus-first-byte timeout, per attempt, times
              the attempts (the reserve precedes the provider GET).
    catch_up: the pool lock's wait plus the operator-editable connect and
              chunk timeouts _open_upstream passes to requests.
    """
    from apps.proxy import control_plane
    from apps.proxy.config_helper import ConfigHelper
    from apps.proxy.vod_proxy.multi_worker_connection_manager import (
        UPSTREAM_ATTEMPTS,
        UPSTREAM_TIMEOUT,
    )
    from apps.timeshift.views import POOL_LOCK_WAIT_SECONDS

    live = (
        control_plane.ATTEMPTS * (control_plane.CONNECT_TIMEOUT + control_plane.READ_TIMEOUT)
        + control_plane.RETRY_DELAY
    )
    vod = UPSTREAM_ATTEMPTS * sum(UPSTREAM_TIMEOUT)
    catch_up = (
        POOL_LOCK_WAIT_SECONDS
        + float(ConfigHelper.connection_timeout())
        + float(ConfigHelper.chunk_timeout())
    )
    return {"live": float(live), "vod": float(vod), "catch_up": float(catch_up)}


def run_spacing_seconds(windows=None) -> float:
    """How far apart two runs must be: SPACING_FACTOR times the widest window, floored."""
    windows = windows or in_flight_windows()
    return max(MIN_SPACING_SECONDS, SPACING_FACTOR * max(windows.values()))


@dataclass
class RunResult:
    status: str  # "skipped", "snapshot" (first run: nothing to compare), "reconciled"
    reason: str = ""
    changes: list = field(default_factory=list)

    def as_dict(self):
        return {"status": self.status, "reason": self.reason, "changes": self.changes}


def _text(value):
    return value.decode() if isinstance(value, bytes) else value


def _int(value, default=0):
    try:
        return int(float(_text(value)))
    except (TypeError, ValueError):
        return default


class SlotReconciler:
    def __init__(self, redis_client=None, *, clock=None, list_channels=None):
        if redis_client is None:
            from core.utils import RedisClient

            redis_client = RedisClient.get_client()
        self.redis = redis_client
        self._clock = clock or self._redis_time
        if list_channels is None:
            from apps.proxy import relay_client

            list_channels = relay_client.list_channels
        self._list_channels = list_channels

    def _redis_time(self):
        seconds, micros = self.redis.time()
        return seconds + micros / 1_000_000

    # -- counters -----------------------------------------------------------

    def _counters(self):
        """The counters an admission check reads, from today's configuration.

        Returns (every counter key, {profile id: its profile counter},
        {profile id: the credential counter its configuration names}). A
        profile counter exists only for max_streams > 0 (a reserve does not
        count an unlimited profile); a credential counter for each pooled,
        limited profile with a fingerprint, shared by every profile whose
        login maps to it.
        """
        from apps.m3u.models import M3UAccountProfile

        profile_counter, config_credential = {}, {}
        profiles = M3UAccountProfile.objects.filter(max_streams__gt=0).select_related(
            "m3u_account__server_group"
        )
        for profile in profiles:
            profile_counter[profile.id] = profile_connections_key(profile.id)
            cred_key, _cap = credential_reservation(profile)
            if cred_key:
                config_credential[profile.id] = cred_key
        keys = set(profile_counter.values()) | set(config_credential.values())
        return keys, profile_counter, config_credential

    def _credential_attribution(self, holders, config_credential, carried, versions, before):
        """{holder identity: the credential counters it counts against}.

        holders is {identity: profile id} at this run; carried is the
        previous run's attribution, {identity: (profile id, counters)}; before
        is the previous run's {counter: (version, identities)}. See the module
        docstring for the rule.
        """
        profile_ids = sorted(set(holders.values()))
        if not profile_ids:
            return {}
        pointers = self.redis.mget([profile_credential_release_key(p) for p in profile_ids])
        current = {
            profile_id: _text(pointer) or config_credential.get(profile_id)
            for profile_id, pointer in zip(profile_ids, pointers)
        }
        attribution = {}
        for identity, profile_id in holders.items():
            now_key = current.get(profile_id)
            prior = carried.get(identity)
            if prior is None or prior[0] != profile_id:
                # First seen, or moved profile (a failover): the pointer, else
                # the configuration.
                attribution[identity] = {now_key} if now_key else set()
                continue
            keys = set(prior[1])
            if now_key and now_key not in keys:
                then_version = before[now_key][0] if now_key in before else 0
                if versions.get(now_key, then_version) != then_version:
                    keys.add(now_key)  # it may have reserved again there
            attribution[identity] = keys
        return attribution

    # -- ground truth ---------------------------------------------------------

    def _live_holders(self, channels):
        holders = {}
        for channel in channels:
            profile_id = channel.get("m3u_profile_id")
            if not profile_id or channel.get("state") in _ENDED_RELAY_STATES:
                continue
            holders[f"live:{channel.get('channel_id')}"] = int(profile_id)
        return holders

    def _scan_hashes(self, pattern, fields):
        # By type, never by key shape: a client-chosen session id may contain
        # ':'. timeshift:pool:<s>:lock and :superseded are strings, not hashes.
        records = {}
        for key in self.redis.scan_iter(match=pattern, count=1000, _type="hash"):
            key = _text(key)
            values = self.redis.hmget(key, fields)
            records[key] = dict(zip(fields, (_text(v) for v in values)))
        return records

    def _alive(self, worker_ids):
        from apps.proxy.vod_proxy.held_records import worker_key

        worker_ids = sorted({w for w in worker_ids if w})
        if not worker_ids:
            return set()
        present = self.redis.mget([worker_key(w) for w in worker_ids])
        return {w for w, value in zip(worker_ids, present) if value is not None}

    def _record_holders(self, now, vod_window):
        from apps.timeshift.redis_keys import TimeshiftRedisKeys

        vod = self._scan_hashes(
            VOD_KEY_PATTERN,
            ["m3u_profile_id", "active_streams", "worker_id", "created_at"],
        )
        pool = self._scan_hashes(
            TimeshiftRedisKeys.pool_scan_pattern(),
            ["profile_id", "busy", "worker_id"],
        )
        alive = self._alive(
            [r["worker_id"] for r in vod.values()] + [r["worker_id"] for r in pool.values()]
        )
        holders = {}
        for key, r in vod.items():
            profile_id = _int(r["m3u_profile_id"], None)
            if not profile_id:
                continue
            active = _int(r["active_streams"])
            if active > 0 and r["worker_id"] in alive:
                holders[f"vod:{key}"] = profile_id
            elif active <= 0 and now - _int(r["created_at"], 0) < vod_window:
                # Seeded, not started: the reserve preceded the provider GET.
                holders[f"vod:{key}"] = profile_id
        for key, r in pool.items():
            profile_id = _int(r["profile_id"], None)
            if profile_id and r["busy"] == "1" and r["worker_id"] in alive:
                holders[f"catchup:{key}"] = profile_id
        return holders

    # -- snapshot -------------------------------------------------------------

    def _load_snapshot(self):
        raw = self.redis.get(SNAPSHOT_KEY)
        if not raw:
            return None
        try:
            data = json.loads(_text(raw))
            return (
                float(data["taken_at"]),
                {k: (int(v[0]), set(v[1])) for k, v in data["counters"].items()},
                {k: (int(v[0]), set(v[1])) for k, v in data["attribution"].items()},
                set(data["present"]),
            )
        except (ValueError, KeyError, TypeError):
            logger.warning("Slot reconciler: discarding an unreadable snapshot")
            return None

    def _save_snapshot(
        self, taken_at, versions, identities, holders, attribution, carried, was_present, spacing
    ):
        # Attribution for every identity the two-run union still keeps: those
        # present now, plus those present at the previous run and absent now,
        # carried forward unchanged for this one run.
        kept = {
            identity: [prior[0], sorted(prior[1])]
            for identity, prior in carried.items()
            if identity in was_present and identity not in holders
        }
        payload = {
            "taken_at": taken_at,
            "counters": {
                k: [versions.get(k, 0), sorted(identities.get(k, ()))] for k in versions
            },
            "attribution": {
                **kept,
                **{
                    identity: [profile_id, sorted(attribution.get(identity, ()))]
                    for identity, profile_id in holders.items()
                },
            },
            "present": sorted(holders),
        }
        self.redis.set(
            SNAPSHOT_KEY, json.dumps(payload), ex=int(max(spacing * SNAPSHOT_TTL_RUNS, 600))
        )

    # -- the run --------------------------------------------------------------

    def run(self) -> RunResult:
        lock = self.redis.lock(LOCK_KEY, timeout=LOCK_TTL_SECONDS)
        if not lock.acquire(blocking=False):
            return RunResult("skipped", "another run holds the lock")
        try:
            return self._run()
        finally:
            try:
                lock.release()
            except Exception:
                pass

    def _run(self) -> RunResult:
        windows = in_flight_windows()
        spacing = run_spacing_seconds(windows)
        previous = self._load_snapshot()
        # The spacing check comes before the ORM pass, so a skipped tick (two
        # in three at the defaults) reads no profile or stream row. Checking
        # an earlier clock read than taken_at below is conservative.
        if previous is not None and self._clock() - previous[0] < spacing:
            return RunResult("skipped", f"less than {spacing:.0f}s since the last snapshot")
        # ORM next: no Redis read is older than it needs to be.
        counter_keys, profile_counter, config_credential = self._counters()

        # The version read and its timestamp come BEFORE any ground truth is
        # read: the next run's safety argument measures the spacing from here.
        taken_at = self._clock()
        versions = read_slot_versions(counter_keys, self.redis)

        try:
            answer = self._list_channels()
        except ImproperlyConfigured as exc:
            logger.warning(
                "Slot reconciler skipped: %s is misconfigured",
                getattr(exc, "var_name", None) or "the relay base URL",
            )
            return RunResult("skipped", "relay misconfigured")
        except Exception as exc:
            from apps.proxy import relay_client

            if isinstance(exc, (relay_client.RelayUnavailable, relay_client.RelayRefused)):
                logger.warning("Slot reconciler skipped: the relay could not answer: %s", exc)
                return RunResult("skipped", "relay unavailable")
            raise
        channels = answer.get("channels") if isinstance(answer, dict) else None
        if not isinstance(channels, list):
            # A 2xx body with no channel list is not an empty live set.
            logger.warning("Slot reconciler skipped: the relay's answer carried no channel list")
            return RunResult("skipped", "relay answer unusable")

        holders = self._live_holders(channels)
        holders.update(self._record_holders(taken_at, windows["vod"]))
        _then, before, carried, was_present = (
            previous if previous is not None else (None, {}, {}, set())
        )
        attribution = self._credential_attribution(
            holders, config_credential, carried, versions, before
        )
        identities = {key: set() for key in counter_keys}
        for identity, profile_id in holders.items():
            key = profile_counter.get(profile_id)
            if key:
                identities[key].add(identity)
            for key in attribution.get(identity, ()):
                if key in identities:
                    identities[key].add(identity)

        changes = []
        if previous is not None:
            for key, now_ids in identities.items():
                if key not in before:
                    continue
                expected, then_ids = before[key]
                if versions.get(key) != expected:
                    continue  # written since the last run: wait for a quiet interval
                floor = len(then_ids & now_ids)
                ceiling = len(then_ids | now_ids)
                status, was, became = reconcile_counter(key, expected, floor, ceiling, self.redis)
                if status == 1:
                    changes.append({"counter": key, "from": was, "to": became})
                    logger.info(
                        "Slot reconciler moved %s from %s to %s (holders: %s at both runs, %s at either)",
                        _loggable(key), was, became, floor, ceiling,
                    )
        self._save_snapshot(
            taken_at, versions, identities, holders, attribution, carried, was_present, spacing
        )
        if previous is None:
            logger.info("Slot reconciler took its first snapshot of %s counters", len(identities))
            return RunResult("snapshot")
        return RunResult("reconciled", changes=changes)


def _loggable(counter_key: str) -> str:
    """A counter's name without the credential fingerprint it embeds."""
    if counter_key.startswith("server_group_connections:"):
        group = counter_key.split(":")[1]
        return f"the shared-login counter of server group {group}"
    return counter_key


def reconcile_provider_slots() -> dict:
    return SlotReconciler().run().as_dict()
