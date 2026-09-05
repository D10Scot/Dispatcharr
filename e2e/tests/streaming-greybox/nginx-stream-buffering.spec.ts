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
 * Pins the trap D7/the spec name for the streaming route: nginx's `/proxy/`
 * location must run with `uwsgi_buffering off` (docker/nginx.conf,
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
 * template. PR 4, which gives `/proxy/`'s route its own nginx location as
 * part of the relay split, must keep this passing — nothing about this
 * assertion depends on which upstream process nginx forwards to, only on
 * the directive nginx applies before it does.
 *
 * `@contract`, not `@characterization`, despite being on the `SUBPROCESS`
 * allowlist (normally a `@characterization` signal, `docs/adr/0002`): the
 * directive it pins is a load-bearing deploy fact that must survive the
 * process split, not an implementation detail of the current single-process
 * shape. PR 4 is the process split this test was written to survive — its
 * location filter now covers every location that split introduced, not just
 * the original single `/proxy/` block.
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
 * Two relay-adjacent locations are absent on purpose: `^~ /proxy/`, which is
 * the API's own short IsAdmin control routes, and `^~ /proxy/relay/`, PR 7's
 * control API, which will serve short JSON rather than a stream.
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
 * literal the parser produces for `location ~ ^/[^/]+/[^/]+/[^/]+$`.
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
  '/[^/]+/[^/]+/[^/]+$',
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
        `location block "${block.header}" does not set uwsgi_buffering off:\n${block.body.join('\n')}`
      ).toBe(true);
    }
  }
);
