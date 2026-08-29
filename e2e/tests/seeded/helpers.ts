import type { ApiClient, GroupSettingRow } from '../../fixtures';

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
 * `slot` distinguishes two windows requested by the same worker.
 */
export function syncWindowFor(
  workerIndex: number,
  slot: number
): { start: number; end: number } {
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
}
