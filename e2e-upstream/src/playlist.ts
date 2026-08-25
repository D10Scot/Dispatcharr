import type { Scenario } from './scenario.js';

/**
 * apps/m3u/tasks.py rejects a response whose content is "non-text", so this
 * is not cosmetic. text/plain would also pass.
 */
export const PLAYLIST_CONTENT_TYPE = 'application/vnd.apple.mpegurl';

/**
 * The product sends no credentials of its own on a standard M3U or XMLTV
 * fetch, so a scenario that wants to validate credentials has to carry them
 * in the URL. Single implementation shared by the playlist body and by
 * `server.ts`'s `scenarioUrls` (which reports the same query back to the
 * test author alongside the scenario's other URLs).
 */
export function credentialQuery(scenario: Scenario): string {
  if (scenario.username === undefined) return '';
  return (
    `?username=${encodeURIComponent(scenario.username)}` +
    `&password=${encodeURIComponent(scenario.password ?? '')}`
  );
}

/**
 * `streamOrigin` must be the internal origin. Dispatcharr is what follows
 * these URLs, so they have to resolve inside the Docker network even when a
 * test fetched this playlist through the published control port.
 */
export function renderPlaylist(scenario: Scenario, streamOrigin: string): string {
  const query = credentialQuery(scenario);
  const lines = ['#EXTM3U'];

  for (const channel of scenario.channels) {
    const attributes = [
      `tvg-id="${channel.tvgId}"`,
      `tvg-name="${channel.name}"`,
      ...(channel.logo === null ? [] : [`tvg-logo="${channel.logo}"`]),
      'group-title="E2E"',
    ].join(' ');

    lines.push(`#EXTINF:-1 ${attributes},${channel.name}`);
    lines.push(`${streamOrigin}/s/${scenario.id}/stream/${channel.id}.ts${query}`);
  }

  return `${lines.join('\n')}\n`;
}
