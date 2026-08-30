import { expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import type {
  M3uEntry,
  M3uPlaylist,
  XcUser,
  XmltvChannel,
  XmltvDocument,
  XmltvProgramme,
} from './types';

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

/**
 * These two parsers are deliberately SHALLOW. They read the attributes and
 * elements this suite asserts on, and they are not M3U or XMLTV validators —
 * a body they accept is not thereby proved well-formed.
 *
 * `e2e/package.json` carries no XML or M3U dependency, and adding one to read
 * a handful of elements is a supply-chain decision out of proportion to the
 * need. Where a real *validity* verdict is wanted, use
 * {@link expectWellFormedXml}, which hands the document to the browser's own
 * DOMParser — a real XML parser this suite already has.
 */

const ATTRIBUTE = /([A-Za-z0-9_-]+)="([^"]*)"/g;

function attributesOf(line: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const match of line.matchAll(ATTRIBUTE)) {
    out[match[1]] = match[2];
  }
  return out;
}

export function parseM3u(text: string): M3uPlaylist {
  const lines = text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0);

  if (lines.length === 0 || !lines[0].startsWith('#EXTM3U')) {
    throw new Error(
      `not an M3U playlist: the first line was ${JSON.stringify(lines[0] ?? '')}`
    );
  }

  const entries: M3uEntry[] = [];
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i];
    if (!line.startsWith('#EXTINF:')) continue;

    const url = lines[i + 1];
    if (url === undefined || url.startsWith('#')) {
      throw new Error(`#EXTINF is not followed by a URL: ${line}`);
    }

    // The title starts after the comma that follows the LAST quoted
    // attribute. Searching from the last quote rather than from the end of
    // the line is what keeps a comma inside a channel name intact —
    // group-title="World",News, Live must yield "News, Live", not "Live".
    const lastQuote = line.lastIndexOf('"');
    const comma = line.indexOf(',', lastQuote === -1 ? line.indexOf(':') : lastQuote);

    entries.push({
      attributes: attributesOf(line),
      title: comma === -1 ? '' : line.slice(comma + 1),
      url,
    });
    i++; // consume the URL line
  }

  return { header: attributesOf(lines[0]), entries };
}

/**
 * `html.escape(..., quote=True)` is what Dispatcharr writes with, so these
 * five are the whole set it can emit. `&amp;` is decoded last, or a body
 * containing the literal text `&amp;lt;` would decode twice.
 */
function decodeXmlEntities(value: string): string {
  return value
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, '&');
}

export function parseXmltv(text: string): XmltvDocument {
  const channels: XmltvChannel[] = [];
  for (const match of text.matchAll(/<channel id="([^"]*)">([\s\S]*?)<\/channel>/g)) {
    channels.push({
      id: decodeXmlEntities(match[1]),
      displayNames: [
        ...match[2].matchAll(/<display-name>([\s\S]*?)<\/display-name>/g),
      ].map((name) => decodeXmlEntities(name[1])),
    });
  }

  const programmes: XmltvProgramme[] = [];
  for (const match of text.matchAll(/<programme\b([^>]*)>([\s\S]*?)<\/programme>/g)) {
    const attributes = attributesOf(match[1]);
    const title = /<title[^>]*>([\s\S]*?)<\/title>/.exec(match[2]);
    programmes.push({
      channel: decodeXmlEntities(attributes.channel ?? ''),
      start: attributes.start ?? '',
      stop: attributes.stop ?? '',
      title: title ? decodeXmlEntities(title[1]) : '',
    });
  }

  return { channels, programmes };
}

/**
 * Assert a body parses as XML, using the browser's DOMParser.
 *
 * This is the only place in the suite that can honestly say "valid XML":
 * {@link parseXmltv} is a regex reader and would happily extract elements
 * from a document with an unclosed root. `adminPage` sits at `about:blank`,
 * which is a perfectly good context for `page.evaluate`.
 */
export async function expectWellFormedXml(page: Page, xml: string): Promise<void> {
  const failure = await page.evaluate((source: string) => {
    const doc = new DOMParser().parseFromString(source, 'application/xml');
    const problem = doc.querySelector('parsererror');
    return problem ? problem.textContent : null;
  }, xml);

  expect(failure, 'body should parse as well-formed XML').toBeNull();
}
