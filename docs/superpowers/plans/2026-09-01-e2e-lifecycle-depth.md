# G12 — Lifecycle Depth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the lifecycle suite a trustworthy migration gate — triage `lifecycle-tests.yml` from permanently red to green, extend `durable-state.ts` from seven scalar rows to seven relations, and add the two `COVERAGE.md` rows G7 left `todo` (backup restore, non-zero `refresh_interval`) on instances of their own.

**Architecture:** Four pieces, in order. **Piece A** (Tasks 1–6) is bash and CI: the fifteen red scenarios, already triaged in the spec, plus the two leaks and the diagnostics that made one of them unclassifiable. **Piece B** (Task 7) is one TypeScript file, `e2e/tests/lifecycle/durable-state.ts`, which both existing lifecycle specs already share. **Piece C** (Task 8) and **Piece D** (Task 9) are one new spec each, with a new Playwright project each. **Piece E** (Tasks 10–11) is the CI wiring and the documentation.

**Tech Stack:** Bash, Docker, GitHub Actions; Playwright 1.62.1 + TypeScript 5.7.2 (ESM, `moduleResolution: bundler`, `strict`), Node 24.

**Spec:** `docs/superpowers/specs/2026-09-01-e2e-lifecycle-depth-design.md` — read it. Decisions are cited below as **D1**–**D22**, verified facts as **F1**–**F12**, triage rows as **T1**–**T6**. The spec's rationale is not repeated here.

**Base:** branch from `origin/main` at or after **`45a33a4a`**. G11 has merged — `4211cbb7` (guards, ADRs, full-run CI) and `7a408c2b` (every test tagged, the tag guard blocking) — so its edits to `e2e/playwright.config.ts`, `.github/workflows/lifecycle-tests.yml`, `e2e/README.md` and `e2e/COVERAGE.md` are already on `main` and there is nothing to rebase through.

---

## Global Constraints

Every task's requirements implicitly include this section.

1. **No product file is touched.** Not `docker/init/*`, not `docker/entrypoint.sh`, not `dispatcharr/settings.py`, not anything under `apps/`. (D2, roadmap rule 5.) `docker/tests/*.sh` **is** test code and this goal modifies it — that is D1, superseding G7's D2, and it applies to the two bash suites and nothing else.
2. **Product defects are filed, never fixed.** `gh issue create --repo D10Scot/Dispatcharr …`. **The `--repo` flag is mandatory**: this checkout is a fork of `Dispatcharr/Dispatcharr` and `gh` without it files on upstream's public tracker (`docs/agents/issue-tracker.md`).
3. **A bash scenario is never written to fail.** (D3.) The suites have no `test.fail()`; a deliberately-red scenario re-breaks the workflow this goal exists to fix. A product defect found in bash gets an issue and a comment at the site, and **no scenario**.
4. **`--keep-on-fail` is never passed.** The TLS suite reuses `tls_test_app`/`tls_test_pg`/`tls_test_redis` across all 8 scenarios, so keeping one failure's containers cascades into six fabricated ones; the puid suite's keep-branch is run-global.
5. **Assert Postgres-backed state only.** AIO configures no Redis persistence and `scripts/wait_for_redis.py` calls `flushdb()` on every boot.
6. **Never assert on a global count or an unfiltered list.** Roadmap rule 4. Assert by id, against values recorded at creation. `waitFor.resource` predicates that check `count === 1` are fine **only** when the query is `?search=<runToken-bearing prefix>`, as `vod-catalogue-ingest.spec.ts` does.
7. **Read the root `CONTEXT.md` before naming anything.** Three distinct things are called "profile" — **Stream Profile** (how we talk upstream), **Output Profile** (downstream transcode), **Channel Profile** (authorization grouping by M2M membership). This plan uses all three words and means them literally.
8. **Every `uses:` in a workflow is a full 40-character commit SHA with a trailing version comment**; `persist-credentials: false` on every `actions/checkout`; `permissions: contents: read` at the top level only. The zizmor hook blocks on **every** finding in an edited workflow file, and the workflows are at zero findings — a ratchet. **Reuse the pins already in `.github/workflows/lifecycle-tests.yml`**; resolve nothing new.
9. **Typecheck is `cd e2e && npm run typecheck`.** `npx tsc --noEmit -p e2e` from the repo root does not resolve. The `PostToolUse` hook runs it on every `e2e/**/*.ts` edit and blocks.
10. **`e2e/COVERAGE.md` is updated in the same PR.** Roadmap rule 3.
11. **Every new `test(` carries a tag, or CI fails.** G11 owns the taxonomy (`docs/adr/0002-e2e-test-taxonomy.md`); apply it, do not extend it. The syntax is Playwright's native tag option as an **inline object literal second argument**: `test('title', { tag: '@characterization' }, async ({ … }) => { … })`. Hoisting that object to a const makes the declaration *unverifiable* and `e2e/tests/guards/tags.spec.ts` fails — it fails closed, and `KNOWN_UNVERIFIABLE` is empty. Every test this goal adds or touches is `@characterization` (spec D19: the files destructure `instance`, which is the `CONTAINER_LIFECYCLE` capability, and ADR 0002 makes anything on a capability list `@characterization` by construction), so each needs a `// @characterization: <fact it pins>` comment immediately above the declaration. Both existing lifecycle specs already carry the tag — no retag.
12. **A new spec that owns a container goes on `CONTAINER_LIFECYCLE.allow` in `e2e/tests/guards/allowlist.ts`.** `capabilities.spec.ts` compares each `allow` array with `toEqual`, so a missing entry fails *and* a stale one does. `instance.manage(['dumpdata', …])` does **not** trip `CONTAINER_INTROSPECTION` — that detector matches only the literals `pgrep`, `docker ` and `manage.py` inside string and template literals. Do not add anything to `GLOBAL_SETTINGS_WRITE`: `tests/lifecycle/durable-state.ts` is already on it for the `system_settings` PATCH it has always made, and none of the seven relations writes `/api/core/settings/`.
13. **On macOS, run the bash suites under bash 4.4+** — Homebrew's `bash`, or a `docker:27-cli` container with bash installed. Stock `/bin/bash` is 3.2.57, where expanding an empty array under `set -u` is an unbound-variable error, so the suite dies on `CLEANUP_ITEMS[@]` before it runs anything. Runners ship bash 5.x, so this never reproduces in CI.
14. **Both suites take a single positional scenario name**, so one scenario can be re-run alone: `bash docker/tests/test-puid-pgid.sh --skip-build pg_major_upgrade`.

## Findings already made — do not re-derive them

The spec's investigation is complete. These are settled; re-running the investigation is wasted effort and risks reaching a different answer from partial evidence.

| # | Settled | Evidence |
|---|---|---|
| **G12-R1** | `ghcr.io/dispatcharr/dispatcharr:latest` is **post**-PUID. It creates `/data/db` owned `1000:1000` with no `postgres` role. | Run 33384550684's `puid-pgid.log`: `ℹ️  Old data owner: 1000:1000` immediately under `Creating old-style data using release image`. |
| **G12-R2** | PUID auto-detect was **removed from the product on purpose** by `7e221720`, and the suite (added in `52ed0fc1`, the same PR that added auto-detect) was never updated. | `git show 7e221720 -- docker/init/01-user-setup.sh`; `git log --follow -- docker/tests/test-puid-pgid.sh` returns `52ed0fc1` only. |
| **G12-R3** | All 7 TLS failures are one exception: `PermissionError: [Errno 13] Permission denied: '/certs/ca.crt'` at `dispatcharr/settings.py`'s `_validate_tls_cert_paths`, caused by `mktemp -d`'s 0700 mode. The only passing scenario, `modular_no_tls_regression`, is the only one that mounts no certificates. | `tls-postgres.log`, all seven `--- Container logs (tls_test_app) ---` blocks. |
| **G12-R4** | `pg_major_upgrade` is **not** classified. Its sibling `pg_upgrade_post_puid` passes on the same run using the same `pg_upgrade` path; the only difference is that it seeds its PG 16 cluster inside `$IMAGE_NAME` instead of from `postgres:16`. | Both scenarios' output in the same log; `test_pg_major_upgrade` vs `test_pg_upgrade_post_puid` in the suite. |
| **G12-R5** | Issue #41 is **not** one of the fifteen — it fails no assertion. A **second**, distinct leak exists: the bind-mount cleanups omit `--entrypoint`, so the AIO entrypoint runs and dies at `docker/entrypoint.sh:109` (`mktemp failed`) without ever running `rm -rf`. | The `mktemp failed` lines under `Bind mount — local filesystem` and `Bind mount upgrade — old UID 102 → PUID=1000`. |
| **G12-R6** | The bash suites have **never** been green in CI. `lifecycle-tests.yml`'s `suites` job *was* `if: github.event_name != 'pull_request'`, so the green G7 PR runs skipped them entirely. G11 widened it to `if: github.event_name != 'pull_request' \|\| needs.changes.outputs.full == 'true'`, so a `migration/*` head branch or a `workflow_dispatch` with `full: true` now runs them on a PR — which is how this goal verifies itself (Task 6 Step 4). | The workflow file at `45a33a4a`; `gh run list --workflow=lifecycle-tests.yml`. |
| **G12-R9** | Nothing under `docker/tests/` changed between the spec's original verification and `45a33a4a`, so the whole triage still applies to the files on disk. | `git log --oneline cf95410e..45a33a4a -- docker/tests/` is empty. |
| **G12-R7** | `instance.manage()` rejects any argument outside `^[A-Za-z0-9._/=-]+$`, so `shell -c` is impossible but `dumpdata django_celery_beat.PeriodicTask --format=json` passes intact. `manage.py` prints a banner to stdout first, so parse from the first `[`. | `Instance.manage` in `e2e/fixtures/instance.ts`; `appliedMigrations` in `upgrade-migrations.spec.ts`. |
| **G12-R8** | `instance.restart()` stops and starts the **provider** container too, and `ScenarioRegistry` is an in-memory `Map` — every upstream scenario is forgotten across a restart. | `scripts/e2e_up.sh`'s `--stop` branch; `e2e-upstream/src/scenario.ts`. |

---

# Piece A — the bash suites and the workflow

### Task 1: Stop the leaks and make the failures readable

Implements **D7** and **D9**, and triage rows **T5** and **T6**. This runs **first** because it removes the one live confound for T4 (Task 5): `pg_major_upgrade` is scenario 17 of 20 on a runner with single-digit gigabytes free, behind ~16 leaked PostgreSQL data volumes.

**Files:**
- Modify: `docker/tests/test-puid-pgid.sh`
- Modify: `docker/tests/test-tls-postgres.sh`

**Context the implementer needs:**

`cleanup_scenario` is duplicated near-verbatim in both suites (`test-puid-pgid.sh` and `test-tls-postgres.sh`, both around line 100–115). Both walk `CLEANUP_ITEMS` in **insertion order**, and scenarios call `fresh_volume` (which does `track_volume`) *before* `track_container`. `docker volume rm` on a volume still mounted by a live container fails, and the failure is swallowed by `2>/dev/null`. That is issue #41, in two files.

- [ ] **Step 1: Remove containers before volumes, in both suites**

Replace the loop body in `cleanup_scenario` — in **both** files — so containers are removed in a first pass and volumes/networks in a second. Do not reorder the tracking calls at each scenario's top: they read naturally as written, and forty call sites is forty chances to miss one.

```bash
    # Two passes, deliberately. CLEANUP_ITEMS is in insertion order and every
    # scenario tracks its volume before the container that mounts it
    # (`fresh_volume` calls `track_volume`), so a single ordered pass tries
    # `docker volume rm` while the container is still up. That fails, the
    # failure is swallowed by 2>/dev/null, and one PostgreSQL data volume
    # leaks per scenario on EVERY run, pass or fail — on a runner with
    # single-digit gigabytes free after a 3.6 GB image load.
    # D10Scot/Dispatcharr#41.
    for item in "${CLEANUP_ITEMS[@]}"; do
        [ "${item%%:*}" = "container" ] || continue
        local name="${item#*:}"
        docker stop "$name" 2>/dev/null
        docker rm -f "$name" 2>/dev/null
    done
    for item in "${CLEANUP_ITEMS[@]}"; do
        local type="${item%%:*}"
        local name="${item#*:}"
        case "$type" in
            volume)  docker volume rm "$name" 2>/dev/null ;;
            network) docker network rm "$name" 2>/dev/null ;;
        esac
    done
    CLEANUP_ITEMS=()
```

- [ ] **Step 2: Fix the second leak — the bind-mount cleanups run the app entrypoint**

In `test-puid-pgid.sh`, `test_bind_mount`, `test_bind_mount_upgrade` and `test_bind_mount_auto_adapt` each end with a line shaped like:

```bash
    docker run --rm -v /tmp:/hosttemp "$IMAGE_NAME" bash -c \
        "rm -rf /hosttemp/puid_test_bind_upg_$$" 2>/dev/null
```

`$IMAGE_NAME` has an `ENTRYPOINT`, so `bash -c "…"` is passed to it as arguments it ignores. The entrypoint then boots, tries to mint a Django secret key into an unmounted `/data`, and exits at `docker/entrypoint.sh:109` printing `mktemp failed`. The `rm -rf` never runs. Add `--entrypoint bash` to every such line — the same form the *seeding* half of each scenario already uses correctly:

```bash
    # --entrypoint bash, like the seeding call above. Without it the AIO
    # entrypoint runs, dies minting a secret key into an unmounted /data
    # ("mktemp failed", docker/entrypoint.sh), and the rm -rf never executes —
    # so every bind-mount scenario leaked its /tmp directory. Sibling
    # mechanism to D10Scot/Dispatcharr#41.
    docker run --rm -v /tmp:/hosttemp --entrypoint bash "$IMAGE_NAME" -c \
        "rm -rf /hosttemp/puid_test_bind_upg_$$" 2>/dev/null
```

Verify every occurrence is fixed:

```bash
grep -n 'docker run --rm -v /tmp:/hosttemp' docker/tests/test-puid-pgid.sh
```

Expected: every hit carries `--entrypoint bash`.

- [ ] **Step 3: Widen and de-noise `dump_logs_on_fail`** (D9)

In `test-puid-pgid.sh`, `dump_logs_on_fail` is `docker logs "$container" 2>&1 | tail -60`. On the one failure this goal could not classify, all 60 lines were PostgreSQL's repeated `collation version mismatch` triplet and not one line of the entrypoint's own stdout survived. Replace the `tail` with:

```bash
        # 200, not 60, and PostgreSQL's repeated collation-mismatch triplet
        # filtered out. At 60 lines this diagnostic was entirely consumed by
        # that warning on the one failure it most needed to explain
        # (pg_major_upgrade), so the artifact carried no entrypoint output at
        # all. The filter drops only the three-line warning/DETAIL/HINT group,
        # which is noise by construction: it fires once per connection.
        docker logs "$container" 2>&1 \
            | grep -vE 'has a collation version mismatch|The database was created using collation version|Rebuild all objects in this database that use the default collation' \
            | tail -200 | sed 's/^/  | /'
```

Apply the equivalent change to `test-tls-postgres.sh`'s `dump_logs_on_fail` (`tail -30` there); its failures are Python tracebacks, which 30 lines truncates. Use `tail -100`, no filter.

- [ ] **Step 4: Raise `STARTUP_TIMEOUT` in both suites** (T5)

`test-puid-pgid.sh` has `STARTUP_TIMEOUT=180`; `test-tls-postgres.sh` has `120`. `restart_idempotent` timed out at 180s on run 33247491371 and passed on 33384550684 — a loaded-runner flake, not a product regression. Raise to `300` and `240` respectively, with a comment at each:

```bash
# 300s, not 180. This is a budget for a loaded CI runner that has just
# `docker load`ed a 3.6 GB image, not a claim about how long a healthy boot
# takes — an ordinary one is ~30s. restart_idempotent timed out at 180s on
# run 33247491371 and passed at the same code on 33384550684.
STARTUP_TIMEOUT=300
```

- [ ] **Step 5: Verify locally**

```bash
bash docker/tests/test-puid-pgid.sh --skip-build fresh_default
docker volume ls | grep puid_test    # expected: no output
docker ps -a | grep puid_test        # expected: no output
ls -d /tmp/puid_test_bind_* 2>/dev/null   # expected: no output
```

The suite needs `dispatcharr:puid-test` to exist; build it once with `docker build -t dispatcharr:puid-test -f docker/Dockerfile .` or drop `--skip-build` for the first run.

**Verification:** `fresh_default` passes; no `puid_test*` volume, container or `/tmp` directory survives.

---

### Task 2: `upgrade_explicit_puid` — seed a genuinely pre-PUID cluster

Implements **D4**, triage row **T1**. Two of the eight failures.

**Files:**
- Modify: `docker/tests/test-puid-pgid.sh`

**Context the implementer needs:**

`setup_old_pg_data` boots `RELEASE_IMAGE="ghcr.io/dispatcharr/dispatcharr:latest"` to manufacture "old-style data (UID 102)". Per **G12-R1**, that image is now post-PUID: it produces `1000:1000` data with no `postgres` bootstrap superuser. Both failing assertions follow directly — `check_role_superuser "$name" "dispatch" "postgres"` finds `<missing>`, and no `Migrating PostgreSQL data ownership` is logged because 1000 already equals `PUID=1000`.

`setup_old_pg_data_manual`, already in the file as a fallback, produces exactly what the scenario needs: `chown -R postgres:postgres`, `su - postgres -c "$PG_BIN/initdb -D /data/db"` (so `postgres` is the bootstrap superuser, OID 10), a `dispatch` login role and a `dispatcharr` database. It is reproducible and depends on no third-party tag. This is not a hypothesis — `test_bind_mount_upgrade` seeds the same way and its `Bind mount ownership migration logged` assertion **passes** in the failing run.

- [ ] **Step 1: Delete the release-image path**

Remove, in this order:
- the `setup_old_pg_data()` function in its entirety;
- the `RELEASE_IMAGE`, `BASE_IMAGE` and `USE_RELEASE_IMAGE` variable declarations near the top;
- the `docker pull "$RELEASE_IMAGE"` block near the foot of the file that sets `USE_RELEASE_IMAGE`.

`BASE_IMAGE` is unused today; it goes with the rest so no reader mistakes it for live configuration.

- [ ] **Step 2: Call the manual seeder unconditionally**

In `test_upgrade_explicit_puid`, replace:

```bash
    if [ "$USE_RELEASE_IMAGE" = true ]; then
        setup_old_pg_data "$vol"
    else
        setup_old_pg_data_manual "$vol"
    fi
```

with:

```bash
    # Always the manual seeder, never the published release image.
    #
    # `ghcr.io/dispatcharr/dispatcharr:latest` used to BE the pre-PUID image
    # this scenario upgrades from. It no longer is: it initialises /data/db
    # as 1000:1000 with `dispatch` as the bootstrap superuser and no
    # `postgres` role at all. Seeding from it made both assertions below
    # unreachable — `postgres` came back `<missing>`, and no ownership
    # migration was logged because 1000 already equalled PUID=1000 — and no
    # future version of that floating tag will be pre-PUID again.
    #
    # The manual seeder produces the genuine article, reproducibly and with
    # no third-party tag in the path: initdb run as the `postgres` OS user,
    # so `postgres` is the bootstrap superuser (OID 10) and the data carries
    # the image's postgres package UID. `test_bind_mount_upgrade` seeds this
    # way and its migration assertion has always passed.
    setup_old_pg_data_manual "$vol"
```

The same substitution is needed in `test_upgrade_auto_adapt`, which Task 3 rewrites — do it there, not here, so the two changes stay reviewable apart.

- [ ] **Step 3: Update the function's own comment**

`setup_old_pg_data_manual`'s header still reads "Fallback: create old-style data manually (if release image unavailable)". It is now the only path. Rewrite it to say what it produces and why it is the only path, referencing the comment from Step 2 rather than repeating it.

- [ ] **Step 4: Run the scenario**

```bash
bash docker/tests/test-puid-pgid.sh --skip-build upgrade_explicit_puid
```

**Verification:** `Failed: 0`. Specifically, `PG role 'postgres' is superuser` and `Ownership migration logged` both report ✅. If the ownership migration is *not* logged, check what UID the manual seeder actually produced — `stat -c '%u' /data/db/PG_VERSION` must differ from 1000 for the migration branch in `docker/init/02-postgres.sh` to fire.

---

### Task 3: Rewrite the two `auto_adapt` scenarios for the product that exists

Implements **D5**, triage row **T2**. Five of the eight failures.

**Files:**
- Modify: `docker/tests/test-puid-pgid.sh`

**Context the implementer needs:**

Per **G12-R2**, `7e221720` deleted PUID auto-detect from `docker/init/01-user-setup.sh`. Its commit message says why: reading `PUID` from the data owner made upgrading users run as UID 102, which "broke host-side access (SSH, WinSCP), made existing DATA_DIR files unwritable, and failed comskip on recordings created before the change." The file now reads `export PUID=${PUID:-1000}` under a comment saying `02-postgres.sh` performs the 102→1000 migration.

So the two scenarios grep for `PUID not set`, a string that no longer exists in any product file, and assert the data stays at UID 102, which the product now deliberately refuses to do. **Do not delete them.** Their subject — an upgrade onto foreign-UID data with no `PUID` set — is a real user's path and is still worth covering. Only their expectation is stale.

- [ ] **Step 1: Rename and rewrite `test_upgrade_auto_adapt`**

Rename the function to `test_upgrade_default_puid`, set `CURRENT_SCENARIO="upgrade_default_puid"`, and update the `SCENARIOS` array entry. Replace the section title and the assertion block:

```bash
# Verifies an upgrade onto foreign-UID data with NO PUID set. The product
# defaults PUID to 1000 and MIGRATES the data to match, rather than adapting
# itself to the data.
#
# This scenario used to be `upgrade_auto_adapt` and asserted the opposite:
# that PUID was read from the data owner and the data left at UID 102. That
# feature existed, and `7e221720` ("fix: remove PUID auto-detect") deleted it
# on purpose — running as UID 102 broke host-side access, made existing
# DATA_DIR files unwritable, and failed comskip. The suite arrived in
# `52ed0fc1`, the same PR that ADDED auto-detect, and was never updated, so
# these assertions have been red on every CI run the suite has ever had.
# Renamed rather than repaired in place: a scenario called `auto_adapt` that
# asserts the absence of auto-adapt is how the next reader concludes the
# product regressed.
test_upgrade_default_puid() {
    CURRENT_SCENARIO="upgrade_default_puid"
    section "Upgrade — foreign-UID data, no PUID (defaults to 1000, migrates)"
    …
    setup_old_pg_data_manual "$vol"

    # No PUID/PGID — 01-user-setup.sh defaults both to 1000.
    docker run -d --name "$name" \
        -e DISPATCHARR_ENV=aio \
        -v "${vol}:/data" \
        "$IMAGE_NAME" >/dev/null

    if wait_for_ready "$name"; then
        check_ownership "$name" "/data/db" "1000" "1000"
        check_ownership "$name" "/data/db/PG_VERSION" "1000" "1000"
        check_pg_accessible "$name" "dispatch"
        check_no_permission_errors "$name"
        check_migrations_done "$name"
        check_log_contains "$name" "Migrating PostgreSQL data ownership" \
            "Ownership migration logged (default PUID)"
        check_log_absent "$name" "PUID not set" \
            "No auto-detect (removed by 7e221720)"
    else
        log_fail "Container failed to start"
    fi
    …
}
```

The `check_log_absent "PUID not set"` line is not padding: it is what turns this scenario into a regression guard for the *removal*. If auto-detect ever comes back, this goes red and names the commit that took it out.

- [ ] **Step 2: Rename and rewrite `test_bind_mount_auto_adapt` the same way**

Rename to `test_bind_mount_default_puid`, `CURRENT_SCENARIO="bind_mount_default_puid"`, section title `"Bind mount upgrade — foreign-UID data, no PUID (defaults to 1000, migrates)"`. Keep its existing `initdb`-inside-`$IMAGE_NAME` seeding untouched — it already produces foreign-UID data correctly, which is why the sibling `bind_mount_upgrade` passes. Replace the three assertions:

- the hand-rolled `expected_uid="102"` block → `check_ownership "$name" "/data/db/PG_VERSION" "1000" "1000"`;
- `check_log_contains … "PUID not set"` → `check_log_absent … "PUID not set"` with the same "removed by 7e221720" description;
- `check_log_absent … "Migrating PostgreSQL data ownership"` → `check_log_contains …`, description `"Bind mount ownership migration logged (default PUID)"`.

Carry Step 1's comment across in short form, pointing at Step 1's full version rather than duplicating it.

- [ ] **Step 3: Update the file's header scenario list**

`test-puid-pgid.sh` lines ~30–45 carry a scenario catalogue in comments (`upgrade_auto_adapt    Upgrade from old UID 102 data, no PUID set (auto-detect)` and `bind_mount_auto_adapt Auto-adapt PUID on bind mount (no migration)`). Rewrite both lines to match the new names and behaviour. Verify none of the old names survives anywhere:

```bash
grep -n "auto_adapt\|auto-adapt\|PUID not set" docker/tests/test-puid-pgid.sh
```

Expected: only the two `check_log_absent "PUID not set"` assertions and the explanatory comments.

- [ ] **Step 4: Run both scenarios**

```bash
bash docker/tests/test-puid-pgid.sh --skip-build upgrade_default_puid
bash docker/tests/test-puid-pgid.sh --skip-build bind_mount_default_puid
```

**Verification:** `Failed: 0` on both.

---

### Task 4: The TLS certificate directory, and the product defect behind it

Implements **D6**, triage row **T3**. All seven TLS failures.

**Files:**
- Modify: `docker/tests/test-tls-postgres.sh`
- File one issue on `D10Scot/Dispatcharr`

**Context the implementer needs:**

Per **G12-R3**, `generate_test_certs` does `CERT_DIR=$(mktemp -d)` — mode 0700, owned by the invoking host user — and bind-mounts it at `/certs`. The app container reads it as `dispatch` (UID 1000, via `su - "$POSTGRES_USER"`), which on Linux cannot traverse a 0700 directory owned by someone else. `dispatcharr/settings.py`'s `_validate_tls_cert_paths` then cannot `stat` `ca.crt` and the container dies at import. On Docker Desktop the bind mount is presented permissively, which is why this passes on a Mac and has failed every CI run.

Only the *directory* needs changing. `openssl` writes the `.crt` files 644 under its default umask; the client key is 600 and is copied out as root by `docker/init/00-fix-pg-ssl-key.sh`; the server keys are consumed by the `postgres` and `redis` containers, which copy and chown their own.

- [ ] **Step 1: Make the certificate directory traversable**

Immediately after `CERT_DIR=$(mktemp -d)` in `generate_test_certs`:

```bash
    # 0755, because mktemp -d gives 0700 owned by the invoking user and the
    # app container reads /certs as `dispatch` (UID 1000, via su -). On a
    # Linux runner UID 1000 cannot traverse it, so settings.py's
    # _validate_tls_cert_paths cannot stat ca.crt and every TLS scenario dies
    # at import with `PermissionError: [Errno 13] … '/certs/ca.crt'`. That is
    # 7 of this suite's 8 scenarios; the eighth,
    # modular_no_tls_regression, is the only one that mounts nothing and the
    # only one that has ever passed.
    #
    # Invisible on Docker Desktop, which presents bind mounts permissively —
    # which is exactly why this survived into CI. A real deployment mounts a
    # secret the application user can read, so this makes the scenarios test
    # what they were written to test rather than testing the host's umask.
    chmod 755 "$CERT_DIR"
```

- [ ] **Step 2: File the product defect** (F12a, D3)

`_validate_tls_cert_paths` exists, by its own docstring, to "raise `ImproperlyConfigured` with a clear message identifying the service and missing file so operators can fix their environment". It tests only `Path(file_path).is_file()`, which **raises** `PermissionError` on an unreadable path rather than returning `False`. An operator mounting a Kubernetes secret or a `:ro` volume the app user cannot traverse gets a raw traceback at Django import time — the outcome the function was written to prevent.

```bash
gh issue create --repo D10Scot/Dispatcharr \
  --title "TLS cert validation raises a raw PermissionError instead of its own ImproperlyConfigured when the app user cannot read the file" \
  --label bug \
  --body '…'
```

The body must state: the function and file (`_validate_tls_cert_paths`, `dispatcharr/settings.py`), that `Path.is_file()` raises rather than returning `False` on `EACCES`, the exact traceback from the CI artifact, the real-world trigger (Kubernetes secrets and `:ro` mounts owned by root at 0600/0700, which `docker/init/00-fix-pg-ssl-key.sh` already exists to work around for the *key* but not for the CA or client certificate), and the one-line shape of the fix (catch `OSError` and raise the same `ImproperlyConfigured` with the reason).

**Do not add a scenario reproducing it** (D3). Add a comment at the `chmod` in Step 1 naming the issue number instead, one line:

```bash
    # (The traceback that got us here is also a product defect in its own
    # right — see D10Scot/Dispatcharr#NNN. Not reproduced here: a bash suite
    # has no test.fail(), so a scenario written to fail would put this
    # workflow straight back where it was.)
```

- [ ] **Step 3: Run the suite**

```bash
bash docker/tests/test-tls-postgres.sh --skip-build
```

**Verification:** `Passed: 12  Failed: 0` (the 5 assertions that already passed, plus one per newly-passing scenario, plus whatever downstream assertions those scenarios reach once their container starts — record the actual number in the PR body rather than asserting a predicted one here). No `PermissionError` anywhere in the output.

---

### Task 5: `pg_major_upgrade` — reproduce under the decision rule

Implements **D8**, triage row **T4**. The one failure the spec does not classify.

**Files:**
- Possibly modify: `docker/tests/test-puid-pgid.sh`
- File one issue on `D10Scot/Dispatcharr` (unconditionally — see Step 4)

**Context the implementer needs:**

Per **G12-R4**, the scenario times out waiting for `uwsgi started with PID` after 300s. The sibling `pg_upgrade_post_puid` exercises the same `pg_upgrade` path and **passes**; the only material difference is that it seeds its PG 16 cluster inside `$IMAGE_NAME` (Ubuntu 24.04, glibc 2.39) whereas `pg_major_upgrade` seeds from the official `postgres:16` image, which has moved to a base with glibc 2.41. The surviving log lines are all `collation version mismatch` warnings naming `dispatcharr` — which proves `pg_upgrade` *did* transfer the old cluster, so the upgrade itself did not silently fall back to the fresh one.

Tasks 1 and 4 have already changed the environment this runs in: the volume leak is gone (so disk pressure at scenario 17 is much lower) and the log tail is 200 lines with the collation noise filtered (so the entrypoint's own output now survives into the artifact).

- [ ] **Step 1: Reproduce, with the improved diagnostics**

```bash
docker build -t dispatcharr:puid-test -f docker/Dockerfile .
bash docker/tests/test-puid-pgid.sh --skip-build pg_major_upgrade
```

Run it **alone**, which is the point of the positional-scenario argument: alone there is no accumulated disk pressure at all, so a pass here and a fail in the full run localises the cause immediately.

- [ ] **Step 2: Apply the decision rule**

Read the last entrypoint line that reached stdout and decide, in writing, in the PR body:

| Observation | Class | Action |
|---|---|---|
| Passes alone but fails in the full run | **CI-environment defect** | Raise this scenario's own `wait_for_ready` budget above 300s and say in a comment that the budget is for accumulated runner load. Record the full-run timing in the PR body. |
| Passes with a longer budget | **CI-environment defect** | Same. |
| The entrypoint's last line is inside `docker/init/02-postgres.sh` — it stops after `Running pg_upgrade from …`, after `Upgrade complete.`, or at a `pg_ctl`/`apt remove` — and never reaches `Starting Postgres...` | **Product defect** | File an issue naming the exact line, then quarantine: replace the scenario body's assertions with `log_skip "pg_major_upgrade: quarantined pending D10Scot/Dispatcharr#NNN — <one-line symptom>"` and a comment. **The `log_skip` message must name the issue number**; a quarantine that does not is not green. |
| `manage.py migrate` or `collectstatic` is the last thing reached and never returns | **Product defect** | Same as above. Note in the issue that the seeded cluster carries a newer glibc collation version than the runtime, since that is the most likely mechanism and the issue should say so rather than making the next reader rediscover it. |

**"Delete the scenario" is not an acceptable outcome.** Neither is "leave it red".

- [ ] **Step 3: If the cause is the seed image's glibc, pin it — do not switch to the sibling's seeding**

`postgres:16` is a floating tag and its base moved under this repository; that is precisely what `lifecycle-tests.yml`'s `schedule:` trigger exists to catch. If Step 2 lands on the collation mismatch, the correct fix is to pin `postgres:16` to a digest resolved with `docker buildx imagetools inspect postgres:16` (per `CLAUDE.md`'s supply-chain rules: tag for readability, digest enforced, never hand-typed) and to say in a comment that the pin is load-bearing for collation compatibility with the AIO image's glibc. Rewriting the scenario to seed from `$IMAGE_NAME` would make it a duplicate of `pg_upgrade_post_puid` and delete the only coverage of upgrading from a cluster this project did not create.

- [ ] **Step 4: File the `pg_upgrade` exit-status defect regardless of Step 2's outcome** (F12b, D3)

Independent of what causes this scenario's timeout, `docker/init/02-postgres.sh` runs:

```bash
su - "$POSTGRES_USER" -c "$NEW_BINDIR/pg_upgrade -U $_install_user -b $OLD_BINDIR -B $NEW_BINDIR -d $POSTGRES_DIR -D $NEW_POSTGRES_DIR"
mv "$POSTGRES_DIR" "${POSTGRES_DIR}_backup_${CURRENT_VERSION}_$(date +%s)"
mv "$NEW_POSTGRES_DIR" "$POSTGRES_DIR"
…
echo "Upgrade complete. Old data directory backed up."
```

The `pg_upgrade` exit status is never checked, and the two `mv`s run regardless — so a failed upgrade is promoted to a normal-looking boot on a freshly `initdb`'d, empty cluster, announced as `Upgrade complete.` The `apt install` two blocks above **does** check (`if [ $? -ne 0 ]`), so this is a local omission, not a house style. The user-visible outcome is total silent data loss on a PostgreSQL major upgrade.

```bash
gh issue create --repo D10Scot/Dispatcharr \
  --title "A failed pg_upgrade is reported as 'Upgrade complete' and the empty new cluster replaces the old data" \
  --label bug \
  --body '…'
```

The body names the file, the three lines, the contrast with the checked `apt install` above it, and the consequence. No scenario reproduces it (D3).

**Verification:** `bash docker/tests/test-puid-pgid.sh --skip-build` reports `Failed: 0`, with any quarantined scenario's `log_skip` naming its issue.

---

### Task 6: Both suites green, end to end

**Files:** none — this is a measurement task, and it is a checkpoint the plan does not proceed past.

- [ ] **Step 1: Full local run of both suites**

```bash
docker build -t dispatcharr:puid-test -f docker/Dockerfile .
docker tag dispatcharr:puid-test dispatcharr:tls-test
bash docker/tests/test-puid-pgid.sh   --skip-build 2>&1 | tee /tmp/g12-puid.log
bash docker/tests/test-tls-postgres.sh --skip-build 2>&1 | tee /tmp/g12-tls.log
```

- [ ] **Step 2: Account for every `Skipped` line by line**

```bash
grep -n "⏭" /tmp/g12-puid.log /tmp/g12-tls.log
```

Two are expected and legitimate before this goal: `readonly_rootfs` (`Read-only rootfs: non-PUID failure (expected — needs more tmpfs mounts)`) and anything gated on an unavailable image. Any *new* skip must be a Task 5 quarantine naming its issue. Record the list in the PR body.

- [ ] **Step 3: Confirm nothing leaked**

```bash
docker volume ls | grep -E 'puid_test|tls_test'
docker ps -a    | grep -E 'puid_test|tls_test'
ls -d /tmp/puid_test_bind_* 2>/dev/null
```

All three: no output.

- [ ] **Step 4: Push and read the real workflow run**

Push the branch. `lifecycle-tests.yml`'s `suites` job is now `if: github.event_name != 'pull_request' || needs.changes.outputs.full == 'true'` (G12-R6), so on an ordinary pull request from a branch **not** named `migration/*` the two bash jobs still do not run. Two ways to make them run, and use the second:

- name the implementation branch `migration/…`, which sets `full=true` in the `changes` job — but this is not a migration branch and naming it one to bend a CI condition is exactly the sort of thing that later gets read as fact;
- **dispatch with `full: true`**, which sets the same output for one run without lying about what the branch is.

```bash
gh workflow run lifecycle-tests.yml --repo D10Scot/Dispatcharr \
  --ref test/e2e-lifecycle-depth -f full=true
gh run watch --repo D10Scot/Dispatcharr
```

`-f full=true` is what makes **every** job run: `changes` sets `full=true`, which satisfies both the `suites` condition above and `upgrade-migrations`'s `if: needs.changes.outputs.lifecycle == 'true' || needs.changes.outputs.full == 'true'`. Substitute the real implementation branch name for `test/e2e-lifecycle-depth` — the spec branch `docs/e2e-g12-spec` an earlier draft of this plan named has merged and no longer exists. `workflow_dispatch` requires the workflow file to be on the default branch, which it is.

**Verification:** both matrix jobs exit 0. Attach both suite-log artifacts to the PR body. **This is the definition of green (spec, § Triage) and Tasks 7–11 do not start until it holds.**

---

# Piece B — durable state, from rows to relations

### Task 7: Seven relations in `durable-state.ts`

Implements **D10**, **D11**, **D12**, **D13**, **D16**.

**Files:**
- Modify: `e2e/tests/lifecycle/durable-state.ts`
- Modify: `e2e/tests/lifecycle/upgrade-migrations.spec.ts` (one call-site argument only)
- Modify: `e2e/tests/lifecycle/restart-persistence.spec.ts` (one call-site argument only)

**Interfaces:**
- `seedDurableState(api, seed, upstream)` — gains a third parameter, the `upstream` fixture.
- `assertDurableState(api, request, state, opts?)` — gains the `request` context (for the XC credential check and the logo bytes, both of which must bypass `ApiClient`'s retry) and `opts?: { logoBytes?: boolean }`, defaulting to `true`.
- `DurableState` gains: `streams`, `channelProfileMembership`, `epgProgrammeTitles`, `xcUser`, `movie`, `series`, `episode`, `recording`, `logo`.

**Context the implementer needs:**

Three properties of the existing file are load-bearing and must survive, and the extended header must restate them:

1. **Serial by construction.** The lifecycle projects run one worker with `fullyParallel: false`. That is what makes creating an M3U account and an EPG source safe on a container `bootstrap` has never pre-warmed — two concurrent creates would both insert an `IntervalSchedule` row and brick the instance permanently ([#7](https://github.com/D10Scot/Dispatcharr/issues/7)). This task adds an **XC** M3U account as well, so the property becomes more important, not less.
2. **Postgres-backed only.** Nothing here may assert Redis state.
3. **By id, against a value recorded at creation.** Never a count on an unfiltered list.

The genuinely new hazard is **G12-R8**: `instance.restart()` stops the provider container, and `ScenarioRegistry` is an in-memory `Map`, so **every upstream scenario is forgotten between seeding and asserting**. Every assertion below reads Dispatcharr's own database through Dispatcharr's own API. The obvious next extension anyone would reach for — re-refresh the account and compare — is the one thing that cannot work here, and the file must say so in a comment so nobody adds it.

Two API facts that are easy to get wrong:

- **EPG programmes need a channel association** (F9). `seed.upstreamEpgSource` returns a source with `EPGData` rows and **zero `ProgramData`**; `parse_programs_for_source` gates on a Channel pointing at an `EPGData` row. Associate with `POST /api/channels/channels/<id>/set-epg/`, then poll `/api/epg/programs/search/?channel_id=<id>`.
- **Channel Profile membership is a toggle, not an add.** `create_profile_memberships`, a `post_save` receiver on `ChannelProfile`, bulk-creates a membership for **every** channel that exists when the profile is created, and `ChannelProfileSerializer.channels` lists the ids of **enabled** memberships. So the durable relation to record is a *disabled* one: `PATCH /api/channels/profiles/<pid>/channels/<cid>/ { enabled: false }` and then assert the channel is **absent** from `profile.channels` after the event. A membership that defaulted back to enabled is exactly the loss this row exists to catch, and asserting the default-enabled state would catch nothing. See `e2e/tests/seeded/channel-profiles.spec.ts` for the shape.

- [ ] **Step 1: Extend `seedDurableState`'s signature and the upstream scenario**

Take `upstream: UpstreamClient` as a third parameter. Create one XC scenario carrying two live channels, one VOD category with one movie, and one series category with one series with one season with one episode — the literal shape `e2e/tests/seeded/vod-catalogue-ingest.spec.ts` uses, including `containerExtension: 'mp4'`, `tmdbId: null`, `imdbId: null` (the fixture types declare those required where the provider's own parser defaults them).

Name everything from `seed.generatedName(...)` so the search queries below are runToken-scoped and rule 6 holds.

- [ ] **Step 2: Channel → Streams, in order** (D12)

```ts
const { channel, streams } = await seed.upstreamChannel(scenario, {
  channelIds: [1, 2],
  channel: { channel_number: CHANNEL_NUMBER },
});
```

Two streams, not one: `Channel.streams` is ordered through `ChannelStream` and the order decides which upstream is primary and which is the failover target. A single-stream channel cannot distinguish "the link survived" from "the ordering survived", and ordering is the half a migration is likelier to lose. Record `streams.map(s => s.id)`; assert with `toEqual` (deep, order-sensitive), never `toContain`.

This replaces the bare `seed.channel(...)` currently at the top of `seedDurableState`. Keep the existing `expect(channel.channel_number).toBe(CHANNEL_NUMBER)` guard — its comment explains that without it the explicit `channel_number` would be compared to itself.

- [ ] **Step 3: Channel Profile membership**

Create the Channel Profile **after** the channel (the receiver is what enrols it), then disable the membership and record that. Assert after the event that `profile.channels` does **not** contain the channel id, with a message saying a re-enabled membership means the M2M row was lost and the receiver re-created it.

- [ ] **Step 4: EPG programme rows**

`seed.upstreamEpgSource(scenario)`, then `POST /api/channels/channels/<id>/set-epg/`, then `waitFor.resource` on `/api/epg/programs/search/?channel_id=<id>` until at least one row appears. Record the returned programme **titles** (a small array), and after the event assert every recorded title is still present for that `channel_id`. Not a count.

This replaces the bare `seed.epgSource(...)` currently in the function.

- [ ] **Step 5: An XC user whose credentials still authenticate**

`seed.xcUser()`. After the event, `request.get('/player_api.php?username=…&password=…')` — **the raw `request` context, not `ApiClient`**, for the same reason `assertAdminTokenStillValid` uses it: `ApiClient` refreshes and retries on a 401, which would mask exactly this. Assert the response's `user_info.auth === 1`.

Note for the implementer: the XC username **is** the Django username; there is no `xc_username` custom property (`XcUser`'s doc comment in `e2e/fixtures/types.ts` establishes this against three call sites in the product). `UserSerializer` does not return `custom_properties`, which is why `xcPassword` is carried on the returned object rather than read back.

- [ ] **Step 6: VOD movie, series and episode**

`seed.xcAccount(scenario, { enable_vod: true })`, then `waitFor.m3uRefreshComplete`, then poll `/api/vod/movies/?search=<prefix>` and `/api/vod/series/?search=<prefix>`. The M3U refresh reaching `success` says **nothing** about VOD — `refresh_vod_content` is fired with `.delay()` after it returns — so poll for the rows, with the 120s budget `vod-catalogue-ingest.spec.ts` uses.

Episodes are **not** part of the refresh: `GET /api/vod/series/<pk>/provider-info/` is a separate, synchronous, on-demand call that creates them. Route it through `api.json` so a 5xx surfaces there rather than two calls later.

After the event assert all three by id, and additionally that `episode.series.id` still equals the recorded series id — the episode→series foreign key is the relation, and reading the episode row alone would not prove it.

- [ ] **Step 7: A scheduled Recording**

`POST /api/channels/recordings/` with `{ channel: <id>, start_time, end_time }` as ISO 8601 strings well in the future (an hour out is plenty; `RecordingSerializer.validate` makes naive datetimes aware, so send them with an explicit offset and avoid the question). Record the id; assert it reads back with the same `channel`.

**Do not let it fire.** A recording that actually runs is G13's whole subject; here the row is a durable-state relation and nothing more. Choose a start time far enough out that no plausible test duration reaches it, and say so in a comment.

- [ ] **Step 8: Logo bytes** (D16)

`seed.logo()`, then after the event `request.get(logo.cache_url)` and
`expect((await served.body()).equals(logoPayload(logo.name))).toBeTruthy()` — the exact assertion `e2e/tests/seeded/logo-upload.spec.ts` makes, and for the reason its comment gives: the payload is unique per name, so byte equality proves both that the file survived and that `cache_url` resolved to the right row.

Gate it behind `opts.logoBytes ?? true`, with this comment:

```ts
// The only assertion in this file that leaves the database, and the only
// one the restore spec must switch off. A version-2 backup archive holds
// `database.dump` and `metadata.json` and no files at all
// (`create_backup`, apps/backups/services.py) — the docstring's "and data
// directories" is stale. So across a restore the Logo *row* comes back with
// the dump while these bytes were never in the archive and were never
// removed: the assertion would pass for entirely the wrong reason, and would
// start failing the day backups learn to carry files. Across a restart or an
// upgrade it is exactly right, because there the question is whether /data
// survived.
```

- [ ] **Step 9: Update both call sites**

`restart-persistence.spec.ts` and `upgrade-migrations.spec.ts` each call `seedDurableState(api, seed)` and `assertDurableState(api, state)`. Add the `upstream` fixture to each test's destructured arguments and pass it; pass `request` to the assertion. Neither spec's structure, ordering or existing assertions change — the `(d)`-first guards (`startedAt` moved; image id changed) stay exactly where they are, ahead of everything else.

- [ ] **Step 10: Extend the two `@characterization:` comments — do not retag** (constraint 11)

Both specs already carry `{ tag: '@characterization' }` at HEAD (`restart-persistence.spec.ts:23`, `upgrade-migrations.spec.ts:163`), and both are already on `CONTAINER_LIFECYCLE.allow`. **Change neither tag and add neither path.** What this task owes is one sentence in each existing `@characterization:` comment, saying that the relations now asserted are the portable half — rows, orderings, foreign keys and file bytes surviving a container event is behaviour any rewrite must preserve — while the coupled half is unchanged and is what the tag is for: the AIO container being the unit of restart in one file, `manage.py showmigrations` output and the image layout in the other.

Do **not** add a `GLOBAL_SETTINGS_WRITE` entry. `durable-state.ts` is already on that list for its `system_settings` PATCH, and none of the seven relations touches `/api/core/settings/` (constraint 12).

- [ ] **Step 11: Typecheck and run**

```bash
cd e2e && npm run typecheck
cd e2e && npm run test:lifecycle
DISPATCHARR_E2E_BASELINE_IMAGE=ghcr.io/d10scot/dispatcharr:<a real ancestor sha> npm run test:lifecycle-upgrade
```

**Verification:** both specs pass. Then prove the new assertions are not vacuous: temporarily reverse one recorded stream-id array before asserting, confirm the test fails naming the ordering, and revert. Do the same for the disabled Channel Profile membership. Record both mutations in the PR body — this is the same discipline `m3u-ingest.spec.ts`'s source-scan comment records, and it is what distinguishes an assertion from a decoration.

---

# Piece C — backup restore

### Task 8: `backup-restore.spec.ts` and the `lifecycle-restore` project

Implements **D14**, **D15**, **D16**. Closes `COVERAGE.md`'s "Backups: restore" row.

**Files:**
- Create: `e2e/tests/lifecycle/backup-restore.spec.ts`
- Modify: `e2e/playwright.config.ts`
- Modify: `e2e/package.json`
- Modify: `e2e/tests/guards/allowlist.ts` — add `'tests/lifecycle/backup-restore.spec.ts'` to `CONTAINER_LIFECYCLE.allow`, with a one-line comment saying it owns and resets a container. `capabilities.spec.ts` compares with `toEqual`, so omitting this fails the `guards` job (constraint 12).

**Context the implementer needs:**

The endpoints (`apps/backups/api_urls.py`):

| | |
|---|---|
| `POST /api/backups/create/` | 202 + `{ task_id }` |
| `GET /api/backups/` | list of `{ name, size, created }` |
| `GET /api/backups/status/<task_id>/` | task state; accepts a token as well as a session |
| `POST /api/backups/<filename>/restore/` | 202 + `{ task_id, task_token }` |

`restore_backup_task` (`apps/backups/tasks.py`) calls `services.restore_backup` then `call_command('migrate', '--noinput')`. `_restore_postgresql` runs `_clean_postgresql_schema` — `DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;` — before `pg_restore --no-owner`. That is why this needs its own instance: it replaces the database under everything else in the container.

The `task_token` in the restore response exists precisely because a restore can invalidate the caller's session; poll with it.

`create_backup` derives the archive name from the clock at **second** granularity and `list_backups` globs the directory. On this isolated instance only one backup is ever created, but still match the archive by the name the create returned rather than taking `results[0]` — rule 6, and the same race `e2e/playwright.config.ts`'s `frontend` project confines to one worker.

- [ ] **Step 1: Add the project**

In `e2e/playwright.config.ts`, after `lifecycle-upgrade`:

```ts
    {
      // Owns its container: a restore runs `DROP SCHEMA public CASCADE`
      // (`_clean_postgresql_schema`, apps/backups/services.py) and replaces
      // every row in the database. On the shared instance that lands under
      // every parallel worker mid-run and under every other project sharing
      // the container locally — which is what `COVERAGE.md`'s restore row
      // has said since G7, and why it stayed `todo` until there was an
      // instance to put it on.
      name: 'lifecycle-restore',
      testDir: './tests/lifecycle',
      testMatch: /backup-restore\.spec\.ts$/,
      workers: 1,
      fullyParallel: false,
      // One boot, a pg_dump, a schema drop, a pg_restore and a migrate.
      // Sized above `fixtures/instance.ts`'s own subprocess timeouts (720s
      // per e2e_up.sh call) for the reason `lifecycle` documents: whichever
      // fires first decides whether a failed boot arrives with the
      // container's logs or with a bare Playwright timeout.
      timeout: 900_000,
      // Attempt 1 consumes the state attempt 2 would need — it resets the
      // volume and provisions the superuser. Same reasoning as `lifecycle`.
      retries: 0,
    },
```

Add `"test:lifecycle-restore": "playwright test --project=lifecycle-restore"` to `e2e/package.json`, and extend the `test` script's guidance string to name it.

- [ ] **Step 2: Write the spec**

Shape, with `instance`, `request`, `baseURL`, `upstream` fixtures and `testInfo`:

1. `await instance.up({ reset: true })` — this spec owns the container and its volume. `reset` also recreates the provider (`destroy()` in `scripts/e2e_up.sh` removes it), so seed **after** this call, never before.
2. `provisionAdmin(request, baseURL!)`, then a fresh `ApiClient` and `Seeder` — **not** the `api`/`seed` fixtures, which read `playwright/.auth/`, written by `bootstrap`, which this project does not depend on and must not. Copy the reasoning comment from `restart-persistence.spec.ts` rather than rewriting it.
3. `const state = await seedDurableState(api, seed, upstream)` — state **A**.
4. `POST /api/backups/create/`; poll `/api/backups/status/<task_id>/` to completion; find the archive in `GET /api/backups/` **by the name the create reported**.
5. Mutate to state **B**, both halves (D14):
   - create a second channel with a distinct generated name and record its id;
   - `DELETE` one of A's rows — the `Recording` is the cheapest choice with no cascade surprises; record that it is gone with a 404 before restoring.
6. `POST /api/backups/<filename>/restore/`; poll `/api/backups/status/<task_id>/` with the returned `task_token`.
7. Assert with polling (D15), because pooled connections reconnect after the schema drop:
   - **A is back**: `assertDurableState(api, request, state, { logoBytes: false })` — the opt-out is D16 and the helper's own comment explains it;
   - the deleted `Recording` reads back by its original id;
   - **B is gone**: `GET /api/channels/channels/<bId>/` is 404.
8. `finally`: attach `instance.logs(300)` on failure **before** `instance.down()`, exactly as `upgrade-migrations.spec.ts` does — the workflow's own `failure()` step runs after teardown has removed the container. Swallow a throw from `down()` so it cannot replace the assertion error.

The header comment must carry, in this order: the `COVERAGE.md` row it closes; why the instance is its own (the schema drop); why both halves of the A/B assertion are needed (a restore that never ran passes "A is back"; a restore that flushed without restoring passes "B is gone"); and D15's rule — **if in-place recovery genuinely does not work, that is a finding to file and pin with `test.fail()`, not a licence to add a container restart until the test goes green.**

- [ ] **Step 3: Typecheck and run**

```bash
cd e2e && npm run typecheck
cd e2e && npm run test:lifecycle-restore
```

**Verification:** passes. Then prove it is not vacuous: skip the restore call entirely and confirm the test fails on **A is back** *and* on **B is gone** (two independent failures, not one). Revert and record it in the PR body.

---

# Piece D — refresh-interval and cron scheduling

### Task 9: `refresh-scheduling.spec.ts` and the `lifecycle-scheduling` project

Implements **D17**, **D18**, **D19**, **D21**. Closes `COVERAGE.md`'s "Refresh-interval scheduling" row and G3's D10 debt.

**Files:**
- Create: `e2e/tests/lifecycle/refresh-scheduling.spec.ts`
- Modify: `e2e/playwright.config.ts`
- Modify: `e2e/package.json`
- Modify: `e2e/tests/guards/allowlist.ts` — add `'tests/lifecycle/refresh-scheduling.spec.ts'` to `CONTAINER_LIFECYCLE.allow` (constraint 12). Nothing else on the five lists changes: `instance.manage(['dumpdata', …])` contains none of `CONTAINER_INTROSPECTION`'s three literals, and the fixture use is what `CONTAINER_LIFECYCLE` polices.
- Modify: `e2e/README.md` (the enumerated interval set — Task 11 does the rest of the docs, but this one edit belongs with the values that need it)

**Context the implementer needs:**

`create_or_update_periodic_task` (`core/scheduling.py`) computes `should_be_enabled = enabled and (use_cron or interval_hours > 0)`. So `refresh_interval: 0` yields a **disabled** `PeriodicTask` — which is why the whole rest of the suite can use 0 safely — and anything else yields one that keeps re-refreshing the account for the life of the container. On these lifecycle instances that is doubly intolerable: per **G12-R8** the provider will have forgotten the scenario the account points at, so a background refresh would mutate rows under whatever is asserting.

The interval branch does `IntervalSchedule.objects.get_or_create(every=max(int(interval_hours), 1) if interval_hours else 1, period=IntervalSchedule.HOURS)` — the smallest schedulable unit is one hour, so **nothing here waits for a tick** (D18).

Two observation routes, and the split between them is the second purpose of this task (D19):

- **Black-box.** `M3UAccountSerializer` and `EPGSourceSerializer` both expose `cron_expression` as a plain `CharField` whose `to_representation` reads it back off `instance.refresh_task.crontab` — both files' comments call it the "single source of truth". So a REST round-trip *is* a proof that a `CrontabSchedule` exists and is linked to the `PeriodicTask`. `refresh_interval` round-trips too.
- **Grey-box.** `PeriodicTask.enabled`, `IntervalSchedule.every` and orphan cleanup have no REST surface. Per **G12-R7**, `instance.manage(['dumpdata', 'django_celery_beat.PeriodicTask', 'django_celery_beat.IntervalSchedule', 'django_celery_beat.CrontabSchedule', '--format=json'])` passes the argument filter intact (every token matches `^[A-Za-z0-9._/=-]+$`), and `manage.py` prints a banner to stdout first, so parse from the first `[`.

**#7's pre-warm rule** (D21). `e2e/README.md`'s "Non-zero `refresh_interval` values, and what they cost" says any non-zero value used from a parallel test must be unique per test and never pre-warmed from a worker, because a concurrent create duplicates the `IntervalSchedule` row and every later M3U/EPG create 500s permanently with no API able to repair it. This project runs `workers: 1`, `fullyParallel: false`, on an instance nothing else touches, and declares no `bootstrap` dependency — so the race is structurally impossible rather than merely avoided. That is **not** a licence to leave the values undocumented: the README says in terms that a stale enumeration is worse than none.

- [ ] **Step 1: Add the project**

```ts
    {
      // Owns its container. A non-zero `refresh_interval` yields
      // `should_be_enabled = true` (`create_or_update_periodic_task`,
      // core/scheduling.py), so the instance ends up with an ENABLED hourly
      // beat task re-refreshing that account for the life of the container.
      // That is why `COVERAGE.md`'s refresh-interval row records this as a
      // direct cost of G3's D10 and why it stayed `todo`: the shared
      // `seeded` instance cannot tolerate it. Nor can `lifecycle` or
      // `lifecycle-upgrade` — the provider forgets its scenarios across a
      // restart (`ScenarioRegistry` is an in-memory Map and
      // `e2e_up.sh --stop` stops the provider), so a background refresh
      // there would mutate rows under the durable-state assertions.
      name: 'lifecycle-scheduling',
      testDir: './tests/lifecycle',
      testMatch: /refresh-scheduling\.spec\.ts$/,
      workers: 1,
      fullyParallel: false,
      timeout: 900_000,
      retries: 0,
    },
```

Add `"test:lifecycle-scheduling"` to `e2e/package.json` and name it in the `test` script's guidance string.

- [ ] **Step 2: Test 1 — portable assertions, REST only**

`instance.up({ reset: true })`, `provisionAdmin`, own `ApiClient`/`Seeder` (same reasoning comment as everywhere else in this directory). Then, for an `M3UAccount` and again for an `EPGSource`:

1. Create with a non-zero `refresh_interval`; read back by id and assert the value persisted rather than being coerced.
2. `PATCH { cron_expression: '<expr>' }`; read back and get the same expression — which proves a `CrontabSchedule` was created and linked.
3. `PATCH { refresh_interval: <another non-zero>, cron_expression: '' }`; read back and get an empty `cron_expression`, proving the task's `crontab` was cleared.

Tag `@characterization`, like every test in this file and for the file-level reason (constraint 11, spec D19): the spec owns and resets a container. Its `@characterization:` comment must say that these particular assertions are the portable ones — `refresh_interval` and `cron_expression` are REST round-trips that any behaviour-preserving rewrite must keep — and that the tag is fixed by the container ownership, not by them. Also state in a comment that step 2's assertion is *not* a tautology: `cron_expression` is not a model field, it is derived from `refresh_task.crontab` on every read. Cite the serializer comment that says so, because a reader who assumes it is a stored column will conclude this test proves nothing.

- [ ] **Step 3: Test 2 — coupled assertions, via `dumpdata`**

Same instance (the project is serial, so the second test runs against the state the first left; if that coupling is uncomfortable, seed fresh names — do **not** add a second `up({ reset: true })`, which would cost another boot).

Write a small local helper that runs the `dumpdata` call, slices from the first `[`, and `JSON.parse`s. Then assert:

- the `PeriodicTask` named for the account exists, `fields.enabled === true`, and its `fields.interval` resolves to an `IntervalSchedule` whose `every`/`period` match what `create_or_update_periodic_task` computes for the chosen `refresh_interval`;
- a second source created with `refresh_interval: 0` yields a `PeriodicTask` with `fields.enabled === false` — the other side of `should_be_enabled`, and the reason the rest of the suite can use 0;
- `DELETE`ing the first source removes its `PeriodicTask` and, once nothing else references it, its `IntervalSchedule` (`_cleanup_orphaned_interval`).

The `@characterization:` comment must say: this couples to django-celery-beat's table names and to the AIO container layout because the product exposes no other view of `PeriodicTask.enabled`, and a rewrite that preserved behaviour but changed scheduler is expected to change this test. This is the only test in the goal where the tag would be right on the assertions' own merits.

This is the first use of `instance.manage` from a **spec** rather than from `fixtures/instance.ts`, and G11 already decided what that costs: nothing extra. `CONTAINER_INTROSPECTION` matches only the literals `pgrep`, `docker ` and `manage.py` in string and template literals, and a `dumpdata` argument array contains none of them; the `instance` fixture use is caught by `CONTAINER_LIFECYCLE`, which this file joins in the Files list above. Do not widen any detector.

- [ ] **Step 4: Record the interval values in `e2e/README.md`** (D21)

The section "Non-zero `refresh_interval` values, and what they cost" states the set in use as **{0, 2, 3, 4, 8531, 8532}** and warns that a stale enumeration is worse than none. Add the values this spec uses, and this paragraph:

```markdown
`e2e/tests/lifecycle/refresh-scheduling.spec.ts` uses NNNN and NNNN, and is
the one exception to the uniqueness rule above — deliberately, and only
because of where it runs. The `lifecycle-scheduling` project is `workers: 1`,
`fullyParallel: false`, on an instance it creates with
`up({ reset: true })` and nothing else touches, and it declares no
`bootstrap` dependency. There is no concurrent create, so the #7 race is
structurally impossible rather than merely avoided, and no pre-warm is
needed or possible (`bootstrap` never runs against that container). **Move
this spec to a shared project and the exemption is gone**: the values would
then need to be unique per test and the default pre-warmed from `bootstrap`,
exactly as above.
```

- [ ] **Step 5: Typecheck and run**

```bash
cd e2e && npm run typecheck
cd e2e && npm run test:lifecycle-scheduling
```

**Verification:** both tests pass. Prove test 1 step 2 is not vacuous by asserting a *different* cron expression than the one PATCHed and confirming it fails; revert.

---

# Piece E — CI and documentation

### Task 10: Wire the two projects into `lifecycle-tests.yml`

Implements **D22**.

**Files:**
- Modify: `.github/workflows/lifecycle-tests.yml`

**Context the implementer needs:**

The zizmor hook blocks on **every** finding in an edited workflow, legacy included, and the workflows are at zero findings — a ratchet (`CLAUDE.md`). Reuse the pins already in this file verbatim; resolve nothing new:

- `actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0`
- `actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093 # v4.3.0`
- `actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2`
- `actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020 # v4.4.0`

The hook checks `zizmor --version` against the pin in `.github/workflows/actions-lint.yml` and warns on drift; bump both together if it complains, or do nothing if it does not.

- [ ] **Step 1: Add one job running both new projects**

One job, not two: each pays a 3.6 GB `docker load`, and both projects are short. Model it on the existing `upgrade-migrations` job — same `needs: [changes, build]`, same checkout/download/load/setup-node/`npm ci`/`playwright install`/`typecheck` prologue, same `timeout-minutes: 45`, same failure-path log dump and report upload — minus the "Resolve the upgrade baseline" step, which neither project needs.

Give it **the same `if:` as `upgrade-migrations`**, verbatim:

```yaml
    if: needs.changes.outputs.lifecycle == 'true' || needs.changes.outputs.full == 'true'
```

That is what puts both projects in the migration gate: `changes` sets `full=true` for a head branch matching `migration/*` or a `workflow_dispatch` with `full: true`, and sets `lifecycle=true` whenever the PR diff matches its pattern — which already includes `^e2e/tests/lifecycle/`, so both new specs select the job by their own paths.

```yaml
      - name: Run the restore spec
        working-directory: ./e2e
        env:
          E2E_BASE_URL: http://localhost:9191
        run: npx playwright test --project=lifecycle-restore

      # Sequential, and after the restore spec, deliberately: each project
      # calls `up({ reset: true })` and takes the container over, so they
      # cannot overlap. Ordering matters one way only — the scheduling spec
      # leaves an ENABLED hourly beat task behind, and while the job ends
      # before it could ever tick, running it last means no later step in
      # this job shares a container with it.
      - name: Run the scheduling spec
        working-directory: ./e2e
        env:
          E2E_BASE_URL: http://localhost:9191
        run: npx playwright test --project=lifecycle-scheduling
```

Add `if: always()` to the second run step **only if** you want a failing restore spec to still report the scheduling result; the default (skip) is the right choice here because a broken container after restore would make the scheduling failure uninterpretable. Leave the default and say so in a comment.

- [ ] **Step 2: Add the new job to `lifecycle-result`'s `needs:` — this is the step it is easiest to skip**

`lifecycle-result` is the aggregate check, and it reads exactly what it lists:

```yaml
    needs: [changes, build, suites, upgrade-migrations]
```

with a `for result in "$BUILD_RESULT" "$SUITES_RESULT" "$UPGRADE_RESULT"` loop over `success|skipped`. A job absent from `needs:` is invisible to it: the new job could fail while `Lifecycle result` reports green, which is precisely the failure that check exists to prevent (its own header explains the sibling case for `build`). Add the job to `needs:`, add its `${{ needs.<job>.result }}` to the `env:` block, and add that variable to the loop.

- [ ] **Step 3: Check the `push` path filter and the `changes` job pattern**

The workflow's `push` filter already covers `e2e/tests/lifecycle/**`, `e2e/fixtures/**`, `e2e/setup/**` and `e2e/playwright.config.ts` — everything the two new specs touch. **Verify, do not assume**, and add nothing already covered. There is now a second filter to check: the `changes` job's `pattern=` regex, which is what gates a pull request. It matches `^e2e/tests/lifecycle/`, so both new spec files select the job; it does **not** match `e2e/tests/guards/allowlist.ts`, and that is correct — the guards run in `e2e-tests.yml`'s own `guards` job, gated on that workflow's `e2e` output, whose pattern starts `^(apps/|core/|dispatcharr/|frontend/|docker/|scripts/|e2e/|…)` and so matches any `e2e/` path including the allowlist. The `pull_request` trigger here carries no `paths:` any more (G11 moved the filtering into `changes`), so there is nothing to narrow there.

One thing **not** to do in this step. `e2e-tests.yml` carries two project lists and a comment saying "A NEW PROJECT MUST BE ADDED TO BOTH LINES." That rule is about projects that belong in *that* workflow's matrix. `lifecycle-restore` and `lifecycle-scheduling` do not (D22) — they go in the new `lifecycle-tests.yml` job instead, for the same reason `lifecycle-upgrade` does. Adding them to `e2e-tests.yml` would put a container-owning `up({ reset: true })` project into the shared-instance matrix. Leave `e2e-tests.yml` untouched; it is not on this goal's file list.

- [ ] **Step 4: Verify**

```bash
zizmor .github/workflows/lifecycle-tests.yml
```

Expected: zero findings. Then push and dispatch with `full: true`, as in Task 6 Step 4 and for the same reason — without it the `suites` legs skip on anything but a `migration/*` branch:

```bash
gh workflow run lifecycle-tests.yml --repo D10Scot/Dispatcharr \
  --ref test/e2e-lifecycle-depth -f full=true
gh run watch --repo D10Scot/Dispatcharr
```

**Verification:** every job green — `changes`, `build`, both `suites` matrix legs, `upgrade-migrations`, the new restore/scheduling job, and `Lifecycle result`. Confirm `Lifecycle result` actually observed the new job: its step log prints one `name=result` pair per dependency, and the new one must appear there. A green aggregate that never names the job is Step 2 not done.

---

### Task 11: Documentation, ledger, issues

**Files:**
- Modify: `e2e/COVERAGE.md`
- Modify: `e2e/README.md`
- Close `D10Scot/Dispatcharr#41`

- [ ] **Step 1: Flip the two `todo` rows**

Find the two rows by their text, not by line number — G11's edits moved both, and an earlier draft of this plan cited the old positions. Under `Lifecycle`, the row beginning *"Backups: restore — split out of G6's Backups row"* and the row beginning *"Refresh-interval scheduling: a **non-zero** `refresh_interval`"*. Both are attributed to **G7** and marked `todo`. Change the Goal column to **G12** and the Status to `done`, and extend each row's text with what was actually built and what was deliberately left out — the ledger's value is that its rows say more than "done". The table is `| Area | Flow | Goal | Status |` and has **no tag column**, so any tag statement belongs in the row's prose:

- the restore row must record D16: a version-2 archive holds `database.dump` and `metadata.json` and **no files**, so the logo-bytes assertion is opted out there and the docstring's "and data directories" is stale;
- the scheduling row must record D18 (no tick is waited for; the smallest interval is one hour), D19 (both tests are `@characterization` because the file owns a container and is on `CONTAINER_LIFECYCLE`, while the assertion-portability split lives in each test's comment), and D21 (the #7 exemption and its condition).

- [ ] **Step 2: Add the new rows**

Under `Lifecycle`, in the same format:

- the seven relations added to `durable-state.ts`, naming them, and recording **G12-R8** — the provider forgets its scenarios across a restart, so every assertion reads Dispatcharr's own rows and a re-refresh-and-compare extension cannot work;
- the bash triage, as one row per class, with the correction that the disposition's "8 of 126 puid-pgid scenarios" counted assertions: 8 failures across **4** scenarios of 20, and 7 of 8 TLS scenarios;
- two `known-bug` rows for the filed product defects (F12a `_validate_tls_cert_paths`, F12b unchecked `pg_upgrade`), each stating explicitly that **no test reproduces them** and why (D3: a bash suite has no `test.fail()`).

- [ ] **Step 3: `e2e/README.md`**

Beyond Task 9 Step 4's interval paragraph:

- the "Projects" section gains `lifecycle-restore` and `lifecycle-scheduling`, each with one line on why it owns its container;
- the "Container lifecycle" section gains **G12-R8** — that `e2e_up.sh --stop` stops the provider and `ScenarioRegistry` is in-memory, so a restart forgets every scenario. This is a harness fact every future lifecycle spec needs and it is currently written down nowhere;
- the "CI" section gains the new job, with its gating stated as it now is: the same `if:` as `upgrade-migrations`, so it runs on a lifecycle-touching PR and always in full mode (`migration/*`, or a dispatch with `full: true`), and it is counted by `Lifecycle result`.

- [ ] **Step 4: Close #41**

```bash
gh issue close 41 --repo D10Scot/Dispatcharr \
  --comment "Fixed in <PR link>: cleanup_scenario now removes containers in a first pass and volumes/networks in a second, in both test-puid-pgid.sh and test-tls-postgres.sh. A second, distinct leak was found and fixed in the same change — the bind-mount scenarios' cleanup omitted --entrypoint, so the AIO entrypoint ran, died minting a secret key into an unmounted /data (\"mktemp failed\", docker/entrypoint.sh), and the rm -rf never executed, leaking a host directory per bind-mount scenario. Verified: after a full suite run, no puid_test/tls_test volume, container or /tmp directory survives."
```

**#41 only.** [#42](https://github.com/D10Scot/Dispatcharr/issues/42) ("the `instance` fixture is guarded only by a comment") is now answered by `CONTAINER_LIFECYCLE`, and Tasks 8 and 9 add two more files to that list — so the PR body may say so. **Do not close it here:** the mechanism landed in G11, and closing another goal's issue from this PR misattributes it.

- [ ] **Step 5: Self-review**

Walk the spec's Decisions list D1–D22 and confirm each is implemented or explicitly deferred with a reason. Then confirm every Non-goal held — in particular that **no product file was touched**:

```bash
git diff --stat origin/main... -- apps/ dispatcharr/ docker/init/ docker/entrypoint.sh core/
```

Expected: **empty**. If it is not, the change is out of scope regardless of how right it looks.

Then confirm the CI story end to end: the workflow's four jobs green on a `workflow_dispatch` against the branch, both suite-log artifacts attached to the PR body, every `Skipped` line accounted for, and every quarantine naming its issue.

---

## Definition of done

1. `lifecycle-tests.yml` is green on a `gh workflow run … -f full=true` run against the implementation branch: `changes`, `build`, both `suites` legs, `upgrade-migrations`, the new restore/scheduling job, and `Lifecycle result` — with the new job named in `Lifecycle result`'s own output.
2. Both bash suites report `Failed: 0`; every `Skipped` is accounted for in the PR body and every quarantine names an issue.
3. `durable-state.ts` asserts seven relations in addition to its seven scalar rows, and both lifecycle specs get them.
4. `backup-restore.spec.ts` and `refresh-scheduling.spec.ts` pass, each on its own instance, each in its own project.
5. Every new `test(` carries `{ tag: '@characterization' }` as an inline object literal with a `// @characterization:` comment above it, both new spec paths are on `CONTAINER_LIFECYCLE.allow`, and `npx playwright test --project=guards` passes.
6. Two product issues filed with `--repo D10Scot/Dispatcharr`; #41 closed; #42 referenced but not closed; no product file modified.
7. `COVERAGE.md`'s two G7 `todo` rows are `done` and attributed to G12; the new rows are written.
8. `cd e2e && npm run typecheck` is clean; `zizmor .github/workflows/lifecycle-tests.yml` reports zero findings.
9. Every mutation check named in Tasks 7, 8 and 9 was run and its result recorded in the PR body.

**Not in this goal, and stated so the PR body can say it out loud:** adding `Lifecycle result` to the Main ruleset. This goal is what makes that possible — the workflow's header says the check "must not be added to the Main ruleset until G12 leaves both bash suites green" — but a ruleset is a repository setting, not a file in this diff. **The follow-up is the maintainer's**, and the PR body should name it as the next step rather than leave a green run looking like a finished gate.
