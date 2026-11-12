/**
 * Xtream credentials out of the request logs nginx and uWSGI write.
 *
 * Xtream clients carry the user's login in the path
 * (`/live|movie|series|timeshift/<user>/<pass>/…`, `/<user>/<pass>/<id>`) or
 * the query string (`player_api.php`, `get.php`, `xmltv.php`,
 * `streaming/timeshift.php`); the browser carries its JWT as `/ws/?token=` and
 * the SSO callback carries `code=`/`state=`. nginx's default `combined` access
 * log prints `$request`, uWSGI's `%(uri)` prints REQUEST_URI, and nginx's error
 * log ends every request-context message with the raw request line.
 *
 * `docker/request_log_redaction.conf` builds `$log_redacted_request_uri` from a
 * chain of `map` blocks. This spec EXECUTES those maps (parsed from the file
 * the image ships, so the test and production cannot drift) against
 * `request-log-redaction.cases.json`, and pins every place a log could bypass
 * them: the access log's format, the error log's level, the uwsgi var both
 * uWSGI processes log, their `log-format`, and the two flags that silence
 * uWSGI's own raw-URI lines.
 *
 * What only a real nginx proves: that PCRE reads these regexes as JavaScript
 * does here, and that nginx evaluates the maps with the raw `$request_uri` the
 * table supplies. The PR that added this spec ran the same table through
 * nginx 1.28.3 and uWSGI 2.0.31 from the base image and recorded the result.
 *
 * `@characterization`: pins the nginx and uWSGI configuration as shipped
 * (docker/nginx.conf, docker/request_log_redaction.conf, the uwsgi params
 * include beside it, docker/uwsgi*.ini). A reimplementation
 * may log differently, but must keep credentials out of whatever it logs.
 */
import { test, expect } from '@playwright/test';
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { REPO_ROOT } from './ast';

const DOCKER = path.join(REPO_ROOT, 'docker');
const SNIPPET = 'request_log_redaction.conf';
const URI_VAR = 'log_redacted_request_uri';
const UWSGI_VAR = 'REDACTED_REQUEST_URI';
const FORMAT = 'redacted';

/**
 * The only variables the access log format may print. An allowlist, not a
 * denylist: a request header ($http_authorization, $http_cookie), a response
 * header ($sent_http_location carries a Redirect profile's provider URL) or an
 * upstream header added later fails here without anyone having to name it.
 */
const FORMAT_VARS = [
  'body_bytes_sent',
  URI_VAR,
  'http_user_agent',
  'remote_addr',
  'request_method',
  'request_time',
  'server_protocol',
  'status',
  'time_local',
  'upstream_addr',
  'upstream_status',
].sort();

interface Case {
  name: string;
  requestUri: string;
  logged: string;
}

const CASES: Case[] = JSON.parse(
  readFileSync(path.join(__dirname, 'request-log-redaction.cases.json'), 'utf8')
);

function read(rel: string): string {
  return readFileSync(path.join(REPO_ROOT, rel), 'utf8');
}

/** The uwsgi params include beside nginx.conf, the one that blanks the relay headers. */
const API_PARAMS = (() => {
  const found = readdirSync(DOCKER).filter((f) => /_api_params\.conf$/.test(f));
  if (found.length !== 1) throw new Error(`docker/: expected one *_api_params.conf, found ${found.join(', ')}`);
  return `docker/${found[0]}`;
})();

/** The project package's utils module, the one that defines redact_url's key list. */
const UTILS = (() => {
  const found = readdirSync(REPO_ROOT, { withFileTypes: true })
    .filter((d) => d.isDirectory() && !d.name.startsWith('.'))
    .map((d) => `${d.name}/utils.py`)
    .filter((rel) => {
      try {
        return /^SENSITIVE_QUERY_KEYS\s*=/m.test(read(rel));
      } catch {
        return false;
      }
    });
  if (found.length !== 1) {
    throw new Error(`expected one top-level */utils.py defining SENSITIVE_QUERY_KEYS, found ${found.length}`);
  }
  return found[0];
})();

/** Drops `#` comments; none of the files read here has a `#` inside a string. */
function stripComments(text: string): string {
  return text
    .split('\n')
    .map((l) => l.replace(/#.*$/, ''))
    .join('\n');
}

/** nginx's own unescaping inside a quoted token (ngx_conf_read_token). */
function unquote(token: string): string {
  if (!token.startsWith('"')) return token;
  return token
    .slice(1, -1)
    .replace(/\\(["'\\tnr])/g, (_m, c: string) => ({ t: '\t', n: '\n', r: '\r' })[c] ?? c);
}

interface MapEntry {
  key: string;
  value: string;
}

interface NginxMap {
  source: string;
  target: string;
  entries: MapEntry[];
  fallback: string;
}

/**
 * Each `map` block's body, found by walking to the brace that closes it with
 * quoted strings skipped, so a `{n}` quantifier inside a quoted regex cannot
 * end the block early and silently drop the entries after it. An unquoted
 * brace inside a body is refused rather than guessed at.
 */
function mapBlocks(conf: string): [string, string, string][] {
  const out: [string, string, string][] = [];
  const headRe = /^\s*map\s+("(?:[^"\\]|\\.)*"|\S+)\s+\$(\w+)\s*\{/gm;
  for (const head of conf.matchAll(headRe)) {
    let i = (head.index ?? 0) + head[0].length;
    let body = '';
    let quoted = false;
    for (; i < conf.length; i++) {
      const ch = conf[i];
      if (quoted) {
        if (ch === '\\') {
          body += ch + conf[i + 1];
          i++;
          continue;
        }
        if (ch === '"') quoted = false;
      } else if (ch === '"') {
        quoted = true;
      } else if (ch === '{') {
        throw new Error(`map $${head[2]}: an unquoted "{" in its body`);
      } else if (ch === '}') {
        break;
      }
      body += ch;
    }
    if (i >= conf.length) throw new Error(`map $${head[2]}: no closing brace`);
    out.push([head[1], head[2], body]);
  }
  return out;
}

function parseMaps(conf: string): NginxMap[] {
  const maps: NginxMap[] = [];
  for (const [source, target, body] of mapBlocks(stripComments(conf))) {
    const entries: MapEntry[] = [];
    let fallback = '';
    // No entry here has a ";" inside quotes; one would split into a token count other than 2 and throw.
    for (const stmt of body.split(';')) {
      const tokens = [...stmt.matchAll(/"(?:[^"\\]|\\.)*"|\S+/g)].map((m) => unquote(m[0]));
      if (tokens.length === 0) continue;
      if (tokens.length !== 2) throw new Error(`map $${target}: cannot read entry "${stmt.trim()}"`);
      if (tokens[0] === 'default') fallback = tokens[1];
      else entries.push({ key: tokens[0], value: tokens[1] });
    }
    maps.push({ source: unquote(source), target, entries, fallback });
  }
  return maps;
}

/** Substitutes `$name` and `$1`..`$9` the way an nginx complex value does. */
function interpolate(template: string, vars: (name: string) => string, captures: string[] = []): string {
  return template.replace(/\$(\d|[A-Za-z_][A-Za-z0-9_]*)/g, (_m, name: string) =>
    /^\d$/.test(name) ? (captures[Number(name)] ?? '') : vars(name)
  );
}

/**
 * Evaluates the maps for one request the way nginx does: lazily, exact keys
 * before regexes, regexes in file order, `~*` case-insensitive, else default.
 *
 * Where JavaScript and PCRE differ, these patterns stay clear of it: no
 * `\Z`/`\z`, no possessive or atomic groups, no inline `(?i)`, and `$` only
 * ever meets input without a newline (a request URI cannot hold one).
 * JavaScript's `i` flag folds a few non-ASCII letters (`ſ` matches `s`) that
 * PCRE without UTF mode does not; no case depends on it, and the real-nginx
 * run recorded in the PR is what covers that difference.
 */
function evaluate(maps: NginxMap[], requestUri: string): (name: string) => string {
  const byTarget = new Map(maps.map((m) => [m.target, m]));
  const cache = new Map<string, string>();
  const get = (name: string): string => {
    if (name === 'request_uri') return requestUri;
    const cached = cache.get(name);
    if (cached !== undefined) return cached;
    const map = byTarget.get(name);
    if (!map) throw new Error(`the maps read $${name}, which this evaluator does not supply`);
    const input = interpolate(map.source, get);
    let out: string | undefined;
    const exact = map.entries.find((e) => !e.key.startsWith('~') && e.key === input);
    if (exact) out = interpolate(exact.value, get);
    for (const e of map.entries) {
      if (out !== undefined) break;
      if (!e.key.startsWith('~')) continue;
      const insensitive = e.key.startsWith('~*');
      const re = new RegExp(e.key.slice(insensitive ? 2 : 1), insensitive ? 'i' : '');
      const m = re.exec(input);
      if (m) out = interpolate(e.value, get, [...m]);
    }
    out ??= interpolate(map.fallback, get);
    cache.set(name, out);
    return out;
  };
  return get;
}

const SENSITIVE_PYTHON = (() => {
  const body = /SENSITIVE_QUERY_KEYS\s*=\s*frozenset\(\s*\{([\s\S]*?)\}\s*\)/.exec(read(UTILS));
  if (!body) throw new Error(`${UTILS}: SENSITIVE_QUERY_KEYS not found`);
  return [...stripComments(body[1]).matchAll(/"([^"]+)"/g)].map((m) => m[1]).sort();
})();


test.describe('request-log credential redaction', () => {
  test('the redaction maps mask every credential-bearing request URI in the case table', { tag: '@characterization' }, () => {
    const maps = parseMaps(read(`docker/${SNIPPET}`));
    expect(maps.map((m) => m.target), `${SNIPPET} defines $${URI_VAR}`).toContain(URI_VAR);
    expect(CASES.length, 'the case table loaded').toBeGreaterThan(40);

    const wrong: string[] = [];
    for (const c of CASES) {
      const got = evaluate(maps, c.requestUri)(URI_VAR);
      if (got !== c.logged) wrong.push(`${c.name}: ${c.requestUri}\n    logged ${got}\n    wanted ${c.logged}`);
      if (/sentinel/.test(got)) {
        wrong.push(`${c.name}: a sentinel credential reached the log line: ${got}`);
      }
    }
    expect(wrong, `$${URI_VAR} for these request URIs`).toEqual([]);
  });

  test('no redaction pattern backtracks super-linearly on a hostile URI', { tag: '@characterization' }, () => {
    // These patterns run in nginx's event loop on unauthenticated input. A
    // quadratic one (the first draft's `[^=&]*%[^=&]*=`) takes about 450 ms on
    // 32,000 repeated characters in V8 where a linear one takes well under
    // 1 ms; the budget sits far from both. V8 and PCRE backtrack alike for
    // these shapes, so the PR's real-nginx timing is the confirmation.
    const n = 32_000;
    const hostile: string[] = [];
    for (const c of ['%', '&', '/', '=', '.', 'a', '1', '*', '?']) {
      const run = c.repeat(n);
      hostile.push(run, `${run}&a=`, `${run}password`, `/x?${run}`, `/live/${run}a`, `/hls/${run}`, `${run}/1`);
    }
    const slow: string[] = [];
    for (const m of parseMaps(read(`docker/${SNIPPET}`))) {
      for (const e of m.entries.filter((x) => x.key.startsWith('~'))) {
        const insensitive = e.key.startsWith('~*');
        const re = new RegExp(e.key.slice(insensitive ? 2 : 1), insensitive ? 'i' : '');
        for (const h of hostile) {
          const t = performance.now();
          re.exec(h);
          const ms = performance.now() - t;
          if (ms > 100) slow.push(`$${m.target} ${e.key.slice(0, 60)}… on ${JSON.stringify(h.slice(0, 12))}×: ${ms.toFixed(0)} ms`);
        }
      }
    }
    expect(slow, 'patterns slower than 100 ms on a 32,000-character hostile input').toEqual([]);
  });

  test('the query maps mask exactly the parameters redact_url masks', { tag: '@characterization' }, () => {
    const maps = parseMaps(read(`docker/${SNIPPET}`)).filter((m) => m.target.startsWith('log_query'));
    expect(maps.length, 'four masking maps and one guard').toBe(5);
    for (const m of maps) {
      const lists = m.entries
        .map((e) => /\(\?:((?:[a-z_]+\|)+[a-z_]+)\)=/.exec(e.key)?.[1])
        .filter((l): l is string => l !== undefined);
      expect(lists.length, `$${m.target} names the sensitive parameters`).toBeGreaterThan(0);
      for (const l of lists) {
        expect(l.split('|').sort(), `$${m.target}'s list against ${UTILS} SENSITIVE_QUERY_KEYS`).toEqual(
          SENSITIVE_PYTHON
        );
      }
    }
  });

  test('nginx logs requests only through the redacted format, and its error log only at alert', { tag: '@characterization' }, () => {
    const conf = stripComments(read('docker/nginx.conf'));
    const snippet = stripComments(read(`docker/${SNIPPET}`));

    expect(conf, 'nginx.conf includes the redaction snippet the Dockerfile installs').toMatch(
      new RegExp(`^\\s*include\\s+/etc/nginx/${SNIPPET.replace(/\./g, '\\.')}\\s*;`, 'm')
    );
    expect(read('docker/Dockerfile'), 'the Dockerfile installs the snippet where nginx.conf includes it').toMatch(
      new RegExp(`^COPY \\./docker/${SNIPPET.replace(/\./g, '\\.')} /etc/nginx/${SNIPPET.replace(/\./g, '\\.')}$`, 'm')
    );

    const formats = [...snippet.matchAll(/log_format\s+(\S+)\s+((?:'[^']*'\s*)+);/g)];
    expect(formats.map((f) => f[1]), 'the snippet declares one log format').toEqual([FORMAT]);
    const format = formats[0][2];
    expect(format, `the access log prints $${URI_VAR}`).toContain(`$${URI_VAR}`);
    const used = [...new Set([...format.matchAll(/\$\{?([A-Za-z_][A-Za-z0-9_]*)/g)].map((m) => m[1]))];
    expect(
      used.filter((v) => !FORMAT_VARS.includes(v)),
      'variables the access log format prints that are not on its allowlist'
    ).toEqual([]);
    expect(conf, 'nginx.conf declares no log_format of its own').not.toMatch(/^\s*log_format\b/m);

    const accessLogs = [...conf.matchAll(/^\s*access_log\s+([^;]*);/gm)].map((m) => m[1].trim());
    expect(accessLogs.length, 'nginx.conf sets the server-level access log').toBeGreaterThan(0);
    for (const a of accessLogs) {
      expect(a === 'off' || a.split(/\s+/)[1] === FORMAT, `access_log ${a} uses ${FORMAT} (or is off)`).toBe(true);
    }

    const errorLogs = [...conf.matchAll(/^\s*error_log\s+([^;]*);/gm)].map((m) => m[1].trim().split(/\s+/));
    expect(errorLogs.length, 'nginx.conf sets the server-level error log').toBeGreaterThan(0);
    for (const e of errorLogs) {
      expect(['alert', 'emerg'], `error_log ${e.join(' ')}: below alert, nginx prints the raw request line`).toContain(
        e[1]
      );
    }
  });

  test('every uwsgi_pass location hands uWSGI the redacted URI', { tag: '@characterization' }, () => {
    const param = new RegExp(`^\\s*uwsgi_param\\s+${UWSGI_VAR}\\s+\\$${URI_VAR}\\s*;`);
    for (const file of ['docker/nginx.conf', API_PARAMS]) {
      const lines = stripComments(read(file)).split('\n');
      const missing: number[] = [];
      let includes = 0;
      lines.forEach((l, i) => {
        if (!/^\s*include\s+uwsgi_params\s*;/.test(l)) return;
        includes++;
        // The next line with a directive on it (comments are already blanked).
        const next = lines.slice(i + 1).find((n) => n.trim() !== '') ?? '';
        if (!param.test(next)) missing.push(i + 1);
      });
      expect(includes, `${file} has uwsgi_params includes to check`).toBeGreaterThan(0);
      expect(missing, `${file}: lines whose include uwsgi_params is not followed by the ${UWSGI_VAR} param`).toEqual([]);
    }
  });

  test('every uWSGI ini logs the redacted var and silences its raw-URI error lines', { tag: '@characterization' }, () => {
    const inis = readdirSync(DOCKER).filter((f) => /^uwsgi.*\.ini$/.test(f)).sort();
    expect(inis, 'the five uWSGI inis').toEqual([
      'uwsgi.debug.ini',
      'uwsgi.dev.ini',
      'uwsgi.ini',
      'uwsgi.modular.ini',
      'uwsgi.relay.ini',
    ]);
    for (const ini of inis) {
      const lines = read(`docker/${ini}`)
        .split('\n')
        .filter((l) => !/^\s*[#;]/.test(l));
      const formats = lines.filter((l) => /^\s*log-format\s*=/.test(l));
      // Without a log-format, uWSGI's default request line prints the URI.
      expect(formats.length, `${ini} sets exactly one log-format`).toBe(1);
      expect(formats[0], `${ini}'s log-format prints %(var.${UWSGI_VAR})`).toContain(`%(var.${UWSGI_VAR})`);
      expect(formats[0], `${ini}'s log-format prints no raw URI, query or referer`).not.toMatch(
        /%\((?:uri|referer|var\.(?:REQUEST_URI|PATH_INFO|QUERY_STRING|DOCUMENT_URI|HTTP_REFERER|HTTP_X_ORIGINAL_URI))\)/
      );
      // uWSGI's "… during GET <raw URI> (<ip>)" and SIGPIPE lines.
      for (const flag of ['ignore-sigpipe', 'ignore-write-errors']) {
        expect(
          lines.some((l) => new RegExp(`^\\s*${flag}\\s*=\\s*true\\s*$`).test(l)),
          `${ini} sets ${flag} = true`
        ).toBe(true);
      }
      expect(
        lines.some((l) => /^\s*disable-write-exception\b/.test(l)) && ini !== 'uwsgi.debug.ini',
        `${ini} leaves disable-write-exception unset, so the app still sees a failed write`
      ).toBe(false);
    }
  });
});
