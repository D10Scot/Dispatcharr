# G7 — deployment lifecycle: progress ledger

Worktree: /Users/dion/git/Dispatcharr-g7-lifecycle
Branch: feat/e2e-lifecycle-g7, off origin/main @ d22d3378
Status: BRAINSTORMING (spec not yet written)

## The finding that reshaped this goal

G7 is NOT "more Playwright specs". Two structural facts:

1. `pristine` cannot hold these tests. It is ONE Playwright invocation against
   ONE shared container, so only the FIRST spec in it sees genuine first-run
   state. PUID/PGID and TLS Postgres need differently-configured containers —
   the TLS suite needs several at once, including a separate Celery container —
   and `scripts/e2e_up.sh` hard-codes a single AIO container with fixed env.
2. Two of the four rows are ALREADY WRITTEN. `docker/tests/test-puid-pgid.sh`
   is 20 scenarios, `test-tls-postgres.sh` is 8, both with real assertions.
   Neither filename appears anywhere in `.github/`. Nothing runs them.

So G7 splits into two pieces of different character:
- **A. Wire up the bash suites** — a `lifecycle-tests.yml` running both in
  parallel (~15 min), on push to main + a `docker/**` path filter + manual
  dispatch. Not on every PR: they pull four images and build one. Best
  value-per-effort in the programme right now: 28 existing scenarios become
  CI signal for the price of a workflow file.
- **B. Two genuinely new tests** — restart-persistence and upgrade.

## Decisions

**D-1 (upgrade baseline).** Fork's own GHCR image. User chose this over
upstream 0.28.0 knowing the value is deferred: the fork has added ZERO
migrations of its own (`origin/main` vs `upstream/dev` shows no migration
divergence), so today the test proves little beyond "the container restarts".
It is scaffolding pointed at the right thing from day one, and becomes
meaningful automatically when Phase 1 starts changing models.

**D-2 (baseline resolution).** Use `ghcr.io/d10scot/dispatcharr:latest` — it
IS main's most recent build, i.e. the fork's own upgrade path from a PR's point
of view. The job resolves and LOGS the digest so a failure stays diagnosable,
with a pinned-SHA override env var for reproducible reruns. Better than
pinning a SHA, which would need manual bumping forever.

**D-3 (restart-persistence).** New `lifecycle` Playwright project, `workers:1`,
`retries:0`, owning its container's lifecycle so it may restart it mid-run.
Assert POSTGRES-backed state only — Redis has no persistence in AIO (no
`--dir`/`--dbfilename`/`appendonly` anywhere) and `wait_for_redis.py` runs
`flushdb()` on every boot.

## Facts verified this session

- NO TOKEN SCOPE NEEDED. The fork's GHCR became anonymously readable when the
  repo went public. `docker-build.yml` tags every push to main with the FULL
  40-char SHA (`ghcr.io/<repo>:${{ github.sha }}`). Confirmed resolvable:
  d22d3378…, c188aab6…, a0c99cdd…, plus `:latest`.
- CLAUDE.md IS STALE: it says `docker-build.yml` "has never run and is broken
  by construction". It runs on every push to main and `build-and-push`
  SUCCEEDS. The workflow went red only because `sign-and-attest` hit a GitHub
  attestation-storage billing restriction on a private fork. THE USER HAS
  FIXED THIS by making the repo public. CLAUDE.md needs the correction.
- `release.yml` has never run; no GitHub releases exist; tags stop at v0.29.0
  (inherited from upstream, the fork has not cut its own release).
- Upstream publishes anonymously-pullable version tags (0.27.0, 0.28.0,
  0.29.0, latest) — the rejected alternative baseline, recorded in case D-1 is
  revisited.
- 130 migrations total (channels 38, epg 27, core 27, m3u 19, accounts 6,
  vod 5, connect 3, plugins 3, hdhr 1, dashboard 1, backups 0). No migration
  test exists anywhere in the repo.
- Persistence: one `/data` volume holds db/, jwt, backups/, logos/, uploads/,
  plugins/, scripts/. `MEDIA_ROOT` resolves under `/app` — NOT volume-backed.
- The real entrypoint is `docker/entrypoint.sh`; `entrypoint.aio.sh` is dead
  and has no PUID handling at all, confirming CLAUDE.md on that point.
