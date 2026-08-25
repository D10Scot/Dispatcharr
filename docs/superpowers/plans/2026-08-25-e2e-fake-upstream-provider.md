# G2 Fake Upstream Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a controllable IPTV provider — M3U playlist, XMLTV EPG, a paced looping MPEG-TS stream, and a control API for eight fault modes — that Dispatcharr can ingest from and stream through in E2E tests.

**Architecture:** A standalone Node/TypeScript HTTP server in its own container on a user-defined Docker network shared with Dispatcharr, addressed as `http://e2e-upstream:8080` from inside the container and `http://127.0.0.1:<published>` from the Playwright host. Isolation is by scenario id in the URL path, so one container serves every worker and every test. A pre-baked TS asset is served in a loop, paced at nominal bitrate, with continuity counters, PCR and PTS/DTS rewritten across the loop seam.

**Tech Stack:** Node 24, TypeScript 5.7.2, vitest, Node's built-in `node:http` (no framework), ffmpeg (build-time only), Docker.

**Spec:** `docs/superpowers/specs/2026-08-25-e2e-fake-upstream-provider-design.md`

## Global Constraints

- **Node's standard library only** for the server. No express, fastify, koa. The whole surface is a dozen routes and byte-level stream control; a framework adds a dependency to audit and hides the socket.
- **TypeScript strict mode**, matching `e2e/tsconfig.json`: `"strict": true`, `"target": "ES2022"`, `"module": "ESNext"`, `"moduleResolution": "bundler"`.
- **Every `uses:` in a workflow is a full 40-character commit SHA** with the version as a trailing comment. Resolve with `gh api repos/<owner>/<repo>/commits/<tag> --jq .sha`. Never type or guess one.
- **Every `FROM` is `image:tag@sha256:<digest>`.** Resolve with `docker buildx imagetools inspect <image>:<tag>`. Never hand-type a digest.
- **Workflows set `permissions: contents: read` at the top level**, and every `actions/checkout` sets `persist-credentials: false`.
- **zizmor is a ratchet held at zero findings.** A `PostToolUse` hook blocks on *every* finding in an edited workflow file, legacy included.
- **`e2e/support/static-upstream.ts` is deleted in Task 9**, not before. Tasks 1–8 leave it working.
- **No product code is modified.** Bugs found are filed with `gh issue create --repo D10Scot/Dispatcharr` — always with the explicit `--repo` flag, because this clone is a fork and `gh` otherwise resolves to the upstream public tracker.
- **Credentials go in the URL string**, never on `M3UAccount.username`/`password` or `EPGSource.username`/`password`. The product does not send those on standard M3U or XMLTV fetches.
- **Ports:** the provider listens on `8080` inside its container, published to `127.0.0.1:9402`. Never 9191.
- **Naming:** "scenario" and "fault" are the canonical terms. Not "session", "instance", "mode", "failure".
- **Commit after every task.** The commit command is spelled out in each task's final step.

---

### Task 1: Provider skeleton, container, and network

Proves the thing the whole goal rests on: that a Dispatcharr container can resolve and reach the provider by container name. Nothing else is built until this is green.

**Files:**
- Create: `e2e-upstream/package.json`, `e2e-upstream/tsconfig.json`, `e2e-upstream/vitest.config.ts`, `e2e-upstream/Dockerfile`, `e2e-upstream/.dockerignore`, `e2e-upstream/src/server.ts`, `e2e-upstream/src/index.ts`
- Modify: `scripts/e2e_up.sh`
- Test: `e2e-upstream/test/server.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `startServer(port: number): Promise<RunningServer>` and `sendJson(res: ServerResponse, status: number, body: unknown): void` from `src/server.ts`, where `RunningServer` is `{ close(): Promise<void>; port: number }`. Container name `e2e-upstream`, network `dispatcharr-e2e-net`, published control port `9402` on `127.0.0.1`.

- [ ] **Step 1: Write the failing test**

`e2e-upstream/test/server.test.ts`:

```ts
import { describe, it, expect, afterEach } from 'vitest';
import { startServer } from '../src/server';

let server: Awaited<ReturnType<typeof startServer>> | undefined;

afterEach(async () => {
  await server?.close();
  server = undefined;
});

describe('server', () => {
  it('answers GET /scenarios with an empty list', async () => {
    server = await startServer(0);
    const res = await fetch(`http://127.0.0.1:${server.port}/scenarios`);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual([]);
  });

  it('answers an unknown path with 404 and a JSON body naming the path', async () => {
    server = await startServer(0);
    const res = await fetch(`http://127.0.0.1:${server.port}/nope`);
    expect(res.status).toBe(404);
    // A bare 404 is indistinguishable from the `not-found` fault. Naming the
    // path is what tells a test author "you asked for the wrong URL" rather
    // than "the fault fired".
    expect(await res.json()).toMatchObject({
      error: expect.stringContaining('/nope'),
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd e2e-upstream && npm install && npx vitest run`
Expected: FAIL — `Cannot find module '../src/server'`

- [ ] **Step 3: Scaffold the package**

`e2e-upstream/package.json`:

```json
{
  "name": "dispatcharr-e2e-upstream",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "build": "tsc",
    "start": "node dist/index.js",
    "test": "vitest run",
    "typecheck": "tsc --noEmit"
  },
  "devDependencies": {
    "@types/node": "24.0.0",
    "typescript": "5.7.2",
    "vitest": "3.2.4"
  }
}
```

`e2e-upstream/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "lib": ["ES2022"],
    "types": ["node"],
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "outDir": "dist",
    "rootDir": "."
  },
  "include": ["src/**/*.ts"],
  "exclude": ["node_modules", "dist", "test"]
}
```

`e2e-upstream/vitest.config.ts`:

```ts
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['test/**/*.test.ts'],
    // The seam and pacing tests move real time; the 5s default is not enough.
    testTimeout: 30_000,
  },
});
```

`e2e-upstream/.dockerignore` — note the `**/` prefixes. `.dockerignore` matching is **not** recursive without them, unlike `.gitignore`; a bare `node_modules` line silently fails to exclude nested ones, which is a mistake already made once in this repo:

```
**/node_modules
**/dist
**/assets
```

- [ ] **Step 4: Write the server**

`e2e-upstream/src/server.ts`:

```ts
import http from 'node:http';
import type { IncomingMessage, ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';

export interface RunningServer {
  close(): Promise<void>;
  port: number;
}

export function sendJson(res: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(payload),
  });
  res.end(payload);
}

async function handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const url = new URL(req.url ?? '/', 'http://placeholder');

  if (url.pathname === '/scenarios' && req.method === 'GET') {
    sendJson(res, 200, []);
    return;
  }

  sendJson(res, 404, { error: `no route for ${req.method} ${url.pathname}` });
}

export function startServer(port: number): Promise<RunningServer> {
  const server = http.createServer((req, res) => {
    handle(req, res).catch((error: unknown) => {
      // Without this the process dies on a handler throw and the container
      // restarts silently mid-test, which reads as a network flake.
      if (!res.headersSent) {
        sendJson(res, 500, { error: String(error) });
      } else {
        res.destroy();
      }
    });
  });

  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, '0.0.0.0', () => {
      resolve({
        port: (server.address() as AddressInfo).port,
        close: () =>
          new Promise<void>((done, fail) =>
            server.close((err) => (err ? fail(err) : done()))
          ),
      });
    });
  });
}
```

`e2e-upstream/src/index.ts`:

```ts
import { startServer } from './server';

const port = Number(process.env.UPSTREAM_PORT ?? 8080);

startServer(port).then((server) => {
  console.log(`e2e-upstream listening on ${server.port}`);
});
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd e2e-upstream && npx vitest run`
Expected: PASS, 2 tests

- [ ] **Step 6: Write the Dockerfile**

Resolve the digest first — do not copy the placeholder below:

```bash
docker buildx imagetools inspect node:24-slim --format '{{.Manifest.Digest}}'
```

`e2e-upstream/Dockerfile` (the ffmpeg builder stage is added in Task 4; this is the runtime-only shape):

```dockerfile
FROM node:24-slim@sha256:PUT_THE_RESOLVED_DIGEST_HERE AS runtime
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json ./
COPY src ./src
RUN npx tsc
EXPOSE 8080
CMD ["node", "dist/index.js"]
```

- [ ] **Step 7: Extend `scripts/e2e_up.sh`**

Add alongside the existing `NAME`/`VOLUME`/`IMAGE`/`PORT` block:

```bash
NETWORK="${DISPATCHARR_E2E_NETWORK:-dispatcharr-e2e-net}"
UPSTREAM_NAME="${DISPATCHARR_E2E_UPSTREAM_CONTAINER:-e2e-upstream}"
UPSTREAM_IMAGE="${DISPATCHARR_E2E_UPSTREAM_IMAGE:-dispatcharr-e2e-upstream:local}"
UPSTREAM_PORT="${DISPATCHARR_E2E_UPSTREAM_PORT:-9402}"
```

Extend `destroy()` to remove the provider container and the network:

```bash
destroy() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker rm -f "$UPSTREAM_NAME" >/dev/null 2>&1 || true
  docker volume rm "$VOLUME" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
}
```

Extend the `--stop` branch to stop both containers:

```bash
  --stop)
    docker stop "$UPSTREAM_NAME" >/dev/null 2>&1 && echo "Stopped $UPSTREAM_NAME." \
      || echo "$UPSTREAM_NAME was not running."
    docker stop "$NAME" >/dev/null 2>&1 && echo "Stopped $NAME." \
      || echo "$NAME was not running."
    exit 0
    ;;
```

Then, **before** the Dispatcharr `docker run`, add:

```bash
# Container-name DNS works only on a user-defined network. The default bridge
# resolves nothing, which is the entire reason this network exists.
docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK" >/dev/null

if ! docker image inspect "$UPSTREAM_IMAGE" >/dev/null 2>&1; then
  echo "Building $UPSTREAM_IMAGE..."
  docker build -f e2e-upstream/Dockerfile -t "$UPSTREAM_IMAGE" e2e-upstream
fi

if docker ps --format '{{.Names}}' | grep -qx "$UPSTREAM_NAME"; then
  : # already running
elif docker ps -a --format '{{.Names}}' | grep -qx "$UPSTREAM_NAME"; then
  docker start "$UPSTREAM_NAME" >/dev/null
else
  docker run -d --name "$UPSTREAM_NAME" \
    --network "$NETWORK" \
    -p "127.0.0.1:${UPSTREAM_PORT}:8080" \
    "$UPSTREAM_IMAGE" >/dev/null
fi

# Wait for the provider before starting Dispatcharr. Dispatcharr does not
# contact it at boot, so the ordering is not strictly required — but a test
# that fails because the provider was still starting is indistinguishable
# from one that fails because the provider is broken, and this removes that
# whole class of confusion.
echo -n "Waiting for the upstream provider"
for _ in $(seq 1 30); do
  if curl -sf -o /dev/null "http://127.0.0.1:${UPSTREAM_PORT}/scenarios"; then
    echo " — ready"
    break
  fi
  echo -n "."
  sleep 1
done
```

Add `--network "$NETWORK"` to the existing Dispatcharr `docker run` invocation.

- [ ] **Step 8: Prove container-to-container DNS**

Run:

```bash
./scripts/e2e_up.sh --down
./scripts/e2e_up.sh
docker exec dispatcharr-e2e curl -sf http://e2e-upstream:8080/scenarios
```

Expected: `[]`

**If this fails, stop and report it rather than working around it.** Every later task assumes it works, and the spec chose this design over `host.docker.internal` precisely on this claim. Record in the task report whether the host is Docker Desktop or Docker Engine (`docker info --format '{{.OperatingSystem}}'`), because CI is Engine and this step checks only one of them.

- [ ] **Step 9: Commit**

Stage, then commit as two separate commands — a repo hook rejects a single call that does both:

```bash
git add e2e-upstream scripts/e2e_up.sh
```

```bash
git commit -m "feat(e2e): scaffold the fake upstream provider and its network"
```

---

### Task 2: Scenario registry and lifecycle

**Files:**
- Create: `e2e-upstream/src/scenario.ts`
- Modify: `e2e-upstream/src/server.ts`
- Test: `e2e-upstream/test/scenario.test.ts`

**Interfaces:**
- Consumes: `sendJson(res, status, body)` from Task 1.
- Produces:

```ts
export interface ChannelSpec {
  id: number;
  name: string;
  tvgId: string;
  logo: string | null;
}

export interface ScenarioRequest {
  channels?: number | ChannelSpec[];
  username?: string;
  password?: string;
  maxConnections?: number;   // omitted = unlimited
  rate?: number;             // default 1
}

export interface Scenario {
  id: string;
  channels: ChannelSpec[];
  username?: string;
  password?: string;
  maxConnections: number | null;   // null = unlimited, 0 = reject all
  rate: number;
}

export class ScenarioRegistry {
  create(request: ScenarioRequest): Scenario;
  get(id: string): Scenario | undefined;
  list(): Scenario[];
  delete(id: string): boolean;
}
```

Also produced, from `src/server.ts`, for later tasks:

```ts
export function readJsonBody(req: IncomingMessage): Promise<unknown>;
export const registry: ScenarioRegistry;
```

- [ ] **Step 1: Write the failing test**

`e2e-upstream/test/scenario.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { ScenarioRegistry } from '../src/scenario';

describe('ScenarioRegistry', () => {
  it('generates the requested number of channels with distinct ids and tvg-ids', () => {
    const registry = new ScenarioRegistry();
    const scenario = registry.create({ channels: 3 });

    expect(scenario.channels).toHaveLength(3);
    expect(new Set(scenario.channels.map((c) => c.id)).size).toBe(3);
    expect(new Set(scenario.channels.map((c) => c.tvgId)).size).toBe(3);
  });

  it('defaults to unlimited connections, rate 1, and one channel', () => {
    const registry = new ScenarioRegistry();
    const scenario = registry.create({});

    expect(scenario.maxConnections).toBeNull();
    expect(scenario.rate).toBe(1);
    expect(scenario.channels).toHaveLength(1);
  });

  it('treats maxConnections 0 as reject-all, not as unlimited', () => {
    const registry = new ScenarioRegistry();
    // The distinction D10 rests on: null is unlimited, 0 is a real limit of
    // zero. `request.maxConnections || null` would silently collapse them and
    // disable every connection-limit test without failing anything.
    expect(registry.create({ maxConnections: 0 }).maxConnections).toBe(0);
  });

  it('accepts explicit channel specs verbatim', () => {
    const registry = new ScenarioRegistry();
    const scenario = registry.create({
      channels: [{ id: 7, name: 'Explicit', tvgId: 'explicit.tv', logo: null }],
    });

    expect(scenario.channels).toEqual([
      { id: 7, name: 'Explicit', tvgId: 'explicit.tv', logo: null },
    ]);
  });

  it('gives every scenario a distinct id and does not evict', () => {
    const registry = new ScenarioRegistry();
    const a = registry.create({});
    const b = registry.create({});

    expect(a.id).not.toBe(b.id);
    expect(registry.list()).toHaveLength(2);
    expect(registry.get(a.id)).toBe(a);
  });

  it('deletes on request and reports whether anything was deleted', () => {
    const registry = new ScenarioRegistry();
    const scenario = registry.create({});

    expect(registry.delete(scenario.id)).toBe(true);
    expect(registry.delete(scenario.id)).toBe(false);
    expect(registry.get(scenario.id)).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd e2e-upstream && npx vitest run test/scenario.test.ts`
Expected: FAIL — `Cannot find module '../src/scenario'`

- [ ] **Step 3: Implement the registry**

`e2e-upstream/src/scenario.ts`:

```ts
import { randomUUID } from 'node:crypto';

export interface ChannelSpec {
  id: number;
  name: string;
  tvgId: string;
  logo: string | null;
}

export interface ScenarioRequest {
  channels?: number | ChannelSpec[];
  username?: string;
  password?: string;
  maxConnections?: number;
  rate?: number;
}

export interface Scenario {
  id: string;
  channels: ChannelSpec[];
  username?: string;
  password?: string;
  /** null = unlimited. 0 is a real limit meaning reject everything. */
  maxConnections: number | null;
  rate: number;
}

function defaultChannels(count: number): ChannelSpec[] {
  return Array.from({ length: count }, (_unused, index) => {
    const n = index + 1;
    return {
      id: n,
      name: `Fake Channel ${n}`,
      tvgId: `fake-${n}.e2e`,
      // example.invalid is reserved by RFC 2606 and can never resolve, so a
      // logo URL cannot accidentally make a real network request.
      logo: `https://example.invalid/logo-${n}.png`,
    };
  });
}

export class ScenarioRegistry {
  private scenarios = new Map<string, Scenario>();

  create(request: ScenarioRequest): Scenario {
    const channels = Array.isArray(request.channels)
      ? request.channels
      : defaultChannels(request.channels ?? 1);

    const scenario: Scenario = {
      id: randomUUID(),
      channels,
      username: request.username,
      password: request.password,
      // `?? null`, never `|| null`: 0 is a real limit and must survive.
      maxConnections: request.maxConnections ?? null,
      rate: request.rate ?? 1,
    };

    this.scenarios.set(scenario.id, scenario);
    return scenario;
  }

  get(id: string): Scenario | undefined {
    return this.scenarios.get(id);
  }

  list(): Scenario[] {
    return [...this.scenarios.values()];
  }

  delete(id: string): boolean {
    return this.scenarios.delete(id);
  }
}
```

- [ ] **Step 4: Wire the control routes into the server**

In `src/server.ts`, add the imports and a module-level registry:

```ts
import { ScenarioRegistry } from './scenario';
import type { Scenario, ScenarioRequest } from './scenario';

export const registry = new ScenarioRegistry();

export async function readJsonBody(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  if (chunks.length === 0) return {};
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

/**
 * `internal` is what Dispatcharr is given; `control` is what the Playwright
 * host calls. They are never interchangeable — see "Two base URLs" in the
 * spec. INTERNAL_ORIGIN is what resolves inside the Docker network; the
 * control origin is echoed from the request's own Host header, so it is
 * correct whatever port the caller published.
 */
const INTERNAL_ORIGIN =
  process.env.UPSTREAM_INTERNAL_ORIGIN ?? 'http://e2e-upstream:8080';

function scenarioUrls(scenario: Scenario, req: IncomingMessage) {
  const credentialQuery =
    scenario.username === undefined
      ? ''
      : `?username=${encodeURIComponent(scenario.username)}` +
        `&password=${encodeURIComponent(scenario.password ?? '')}`;

  return {
    internal: `${INTERNAL_ORIGIN}/s/${scenario.id}`,
    control: `http://${req.headers.host ?? '127.0.0.1'}/s/${scenario.id}`,
    credentialQuery,
  };
}
```

Add these routes to `handle()`, before the 404 fallthrough:

```ts
if (url.pathname === '/scenarios' && req.method === 'POST') {
  const scenario = registry.create((await readJsonBody(req)) as ScenarioRequest);
  sendJson(res, 201, { ...scenario, ...scenarioUrls(scenario, req) });
  return;
}

if (url.pathname === '/scenarios' && req.method === 'GET') {
  sendJson(res, 200, registry.list().map((s) => ({ ...s, ...scenarioUrls(s, req) })));
  return;
}

const scenarioMatch = /^\/scenarios\/([^/]+)$/.exec(url.pathname);
if (scenarioMatch && req.method === 'DELETE') {
  sendJson(res, registry.delete(scenarioMatch[1]) ? 204 : 404, {});
  return;
}
```

The Task 1 test asserting `GET /scenarios` returns `[]` still passes: the registry is empty on a fresh process. Note that `registry` being module-level means vitest files sharing a process share it — every test in this suite that creates scenarios must therefore construct its own `ScenarioRegistry` rather than reaching for the exported one, which is what the tests above do.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd e2e-upstream && npx vitest run`
Expected: PASS, 8 tests

- [ ] **Step 6: Commit**

```bash
git add e2e-upstream
```

```bash
git commit -m "feat(e2e): scenario registry and lifecycle routes"
```

---
### Task 3: M3U playlist and XMLTV EPG generation

**Files:**
- Create: `e2e-upstream/src/playlist.ts`, `e2e-upstream/src/xmltv.ts`
- Modify: `e2e-upstream/src/server.ts`
- Test: `e2e-upstream/test/playlist.test.ts`, `e2e-upstream/test/xmltv.test.ts`

**Interfaces:**
- Consumes: `Scenario`, `ChannelSpec` (Task 2); `sendJson`, `registry`, `INTERNAL_ORIGIN` (Tasks 1–2).
- Produces:

```ts
export function renderPlaylist(scenario: Scenario, streamOrigin: string): string;
export const PLAYLIST_CONTENT_TYPE = 'application/vnd.apple.mpegurl';

export function renderXmltv(scenario: Scenario, now: Date): string;
export const XMLTV_CONTENT_TYPE = 'application/xml';
```

`streamOrigin` is always the **internal** origin: Dispatcharr is the consumer of these URLs, so they must resolve inside the Docker network even when a test fetched the playlist through the control origin to inspect it.

- [ ] **Step 1: Write the failing playlist test**

`e2e-upstream/test/playlist.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { ScenarioRegistry } from '../src/scenario';
import { renderPlaylist, PLAYLIST_CONTENT_TYPE } from '../src/playlist';

const ORIGIN = 'http://e2e-upstream:8080';

describe('renderPlaylist', () => {
  it('starts with the #EXTM3U header', () => {
    const scenario = new ScenarioRegistry().create({ channels: 1 });
    expect(renderPlaylist(scenario, ORIGIN).split('\n')[0]).toBe('#EXTM3U');
  });

  it('emits one EXTINF and one URL per channel, in order', () => {
    const scenario = new ScenarioRegistry().create({ channels: 2 });
    const lines = renderPlaylist(scenario, ORIGIN).trim().split('\n');

    // header + 2 channels * 2 lines
    expect(lines).toHaveLength(5);
    expect(lines[1]).toContain('tvg-id="fake-1.e2e"');
    expect(lines[2]).toBe(`${ORIGIN}/s/${scenario.id}/stream/1.ts`);
    expect(lines[3]).toContain('tvg-id="fake-2.e2e"');
    expect(lines[4]).toBe(`${ORIGIN}/s/${scenario.id}/stream/2.ts`);
  });

  it('carries the channel name after the comma, which is what Dispatcharr imports as the name', () => {
    const scenario = new ScenarioRegistry().create({
      channels: [{ id: 1, name: 'Named Channel', tvgId: 'named.e2e', logo: null }],
    });
    expect(renderPlaylist(scenario, ORIGIN)).toContain(',Named Channel');
  });

  it('omits tvg-logo entirely when a channel has no logo', () => {
    const scenario = new ScenarioRegistry().create({
      channels: [{ id: 1, name: 'No Logo', tvgId: 'nologo.e2e', logo: null }],
    });
    // An empty tvg-logo="" is not the same as an absent one, and G3 will
    // test the absent case. Emitting an empty attribute would make that
    // test unwritable.
    expect(renderPlaylist(scenario, ORIGIN)).not.toContain('tvg-logo');
  });

  it('appends credentials to stream URLs when the scenario declares them', () => {
    const scenario = new ScenarioRegistry().create({
      channels: 1,
      username: 'user@example.com',
      password: 'p a s s',
    });
    const playlist = renderPlaylist(scenario, ORIGIN);

    // The product sends no credentials of its own on a standard M3U fetch,
    // so anything the provider wants to validate has to be in the URL.
    expect(playlist).toContain('username=user%40example.com');
    expect(playlist).toContain('password=p%20a%20s%20s');
  });

  it('declares the content type the product will accept', () => {
    // apps/m3u/tasks.py rejects "non-text content" outright, so this
    // constant is load-bearing rather than cosmetic.
    expect(PLAYLIST_CONTENT_TYPE).toBe('application/vnd.apple.mpegurl');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd e2e-upstream && npx vitest run test/playlist.test.ts`
Expected: FAIL — `Cannot find module '../src/playlist'`

- [ ] **Step 3: Implement the playlist**

`e2e-upstream/src/playlist.ts`:

```ts
import type { Scenario } from './scenario';

/**
 * apps/m3u/tasks.py rejects a response whose content is "non-text", so this
 * is not cosmetic. text/plain would also pass.
 */
export const PLAYLIST_CONTENT_TYPE = 'application/vnd.apple.mpegurl';

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
```

- [ ] **Step 4: Run playlist tests to verify they pass**

Run: `cd e2e-upstream && npx vitest run test/playlist.test.ts`
Expected: PASS, 6 tests

- [ ] **Step 5: Write the failing XMLTV test**

`e2e-upstream/test/xmltv.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { ScenarioRegistry } from '../src/scenario';
import { renderXmltv, XMLTV_CONTENT_TYPE } from '../src/xmltv';

const NOW = new Date('2026-08-25T12:34:56Z');

describe('renderXmltv', () => {
  it('declares one <channel> per scenario channel, keyed by tvg-id', () => {
    const scenario = new ScenarioRegistry().create({ channels: 2 });
    const xml = renderXmltv(scenario, NOW);

    expect(xml).toContain('<channel id="fake-1.e2e">');
    expect(xml).toContain('<channel id="fake-2.e2e">');
  });

  it('emits programmes in XMLTV timestamp format', () => {
    const scenario = new ScenarioRegistry().create({ channels: 1 });
    // YYYYMMDDHHMMSS +0000 — anything else and the EPG parser drops the row
    // silently, which would look like "EPG import is broken".
    expect(renderXmltv(scenario, NOW)).toMatch(/start="\d{14} \+0000"/);
  });

  it('covers a window starting before now, so a programme is always in progress', () => {
    const scenario = new ScenarioRegistry().create({ channels: 1 });
    const xml = renderXmltv(scenario, NOW);
    const starts = [...xml.matchAll(/start="(\d{14}) \+0000"/g)].map((m) => m[1]);

    // A guide with nothing airing right now makes "is the channel showing
    // the right programme" untestable.
    expect(starts[0] < '20260825123456').toBe(true);
  });

  it('produces programmes that abut without gaps or overlaps', () => {
    const scenario = new ScenarioRegistry().create({ channels: 1 });
    const xml = renderXmltv(scenario, NOW);
    const stops = [...xml.matchAll(/stop="(\d{14}) \+0000"/g)].map((m) => m[1]);
    const starts = [...xml.matchAll(/start="(\d{14}) \+0000"/g)].map((m) => m[1]);

    expect(starts.slice(1)).toEqual(stops.slice(0, -1));
  });

  it('escapes XML metacharacters in channel names', () => {
    const scenario = new ScenarioRegistry().create({
      channels: [{ id: 1, name: 'Rock & Roll <live>', tvgId: 'rock.e2e', logo: null }],
    });
    const xml = renderXmltv(scenario, NOW);

    expect(xml).toContain('Rock &amp; Roll &lt;live&gt;');
    expect(xml).not.toContain('Rock & Roll <live>');
  });

  it('declares the XML content type', () => {
    expect(XMLTV_CONTENT_TYPE).toBe('application/xml');
  });
});
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd e2e-upstream && npx vitest run test/xmltv.test.ts`
Expected: FAIL — `Cannot find module '../src/xmltv'`

- [ ] **Step 7: Implement XMLTV**

`e2e-upstream/src/xmltv.ts`:

```ts
import type { Scenario } from './scenario';

export const XMLTV_CONTENT_TYPE = 'application/xml';

/** Hours of guide before and after `now`. */
const HOURS_BEFORE = 2;
const HOURS_AFTER = 24;
const SLOT_MS = 60 * 60 * 1000;

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
```

- [ ] **Step 8: Wire both routes into the server**

In `src/server.ts`, add before the 404 fallthrough:

```ts
const playlistMatch = /^\/s\/([^/]+)\/playlist\.m3u$/.exec(url.pathname);
if (playlistMatch && req.method === 'GET') {
  const scenario = registry.get(playlistMatch[1]);
  if (!scenario) {
    sendJson(res, 404, { error: `no scenario ${playlistMatch[1]}` });
    return;
  }
  const body = renderPlaylist(scenario, INTERNAL_ORIGIN);
  res.writeHead(200, {
    'Content-Type': PLAYLIST_CONTENT_TYPE,
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
  return;
}

const epgMatch = /^\/s\/([^/]+)\/epg\.xml$/.exec(url.pathname);
if (epgMatch && req.method === 'GET') {
  const scenario = registry.get(epgMatch[1]);
  if (!scenario) {
    sendJson(res, 404, { error: `no scenario ${epgMatch[1]}` });
    return;
  }
  const body = renderXmltv(scenario, new Date());
  res.writeHead(200, {
    'Content-Type': XMLTV_CONTENT_TYPE,
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
  return;
}
```

- [ ] **Step 9: Run the whole suite**

Run: `cd e2e-upstream && npx vitest run`
Expected: PASS, 20 tests

- [ ] **Step 10: Commit**

```bash
git add e2e-upstream
```

```bash
git commit -m "feat(e2e): M3U playlist and XMLTV EPG generation"
```

---

### Task 4: TS asset, and the loop-seam rewriter

The hardest task, and the one everything downstream trusts. Read the spec's "The TS asset" section before starting.

Three values must advance monotonically across the loop seam, per PID: **continuity counters**, **PCR**, and **PTS/DTS**. The third is the one that matters end-to-end, because ffmpeg's mpegts muxer regenerates CC and PCR — so through the default `-c copy` profile, PTS monotonicity read from PES headers is the only decoder-free continuity evidence a test can get.

Per D20, the tests here synthesise their own TS in-process. Do **not** shell out to ffmpeg from a test: `assets/` is gitignored and built in the Docker builder stage, the CI job for this suite has no `needs: build`, and a host ffmpeg would reintroduce the version skew the pre-baked asset exists to remove.

**Files:**
- Create: `e2e-upstream/src/ts.ts`, `e2e-upstream/src/ts-loop.ts`, `e2e-upstream/scripts/make-asset.sh`, `e2e-upstream/test/helpers/synthetic-ts.ts`
- Modify: `e2e-upstream/Dockerfile`
- Test: `e2e-upstream/test/ts.test.ts`, `e2e-upstream/test/ts-loop.test.ts`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:

```ts
// src/ts.ts — packet-level primitives
export const TS_PACKET_SIZE = 188;
export const TS_SYNC_BYTE = 0x47;
export const NULL_PID = 0x1fff;

export function pidOf(packet: Buffer): number;
export function hasPayload(packet: Buffer): boolean;
export function hasAdaptationField(packet: Buffer): boolean;
export function payloadUnitStart(packet: Buffer): boolean;
export function payloadOffset(packet: Buffer): number;   // -1 when no payload
export function readPcrBase(packet: Buffer): bigint | null;
export function writePcrBase(packet: Buffer, base: bigint): void;
export function readTimestamp(buffer: Buffer, offset: number): bigint;
export function writeTimestamp(buffer: Buffer, offset: number, value: bigint, prefix: number): void;

// src/ts-loop.ts — the seam
export class LoopRewriter {
  constructor(loopDuration90k: bigint);
  rewrite(packet: Buffer): Buffer;   // returns a copy; never mutates input
  advanceLoop(): void;
}
```

- [ ] **Step 1: Write the synthetic TS helper**

`e2e-upstream/test/helpers/synthetic-ts.ts`:

```ts
import { TS_PACKET_SIZE } from '../../src/ts';

export interface SyntheticOptions {
  packets: number;
  pid: number;
  /** 90 kHz ticks between consecutive packets. */
  step: bigint;
  /** 90 kHz value of the first packet. */
  start?: bigint;
}

function writeTs(buffer: Buffer, offset: number, value: bigint, prefix: number): void {
  const v = value & 0x1ffffffffn;
  buffer[offset] = ((prefix & 0x0f) << 4) | (Number((v >> 30n) & 0x07n) << 1) | 0x01;
  buffer[offset + 1] = Number((v >> 22n) & 0xffn);
  buffer[offset + 2] = (Number((v >> 15n) & 0x7fn) << 1) | 0x01;
  buffer[offset + 3] = Number((v >> 7n) & 0xffn);
  buffer[offset + 4] = (Number(v & 0x7fn) << 1) | 0x01;
}

/**
 * A deliberately unrealistic stream: every packet carries an adaptation field
 * with a PCR and a complete PES header with PTS and DTS. Real video looks
 * nothing like this, and that is the point — the rewriter must not care what
 * the asset contains, so the test gives it the densest possible case.
 *
 * Layout, matching the offsets LoopRewriter computes:
 *   0..3    TS header, AFC=11 (adaptation + payload), PUSI set
 *   4       adaptation_field_length = 7
 *   5       adaptation flags = 0x10 (PCR present)
 *   6..11   PCR (33-bit base at 90 kHz, 6 reserved bits, 9-bit extension)
 *   12..14  PES start code 00 00 01
 *   15      stream_id 0xE0 (video)
 *   16..17  PES_packet_length (0 = unbounded, legal for video)
 *   18      PES flags 1
 *   19      PES flags 2 = 0xC0 (PTS and DTS present)
 *   20      PES_header_data_length = 10
 *   21..25  PTS
 *   26..30  DTS
 *   31..187 0xFF padding
 */
export function makeSyntheticTs(options: SyntheticOptions): Buffer {
  const { packets, pid, step } = options;
  const start = options.start ?? 0n;
  const out = Buffer.alloc(packets * TS_PACKET_SIZE, 0xff);

  for (let index = 0; index < packets; index += 1) {
    const base = out.subarray(index * TS_PACKET_SIZE, (index + 1) * TS_PACKET_SIZE);
    const stamp = start + step * BigInt(index);

    base[0] = 0x47;
    base[1] = 0x40 | ((pid >> 8) & 0x1f);
    base[2] = pid & 0xff;
    base[3] = 0x30 | (index & 0x0f); // AFC = 11, continuity counter
    base[4] = 7;
    base[5] = 0x10;

    // PCR base is 33 bits at 90 kHz — the same clock as PTS — so the seam
    // offset added to PTS applies unchanged. The 9-bit extension is left
    // alone.
    base[6] = Number((stamp >> 25n) & 0xffn);
    base[7] = Number((stamp >> 17n) & 0xffn);
    base[8] = Number((stamp >> 9n) & 0xffn);
    base[9] = Number((stamp >> 1n) & 0xffn);
    base[10] = (Number(stamp & 0x01n) << 7) | 0x7e;
    base[11] = 0x00;

    base[12] = 0x00;
    base[13] = 0x00;
    base[14] = 0x01;
    base[15] = 0xe0;
    base[16] = 0x00;
    base[17] = 0x00;
    base[18] = 0x80;
    base[19] = 0xc0;
    base[20] = 10;
    writeTs(base, 21, stamp, 0b0011);
    writeTs(base, 26, stamp, 0b0001);
  }

  return out;
}
```

- [ ] **Step 2: Write the failing packet-primitives test**

`e2e-upstream/test/ts.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import {
  TS_PACKET_SIZE,
  pidOf,
  hasPayload,
  hasAdaptationField,
  payloadUnitStart,
  payloadOffset,
  readPcrBase,
  writePcrBase,
  readTimestamp,
  writeTimestamp,
} from '../src/ts';
import { makeSyntheticTs } from './helpers/synthetic-ts';

const PID = 0x0100;

function onePacket(): Buffer {
  return makeSyntheticTs({ packets: 1, pid: PID, step: 0n, start: 900_000n });
}

describe('TS packet primitives', () => {
  it('reads the PID out of the 13 bits spanning bytes 1 and 2', () => {
    expect(pidOf(onePacket())).toBe(PID);
  });

  it('recognises adaptation field plus payload', () => {
    const packet = onePacket();
    expect(hasAdaptationField(packet)).toBe(true);
    expect(hasPayload(packet)).toBe(true);
    expect(payloadUnitStart(packet)).toBe(true);
  });

  it('places the payload after the adaptation field', () => {
    // 4 header bytes + 1 length byte + 7 adaptation bytes
    expect(payloadOffset(onePacket())).toBe(12);
  });

  it('reports no payload offset for an adaptation-only packet', () => {
    const packet = onePacket();
    packet[3] = 0x20; // AFC = 10, adaptation only
    expect(hasPayload(packet)).toBe(false);
    expect(payloadOffset(packet)).toBe(-1);
  });

  it('round-trips a PCR base without disturbing the extension bits', () => {
    const packet = onePacket();
    const before = packet[10] & 0x7f;

    writePcrBase(packet, 1_234_567n);

    expect(readPcrBase(packet)).toBe(1_234_567n);
    expect(packet[10] & 0x7f).toBe(before);
  });

  it('round-trips a 33-bit timestamp at its maximum value', () => {
    const packet = onePacket();
    const max = 0x1ffffffffn;

    writeTimestamp(packet, 21, max, 0b0011);

    expect(readTimestamp(packet, 21)).toBe(max);
  });

  it('preserves the four-bit prefix that distinguishes PTS from DTS', () => {
    const packet = onePacket();
    writeTimestamp(packet, 26, 5_000n, 0b0001);
    expect(packet[26] >> 4).toBe(0b0001);
  });

  it('leaves marker bits set, which decoders require', () => {
    const packet = onePacket();
    writeTimestamp(packet, 21, 12_345n, 0b0011);

    expect(packet[21] & 0x01).toBe(1);
    expect(packet[23] & 0x01).toBe(1);
    expect(packet[25] & 0x01).toBe(1);
  });

  it('builds packets of exactly 188 bytes', () => {
    expect(makeSyntheticTs({ packets: 3, pid: PID, step: 3600n }).byteLength).toBe(
      3 * TS_PACKET_SIZE
    );
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd e2e-upstream && npx vitest run test/ts.test.ts`
Expected: FAIL — `Cannot find module '../src/ts'`

- [ ] **Step 4: Implement the primitives**

`e2e-upstream/src/ts.ts`:

```ts
export const TS_PACKET_SIZE = 188;
export const TS_SYNC_BYTE = 0x47;
/** Null packets carry no continuity obligation and must not be renumbered. */
export const NULL_PID = 0x1fff;

export function pidOf(packet: Buffer): number {
  return ((packet[1] & 0x1f) << 8) | packet[2];
}

function adaptationFieldControl(packet: Buffer): number {
  return (packet[3] >> 4) & 0x03;
}

export function hasPayload(packet: Buffer): boolean {
  const afc = adaptationFieldControl(packet);
  return afc === 0b01 || afc === 0b11;
}

export function hasAdaptationField(packet: Buffer): boolean {
  const afc = adaptationFieldControl(packet);
  return afc === 0b10 || afc === 0b11;
}

export function payloadUnitStart(packet: Buffer): boolean {
  return (packet[1] & 0x40) !== 0;
}

export function payloadOffset(packet: Buffer): number {
  if (!hasPayload(packet)) return -1;
  if (!hasAdaptationField(packet)) return 4;
  return 5 + packet[4];
}

/**
 * PCR base is 33 bits at 90 kHz — the same clock as PTS/DTS — spanning bytes
 * 6..10 (bit 7 of byte 10 is its least significant bit). The 9-bit 27 MHz
 * extension that follows is deliberately not touched by any of this: adding a
 * whole-loop offset at 90 kHz leaves it correct.
 */
export function readPcrBase(packet: Buffer): bigint | null {
  if (!hasAdaptationField(packet)) return null;
  if (packet[4] === 0) return null;
  if ((packet[5] & 0x10) === 0) return null;

  return (
    (BigInt(packet[6]) << 25n) |
    (BigInt(packet[7]) << 17n) |
    (BigInt(packet[8]) << 9n) |
    (BigInt(packet[9]) << 1n) |
    (BigInt(packet[10]) >> 7n)
  );
}

export function writePcrBase(packet: Buffer, base: bigint): void {
  const value = base & 0x1ffffffffn;
  packet[6] = Number((value >> 25n) & 0xffn);
  packet[7] = Number((value >> 17n) & 0xffn);
  packet[8] = Number((value >> 9n) & 0xffn);
  packet[9] = Number((value >> 1n) & 0xffn);
  // Only bit 7 belongs to the base; the rest is reserved bits and the top bit
  // of the extension, so mask them through untouched.
  packet[10] = (packet[10] & 0x7f) | (Number(value & 0x01n) << 7);
}

/**
 * A PTS or DTS: 33 bits spread across 5 bytes, interleaved with a 4-bit
 * prefix and three marker bits that must stay set.
 */
export function readTimestamp(buffer: Buffer, offset: number): bigint {
  const b0 = (BigInt(buffer[offset]) >> 1n) & 0x07n;
  const b1 = BigInt(buffer[offset + 1]);
  const b2 = (BigInt(buffer[offset + 2]) >> 1n) & 0x7fn;
  const b3 = BigInt(buffer[offset + 3]);
  const b4 = (BigInt(buffer[offset + 4]) >> 1n) & 0x7fn;

  return (b0 << 30n) | (b1 << 22n) | (b2 << 15n) | (b3 << 7n) | b4;
}

export function writeTimestamp(
  buffer: Buffer,
  offset: number,
  value: bigint,
  prefix: number
): void {
  const v = value & 0x1ffffffffn;
  buffer[offset] = ((prefix & 0x0f) << 4) | (Number((v >> 30n) & 0x07n) << 1) | 0x01;
  buffer[offset + 1] = Number((v >> 22n) & 0xffn);
  buffer[offset + 2] = (Number((v >> 15n) & 0x7fn) << 1) | 0x01;
  buffer[offset + 3] = Number((v >> 7n) & 0xffn);
  buffer[offset + 4] = (Number(v & 0x7fn) << 1) | 0x01;
}
```

- [ ] **Step 5: Run primitives tests to verify they pass**

Run: `cd e2e-upstream && npx vitest run test/ts.test.ts`
Expected: PASS, 9 tests

- [ ] **Step 6: Write the failing seam test**

`e2e-upstream/test/ts-loop.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import {
  TS_PACKET_SIZE,
  pidOf,
  hasPayload,
  payloadOffset,
  payloadUnitStart,
  readPcrBase,
  readTimestamp,
} from '../src/ts';
import { LoopRewriter } from '../src/ts-loop';
import { makeSyntheticTs } from './helpers/synthetic-ts';

const PID = 0x0100;
const PACKETS = 8;
const STEP = 3600n; // 40 ms at 90 kHz
const LOOP_DURATION = STEP * BigInt(PACKETS);

function packetsOf(buffer: Buffer): Buffer[] {
  const out: Buffer[] = [];
  for (let at = 0; at < buffer.byteLength; at += TS_PACKET_SIZE) {
    out.push(buffer.subarray(at, at + TS_PACKET_SIZE));
  }
  return out;
}

/** Two loops of the same asset, pushed through one rewriter. */
function twoLoops(): Buffer[] {
  const asset = packetsOf(makeSyntheticTs({ packets: PACKETS, pid: PID, step: STEP }));
  const rewriter = new LoopRewriter(LOOP_DURATION);
  const out: Buffer[] = [];

  for (const packet of asset) out.push(rewriter.rewrite(packet));
  rewriter.advanceLoop();
  for (const packet of asset) out.push(rewriter.rewrite(packet));

  return out;
}

describe('LoopRewriter', () => {
  it('makes PTS strictly increase across the loop seam', () => {
    // The assertion that matters end to end. ffmpeg's mpegts muxer
    // regenerates CC and PCR, so through the default -c copy profile this is
    // the only decoder-free continuity evidence a test can read.
    const stamps = twoLoops()
      .filter((p) => payloadUnitStart(p) && hasPayload(p))
      .map((p) => readTimestamp(p, payloadOffset(p) + 9));

    for (let i = 1; i < stamps.length; i += 1) {
      expect(
        stamps[i] > stamps[i - 1],
        `PTS went backwards at packet ${i}: ${stamps[i - 1]} then ${stamps[i]}`
      ).toBe(true);
    }
  });

  it('makes DTS strictly increase across the loop seam', () => {
    const stamps = twoLoops()
      .filter((p) => payloadUnitStart(p) && hasPayload(p))
      .map((p) => readTimestamp(p, payloadOffset(p) + 14));

    for (let i = 1; i < stamps.length; i += 1) {
      expect(stamps[i] > stamps[i - 1]).toBe(true);
    }
  });

  it('makes PCR strictly increase across the loop seam', () => {
    const bases = twoLoops()
      .map((p) => readPcrBase(p))
      .filter((base): base is bigint => base !== null);

    for (let i = 1; i < bases.length; i += 1) {
      expect(bases[i] > bases[i - 1]).toBe(true);
    }
  });

  it('increments continuity counters by exactly one per PID, wrapping at 16', () => {
    const counters = twoLoops()
      .filter((p) => hasPayload(p) && pidOf(p) === PID)
      .map((p) => p[3] & 0x0f);

    for (let i = 1; i < counters.length; i += 1) {
      expect(counters[i]).toBe((counters[i - 1] + 1) & 0x0f);
    }
  });

  it('does not renumber null packets', () => {
    // PID 0x1FFF carries no continuity obligation. Renumbering it produces a
    // stream that fails strict analysers for no reason.
    const nullPacket = makeSyntheticTs({ packets: 1, pid: 0x1fff, step: 0n });
    const rewriter = new LoopRewriter(LOOP_DURATION);
    const before = nullPacket[3] & 0x0f;

    expect(rewriter.rewrite(nullPacket)[3] & 0x0f).toBe(before);
  });

  it('never mutates the packet it was given', () => {
    // The asset buffer is read once and shared by every connection. A
    // rewriter that mutated in place would corrupt it for everyone, and the
    // corruption would grow with each loop.
    const asset = makeSyntheticTs({ packets: 1, pid: PID, step: STEP });
    const original = Buffer.from(asset);
    const rewriter = new LoopRewriter(LOOP_DURATION);

    rewriter.advanceLoop();
    rewriter.rewrite(asset);

    expect(asset.equals(original)).toBe(true);
  });

  it('leaves the first loop byte-identical apart from continuity counters', () => {
    const asset = packetsOf(makeSyntheticTs({ packets: PACKETS, pid: PID, step: STEP }));
    const rewriter = new LoopRewriter(LOOP_DURATION);

    for (const packet of asset) {
      const rewritten = rewriter.rewrite(packet);
      // Byte 3 holds the counter; everything else is untouched at offset 0.
      expect(rewritten.subarray(0, 3).equals(packet.subarray(0, 3))).toBe(true);
      expect(rewritten.subarray(4).equals(packet.subarray(4))).toBe(true);
    }
  });
});
```

- [ ] **Step 7: Run test to verify it fails**

Run: `cd e2e-upstream && npx vitest run test/ts-loop.test.ts`
Expected: FAIL — `Cannot find module '../src/ts-loop'`

- [ ] **Step 8: Implement the rewriter**

`e2e-upstream/src/ts-loop.ts`:

```ts
import {
  NULL_PID,
  TS_PACKET_SIZE,
  hasPayload,
  payloadOffset,
  payloadUnitStart,
  pidOf,
  readPcrBase,
  readTimestamp,
  writePcrBase,
  writeTimestamp,
} from './ts';

/** 33 bits. Everything wraps here, at ~26.5 hours for a 90 kHz clock. */
const TIMESTAMP_MASK = 0x1ffffffffn;

/**
 * Serves one asset repeatedly as a single continuous stream.
 *
 * On each wrap, PTS, DTS and PCR are shifted forward by a whole loop duration
 * so they keep advancing, and continuity counters are renumbered from the
 * rewriter's own per-PID state rather than the asset's. Counters are rewritten
 * on every packet, not only at the seam: the source is already correct within
 * a loop, so this is a no-op there, and it means continuity has exactly one
 * owner instead of two that must agree.
 *
 * The 2^33 / 90 kHz wrap (~26.5 h) is left to happen. No E2E run is remotely
 * that long, and "fixing" it would mean tracking a discontinuity the product
 * has to handle anyway.
 */
export class LoopRewriter {
  private ccByPid = new Map<number, number>();
  private offset90k = 0n;
  private loopIndex = 0;

  constructor(private readonly loopDuration90k: bigint) {}

  advanceLoop(): void {
    this.loopIndex += 1;
    this.offset90k = (this.loopDuration90k * BigInt(this.loopIndex)) & TIMESTAMP_MASK;
  }

  rewrite(packet: Buffer): Buffer {
    // A copy, always: the asset buffer is read once and shared by every
    // connection, so mutating in place would corrupt it for everyone.
    const out = Buffer.from(packet);

    this.rewriteContinuity(out);
    this.rewritePcr(out);
    this.rewriteTimestamps(out);

    return out;
  }

  private rewriteContinuity(out: Buffer): void {
    const pid = pidOf(out);
    if (pid === NULL_PID) return;
    if (!hasPayload(out)) return;

    const next = ((this.ccByPid.get(pid) ?? 15) + 1) & 0x0f;
    this.ccByPid.set(pid, next);
    out[3] = (out[3] & 0xf0) | next;
  }

  private rewritePcr(out: Buffer): void {
    const base = readPcrBase(out);
    if (base === null) return;
    writePcrBase(out, (base + this.offset90k) & TIMESTAMP_MASK);
  }

  private rewriteTimestamps(out: Buffer): void {
    if (!payloadUnitStart(out)) return;

    const start = payloadOffset(out);
    if (start < 0) return;

    // A PES packet, not a PSI section: 00 00 01 start code.
    if (start + 9 > TS_PACKET_SIZE) return;
    if (out[start] !== 0x00 || out[start + 1] !== 0x00 || out[start + 2] !== 0x01) return;

    const flags = (out[start + 7] >> 6) & 0x03;
    if (flags === 0) return;

    const ptsAt = start + 9;
    if (ptsAt + 5 > TS_PACKET_SIZE) return;
    writeTimestamp(
      out,
      ptsAt,
      (readTimestamp(out, ptsAt) + this.offset90k) & TIMESTAMP_MASK,
      out[ptsAt] >> 4
    );

    // flags === 0b11 means PTS and DTS; 0b10 means PTS alone.
    if (flags !== 0b11) return;

    const dtsAt = start + 14;
    if (dtsAt + 5 > TS_PACKET_SIZE) return;
    writeTimestamp(
      out,
      dtsAt,
      (readTimestamp(out, dtsAt) + this.offset90k) & TIMESTAMP_MASK,
      out[dtsAt] >> 4
    );
  }
}
```

- [ ] **Step 9: Run the whole suite**

Run: `cd e2e-upstream && npx vitest run`
Expected: PASS, 27 tests

- [ ] **Step 10: Write the asset build script**

`e2e-upstream/scripts/make-asset.sh`:

```bash
#!/usr/bin/env bash
# Generate the looping MPEG-TS asset. Build-time only: ffmpeg is confined to
# the Docker builder stage so the runtime image, and this repo, carry neither
# ffmpeg nor a version of it that could drift from CI's.
set -euo pipefail

OUT="${1:?usage: make-asset.sh <output.ts>}"
DURATION="${ASSET_DURATION_SECONDS:-60}"
FPS="${ASSET_FPS:-25}"
BITRATE="${ASSET_BITRATE:-2000k}"

# The burned-in frame counter is a human debugging aid only — for eyeballing a
# captured TS in VLC after a failure. Nothing in the test runner decodes video,
# so no test asserts on it.
ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "testsrc=size=640x360:rate=${FPS}:duration=${DURATION}" \
  -f lavfi -i "sine=frequency=440:duration=${DURATION}" \
  -vf "drawtext=text='%{frame_num}':x=10:y=10:fontsize=48:fontcolor=white:box=1:boxcolor=black" \
  -c:v libx264 -preset ultrafast -b:v "${BITRATE}" -pix_fmt yuv420p \
  -c:a aac -b:a 128k \
  -mpegts_start_pid 0x100 -streamid 0:256 -streamid 1:257 \
  -f mpegts "${OUT}"

echo "Wrote ${OUT} ($(stat -c%s "${OUT}" 2>/dev/null || stat -f%z "${OUT}") bytes)"
```

Make it executable: `chmod +x e2e-upstream/scripts/make-asset.sh`

- [ ] **Step 11: Add the ffmpeg builder stage to the Dockerfile**

Resolve the builder digest first:

```bash
docker buildx imagetools inspect debian:bookworm-slim --format '{{.Manifest.Digest}}'
```

Prepend to `e2e-upstream/Dockerfile`, keeping the existing runtime stage below it:

```dockerfile
FROM debian:bookworm-slim@sha256:PUT_THE_RESOLVED_DIGEST_HERE AS asset
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY scripts/make-asset.sh ./
RUN chmod +x make-asset.sh && ./make-asset.sh /build/loop.ts
```

And in the runtime stage, before `CMD`:

```dockerfile
COPY --from=asset /build/loop.ts /app/assets/loop.ts
ENV UPSTREAM_ASSET=/app/assets/loop.ts
```

- [ ] **Step 12: Verify the asset builds and is well-formed**

```bash
docker build -f e2e-upstream/Dockerfile -t dispatcharr-e2e-upstream:local e2e-upstream
docker run --rm --entrypoint sh dispatcharr-e2e-upstream:local -c \
  'ls -l /app/assets/loop.ts && head -c 1 /app/assets/loop.ts | od -An -tx1'
```

Expected: a file of a few MB, first byte `47`. If the first byte is not `47`, the asset is not TS and every downstream assertion is meaningless — stop and report.

- [ ] **Step 13: Commit**

```bash
git add e2e-upstream
```

```bash
git commit -m "feat(e2e): TS packet primitives and the loop-seam rewriter

PTS, DTS and PCR are shifted by a whole loop duration on each wrap, and
continuity counters are renumbered from the rewriter's own per-PID state.
PTS monotonicity is the assertion that matters: ffmpeg's mpegts muxer
regenerates CC and PCR, so through the default -c copy profile it is the only
decoder-free continuity evidence available."
```

---
### Task 5: Paced streaming, connection accounting, and HEAD

Nothing in the product paces the read — the default ffmpeg profile has no `-re` and the Proxy profile is a bare `iter_content` loop — so the provider must pace, or a 15 MB asset floods the Redis ring buffer at hundreds of Mbit on DB 0, which it shares with the Celery broker and the cache.

**Files:**
- Create: `e2e-upstream/src/asset.ts`, `e2e-upstream/src/connections.ts`, `e2e-upstream/src/stream.ts`
- Modify: `e2e-upstream/src/server.ts`
- Test: `e2e-upstream/test/asset.test.ts`, `e2e-upstream/test/stream.test.ts`

**Interfaces:**
- Consumes: `LoopRewriter` (Task 4), `TS_PACKET_SIZE`, `readTimestamp`, `readPcrBase`, `payloadOffset`, `payloadUnitStart`, `hasPayload` (Task 4); `Scenario`, `registry` (Task 2).
- Produces:

```ts
// src/asset.ts
export interface LoadedAsset {
  bytes: Buffer;
  loopDuration90k: bigint;
  durationSeconds: number;
  byteRate: number;          // bytes per second at rate 1
}
export function measureLoop(bytes: Buffer): { loopDuration90k: bigint; durationSeconds: number };
export function loadAsset(path: string): LoadedAsset;

// src/connections.ts
export interface LiveConnection {
  readonly scenarioId: string;
  readonly channelId: number;
  setDeadAir(active: boolean): void;
  setRate(rate: number | null): void;   // null = follow the scenario rate
  disconnect(options: { clean: boolean; afterBytes?: number }): void;
}
export class ConnectionRegistry {
  tryAcquire(scenario: Scenario, connection: LiveConnection): boolean;
  release(connection: LiveConnection): void;
  count(scenarioId: string): number;
  matching(scenarioId: string, channelId?: number): LiveConnection[];
}

// src/stream.ts
export const STREAM_CONTENT_TYPE = 'video/mp2t';
export const PACKETS_PER_CHUNK = 40;
export function streamLoop(
  res: ServerResponse,
  asset: LoadedAsset,
  control: StreamControl
): Promise<void>;
export interface StreamControl {
  scenarioRate(): number;
  onConnection(connection: LiveConnection): void;
  onClosed(): void;
}
```

- [ ] **Step 1: Write the failing asset test**

`e2e-upstream/test/asset.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { measureLoop } from '../src/asset';
import { makeSyntheticTs } from './helpers/synthetic-ts';

const STEP = 3600n;      // 40 ms at 90 kHz
const PACKETS = 10;

describe('measureLoop', () => {
  it('reports a duration one step longer than the span between first and last timestamp', () => {
    // Strictly longer than the span, or the next loop's first timestamp
    // equals this loop's last and PTS stops strictly increasing — which is
    // exactly the discontinuity the seam rewriter exists to prevent.
    const bytes = makeSyntheticTs({ packets: PACKETS, pid: 0x0100, step: STEP });
    const { loopDuration90k } = measureLoop(bytes);

    expect(loopDuration90k).toBe(STEP * BigInt(PACKETS));
  });

  it('converts the duration to seconds against the 90 kHz clock', () => {
    const bytes = makeSyntheticTs({ packets: PACKETS, pid: 0x0100, step: STEP });
    expect(measureLoop(bytes).durationSeconds).toBeCloseTo(0.4, 5);
  });

  it('throws by name on a buffer that is not a whole number of packets', () => {
    const bytes = makeSyntheticTs({ packets: 2, pid: 0x0100, step: STEP }).subarray(0, 300);
    expect(() => measureLoop(bytes)).toThrow(/188/);
  });

  it('throws by name when no timestamps are present at all', () => {
    // An asset with no PTS and no PCR cannot be looped continuously, and
    // failing at load is far better than emitting a stream whose seam
    // silently jumps backwards.
    const bytes = Buffer.alloc(188 * 4, 0xff);
    for (let at = 0; at < bytes.byteLength; at += 188) {
      bytes[at] = 0x47;
      bytes[at + 3] = 0x10; // payload only, no adaptation field, no PES
    }
    expect(() => measureLoop(bytes)).toThrow(/no timestamps/i);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd e2e-upstream && npx vitest run test/asset.test.ts`
Expected: FAIL — `Cannot find module '../src/asset'`

- [ ] **Step 3: Implement asset loading and measurement**

`e2e-upstream/src/asset.ts`:

```ts
import { readFileSync } from 'node:fs';
import {
  TS_PACKET_SIZE,
  hasPayload,
  payloadOffset,
  payloadUnitStart,
  readPcrBase,
  readTimestamp,
} from './ts';

export interface LoadedAsset {
  bytes: Buffer;
  loopDuration90k: bigint;
  durationSeconds: number;
  /** Bytes per second at rate 1 — what pacing multiplies. */
  byteRate: number;
}

/**
 * Derives the loop duration from the asset itself rather than trusting a
 * configured value. A duration that is too short makes the seam jump
 * backwards, which breaks the one property every streaming test depends on;
 * measuring removes the chance of the build script and the server disagreeing.
 *
 * The result is the observed span plus one average sample interval, so the
 * next loop's first timestamp lands strictly after this loop's last.
 */
export function measureLoop(bytes: Buffer): {
  loopDuration90k: bigint;
  durationSeconds: number;
} {
  if (bytes.byteLength % TS_PACKET_SIZE !== 0) {
    throw new Error(
      `asset is ${bytes.byteLength} bytes, not a whole number of 188-byte TS packets`
    );
  }

  const stamps: bigint[] = [];

  for (let at = 0; at < bytes.byteLength; at += TS_PACKET_SIZE) {
    const packet = bytes.subarray(at, at + TS_PACKET_SIZE);

    const pcr = readPcrBase(packet);
    if (pcr !== null) stamps.push(pcr);

    if (!payloadUnitStart(packet) || !hasPayload(packet)) continue;
    const start = payloadOffset(packet);
    if (start < 0 || start + 14 > TS_PACKET_SIZE) continue;
    if (packet[start] !== 0x00 || packet[start + 1] !== 0x00 || packet[start + 2] !== 0x01) {
      continue;
    }
    if (((packet[start + 7] >> 6) & 0x03) === 0) continue;
    stamps.push(readTimestamp(packet, start + 9));
  }

  if (stamps.length < 2) {
    throw new Error('asset carries no timestamps; it cannot be looped continuously');
  }

  let min = stamps[0];
  let max = stamps[0];
  for (const stamp of stamps) {
    if (stamp < min) min = stamp;
    if (stamp > max) max = stamp;
  }

  const span = max - min;
  const step = span / BigInt(stamps.length - 1);
  const loopDuration90k = span + step;

  return {
    loopDuration90k,
    durationSeconds: Number(loopDuration90k) / 90_000,
  };
}

export function loadAsset(path: string): LoadedAsset {
  const bytes = readFileSync(path);
  const { loopDuration90k, durationSeconds } = measureLoop(bytes);

  return {
    bytes,
    loopDuration90k,
    durationSeconds,
    byteRate: bytes.byteLength / durationSeconds,
  };
}
```

Note on `measureLoop`'s expected value in the test: the synthetic helper emits both a PCR and a PTS at the same value for each packet, so `stamps.length` is `2 * PACKETS`, `span` is `STEP * (PACKETS - 1)`, and `step` is `span / (2 * PACKETS - 1)`. That does **not** equal `STEP * PACKETS`. Fix the first test's expectation to compute the same arithmetic, or — better — have the helper emit PCR only on the first packet of each group so the sample set is unambiguous. **Take the second option**: change `makeSyntheticTs` to set the PCR flag only when `index % 4 === 0`, and update `test/ts.test.ts`'s `onePacket()` (index 0, so it still has a PCR). Then re-derive the expectation and pin it explicitly rather than asserting a round number.

- [ ] **Step 4: Run asset tests to verify they pass**

Run: `cd e2e-upstream && npx vitest run test/asset.test.ts`
Expected: PASS, 4 tests

- [ ] **Step 5: Implement connection accounting**

`e2e-upstream/src/connections.ts`:

```ts
import type { Scenario } from './scenario';

export interface LiveConnection {
  readonly scenarioId: string;
  readonly channelId: number;
  setDeadAir(active: boolean): void;
  /** null = follow the scenario's own rate. */
  setRate(rate: number | null): void;
  disconnect(options: { clean: boolean; afterBytes?: number }): void;
}

export class ConnectionRegistry {
  private live = new Map<string, Set<LiveConnection>>();

  /**
   * Admits the connection unless the scenario's limit is already reached.
   * `maxConnections` null means unlimited; 0 means reject everything.
   */
  tryAcquire(scenario: Scenario, connection: LiveConnection): boolean {
    const set = this.live.get(scenario.id) ?? new Set<LiveConnection>();

    if (scenario.maxConnections !== null && set.size >= scenario.maxConnections) {
      return false;
    }

    set.add(connection);
    this.live.set(scenario.id, set);
    return true;
  }

  release(connection: LiveConnection): void {
    this.live.get(connection.scenarioId)?.delete(connection);
  }

  count(scenarioId: string): number {
    return this.live.get(scenarioId)?.size ?? 0;
  }

  /** Live connections for a scenario, optionally narrowed to one channel. */
  matching(scenarioId: string, channelId?: number): LiveConnection[] {
    const all = [...(this.live.get(scenarioId) ?? [])];
    return channelId === undefined ? all : all.filter((c) => c.channelId === channelId);
  }
}
```

- [ ] **Step 6: Write the failing stream test**

`e2e-upstream/test/stream.test.ts`:

```ts
import { describe, it, expect, afterEach } from 'vitest';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import { TS_PACKET_SIZE } from '../src/ts';
import { measureLoop } from '../src/asset';
import { streamLoop, STREAM_CONTENT_TYPE } from '../src/stream';
import type { LiveConnection } from '../src/connections';
import { makeSyntheticTs } from './helpers/synthetic-ts';

const STEP = 3600n;
const PACKETS = 200;

function fakeAsset() {
  const bytes = makeSyntheticTs({ packets: PACKETS, pid: 0x0100, step: STEP });
  const { loopDuration90k, durationSeconds } = measureLoop(bytes);
  return { bytes, loopDuration90k, durationSeconds, byteRate: bytes.byteLength / durationSeconds };
}

let server: http.Server | undefined;

afterEach(() => {
  server?.close();
  server = undefined;
});

async function serve(rate: number): Promise<string> {
  const asset = fakeAsset();
  server = http.createServer((_req, res) => {
    let connection: LiveConnection | undefined;
    void streamLoop(res, asset, {
      scenarioRate: () => rate,
      onConnection: (c) => {
        connection = c;
      },
      onClosed: () => {
        connection = undefined;
      },
    });
  });
  await new Promise<void>((resolve) => server!.listen(0, '127.0.0.1', resolve));
  return `http://127.0.0.1:${(server!.address() as AddressInfo).port}/`;
}

describe('streamLoop', () => {
  it('serves 188-aligned TS with the content type the product expects', async () => {
    const url = await serve(50);
    const res = await fetch(url);

    expect(res.headers.get('content-type')).toBe(STREAM_CONTENT_TYPE);

    const reader = res.body!.getReader();
    const first = await reader.read();
    await reader.cancel();

    expect(first.value![0]).toBe(0x47);
    expect(first.value!.byteLength % TS_PACKET_SIZE).toBe(0);
  });

  it('paces roughly to the asset bitrate times the rate', async () => {
    // The property that matters: an unpaced provider is read at wire speed
    // and floods Dispatcharr's Redis ring buffer. Tolerance is wide because
    // this measures real time on a shared runner; it is checking an order of
    // magnitude, not a stopwatch.
    const asset = fakeAsset();
    const url = await serve(10);
    const started = Date.now();

    const res = await fetch(url);
    const reader = res.body!.getReader();
    let read = 0;
    const want = Math.floor(asset.byteRate * 10 * 0.5); // ~0.5s of output
    while (read < want) {
      const { value, done } = await reader.read();
      if (done) break;
      read += value!.byteLength;
    }
    await reader.cancel();

    const elapsed = Date.now() - started;
    expect(elapsed).toBeGreaterThan(150);
    expect(elapsed).toBeLessThan(4000);
  });

  it('stops writing when dead air is set, without closing the connection', async () => {
    const url = await serve(50);
    const res = await fetch(url);
    const reader = res.body!.getReader();

    await reader.read();               // prove it is flowing
    connectionUnderTest!.setDeadAir(true);

    const stalled = await Promise.race([
      reader.read().then(() => 'read' as const),
      new Promise<'silent'>((resolve) => setTimeout(() => resolve('silent'), 1000)),
    ]);
    await reader.cancel();

    expect(stalled).toBe('silent');
  });
});
```

The third test needs a handle on the `LiveConnection` the server created. Replace the local `connection` variable in `serve()` with a module-level `let connectionUnderTest: LiveConnection | undefined;` assigned in `onConnection` and cleared in `onClosed`, and reference it as above. Declare it above `serve()`.

- [ ] **Step 7: Run test to verify it fails**

Run: `cd e2e-upstream && npx vitest run test/stream.test.ts`
Expected: FAIL — `Cannot find module '../src/stream'`

- [ ] **Step 8: Implement the paced stream**

`e2e-upstream/src/stream.ts`:

```ts
import type { ServerResponse } from 'node:http';
import { TS_PACKET_SIZE } from './ts';
import { LoopRewriter } from './ts-loop';
import type { LoadedAsset } from './asset';
import type { LiveConnection } from './connections';

export const STREAM_CONTENT_TYPE = 'video/mp2t';
/** ~7.5 KB, which at 2 Mbit is a wakeup every ~30 ms. */
export const PACKETS_PER_CHUNK = 40;

export interface StreamControl {
  scenarioRate(): number;
  onConnection(connection: LiveConnection): void;
  onClosed(): void;
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export function streamLoop(
  res: ServerResponse,
  asset: LoadedAsset,
  control: StreamControl,
  identity: { scenarioId: string; channelId: number }
): Promise<void> {
  let deadAir = false;
  let rateOverride: number | null = null;
  let closing: { clean: boolean; afterBytes?: number } | undefined;
  let written = 0;
  let open = true;

  const connection: LiveConnection = {
    scenarioId: identity.scenarioId,
    channelId: identity.channelId,
    setDeadAir: (active) => {
      deadAir = active;
    },
    setRate: (rate) => {
      rateOverride = rate;
    },
    disconnect: (options) => {
      closing = options;
    },
  };

  res.writeHead(200, {
    'Content-Type': STREAM_CONTENT_TYPE,
    // No Content-Length: this stream has no end, and declaring one makes
    // requests wait for bytes that never come.
    'Cache-Control': 'no-store',
  });

  control.onConnection(connection);
  res.on('close', () => {
    open = false;
    control.onClosed();
  });

  const rewriter = new LoopRewriter(asset.loopDuration90k);
  const totalPackets = asset.bytes.byteLength / TS_PACKET_SIZE;

  return (async () => {
    let index = 0;

    while (open) {
      if (closing) {
        // A clean end() is an EOF the product logs as "HTTP stream ended";
        // destroy() is an I/O error on a different reconnect branch. Real
        // providers do both, so tests choose.
        if (closing.clean) res.end();
        else res.destroy();
        return;
      }

      if (deadAir) {
        // Open socket, no bytes. Poll rather than await a signal so a fault
        // cleared mid-stall resumes without reconnecting.
        await sleep(100);
        continue;
      }

      const chunkPackets: Buffer[] = [];
      for (let n = 0; n < PACKETS_PER_CHUNK; n += 1) {
        const at = index * TS_PACKET_SIZE;
        chunkPackets.push(rewriter.rewrite(asset.bytes.subarray(at, at + TS_PACKET_SIZE)));

        index += 1;
        if (index >= totalPackets) {
          index = 0;
          rewriter.advanceLoop();
        }
      }

      const chunk = Buffer.concat(chunkPackets);

      if (closing?.afterBytes !== undefined && written + chunk.byteLength >= closing.afterBytes) {
        const remaining = Math.max(0, closing.afterBytes - written);
        res.write(chunk.subarray(0, remaining));
        if (closing.clean) res.end();
        else res.destroy();
        return;
      }

      if (!res.write(chunk)) {
        // Respect backpressure, or a slow client turns into unbounded memory
        // in this process rather than a slow stream.
        await new Promise<void>((resolve) => res.once('drain', resolve));
      }
      written += chunk.byteLength;

      // Sleep per chunk rather than against a cumulative target, so a rate
      // changed mid-stream takes effect on the very next chunk instead of
      // being averaged away by everything already sent.
      const rate = rateOverride ?? control.scenarioRate();
      await sleep((chunk.byteLength / (asset.byteRate * rate)) * 1000);
    }
  })();
}
```

- [ ] **Step 9: Wire the stream route and HEAD into the server**

In `src/server.ts`:

```ts
import { loadAsset } from './asset';
import { ConnectionRegistry } from './connections';
import { streamLoop, STREAM_CONTENT_TYPE } from './stream';

export const connections = new ConnectionRegistry();
const asset = loadAsset(process.env.UPSTREAM_ASSET ?? '/app/assets/loop.ts');
```

Route, before the 404 fallthrough:

```ts
const streamMatch = /^\/s\/([^/]+)\/stream\/(\d+)\.ts$/.exec(url.pathname);
if (streamMatch) {
  const scenario = registry.get(streamMatch[1]);
  if (!scenario) {
    sendJson(res, 404, { error: `no scenario ${streamMatch[1]}` });
    return;
  }
  const channelId = Number(streamMatch[2]);

  // validate_stream_url() probes with HEAD before streaming. It must succeed,
  // and it must not consume a connection slot — a maxConnections:1 scenario
  // would otherwise reject the real client that follows.
  if (req.method === 'HEAD') {
    res.writeHead(200, { 'Content-Type': STREAM_CONTENT_TYPE });
    res.end();
    return;
  }

  if (req.method !== 'GET') {
    sendJson(res, 405, { error: `${req.method} not allowed on a stream` });
    return;
  }

  let admitted: LiveConnection | undefined;
  await streamLoop(
    res,
    asset,
    {
      scenarioRate: () => scenario.rate,
      onConnection: (connection) => {
        if (!connections.tryAcquire(scenario, connection)) return;
        admitted = connection;
      },
      onClosed: () => {
        if (admitted) connections.release(admitted);
      },
    },
    { scenarioId: scenario.id, channelId }
  );
  return;
}
```

`tryAcquire` returning false must reject the request rather than stream it. Restructure so the acquire happens **before** `streamLoop` writes headers: construct the `LiveConnection` in the route, call `connections.tryAcquire(scenario, connection)`, and on false respond `sendJson(res, 429, { error: 'connection limit reached' })` and return. Pass the already-constructed connection into `streamLoop` instead of having it build one. Adjust `streamLoop`'s signature to take the connection rather than `identity`, and have it attach the control methods to it.

- [ ] **Step 10: Run the whole suite**

Run: `cd e2e-upstream && npx vitest run`
Expected: PASS, 34 tests

- [ ] **Step 11: Commit**

```bash
git add e2e-upstream
```

```bash
git commit -m "feat(e2e): paced TS streaming, connection accounting, HEAD probes

Paced at the asset's measured bitrate: nothing in the product throttles the
read, so an unpaced provider floods the Redis ring buffer and makes speed=
read ~50x, which stops the buffering detector ever arming.

HEAD answers 200 and does not consume a slot, because validate_stream_url
probes before every redirect-profile stream."
```

---

### Task 6: The eight faults and the control API

**Files:**
- Create: `e2e-upstream/src/faults.ts`
- Modify: `e2e-upstream/src/server.ts`, `e2e-upstream/src/stream.ts`
- Test: `e2e-upstream/test/faults.test.ts`

**Interfaces:**
- Consumes: `ConnectionRegistry`, `LiveConnection` (Task 5); `registry`, `readJsonBody`, `sendJson` (Tasks 1–2).
- Produces:

```ts
export type FaultName =
  | 'dead-air' | 'slow-trickle' | 'disconnect' | 'not-found'
  | 'auth-failure' | 'connection-limit' | 'redirect-chain' | 'non-ts-bytes';

export interface FaultRequest {
  fault: FaultName;
  active: boolean;
  channel?: number;
  rate?: number;        // slow-trickle, default 0.1
  clean?: boolean;      // disconnect, default false (abrupt)
  afterBytes?: number;  // disconnect
  depth?: number;       // redirect-chain, default 2
}

export interface FaultResult {
  fault: FaultName;
  active: boolean;
  appliedTo: number;
}

export class FaultStore {
  apply(scenarioId: string, request: FaultRequest, connections: ConnectionRegistry): FaultResult;
  isActive(scenarioId: string, fault: FaultName, channelId?: number): boolean;
  configOf(scenarioId: string, fault: FaultName): FaultRequest | undefined;
  clearAll(scenarioId: string): void;
}
```

**Which faults reach live connections.** This distinction is the whole point of `appliedTo`, and getting it wrong makes legitimate tests unwritable:

| Fault | Live | New | Why |
|---|---|---|---|
| `dead-air` | yes | yes | Stops writes on an open socket |
| `slow-trickle` | yes | yes | Changes the pacing of an open socket |
| `disconnect` | yes | no | Closes an open socket; meaningless for a request not yet made |
| `not-found` | no | yes | Headers are already sent on a live response |
| `auth-failure` | no | yes | Same |
| `connection-limit` | no | yes | Admission control happens before headers |
| `redirect-chain` | no | yes | Same |
| `non-ts-bytes` | no | yes | Same |

`appliedTo: 0` is therefore **correct and expected** for the new-only faults. Arming `not-found` for the next reconnect is a normal test. Do not assert `appliedTo > 0` inside the fixture — return it and let the test decide.

- [ ] **Step 1: Write the failing test**

`e2e-upstream/test/faults.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { FaultStore } from '../src/faults';
import { ConnectionRegistry } from '../src/connections';
import type { LiveConnection } from '../src/connections';
import { ScenarioRegistry } from '../src/scenario';

function fakeConnection(scenarioId: string, channelId: number) {
  const calls: string[] = [];
  const connection: LiveConnection = {
    scenarioId,
    channelId,
    setDeadAir: (active) => calls.push(`deadAir:${active}`),
    setRate: (rate) => calls.push(`rate:${rate}`),
    disconnect: (options) => calls.push(`disconnect:${options.clean}`),
  };
  return { connection, calls };
}

describe('FaultStore', () => {
  it('reports appliedTo 0 for a fault that can only affect the next request', () => {
    // Arming not-found for a reconnect that has not happened yet is a normal
    // test. If this were an error, that test could not be written.
    const scenario = new ScenarioRegistry().create({});
    const result = new FaultStore().apply(
      scenario.id,
      { fault: 'not-found', active: true },
      new ConnectionRegistry()
    );

    expect(result).toEqual({ fault: 'not-found', active: true, appliedTo: 0 });
  });

  it('applies dead air to every live connection and counts them', () => {
    const scenario = new ScenarioRegistry().create({ channels: 2 });
    const connections = new ConnectionRegistry();
    const a = fakeConnection(scenario.id, 1);
    const b = fakeConnection(scenario.id, 2);
    connections.tryAcquire(scenario, a.connection);
    connections.tryAcquire(scenario, b.connection);

    const result = new FaultStore().apply(
      scenario.id,
      { fault: 'dead-air', active: true },
      connections
    );

    expect(result.appliedTo).toBe(2);
    expect(a.calls).toContain('deadAir:true');
    expect(b.calls).toContain('deadAir:true');
  });

  it('narrows to one channel when the request names one', () => {
    // Every failover trigger switches to the channel's *next* Stream row. A
    // scenario-wide fault takes both down, and the test cannot then tell
    // "switched" from "didn't".
    const scenario = new ScenarioRegistry().create({ channels: 2 });
    const connections = new ConnectionRegistry();
    const a = fakeConnection(scenario.id, 1);
    const b = fakeConnection(scenario.id, 2);
    connections.tryAcquire(scenario, a.connection);
    connections.tryAcquire(scenario, b.connection);

    const result = new FaultStore().apply(
      scenario.id,
      { fault: 'dead-air', active: true, channel: 1 },
      connections
    );

    expect(result.appliedTo).toBe(1);
    expect(a.calls).toContain('deadAir:true');
    expect(b.calls).toHaveLength(0);
  });

  it('defaults disconnect to abrupt', () => {
    const scenario = new ScenarioRegistry().create({});
    const connections = new ConnectionRegistry();
    const a = fakeConnection(scenario.id, 1);
    connections.tryAcquire(scenario, a.connection);

    new FaultStore().apply(scenario.id, { fault: 'disconnect', active: true }, connections);

    expect(a.calls).toContain('disconnect:false');
  });

  it('reports a fault as active only for the channel it was scoped to', () => {
    const store = new FaultStore();
    const scenario = new ScenarioRegistry().create({ channels: 2 });

    store.apply(scenario.id, { fault: 'not-found', active: true, channel: 1 }, new ConnectionRegistry());

    expect(store.isActive(scenario.id, 'not-found', 1)).toBe(true);
    expect(store.isActive(scenario.id, 'not-found', 2)).toBe(false);
  });

  it('clears a fault when active is false', () => {
    const store = new FaultStore();
    const scenario = new ScenarioRegistry().create({});
    const connections = new ConnectionRegistry();

    store.apply(scenario.id, { fault: 'not-found', active: true }, connections);
    const cleared = store.apply(scenario.id, { fault: 'not-found', active: false }, connections);

    expect(cleared.active).toBe(false);
    expect(store.isActive(scenario.id, 'not-found')).toBe(false);
  });

  it('restores the scenario rate when slow-trickle is cleared', () => {
    const scenario = new ScenarioRegistry().create({});
    const connections = new ConnectionRegistry();
    const a = fakeConnection(scenario.id, 1);
    connections.tryAcquire(scenario, a.connection);
    const store = new FaultStore();

    store.apply(scenario.id, { fault: 'slow-trickle', active: true, rate: 0.05 }, connections);
    store.apply(scenario.id, { fault: 'slow-trickle', active: false }, connections);

    // null, not 1: the connection must go back to following the scenario's
    // own rate, which a test may have set to something other than 1.
    expect(a.calls).toEqual(['rate:0.05', 'rate:null']);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd e2e-upstream && npx vitest run test/faults.test.ts`
Expected: FAIL — `Cannot find module '../src/faults'`

- [ ] **Step 3: Implement the fault store**

`e2e-upstream/src/faults.ts` — the store keeps, per scenario, a map of fault name to its request; `isActive` matches when the stored request has no channel or its channel equals the one asked about:

```ts
import type { ConnectionRegistry } from './connections';

export type FaultName =
  | 'dead-air'
  | 'slow-trickle'
  | 'disconnect'
  | 'not-found'
  | 'auth-failure'
  | 'connection-limit'
  | 'redirect-chain'
  | 'non-ts-bytes';

export const FAULT_NAMES: readonly FaultName[] = [
  'dead-air',
  'slow-trickle',
  'disconnect',
  'not-found',
  'auth-failure',
  'connection-limit',
  'redirect-chain',
  'non-ts-bytes',
];

export interface FaultRequest {
  fault: FaultName;
  active: boolean;
  channel?: number;
  rate?: number;
  clean?: boolean;
  afterBytes?: number;
  depth?: number;
}

export interface FaultResult {
  fault: FaultName;
  active: boolean;
  appliedTo: number;
}

const DEFAULT_TRICKLE_RATE = 0.1;
const DEFAULT_REDIRECT_DEPTH = 2;

export class FaultStore {
  private byScenario = new Map<string, Map<FaultName, FaultRequest>>();

  apply(
    scenarioId: string,
    request: FaultRequest,
    connections: ConnectionRegistry
  ): FaultResult {
    const faults = this.byScenario.get(scenarioId) ?? new Map<FaultName, FaultRequest>();
    this.byScenario.set(scenarioId, faults);

    if (request.active) faults.set(request.fault, request);
    else faults.delete(request.fault);

    const targets = connections.matching(scenarioId, request.channel);
    let appliedTo = 0;

    for (const connection of targets) {
      switch (request.fault) {
        case 'dead-air':
          connection.setDeadAir(request.active);
          appliedTo += 1;
          break;
        case 'slow-trickle':
          // null on clear, so the connection returns to the scenario's own
          // rate rather than being pinned to 1.
          connection.setRate(request.active ? (request.rate ?? DEFAULT_TRICKLE_RATE) : null);
          appliedTo += 1;
          break;
        case 'disconnect':
          if (request.active) {
            connection.disconnect({
              clean: request.clean ?? false,
              afterBytes: request.afterBytes,
            });
            appliedTo += 1;
          }
          break;
        default:
          // Headers are already sent on a live response, so these faults can
          // only affect the next request. appliedTo stays 0 and that is
          // correct — see the table in the plan.
          break;
      }
    }

    return { fault: request.fault, active: request.active, appliedTo };
  }

  isActive(scenarioId: string, fault: FaultName, channelId?: number): boolean {
    const stored = this.byScenario.get(scenarioId)?.get(fault);
    if (stored === undefined) return false;
    if (stored.channel === undefined) return true;
    return stored.channel === channelId;
  }

  configOf(scenarioId: string, fault: FaultName): FaultRequest | undefined {
    return this.byScenario.get(scenarioId)?.get(fault);
  }

  clearAll(scenarioId: string): void {
    this.byScenario.delete(scenarioId);
  }
}

export { DEFAULT_REDIRECT_DEPTH };
```

- [ ] **Step 4: Run fault tests to verify they pass**

Run: `cd e2e-upstream && npx vitest run test/faults.test.ts`
Expected: PASS, 7 tests

- [ ] **Step 5: Enforce the new-request faults in the routes**

In `src/server.ts`, add a `const faults = new FaultStore();` (exported, so Task 7 can log applications) and check them at the top of the stream route, **in this order** — the order is the realistic one and it matters, because a test arming two faults expects the earlier one to win:

```ts
// 1. not-found: nothing else can happen if the URL 404s.
if (faults.isActive(scenario.id, 'not-found', channelId)) {
  sendJson(res, 404, { error: 'fault: not-found' });
  return;
}

// 2. auth-failure: credentials that were valid stop being accepted.
if (faults.isActive(scenario.id, 'auth-failure', channelId)) {
  sendJson(res, 401, { error: 'fault: auth-failure' });
  return;
}

// 3. Real credential validation, when the scenario declares any.
if (scenario.username !== undefined) {
  const givenUser = url.searchParams.get('username');
  const givenPass = url.searchParams.get('password');
  if (givenUser !== scenario.username || givenPass !== (scenario.password ?? '')) {
    sendJson(res, 401, { error: 'bad credentials' });
    return;
  }
}

// 4. redirect-chain: a chain of 302s that finally lands on this same URL
//    with ?chain=0, so the payload is reachable by following it.
const chainConfig = faults.configOf(scenario.id, 'redirect-chain');
if (chainConfig && faults.isActive(scenario.id, 'redirect-chain', channelId)) {
  const remaining = Number(url.searchParams.get('chain') ?? (chainConfig.depth ?? DEFAULT_REDIRECT_DEPTH));
  if (remaining > 0) {
    const next = new URL(url.pathname + url.search, INTERNAL_ORIGIN);
    next.searchParams.set('chain', String(remaining - 1));
    res.writeHead(302, { Location: next.toString() });
    res.end();
    return;
  }
}

// 5. non-ts-bytes: 200 with an HTML error page, which is what a provider
//    actually sends when it is unhappy. buffer.py's realignment is the code
//    this exercises.
if (faults.isActive(scenario.id, 'non-ts-bytes', channelId)) {
  const body = '<html><body><h1>502 Bad Gateway</h1></body></html>';
  res.writeHead(200, {
    'Content-Type': 'text/html',
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
  return;
}

// 6. connection-limit as a fault forces rejection regardless of the count.
if (faults.isActive(scenario.id, 'connection-limit', channelId)) {
  sendJson(res, 429, { error: 'fault: connection-limit' });
  return;
}
```

Apply the same `not-found` and `auth-failure` checks to the playlist and EPG routes, so an M3U refresh can be made to fail.

- [ ] **Step 6: Add the control routes**

```ts
const faultMatch = /^\/s\/([^/]+)\/fault$/.exec(url.pathname);
if (faultMatch && req.method === 'POST') {
  const scenario = registry.get(faultMatch[1]);
  if (!scenario) {
    sendJson(res, 404, { error: `no scenario ${faultMatch[1]}` });
    return;
  }
  const request = (await readJsonBody(req)) as FaultRequest;
  if (!FAULT_NAMES.includes(request.fault)) {
    // Naming the valid set turns a typo into an immediate, readable failure
    // rather than a fault that silently never fires.
    sendJson(res, 400, {
      error: `unknown fault ${String(request.fault)}; expected one of ${FAULT_NAMES.join(', ')}`,
    });
    return;
  }
  sendJson(res, 200, faults.apply(scenario.id, request, connections));
  return;
}

const rateMatch = /^\/s\/([^/]+)\/rate$/.exec(url.pathname);
if (rateMatch && req.method === 'POST') {
  const scenario = registry.get(rateMatch[1]);
  if (!scenario) {
    sendJson(res, 404, { error: `no scenario ${rateMatch[1]}` });
    return;
  }
  const body = (await readJsonBody(req)) as { rate?: number };
  if (typeof body.rate !== 'number' || body.rate <= 0) {
    sendJson(res, 400, { error: 'rate must be a number greater than 0' });
    return;
  }
  scenario.rate = body.rate;
  sendJson(res, 200, { rate: scenario.rate });
  return;
}
```

- [ ] **Step 7: Run the whole suite**

Run: `cd e2e-upstream && npx vitest run`
Expected: PASS, 41 tests

- [ ] **Step 8: Commit**

```bash
git add e2e-upstream
```

```bash
git commit -m "feat(e2e): eight fault modes and the fault control API

appliedTo counts only the live connections a fault could reach. The five
new-request faults legitimately report 0, because headers are already sent on
an open response — arming not-found for the next reconnect is a normal test."
```

---

### Task 7: Per-scenario request log

Makes G4 debuggable. Without it, "the failover didn't fire" cannot be told apart from "it reconnected and the provider rejected it".

**Files:**
- Create: `e2e-upstream/src/log.ts`
- Modify: `e2e-upstream/src/server.ts`, `e2e-upstream/src/stream.ts`
- Test: `e2e-upstream/test/log.test.ts`

**Interfaces:**
- Produces:

```ts
export interface LogEntry {
  at: string;              // ISO 8601
  kind: 'request' | 'open' | 'close' | 'fault';
  method?: string;
  path?: string;
  status?: number;
  channelId?: number;
  bytes?: number;
  durationMs?: number;
  fault?: string;
  detail?: string;
}

export class ScenarioLog {
  record(scenarioId: string, entry: Omit<LogEntry, 'at'>): void;
  entries(scenarioId: string): LogEntry[];
  clear(scenarioId: string): void;
}
```

- [ ] **Step 1: Write the failing test**

`e2e-upstream/test/log.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { ScenarioLog, MAX_ENTRIES } from '../src/log';

describe('ScenarioLog', () => {
  it('keeps entries per scenario, oldest first', () => {
    const log = new ScenarioLog();
    log.record('a', { kind: 'request', method: 'GET', path: '/one', status: 200 });
    log.record('a', { kind: 'request', method: 'GET', path: '/two', status: 404 });
    log.record('b', { kind: 'request', method: 'GET', path: '/other', status: 200 });

    expect(log.entries('a').map((e) => e.path)).toEqual(['/one', '/two']);
    expect(log.entries('b')).toHaveLength(1);
  });

  it('stamps every entry with an ISO timestamp', () => {
    const log = new ScenarioLog();
    log.record('a', { kind: 'open', channelId: 1 });

    expect(log.entries('a')[0].at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });

  it('records the HTTP method, so a HEAD probe is distinguishable from a client', () => {
    // validate_stream_url probes with HEAD before every redirect-profile
    // stream. A log that did not record the method would show two
    // indistinguishable hits and make the probe look like a real viewer.
    const log = new ScenarioLog();
    log.record('a', { kind: 'request', method: 'HEAD', path: '/s/a/stream/1.ts', status: 200 });

    expect(log.entries('a')[0].method).toBe('HEAD');
  });

  it('caps the history so a long streaming test cannot exhaust memory', () => {
    const log = new ScenarioLog();
    for (let n = 0; n < MAX_ENTRIES + 50; n += 1) {
      log.record('a', { kind: 'request', path: `/${n}` });
    }

    expect(log.entries('a')).toHaveLength(MAX_ENTRIES);
    expect(log.entries('a')[0].path).toBe('/50');
  });

  it('returns an empty list for a scenario that has done nothing', () => {
    expect(new ScenarioLog().entries('unknown')).toEqual([]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd e2e-upstream && npx vitest run test/log.test.ts`
Expected: FAIL — `Cannot find module '../src/log'`

- [ ] **Step 3: Implement the log**

`e2e-upstream/src/log.ts`:

```ts
export interface LogEntry {
  at: string;
  kind: 'request' | 'open' | 'close' | 'fault';
  method?: string;
  path?: string;
  status?: number;
  channelId?: number;
  bytes?: number;
  durationMs?: number;
  fault?: string;
  detail?: string;
}

/**
 * Bounded because a streaming test can hold a connection for five minutes and
 * a scenario is never evicted. Old entries are dropped, not new ones: the
 * interesting end of a failure is the recent end.
 */
export const MAX_ENTRIES = 2000;

export class ScenarioLog {
  private byScenario = new Map<string, LogEntry[]>();

  record(scenarioId: string, entry: Omit<LogEntry, 'at'>): void {
    const entries = this.byScenario.get(scenarioId) ?? [];
    entries.push({ at: new Date().toISOString(), ...entry });
    if (entries.length > MAX_ENTRIES) entries.splice(0, entries.length - MAX_ENTRIES);
    this.byScenario.set(scenarioId, entries);
  }

  entries(scenarioId: string): LogEntry[] {
    return this.byScenario.get(scenarioId) ?? [];
  }

  clear(scenarioId: string): void {
    this.byScenario.delete(scenarioId);
  }
}
```

- [ ] **Step 4: Wire logging into the server**

Add `export const scenarioLog = new ScenarioLog();` to `src/server.ts`.

Record at four points:

1. Every request that resolves to a scenario, once its status is decided: `scenarioLog.record(scenario.id, { kind: 'request', method: req.method, path: url.pathname, status })`. Add this to the playlist, EPG and stream routes.
2. Stream open, in `onConnection`: `{ kind: 'open', channelId }`.
3. Stream close, in `onClosed`: `{ kind: 'close', channelId, bytes, durationMs }`. `streamLoop` must therefore report its byte count and duration — extend `StreamControl.onClosed` to `onClosed(stats: { bytes: number; durationMs: number }): void` and pass the values it already tracks.
4. Every fault application, in the fault route: `{ kind: 'fault', fault: request.fault, detail: JSON.stringify(result) }`.

Then add the two read routes:

```ts
const logMatch = /^\/s\/([^/]+)\/log$/.exec(url.pathname);
if (logMatch && req.method === 'GET') {
  sendJson(res, 200, scenarioLog.entries(logMatch[1]));
  return;
}

const connectionsMatch = /^\/s\/([^/]+)\/connections$/.exec(url.pathname);
if (connectionsMatch && req.method === 'GET') {
  const scenario = registry.get(connectionsMatch[1]);
  if (!scenario) {
    sendJson(res, 404, { error: `no scenario ${connectionsMatch[1]}` });
    return;
  }
  sendJson(res, 200, {
    live: connections.count(scenario.id),
    maxConnections: scenario.maxConnections,
    channels: connections
      .matching(scenario.id)
      .map((connection) => connection.channelId),
  });
  return;
}
```

- [ ] **Step 5: Run the whole suite**

Run: `cd e2e-upstream && npx vitest run`
Expected: PASS, 46 tests

- [ ] **Step 6: Commit**

```bash
git add e2e-upstream
```

```bash
git commit -m "feat(e2e): per-scenario request and connection log

Records the HTTP method, so validate_stream_url's HEAD probe is
distinguishable from a real viewer in a G4 failure post-mortem."
```

---
### Task 8: The `upstream` fixture and `streamClient`'s redirect option

**Files:**
- Create: `e2e/fixtures/upstream.ts`
- Modify: `e2e/fixtures/index.ts`, `e2e/fixtures/stream-client.ts`
- Test: covered by Tasks 9 and 10; this task's gate is `npm run typecheck` plus the existing suite still passing.

**Interfaces:**
- Consumes: the provider's control API (Tasks 2, 6, 7).
- Produces:

```ts
export interface UpstreamChannel { id: number; name: string; tvgId: string; logo: string | null }

export interface UpstreamScenario {
  id: string;
  /** Origin Dispatcharr resolves. Hand these URLs to the product. */
  internal: string;
  /** Origin Playwright resolves. Hand these to fetch/streamClient. */
  control: string;
  credentialQuery: string;
  channels: UpstreamChannel[];
}

export class UpstreamClient {
  scenario(request?: ScenarioRequest): Promise<UpstreamScenario>;
  fault(scenario: UpstreamScenario, fault: FaultName, options?: FaultOptions): Promise<FaultResult>;
  clearFault(scenario: UpstreamScenario, fault: FaultName, options?: FaultOptions): Promise<FaultResult>;
  rate(scenario: UpstreamScenario, rate: number): Promise<{ rate: number }>;
  log(scenario: UpstreamScenario): Promise<LogEntry[]>;
  connections(scenario: UpstreamScenario): Promise<{ live: number; maxConnections: number | null; channels: number[] }>;
  playlistUrl(scenario: UpstreamScenario): string;   // internal
  epgUrl(scenario: UpstreamScenario): string;        // internal
  streamUrl(scenario: UpstreamScenario, channelId: number): string;  // internal
  toControl(url: string): string;
  readonly created: UpstreamScenario[];
}
```

Plus the changed `StreamClient.open` signature:

```ts
export interface StreamOpenOptions {
  headers?: Record<string, string>;
  /** Defaults to 'follow', preserving existing behaviour. */
  redirect?: RequestRedirect;
}
open(path: string, options?: StreamOpenOptions): Promise<void>;
```

- [ ] **Step 1: Write the client**

`e2e/fixtures/upstream.ts`. The critical part is `toControl`: Dispatcharr's Redirect profile 302s the client to the *original* upstream URL, which is a container-internal hostname the Playwright host cannot resolve, so a redirect test walks the chain itself after rewriting each hop.

```ts
import type { TestInfo } from '@playwright/test';

export const UPSTREAM_CONTROL_BASE =
  process.env.E2E_UPSTREAM_CONTROL_URL ?? 'http://127.0.0.1:9402';

export const UPSTREAM_INTERNAL_BASE =
  process.env.E2E_UPSTREAM_INTERNAL_URL ?? 'http://e2e-upstream:8080';

export type FaultName =
  | 'dead-air'
  | 'slow-trickle'
  | 'disconnect'
  | 'not-found'
  | 'auth-failure'
  | 'connection-limit'
  | 'redirect-chain'
  | 'non-ts-bytes';

export interface FaultOptions {
  channel?: number;
  rate?: number;
  clean?: boolean;
  afterBytes?: number;
  depth?: number;
}

export interface FaultResult {
  fault: FaultName;
  active: boolean;
  /**
   * How many *live* connections the fault reached. Five of the eight faults
   * can only affect the next request — headers are already sent on an open
   * response — so 0 is correct and expected for them. Arming `not-found` for
   * a reconnect that has not happened yet is a normal test. Assert on this
   * value when your test means to disrupt something already streaming; do
   * not assume it is always positive.
   */
  appliedTo: number;
}

export interface UpstreamChannel {
  id: number;
  name: string;
  tvgId: string;
  logo: string | null;
}

export interface ScenarioRequest {
  channels?: number | UpstreamChannel[];
  username?: string;
  password?: string;
  maxConnections?: number;
  rate?: number;
}

export interface UpstreamScenario {
  id: string;
  internal: string;
  control: string;
  credentialQuery: string;
  channels: UpstreamChannel[];
}

export interface LogEntry {
  at: string;
  kind: 'request' | 'open' | 'close' | 'fault';
  method?: string;
  path?: string;
  status?: number;
  channelId?: number;
  bytes?: number;
  durationMs?: number;
  fault?: string;
  detail?: string;
}

export class UpstreamClient {
  readonly created: UpstreamScenario[] = [];

  constructor(private readonly controlBase: string = UPSTREAM_CONTROL_BASE) {}

  private async call<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${this.controlBase}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    });
    if (!res.ok) {
      throw new Error(
        `upstream control ${init?.method ?? 'GET'} ${path} failed: ` +
          `${res.status} ${res.statusText} — ${await res.text()}`
      );
    }
    return (await res.json()) as T;
  }

  async scenario(request: ScenarioRequest = {}): Promise<UpstreamScenario> {
    const scenario = await this.call<UpstreamScenario>('/scenarios', {
      method: 'POST',
      body: JSON.stringify(request),
    });
    // The provider echoes `control` from the request's Host header, which is
    // the base this client used — so it already points at the published port.
    this.created.push(scenario);
    return scenario;
  }

  fault(
    scenario: UpstreamScenario,
    fault: FaultName,
    options: FaultOptions = {}
  ): Promise<FaultResult> {
    return this.call<FaultResult>(`/s/${scenario.id}/fault`, {
      method: 'POST',
      body: JSON.stringify({ fault, active: true, ...options }),
    });
  }

  clearFault(
    scenario: UpstreamScenario,
    fault: FaultName,
    options: FaultOptions = {}
  ): Promise<FaultResult> {
    return this.call<FaultResult>(`/s/${scenario.id}/fault`, {
      method: 'POST',
      body: JSON.stringify({ fault, active: false, ...options }),
    });
  }

  rate(scenario: UpstreamScenario, rate: number): Promise<{ rate: number }> {
    return this.call(`/s/${scenario.id}/rate`, {
      method: 'POST',
      body: JSON.stringify({ rate }),
    });
  }

  log(scenario: UpstreamScenario): Promise<LogEntry[]> {
    return this.call<LogEntry[]>(`/s/${scenario.id}/log`);
  }

  connections(
    scenario: UpstreamScenario
  ): Promise<{ live: number; maxConnections: number | null; channels: number[] }> {
    return this.call(`/s/${scenario.id}/connections`);
  }

  playlistUrl(scenario: UpstreamScenario): string {
    return `${scenario.internal}/playlist.m3u${scenario.credentialQuery}`;
  }

  epgUrl(scenario: UpstreamScenario): string {
    return `${scenario.internal}/epg.xml${scenario.credentialQuery}`;
  }

  streamUrl(scenario: UpstreamScenario, channelId: number): string {
    return `${scenario.internal}/stream/${channelId}.ts${scenario.credentialQuery}`;
  }

  /**
   * Rewrites a container-internal upstream URL to one the Playwright host can
   * reach.
   *
   * Needed because `validate_stream_url()` follows redirects server-side but
   * returns the URL it was *given*, and `views.py` then 302s the client to
   * that — i.e. to `http://e2e-upstream:8080/...`, a name that resolves only
   * inside the Docker network. A Redirect-profile test therefore opens with
   * `redirect: 'manual'`, reads `Location`, and walks the chain itself,
   * passing each hop through here.
   *
   * Throws rather than returning the input unchanged: silently passing an
   * unrecognised URL through is how a test ends up making a real outbound
   * request to whatever the URL happens to name.
   */
  toControl(url: string): string {
    if (!url.startsWith(UPSTREAM_INTERNAL_BASE)) {
      throw new Error(
        `toControl() expected a URL under ${UPSTREAM_INTERNAL_BASE}, got ${url}`
      );
    }
    return this.controlBase + url.slice(UPSTREAM_INTERNAL_BASE.length);
  }

  /** Attaches every scenario's log to the report. Called by the fixture on failure. */
  async attachLogs(testInfo: TestInfo): Promise<void> {
    for (const scenario of this.created) {
      await testInfo.attach(`upstream-log-${scenario.id}`, {
        body: JSON.stringify(await this.log(scenario), null, 2),
        contentType: 'application/json',
      });
    }
  }
}
```

- [ ] **Step 2: Register the fixture**

In `e2e/fixtures/index.ts`, add `upstream: UpstreamClient` to the `Fixtures` type and:

```ts
  upstream: async ({}, use, testInfo) => {
    const client = new UpstreamClient();
    await use(client);
    // Only on failure: a passing test's log is noise, and fetching it costs a
    // round trip per scenario.
    if (testInfo.status !== testInfo.expectedStatus) {
      await client.attachLogs(testInfo);
    }
  },
```

Export the types and class:

```ts
export { UpstreamClient, UPSTREAM_CONTROL_BASE, UPSTREAM_INTERNAL_BASE } from './upstream';
export type {
  FaultName,
  FaultOptions,
  FaultResult,
  LogEntry,
  ScenarioRequest,
  UpstreamChannel,
  UpstreamScenario,
} from './upstream';
```

Add an `upstream` block to the file's header comment, in the same style as the existing entries. It must state: the two origins and that they are never interchangeable; that `appliedTo` is 0 for the five new-request faults and that is correct; and that scenarios are test-scoped with no cleanup.

- [ ] **Step 3: Change `streamClient.open`'s signature**

In `e2e/fixtures/stream-client.ts`:

```ts
export interface StreamOpenOptions {
  headers?: Record<string, string>;
  /**
   * Defaults to 'follow'. Pass 'manual' when the response is expected to be a
   * redirect to a container-internal hostname — Dispatcharr's Redirect profile
   * 302s to the original upstream URL, which this process cannot resolve.
   */
  redirect?: RequestRedirect;
}

async open(path: string, options: StreamOpenOptions = {}): Promise<void> {
  this.controller = new AbortController();
  const url = path.startsWith('http') ? path : new URL(path, this.baseURL).toString();

  let response: Response;
  try {
    response = await fetch(url, {
      headers: options.headers ?? {},
      redirect: options.redirect ?? 'follow',
      signal: this.controller.signal,
    });
  } catch (cause) {
    throw new Error(describeFetchFailure(url, cause), { cause });
  }

  // With redirect: 'manual', a 3xx is the expected outcome, not a failure —
  // the caller reads Location and walks the chain. res.ok() is false for it,
  // so the check below must not reject it.
  if (!response.ok && !(options.redirect === 'manual' && response.status >= 300 && response.status < 400)) {
    throw new Error(`stream open failed: ${response.status} ${response.statusText}`);
  }
  this.status = response.status;
  this.headers = response.headers;
  if (!response.body) {
    throw new Error('stream response carried no body');
  }
  this.reader = response.body.getReader();
}
```

Add `status` and `headers` as public readable fields so a redirect test can read `Location`.

And the named error:

```ts
/**
 * A DNS failure on the provider's container-internal name is the single most
 * likely way a streaming test goes wrong, and Node reports it as a bare
 * "fetch failed" with the cause buried. Naming it costs one function and
 * saves the reader the whole investigation.
 */
function describeFetchFailure(url: string, cause: unknown): string {
  const code = (cause as { cause?: { code?: string } })?.cause?.code;
  const dnsFailure = code === 'ENOTFOUND' || code === 'EAI_AGAIN';

  if (dnsFailure && url.includes('e2e-upstream')) {
    return (
      `stream open failed: cannot resolve ${url} from the test process. ` +
      `That hostname resolves only inside the Docker network. If this came ` +
      `from following a redirect, open with { redirect: 'manual' } and pass ` +
      `each Location through upstream.toControl().`
    );
  }
  return `stream open failed: ${url} — ${String(cause)}`;
}
```

- [ ] **Step 4: Typecheck and run the existing suites**

Run: `cd e2e && npm run typecheck`
Expected: PASS. The three existing `open()` call sites pass no second argument, so none of them break.

Run: `cd e2e && npx playwright test --project=streaming`
Expected: PASS, unchanged — this task has not touched the exemplars yet.

- [ ] **Step 5: Commit**

```bash
git add e2e/fixtures
```

```bash
git commit -m "feat(e2e): upstream fixture, and a redirect option on streamClient

toControl() exists because validate_stream_url returns the URL it was given
rather than the redirect target, so Dispatcharr 302s the client to a
container-internal hostname the test process cannot resolve. A DNS failure on
that name now throws by name instead of a bare 'fetch failed'."
```

---

### Task 9: Port the G1 exemplars onto the provider, delete the throwaway

**Files:**
- Modify: `e2e/tests/streaming/stream-client.spec.ts`, `e2e/tests/streaming/stalled-stream.spec.ts`
- Delete: `e2e/support/static-upstream.ts`

These two specs test `streamClient`'s **own** semantics, not the proxy, so they keep hitting the provider **directly** through `control`. The through-Dispatcharr tests are Task 10's.

The regression `stalled-stream.spec.ts` pins is real and must survive the port: `collectFor(ms)` races `pump()` against a timer, and when the timer wins the abandoned `reader.read()` is left outstanding. Read requests queue FIFO, so a later `readPackets()` that issued its own read would sit behind the abandoned one and wait for a chunk *after* the one it needed — a deadlock with the wanted bytes already buffered. Its two cases need a stream that bursts then falls silent, and a stream that genuinely ends. Both are now faults:

| Old mechanism | New mechanism |
|---|---|
| `burstsAtMs: [0, 600]` then silence | Read once, then `upstream.fault(scenario, 'dead-air')` |
| `endAfterLastBurst: true` | `upstream.fault(scenario, 'disconnect', { clean: true, afterBytes })` |

- [ ] **Step 1: Port `stream-client.spec.ts`**

```ts
import { test, expect, expectTsAligned, TS_PACKET_SIZE } from '../../fixtures';

test('reads whole TS packets from a live stream', async ({ upstream, streamClient }) => {
  const scenario = await upstream.scenario({ channels: 1, rate: 20 });

  // rate 20 so the test does not wait real time for real bitrate. Only a
  // test asserting on ffmpeg's speed= needs rate 1.
  await streamClient.open(upstream.toControl(upstream.streamUrl(scenario, 1)));

  const packets = await streamClient.readPackets(10);

  expect(packets.byteLength).toBe(10 * TS_PACKET_SIZE);
  expectTsAligned(packets);
});
```

- [ ] **Step 2: Port `stalled-stream.spec.ts`**

Keep the existing `withDeadline` helper and its explanatory comment verbatim — it exists so a regression fails in seconds rather than timing out at 300 s with a useless message. Replace only how the stall and the end are produced:

```ts
test('readPackets returns promptly when collectFor timed out mid-read', async ({
  upstream,
  streamClient,
}) => {
  const scenario = await upstream.scenario({ channels: 1, rate: 20 });
  await streamClient.open(upstream.toControl(upstream.streamUrl(scenario, 1)));

  // Let bytes flow, then stall the socket with it still open.
  const flowing = await streamClient.readPackets(5);
  expectTsAligned(flowing);

  const applied = await upstream.fault(scenario, 'dead-air');
  // dead-air reaches live connections, so this must be 1. If it is 0 the
  // stream was never admitted and the rest of this test proves nothing.
  expect(applied.appliedTo).toBe(1);

  // The 200ms deadline expires with a reader.read() outstanding.
  await streamClient.collectFor(200);

  // Clearing the fault delivers the chunk that fulfils that outstanding read.
  await upstream.clearFault(scenario, 'dead-air');

  const after = await withDeadline(
    streamClient.readPackets(1),
    READ_DEADLINE_MS,
    'readPackets after a timed-out collectFor'
  );
  expectTsAligned(after);
});
```

The second case, a stream that genuinely ends:

```ts
test('readPackets throws by name when the stream ends short', async ({
  upstream,
  streamClient,
}) => {
  const scenario = await upstream.scenario({ channels: 1, rate: 20 });
  await streamClient.open(upstream.toControl(upstream.streamUrl(scenario, 1)));

  // A clean EOF after a bounded number of bytes — the product logs this as
  // "HTTP stream ended", a different reconnect branch from an abrupt close.
  await upstream.fault(scenario, 'disconnect', {
    clean: true,
    afterBytes: 20 * TS_PACKET_SIZE,
  });

  await expect(
    withDeadline(streamClient.readPackets(1000), READ_DEADLINE_MS, 'readPackets past the end')
  ).rejects.toThrow(/stream ended after \d+ bytes/);
});
```

- [ ] **Step 3: Delete the throwaway**

```bash
git rm e2e/support/static-upstream.ts
rmdir e2e/support 2>/dev/null || true
```

- [ ] **Step 4: Verify nothing still imports it**

Run: `grep -rn "static-upstream" e2e || echo "clean"`
Expected: `clean`

Run: `cd e2e && npm run typecheck`
Expected: PASS

- [ ] **Step 5: Run the streaming project**

Run: `./scripts/e2e_up.sh && cd e2e && npx playwright test --project=streaming`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A e2e
```

```bash
git commit -m "test(e2e): port the streaming exemplars onto the provider

The stalled-stream regression is preserved: dead-air replaces the burst
schedule, and a clean disconnect after a byte count replaces
endAfterLastBurst. Deletes e2e/support/static-upstream.ts, which G1 labelled
throwaway for exactly this moment."
```

---

### Task 10: The two plumbing proofs

Nothing before this proves the loop actually closes — that Dispatcharr can *fetch* from the provider and *stream through* it. These two tests exist so G3's and G4's agents never inherit an undiagnosed networking failure.

**Files:**
- Create: `e2e/tests/seeded/upstream-ingest.spec.ts`, `e2e/tests/streaming/upstream-through-proxy.spec.ts`

**Interfaces:**
- Consumes: `upstream` (Task 8), `seed`, `api`, `waitFor`, `streamClient`, `expectTsAligned` (G1).

Facts these tests must respect, all verified:

- `seed.m3uAccount()` defaults to `is_active: false` and a dead-port URL. **Both** must be overridden, or the refresh never starts and both wait phases fail.
- `waitFor.m3uRefreshComplete(id)` **owns the trigger**. Do not POST `/api/m3u/refresh/<id>/` first.
- `GET /api/channels/streams/` is paginated and supports `?search=`, matching `name` and `channel_group__name`. Never assert against the unfiltered list.
- `ChannelSerializer.streams` is a `PrimaryKeyRelatedField`, so `seed.channel({ streams: [id] })` works, and `Channel.uuid` is already on the fixture type.
- Issue #7: concurrent `M3UAccount` creation can wedge an instance via an `IntervalSchedule.get_or_create` race. `bootstrap` pre-warms the schedule and detects the poisoned state, so this is handled — but if the ingest test fails with a 500 on account creation, check that first rather than assuming the provider is at fault.

- [ ] **Step 1: Write the ingest proof**

`e2e/tests/seeded/upstream-ingest.spec.ts`:

```ts
import { test, expect } from '../../fixtures';
import type { M3uAccount } from '../../fixtures';

interface StreamPage {
  count: number;
  results: { id: number; name: string; url: string }[];
}

test('Dispatcharr ingests a playlist from the fake upstream', async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  // Names are worker- and test-scoped so the ?search= below is a filtered
  // query, not an assertion about global state. The default catalogue's
  // "Fake Channel 1" would collide across parallel tests.
  const prefix = seed.generatedName('upstreamChannel');
  const scenario = await upstream.scenario({
    channels: [
      { id: 1, name: `${prefix}-a`, tvgId: `${prefix}-a.e2e`, logo: null },
      { id: 2, name: `${prefix}-b`, tvgId: `${prefix}-b.e2e`, logo: null },
    ],
  });

  const account = await seed.m3uAccount({
    server_url: upstream.playlistUrl(scenario),
    // Both overrides are load-bearing: the factory defaults to an inactive
    // account on a dead port, and an inactive account never starts a refresh.
    is_active: true,
  });

  // m3uRefreshComplete triggers the refresh itself. Do not POST it first.
  const refreshed: M3uAccount = await waitFor.m3uRefreshComplete(account.id);
  expect(refreshed.status).toBe('success');

  const page = await api.json<StreamPage>(
    await api.get(`/api/channels/streams/?search=${encodeURIComponent(prefix)}`),
    'streams created by the upstream ingest'
  );

  expect(page.count).toBe(2);
  expect(page.results.map((s) => s.name).sort()).toEqual([`${prefix}-a`, `${prefix}-b`]);
  // The URL survived the round trip, which is what proves the playlist was
  // parsed rather than merely fetched.
  expect(page.results[0].url).toContain(scenario.id);
});
```

- [ ] **Step 2: Run it**

Run: `./scripts/e2e_up.sh && cd e2e && npx playwright test --project=seeded upstream-ingest`
Expected: PASS

If it fails at `m3uRefreshComplete`, read the provider's view of it before anything else — the failure attaches the scenario log automatically, and a log with no `GET /s/<id>/playlist.m3u` entry means Dispatcharr never reached the provider, which is a networking problem, not a parsing one.

- [ ] **Step 3: Write the stream-through proof**

`e2e/tests/streaming/upstream-through-proxy.spec.ts`. Use the **Proxy** stream profile deliberately: it is raw HTTP passthrough with no subprocess, so the bytes arriving at the client are the provider's own and a failure implicates the network path rather than ffmpeg. G4 covers the profiles properly.

```ts
import { test, expect, expectTsAligned, TS_PACKET_SIZE } from '../../fixtures';
import type { Channel, StreamProfile } from '../../fixtures';

interface StreamProfilePage {
  count: number;
  results: StreamProfile[];
}

test('Dispatcharr proxies the fake upstream to a client', async ({
  upstream,
  seed,
  api,
  streamClient,
}) => {
  const scenario = await upstream.scenario({ channels: 1, rate: 20 });

  // The Proxy profile is raw HTTP passthrough — no subprocess — so what the
  // client receives is the provider's own bytes. That makes a failure here a
  // statement about the network path, not about ffmpeg.
  const profiles = await api.json<StreamProfilePage | StreamProfile[]>(
    await api.get('/api/core/streamprofiles/'),
    'locked stream profiles'
  );
  const all = Array.isArray(profiles) ? profiles : profiles.results;
  const proxyProfile = all.find((p) => p.name === 'Proxy');
  expect(proxyProfile, 'the locked "Proxy" stream profile should ship').toBeDefined();

  // No seed.stream() factory exists; generatedName is exported for exactly
  // this case — a row created by hand that still respects the naming scheme.
  const stream = await api.json<{ id: number }>(
    await api.post('/api/channels/streams/', {
      name: seed.generatedName('stream'),
      url: upstream.streamUrl(scenario, 1),
      is_custom: true,
    }),
    'custom stream pointing at the fake upstream'
  );

  const channel: Channel = await seed.channel({
    streams: [stream.id],
    stream_profile_id: proxyProfile!.id,
  });

  await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
  const packets = await streamClient.readPackets(50);

  expect(packets.byteLength).toBe(50 * TS_PACKET_SIZE);
  expectTsAligned(packets);

  // The provider agrees it served exactly one connection for this channel.
  const seen = await upstream.log(scenario);
  expect(seen.some((entry) => entry.kind === 'open' && entry.channelId === 1)).toBe(true);
});
```

`StreamProfile` may not carry `name` on the fixture type. If `npm run typecheck` complains, add the field to `e2e/fixtures/types.ts` following that file's documented rule — with evidence from `apps/core/serializers.py`, never a cast.

- [ ] **Step 4: Run it**

Run: `cd e2e && npx playwright test --project=streaming upstream-through-proxy`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add e2e/tests
```

```bash
git commit -m "test(e2e): prove Dispatcharr can ingest from and stream through the provider

The gap G1 left: both of its streaming exemplars read the throwaway upstream
directly, so no test had ever routed bytes through Dispatcharr from a
test-controlled source."
```

---

### Task 11: CI wiring and documentation

**Files:**
- Modify: `.github/workflows/e2e-tests.yml`, `e2e/COVERAGE.md`, `CONTEXT.md`, `e2e/README.md`
- Create: `e2e-upstream/README.md`

**zizmor is a ratchet at zero findings** and its hook blocks on every finding in this file. Write each new step clean the first time: no unpinned `uses:`, no `persist-credentials` left at its default, no workflow-level write permissions.

- [ ] **Step 1: Add the provider to the build job**

In the `build` job, after the existing image build:

```yaml
      - name: Build the upstream provider image
        run: docker build -f e2e-upstream/Dockerfile -t dispatcharr-e2e-upstream:local e2e-upstream

      - name: Export both images
        run: docker save dispatcharr-e2e:local dispatcharr-e2e-upstream:local | gzip > /tmp/dispatcharr-e2e.tar.gz
```

Replace the existing single-image `docker save` step with the two-image one above. `docker save` accepts several image references and writes one archive, so the artifact plumbing and the three consumers are unchanged — `docker load` restores both tags.

- [ ] **Step 2: Add the provider's own test job**

A sibling of `build`, deliberately **without** `needs: build` — it tests the provider in isolation and must report in under a minute rather than waiting on a 45-minute AIO build:

```yaml
  upstream:
    name: upstream
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Checkout code
        uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
        with:
          persist-credentials: false

      - name: Setup Node.js
        uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020 # v4.4.0
        with:
          node-version: '24'

      - name: Install dependencies
        working-directory: ./e2e-upstream
        run: npm ci

      - name: Typecheck
        working-directory: ./e2e-upstream
        run: npm run typecheck

      - name: Run the provider test suite
        working-directory: ./e2e-upstream
        run: npm test
```

The two action SHAs above are copied from the existing steps in this same file, so they are already publisher-verified and pinned. Do not re-resolve them; do verify by eye that they match what the file already uses.

- [ ] **Step 3: Point the matrix jobs at the shared script**

The `test` job already runs `./scripts/e2e_up.sh`, which Task 1 taught to create the network and start both containers. Nothing changes there — that is the payoff of the single-boot-path rule. Add the provider's logs to the failure path:

```yaml
      - name: Container logs (on failure)
        if: failure()
        run: |
          docker logs dispatcharr-e2e || true
          docker logs e2e-upstream || true
```

- [ ] **Step 4: Verify zizmor is still clean**

Run: `zizmor .github/workflows/e2e-tests.yml`
Expected: no findings. If the hook reports a version mismatch against the pin in `.github/workflows/actions-lint.yml`, bump both together — never silence one.

- [ ] **Step 5: Write `e2e-upstream/README.md`**

Cover, with no forward references to code the reader has to open:

- What it is, and that it is test infrastructure — never shipped, never in the product image.
- Running it locally: `./scripts/e2e_up.sh` starts it; `http://127.0.0.1:9402/scenarios` lists live scenarios.
- The two origins, why they exist, and that `toControl()` is the only sanctioned conversion.
- The control API table, copied from the spec.
- The fault catalogue table **including the "Applies to" column**, and an explicit statement that `appliedTo: 0` is correct for the five new-request faults.
- Pacing: rate 1 is nominal bitrate; only tests asserting on ffmpeg's `speed=` need it; everything else should use a higher rate and say why.
- The asset: built by `scripts/make-asset.sh` in the Docker builder stage, measured at load, and that the burned-in frame counter is a human debugging aid with no test consumer.

- [ ] **Step 6: Update `e2e/COVERAGE.md`**

Mark the G2 rows done: fake upstream provider, fault injection, and the two plumbing proofs. Leave every G3–G7 row at `todo`. Add a line stating that G3 and G4 are now unblocked.

- [ ] **Step 7: Update `CONTEXT.md`**

Add three glossary entries, in the file's existing style — definitions only, no implementation detail:

- **Scenario** — one test's isolated view of the fake upstream provider: its own catalogue, credentials, connection limit and faults, addressed by an id in the URL path. Not a session; not a Playwright project.
- **Fault** — a deliberate provider misbehaviour a test switches on to drive a Dispatcharr failure path. Distinct from a bug: a fault is expected, and the product is expected to survive it.
- **Upstream provider** — the fake IPTV source the E2E suite controls. Distinct from an *M3U Account*, which is Dispatcharr's record of a provider, and from a *Stream*, which is one playable URL.

- [ ] **Step 8: Update `e2e/README.md`**

Add a section stating that G2-dependent tests require the local two-container topology, and that the `E2E_BASE_URL` escape hatch does **not** extend to them — a remote Dispatcharr instance cannot reach a provider running on your laptop.

- [ ] **Step 9: Run everything**

```bash
cd e2e-upstream && npm test
cd ../e2e && npm run typecheck
./scripts/e2e_up.sh --reset
cd e2e && npx playwright test --project=seeded && npx playwright test --project=streaming
```

Expected: all green. `--reset` matters: it proves the whole topology comes up from nothing, which is what CI does.

- [ ] **Step 10: Commit**

```bash
git add -A
```

```bash
git commit -m "ci(e2e): build and test the upstream provider; document it

The provider's own suite runs without needs: build, so a provider regression
reports in under a minute instead of waiting on the AIO image."
```

---

## Self-review

**Spec coverage.** Every deliverable in the spec maps to a task: provider server and eight faults (1, 2, 3, 5, 6), Dockerfile with the ffmpeg builder confined to a build stage (1, 4), vitest suite including the seam's PTS monotonicity assertion and the `appliedTo === 0` case (4, 6), `e2e/fixtures/upstream.ts` with `toControl` (8), `streamClient`'s redirect option and named error (8), `e2e_up.sh` with network and readiness wait (1), CI with both images in one artifact and a `needs`-free `upstream` job (11), the ported exemplars hitting the provider directly (9), deletion of `static-upstream.ts` (9), the two plumbing proofs in `seeded` and `streaming` (10), and the three doc updates (11).

**Two places the plan knowingly diverges from a first reading of the spec**, both recorded so a reviewer does not treat them as drift:

1. The spec describes `slow-trickle` and the `/rate` control as separate things. The plan implements `slow-trickle` as a per-connection rate override and `/rate` as the scenario-wide default, with `clearFault` restoring `null` rather than `1` — so a scenario deliberately running at rate 20 is not silently reset to real time when a trickle is cleared. A test pins this.
2. The spec's loop duration is implied to come from the asset build. The plan **measures** it from the asset at load instead, because a build script and a server that disagree produce a seam that jumps backwards — silently breaking the one property every streaming test rests on.

**One correction folded into Task 5 rather than left to bite.** The synthetic TS helper as first written emits a PCR *and* a PTS per packet, which makes `measureLoop`'s sample count `2 * PACKETS` and its `step` arithmetic not equal the round number the test expects. Step 3 of Task 5 says so explicitly and directs the implementer to emit PCR every fourth packet and re-derive the expectation, rather than discovering it as a confusing failure.

**Type consistency.** `Scenario`/`ScenarioRequest`/`ChannelSpec` (Task 2) are mirrored on the fixture side as `UpstreamScenario`/`ScenarioRequest`/`UpstreamChannel` (Task 8) — deliberately different names because the fixture's version carries `internal`, `control` and `credentialQuery` that the server's does not. `FaultName`, `FaultRequest`/`FaultOptions` and `FaultResult` agree across Tasks 6 and 8. `LiveConnection`'s three methods (`setDeadAir`, `setRate`, `disconnect`) are used identically in Tasks 5 and 6. `StreamControl.onClosed` gains a stats argument in Task 7, which Task 5 must therefore not treat as final — Task 7 Step 4 says so.

**Known gap, deliberately left.** `streamLoop`'s pacing sleeps per chunk rather than against a cumulative target, so it drifts slightly slow under load. That is the right trade: a cumulative target would average away a rate change made mid-stream, which is precisely what `slow-trickle` needs to do promptly. The stream test asserts an order of magnitude, not a stopwatch.
