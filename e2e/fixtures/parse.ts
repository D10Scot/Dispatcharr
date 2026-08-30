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

/**
 * Used for the `#EXTM3U` header line only, which is attributes and nothing
 * else. An `#EXTINF` line must go through {@link splitExtinf} instead: it has
 * a title after the attributes, and scanning the whole line would pick up
 * anything in that title shaped like `key="value"` as a phantom attribute.
 */
function attributesOf(line: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const match of line.matchAll(ATTRIBUTE)) {
    out[match[1]] = match[2];
  }
  return out;
}

/** Anchored, so the walk in `splitExtinf` can only consume from the cursor. */
const LEADING_ATTRIBUTE = /^[ \t]*([A-Za-z0-9_-]+)="([^"]*)"/;

/**
 * Splits an `#EXTINF` line into its attributes and its title by walking the
 * attribute region left to right, rather than by searching backwards from the
 * last `"` on the line.
 *
 * The direction is the whole point. A backwards search cannot tell an
 * attribute's closing quote from a quote inside the title, so a title
 * containing `"` moves the search anchor into the title and the comma lookup
 * from it lands past the real boundary — or fails entirely, yielding an empty
 * title. Worse, scanning the entire line for attributes picks up anything in
 * the title shaped like `key="value"`, so a channel named `Ch a="b"` used to
 * parse as an entry with an empty title and a phantom `a` attribute, with no
 * error. Both callers of this parser key their `find()` on
 * `attributes['tvg-name']`, so a phantom attribute is not a cosmetic problem.
 *
 * Walking forwards has neither failure. It also yields `wellFormed` for free:
 * a line whose attribute region ends anywhere other than the title comma had
 * text spill out of a quoted value, which is precisely the shape
 * D10Scot/Dispatcharr#80 produces. Reported rather than repaired — this
 * parser must not invent a well-formed reading of a malformed line, or
 * `output-m3u.spec.ts`'s pin on that defect would have nothing to see.
 */
export function splitExtinf(line: string): {
  attributes: Record<string, string>;
  title: string;
  wellFormed: boolean;
} {
  // Skip `#EXTINF:` and the duration field, which runs to the first
  // whitespace or comma (`#EXTINF:-1,Title` has no attributes at all).
  let cursor = line.indexOf(':') + 1;
  while (cursor < line.length && !' \t,'.includes(line[cursor])) cursor++;

  const attributes: Record<string, string> = {};
  for (;;) {
    const match = LEADING_ATTRIBUTE.exec(line.slice(cursor));
    if (!match) break;
    attributes[match[1]] = match[2];
    cursor += match[0].length;
  }

  const rest = line.slice(cursor);
  const comma = rest.indexOf(',');
  return {
    attributes,
    title: comma === -1 ? '' : rest.slice(comma + 1),
    // `=== 0`, not `!== -1`: the attribute walk stops at the first thing it
    // cannot read, so anything between there and the comma is spilled text.
    wellFormed: comma === 0,
  };
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

    // Attributes and title come from one forward walk (see splitExtinf), so
    // a comma inside a channel name survives — group-title="World",News,
    // Live yields "News, Live", not "Live" — and nothing in the title can be
    // mistaken for an attribute.
    //
    // KNOWN LIMITATION, not a bug here: a channel or group name containing a
    // `"` still does not round-trip, because `apps/output/views.py:306-308`
    // interpolates `tvg-name="{tvg_name}"` and `group-title="{group_title}"`
    // with no quote-escaping — the product's own output is malformed for such
    // a name, and this parser has no well-formed input to recover from.
    // Filed as D10Scot/Dispatcharr#80; do not "fix" this parser to
    // compensate. It reports the malformation as `wellFormed: false` instead,
    // which is what that defect's pin asserts on.
    entries.push({ ...splitExtinf(line), url });
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
export function decodeXmlEntities(value: string): string {
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
