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
 * shape. A red run here is meant to block PR 4 by design, the way any other
 * `@contract` test does.
 */
test(
  'the /proxy/ location keeps uwsgi_buffering off',
  { tag: '@contract' },
  async () => {
    const { stdout } = await execFileAsync('docker', ['exec', CONTAINER_NAME, 'nginx', '-T']);
    const blocks = parseLocationBlocks(stdout);
    const proxyBlocks = blocks.filter((b) => b.target.startsWith('/proxy/'));

    // Vacuous-pass guard: if nginx's config ever stops declaring a /proxy/
    // location at all (renamed, merged into another block), the `.every()`
    // below would pass on an empty array and this test would silently stop
    // meaning anything. Fail loudly instead.
    expect(
      proxyBlocks.length,
      `expected at least one location block targeting /proxy/ in nginx -T's output; found blocks: ${blocks.map((b) => b.header).join(', ')}`
    ).toBeGreaterThan(0);

    for (const block of proxyBlocks) {
      expect(
        block.body.some((line) => /^\s*uwsgi_buffering\s+off\s*;/.test(line)),
        `location block "${block.header}" does not set uwsgi_buffering off:\n${block.body.join('\n')}`
      ).toBe(true);
    }
  }
);
