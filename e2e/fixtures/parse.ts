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
    //
    // KNOWN LIMITATION, not a bug here: a channel or group name containing a
    // `"` truncates, because `apps/output/views.py:304-306` interpolates
    // `tvg-name="{tvg_name}"` and `group-title="{group_title}"` with no
    // quote-escaping — the product's own output is malformed for such a
    // name, and this parser has no well-formed input to recover from. Filed
    // as D10Scot/Dispatcharr#80; do not "fix" this parser to compensate.
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
 *
 * Deliberately not decoded: the decimal forms `&#39;`/`&apos;`. `html.escape`
 * never emits either — it always writes `&#x27;` — so adding them would widen
 * this function past what it needs to handle for no reason. If a future
 * Dispatcharr change starts emitting one, that is new evidence to add here,
 * not something to pre-empt.
 *
 * Note for callers: this function only ever returns a `string`. A field that
 * is genuinely *absent* from the source (no `stop=` attribute, no
 * `<title>` element) is `undefined`/`''` upstream of this call, not something
 * this function invents — empty-vs-absent stays distinguishable at the call
 * site, this just never introduces a third state.
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
  // Without this guard, an HTML error page, an empty body or a JSON payload
  // all match zero `<channel>`/`<programme>` elements and return
  // `{channels: [], programmes: []}` — indistinguishable from a real, empty
  // guide. Every downstream absence assertion ("my channel is not in this
  // guide") would then pass trivially against a broken endpoint. `parseM3u`
  // already guards its input the same way; this brings XMLTV in line.
  //
  // Deliberately a substring test, not an anchored root check: a body whose
  // *content* mentions `<tv>` would pass. Anchoring would mean tolerating an
  // XML declaration, a doctype and leading comments, and a version of that
  // which is even slightly too strict rejects a valid guide — which fails in
  // the dangerous direction, since every downstream EPG test would then error
  // rather than assert. The failure modes this exists to catch (an HTML error
  // page, a JSON body, an empty response) do not contain the string. Do not
  // "tighten" this without a test proving real Dispatcharr output still parses.
  if (!/<tv[\s>]/.test(text)) {
    throw new Error(
      `not an XMLTV document: no <tv> root element. Body started with ${JSON.stringify(
        text.slice(0, 120)
      )}`
    );
  }

  const channels: XmltvChannel[] = [];
  for (const match of text.matchAll(/<channel\b([^>]*)>([\s\S]*?)<\/channel>/g)) {
    channels.push({
      id: decodeXmlEntities(attributesOf(match[1]).id ?? ''),
      displayNames: [
        ...match[2].matchAll(/<display-name\b[^>]*>([\s\S]*?)<\/display-name>/g),
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
