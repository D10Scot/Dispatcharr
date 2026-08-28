# G7 — Deployment Lifecycle

**Date:** 2026-08-28
**Status:** Approved, ready for implementation planning
**Wave:** 2 (G1 landed at `a0c99cdd`, G2 at `c188aab6`; G7 branches from `main` at `d22d3378`)
**Parent:** `2026-08-23-e2e-coverage-roadmap-design.md`
**Sibling in flight:** G4 (`2026-08-28-e2e-streaming-data-path-design.md`) — disjoint files

## Goal

Prove that a Dispatcharr container survives the four things that actually happen to a deployed
instance: it gets restarted, it gets upgraded onto an existing data volume, it gets launched with
somebody else's PUID/PGID, and it gets pointed at a PostgreSQL that insists on TLS.

G7 is not "more Playwright specs". Two structural facts reshape it, and both are load-bearing for
everything below.

**The `pristine` project cannot hold these tests.** It is one Playwright invocation against one
shared container, so only the *first* spec in it sees genuine first-run state — which is why it
holds exactly one spec today. PUID/PGID and TLS need differently *configured* containers, not
merely fresh ones: the TLS suite stands up several at once, including a separate Celery container
on a dedicated network with generated certificates. `scripts/e2e_up.sh` hard-codes one AIO
container with fixed env. `e2e/README.md` already says this in as many words.

**Two of the four rows are already written, in bash, and nothing runs them.**
`docker/tests/test-puid-pgid.sh` is 1,517 lines and 20 scenarios;
`docker/tests/test-tls-postgres.sh` is 892 lines and 8. Neither filename appears anywhere under
`.github/`. `CLAUDE.md` calls them "the repo's best integration tests — wired into no workflow".

So the highest-value work in G7 is not writing tests. It is wiring up 28 existing scenarios for
the price of a workflow file, and then writing the two rows that genuinely do not exist yet.

## Current state

`e2e/COVERAGE.md` carries four G7 rows, all `todo`: upgrade-from-previous-release (migrations),
restart preserves channels and settings, PUID/PGID honoured, TLS Postgres connection. The
first-run row that the roadmap's G7 paragraph also mentions is already `done` under G1
(`e2e/tests/pristine/first-run-setup-and-login.spec.ts`), so G7's scope is exactly these four.

There is **no migration test anywhere in the repository** — not a unit test, not a CI job, not a
`makemigrations --check` outside the local `PostToolUse` hook. There are 130 migrations. The fork
has added none of its own.

## Verified facts this design rests on

Cited by symbol or filename, never by line number — line numbers in this repo drift, and an
earlier spec in this series shipped four wrong ones. Anything marked **unverified** is an
inference and is flagged as one.

| Fact | Source | Consequence |
|---|---|---|
| Both bash suites take `--skip-build` and then use a hard-coded image tag: `dispatcharr:puid-test` and `dispatcharr:tls-test` | `docker/tests/test-puid-pgid.sh`, `test-tls-postgres.sh`, `IMAGE_NAME` | CI can build once and `docker tag` into both names. **No suite edit is needed to make them share one image.** See D6 |
| Without `--skip-build` each suite runs `docker build -f docker/Dockerfile .` itself | both suites, "Main" section | Left alone, two jobs would each pay the AIO build that `e2e-tests.yml` budgets 45 minutes for |
| The suites pull, between them, `ghcr.io/dispatcharr/dispatcharr:latest` (upstream), `postgres:16`, `postgres:17`, `redis:latest`, plus `alpine/openssl` for cert generation | `RELEASE_IMAGE` and the `docker pull` block in `test-puid-pgid.sh`; `generate_test_certs`, `start_tls_postgres`, `start_tls_redis` in `test-tls-postgres.sh` | Four-plus image pulls and one build per run. This is why the workflow is not on every PR. See D4 |
| Both suites exit non-zero on failure — `exit 1` in the puid suite's summary, a bare `[ $FAIL -eq 0 ]` as the last statement in the TLS suite | both suites, "Summary" | A plain `run:` step reports correctly **provided the pipeline does not swallow the status**. See D7 |
| Both suites use `set -uo pipefail` — deliberately **without** `-e` — and accumulate failures rather than aborting | both suites, configuration block | One broken scenario does not hide the other nineteen. Good for signal, and it means the whole suite always runs to completion |
| Every assertion in both suites is `docker logs \| grep`, `docker exec stat`, or `docker exec psql` | `check_log_contains`, `check_ownership`, `check_pg_accessible` in both suites | A bare red X carries no information. Diagnosability has to be designed in. See D7 |
| Both suites clean up their containers and volumes on failure by default; `--keep-on-fail` suppresses that | `cleanup_scenario` in both suites | Post-hoc `docker logs` in a workflow step finds nothing. The suites' own `dump_logs_on_fail` (tail -60 / tail -30) is the only container output that survives |
| **`--keep-on-fail` is actively harmful in CI for the TLS suite.** All eight of its scenarios reuse the same container names (`tls_test_app`, `tls_test_pg`, `tls_test_redis`), and its keep-branch is per-scenario | `test-tls-postgres.sh`, `cleanup_scenario`, and the `local name=` lines in every `test_modular_*` | Keeping one failing scenario's containers makes the next `docker run --name` collide, turning one real failure into seven fabricated ones. See D7 |
| The puid suite's keep-branch tests `${#ERRORS[@]} -gt 0` — a run-global counter | `test-puid-pgid.sh`, `cleanup_scenario` | After the first failure it stops cleaning up *everything*, accumulating up to 20 containers and PostgreSQL data volumes on a runner with single-digit gigabytes free. Same conclusion as the row above |
| Both suites accept a single positional scenario name to run one scenario | both suites, argument parsing and the `SINGLE_SCENARIO` guard in the runner loop | Local reproduction of a CI failure is one argument. Worth putting in the failure message |
| Every log string the suites grep for exists in the product today | `check_log_contains` call sites vs. `dispatcharr/settings.py` (`PostgreSQL TLS: enabled`, `Redis TLS: enabled`), `docker/init/00-fix-pg-ssl-key.sh` (`Fixed PostgreSQL client key`), `docker/init/02-postgres.sh` (`Migrating PostgreSQL data ownership`, `Application role configured`, `Old cluster install user:`, `Upgrade complete`), `docker/entrypoint.celery.sh` (`Migrations complete, starting Celery`) | The suites are not asserting against strings that have since been renamed. Spot-checked this session; that they actually pass is still untested — see Risks |
| `test-puid-pgid.sh`'s `RELEASE_IMAGE` is **upstream's** `ghcr.io/dispatcharr/dispatcharr:latest`, not the fork's | `test-puid-pgid.sh`, `RELEASE_IMAGE` | Correct as written: those scenarios simulate a user upgrading from the published pre-PUID image. Changing it to the fork changes what the test tests. See D2 |
| `test-puid-pgid.sh` assigns `BASE_IMAGE` and never reads it | `test-puid-pgid.sh`, configuration block | A one-line dead variable. **Leave it.** See D2 |
| Two scenarios run `apt update && apt install -y postgresql-$CURRENT_VERSION` *inside the container at runtime* | `docker/init/02-postgres.sh`, the `pg_upgrade` branch, reached by `pg_major_upgrade` and `pg_upgrade_post_puid` | Those two scenarios depend on a live apt repository during the test. `f3fd4dd2` exists because Launchpad's API is flaky. This is G7's largest flake vector |
| Two scenarios raise `wait_for_ready` to 300s for that reason | `test-puid-pgid.sh`, `test_pg_major_upgrade` and `test_pg_upgrade_post_puid` | The job timeout must have real headroom over the suites' documented "10-15 minutes" |
| `.github/workflows/e2e-tests.yml` gives **each matrix project its own runner and its own container**, via one `build` job that saves both images into a single artifact | `e2e-tests.yml`, jobs `build` and `test` | Adding a Playwright project is adding a matrix entry, not inventing a mechanism. `e2e/README.md` states the obligation explicitly |
| `scripts/e2e_up.sh` honours `DISPATCHARR_E2E_IMAGE`, `_CONTAINER`, `_VOLUME`, `_PORT`, `_NETWORK` and `_READY_ATTEMPTS`, and builds the AIO image only when `docker image inspect` misses | `scripts/e2e_up.sh` | A pre-`docker pull`ed baseline image is used as-is. But an image reference it has never seen **is built from `docker/Dockerfile` and mis-tagged**, so the pull must happen first |
| `scripts/e2e_up.sh` has **no mode that replaces the container while keeping the volume**. `--stop` keeps the container (and therefore its original image snapshot); `--reset` and `--down` destroy the volume | `scripts/e2e_up.sh`, the `case` block and `destroy()` | An upgrade is exactly "new container, same volume". See D9 |
| `destroy()` also removes the shared network and the `e2e-upstream` container | `scripts/e2e_up.sh`, `destroy()` | `--reset`/`--down` from a lifecycle spec would tear down another project's provider. Safe only because `lifecycle` runs alone. See D8 |
| The app-container reuse branches key on **container name only**, never on image id — unlike the provider, which is recreated when its image id moves | `scripts/e2e_up.sh`, the `UPSTREAM_IMAGE_ID` comparison vs. the `$NAME` branches | Pointing `DISPATCHARR_E2E_IMAGE` at a different image and re-running the script silently keeps serving the old one. This is the trap D9 closes |
| `docker/entrypoint.sh` runs `manage.py migrate --noinput` on **every** boot, as `su - $POSTGRES_USER`, after PostgreSQL is up and before uWSGI starts | `docker/entrypoint.sh` | The upgrade path under test is "start the new image on the old volume". There is no separate migrate step to drive |
| `uwsgi started with PID` is printed after migrate and collectstatic, and is what both bash suites use as their readiness marker | `docker/entrypoint.sh`; `wait_for_ready` in both suites | Readiness implies migrations completed. `check_migrations_done` says so in its own comment |
| `GET /api/accounts/initialize-superuser/` returns 200 whether or not an admin exists — it short-circuits to `superuser_exists: true` before any method dispatch; only `POST` is IP-gated | `apps/accounts/api_views.py`, `initialize_superuser` | The readiness probe `scripts/e2e_up.sh` already polls is valid for the *second*, already-bootstrapped boot in the upgrade test. Nothing new is needed |
| The Django secret key is generated once into `/data/jwt` and reused on every subsequent boot | `docker/entrypoint.sh`, `SECRET_FILE` | **A JWT minted before a restart or an upgrade still authenticates afterwards.** That is a cheap, specific assertion that `/data` really persisted — a regenerated `DJANGO_SECRET_KEY` invalidates every token. See D11 |
| `/data` holds `db/`, `jwt`, `backups/`, `logos/`, `cache/`, `recordings/`, `uploads/`, `m3us/`, `epgs/`, `plugins/`, `models/`, `scripts/` | `docker/init/03-init-dispatcharr.sh`, `DATA_DIRS`; `docker/entrypoint.sh`, `SECRET_FILE` | One volume carries everything durable |
| `MEDIA_ROOT = BASE_DIR / "media"` resolves under `/app` and is **not** volume-backed; `03-init-dispatcharr.sh` creates it as an `APP_DIRS` entry "on the image layer" | `dispatcharr/settings.py`; `docker/init/03-init-dispatcharr.sh` | Its known uses are caches (`cached_m3u`, `cached_epg`, `comskip`). Whether an uploaded logo's *bytes* survive a container recreate is **unverified** — `upload_to='logos/'` in `apps/channels/migrations/0001_initial.py` is relative to `MEDIA_ROOT`, while `LOGOS_DIR` defaults to `/data/logos`. See Non-goals |
| Redis has no persistence configured in AIO, and `scripts/wait_for_redis.py` calls `flushdb()` on every boot | `CLAUDE.md`, State; `scripts/wait_for_redis.py` | **Nothing Redis-backed may be asserted to survive a restart.** See D11 |
| `docker/init/02-postgres.sh` writes an ownership sentinel to `/data/db/.owner_puid` and, on a PG major mismatch, runs a real `pg_upgrade` with a `db_backup_<ver>_*` directory left behind | `docker/init/02-postgres.sh` | Exactly the strings and paths `test-puid-pgid.sh` already asserts on. Piece A needs a runner, not new assertions |
| The fork's GHCR is anonymously readable, and `:latest` plus full-40-char-SHA tags resolve | verified this session against `ghcr.io/v2/d10scot/dispatcharr` with an anonymous pull token: `manifests/latest` → 200, and `tags/list` returns `latest`, `base`, full commit SHAs and `0.29.0-<timestamp>` tags | The upgrade baseline needs no registry credentials and therefore no token scope in any workflow |
| **Two workflows push `:latest` on a push to main**: `docker-build.yml` (tags `latest` + `${{ github.sha }}`, no `TIMESTAMP` build-arg) and `ci.yml` (tags `latest` + `<version>-<timestamp>`, passing `TIMESTAMP`) | `.github/workflows/docker-build.yml`, `.github/workflows/ci.yml` | `:latest` can be *the commit under test*, which would make the upgrade test upgrade from itself and pass vacuously. Only `docker-build.yml` publishes the full-SHA tag. See D10 |
| `version.py` ships `__timestamp__ = None` and the Dockerfile only overwrites it when `TIMESTAMP` is passed, which `docker-build.yml` does not | `version.py`, `docker/Dockerfile`, `docker-build.yml` | **`GET /api/core/version/` cannot discriminate the baseline image from the local build.** Both may report `0.29.0` with a null timestamp. The upgrade test must prove the swap with `docker inspect`, not with the product |
| `CLAUDE.md` is **stale** where it says `docker-build.yml` "has never run and is broken by construction" | the workflow runs on every push to main and `build-and-push` succeeds; it went red only on `sign-and-attest` hitting an attestation-storage billing restriction on a private fork, which the user has since fixed by making the repo public | A correction to surface, not to make here. See Non-goals |
| `bootstrap` probes `GET /api/accounts/initialize-superuser/`, POSTs `ADMIN` if no superuser exists (behind `assertMayCreateSuperuser`), then logs in through `loginWithThrottleBackoff`, then persists auth files and pre-warms the `IntervalSchedule` row | `e2e/setup/bootstrap.setup.ts` | The first two steps are exactly what a lifecycle spec needs on a freshly-created instance; the last two are not. See D13 |
| `assertMayCreateSuperuser` gates on hostname, not on port or container identity, and admits any loopback target with no opt-in | `e2e/setup/superuser-guard.ts`, `isLoopbackHost` | A lifecycle-owned container on any loopback port bootstraps with no extra configuration |
| `ApiClient`'s constructor takes an optional explicit `TokenPair`, and `Seeder`'s takes an `ApiClient` | `e2e/fixtures/api.ts`, `e2e/fixtures/seed.ts` | A spec that provisions its own admin builds both directly, without `playwright/.auth/` and without the `api`/`seed` fixtures |
| `POST /api/accounts/token/` is throttled at 3/minute per client IP, shared across the whole run | `e2e/README.md`; `dispatcharr/settings.py`, `DEFAULT_THROTTLE_RATES` | Two lifecycle specs on two fresh instances spend two logins. Under the cap, but `loginWithThrottleBackoff` is mandatory, not optional |
| `CoreSettings` rows are grouped JSON blobs keyed by the `*_SETTINGS_KEY` constants (`system_settings`, `stream_settings`, …); the viewset is registered as `settings` | `core/models.py`, `core/api_urls.py` | `/api/core/settings/` is the route. A settings change is **global**, which `e2e/README.md` flags as a `pristine`-only move on a shared instance. Reinforces D8 |
| The zizmor hook blocks on **every** finding in an edited workflow file, and the workflows are currently at **zero** findings | `CLAUDE.md`, Test hooks; `.github/workflows/actions-lint.yml` | Both workflow files G7 touches must be clean first time. Expect the hook to block, not to warn |

## Decisions

| # | Decision | Rationale — and what was rejected |
|---|---|---|
| D1 | **G7 splits into two pieces of different character.** Piece A wires up the two existing bash suites; Piece B writes the two rows that do not exist. They share no files and can land in either order | They are different work with different risk. Piece A is a workflow file over known-good, never-executed code — its whole value is that the code is *unchanged*. Piece B is new test code in the Playwright harness. Rejected: one undifferentiated "G7 implementation", which is how the bash suites end up quietly rewritten to fit a test-authoring habit, and how "did the wiring work" drowns out "is the new test good" in review |
| D2 | **The bash suites are wired up entirely unmodified.** Not one line | They are known-good and have never run. Changing them in the same PR that first executes them destroys the only signal the PR carries: a red run would be indistinguishable between "the suite found a real bug" and "the edit broke the suite". Everything CI needs — `--skip-build`, a single positional scenario name, correct exit codes — is already there, and the workflow adapts to *them*. Two live temptations, both to be resisted: `RELEASE_IMAGE` pointing at upstream is *correct* (those scenarios simulate upgrading from the published pre-PUID image), and the unused `BASE_IMAGE` variable is a cosmetic not worth spending this PR's signal on. If a suite turns out to be genuinely broken, **fix it in a follow-up PR that says so**, and record the first run's raw output in this one |
| D3 | **Piece A gets its own workflow, `.github/workflows/lifecycle-tests.yml`. Piece B rides `e2e-tests.yml`'s existing matrix as a fourth project** | The two pieces have incompatible economics. Piece A pulls four-plus images and needs an AIO build of its own; Piece B is a Playwright project that reuses the artifact `e2e-tests.yml` already builds, runs in parallel with the other three, and therefore adds ~0 to wall clock. Putting Piece B in the new workflow would pay a second 45-minute build for it *and* leave migrations unguarded on PRs; putting Piece A in `e2e-tests.yml` would put a ~60-minute job on every PR. `e2e/README.md` already obliges a new project to be added to that matrix. Rejected: both jobs in `lifecycle-tests.yml` (considered; the second AIO build is the deciding cost) |
| D4 | **`lifecycle-tests.yml` triggers on a path-filtered `push` to `main`, a weekly `schedule`, and `workflow_dispatch`. No `pull_request` trigger. `cancel-in-progress: false`** | The trigger shape is the settled decision from the working ledger, kept as settled. Path filter: `docker/**`, `**/migrations/**`, `scripts/e2e_up.sh`, `scripts/wait_for_redis.py`, `dispatcharr/settings.py`, `e2e/tests/lifecycle/**`, and the workflow file itself. `**/migrations/**` is load-bearing under D16: the upgrade job exists to catch a migration that breaks or destroys data, and migrations land under `apps/*/migrations/` and `core/migrations/`. **One narrow exception to "no `pull_request`"**: a `pull_request` trigger filtered to `**/migrations/**` alone, with the two bash-suite jobs gated off by `if: github.event_name != 'pull_request'`. A PR that adds a migration is gated by the upgrade test; every other PR pays nothing. The **schedule is an addition, and it earns its place**: these suites pull `postgres:16`, `postgres:17`, `redis:latest` and upstream's `:latest` — four floating tags whose contents change under this repository, and which no path filter can ever notice. `cancel-in-progress: false` because this is a post-merge suite: cancelling drops lifecycle signal for every commit but the last in a run of merges, and those intermediate commits are already on `main` — the opposite of the PR-latency argument that makes `cancel-in-progress: true` right everywhere else in this repo. **A path-filtered workflow must not be made a required check**: on a PR that touches none of those paths it never reports, and a required check that never reports blocks the merge forever |
| D5 | **Piece A is two parallel matrix jobs, not one sequential job** | Serial would put 20–30 minutes on the critical path *after* an already-long build. Parallel also halves peak disk: each job pulls its own subset onto a runner that has single-digit gigabytes free after a 3.6 GB image load, and the puid suite alone creates a PostgreSQL data volume per scenario. And it separates the signal — `fail-fast: false` means one red suite names itself while the other still reports. The suites' container-name prefixes differ (`puid_test` vs `tls_test`), so one runner is *possible* — that is not the same as advisable. Rejected: one sequential job, which would only make sense under a runner-minute budget that nothing in this repo's CI suggests exists |
| D6 | **One `build` job produces the AIO image; each suite job loads it and `docker tag`s it into the name that suite expects, then runs with `--skip-build`** | One image under test, which is G1's D4 and G2's D7 for the same reason: `docker/Dockerfile` uses `npm install` with no lockfile, so N builds can produce N different frontend bundles. This is also the whole of how D2 is achieved without touching a suite — the tag adapts to the script, not the other way round |
| D7 | **Diagnosability is designed, not hoped for.** Each suite runs under `pipefail`, tee'd to a file, and that file is uploaded as an artifact on `always()`. A `failure()`-only step dumps `docker ps -a` and `docker logs` for anything still standing. **`--keep-on-fail` is not passed** | These suites assert via `docker logs \| grep`; a bare red X is useless. Three specifics. (1) `pipefail` is non-negotiable — GitHub's default `bash` shell already sets `-eo pipefail`, so `run: … \| tee …` reports correctly *unless* somebody adds a custom `shell:`; say so in a comment, because without it the job goes **green on failure**. (2) `--keep-on-fail` looks like the obvious answer and is a trap, for the two mechanisms in the fact table: cascading name collisions in the TLS suite, and run-global resource accumulation in the puid suite. (3) The suites' own `dump_logs_on_fail` and their closing named-failure list are already in the stream being tee'd — the artifact makes them durable and greppable, and the job summary should name the one-scenario re-run command (`bash docker/tests/test-puid-pgid.sh --skip-build <scenario>`) |
| D8 | **A new `lifecycle` Playwright project: `workers: 1`, `fullyParallel: false`, `retries: 0`, a 600 000 ms timeout, no `dependencies`, no `storageState`. It owns its container's lifecycle and must run alone** | Settled decision D-3, made concrete. No `bootstrap` dependency and no `storageState` for the same reason `pristine` has none: bootstrap targets whichever container is up *before* the project starts, and both lifecycle specs replace or destroy a container mid-run — a persisted admin token would point at an instance that no longer exists. `retries: 0` because attempt 1 consumes the state attempt 2 needs, exactly as in `pristine`. "Runs alone" is already the rule for `pristine` and, per G4's D2, for `streaming-greybox`; in CI it is free (each matrix job has its own runner and container), and locally it is one line in `e2e/README.md`. It is also what makes a global `CoreSettings` mutation legitimate here. Rejected: a separately-named container/volume/port so the project could coexist with `seeded` locally — `destroy()` reaches the shared network and provider anyway, so coexistence would be an illusion with a worse failure mode |
| D9 | **Add one mode to `scripts/e2e_up.sh`: `--recreate` — destroy the app container, keep the volume, network and provider, then start normally** | An upgrade *is* "new container, same volume", and the script has no way to express it: `--stop` keeps the container and therefore its original image snapshot, `--reset` and `--down` destroy the volume. Worse, the app-container reuse branches key on name and never on image id, so setting `DISPATCHARR_E2E_IMAGE` and re-running silently serves the old image — a failure mode that would make the upgrade test pass for entirely the wrong reason. Rejected: a bare `docker rm -f` in the spec followed by a script call, which works but puts half the boot path back outside the single boot path that G1 and G2 both spent a decision defending. Recorded because it is a legitimate fallback if the script edit proves contentious |
| D10 | **The upgrade baseline is a fork image resolved from the CI event, not `:latest`.** `e2e-tests.yml`'s lifecycle job sets `DISPATCHARR_E2E_BASELINE_IMAGE` to `ghcr.io/d10scot/dispatcharr:${{ github.event.pull_request.base.sha }}` on a PR and `:${{ github.event.before }}` on a push to main; the fixture falls back to `:latest` when the variable is unset (local runs) or the SHA tag does not resolve, and says loudly which it used. The resolved digest is logged and attached to the report either way | Settled decision D-2 said "use `:latest`". This keeps its intent — *the fork's own upgrade path* — and closes a hole in its mechanism found this session: **two workflows publish `:latest` on every push to main**, so on a push-triggered run `:latest` can be the commit under test, and the upgrade test would upgrade from itself and pass vacuously while looking perfectly green. Both event-derived SHAs name a commit that is on `main`, is an ancestor of the code under test, and is never that code — and `docker-build.yml` publishes a full-40-char-SHA tag for every push to main, which is exactly the tag being asked for. Rejected: (a) bare `:latest`, for the race above; (b) hand-pinning a historical SHA in the workflow, correct once and silently stale forever after. The `:latest` fallback is retained deliberately so a local run and a commit whose own build failed both still work, with the degradation announced rather than silent |
| D11 | **Both new specs assert Postgres-backed state only, by id, with recorded field values — never a count, never an unfiltered list** | Roadmap rule 4. Redis is excluded by construction, not by preference: AIO configures no persistence and `wait_for_redis.py` flushes on every boot, so a Redis-backed assertion would be asserting a falsehood. The concrete row set both specs create, through `Seeder`: a `Channel` (with an explicit `channel_number`), a `ChannelProfile`, a custom `StreamProfile` (`is_active: true`, a distinctive `parameters` string, and unlocked — so it is distinguishable from the built-in profiles by construction), an inactive `M3UAccount` on an unroutable URL, an inactive `EPGSource`, a `User` at `user_level: 1`, plus one PATCH into the `system_settings` `CoreSettings` row. Assertions after the lifecycle event, in order of what they prove: **(a)** the pre-event access token still authenticates via `/api/accounts/users/me/` returning `e2e-admin` — proving `/data/jwt` persisted, because a regenerated `DJANGO_SECRET_KEY` invalidates every token; **(b)** each of the seven rows `GET`s by id with the field values recorded at creation; **(c)** the `system_settings` field reads back changed, not defaulted; **(d)** the lifecycle event demonstrably happened — `docker inspect`'s `.State.StartedAt` moved for the restart, and `.Image` equals the local image's id for the upgrade. **(d) is not padding**: without it a spec that silently failed to restart or replace anything passes every other assertion. Rejected: asserting through the UI, which adds browser flake to a test whose entire subject is the data layer |
| D12 | **The upgrade spec asserts migration state two ways: `manage.py migrate --check` exits 0, and the set of applied migrations after the upgrade is a superset of the set before** | `--check` proves nothing is left unapplied. The superset comparison — `manage.py showmigrations --list`, parsed for `[X] app.name`, captured on the baseline and again after — is what would catch a migration renamed, deleted or squashed out from under existing data, which is the failure mode this row exists for and which `--check` alone cannot see. Both run through `docker exec … su - dispatch -c 'cd /app && …'`, the same grey-box move the bash suites make throughout; the container is the subject of the test, not an implementation detail behind it. Verify `migrate --check`'s exit semantics against the pinned Django at implementation time. Rejected: asserting only that the container starts, which passes trivially today and would keep passing trivially if a future migration silently dropped data |
| D13 | **Extract `provisionAdmin(request, baseURL)` from `bootstrap.setup.ts` into `e2e/setup/`, and have both callers use it. The lifecycle specs build `ApiClient` and `Seeder` directly from the pair it returns** | Both specs need the probe → `assertMayCreateSuperuser` → POST → `loginWithThrottleBackoff` sequence on an instance nothing has bootstrapped. Duplicating it would duplicate the superuser guard, which `superuser-guard.ts` states plainly is not a guard if only one of the two paths consults it. The extraction is deliberately minimal — the probe/create/login block only. `persistAdminAuth` and the `IntervalSchedule` pre-warm stay in `bootstrap.setup.ts`: the lifecycle specs hold the pair in memory and never write `playwright/.auth/`, and a single-worker spec creating M3U accounts serially cannot lose the concurrent-create race the pre-warm exists to prevent |
| D14 | **A `test:lifecycle` npm script, and the project added to `e2e-tests.yml`'s matrix in the same PR — carrying the restart spec only, per D16** | `e2e/README.md`: "If you add a fourth project to `playwright.config.ts`, add it to that matrix too — nothing wires new projects in automatically." `npm test` with no suffix already fails with a message listing the populations; `lifecycle` joins that list, with the "run it alone" caveat attached |
| D16 | **The upgrade spec runs in `lifecycle-tests.yml`, not `e2e-tests.yml`. Only the ~3-minute restart spec joins the PR matrix** | Placing both lifecycle specs in `e2e-tests.yml` puts ~12 minutes on **every PR**, where the longest existing test job is `seeded` at 284s. That makes lifecycle the long pole and roughly doubles E2E latency on every PR — breaching the ~10-minute ceiling that G4 is being sharded into three projects specifically to protect. Sharding one goal to hold that budget while another breaches it is incoherent. The move costs nothing because `lifecycle-tests.yml` **already builds the AIO image** for the two bash suites (D6); the upgrade job is a third consumer of an artifact that already exists. Migration-touching PRs keep their gate through D4's narrow `pull_request` filter | (a) Both specs in `e2e-tests.yml` — the ~12-minute PR cost above. (b) Both in `lifecycle-tests.yml` — loses cheap per-PR restart signal for no saving, since the restart spec is ~3 minutes and reuses a build that workflow already has. (c) A separate third workflow — pays a second 45-minute-budget AIO build to run one spec |
| D15 | **Product defects found are asserted correct, marked `test.fail()`, and filed — never patched** | Roadmap rule 5. `gh issue create --repo D10Scot/Dispatcharr`, with the explicit `--repo` flag, always: this checkout is a fork and `gh` without it resolves to upstream's public tracker. G7 has a specific reason to expect this — the bash suites have never been executed, so a first run is as likely to find a product bug as a suite bug, and telling those apart is the first thing the implementer will have to do |

## Piece A — wire up the bash suites

**One new file: `.github/workflows/lifecycle-tests.yml`.** Nothing else changes.

```
build (AIO image, timeout 45)
  └─ artifact ──┬─→ puid-pgid          (docker tag → dispatcharr:puid-test, --skip-build)
                ├─→ tls-postgres       (docker tag → dispatcharr:tls-test,  --skip-build)
                └─→ upgrade-migrations  (D16: Playwright, --project=lifecycle --grep upgrade)
```

Shape, mirroring `e2e-tests.yml` step for step so the two workflows stay legible as a pair:

- `permissions: contents: read` at the top level, and nowhere else. Neither job needs more — the
  GHCR pulls are anonymous, which is why no token scope appears anywhere in this design.
- `concurrency: { group: lifecycle-tests-${{ github.workflow }}-${{ github.ref }},
  cancel-in-progress: false }` — the group naming matches every other workflow here; the `false`
  is the deliberate departure argued in D4.
- `build`: `timeout-minutes: 45`, `docker build -f docker/Dockerfile -t dispatcharr-lifecycle:local .`,
  `docker save | gzip`, upload. Identical in intent to `e2e-tests.yml`'s `build`.
- The suite job: a two-entry `include:` matrix carrying `{ name, script, tag }`, `fail-fast: false`,
  `timeout-minutes: 45`. The suites document 10–15 minutes; the headroom is for the two
  `pg_upgrade` scenarios, which `apt install` a PostgreSQL major version inside the container and
  raise their own readiness budget to 300s each.
- Steps: checkout → download artifact → `docker load` → `docker tag dispatcharr-lifecycle:local
  dispatcharr:${{ matrix.tag }}` → `bash ${{ matrix.script }} --skip-build 2>&1 | tee
  "$RUNNER_TEMP/${{ matrix.name }}.log"` → `if: failure()` container dump → `if: always()` upload
  of the log.

Every `actions/checkout` gets `persist-credentials: false`. Every `uses:` is a full 40-character
commit SHA with a trailing version comment — `actions/checkout`, `actions/upload-artifact` and
`actions/download-artifact` are the only three actions needed, all already SHA-pinned in
`e2e-tests.yml`, and the pins must be **resolved at implementation time with
`gh api repos/<owner>/<repo>/commits/<tag> --jq .sha`**, not typed from memory. Reusing the exact
pins already in `e2e-tests.yml` is the cheapest correct route.

**Expect the zizmor hook to block.** It fires on `Write|Edit` to any `.github/workflows/*.yml`,
blocks on *every* finding in the edited file including legacy ones, and the workflows are currently
at zero findings — a ratchet, not a warning. The same check runs in CI as `actions-lint.yml`
against the same pinned version. A workflow-level `permissions:` elevation, a floating tag, or a
checkout without `persist-credentials: false` will each stop the edit from landing.

## Piece B — the two rows that do not exist

**New directory `e2e/tests/lifecycle/`, one new project, one new fixture, one script mode, one
extracted helper.** Both specs are self-contained: each brings up the instance it needs, provisions
its own admin, seeds, performs the lifecycle event, and asserts. Neither depends on the other's
ordering, which is what makes `workers: 1` safe without a declared sequence.

```
e2e/tests/lifecycle/restart-persistence.spec.ts    ~3 min   reuses the container: --stop, then start
e2e/tests/lifecycle/upgrade-migrations.spec.ts     ~9 min   baseline image → --recreate → local image
```

`e2e/fixtures/instance.ts` is a test-scoped fixture wrapping `scripts/e2e_up.sh` through
`execFile`, plus the `docker` reads the assertions need:

| Method | Does |
|---|---|
| `instance.up({ image?, reset? })` | Runs the script with `DISPATCHARR_E2E_IMAGE` and `DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD` set. Throws named on a non-zero exit, quoting the script's output |
| `instance.restart()` | `--stop`, then a plain start — an in-place restart of the same container, through the single boot path |
| `instance.recreate({ image })` | `--recreate` (D9) with the image set |
| `instance.down()` | `--down`, for the upgrade spec's teardown |
| `instance.pull(ref)` | `docker pull`, then `docker image inspect -f '{{index .RepoDigests 0}}'`, returning the digest for the caller to log and attach |
| `instance.imageId()` / `instance.startedAt()` | `docker inspect -f '{{.Image}}'` / `'{{.State.StartedAt}}'`, for D11(d) |
| `instance.manage(argv)` | `docker exec … su - dispatch -c 'cd /app && python manage.py …'`, returning stdout and exit code, for D12 |

Its file header states plainly that it drives Docker from inside a test, that only the `lifecycle`
project may import it, and why (D8). The upgrade spec's teardown is a `finally` calling `down()` —
`destroy()` removes the shared network and provider container as well, which is survivable exactly
because this project runs alone, and the header says that too.

Neither spec uses the `upstream` fixture, so the provider is present-but-unused throughout — the
same relationship `pristine` already has with it.

## Test inventory

| # | COVERAGE row | Artifact | Mechanism | Est. |
|---|---|---|---|---|
| 1 | PUID/PGID honoured | `docker/tests/test-puid-pgid.sh`, unmodified, run by `lifecycle-tests.yml` | 20 scenarios: fresh installs at default and custom PUID, upgrade from UID 102 with and without an explicit PUID, restart idempotency, PUID change, the UID-102 collision, PUID=0 and non-numeric rejection, bind mounts, tmpfs, modular mode, custom user and port, two PostgreSQL major upgrades, the full nginx→uwsgi→Django stack, and a read-only rootfs | 10–15 min (the suite's own estimate; never timed) |
| 2 | TLS Postgres connection | `docker/tests/test-tls-postgres.sh`, unmodified, run by `lifecycle-tests.yml` | 8 scenarios: PG mTLS cert-only, mTLS with password, server-only TLS, a 0777 client key, a no-TLS regression check, `verify-full` with CN matching, Redis TLS, and full TLS with a separate Celery container sharing the volume | 10–15 min (same caveat) |
| 3 | Restart preserves channels and settings | `e2e/tests/lifecycle/restart-persistence.spec.ts`, `lifecycle` project in `e2e-tests.yml` | `instance.up()`, `provisionAdmin`, seed the seven-row set of D11, `instance.restart()`, then assertions (a)–(d) with `startedAt` as the event proof | ~3 min |
| 4 | Upgrade from previous release (migrations) | `e2e/tests/lifecycle/upgrade-migrations.spec.ts`, `lifecycle` project run by `lifecycle-tests.yml` (D16) | `instance.pull(baseline)` per D10 and attach the digest; `up({ image: baseline, reset: true })`; `provisionAdmin`; capture the applied-migration set; seed the same seven rows; `recreate({ image: 'dispatcharr-e2e:local' })`; assert D12's two migration checks plus (a)–(d) with `imageId` as the event proof; `finally` → `down()` | ~9 min |

Rows 1 and 2 are `done` the moment the workflow runs them green. Rows 3 and 4 are `done` when the
specs land. All four move to `done` in `e2e/COVERAGE.md` in the same PR as the artifact that covers
them — roadmap rule 3.

**The settled position on row 4's value is worth restating so nobody re-derives it as a problem.**
The fork has added zero migrations of its own, so today this test proves little beyond "the
container restarts onto its own data and Django's runner does not choke on a no-op". It was chosen
anyway, over an upstream `0.28.0` baseline, because it is scaffolding pointed at the right thing
from day one: it becomes meaningful automatically the moment Phase 1 starts changing models, and
building it then is strictly harder than building it now.

## Non-goals

- **Fixing `docker-build.yml`'s `sign-and-attest` job.** Out of scope, and the billing restriction
  behind it has already been addressed by making the repository public.
- **Correcting `CLAUDE.md`'s claim that `docker-build.yml` "has never run and is broken by
  construction".** It is stale. Surface it as a follow-up; do not make the edit inside G7's PR,
  where it would be an unrelated change to the file every agent reads.
- **Any Dockerfile pinning sweep.** `docker/Dockerfile:8,24` and `docker/DispatcharrBase:7,98`
  remain floating. Roadmap non-goal, restated by `CLAUDE.md`: leave clean anything you touch, do
  not go looking. G7 builds `docker/Dockerfile`; it edits no Dockerfile.
- **Modifying the bash suites.** D2. If one is broken, that is a follow-up PR with its own title.
- **A PostgreSQL major-version upgrade test of our own.** `test-puid-pgid.sh`'s `pg_major_upgrade`
  and `pg_upgrade_post_puid` already cover PG 16→17 end to end. Row 4 is a Django-migration test at
  a constant PG major, not a duplicate.
- **Uploaded media across an upgrade.** `MEDIA_ROOT` is under `/app` and not volume-backed
  (verified); whether an uploaded logo's bytes survive a container recreate is **unverified**, and
  chasing it is a product investigation, not a test. Worth filing as a question; not asserted here.
- **Anything Redis-backed surviving a restart.** Excluded by construction (D11), not deferred.
- **First-run setup.** Already `done` under G1, in the `pristine` project.
- **Backup and restore.** A `backups` row exists under G6; `/data/backups` persisting is implied by
  the volume assertions here and is not separately tested.
- **The G2 fake upstream provider.** None of the four rows need live upstream traffic. It is
  present but unused.
- **Fixing product defects.** Assert correct, `test.fail()`, file the issue (D15).

## Risks

| Risk | Mitigation |
|---|---|
| **The bash suites have never run. The first CI execution may be red for reasons that have nothing to do with a product regression** — a Docker Desktop assumption that does not hold on `ubuntu-latest`, a drifted log string, a scenario written against a since-changed init script | This is the expected outcome of a first run, not a failure of the plan, and D2 is what keeps it interpretable: an unmodified suite failing tells you something true. Land the workflow, read the uploaded logs, then triage each failure into "suite bug" (follow-up PR) or "product bug" (issue, D15). Do not pre-emptively fix a suite you have not yet watched fail |
| **The two `pg_upgrade` scenarios `apt install` a PostgreSQL major version at runtime, inside the container** | The largest flake vector in G7, and the reason `f3fd4dd2` exists. If they prove unreliable on CI runners, the correct response is the suites' existing single-scenario argument and a documented exclusion in the workflow — *not* an edit to the suite. Both already self-skip when `postgres:16` cannot be pulled |
| **Disk on the runner.** A 3.6 GB image load, four-plus pulled images, and up to 20 PostgreSQL data volumes in one job | D5's parallel split is half the answer. The other half is not passing `--keep-on-fail`, which is what would let volumes accumulate across an entire failing run. Worth a dry run before trusting D4's timeout budget |
| **`--keep-on-fail` looks like the obvious diagnosability answer and would make things worse** | Called out explicitly in D7 with the mechanism, so an implementer reaching for it reads why first |
| **A `tee` without `pipefail` turns every failure green** | GitHub's default `bash` shell sets `-eo pipefail`, so the default is safe. The risk is a custom `shell:` added later. A comment at the step says so |
| **The upgrade spec could upgrade from itself.** `:latest` is written by two workflows on every push to main and can be the commit under test | D10 resolves the baseline from the CI event instead, so the baseline is always a strict ancestor. The `:latest` fallback remains for local runs and for a commit whose own build failed, and announces itself; the resolved digest is logged and attached on every run |
| **The upgrade spec could pass without upgrading anything** — `e2e_up.sh` reuses a container by name regardless of image, so a missing `--recreate` silently keeps the baseline running | D9 closes the hole and D11(d) catches it anyway: `.Image` is asserted to equal the *local* image's id after the swap. Two independent guards, deliberately |
| **The upgrade spec could build the baseline instead of pulling it.** `e2e_up.sh` builds from `docker/Dockerfile` when `docker image inspect` misses, so a failed or forgotten pull produces a "baseline" that is the local code | `instance.pull()` runs first and fails named on a pull error, returning the digest the spec logs. A test that compared the image against itself would otherwise pass forever |
| **`docker/Dockerfile:14`'s unpinned `npm install`** means the image row 4 builds is not guaranteed identical across two runs of the same commit | Pre-existing, tracked debt in `CLAUDE.md`. Named here because row 4 is the one new test that always builds fresh rather than reusing a published image, so it inherits the nondeterminism directly |
| **The `lifecycle` project destroys containers other projects are using** | It runs alone: its own matrix job and runner in CI, and a documented rule locally, alongside the same rule that already exists for `pristine` and (per G4's D2) `streaming-greybox`. `e2e/README.md` and the `instance.ts` header both state it |
| **Extracting `provisionAdmin` touches `e2e/setup/bootstrap.setup.ts`, which other wave-2 goals may also edit** | Additive and mechanical — one function moved, one call site changed, no behaviour altered. Same mitigation as G4's `seed.ts` conflict: keep it small |
| **Two fresh instances mean two logins against a 3/minute budget** | Under the cap, and `provisionAdmin` goes through `loginWithThrottleBackoff`, which honours `Retry-After`. The project's 600 000 ms timeout has room for a throttle window, and `retries: 0` means a spent login is never wasted on a retry |
| **The `lifecycle` job could exceed `e2e-tests.yml`'s 30-minute job timeout** — a ~3.6 GB baseline pull plus four container boots on a cold runner | Budgeted at ~12–15 minutes against a 30-minute ceiling. If it proves tight, raise the timeout on that job rather than trimming assertions; the AIO build is the long pole in that workflow regardless |
| **Which `system_settings` field to change is unresolved** | Deliberately an implementation-time choice: pick one with an unambiguous non-default value and no side effects, and record it in a comment at the call site. `CoreSettingsViewSet` is registered as `settings` and the grouped keys are the `*_SETTINGS_KEY` constants — both verified; the field-level detail was not enumerated and is not worth guessing here |
| **Adding a project to `e2e-tests.yml` trips the zizmor ratchet on a file G4 is also editing** | Both goals add matrix entries to the same workflow. Additive, one line each. Whichever lands second rebases; the hook checks the whole file either way |
