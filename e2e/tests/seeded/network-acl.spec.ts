import { test, expect, xcQuery } from '../../fixtures';
import type { CoreSetting, NetworkAccessCheck, User } from '../../fixtures';
import { listRows } from '../../setup/http';

/**
 * The network-access ACL: `dispatcharr/utils.py:network_access_allowed`.
 *
 * `test.describe.configure({ mode: 'serial' })` below is required, not
 * decorative: `seeded` is `fullyParallel: true`, so a spec *file* is not a
 * confinement boundary on its own — two tests in this file could otherwise
 * run on two different workers at once. Test 3 writes the instance-wide
 * `network_access` row; only serial mode (which also pins every test here to
 * one worker, in order) makes that window something this file alone can see
 * and clean up.
 *
 * `network_access_allowed(request, settings_key, user=None)` has exactly
 * three scope defaults, and the shipped `network_access` `CoreSettings` row
 * is `{}` — no key present — so every request in tests 1 and 2 runs under
 * these defaults, untouched:
 *   - `M3U_EPG` → `LOCAL_NETWORK_CIDRS` (private/loopback only)
 *   - everything else (including `XC_API`, `STREAMS`, `UI`) → `0.0.0.0/0`
 *
 * The mechanism every test here depends on: `get_client_ip`
 * (`dispatcharr/utils.py`) honours `X-Real-IP` only when `REMOTE_ADDR` — the
 * TCP peer — is itself a trusted proxy. In this container that peer is
 * nginx, reached over the Docker bridge, which is inside
 * `LOCAL_NETWORK_CIDRS` and therefore trusted by default. nginx's
 * `uwsgi_pass` routes neither set nor strip `X-Real-IP`, so a client that
 * supplies its own header is believed verbatim
 * ([#81](https://github.com/D10Scot/Dispatcharr/issues/81)). Test 1 pins
 * this as a fact about *this* topology, not a portable one.
 *
 * `network_access["UI"]` is never written by any test in this file, under
 * any circumstance. `apps/accounts/permissions.py:Authenticated` gates every
 * DRF endpoint — including the settings-write endpoint that would undo a
 * mistake — on that scope, so a wrong `UI` value locks out the very API call
 * needed to fix it, and recovery would mean `manage.py reset_network_access`
 * over `docker exec` against a shared instance.
 *
 * Every request below goes through the built-in `request` fixture, never
 * `api`: `e2e/README.md` rule 11 — `ApiClient` retries once through a token
 * refresh on *any* 401, and 401 is one of the two statuses this file
 * asserts on (test 5 pins a `player_api.php` 401 as a known defect). Driving
 * that call through `api` would let the retry silently absorb the very
 * rejection under test.
 */
test.describe.configure({ mode: 'serial' });

// RFC 5737 TEST-NET-3 — reserved for documentation, so it can never collide
// with a real deployment address. Used everywhere in this file in place of a
// made-up non-local address.
const TEST_NET_3_IP = '203.0.113.5';
const TEST_NET_3_CIDR = '203.0.113.0/24';
const SPOOF_HEADERS = { 'X-Real-IP': TEST_NET_3_IP };

/** IPv4-only mirror of `dispatcharr/utils.py:LOCAL_NETWORK_CIDRS`'s four
 * IPv4 members. The container's own network is IPv4 (the unheadered probe in
 * Task 0 saw `172.25.0.1`, the Docker bridge), so the three IPv6 members
 * (`::1/128`, `fc00::/7`, `fe80::/10`) are never exercised here and are
 * omitted rather than half-implemented. */
const LOCAL_NETWORK_CIDRS_V4 = ['127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'];

function ipv4ToInt(ip: string): number | null {
  const m = ip.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (!m) return null;
  const parts = m.slice(1).map(Number);
  if (parts.some((p) => p > 255)) return null;
  return ((parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]) >>> 0;
}

function ipv4InCidr(ip: string, cidr: string): boolean {
  const [base, bitsStr] = cidr.split('/');
  const bits = Number(bitsStr);
  const ipInt = ipv4ToInt(ip);
  const baseInt = ipv4ToInt(base);
  if (ipInt === null || baseInt === null) return false;
  const mask = bits === 0 ? 0 : (0xffffffff << (32 - bits)) >>> 0;
  return (ipInt & mask) === (baseInt & mask);
}

function isWithinLocalNetworkCidrs(ip: string): boolean {
  return LOCAL_NETWORK_CIDRS_V4.some((cidr) => ipv4InCidr(ip, cidr));
}

/**
 * "Refused" for the XC surfaces, without pinning a specific status: a 200
 * is never a refusal, and the one surface that could otherwise produce a
 * false negative — `player_api.php`'s default action returns a `user_info`
 * envelope on success — is checked explicitly. `get.php`/`xmltv.php` never
 * produce that envelope on success (M3U text / XMLTV text respectively), so
 * the JSON-parse failure there is itself consistent with refusal.
 */
async function isXcRefused(res: {
  status(): number;
  json(): Promise<unknown>;
}): Promise<boolean> {
  if (res.status() === 200) return false;
  try {
    const body: unknown = await res.json();
    if (body && typeof body === 'object' && 'user_info' in (body as Record<string, unknown>)) {
      return false;
    }
  } catch {
    // Not JSON — fine; only the player_api.php envelope is JSON-shaped.
  }
  return true;
}

// @characterization: pins a fact about this container's nginx/uwsgi
// topology (that X-Real-IP from the Docker-bridge peer is honoured), which a
// deployment with DISPATCHARR_TRUSTED_PROXIES=none correctly fails. Every
// other test in this file depends on this holding, and this test is their
// premise, not a portable contract of its own.
test(
  'the network-access check resolves client_ip from an unheadered request and from a spoofed X-Real-IP',
  { tag: '@characterization' },
  async ({ request, api }) => {
    const token = await api.freshAccessToken();
    const auth = { Authorization: `Bearer ${token}` };
    const failureContext =
      'This is the premise for tests 2 and 3 in this file: they only mean something if ' +
      "this container's nginx/uwsgi topology honours X-Real-IP from the Docker-bridge " +
      'peer. If this fails, check DISPATCHARR_TRUSTED_PROXIES (dispatcharr/utils.py) — a ' +
      'deployment that sets it to "none" correctly fails this test — and ' +
      'https://github.com/D10Scot/Dispatcharr/issues/81.';

    const plain = await request.post('/api/core/settings/check/', {
      headers: auth,
      data: { key: 'network_access', value: {} },
    });
    expect(plain.status(), failureContext).toBe(200);
    const plainBody: NetworkAccessCheck = await plain.json();

    const spoofed = await request.post('/api/core/settings/check/', {
      headers: { ...auth, 'X-Real-IP': TEST_NET_3_IP },
      data: { key: 'network_access', value: {} },
    });
    expect(spoofed.status(), failureContext).toBe(200);
    const spoofedBody: NetworkAccessCheck = await spoofed.json();

    expect(
      isWithinLocalNetworkCidrs(plainBody.client_ip),
      `${failureContext} An unheadered request's client_ip was ${plainBody.client_ip}, ` +
        'expected an address inside LOCAL_NETWORK_CIDRS.'
    ).toBe(true);

    expect(
      spoofedBody.client_ip,
      `${failureContext} A request carrying X-Real-IP: ${TEST_NET_3_IP} resolved to ` +
        `client_ip ${spoofedBody.client_ip}, expected the header to be trusted verbatim.`
    ).toBe(TEST_NET_3_IP);
  }
);

test(
  'the M3U_EPG default refuses a client with a spoofed non-local X-Real-IP, out of the box',
  { tag: '@contract' },
  async ({ request }) => {
    // No settings write here — this is the product's out-of-the-box
    // behaviour with the shipped `network_access: {}` row, which is what
    // makes it the strongest form of this assertion.
    const paths = ['/output/m3u', '/output/epg', '/hdhr/discover.json', '/hdhr/lineup.json'];

    for (const path of paths) {
      // Positive control first, in the same test: a broken instance that
      // 403s everything cannot pass this by refusing the plain request too.
      const control = await request.get(path);
      expect(control.status(), `${path}: unheadered request (positive control)`).toBe(200);

      const blocked = await request.get(path, { headers: SPOOF_HEADERS });
      expect(blocked.status(), `${path}: spoofed non-local X-Real-IP`).toBe(403);
      expect(await blocked.json(), path).toEqual({ error: 'Forbidden' });
    }
  }
);

/**
 * Restores the `network_access` row PATCHed by test 3, to whatever it held
 * before that PATCH. Set only inside test 3, immediately before the write —
 * so this is a no-op for every other test in the file.
 *
 * `afterEach`, not a body-level `try`/`finally`: Playwright tears a test
 * down mid-`await` on a timeout, and code after that point — a `finally`
 * block included — does not reliably run. `afterEach` hooks are Playwright's
 * own fixture-teardown machinery and run on their own budget regardless of
 * how the test body ended. Same reasoning `plugins.spec.ts` and
 * `settings.spec.ts` already record, and the same non-masking shape: a
 * cleanup failure on top of an already-failing test is logged, not raised
 * over the reported cause.
 */
let networkAccessRestore: { id: number; value: unknown } | undefined;

test.afterEach(async ({ api }, testInfo) => {
  if (!networkAccessRestore) return;
  const { id, value } = networkAccessRestore;
  networkAccessRestore = undefined;

  try {
    const restored = await api.patch(`/api/core/settings/${id}/`, { value });
    if (restored.status() !== 200) {
      throw new Error(`network_access restore failed: PATCH returned ${restored.status()}`);
    }
  } catch (cleanupError) {
    if (testInfo.status !== 'passed') {
      console.error(
        'network-acl.spec.ts: cleanup failed after an in-flight test failure — ' +
          'not overwriting it. Cleanup error:',
        cleanupError
      );
      return;
    }
    throw cleanupError;
  }
});

// D2's blast-radius argument, in full, because it is what justifies the one
// exception to "never mutate a global CoreSettings row" this file makes:
// narrowing network_access["XC_API"] from its default 0.0.0.0/0 to the local
// CIDRs refuses only a request that carries a spoofed, non-local X-Real-IP
// header. Nothing else in the whole suite sends one — grep the tree for
// X-Real-IP and this file is the only hit outside this comment — so for the
// life of this test, every *real* client of every other test keeps exactly
// the access it already had, and even a leaked/misapplied value costs the
// container nothing beyond what test 1 already proves is spoofable anyway.
// A reader unconvinced by this argument can delete this one test and lose
// nothing else: it is D2's cost estimate made executable.
test(
  'narrowing the global XC_API allowlist blocks get.php/xmltv.php by network, not by credentials',
  { tag: '@contract' },
  async ({ api, seed, request }) => {
    const rows = listRows<CoreSetting>(
      await api.json(await api.get('/api/core/settings/'), 'list core settings')
    );
    const row = rows.find((candidate) => candidate.key === 'network_access');
    expect(row, 'no CoreSettings row with key "network_access"').toBeDefined();

    const currentValue = (row!.value ?? {}) as Record<string, unknown>;
    // Captured before the write, so afterEach can restore it even if
    // everything below throws.
    networkAccessRestore = { id: row!.id, value: currentValue };

    const narrowedValue = {
      ...currentValue,
      XC_API: '127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,::1/128,fc00::/7,fe80::/10',
    };
    const patched = await api.patch(`/api/core/settings/${row!.id}/`, { value: narrowedValue });
    expect(patched.status()).toBe(200);

    // No other key was touched, and network_access["UI"] specifically was
    // never written — confirmed by reading the row back rather than trusting
    // the request body.
    const readBack = await api.json<CoreSetting>(
      await api.get(`/api/core/settings/${row!.id}/`),
      'read back network_access after the XC_API write'
    );
    const readBackValue = readBack.value as Record<string, unknown>;
    expect(
      readBackValue.UI,
      'network_access["UI"] must be absent or unchanged; it is never written'
    ).toEqual(currentValue.UI);
    expect(
      Object.keys(readBackValue).sort(),
      'no key other than XC_API changed'
    ).toEqual(Object.keys(narrowedValue).sort());

    const user = await seed.xcUser();

    // Positive control: the narrowed value denies nothing real. This is D2's
    // argument made executable — if this ever fails, the narrowed CIDR list
    // is wrong, not merely strict.
    const getControl = await request.get(`/get.php${xcQuery(user)}`);
    expect(getControl.status(), 'get.php positive control').toBe(200);
    const xmltvControl = await request.get(`/xmltv.php${xcQuery(user)}`);
    expect(xmltvControl.status(), 'xmltv.php positive control').toBe(200);

    const getBlocked = await request.get(`/get.php${xcQuery(user)}`, { headers: SPOOF_HEADERS });
    expect(getBlocked.status()).toBe(403);
    expect(await getBlocked.json()).toEqual({ error: 'Forbidden' });

    const xmltvBlocked = await request.get(`/xmltv.php${xcQuery(user)}`, {
      headers: SPOOF_HEADERS,
    });
    expect(xmltvBlocked.status()).toBe(403);
    expect(await xmltvBlocked.json()).toEqual({ error: 'Forbidden' });
  }
);

test(
  'a per-user XC_API allowlist refuses that user on all three XC surfaces (D4)',
  { tag: '@contract' },
  async ({ api, seed, request }) => {
    // No header, no global write: network_access_allowed's per-user branch
    // (dispatcharr/utils.py:205-215) is authoritative when non-empty — the
    // user must match one of *those* CIDRs regardless of the global default.
    // 203.0.113.0/24 cannot contain any real client, so this test needs no
    // spoofed header at all. Zero logins spent: the XC surface authenticates
    // from credentials in the URL, so no token is ever minted for this user.
    const user = await seed.xcUser();

    // Positive control before the write.
    const control = await request.get(`/player_api.php${xcQuery(user)}`);
    expect(
      control.status(),
      'positive control: player_api.php with valid credentials, before the per-user write'
    ).toBe(200);
    const controlBody = (await control.json()) as { user_info?: { username?: string } };
    expect(
      controlBody.user_info?.username,
      'positive control must be the real user_info envelope'
    ).toBe(user.username);

    // Read-modify-write on custom_properties: xc_password already lives
    // there, and overwriting it wholesale would break the credentials this
    // test is about to reuse.
    const existing = await api.json<User & { custom_properties: Record<string, unknown> | null }>(
      await api.get(`/api/accounts/users/${user.id}/`),
      'read existing custom_properties before merge'
    );
    const patched = await api.patch(`/api/accounts/users/${user.id}/`, {
      custom_properties: {
        ...(existing.custom_properties ?? {}),
        allowed_networks: { XC_API: TEST_NET_3_CIDR },
      },
    });
    expect(patched.status()).toBe(200);

    // Refusal, not a specific status: this test stays green whichever way
    // test 5's defect (401 instead of a correct 403) is resolved.
    for (const path of [
      `/player_api.php${xcQuery(user)}`,
      `/get.php${xcQuery(user)}`,
      `/xmltv.php${xcQuery(user)}`,
    ]) {
      const res = await request.get(path);
      expect(
        await isXcRefused(res),
        `${path} must refuse a user whose allowed_networks excludes the real client`
      ).toBe(true);
    }
  }
);

// D5, D13a: the known bug. apps/output/views.py:xc_get_user (:374) applies
// network_access_allowed(request, 'XC_API', user) and returns None on
// denial; xc_player_api (:449-454) — like xc_panel_api, xc_get and xc_xmltv
// — maps a None user to 401 {"error": "Unauthorized"}. So a client blocked
// by the PER-USER allowed_networks CIDR is told its password is wrong, not
// that its network is refused. get.php/xmltv.php do have a real 403
// (apps/output/views.py:496-508, :531-543), but only from the separate,
// earlier GLOBAL network_access_allowed(request, 'XC_API') call that passes
// no user — the per-user branch inside xc_get_user can never produce a 403
// on any surface, player_api.php included. Filed as
// https://github.com/D10Scot/Dispatcharr/issues/134.
//
// test.fail() caveat, matching hidden-channel-streamable.spec.ts: it is
// satisfied by ANY failure in the body, guards included — so a broken
// premise (e.g. a wrong xc_password, or the per-user write itself failing)
// would also read as "expected failure" and this test would go green while
// proving nothing. The premise and the positive control are therefore
// asserted first, each with its own message, and only the final assertion
// is inverted. Verified with `--reporter=json` that this pin fails at the
// final expect below, with every assertion above it passing — re-verify the
// same way after any edit here.
test.fail(
  'a network-blocked XC user gets 401 from player_api.php, not the correct 403 (#134)',
  { tag: '@contract' },
  async ({ api, seed, request }) => {
    const user = await seed.xcUser();

    const control = await request.get(`/player_api.php${xcQuery(user)}`);
    expect(control.status(), 'premise: valid credentials must succeed before the write').toBe(
      200
    );
    const controlBody = (await control.json()) as { user_info?: { username?: string } };
    expect(controlBody.user_info?.username, 'premise: must be the real user_info envelope').toBe(
      user.username
    );

    const existing = await api.json<User & { custom_properties: Record<string, unknown> | null }>(
      await api.get(`/api/accounts/users/${user.id}/`),
      'read existing custom_properties before merge'
    );
    const patched = await api.patch(`/api/accounts/users/${user.id}/`, {
      custom_properties: {
        ...(existing.custom_properties ?? {}),
        allowed_networks: { XC_API: TEST_NET_3_CIDR },
      },
    });
    expect(patched.status(), 'premise: the per-user write must itself succeed').toBe(200);

    const res = await request.get(`/player_api.php${xcQuery(user)}`);
    expect(res.status()).toBe(403); // correct behaviour; today it is 401
  }
);
