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

## The eight goals

| | Goal | Depends on | Wave |
|---|---|---|---|
| **G1** | **Harness foundation** — fixtures, auth reuse, API seeding, project topology, CI, `CONTEXT.md`, coverage inventory, exemplars | — | 1 |
| **G2** | **Fake upstream provider** — M3U, XMLTV, real looping TS, fault injection, control API | — | 1 |
| **G3** | **Content sources & ingest** — M3U/EPG refresh, channel creation, auto-sync, groups, Channel Profiles, logos | G1, G2 | 2 |
| **G4** | **Live streaming data path** — byte-level proxy assertions, multi-client sharing, mid-stream switching, all three failover triggers, Stream Profiles, Output Profiles | G1, G2 | 2 |
| **G5** | **Client output surfaces** — `/output/m3u`, `/output/epg`, HDHomeRun, the Xtream listing and authentication surface, the authorization matrix | G1, G2 | 2 |
| **G6** | **Frontend surfaces** — Guide, DVR, Users, Settings, Plugins, Stats, Connect, Logos, backups | G1 | 2 |
| **G7** | **Deployment lifecycle** — first-run, upgrade-with-migrations, restart persistence, PUID/PGID, TLS Postgres | G1 | 2 |
| **G8** | **Provider-side XC / VOD / catch-up emulation** — extend the G2 provider to speak Xtream Codes, serve a VOD and series catalogue, and answer catch-up URLs; then the tests that need one: catch-up/timeshift end to end, the XC VOD and series actions against real content, XC-sourced M3U ingest | G2, G5 | 3 |

```
G1 ─┐
G2 ─┴─→ G3 ─→ ┌ G4
              ├ G5 ─→ G8
G1 ──────────→├ G6
G1 ──────────→└ G7
```

Wave 1 is two agents in two worktrees, working disjoint files. Wave 2 is five, dispatched only
once G1 and G2 have merged to `main`. Wave 3 is G8 alone, dispatched once G5 has landed the
server-side surfaces it deepens.

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

## Rules binding every goal

1. **Own worktree, own branch off `main`, own PR.** Per `CLAUDE.md`.
2. **Read the root `CONTEXT.md` before naming anything.** This codebase has three distinct
   things called "profile" (Stream Profile, Output Profile, Channel Profile) and "stream" means
   both a `Stream` model row and the act of streaming. Getting this wrong once, in a fixture
   name, propagates permanently. The glossary lives at the repo root, not under `e2e/` — it is
   product vocabulary, not E2E vocabulary. See `docs/agents/domain.md`.
3. **Update `e2e/COVERAGE.md` in the same PR as the tests.** The inventory is how eight agents
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
