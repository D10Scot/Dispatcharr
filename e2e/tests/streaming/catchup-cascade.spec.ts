import { test, expect } from '../../fixtures';
import { catchupTimestamp, seedCatchupChannel } from './helpers';

/**
 * Drives `/proxy/catchup/<Channel.uuid>` — the **native** catch-up surface
 * (spec inventory row 5), not the root `/timeshift/...` XC route
 * `catchup-path-layout.spec.ts` already covers. Both routes end up in the
 * same shared `_serve_catchup` (apps/timeshift/views.py), which is what
 * calls `build_timeshift_candidate_urls` and runs the seven-candidate
 * cascade under test here — so the cascade behaviour itself does not differ
 * by entry point, and driving it from the native surface is what proves
 * that surface is wired end to end rather than leaving it completely
 * unexercised by this goal.
 *
 * Authenticated with the admin JWT `api` fixture already holds, not an XC
 * end-user: the native route's `authentication_classes` are
 * JWTAuthentication/ApiKeyAuthentication/QueryParamJWTAuthentication, not
 * `_authenticate_user`'s XC username/password, so no `seed.xcUser()`
 * stand-in is needed for this proof at all.
 */
test('the candidate cascade falls through to the QUERY layout when PATH 404s', async ({
  upstream,
  seed,
  api,
  waitFor,
  streamClient,
}) => {
  // A FRESH account, deliberately: _set_cached_format_index caches the
  // winning candidate index per account in the Django cache, and a reused
  // account would start the walk at whatever last worked rather than at
  // candidate 0.
  const { scenario, channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });

  // No clearFault / teardown needed: FaultStore keys every armed fault by
  // scenario id (e2e-upstream/src/faults.ts), and `scenario` above is a
  // fresh one this test alone addresses — no other spec or worker can ever
  // reach it, so the fault cannot leak past this test.
  await upstream.fault(scenario, 'catchup-layout-404', { layout: 'path' });

  const requestInstant = new Date(Date.now() - 2 * 60 * 60 * 1000);
  const start = catchupTimestamp(requestInstant);
  const token = await api.freshAccessToken();

  // ?start=&duration= is the native route's own direct-auth shape
  // (apps/timeshift/views.py's catchup_proxy docstring); duration goes
  // through the identical client_duration_to_window() as the PATH route's
  // URL segment, so the same +5-minute buffer assertion below is valid here
  // too. Like the PATH route, a session-less first request gets a
  // same-origin 301 minting a session_id, which streamClient.open follows
  // automatically.
  await streamClient.open(
    `/proxy/catchup/${channel.uuid}?start=${encodeURIComponent(start)}&duration=60`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  expect((await streamClient.readPackets(20))[0]).toBe(0x47);
  await streamClient.close();

  const log = await upstream.log(scenario);
  const attempts = log.filter(
    (entry) => entry.kind === 'request' && entry.path?.includes('timeshift')
  );

  // build_timeshift_candidate_urls emits three PATH shapes, then four QUERY
  // shapes (apps/timeshift/helpers.py:466-498). With PATH blocked, a walk
  // that reaches QUERY at all could still be wrong in three ways a bare
  // count can't catch: the three PATH attempts could carry the *same*
  // timestamp shape instead of three distinct ones (a shape-derivation
  // regression would still 404 three times and fall through), QUERY could
  // be tried before PATH is exhausted, or the wrong QUERY candidate could
  // win. The assertions below pin candidate identity and order — not shape
  // *correctness*, which COVERAGE.md:63/85 assigns to G10.
  const pathAttempts = attempts.filter((e) => e.path!.includes('/timeshift/'));
  const queryAttempts = attempts.filter((e) => e.path!.includes('timeshift.php'));

  expect(pathAttempts).toHaveLength(3);
  expect(pathAttempts.every((e) => e.status === 404)).toBe(true);
  expect(queryAttempts.length).toBeGreaterThan(0);
  expect(queryAttempts[0].status).toBe(200);

  // Order: the three PATH attempts are the first three "timeshift" requests
  // logged, and the winning QUERY attempt is the fourth. `attempts` is
  // filtered but order-preserving (ScenarioLog.record appends;
  // e2e-upstream/src/log.ts:30-35), so this is a direct check on arrival
  // order, not an inference from the split-out arrays.
  expect(attempts.slice(0, 3)).toEqual(pathAttempts);
  expect(attempts[3]).toEqual(queryAttempts[0]);

  // And the cascade STOPS at the winner. Without this, a cascade that kept
  // walking candidates 4-6 after its 200, or that retried the whole list,
  // would be invisible: every assertion above is satisfied by a prefix of
  // the log. Four is the whole of it — three PATH 404s then one QUERY 200.
  expect(attempts).toHaveLength(4);

  // Identity: each PATH attempt carries a distinct strftime shape, in the
  // exact order build_timeshift_candidate_urls emits them — colon-dash,
  // underscore, then colon-seconds — and the winning QUERY attempt is
  // specifically candidate index 3 (format_a + underscore_ts), the first
  // QUERY shape in that order. Derived from the same `requestInstant` the
  // request itself used, not re-parsed from the response, so this fails if
  // the product ever reorders or collapses the candidate list.
  const pad = (n: number): string => String(n).padStart(2, '0');
  const y = requestInstant.getUTCFullYear();
  const mo = pad(requestInstant.getUTCMonth() + 1);
  const d = pad(requestInstant.getUTCDate());
  const h = pad(requestInstant.getUTCHours());
  const mi = pad(requestInstant.getUTCMinutes());
  const colonDashTs = start; // %Y-%m-%d:%H-%M — catchupTimestamp already emits this shape
  const underscoreTs = `${y}-${mo}-${d}_${h}-${mi}`; // %Y-%m-%d_%H-%M
  // Seconds are always "00" here, not requestInstant's actual seconds:
  // `start` carries no seconds (catchupTimestamp's colon-dash shape omits
  // them), and normalize_catchup_timestamp_input defaults an absent second
  // to "00" (apps/timeshift/helpers.py:94) before this shape is derived.
  const colonSecondsTs = `${y}-${mo}-${d}:${h}:${mi}:00`; // %Y-%m-%d:%H:%M:%S

  expect(pathAttempts[0].path).toContain(`/${colonDashTs}/`);
  expect(pathAttempts[1].path).toContain(`/${underscoreTs}/`);
  expect(pathAttempts[2].path).toContain(`/${colonSecondsTs}/`);

  expect(queryAttempts[0].path).toContain(`username=${scenario.username}`);
  expect(queryAttempts[0].path).toContain('duration=65');
  expect(queryAttempts[0].path).toContain(`start=${underscoreTs}`);
});
