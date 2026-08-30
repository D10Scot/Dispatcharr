import { expect } from '@playwright/test';
import type { APIRequestContext } from '@playwright/test';
import { xcQuery } from './parse';
import type { XcUser } from './types';

/**
 * Helpers for the client-facing output surfaces — `/output/m3u`,
 * `/output/epg` and the Xtream `player_api.php` listing actions.
 *
 * All three surfaces are read by more than one spec file, and all three have
 * a trap that every caller has to clear in the same way. Sharing the clearing
 * here is what stops one call site quietly doing it differently from the
 * next; that divergence is exactly what the G5 review found.
 */

/** A token distinct per call, so no two fetches can share a cache entry. */
function bustToken(): string {
  return `e2e-${Math.random().toString(36).slice(2)}`;
}

/**
 * A query string for `/output/m3u` that no other caller can share a cache
 * entry with.
 *
 * `generate_m3u` caches the rendered body under
 * `f"{profile}:{user}:{request.GET.urlencode()}:origin=..."` for 2 seconds
 * (`apps/output/views.py:126-131`, `:336`), with no per-channel
 * invalidation. A bare `/output/m3u` is therefore ONE key for every anonymous
 * caller on the instance, and the `seeded` project runs `fullyParallel` on 4
 * workers: one worker's fetch can be served a body another worker rendered
 * before this test's channel existed, failing an assertion with nothing wrong
 * in the product. Reproduced twice in a row against this stack before the
 * first of these busters was added, and zero times in three repeats after.
 *
 * `e2e` is not among the parameters `generate_m3u` reads (`cachedlogos`,
 * `direct`, `output_profile`, `output_format`/`output`, `tvg_id_source`), and
 * the per-channel stream URL is built from `proxy_qs`, which carries only
 * `output_profile` and `output_format` (`apps/output/views.py:230-235`) — so
 * this changes the cache key without changing a byte of the rendered body.
 */
export function m3uQuery(): string {
  return `?e2e=${bustToken()}`;
}

/**
 * A query string for `/output/epg` that no other caller can share a cache
 * entry with, without paying for a wide programme window to get there.
 *
 * `/output/epg` is served from a 300-second Redis chunk cache whose key is
 * `profile:username:d=:p=:logos=:tvgid=:origin=` (`apps/output/epg.py:1118-1123`)
 * — the raw query string is NOT in it, so `?e2e=` does not bust it, and
 * creating a channel invalidates it only when `epg_data` is involved
 * (`refresh_epg_programs` in `apps/channels/signals.py`), which a plain
 * seeded channel is not. Without a buster this reads a body rendered up to
 * five minutes before its channel existed.
 *
 * `tvg_id_source` is the parameter to vary, not `days`. It goes into the key
 * verbatim and is only ever COMPARED against the two literals `'tvg_id'` and
 * `'gracenote'` (`apps/output/epg.py:1115`, `:1245-1247`), so any other value
 * — including this token — takes the same default branch as the unset
 * parameter and emits byte-identical channel ids. It gives unbounded key
 * entropy at zero body cost.
 *
 * That matters because `days` used to carry the entropy, and `days` is also
 * how much of the guide gets rendered: `generate_epg` gives EVERY EPG-less
 * channel on the instance 6 programmes per day, for the whole accumulated
 * channel population, not just the calling test's. A `?days=365` fetch threw
 * `Cannot create a string longer than 0x1fffffe8 characters` against this
 * stack; narrowing to 30 fixed that but left the margin shrinking every run,
 * since nothing here ever deletes a channel. Pinning `days=1` bounds the body
 * permanently, and moving the entropy off `days` is what makes that safe —
 * a fixed `days` with no other buster would reinstate the cache race.
 *
 * `days` stays explicit rather than omitted: unset means `epg_days` from the
 * user's custom properties, defaulting to 0, and 0 takes a different branch
 * (`dummy_days = 3`, `cutoff_date = None`).
 */
export function epgQuery(days = 1): string {
  return `?days=${days}&tvg_id_source=${bustToken()}`;
}

export type XcStream = {
  num: number;
  name: string;
  stream_id: number;
  stream_type: string;
  category_id: string;
  category_ids: number[];
  epg_channel_id: string;
  is_adult: number;
  tv_archive: number;
  /** The provider's `tv_archive_duration`, reaching `Stream.catchup_days` via `int(... or 0)` (`apps/m3u/tasks.py:1167`). */
  tv_archive_duration: number;
};

/**
 * `player_api.php?action=get_live_streams` for one XC principal.
 *
 * One helper rather than a copy per spec, because the status assertion is the
 * part that keeps getting dropped. `get_live_streams` is the one action served
 * as a `StreamingHttpResponse` (`_xc_stream_live_streams` yields the array
 * element by element), so the body must be read whole before parsing — and a
 * non-200 that still parses must not slip through as an empty or malformed
 * stream list. A `{"error": ...}` envelope from an unresolvable user (#84
 * returns 404) or a wrong password (401) parses fine; without the status
 * check the failure surfaces frames later as `TypeError: listed.map is not a
 * function`, pointing at the harness instead of at the surface.
 *
 * `label` names the caller in the assertion message — several specs make this
 * call for different reasons in the same file.
 */
export async function xcLiveStreams(
  request: APIRequestContext,
  user: XcUser,
  label = 'get_live_streams'
): Promise<XcStream[]> {
  const res = await request.get(
    `/player_api.php${xcQuery(user, { action: 'get_live_streams' })}`
  );
  expect(res.status(), label).toBe(200);
  return JSON.parse(await res.text());
}
