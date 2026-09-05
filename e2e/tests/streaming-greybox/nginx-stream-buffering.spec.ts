import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { test, expect } from '../../fixtures';

const execFileAsync = promisify(execFile);

// Mirrors the container-name resolution in output-profile-sharing.spec.ts
// (and fixtures/greybox/redis.ts, which this file does not import — reading
// nginx's own config isn't a Redis operation).
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
 */

/**
 * Every relay-bound location as of Phase 1 PR 4 (docker/nginx.conf), by the
 * exact `target` `parseLocationBlocks` produces for it. Widened from the
 * original single `/proxy/` prefix once that block split into eight
 * relay-bound locations plus the XC three-segment regex — this list is what
 * keeps the buffering pin covering the whole relay surface rather than the
 * one route it happened to be written against.
 *
 * **Exact targets, deliberately, not `startsWith` prefixes.** A prefix test
 * on `/proxy/vod/` also matches the `= /proxy/vod/stats/` and
 * `= /proxy/vod/stop_client/` exact locations, which stay on the API and
 * correctly carry no `uwsgi_buffering off` — the same trap applies to the
 * three `/proxy/catchup/` control routes. Comparing whole targets keeps the
 * filter naming exactly the nine blocks it means.
 *
 * Two locations are absent on purpose, for different reasons: `^~ /proxy/`
 * stays on the API — it is the API's own short IsAdmin control routes, never
 * `uwsgi_pass relay_py`. `^~ /proxy/relay/` *is* relay-bound
 * (`uwsgi_pass relay_py`) but carries no `uwsgi_buffering off`, correctly:
 * it is PR 7's still-unmounted control API, which will serve short JSON
 * rather than a stream.
 *
 * A third is absent because it cannot appear: PR 4 also routes
 * `^/api/channels/recordings/\d+/file/$` to the relay, but that location is
 * **nested inside `^~ /api/`**, and `parseLocationBlocks` walks by brace
 * depth from each `location` header — so the nested block's lines are part
 * of `/api/`'s own `body`, and it never surfaces as a separate entry with a
 * `target` of its own. Adding it to this list would make the set assertion
 * below fail on a correct config. Its `uwsgi_buffering off` is pinned by
 * `docker/nginx.conf` review and Task 5's grep counts instead.
 *
 * The last entry is the XC three-segment root form: `parseLocationBlocks`
 * strips a regex location's leading `^` from its `target`, so this is the
 * literal the parser produces for
 * `location ~ ^/[^/]+/[^/]+/\d+(?:\.[A-Za-z0-9]+)?$`.
 */
const RELAY_BOUND_TARGETS = [
  '/proxy/ts/stream/',
  '/proxy/vod/',
  '/proxy/catchup/',
  '/live/',
  '/movie/',
  '/series/',
  '/timeshift/',
  '/streaming/timeshift.php',
  '/[^/]+/[^/]+/\\d+(?:\\.[A-Za-z0-9]+)?$',
];

test(
  'every relay-bound location keeps uwsgi_buffering off',
  { tag: '@contract' },
  async () => {
    const { stdout } = await execFileAsync('docker', ['exec', CONTAINER_NAME, 'nginx', '-T']);
    const blocks = parseLocationBlocks(stdout);
    const relayBlocks = blocks.filter((b) => RELAY_BOUND_TARGETS.includes(b.target));

    // Vacuous-pass guard: if nginx's config ever stops declaring these
    // locations (renamed, merged, or the relay split reverted), the loop
    // below would pass over an empty array and this test would silently
    // stop meaning anything. Fail loudly instead — and assert the full set,
    // not just "more than zero", so losing eight of the nine is a failure
    // rather than a pass.
    expect(
      relayBlocks.map((b) => b.target).sort(),
      `expected every relay-bound location in nginx -T's output (${RELAY_BOUND_TARGETS.join(', ')}); found blocks: ${blocks.map((b) => b.header).join(', ')}`
    ).toEqual([...RELAY_BOUND_TARGETS].sort());

    for (const block of relayBlocks) {
      expect(
        block.body.some((line) => /^\s*uwsgi_buffering\s+off\s*;/.test(line)),
        `location block "${block.header}" does not set uwsgi_buffering off:\n${block.body.map((l) => l.replace(/"[0-9a-f]{64}"/, '"<marker>"')).join('\n')}`
      ).toBe(true);
    }
  }
);

/**
 * The five variables the hop's answer travels in. Order-independent: the
 * assertion is set membership, so reordering the block in nginx.conf is
 * not a failure.
 */
const AUTH_REQUEST_SET_VARS = [
  '$relay_name',
  '$relay_channel',
  '$relay_output',
  '$relay_client',
  '$relay_user',
  // The sixth carries the status the module cannot transport: a 404 or
  // 429 decision arrives as 403 and error_page turns it back.
  '$authorize_status',
];

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

      // The marker: a literal "1" here would let anyone who can reach the
      // relay's port hand it a hand-written X-Relay-Channel. The sed'd
      // value is a 64-character hex digest, and the placeholder itself
      // reaching a running container means 03-init-dispatcharr.sh did not
      // substitute it — which would 403 every tune.
      const marker = block.body.find((line) =>
        /uwsgi_param\s+HTTP_X_DISPATCHARR_AUTHORIZED/.test(line)
      );
      expect(marker, `location "${block.header}" sets no trust marker`).toBeTruthy();
      expect(marker).toMatch(/"[0-9a-f]{64}"/);

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
      '/proxy/relay/',
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
