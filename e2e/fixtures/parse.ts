import type { XcUser } from './types';

/**
 * The credential query string every Xtream endpoint takes.
 *
 * Four surfaces need this (`player_api.php`, `panel_api.php`, `get.php`,
 * `xmltv.php`) and two more embed it in a path. Hand-rolling it at each call
 * site is four chances to get the encoding wrong — a generated username
 * contains `@` and `.`, both of which must survive.
 *
 * `extra` carries the per-call parameters: `{ action: 'get_live_streams' }`,
 * `{ action: 'get_short_epg', stream_id: channel.id }`.
 */
export function xcQuery(
  user: XcUser,
  extra: Record<string, string | number> = {}
): string {
  const params = new URLSearchParams({
    username: user.username,
    password: user.xcPassword,
  });
  for (const [key, value] of Object.entries(extra)) {
    params.set(key, String(value));
  }
  return `?${params.toString()}`;
}
