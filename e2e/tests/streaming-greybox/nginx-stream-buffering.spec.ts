import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { test, expect } from '../../fixtures';

const execFileAsync = promisify(execFile);

// Mirrors the container-name resolution in output-profile-sharing.spec.ts.
const CONTAINER_NAME = process.env.DISPATCHARR_E2E_CONTAINER || 'dispatcharr-e2e';

/** One `location` block's header line, parsed into its target path. */
const LOCATION_HEADER_RE = /^\s*location\s+(?:(=|~\*?|\^~)\s+)?(\S+)\s*\{\s*$/;

interface LocationBlock {
  /** The raw header line, for failure messages. */
  header: string;
  /** The location's own target — a regex modifier's `^` anchor stripped, so
   *  `location ~ ^/proxy/foo` and `location /proxy/foo` compare the same way. */
  target: string;
  /** Every line strictly between the header's `{` and its matching `}`. */
  body: string[];
}

/**
 * Parses `nginx -T`'s resolved config into every top-level `location` block,
 * by brace depth rather than a fixed indentation guess — `nginx -T` echoes
 * the files verbatim under a `# configuration file …:` banner, so
 * indentation is whatever the config author used, not something nginx
 * normalises; brace depth is the only reliable structure.
 */
function parseLocationBlocks(config: string): LocationBlock[] {
  const lines = config.split('\n');
  const blocks: LocationBlock[] = [];

  for (let i = 0; i < lines.length; i++) {
    const match = LOCATION_HEADER_RE.exec(lines[i]);
    if (!match) continue;

    const [, modifier, rawTarget] = match;
    const target = modifier?.startsWith('~') ? rawTarget.replace(/^\^/, '') : rawTarget;

    let depth = 1;
    const body: string[] = [];
    let j = i + 1;
    for (; j < lines.length && depth > 0; j++) {
      for (const ch of lines[j]) {
        if (ch === '{') depth++;
        else if (ch === '}') depth--;
        if (depth === 0) break;
      }
      if (depth > 0) body.push(lines[j]);
    }

    blocks.push({ header: lines[i].trim(), target, body });
    i = j - 1;
  }

  return blocks;
}

/**
 * Pins the trap D7/the spec name for the streaming routes: every relay-bound
 * nginx location must run with `uwsgi_buffering off` (docker/nginx.conf,
 * CLAUDE.md § Architecture) — a past bug used `proxy_buffering off` (the
 * wrong directive family for `uwsgi_pass`) and nginx silently spooled live
 * TS to disk before forwarding it.
 *
 * This supersedes an earlier attempt at a *behavioural* spooling detector (a
 * dead-air upstream, timed against how fast Dispatcharr's own keep-alive
 * packets arrive). That approach doesn't work on this codebase: a from-open
 * dead-air connection only starts producing keep-alives once
 * `StreamManager`'s health monitor marks it unhealthy, which for a channel
 * that has never buffered any real data is gated behind the
 * `channel_init_grace_period` (60s default, `apps/proxy/config.py`) rather
 * than the faster `CONNECTION_TIMEOUT` — so no ceiling under a minute could
 * ever discriminate buffered nginx from Dispatcharr's own, unrelated,
 * initialization delay. Reading nginx's actual resolved configuration is a
 * direct, static pin of the one thing that matters and carries none of that
 * timing ambiguity.
 *
 * `nginx -T` (not the checked-in `docker/nginx.conf`) is read because it is
 * the *resolved* config the running container actually serves —
 * `docker/init/03-init-dispatcharr.sh` substitutes `NGINX_PORT` at container
 * start, and this test is exercising the deployed artifact, not the
 * template. PR 4 split the original single `/proxy/` location into the
 * relay-bound location table below, each with its own `uwsgi_pass` target —
 * nothing about this assertion depends on which upstream process nginx
 * forwards to, only on the directive nginx applies before it does.
 *
 * `@contract`, not `@characterization`, despite being on the `SUBPROCESS`
 * allowlist (normally a `@characterization` signal, `docs/adr/0002`): the
 * directive it pins is a load-bearing deploy fact that must survive the
 * process split, not an implementation detail of the current single-process
 * shape. PR 4 is the process split this test was written to survive — its
 * location filter now covers every location that split introduced, not just
 * the original single `/proxy/` block.
 *
 * PR 5 (the authorize hop, ADR 0005) adds two more load-bearing properties
 * to the same location table, pinned by the two tests below rather than a
 * new file: every relay-bound location runs `auth_request
 * /_dispatcharr/authorize` and reads back all six `auth_request_set`
 * variables — five carrying the hop's decision (`$relay_channel`,
 * `$relay_output`, `$relay_client`, `$relay_user`, `$relay_name`), the
 * sixth (`$authorize_status`) carrying the real status code the
 * `ngx_http_auth_request_module` cannot transport itself (it allows on 2xx
 * and denies with 401/403 verbatim, but calls every other subrequest status
 * an error) — plus the `error_page 403 = @authorize_denied` that restores
 * it. Every location that is *not* behind the hop instead carries the
 * `dispatcharr_api_params.conf` blanking include and issues no
 * `auth_request` at all. Neither property is meaningful alone: a relay-bound
 * location that ran the hop but never blanked a client's own headers
 * elsewhere would still let a request into a non-relay-bound Django view
 * carry a forged `X-Relay-Channel`, since both processes share one urlconf
 * (D1). The pair together is what makes the trust marker unforgeable.
 *
 * Stage 2d-3 splits every assertion below by DIRECTIVE FAMILY rather than
 * changing what any of them claims. Three of the nine relay-bound locations
 * moved from uwsgi_pass to proxy_pass http://relay_go, where uwsgi_buffering
 * is inert and uwsgi_param is meaningless; the properties are identical and
 * the spellings are not. One assertion is genuinely NEW and is the reason
 * this file earns its keep at the flip: proxy_set_header is an ARRAY
 * directive, so a location declaring any of its own inherits none of the six
 * the server block declares -- and a config that pastes the working uwsgi
 * block and changes only _pass passes every other assertion here while
 * reporting nginx's own address as every viewer's ip_address.
 */

/**
 * The six relay-bound locations still served by the Python relay over
 * `uwsgi_pass` after stage 2d-3: VOD, catch-up, the XC VOD roots and
 * timeshift.
 *
 * **Exact targets, deliberately, not `startsWith` prefixes.** A prefix test
 * on `/proxy/vod/` also matches the `= /proxy/vod/stats/` and
 * `= /proxy/vod/stop_client/` exact locations, which stay on the API and
 * correctly carry no buffering directive at all — the same trap applies to
 * the three `/proxy/catchup/` control routes. Comparing whole targets keeps
 * the filter naming exactly the blocks it means.
 */
const UWSGI_BOUND_TARGETS = [
  '/proxy/vod/',
  '/proxy/catchup/',
  '/movie/',
  '/series/',
  '/timeshift/',
  '/streaming/timeshift.php',
];

/**
 * The three relay-bound locations stage 2d-3 moved to the Go relay over
 * `proxy_pass http://relay_go`. The last entry is the XC three-segment root
 * form: `parseLocationBlocks` strips a regex location's leading `^` from its
 * `target`, so this is the literal the parser produces for
 * `location ~ ^/[^/]+/[^/]+/\d+(?:\.[A-Za-z0-9]+)?$`.
 */
const PROXY_BOUND_TARGETS = [
  '/proxy/ts/stream/',
  '/live/',
  '/[^/]+/[^/]+/\\d+(?:\\.[A-Za-z0-9]+)?$',
];

/**
 * Both halves, for the assertions that are directive-family-agnostic: the
 * authorize subrequest, the eight `auth_request_set` variables and the
 * `error_page` that restores the hop's real status.
 *
 * Two locations are absent on purpose, for different reasons, and a third
 * because it cannot appear. `^~ /proxy/` stays on the API — it is the API's
 * own short IsAdmin control routes, never relay-bound. `^~ /proxy/relay/`
 * *is* relay-bound — Go-bound since 2d-3 — but runs no hop and carries no
 * buffering directive, correctly: it is the relay control API Phase 1 PR 7
 * mounted, and it serves short JSON rather than a stream. Its own properties
 * are pinned by the fourth test in this file.
 *
 * The third is absent because it cannot appear: PR 4 also routes
 * `^/api/channels/recordings/\d+/file/$` to the relay, but that location is
 * **nested inside `^~ /api/`**, and `parseLocationBlocks` walks by brace
 * depth from each `location` header — so the nested block's lines are part
 * of `/api/`'s own `body`, and it never surfaces as a separate entry with a
 * `target` of its own. Adding it to either list would make the set
 * assertions below fail on a correct config. Its `uwsgi_buffering off` is
 * pinned by `docker/nginx.conf` review and the plan's grep counts instead.
 */
const RELAY_BOUND_TARGETS = [...UWSGI_BOUND_TARGETS, ...PROXY_BOUND_TARGETS];

/**
 * The six the `server` block declares at `docker/nginx.conf:51-56`. Every
 * `proxy_pass` location must re-declare all six, because `proxy_set_header`
 * is an array directive and declaring one of your own discards the lot.
 * Names only: the values are nginx variables this test has no business
 * duplicating.
 */
const SERVER_LEVEL_PROXY_HEADERS = [
  'X-Real-IP',
  'X-Forwarded-For',
  'X-Forwarded-Host',
  'X-Forwarded-Proto',
  'Host',
  'X-Forwarded-Port',
];

test(
  'every relay-bound location keeps buffering off, in its own directive family',
  { tag: '@contract' },
  async () => {
    const { stdout } = await execFileAsync('docker', ['exec', CONTAINER_NAME, 'nginx', '-T']);
    const blocks = parseLocationBlocks(stdout);

    // Two halves, two vacuous-pass guards. uwsgi_buffering is INERT under
    // proxy_pass and proxy_buffering is inert under uwsgi_pass, so asserting
    // one directive over all nine would pass six and silently mean nothing on
    // the other three — which is exactly the trap CLAUDE.md's historical
    // incident describes, arriving from the opposite direction.
    //
    // Each half asserts the full set rather than "more than zero", so losing
    // five of the six (or two of the three) is a failure rather than a pass.
    for (const [targets, directive] of [
      [UWSGI_BOUND_TARGETS, 'uwsgi_buffering'],
      [PROXY_BOUND_TARGETS, 'proxy_buffering'],
    ] as const) {
      const found = blocks.filter((b) => targets.includes(b.target));
      expect(
        found.map((b) => b.target).sort(),
        `expected every ${directive} relay-bound location in nginx -T's output ` +
          `(${targets.join(', ')}); found blocks: ${blocks.map((b) => b.header).join(', ')}`
      ).toEqual([...targets].sort());

      for (const block of found) {
        expect(
          block.body.some((line) => new RegExp(`^\\s*${directive}\\s+off\\s*;`).test(line)),
          `location block "${block.header}" does not set ${directive} off:\n` +
            block.body.map((l) => l.replace(/"[0-9a-f]{64}"/, '"<marker>"')).join('\n')
        ).toBe(true);
      }
    }
  }
);

/**
 * The variables the hop's answer travels in. Order-independent: the
 * assertion is set membership, so reordering the block in nginx.conf is
 * not a failure.
 */
const AUTH_REQUEST_SET_VARS = [
  '$relay_name',
  '$relay_channel',
  '$relay_output',
  '$relay_client',
  '$relay_user',
  // 2b-2: resolved once by the hop so the relay re-reads no User row
  // and needs no trusted-proxy configuration of its own.
  '$relay_output_format',
  '$relay_client_ip',
  // The eighth carries the status the module cannot transport: a 404 or
  // 429 decision arrives as 403 and error_page turns it back.
  '$authorize_status',
];

// The subset that is actually forwarded to the relay. $relay_name is
// captured for `uwsgi_pass $relay_upstream` and never sent onward, so
// this list is one shorter than the one above and must stay that way --
// principle 5: capturing a variable and forwarding it are two different
// things, and a test that checks only the first leaves nine locations'
// worth of middle unpinned.
//
// HEADER names, not uwsgi_param names: since 2d-3 the same seven values
// travel as `uwsgi_param HTTP_X_RELAY_CHANNEL` on six locations and
// `proxy_set_header X-Relay-Channel` on three. One list, two spellings
// derived from it, so the halves cannot drift apart.
const FORWARDED_RELAY_HEADERS = [
  'X-Relay-Channel',
  'X-Relay-Output',
  'X-Relay-Client',
  'X-Relay-User',
  'X-Relay-Output-Format',
  'X-Relay-Client-IP',
];

/** `X-Relay-Channel` -> `HTTP_X_RELAY_CHANNEL`, nginx's HTTP_-prefixed form. */
const uwsgiParamName = (header: string) => `HTTP_${header.toUpperCase().replace(/-/g, '_')}`;

test(
  'every relay-bound location authorizes through the hop',
  { tag: '@contract' },
  async () => {
    const { stdout } = await execFileAsync('docker', ['exec', CONTAINER_NAME, 'nginx', '-T']);
    const blocks = parseLocationBlocks(stdout);
    const relayBlocks = blocks.filter((b) => RELAY_BOUND_TARGETS.includes(b.target));

    // Same vacuous-pass guard as the buffering test above: an empty array
    // would pass every loop below while proving nothing.
    expect(
      relayBlocks.map((b) => b.target).sort(),
      `expected every relay-bound location in nginx -T's output; found: ${blocks.map((b) => b.header).join(', ')}`
    ).toEqual([...RELAY_BOUND_TARGETS].sort());

    for (const block of relayBlocks) {
      expect(
        block.body.some((line) => /^\s*auth_request\s+\/_dispatcharr\/authorize\s*;/.test(line)),
        `location "${block.header}" does not issue the authorize subrequest:\n${block.body.map((l) => l.replace(/"[0-9a-f]{64}"/, '"<marker>"')).join('\n')}`
      ).toBe(true);

      for (const variable of AUTH_REQUEST_SET_VARS) {
        expect(
          block.body.some((line) =>
            new RegExp(`^\\s*auth_request_set\\s+\\${variable}\\s`).test(line)
          ),
          `location "${block.header}" does not set ${variable} from the subrequest`
        ).toBe(true);
      }

      const proxied = PROXY_BOUND_TARGETS.includes(block.target);

      // The other half of the chain. auth_request_set copies the
      // subrequest's response header into a variable; only a uwsgi_param or
      // a proxy_set_header sends it to the relay -- and either form is also
      // what overrides whatever the client sent under the same name. A
      // location that captures but does not forward looks correct in the
      // config and silently strips the header.
      for (const header of FORWARDED_RELAY_HEADERS) {
        const pattern = proxied
          ? new RegExp(`^\\s*proxy_set_header\\s+${header}\\s+\\$relay_`)
          : new RegExp(`^\\s*uwsgi_param\\s+${uwsgiParamName(header)}\\s+\\$relay_`);
        expect(
          block.body.some((line) => pattern.test(line)),
          `location "${block.header}" captures but does not forward ${header}`
        ).toBe(true);
      }

      // The marker: a literal "1" here would let anyone who can reach the
      // relay's port hand it a hand-written X-Relay-Channel. The sed'd
      // value is a 64-character hex digest, and the placeholder itself
      // reaching a running container means 03-init-dispatcharr.sh did not
      // substitute it — which would 403 every tune.
      const markerRe = proxied
        ? /proxy_set_header\s+X-Dispatcharr-Authorized/
        : /uwsgi_param\s+HTTP_X_DISPATCHARR_AUTHORIZED/;
      const marker = block.body.find((line) => markerRe.test(line));
      expect(marker, `location "${block.header}" sets no trust marker`).toBeTruthy();
      expect(marker).toMatch(/"[0-9a-f]{64}"/);

      // NEW at 2d-3, and the reason this file earns its keep at the flip.
      // proxy_set_header is an ARRAY directive: the moment this location
      // declares one of its own it inherits NONE of the six the server block
      // declares at nginx.conf:51-56. A config that pastes the working uwsgi
      // block and changes only _pass satisfies every assertion above and
      // reports nginx's own address as every viewer's ip_address on both
      // status endpoints -- invisible in dev, invisible in a smoke test,
      // wrong in production, while VOD and catch-up keep reporting
      // correctly. Only the three proxy_pass locations: the fourth flipped
      // location, ^~ /proxy/relay/, deliberately needs none of the six --
      // its client is Django, not a viewer -- and is covered by the fourth
      // test instead.
      if (proxied) {
        for (const header of SERVER_LEVEL_PROXY_HEADERS) {
          expect(
            block.body.some((line) =>
              new RegExp(`^\\s*proxy_set_header\\s+${header}\\s`).test(line)
            ),
            `location "${block.header}" does not re-declare the server-level ` +
              `proxy_set_header ${header}; declaring any proxy_set_header of its own ` +
              'discards all six'
          ).toBe(true);
        }

        // A second simple-directive trap, found only after the flip shipped:
        // proxy_connect_timeout is a SIMPLE directive (unlike the six above)
        // and inherits normally -- but nginx.conf:64 sets a server-level
        // proxy_connect_timeout 75 for an unrelated proxy_pass elsewhere in
        // this file. uwsgi_pass never set uwsgi_connect_timeout on these
        // locations, so they used nginx's implicit 60s default; proxy_pass
        // silently inherited the unrelated 75s instead. 75s exceeds
        // docker/tests/test-puid-pgid.sh's test_role_split 70s client-side
        // budget for "the relay container is stopped, expect
        // 502/503/504" -- measured as a real CI regression (ERR:timed out),
        // not a flake, and puid-pgid only runs in full mode
        // (migration/** or workflow_dispatch), so this is the only
        // assertion of it that runs on an ordinary PR touching docker/.
        expect(
          block.body.some((line) => /^\s*proxy_connect_timeout\s+60s\s*;/.test(line)),
          `location "${block.header}" does not set proxy_connect_timeout 60s; without it, ` +
            'this proxy_pass location silently inherits the server block\'s ' +
            'proxy_connect_timeout 75 (set for an unrelated location), which exceeds ' +
            "test-puid-pgid.sh's test_role_split 70s budget"
        ).toBe(true);
      }

      // Without this, a 404 or 429 decision reaches the viewer as 500:
      // the auth_request module denies verbatim on 401 and 403 only.
      expect(
        block.body.some((line) =>
          /^\s*error_page\s+403\s*=\s*@authorize_denied\s*;/.test(line)
        ),
        `location "${block.header}" does not restore the hop's real status`
      ).toBe(true);
    }

    // The named location the error_page above points at. A dangling
    // error_page target is a 500 on every denial, which is the failure
    // this whole block exists to prevent.
    const denied = blocks.find((b) => b.target === '@authorize_denied');
    expect(denied, 'no location @authorize_denied').toBeTruthy();
    expect(denied!.body.some((line) => /\$authorize_status\s*=\s*404/.test(line))).toBe(true);
    expect(denied!.body.some((line) => /\$authorize_status\s*=\s*429/.test(line))).toBe(true);
    expect(denied!.body.some((line) => /^\s*return\s+403\s*;/.test(line))).toBe(true);

    // The authorize location itself must exist and be internal, or every
    // subrequest above is a 404 that nginx reports as a 500.
    const authorize = blocks.find((b) => b.target === '/_dispatcharr/authorize');
    expect(authorize, 'no = /_dispatcharr/authorize location').toBeTruthy();
    expect(authorize!.body.some((line) => /^\s*internal\s*;/.test(line))).toBe(true);
  }
);

test(
  'every location outside the hop blanks the trust params',
  { tag: '@contract' },
  async () => {
    const { stdout } = await execFileAsync('docker', ['exec', CONTAINER_NAME, 'nginx', '-T']);
    const blocks = parseLocationBlocks(stdout);

    // Both processes run one urlconf (spec D1), so a stream view is
    // reachable through any Django-bound location. Each of these must
    // therefore overwrite the five params a client could otherwise send.
    const blanked = [
      '/',
      '/api/',
      '/output/',
      '/hdhr',
      '/proxy/',
      '/proxy/ts/status',
      '/proxy/vod/stats/',
      '/proxy/vod/stop_client/',
      '/proxy/catchup/stats/',
      '/proxy/catchup/programs/',
      '/proxy/catchup/stop_client/',
      '/_dispatcharr/authorize',
    ];

    for (const target of blanked) {
      const block = blocks.find((b) => b.target === target);
      expect(block, `no location for ${target}`).toBeTruthy();
      expect(
        block!.body.some((line) => /dispatcharr_api_params\.conf\s*;/.test(line)),
        `location "${block!.header}" does not include the blanking params`
      ).toBe(true);
      expect(
        block!.body.some((line) => /^\s*auth_request\s+\//.test(line)),
        `location "${block!.header}" must not run the authorize subrequest`
      ).toBe(false);
    }

    // The include is the mechanism; these are the names it must blank.
    // Asserting the include's presence alone cannot tell a five-name
    // file from a seven-name one, which is exactly the drift 2b-2
    // introduces.
    //
    // The uwsgi_param spelling is derived from FORWARDED_RELAY_HEADERS
    // rather than listed again: 2d-3 changed that constant to hold header
    // names so the two families cannot drift, and a second hand-written
    // list here would reintroduce exactly the drift it removed.
    const paramsFile = stdout.match(
      /# configuration file \/etc\/nginx\/dispatcharr_api_params\.conf:\n([\s\S]*?)(?=\n# configuration file |\n*$)/
    );
    expect(paramsFile, 'nginx -T did not dump dispatcharr_api_params.conf').toBeTruthy();
    for (const param of [
      'HTTP_X_DISPATCHARR_AUTHORIZED',
      ...FORWARDED_RELAY_HEADERS.map(uwsgiParamName),
    ]) {
      expect(
        new RegExp(`^\\s*uwsgi_param\\s+${param}\\s+""\\s*;`, 'm').test(paramsFile![1]),
        `dispatcharr_api_params.conf does not blank ${param}`
      ).toBe(true);
    }

    // The proxy_pass twin, new at 2d-3 and asserted for the same reason.
    // ^~ /proxy/relay/ is the only location that includes it, and the fourth
    // test below asserts that it does; this asserts the file's contents.
    const proxyParamsFile = stdout.match(
      /# configuration file \/etc\/nginx\/dispatcharr_api_params_proxy\.conf:\n([\s\S]*?)(?=\n# configuration file |\n*$)/
    );
    expect(
      proxyParamsFile,
      'nginx -T did not dump dispatcharr_api_params_proxy.conf'
    ).toBeTruthy();
    for (const header of ['X-Dispatcharr-Authorized', ...FORWARDED_RELAY_HEADERS]) {
      expect(
        new RegExp(`^\\s*proxy_set_header\\s+${header}\\s+""\\s*;`, 'm').test(
          proxyParamsFile![1]
        ),
        `dispatcharr_api_params_proxy.conf does not blank ${header}`
      ).toBe(true);
    }

    // The nested recordings-file location never surfaces as its own block
    // (parseLocationBlocks walks by brace depth from each header, so its
    // lines are part of /api/'s body). Assert on that body instead: it is
    // relay-bound, and it must carry neither an auth_request nor a
    // $relay_upstream pass.
    const api = blocks.find((b) => b.target === '/api/')!;
    // Match the location header, not the word in the comment above it: a
    // deleted nested location with its explanatory comment left behind
    // would otherwise still pass.
    expect(
      api.body.some((line) => /location\s+~\s+\^\/api\/channels\/recordings/.test(line)),
      'the nested recordings-file location is gone from ^~ /api/'
    ).toBe(true);
    expect(api.body.some((line) => /^\s*auth_request\s+\//.test(line))).toBe(false);
  }
);

test(
  'the relay control API is routed to the relay and gated by no nginx-level authorizer',
  { tag: '@contract' },
  async () => {
    const { stdout } = await execFileAsync('docker', ['exec', CONTAINER_NAME, 'nginx', '-T']);
    const blocks = parseLocationBlocks(stdout);
    const block = blocks.find((b) => b.target === '/proxy/relay/');
    expect(block, 'no ^~ /proxy/relay/ location found').toBeTruthy();

    // Relay-bound: these five routes exist so no control-plane process
    // reads a relay-owned Redis key, which only works if they reach the
    // relay. A literal upstream group, not $relay_upstream: no
    // subrequest runs here, so $relay_name is unset and a variable pass
    // nothing feeds is a thing a reader has to disprove -- and since 2d-3
    // the group is relay_go, hardcoded rather than mapped, because D3 keeps
    // the map and relay_py untouched for the five locations that did not
    // move.
    expect(
      block!.body.some((line) => /^\s*proxy_pass\s+http:\/\/relay_go\s*;/.test(line)),
      'the relay control API must reach the relay'
    ).toBe(true);

    // NOT internal;. Django dials these as an ordinary HTTP client --
    // from the worker container across the compose network, and from
    // the api container through this nginx -- and `internal;` would 404
    // every one of those calls.
    expect(
      block!.body.some((line) => /^\s*internal\s*;/.test(line)),
      'the relay control API must stay reachable by Django, which is an ordinary client here'
    ).toBe(false);

    // The token is the whole gate (D9): authorize_stream() would 404 a
    // URI that names no channel, so the hop must not sit in front of it.
    expect(
      block!.body.some((line) => /^\s*auth_request\s+\//.test(line)),
      'the relay control API must not run the authorize subrequest'
    ).toBe(false);

    // A client-supplied X-Relay-* header still never reaches the relay
    // on this path.
    expect(
      block!.body.some((line) => /dispatcharr_api_params_proxy\.conf\s*;/.test(line)),
      'the relay control API must still blank the trust params'
    ).toBe(true);

    // POST .../advance waits on the owner's confirmation for up to
    // STREAM_SWITCH_CONFIRM_TIMEOUT = 15s; relay_client allows 20s.
    // An explicit window above both keeps the client's timeout the one
    // that fires rather than nginx's 60s default.
    expect(
      block!.body.some((line) => /^\s*proxy_read_timeout\s+30s\s*;/.test(line)),
      'the relay control API needs a read timeout above the advance budget'
    ).toBe(true);

    // Same simple-directive trap as the three byte-path locations (see the
    // second test's comment): without an explicit proxy_connect_timeout this
    // location inherits nginx.conf:64's server-level proxy_connect_timeout 75,
    // set for an unrelated proxy_pass. relay_client.py's own 2s connect
    // timeout fires first in practice, but nginx's own budget should still
    // match the pre-flip uwsgi default rather than an unrelated directive.
    expect(
      block!.body.some((line) => /^\s*proxy_connect_timeout\s+60s\s*;/.test(line)),
      'the relay control API does not set proxy_connect_timeout 60s; without it, it silently ' +
        "inherits the server block's proxy_connect_timeout 75 (set for an unrelated location)"
    ).toBe(true);
  }
);
