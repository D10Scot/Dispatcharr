import type { Scenario } from './scenario.js';

export const XMLTV_CONTENT_TYPE = 'application/xml';

/** Hours of guide before and after `now`. */
const HOURS_BEFORE = 2;
const HOURS_AFTER = 24;
const SLOT_MS = 60 * 60 * 1000;

// Escaping `& < > "` (and leaving `'` alone, which needs no escaping in
// element text) is sufficient here because `scenario.ts` already rejects
// control characters in `name`/`tvgId` at validation time — the only inputs
// that could otherwise produce a not-well-formed document (e.g. a bare NUL).
function escapeXml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** XMLTV wants YYYYMMDDHHMMSS +0000. Anything else is dropped silently. */
function xmltvTime(date: Date): string {
  const pad = (n: number, width = 2) => String(n).padStart(width, '0');
  return (
    `${pad(date.getUTCFullYear(), 4)}${pad(date.getUTCMonth() + 1)}${pad(date.getUTCDate())}` +
    `${pad(date.getUTCHours())}${pad(date.getUTCMinutes())}${pad(date.getUTCSeconds())} +0000`
  );
}

export function renderXmltv(scenario: Scenario, now: Date): string {
  // Anchor to the hour so slots abut exactly and the format stays readable.
  const anchor = Math.floor(now.getTime() / SLOT_MS) * SLOT_MS;
  const first = anchor - HOURS_BEFORE * SLOT_MS;
  const slots = HOURS_BEFORE + HOURS_AFTER;

  const parts = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<tv generator-info-name="dispatcharr-e2e-upstream">',
  ];

  for (const channel of scenario.channels) {
    parts.push(`  <channel id="${escapeXml(channel.tvgId)}">`);
    parts.push(`    <display-name>${escapeXml(channel.name)}</display-name>`);
    parts.push('  </channel>');
  }

  for (const channel of scenario.channels) {
    for (let slot = 0; slot < slots; slot += 1) {
      const start = new Date(first + slot * SLOT_MS);
      const stop = new Date(first + (slot + 1) * SLOT_MS);
      parts.push(
        `  <programme start="${xmltvTime(start)}" stop="${xmltvTime(stop)}" ` +
          `channel="${escapeXml(channel.tvgId)}">`
      );
      parts.push(
        `    <title>${escapeXml(channel.name)} — slot ${slot + 1}</title>`
      );
      parts.push('  </programme>');
    }
  }

  parts.push('</tv>');
  return `${parts.join('\n')}\n`;
}
