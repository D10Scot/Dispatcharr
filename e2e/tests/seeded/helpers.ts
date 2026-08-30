import type { ApiClient, GroupSettingRow, M3uAccountChannelGroup } from '../../fixtures';

/**
 * A disjoint `[auto_sync_channel_start, auto_sync_channel_end]` window for one
 * auto-sync test.
 *
 * Two properties matter. **Disjoint across workers**, because `seeded` runs
 * four of them in parallel and each test wants a window nobody else is filling.
 * And **high**, four figures, because `seed.channel()` and
 * `channels/from-stream/` auto-assign numbers upward from 1 — a low window
 * would collide with them constantly.
 *
 * It is deliberately NOT a guarantee of exclusivity: `sync_auto_channels`
 * seeds `used_numbers` from every Channel row in the instance except this
 * account's own visible auto-created ones, and `build_reserved_set` is equally
 * global — so any channel anywhere inside the window is skipped over. That is
 * why every numbering assertion in these tests is relative (inside the window,
 * distinct, ascending in catalogue order) and never absolute.
 *
 * `slot` distinguishes two windows requested by the same worker — only `0`
 * and `1` are valid (Task 9 uses `0`, Task 10 uses `1`). Each worker's own
 * span is 200 wide and each slot claims 100 of it, so `slot` **must** stay
 * below 2: `slot: 2` would start at `workerIndex * 200 + 200`, i.e. inside
 * the *next* worker's `slot: 0` window, defeating the one property this
 * function exists to guarantee. Guarded rather than documented alone, since
 * a silent collision here is exactly the kind of cross-worker flake this
 * whole scheme is meant to rule out.
 *
 * **Nothing reclaims a number once assigned, so a 100-wide window is a
 * budget, not an infinite resource.** `sync_auto_channels` reports
 * `channels_failed` (surfaced in the refresh's `last_message` as
 * `"Auto-sync: N failed"`) once a window is full, and from the outside that
 * looks exactly like an ordinary test timeout with no obvious cause — this
 * bit Task 10's own verification after a dozen-odd repeated local runs of
 * this file in one session against a container that was never reset. CI is
 * unaffected (each matrix job gets a fresh container), but running this
 * file repeatedly during local development eventually exhausts a window;
 * the remedy is `./scripts/e2e_up.sh --reset`, not a wider window here.
 */
export function syncWindowFor(
  workerIndex: number,
  slot: number
): { start: number; end: number } {
  if (slot < 0 || slot > 1) {
    throw new Error(
      `syncWindowFor: slot must be 0 or 1 (got ${slot}) — a slot of 2 or more ` +
        'lands inside the next worker\'s own window and defeats the disjointness ' +
        'this function exists to guarantee. Widen the per-worker span in this ' +
        'function itself if a third slot is ever genuinely needed.'
    );
  }
  const start = 9000 + workerIndex * 200 + slot * 100;
  return { start, end: start + 99 };
}

/**
 * Full-field upsert of one or more `group_settings` rows via
 * `PATCH /api/m3u/accounts/<id>/group-settings/`
 * (`M3UAccountViewSet.update_group_settings`).
 *
 * Centralised here, not inlined per spec file, because both Task 9 and
 * Task 10 enable auto channel sync on a group relation and the plan
 * otherwise spells out the identical PATCH block twice — a duplication the
 * review rubric treats as a defect. `rows` is an array, matching the
 * endpoint's own body shape, so a caller touching one group (this task) and
 * a caller touching several (or re-touching the same one with a changed
 * catalogue) share the same call, neither privileged over the other.
 *
 * `category_settings` is always sent empty: nothing in this goal writes VOD
 * category settings.
 *
 * This function fills in nothing. Every field of every row is REQUIRED — see
 * `GroupSettingRow`'s doc comment in `fixtures/types.ts` for why an omitted
 * field is not "left alone" but overwritten with its zero value. It is a
 * thin, asserting wrapper around the PATCH, not a place to reintroduce the
 * "omit and keep the old value" behaviour that type exists to rule out.
 *
 * **A 200 alone does not mean every row landed.** `update_group_settings`
 * silently skips any row whose `channel_group` is falsy
 * (`apps/m3u/api_views.py:532`, `if setting.get("channel_group")`) and still
 * returns `{"message": "Group settings updated successfully"}` — a
 * malformed row (a stale or zero id, say) would otherwise fail silently for
 * every caller of this helper. So this reads the account back and throws
 * unless every row's fields actually match what was sent, rather than
 * leaving that check to whichever caller happens to read back on its own —
 * Task 9 does; a future one might not.
 */
export async function applyGroupSettings(
  api: ApiClient,
  accountId: number,
  rows: GroupSettingRow[]
): Promise<void> {
  const res = await api.patch(`/api/m3u/accounts/${accountId}/group-settings/`, {
    group_settings: rows,
    category_settings: [],
  });
  await api.json(res, `group-settings PATCH for account ${accountId}`);

  const readBack = await api.json<{ channel_groups: M3uAccountChannelGroup[] }>(
    await api.get(`/api/m3u/accounts/${accountId}/`),
    `group-settings read-back for account ${accountId}`
  );
  for (const row of rows) {
    const landed = readBack.channel_groups.find((g) => g.channel_group === row.channel_group);
    const matches =
      landed !== undefined &&
      landed.enabled === row.enabled &&
      landed.auto_channel_sync === row.auto_channel_sync &&
      landed.auto_sync_channel_start === row.auto_sync_channel_start &&
      landed.auto_sync_channel_end === row.auto_sync_channel_end;
    if (!matches) {
      throw new Error(
        `applyGroupSettings: row for channel_group ${row.channel_group} did not land on ` +
          `account ${accountId} — PATCH returned 200, but the account's group relation is ` +
          `${JSON.stringify(landed)}, not the row sent (${JSON.stringify(row)}). ` +
          '`update_group_settings` silently skips a row whose `channel_group` is falsy ' +
          '(apps/m3u/api_views.py:532); check that id is real and non-zero.'
      );
    }
  }
}
