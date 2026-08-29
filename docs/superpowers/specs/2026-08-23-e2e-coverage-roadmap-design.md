# E2E Coverage Roadmap

**Date:** 2026-08-23
**Status:** Approved
**Scope:** Programme-level decomposition. Each goal below gets its own spec, plan, worktree, branch and PR.

## Why this exists

Dispatcharr has 1,787 backend tests and 6,128 frontend tests, and **nothing tested end to
end** until `e1098206` added a single Playwright spec. Coverage is inversely correlated with
criticality: `live_proxy` 38.5%, `vod_proxy` 35.6%, `hls_proxy` 0%, against `timeshift` 78.7%.
No test spawns a subprocess, so ffmpeg lifecycle and stderr parsing run only against
hand-written strings. Exactly one test file talks to a real Redis, so the ownership lease and
the ring buffer never meet real Redis semantics.

E2E tests are not a nicer unit test. They are the only place these things can be observed at
all — and the relay extraction (Phase 1 of this fork's stated direction) needs that safety net
in place *before* it moves the boundary.

## The ten goals

| | Goal | Depends on | Wave |
|---|---|---|---|
| **G1** | **Harness foundation** — fixtures, auth reuse, API seeding, project topology, CI, `CONTEXT.md`, coverage inventory, exemplars | — | 1 |
| **G2** | **Fake upstream provider** — M3U, XMLTV, real looping TS, fault injection, control API | — | 1 |
| **G3** | **Content sources & ingest** — M3U/EPG refresh, channel creation, auto-sync, groups, Channel Profiles, logos | G1, G2 | 2 |
| **G4** | **Live streaming data path** — byte-level proxy assertions, multi-client sharing, mid-stream switching, all three failover triggers, Stream Profiles, Output Profiles | G1, G2 | 2 |
| **G5** | **Client output surfaces** — `/output/m3u`, `/output/epg`, HDHomeRun, the Xtream listing and authentication surface, the authorization matrix | G1, G2 | 2 |
| **G6** | **Frontend surfaces** — Guide, DVR, Users, Settings, Plugins, Stats, Connect, Logos, backups | G1 | 2 |
| **G7** | **Deployment lifecycle** — first-run, upgrade-with-migrations, restart persistence, PUID/PGID, TLS Postgres | G1 | 2 |
| **G8** | **Provider-side XC / VOD / catch-up emulation** — extend the G2 provider to speak Xtream Codes, serve a VOD and series catalogue, and answer catch-up URLs in the shapes `build_timeshift_candidate_urls` tries. Ships **plumbing proofs only**; the tests that need the provider are G9 and G10 | G2, G5 | 3 |
| **G9** | **VOD and series end to end** — catalogue ingest into `Movie`/`Series`/`Episode`, the XC VOD and series actions against real content, and the `vod_proxy` streaming path including Range and seek | G8 | 4 |
| **G10** | **Catch-up / timeshift end to end** — both provider URL layouts, the candidate cascade, redirect and proxy modes, and the ingest fields catch-up depends on | G8 | 4 |

```
G1 ─┐
G2 ─┴─→ G3 ─→ ┌ G4
              ├ G5 ─→ G8 ─→ ┌ G9
G1 ──────────→├ G6          └ G10
G1 ──────────→└ G7
```

Wave 1 is two agents in two worktrees, working disjoint files. Wave 2 is five, dispatched only
once G1 and G2 have merged to `main`. Wave 3 is G8 alone, dispatched once G5 has landed the
server-side surfaces it deepens. Wave 4 is G9 and G10, dispatched once G8's provider build has
landed; they are disjoint in subject and can run in parallel.

## Goal notes

**G1** is the contract every other goal codes against. If its fixture API is wrong, five agents
build on sand. It ships exemplar tests specifically so wave 2 has something to copy rather than
five house styles. See `2026-08-23-e2e-harness-foundation-design.md`.

**G2** is a build, not a fixture: its own image, its own control API for flipping fault modes
mid-test, and a deterministic TS pattern (fixed PIDs, a counter burned into the video) so a
client can prove it received contiguous output. Expect it to take longest.

**G2 deliberately excludes** Xtream Codes / VOD / catch-up provider emulation. That moves into
**G8**, which builds it on G2's foundation. This keeps G2 shippable.

**G4** is the highest-value goal and the reason the programme exists. It is also the only goal
whose tests are not browser tests.

**G5 was originally given both a test goal and a build** — the server-side output surfaces *and*
the provider emulation G2 had deliberately excluded. Those are different kinds of work, and only
one row of G5's inventory actually needed the build: `catchup_proxy` in `apps/timeshift/views.py`
constructs its upstream URL from the account's Xtream catch-up template
(`get_transformed_credentials` → `build_timeshift_candidate_urls`), so it has nothing to point at
until the fake provider speaks XC. Everything else G5 covers is Dispatcharr generating output
from its own database and needs no upstream at all.

So the two were split. G2 was the programme's longest goal *because* it was a build; folding a
second build into G5 would have repeated that and blocked a dozen cheap server-side tests behind
it. **G5 is now server-side output surfaces only, and G8 owns the provider emulation together
with every test that depends on it.** G8 is defined here and specced when it is scheduled — G5's
spec is responsible for drawing the line clearly enough that nothing falls between them.

**G5** will find real bugs. Three, verified against the code rather than inferred:
`xc_get_live_categories` in `apps/output/views.py` filters `"channels__user_level": 0` — an exact
match — while the same function uses `channels__user_level__lte` immediately above and below it;
`stream_xc` in `apps/proxy/live_proxy/views.py` applies `user_level` and Channel Profile
membership but omits the `is_adult` filter every listing path applies for the same user, so a
channel a user cannot list is still streamable; and the HDHomeRun endpoints are `AllowAny` with
no principal at all, so `apps/hdhr/api_views.py` cannot apply *any* per-user filter — there is
not one occurrence of `hide_adult_content` anywhere under `apps/hdhr/`. See "Finding product
bugs" below.

**G8** is a build first and a test goal second, exactly as G2 was. Expect it to be long, and
expect its spec to say what the fake provider must serve — an XC `player_api.php`, a VOD and
series catalogue, and catch-up URLs in the shapes `build_timeshift_candidate_urls` tries —
before it says what to assert.

**G7** is not optional. It is where every test that *cannot* share the ordinary `seeded`
instance lives — but that is not one population, and G7 should not build it as one. First-run
setup and global `CoreSettings` changes are the `pristine` population: a fresh instance with no
superuser, run with `playwright.config.ts`'s existing `pristine` project. Upgrade-with-migrations,
restart persistence, PUID/PGID and TLS Postgres are different again from each other — a previous
image, different launch env, and different services and volume history, respectively — and don't
share a container with `pristine` or with each other. G7 is scenario-specific jobs, each standing
up the container it needs; only the first-run case is `pristine`. It also wires up
`docker/tests/test-puid-pgid.sh` and `test-tls-postgres.sh`, which are currently attached to no
workflow at all.

**G8 was itself split**, for the same reason G5 was. As first defined it carried the provider
build *and* every test that needs it — the pattern that made G5 unshippable. G2 is the evidence
that a build is shippable when it stops at **plumbing proofs**: enough Dispatcharr-facing tests
to prove the wiring works, and not one test of the product's behaviour. So **G8 is now the build
alone**, and the two consumer goals below own the coverage. Nothing about the split changes what
gets tested; it changes which PR tests it. See
`2026-08-29-e2e-xc-provider-emulation-design.md`.

**G9** owns everything VOD. Catalogue ingest is the first half: `refresh_vod_content` walks
`get_vod_categories` → `get_vod_streams` → `get_series_categories` → `get_series`, and the
per-series episode fetch (`get_series_info`) is a *separate, on-demand* call reached through
`GET /api/vod/series/<pk>/provider-info/`, not part of the refresh. Category gating
(`M3UVODCategoryRelation.enabled`, and `auto_enable_new_groups_vod`/`_series`), the
`Uncategorized` fallback, and the `get_vod_info` advanced-data path all belong here. The second
half is the `vod_proxy` streaming path, which is a different architecture from live streaming —
`iter_content` passthrough, one upstream per session, session id in the URL path, and Range/seek
driven by the provider's `Content-Length`. G9 also deepens the four XC VOD/series actions G5
could only assert as well-formed-and-empty, and the two (`get_vod_info`, `get_series_info`) that
G5 could only assert as `404`. **G9 must not touch the four Lua scripts in `vod_proxy`'s stream
counter**: they bypass the metadata lock deliberately, as a real bug fix, pinned by
`apps/proxy/vod_proxy/tests/test_vod_lock_contention.py`.

**G10** owns everything catch-up. Three client entry points reach the same code
(`/proxy/catchup/<uuid>`, the root `timeshift/<user>/<pass>/<dur>/<start>/<id>.ts`, and
`streaming/timeshift.php`), and which one was used decides the provider URL layout in redirect
mode (`client_timeshift_url_layout`). Proxy mode does not use that choice at all: it walks
`build_timeshift_candidate_urls`'s seven ordered candidates — three PATH timestamp shapes, then
four QUERY shapes — until one answers with MPEG-TS, and caches the winning index per account.
That cascade is the part most likely to be wrong and the part nothing observes today. G10 also
owns the XC live-ingest fields catch-up depends on (`tv_archive`/`tv_archive_duration` →
`Stream.is_catchup`/`catchup_days` → `rollup_channel_catchup_fields` → `Channel.is_catchup`, and
`server_info.timezone` on the account profile, which drives `convert_timestamp_to_provider_tz`),
because those are its preconditions and it is the goal that breaks when they are wrong. One
inherited decision lands here too: the generated M3U emits no `catchup=` attribute, so an
M3U-only client can never discover catch-up — G10 decides whether that is a defect to file.
**G10 cannot prove Dispatcharr seeks to the right moment**: G8's archive is not time-addressable
(see its Non-goals). G10 proves the right moment was *asked for*, and says so in every row.

## Rules binding every goal

1. **Own worktree, own branch off `main`, own PR.** Per `CLAUDE.md`.
2. **Read the root `CONTEXT.md` before naming anything.** This codebase has three distinct
   things called "profile" (Stream Profile, Output Profile, Channel Profile) and "stream" means
   both a `Stream` model row and the act of streaming. Getting this wrong once, in a fixture
   name, propagates permanently. The glossary lives at the repo root, not under `e2e/` — it is
   product vocabulary, not E2E vocabulary. See `docs/agents/domain.md`.
3. **Update `e2e/COVERAGE.md` in the same PR as the tests.** The inventory is how ten agents
   avoid duplicating each other and avoid leaving silent gaps.
4. **Never assume the instance is empty.** No assertion on a global count or an unfiltered list.
5. **Test agents file product bugs; they do not fix them.** See below.

## Finding product bugs

Wave 2 will hit the defects catalogued in `CLAUDE.md`. The policy:

- Write the test to assert **correct** behaviour.
- Mark it `test.fail()` with a comment naming the defect and its location.
- Open an issue **on the fork**: `gh issue create --repo D10Scot/Dispatcharr …`. The explicit
  `--repo` flag is mandatory — without it `gh` resolves to the upstream public project and
  files this fork's internal findings on someone else's tracker. See
  `docs/agents/issue-tracker.md`.
- Do not patch the product in a test PR.

`test.fail()` is the honest encoding: the test runs, the bug is recorded as a
red-that-should-be-red, and when someone fixes the product the suite goes red the *other* way
and tells you. Skipping loses that information. Letting a test agent patch `live_proxy`
mid-flight is how this programme turns into an unplanned refactor.

## Non-goals

- Rewriting or reorganising the existing backend/frontend unit suites.
- Fixing the two path-routing defects in `labels_for_changed_paths()`. Separate, known work.
- A repo-wide Dockerfile pinning sweep. `docker/Dockerfile:8,24` and `docker/DispatcharrBase:7,98`
  remain floating; leave clean anything you touch, but do not go looking.
- Performance or load testing. This programme establishes correctness only.
