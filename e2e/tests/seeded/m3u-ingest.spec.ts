import { test, expect } from '../../fixtures';
import type { ChannelGroup, M3uAccount, StreamPage } from '../../fixtures';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

/**
 * The `group-title` every fake-provider channel carries, hardcoded in
 * `e2e-upstream/src/playlist.ts` (`renderPlaylist`). There is exactly one
 * ChannelGroup in play across every scenario and every worker, which is why
 * the group assertions below are membership checks and never counts.
 */
const UPSTREAM_GROUP_NAME = 'E2E';

test('an M3U refresh ingests the declared catalogue faithfully', async ({
  upstream,
  seed,
  api,
}) => {
  const prefix = seed.generatedName('catalogue');
  const declared = [1, 2, 3].map((id) => ({
    id,
    name: `${prefix}-ch${id}`,
    tvgId: `${prefix}-ch${id}.e2e`,
    logo: `https://example.invalid/${prefix}-ch${id}.png`,
  }));
  const scenario = await upstream.scenario({ channels: declared });

  const account = await seed.upstreamM3UAccount(scenario);

  // Scoped to this account, so `count` describes only this test's rows.
  const page = await api.json<StreamPage>(
    await api.get(`/api/channels/streams/?m3u_account=${account.id}`),
    'streams ingested by this account'
  );
  expect(page.count).toBe(3);

  const byName = new Map(page.results.map((s) => [s.name, s]));
  for (const channel of declared) {
    const stream = byName.get(channel.name);
    expect(stream, `no stream named ${channel.name}`).toBeDefined();
    expect(stream!.tvg_id).toBe(channel.tvgId);
    expect(stream!.logo_url).toBe(channel.logo);
    expect(stream!.m3u_account).toBe(account.id);
    expect(stream!.is_custom).toBe(false);
    // The URL survived the round trip, which is what proves the playlist was
    // parsed rather than merely fetched.
    expect(stream!.url).toContain(scenario.id);
    expect(stream!.url).toContain(`/stream/${channel.id}.ts`);
  }

  // Every stream landed in one group, and that group is wired to this account.
  const groupIds = new Set(page.results.map((s) => s.channel_group));
  expect(groupIds.size).toBe(1);
  const groupId = page.results[0].channel_group;
  expect(groupId).not.toBeNull();

  const readBack = await api.json<M3uAccount & { channel_groups: { channel_group: number }[] }>(
    await api.get(`/api/m3u/accounts/${account.id}/`),
    'account read-back for its group relations'
  );
  expect(readBack.channel_groups.map((g) => g.channel_group)).toContain(groupId);

  // Global, unpaginated list — membership only, never a count.
  const groups = await api.json<ChannelGroup[]>(
    await api.get('/api/channels/groups/'),
    'channel groups'
  );
  expect(groups.find((g) => g.id === groupId)?.name).toBe(UPSTREAM_GROUP_NAME);
});

// Pins `Seeder.waitForCreateTimeGroupRefreshToSettle()`'s own contract,
// deterministically — no fault, no timing race. `seed.upstreamM3UAccount()`
// relies on this method resolving on a genuine terminal write and timing out
// loudly on anything else (see its doc comment in seed.ts, and
// `upstreamM3UAccount()`'s, for the create-time-refresh race this closes).
//
// An account created `is_active: false` guarantees the account-lookup inside
// `refresh_m3u_groups` (`apps/m3u/tasks.py:1552-1556`, which filters
// `is_active=True`) raises `DoesNotExist` every time the create-time task
// runs — it writes nothing and the row's status never leaves `idle`. So this
// wait can only ever time out, never resolve, with zero dependence on
// container speed or the fake provider's behaviour.
test('waitForCreateTimeGroupRefreshToSettle times out rather than passing silently when the account never settles', async ({
  seed,
}) => {
  const account = await seed.m3uAccount({ is_active: false });

  await expect(
    seed.waitForCreateTimeGroupRefreshToSettle(account.id, {
      timeoutMs: 2_000,
      intervalMs: 100,
    })
  ).rejects.toThrow(/timed out.*to settle/is);
});

// Pins D10Scot/Dispatcharr#59's fix in `Waiter.m3uRefreshComplete()`,
// deterministically. The real symptom — a trigger silently dropped because
// `refresh_single_m3u_account`'s task lock from an immediately preceding
// refresh is still held — is timing-dependent against a live container and
// not reliably forceable from a test. So this pins the *mechanism* instead,
// with a custom `trigger` standing in for "the first attempt was dropped":
// it does nothing at all on its first call (exactly what a lock-contention
// drop looks like from here — the account never moves off its baseline),
// and only actually queues a refresh on its second call. If
// `m3uRefreshComplete()` still resolves, it can only be because phase 1
// re-invoked `trigger` on its own — `waitFor.resource()`'s poll alone would
// otherwise sit on an account stuck at its baseline until `startTimeoutMs`.
test("waitFor.m3uRefreshComplete re-fires its trigger when the account never moves off its baseline", async ({
  seed,
  waitFor,
  api,
}) => {
  // Inactive: no create-time `refresh_m3u_groups` task competes for
  // anything here, so the only thing that can move this account's status is
  // whichever `trigger()` call this test lets through.
  const account = await seed.m3uAccount({ is_active: false });
  let attempts = 0;

  const result = await waitFor.m3uRefreshComplete(account.id, {
    // Comfortably more than one retry interval (hardcoded at 5s inside
    // `m3uRefreshComplete`), so a single re-fire has room to land and
    // resolve well before this budget is exhausted.
    startTimeoutMs: 12_000,
    trigger: async () => {
      attempts += 1;
      if (attempts === 1) {
        return; // The dropped attempt.
      }
      // The account must be reactivated too: an inactive account's refresh
      // is its own silent no-op (see this method's doc comment in
      // wait.ts), so a bare POST here would prove nothing.
      const activated = await api.patch(`/api/m3u/accounts/${account.id}/`, {
        is_active: true,
      });
      expect(activated.ok()).toBeTruthy();
      const triggered = await api.post(`/api/m3u/refresh/${account.id}/`, {});
      expect(triggered.ok()).toBeTruthy();
    },
  });

  // The default `server_url` (the discard port) refuses the connection fast
  // — this test only needs a terminal status distinct from the idle
  // baseline, not a working playlist.
  expect(result.status).toBe('error');
  expect(attempts).toBeGreaterThanOrEqual(2);
});

/**
 * Scans `seed.ts`'s source text for one method's body. `anchor` must be the
 * method's signature up to and including its opening `(` (e.g.
 * `'async upstreamM3UAccount('`) — this first paren-counts from there to the
 * matching `)` that closes the parameter list, *then* brace-counts from the
 * next `{` to its match. Not a real parser — a plain-text scan is enough for
 * one well-formed, already-typechecked function, in the same spirit as
 * `streaming-greybox/quarantine.spec.ts`'s source scan (which enforces its
 * own import-allowlist convention the same way: by reading files as text,
 * not by parsing them).
 *
 * The paren-counting pass is load-bearing, not decorative: `upstreamM3UAccount`'s
 * own parameter list has a default value of `{}` (`overrides:
 * M3uAccountOverrides = {}`), so starting the brace scan at the *first* `{`
 * after `anchor` finds that empty object literal — already balanced at
 * depth zero — and returns it as the "body" instead of ever reaching the
 * function's real one.
 */
function extractMethodBody(source: string, anchor: string): string {
  if (!anchor.endsWith('(')) {
    throw new Error(`extractMethodBody: anchor must end with '(': ${JSON.stringify(anchor)}`);
  }
  const anchorIndex = source.indexOf(anchor);
  if (anchorIndex === -1) {
    throw new Error(`extractMethodBody: anchor ${JSON.stringify(anchor)} not found in source`);
  }

  const parenStart = anchorIndex + anchor.length - 1;
  let parenDepth = 0;
  let parenEnd = -1;
  for (let i = parenStart; i < source.length; i++) {
    if (source[i] === '(') parenDepth++;
    else if (source[i] === ')') {
      parenDepth--;
      if (parenDepth === 0) {
        parenEnd = i;
        break;
      }
    }
  }
  if (parenEnd === -1) {
    throw new Error(`extractMethodBody: unbalanced parens after anchor ${JSON.stringify(anchor)}`);
  }

  const braceStart = source.indexOf('{', parenEnd);
  if (braceStart === -1) {
    throw new Error(`extractMethodBody: no '{' found after the parameter list of ${JSON.stringify(anchor)}`);
  }
  let braceDepth = 0;
  for (let i = braceStart; i < source.length; i++) {
    if (source[i] === '{') braceDepth++;
    else if (source[i] === '}') {
      braceDepth--;
      if (braceDepth === 0) return source.slice(braceStart, i + 1);
    }
  }
  throw new Error(`extractMethodBody: unbalanced braces after anchor ${JSON.stringify(anchor)}`);
}

// A convention plus a doc comment decays silently. This does not.
//
// `upstreamM3UAccount()`'s own doc comment and `waitForCreateTimeGroupRefresh
// ToSettle()`'s doc comment (both in seed.ts) explain the race this call
// defends against — the create-time `refresh_m3u_groups` task racing
// `waitFor.m3uRefreshComplete()`'s baseline read — and the two behavioural
// tests above this one in this file exercise the wait's own timeout contract
// deterministically. Neither of those proves `upstreamM3UAccount()` still
// *calls* the wait: it's one line in a function whose removal every
// behavioural test in this suite passes straight through (confirmed by
// deleting it and re-running the full seeded project — see
// task-1-report.md's "Fix round 2" for the mutation check). That is exactly
// the situation `quarantine.spec.ts` was written for — a hazard invisible to
// every test that isn't specifically looking for it — so this checks the
// source text directly, the same way.
test("upstreamM3UAccount() still calls waitForCreateTimeGroupRefreshToSettle() before triggering the real refresh", async () => {
  const seedPath = path.resolve(__dirname, '../../fixtures/seed.ts');
  const source = await readFile(seedPath, 'utf8');

  // Scoped to the method's own body, not the whole file: the identifier
  // `waitForCreateTimeGroupRefreshToSettle` also appears in seed.ts's doc
  // comments and in that method's own definition, so a file-wide search
  // would still pass even if this specific call were deleted, or moved
  // somewhere that no longer runs before the baseline read it exists to
  // protect.
  const body = extractMethodBody(source, 'async upstreamM3UAccount(');

  expect(
    /\bthis\.waitForCreateTimeGroupRefreshToSettle\s*\(/.test(body),
    "upstreamM3UAccount()'s body no longer calls " +
      'this.waitForCreateTimeGroupRefreshToSettle(...) before triggering the ' +
      'real refresh. That call is the only defence against the create-time ' +
      'refresh_m3u_groups race documented on both methods\' doc comments in ' +
      'seed.ts: without it, m3uRefreshComplete()\'s baseline read can land on ' +
      'a status the create-time task wrote, not the triggered refresh — an ' +
      'intermittent false failure in every later G3 test built on ' +
      'seed.upstreamM3UAccount(). Restore the call inside ' +
      'upstreamM3UAccount(), immediately after the account is created and ' +
      'before waitFor.m3uRefreshComplete() is invoked.'
  ).toBe(true);
});

/**
 * Known bug: D10Scot/Dispatcharr#15. `M3UAccountSerializer` declares
 * `read_only_fields = ["locked", "created_at", "updated_at"]` in its **class
 * body** instead of inside `Meta`, so DRF never reads it and `locked` is
 * writable over the API. `locked` marks the built-in custom account
 * (`M3UAccount.get_custom_account`), and nothing else in `apps/` or `core/`
 * checks it — so a client can both set and clear it at will.
 *
 * Asserts the CORRECT behaviour and is expected to fail until #15 is fixed.
 * Do not patch the product from this harness; do not file a duplicate issue.
 */
test.fail('M3UAccount.locked is not writable over the API', async ({ seed, api }) => {
  const account = await seed.m3uAccount();
  expect(account.locked).toBe(false);

  const patched = await api.patch(`/api/m3u/accounts/${account.id}/`, { locked: true });
  expect(patched.ok()).toBeTruthy();

  const readBack = await api.json<M3uAccount>(
    await api.get(`/api/m3u/accounts/${account.id}/`),
    'account read-back after attempting to set locked'
  );
  expect(readBack.locked).toBe(false);
});
