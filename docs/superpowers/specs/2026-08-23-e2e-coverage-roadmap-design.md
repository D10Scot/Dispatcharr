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

## The seven goals

| | Goal | Depends on | Wave |
|---|---|---|---|
| **G1** | **Harness foundation** — fixtures, auth reuse, API seeding, project topology, CI, `CONTEXT.md`, coverage inventory, exemplars | — | 1 |
| **G2** | **Fake upstream provider** — M3U, XMLTV, real looping TS, fault injection, control API | — | 1 |
| **G3** | **Content sources & ingest** — M3U/EPG refresh, channel creation, auto-sync, groups, Channel Profiles, logos | G1, G2 | 2 |
| **G4** | **Live streaming data path** — byte-level proxy assertions, multi-client sharing, mid-stream switching, all three failover triggers, Stream Profiles, Output Profiles | G1, G2 | 2 |
| **G5** | **Client output surfaces** — M3U/EPG output, HDHomeRun, Xtream (incl. building provider-side emulation), catch-up, authorization matrix | G1, G2 | 2 |
| **G6** | **Frontend surfaces** — Guide, DVR, Users, Settings, Plugins, Stats, Connect, Logos, backups | G1 | 2 |
| **G7** | **Deployment lifecycle** — first-run, upgrade-with-migrations, restart persistence, PUID/PGID, TLS Postgres | G1 | 2 |

```
G1 ─┐
G2 ─┴─→ G3 ─→ ┌ G4
              ├ G5
G1 ──────────→├ G6
G1 ──────────→└ G7
```

Wave 1 is two agents in two worktrees, working disjoint files. Wave 2 is five, dispatched only
once G1 and G2 have merged to `main`.

## Goal notes

**G1** is the contract every other goal codes against. If its fixture API is wrong, five agents
build on sand. It ships exemplar tests specifically so wave 2 has something to copy rather than
five house styles. See `2026-08-23-e2e-harness-foundation-design.md`.

**G2** is a build, not a fixture: its own image, its own control API for flipping fault modes
mid-test, and a deterministic TS pattern (fixed PIDs, a counter burned into the video) so a
client can prove it received contiguous output. Expect it to take longest.

**G2 deliberately excludes** Xtream Codes / VOD / catch-up provider emulation. That moves into
**G5**, which builds it on G2's foundation. This keeps G2 shippable.

**G4** is the highest-value goal and the reason the programme exists. It is also the only goal
whose tests are not browser tests.

**G5** will find real bugs — `output/views.py:593` uses `"channels__user_level": 0` instead of
`__lte`, and `hide_adult_content` is not applied in `live_proxy/views.py`,
`timeshift/views.py` or `hdhr/api_views.py`, so hidden channels are unlistable but still
streamable. See "Finding product bugs" below.

**G7** is not optional. It is where every test that *cannot* share a seeded instance lives —
the `pristine` population. First-run setup, global `CoreSettings` changes, migrations,
PUID/PGID and TLS Postgres all belong here. It also wires up `docker/tests/test-puid-pgid.sh`
and `test-tls-postgres.sh`, which are currently attached to no workflow at all.

## Rules binding every goal

1. **Own worktree, own branch off `main`, own PR.** Per `CLAUDE.md`.
2. **Read the root `CONTEXT.md` before naming anything.** This codebase has three distinct
   things called "profile" (Stream Profile, Output Profile, Channel Profile) and "stream" means
   both a `Stream` model row and the act of streaming. Getting this wrong once, in a fixture
   name, propagates permanently. The glossary lives at the repo root, not under `e2e/` — it is
   product vocabulary, not E2E vocabulary. See `docs/agents/domain.md`.
3. **Update `e2e/COVERAGE.md` in the same PR as the tests.** The inventory is how seven agents
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
