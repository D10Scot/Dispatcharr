"""
Shared connection pool enforcement for M3U accounts in the same ServerGroup.

Profile selection rotates across M3UAccountProfile rows using each profile's own
Redis counter (the pre-pool behavior). When an account belongs to a ServerGroup, a credential-scoped counter is checked on reserve/release
so accounts sharing the same provider login share one limit without blocking
unrelated logins on the same group. Account profiles with max_streams=0 skip
credential enforcement for that profile.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Literal, Optional, Tuple

logger = logging.getLogger(__name__)

ReserveFailureReason = Literal["profile_full", "credential_full"]

PROFILE_CONNECTIONS_KEY = "profile_connections:{profile_id}"
PROFILE_CREDENTIAL_RELEASE_KEY = "profile_credential_release:{profile_id}"
SERVER_GROUP_CONNECTIONS_KEY = "server_group_connections:{group_id}:{fingerprint}"

_XC_URL_CREDENTIALS_RE = re.compile(
    r"/(?:live|movie|series)/([^/]+)/([^/]+)/",
    re.IGNORECASE,
)


def profile_connections_key(profile_id: int) -> str:
    return PROFILE_CONNECTIONS_KEY.format(profile_id=profile_id)


def profile_credential_release_key(profile_id: int) -> str:
    """Redis key storing the credential counter to release when the profile row is gone."""
    return PROFILE_CREDENTIAL_RELEASE_KEY.format(profile_id=profile_id)


def server_group_connections_key(group_id: int, fingerprint: str) -> str:
    """Redis key for per-credential usage within a ServerGroup."""
    return SERVER_GROUP_CONNECTIONS_KEY.format(
        group_id=group_id,
        fingerprint=fingerprint[:16],
    )


def compute_credential_fingerprint(username: str, password: str) -> Optional[str]:
    """Return a stable hash for grouping accounts with the same IPTV login."""
    if not username or not password:
        return None
    normalized = f"{username.strip().casefold()}\0{password.strip()}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def extract_credentials_from_stream_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse username/password embedded in an Xtream-style stream URL."""
    if not url:
        return None, None
    match = _XC_URL_CREDENTIALS_RE.search(url)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def _fingerprint_from_profile_stream_url(profile) -> Optional[str]:
    """STD/M3U: fingerprint from a sample stream URL after profile rewrite."""
    from apps.channels.models import Stream

    sample_url = (
        Stream.objects.filter(m3u_account=profile.m3u_account)
        .exclude(url="")
        .values_list("url", flat=True)
        .first()
    )
    if not sample_url:
        return None

    try:
        from apps.proxy.next_source import transform_url

        transformed = transform_url(
            sample_url,
            profile.search_pattern or "",
            profile.replace_pattern or "",
        )
        url_user, url_pass = extract_credentials_from_stream_url(
            transformed or sample_url
        )
        return compute_credential_fingerprint(url_user or "", url_pass or "")
    except Exception as exc:
        logger.debug(
            "Could not derive profile %s fingerprint from stream URL: %s",
            profile.pk,
            exc,
        )
        return None


def get_profile_credential_fingerprint(profile) -> Optional[str]:
    """Fingerprint for credentials this profile uses at playback time."""
    m3u_account = profile.m3u_account

    if m3u_account.account_type == "XC":
        try:
            from apps.m3u.tasks import get_transformed_credentials

            _url, username, password = get_transformed_credentials(m3u_account, profile)
            fingerprint = compute_credential_fingerprint(username or "", password or "")
            if fingerprint:
                return fingerprint
        except Exception as exc:
            logger.debug(
                "Could not resolve transformed credentials for profile %s: %s",
                profile.pk,
                exc,
            )

    fingerprint = _fingerprint_from_profile_stream_url(profile)
    if fingerprint:
        return fingerprint

    return compute_credential_fingerprint(
        m3u_account.username or "",
        m3u_account.password or "",
    )


def get_enforced_server_group_for_profile(profile):
    """Return the ServerGroup for credential pooling when the account is assigned to one."""
    group = profile.m3u_account.server_group
    if group:
        return group
    return None


def _credential_counter_key(profile, group) -> Optional[str]:
    fingerprint = get_profile_credential_fingerprint(profile)
    if not fingerprint:
        return None
    return server_group_connections_key(group.id, fingerprint)


def get_profile_connection_count(profile, redis_client) -> int:
    return int(redis_client.get(profile_connections_key(profile.id)) or 0)


def get_credential_connection_count(profile, redis_client) -> int:
    group = get_enforced_server_group_for_profile(profile)
    if not group:
        return 0
    cred_key = _credential_counter_key(profile, group)
    if not cred_key:
        return 0
    return int(redis_client.get(cred_key) or 0)


def profile_has_capacity_for_selection(profile, redis_client) -> bool:
    """Per-profile capacity check used when rotating across profiles on one account."""
    if profile.max_streams == 0:
        return True
    return get_profile_connection_count(profile, redis_client) < profile.max_streams


def group_has_capacity_for_profile(profile, redis_client) -> bool:
    # Profiles with max_streams=0 skip credential enforcement entirely. An unlimited
    # profile in a pooled group can still stream while other accounts share the login.
    group = get_enforced_server_group_for_profile(profile)
    if not group or profile.max_streams == 0:
        return True
    cred_key = _credential_counter_key(profile, group)
    if not cred_key:
        return True
    return int(redis_client.get(cred_key) or 0) < profile.max_streams


def pool_has_capacity_for_profile(profile, redis_client) -> bool:
    """Non-mutating check before reserve: profile slot and credential slot if applicable."""
    return profile_has_capacity_for_selection(profile, redis_client) and group_has_capacity_for_profile(
        profile, redis_client
    )


# The reason both get_stream()s give when every profile they tried was full
# (apps/channels/models.py). next-source adds `capacity` to exactly this refusal.
ALL_PROFILES_FULL = "All active M3U profiles have reached maximum connection limits"


def credential_sibling_profile_ids(profile) -> list[int]:
    """Every profile whose reserve counts against `profile`'s credential counter,
    `profile` included and active or not; [] when it has none (no ServerGroup,
    max_streams 0, or no fingerprint: credential_reservation's (None, 0))."""
    key, _cap = credential_reservation(profile)
    if key is None:
        return []
    from apps.m3u.models import M3UAccountProfile

    group = get_enforced_server_group_for_profile(profile)
    candidates = M3UAccountProfile.objects.filter(
        m3u_account__server_group=group
    ).select_related("m3u_account")
    return sorted(p.id for p in candidates if credential_reservation(p)[0] == key)


def blocking_profile_ids(profiles, redis_client) -> list[int]:
    """Read-only: of `profiles`, each one full on its own counter
    (not profile_has_capacity_for_selection) names itself alone; each one
    whose own counter has room but whose credential counter is full
    (not group_has_capacity_for_profile: the credential_full refusal, R72)
    names every credential sibling, itself included. Sorted ascending, no
    duplicates. Writes nothing."""
    named: set[int] = set()
    for profile in profiles:
        if not profile_has_capacity_for_selection(profile, redis_client):
            named.add(profile.id)
        elif not group_has_capacity_for_profile(profile, redis_client):
            named.update(credential_sibling_profile_ids(profile))
            named.add(profile.id)
    return sorted(named)


def profile_available_for_channel_switch(
    profile, redis_client, *, channel_already_on_profile: bool
) -> bool:
    """
    Non-mutating capacity check when selecting a profile for an in-flight channel.

    If the channel already holds this profile's slots, skip re-checking capacity.
    """
    if channel_already_on_profile:
        return True
    return pool_has_capacity_for_profile(profile, redis_client)


# --------------------------------------------------------------------------
# The provider-slot script (#513 constraint 1; #470; #471).
#
# EVERY write to a provider-slot counter -- profile_connections:{id} and
# server_group_connections:{group}:{fp} -- happens inside this one Lua script.
# reserve, release and switch each increment slot_version:<counter key> in
# the same atomic step as the counter write, because each is a holder's own
# action. The reconciler's own write (the reconcile op below) is not a
# holder's action and deliberately bumps no version: it reads a counter's
# version at one run and writes the counter at the next only if the version
# has not moved, so "unchanged" means "nobody wrote it", never "it was
# written and written back" (a release then a tune between runs) -- and its
# own clamp must not count as such a write, or the next run would see a
# version it moved itself and refuse to check again.
#
# The script also makes both repairs atomic that were a GET then a SET in
# Python: a counter found below zero is treated as zero by a reserve and set
# to zero by a release (#470 for the credential counter, #471 for the profile
# counter). A reserve checks both caps BEFORE writing either counter, so a
# refused reserve writes nothing at all -- no INCR-then-DECR -- and bumps no
# version.
#
# The one key this script touches without it being passed in KEYS is the
# credential counter a release pointer names (profile_credential_release:{id}
# stores it at reserve time). That is fine on the single, non-cluster Redis
# every deployment runs, and it is the reason release does not need an ORM
# read to find the counter (PoolEnforcementTests pins that).
# --------------------------------------------------------------------------
SLOT_VERSION_KEY_PREFIX = "slot_version:"

_SLOT_SCRIPT = """
-- provider_slot
local op = ARGV[1]

local function vkey(k) return 'slot_version:' .. k end
local function read(k) return tonumber(redis.call('GET', k) or '0') or 0 end
local function write(k, v)
  redis.call('SET', k, v)
  redis.call('INCR', vkey(k))
end
-- Give one slot back: never below zero; a counter already below zero is
-- repaired to zero; an absent or zero counter is left alone.
local function give_back(k)
  local c = read(k)
  if c > 0 then
    write(k, c - 1)
  elseif c < 0 then
    write(k, 0)
  end
end
-- Take one slot with no cap (a profile switch): a negative counter counts from zero.
local function take(k)
  local c = read(k)
  if c < 0 then c = 0 end
  write(k, c + 1)
end

if op == 'reserve' then
  -- KEYS: profile counter, credential counter (or a placeholder), release pointer
  -- ARGV: op, profile max (0 = not counted), credential max (0 = no credential counter)
  local pmax = tonumber(ARGV[2])
  local cmax = tonumber(ARGV[3])
  local pc = 0
  if pmax > 0 then
    pc = read(KEYS[1])
    if pc < 0 then pc = 0 end
    if pc + 1 > pmax then return {0, pc, 'profile_full'} end
  end
  local cc = 0
  if cmax > 0 then
    cc = read(KEYS[2])
    if cc < 0 then cc = 0 end
    if cc + 1 > cmax then return {0, pc, 'credential_full'} end
  end
  if pmax > 0 then write(KEYS[1], pc + 1) end
  if cmax > 0 then
    write(KEYS[2], cc + 1)
    redis.call('SET', KEYS[3], KEYS[2])
  end
  if pmax > 0 then return {1, pc + 1, ''} end
  return {1, 0, ''}
elseif op == 'release' then
  -- KEYS: profile counter, release pointer
  local ck = redis.call('GET', KEYS[2])
  if ck then
    give_back(ck)
    redis.call('DEL', KEYS[2])
  end
  give_back(KEYS[1])
  if ck then return 1 end
  return 0
elseif op == 'switch' then
  -- KEYS: old profile counter, new profile counter, stream_profile key,
  --       old release pointer, new release pointer, new credential counter
  -- ARGV: op, new profile id, move credential (0/1), new credential max
  if ARGV[3] == '1' then
    local ncmax = tonumber(ARGV[4])
    local ncc = 0
    if ncmax > 0 then
      ncc = read(KEYS[6])
      if ncc < 0 then ncc = 0 end
      if ncc + 1 > ncmax then return {0, 'credential_full'} end
    end
    local ock = redis.call('GET', KEYS[4])
    if ock then
      give_back(ock)
      redis.call('DEL', KEYS[4])
    end
    if ncmax > 0 then
      write(KEYS[6], ncc + 1)
      redis.call('SET', KEYS[5], KEYS[6])
    end
  end
  give_back(KEYS[1])
  redis.call('SET', KEYS[3], ARGV[2])
  take(KEYS[2])
  return {1, ''}
elseif op == 'reconcile' then
  -- KEYS: counter. ARGV: op, expected version, floor, ceiling.
  -- Writes the counter, clamped into [floor, ceiling], only if its version
  -- still equals the one the previous reconciler run recorded. The
  -- reconciler's own write bumps no version: it is not a holder.
  local k = KEYS[1]
  local v = tonumber(redis.call('GET', vkey(k)) or '0') or 0
  local c = read(k)
  if v ~= tonumber(ARGV[2]) then return {-1, c, c} end
  local t = c
  local lo = tonumber(ARGV[3])
  local hi = tonumber(ARGV[4])
  if t < lo then t = lo end
  if t > hi then t = hi end
  if t == c then return {0, c, c} end
  redis.call('SET', k, t)
  return {1, c, t}
end
return redis.error_reply('provider_slot: unknown op ' .. tostring(op))
"""

# A placeholder for an unused KEYS slot: the script never reads or writes it
# (every use of KEYS[2] in 'reserve' is guarded by cmax > 0, and of KEYS[6] in
# 'switch' by ncmax > 0).
_NO_KEY = "provider_slot:unused"


def slot_version_key(counter_key: str) -> str:
    """The version key the slot script bumps on every write to counter_key."""
    return f"{SLOT_VERSION_KEY_PREFIX}{counter_key}"


def _run_slot_script(redis_client, keys, args):
    # register_script() only hashes the source; the first call per server
    # loads it and every later call is one EVALSHA. No per-client cache: a
    # cache keyed on id(client) can hand a new client a stale Script bound to
    # a dead one (the VOD module's tests clear such a cache for that reason).
    return redis_client.register_script(_SLOT_SCRIPT)(keys=keys, args=args)


def _decoded(value):
    return value.decode() if isinstance(value, bytes) else value


def credential_reservation(profile) -> Tuple[Optional[str], int]:
    """The credential counter a reserve on this profile counts against, and its cap.

    (None, 0) when the profile skips credential enforcement: no ServerGroup,
    max_streams=0, or no fingerprint.
    """
    group = get_enforced_server_group_for_profile(profile)
    if not group or profile.max_streams == 0:
        return None, 0
    cred_key = _credential_counter_key(profile, group)
    if not cred_key:
        return None, 0
    return cred_key, profile.max_streams


def reserve_profile_slot(
    profile, redis_client
) -> Tuple[bool, int, Optional[ReserveFailureReason]]:
    """
    Atomically reserve profile + optional credential slots in one script call.

    Returns (reserved, profile_count_after_attempt, failure_reason).
    failure_reason is set when reserved is False. A refused reserve writes
    nothing.
    """
    cred_key, cred_max = credential_reservation(profile)
    result = _run_slot_script(
        redis_client,
        keys=[
            profile_connections_key(profile.id),
            cred_key or _NO_KEY,
            profile_credential_release_key(profile.id),
        ],
        args=["reserve", max(profile.max_streams, 0), cred_max],
    )
    reserved, count, reason = int(result[0]), int(result[1]), _decoded(result[2])
    if reserved:
        return True, count, None
    return False, count, reason


def release_profile_slot(profile_id: int, redis_client) -> None:
    """Release profile and shared credential slots after a stream end."""
    _run_slot_script(
        redis_client,
        keys=[
            profile_connections_key(profile_id),
            profile_credential_release_key(profile_id),
        ],
        args=["release"],
    )


def switch_profile_slot(
    old_profile, new_profile, stream_profile_key: str, redis_client
) -> bool:
    """Move one stream's slots from old_profile to new_profile, atomically.

    The profile counters always move: old gives one back, new takes one with
    no cap check (the caller selected new_profile with
    profile_available_for_channel_switch() first, exactly as before). The
    credential counter moves only when the provider login changes, and a full
    credential pool on the new login refuses the whole switch before anything
    is written. stream_profile_key is rewritten to new_profile's id in the
    same step.

    Returns False when the new login's credential pool is full.
    """
    old_fp = get_profile_credential_fingerprint(old_profile)
    new_fp = get_profile_credential_fingerprint(new_profile)
    move_credential = old_fp != new_fp
    new_cred_key, new_cred_max = (
        credential_reservation(new_profile) if move_credential else (None, 0)
    )
    result = _run_slot_script(
        redis_client,
        keys=[
            profile_connections_key(old_profile.id),
            profile_connections_key(new_profile.id),
            stream_profile_key,
            profile_credential_release_key(old_profile.id),
            profile_credential_release_key(new_profile.id),
            new_cred_key or _NO_KEY,
        ],
        args=["switch", new_profile.id, 1 if move_credential else 0, new_cred_max],
    )
    return int(result[0]) == 1


def reconcile_counter(
    counter_key: str, expected_version: int, floor: int, ceiling: int, redis_client
) -> Tuple[int, int, int]:
    """Clamp a counter into [floor, ceiling] if its version is still expected_version.

    Returns (status, before, after): status -1 when the version moved (no
    write), 0 when the counter was already inside the range (no write), 1 when
    it was written.
    """
    result = _run_slot_script(
        redis_client,
        keys=[counter_key],
        args=["reconcile", expected_version, floor, ceiling],
    )
    return int(result[0]), int(result[1]), int(result[2])


def read_slot_versions(counter_keys, redis_client) -> dict:
    """One MGET of every counter's version; an absent version reads 0."""
    counter_keys = list(counter_keys)
    if not counter_keys:
        return {}
    values = redis_client.mget([slot_version_key(k) for k in counter_keys])
    return {k: int(_decoded(v) or 0) for k, v in zip(counter_keys, values)}
