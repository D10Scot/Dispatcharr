# G12 — Lifecycle Depth

**Date:** 2026-09-01
**Status:** Draft, ready for review
**Wave:** 6 (parallel with G13, G14, G15; after G11)
**Parent:** `2026-08-23-e2e-coverage-roadmap-design.md`
**Goal definition:** `2026-09-01-e2e-programme-review-disposition.md`, "G12 — Lifecycle depth"
**Direct predecessor:** `2026-08-28-e2e-deployment-lifecycle-design.md` (G7) and its plan
**Revised:** 2026-09-01, after G11 landed (`45a33a4a`)
**Verified at:** `origin/main` `45a33a4a` ("docs: record two traps that cost time this
session (#126)"), which carries G11's two PRs — `4211cbb7` (guards, ADRs, full-run CI) and
`7a408c2b` (every test tagged, the tag guard blocking).
Line numbers drift; symbol names are the durable half of every citation.

**What the revision changed.** This spec was written before G11 merged and hedged on
mechanisms G11 has now decided: the tag syntax, the guard that enforces it, and the CI gating.
Those hedges are replaced with the mechanism that exists (D19, D20, D22, § Tags, § Non-goals),
and a § Migration relevance was added to say which of the four pieces the relay extraction
actually depends on. The triage itself is unchanged and still holds: **nothing under
`docker/tests/` has been touched since the original verification** (`git log cf95410e..45a33a4a
-- docker/tests/` is empty), so C1–C4, F1–F6 and T1–T6 stand as written.

## Goal

The lifecycle suite is the one part of this programme that a relay extraction cannot route
around: it is where "the container came back and the data is still there" is decided. Today it
is two-thirds theatre. `lifecycle-tests.yml` has been **red on every post-merge run since it
landed** — a workflow that always fails carries no signal, so nothing in it is a gate. And
`durable-state.ts` asserts seven scalar rows, so a migration that dropped every channel↔stream
link, every Channel Profile membership and the entire EPG programme table would pass it
untouched.

G12 makes the suite say something true, in four parts:

1. **Triage the red bash scenarios to green.** Classify each failure, fix what is a test bug,
   file what is a product bug, and leave `lifecycle-tests.yml` green so a future red run means
   something.
2. **Deepen `durable-state.ts` from rows to relations** — the shapes a migration loses silently.
3. **Backup restore end to end**, on an isolated instance.
4. **Non-zero `refresh_interval` and cron scheduling**, on an isolated instance, closing G3's D10
   debt.

Everything else stays out. See Non-goals.

## Migration relevance

The programme exists to make this suite a trustworthy gate for the relay extraction
(`CLAUDE.md`, "extract the streaming relay from the Django web workers into its own process").
The four pieces are not equally load-bearing for that, and saying so plainly is what lets wave 6
be cut if it runs long.

**Gate-critical — these must land, and they must land first.**

- **Piece A, a green `lifecycle-tests.yml`.** `Lifecycle result` is the one check in that
  workflow that may ever be required, and its own header says it "must not be added to the Main
  ruleset until G12 leaves both bash suites green". A `migration/*` branch turns on full mode
  (`changes` sets `full=true` for a head branch matching `migration/*`), which is what makes
  `suites` run on a pull request at all. Until Piece A is done, the extraction's own branches
  either run a red gate or no gate. Nothing else in G12 unblocks that.
- **Piece B, relations survive a restart and an upgrade.** This is the durable-state contract
  the extraction must not break, and one relation in it is directly about the relay: the
  `Channel → Streams` **order** decides which upstream is primary and which is the failover
  target (D12). A relay in its own process reads that ordering to fail over; an extraction that
  preserved every row and lost the ordering would pass today's `durable-state.ts` untouched.

**Not gate-critical.**

- **Piece C, restore.** Deployment safety. It proves an operator can get their instance back,
  which matters most on the day an extraction goes wrong — but it exercises `apps/backups`,
  which the extraction does not move, and a red restore spec says nothing about the relay.
- **Piece D, scheduling.** Closes G3's D10 debt and touches nothing the extraction moves:
  django-celery-beat rows behind `M3UAccount`/`EPGSource` refreshes. Worth doing, last in line.

**If wave 6 runs long, D is the piece to defer** — its `COVERAGE.md` row stays `todo`,
attributed forward, and nothing else in the goal depends on it. A and B are not deferrable.

One caution specific to Piece B's `Recording` relation: `recover_recordings_on_startup` runs on
**every boot** (`dispatcharr/celery.py:on_worker_ready` fires it on `worker_ready`), and for a
recording whose `start_time` is still in the future it re-resolves the beat task and writes
`rec.save(update_fields=["task_id"])` (`apps/channels/tasks.py`, the "Ensure future recordings
are scheduled" block). Were the window to open mid-test, the in-window branch rewrites
`custom_properties["status"]` as well. So the assertion is **by id and `channel` only** — not
`task_id`, not `custom_properties`. Those two fields are the product correctly repairing itself
across the very event under test, and asserting on them would make a working recovery look like
a lost row.

## Current state

| | |
|---|---|
| `docker/tests/test-puid-pgid.sh` | 20 scenarios, 1,517 lines. 8 failed assertions across **4** scenarios on run 33384550684 |
| `docker/tests/test-tls-postgres.sh` | 8 scenarios, 892 lines. 7 failed scenarios on the same run — all one root cause |
| `e2e/tests/lifecycle/durable-state.ts` | `seedDurableState` creates 7 rows; `assertDurableState` reads 7 back by id. No relation is asserted anywhere |
| `e2e/tests/lifecycle/restart-persistence.spec.ts` | 1 test, `@characterization`, project `lifecycle`, in `e2e-tests.yml`'s normal project list |
| `e2e/tests/lifecycle/upgrade-migrations.spec.ts` | 1 test, `@characterization`, project `lifecycle-upgrade`, in `lifecycle-tests.yml` and in `e2e-tests.yml`'s **full** list only |
| `e2e/COVERAGE.md` | Two `todo` rows attributed to G7 and never built, both under `Lifecycle`: the row beginning *"Backups: restore — split out of G6's Backups row"* and the row beginning *"Refresh-interval scheduling: a **non-zero** `refresh_interval`"*. Cite them by that text — the earlier draft of this spec gave line numbers, and G11's edits moved both |

Both `todo` rows already prescribe the isolation this goal needs. The restore row: *"Restoring on
a shared instance replaces the database under every parallel worker mid-run … so it needs an
instance of its own; G7 already stands one up per scenario."* The refresh-interval row: *"a
non-zero interval leaves an enabled hourly beat task re-refreshing that account for the life of
the container … G7's scenario-specific jobs each stand up their own instance and can."* G12
inherits both rows from G7 and marks them `done`.

## Corrections to the disposition document

The disposition is right that the workflow is permanently red and right about the two root
symptom families. Three of its statements do not survive re-checking, and one is a
mislabelling that would send an implementer looking for the wrong thing.

**C1 — "8 of 126 puid-pgid scenarios and 7 of 12 tls-postgres scenarios fail" counts
assertions, not scenarios.** `test-puid-pgid.sh` declares exactly 20 scenarios (the `SCENARIOS`
array near the foot of the file; `grep -c '^test_.*() {'` returns 20) and
`test-tls-postgres.sh` declares 8. The run's own summary is `Passed: 117 Failed: 8 Skipped: 1`
— those are `log_pass`/`log_fail` calls. The 8 failures cluster into **4 scenarios of 20**
(`upgrade_explicit_puid` ×2, `upgrade_auto_adapt` ×2, `bind_mount_auto_adapt` ×3,
`pg_major_upgrade` ×1); the TLS suite's 7 failures happen to be one per scenario, so there it
is genuinely **7 scenarios of 8**. The distinction matters: 4 broken scenarios out of 20 is a
tractable triage, 126 is not.

**C2 — the puid failures are not "ownership-migration failures".** Three distinct causes, none
of them a live ownership-migration bug. Two of them are the suite testing a feature the product
deliberately **deleted** (§ Triage, T2).

**C3 — the TLS failures are not "container-start/cert-permission failures", plural.** They are
one failure with one cause, repeated seven times: every scenario that mounts the generated
certificate directory dies at the same line with the same exception. The eighth scenario,
`modular_no_tls_regression`, is the only one that mounts no certificates and the only one that
passes. That is not two classes; it is a controlled experiment the suite ran on itself.

**C4 — "every run is red" understates it: the bash suites have never been green in CI, not
once.** The disposition cites run 33245032230 as a comparison point without noticing that
`lifecycle-tests.yml`'s `suites` job carried, at the time, `if: github.event_name !=
'pull_request'` — so on the G7 pull request the two bash jobs were **skipped**, and the green
tick was `build` plus `upgrade-migrations`. The first execution of either suite anywhere was the
post-merge run 33247491371, which was red (9 failures), and every run since has been red. G11
has since widened that condition to `if: github.event_name != 'pull_request' ||
needs.changes.outputs.full == 'true'`, so a `migration/*` head branch or a `workflow_dispatch`
with `full: true` now does run both suites on a pull request — which changes how G12 verifies
itself (§ Non-goals, and the plan's Tasks 6 and 10) but not one word of the diagnosis. G7's own D2
("**The bash suites are not modified. Not one line.** … known-good and have never run") rested
on an assumption that the first run would tell us whether they were good. It did. They are not.
**G12 explicitly supersedes D2.**

## Verified facts this design rests on

Each was checked against the tree or the CI artifacts at the SHA above, not carried over from
the disposition.

**F1 — Upstream's release image is no longer a pre-PUID image.** `setup_old_pg_data` in
`test-puid-pgid.sh` boots `RELEASE_IMAGE="ghcr.io/dispatcharr/dispatcharr:latest"` to
manufacture "old-style data (UID 102)", then logs what it actually got. The artifact says
`Old data owner: 1000:1000`. `USE_RELEASE_IMAGE` is set `true` whenever that floating tag pulls,
which in CI is always, so the manual fallback `setup_old_pg_data_manual` — which does produce a
`postgres`-owned cluster with a `postgres` bootstrap superuser — never runs. Both
`upgrade_explicit_puid` failures fall straight out of this: no `postgres` role exists in a
cluster `initdb`'d by the post-PUID image (`PG role 'postgres' not superuser (got:
'<missing>')`), and no ownership migration is logged because 1000 already equals `PUID=1000`.

**F2 — PUID auto-detect was removed from the product on purpose, and the suite was not
updated.** `7e221720` ("fix: remove PUID auto-detect") deleted the two blocks in
`docker/init/01-user-setup.sh` that read `PUID`/`PGID` from `${POSTGRES_DIR}/PG_VERSION`'s owner
and echoed `PUID not set — defaulting to existing data owner UID: …`. Its message is explicit
about why: running as UID 102 "broke host-side access (SSH, WinSCP), made existing DATA_DIR
files unwritable, and failed comskip". The file now reads `export PUID=${PUID:-1000}` under a
comment saying the 102→1000 migration is `02-postgres.sh`'s job. The suite arrived in
`52ed0fc1`, the *same* PR that added auto-detect, and `git log --follow` shows it has never been
touched since. So `test_upgrade_auto_adapt` and `test_bind_mount_auto_adapt` grep for a log line
that no longer exists and assert an ownership outcome the product no longer produces. Five of
the eight failures are this.

**F3 — every TLS failure is `PermissionError: [Errno 13] Permission denied: '/certs/ca.crt'`.**
`generate_test_certs` does `CERT_DIR=$(mktemp -d)` — mode 0700, owned by the invoking host user
— and bind-mounts it into the app container, which reads it as the `dispatch` user (UID 1000,
via `su - "$POSTGRES_USER"`). On a Linux runner UID 1000 cannot traverse a 0700 directory owned
by someone else, so `dispatcharr/settings.py`'s `_validate_tls_cert_paths` cannot `stat`
`ca.crt`. On Docker Desktop the bind mount is presented permissively, which is why this has
never been seen locally. `docker/init/00-fix-pg-ssl-key.sh` masks it for the client *key* only,
because that script runs as root and copies the key out; the CA and client certificates are read
in-place by Django. `modular_no_tls_regression`, the one scenario that mounts nothing, is the one
that passes.

**F4 — `pg_major_upgrade` is under-determined from the artifact, by the suite's own design.**
The scenario times out at `wait_for_ready "$name" 300`, which greps `docker logs` for `uwsgi
started with PID`. The diagnostic that follows is `dump_logs_on_fail`, which is `docker logs |
tail -60` — and all 60 lines are PostgreSQL's `collation version mismatch` warnings emitted at a
5-second cadence, so not one line of the entrypoint's own stdout survives into the artifact.
Three facts narrow it: (a) the sibling `pg_upgrade_post_puid`, which exercises the same
`pg_upgrade` path, **passes** in the same run, and the only difference is that it seeds its PG 16
cluster *inside* `$IMAGE_NAME` rather than from the official `postgres:16` image; (b) the
surviving warnings say the databases carry collation version 2.41 while the OS provides 2.39, so
`postgres:16` has moved to a glibc newer than the AIO image's Ubuntu 24.04 — and they name
`dispatcharr`, which means `pg_upgrade` did transfer the old cluster rather than leaving the
fresh one in place; (c) it is scenario 17 of 20, by which point issue #41's leak has left ~16
PostgreSQL data volumes on a runner with single-digit gigabytes free. This is the one failure
this spec does **not** classify from the evidence; the plan reproduces it under a written
decision rule (§ Triage, T4).

**F5 — issue [#41](https://github.com/D10Scot/Dispatcharr/issues/41) is *not* one of the fifteen,
and there is a second leak beside it.** #41 (volumes removed before the containers mounting
them, because `cleanup_scenario` walks `CLEANUP_ITEMS` in insertion order) fails no assertion —
the suite reports success and the volumes accumulate. A second, distinct leak is visible in the
same artifact: the bind-mount scenarios clean up with `docker run --rm -v /tmp:/hosttemp
"$IMAGE_NAME" bash -c "rm -rf …"` and **omit `--entrypoint`**, so `bash -c …` is handed to the
AIO entrypoint as arguments it ignores; the entrypoint then tries to mint a Django secret key
into an unmounted `/data` and dies at `docker/entrypoint.sh:109` (`mktemp failed`). The host
directories are never removed. Both leaks appear in the log as the `mktemp failed` lines at
`test-puid-pgid.sh`'s bind-mount scenarios.

**F6 — `restart_idempotent` is intermittent.** It failed on run 33247491371 (`Timeout (180s)
waiting for puid_test_restart`) and passed on 33384550684. `STARTUP_TIMEOUT=180` is the only
budget it gets, and every other scenario in the suite that boots a container twice uses the same
one.

**F7 — `instance.manage()` accepts plain tokens only.** It rejects any argument not matching
`^[A-Za-z0-9._/=-]+$` before shelling out, so `manage(['shell', '-c', '…'])` is impossible.
`manage(['dumpdata', 'django_celery_beat.PeriodicTask', '--format=json'])` passes the filter
intact — every token is plain — which is the route by which a scheduling test can observe
`PeriodicTask.enabled` and `IntervalSchedule.every`. `manage.py` prints a banner to **stdout**
before command output (documented in `upgrade-migrations.spec.ts`'s `appliedMigrations`), so the
JSON must be parsed from the first `[`.

**F8 — the fake upstream provider is available to the lifecycle projects, and its registry does
not survive a restart.** `scripts/e2e_up.sh` starts `e2e-upstream` unconditionally and publishes
its control API on `127.0.0.1:9402`; the `upstream` fixture (`e2e/fixtures/index.ts`) has no
dependencies and no `bootstrap` requirement, so a lifecycle spec may use it. But `ScenarioRegistry`
(`e2e-upstream/src/scenario.ts`) is a plain in-memory `Map`, and `instance.restart()` is
`e2e_up.sh --stop` followed by a bare invocation — which stops and starts the provider container
too. **Every scenario is forgotten across a restart.** Anything the provider seeded must
therefore be asserted from Dispatcharr's own rows afterwards, never re-fetched from the
provider. `recreate()` leaves the provider alone; `up({ reset: true })` destroys it via
`destroy()`.

**F9 — EPG programme rows require a channel association.** `seed.upstreamEpgSource` returns a
source with `EPGData` rows and **zero `ProgramData`**: `parse_programs_for_source` gates on a
Channel pointing at an `EPGData` row. Programmes appear only after `POST
/api/channels/channels/<id>/set-epg/`, and are read at `/api/epg/programs/search/?channel_id=`.

**F10 — a version-2 backup contains the database and nothing else.** `create_backup`
(`apps/backups/services.py`) writes `database.dump` plus `metadata.json` into the archive; the
docstring's "and data directories" is stale. `restore_backup` → `_restore_database` →
`_restore_postgresql` runs `_clean_postgresql_schema` (`DROP SCHEMA public CASCADE`) and then
`pg_restore --no-owner`, and `restore_backup_task` runs `migrate --noinput` afterwards. So a
restore replaces every row and **no file**: uploaded logo bytes under `/data/logos` survive a
restore untouched, which is the opposite of what they do across a lost volume.

**F11 — `cron_expression` is a genuine black-box view of the `PeriodicTask`.**
`M3UAccountSerializer` and `EPGSourceSerializer` both declare it as a plain `CharField` and both
`to_representation` methods derive it from `instance.refresh_task.crontab` — the serializers'
own comments say "single source of truth". So a round-trip through the REST API proves a
`CrontabSchedule` was created and linked, with no `manage.py` at all. `refresh_task` itself,
`PeriodicTask.enabled` and `IntervalSchedule.every` have no REST surface.

**F12 — the two product defects found during triage.** Both are read off the source, neither is
inferred from a failure:
- `_validate_tls_cert_paths` (`dispatcharr/settings.py`) exists, by its own docstring, to
  "raise `ImproperlyConfigured` with a clear message identifying the service and missing file so
  operators can fix their environment" — and it tests only `Path(file_path).is_file()`, which
  raises `PermissionError` on an unreadable path instead of returning `False`. An operator
  mounting a Kubernetes secret or a `:ro` volume the app user cannot traverse gets a raw
  traceback at import time, which is precisely the outcome the function was written to prevent.
- `docker/init/02-postgres.sh`'s major-upgrade path runs `su - "$POSTGRES_USER" -c "$NEW_BINDIR/pg_upgrade …"`
  and **never checks its exit status**, then unconditionally `mv`s the old data directory to a
  backup and `mv`s the new one into place, then prints `Upgrade complete.` A failed
  `pg_upgrade` is therefore promoted to a successful-looking boot on a freshly `initdb`'d, empty
  cluster. The `apt install` two blocks above it does check (`if [ $? -ne 0 ]`), so the omission
  is local, not a house style.

## Decisions

**D1 — G7's D2 is superseded: the bash suites are modified.** D2 was correct while the suites
had never executed. They have now executed eleven times and failed eleven times, and F1/F2/F3
show the failures are in the suites, not the product. Leaving them unmodified preserves nothing
and costs the workflow's entire signal.

**D2 — every suite change is a test change; no product file is touched.** `docker/tests/*.sh`
is test code. `docker/init/*`, `docker/entrypoint.sh`, `dispatcharr/settings.py` and everything
under `apps/` are product and are read-only for this goal, exactly as the roadmap's rule 5
requires. The two defects in F12 are filed with `gh issue create --repo D10Scot/Dispatcharr` —
the `--repo` flag is mandatory; without it `gh` resolves to `Dispatcharr/Dispatcharr` and files
this fork's findings on the upstream public tracker.

**D3 — a bash suite cannot express `test.fail()`, so a product defect found there is filed and
*not* reproduced.** The Playwright bug policy — assert correct behaviour, invert with
`test.fail()`, file the issue — has no analogue in a suite whose only outcome is a
`log_pass`/`log_fail` counter and an exit code. A scenario written to fail would put the
workflow straight back where G12 found it. So for F12's two defects the spec commits to: file
the issue, cite it in `COVERAGE.md`, and add **no** scenario. This is stated in the plan so that
a later reader does not mistake the absence for an oversight. The one thing that *is* added is
a comment at each affected site naming the issue.

**D4 — `upgrade_explicit_puid` is fixed by seeding from `setup_old_pg_data_manual`
unconditionally, and `RELEASE_IMAGE` is deleted.** The manual seeder already exists in the file
for exactly this purpose, and it produces what the scenario's own comment claims: a cluster
`initdb`'d by the `postgres` OS user with `postgres` as bootstrap superuser, at whatever UID the
image's `postgres` package user has. That is a *genuinely* pre-PUID cluster, reproducibly, with
no dependency on a floating third-party tag. The release-image path is not repaired but removed:
it can never again produce pre-PUID data, and a fixture that silently produces the wrong premise
is worse than no fixture (this is the same failure the disposition catalogues for pre-G9
`test.fail()` pins — a premise that can rot inside the assertion). `BASE_IMAGE`, unused, goes
with it.

**D5 — the two `auto_adapt` scenarios are rewritten to assert today's behaviour, not deleted.**
Their *subject* — an upgrade onto foreign-UID data with **no** `PUID` set — is still worth
covering and is still a real user's path; only their expectation is stale. They become
`upgrade_default_puid` and `bind_mount_default_puid`, asserting what `7e221720` deliberately
installed: `PUID` defaults to 1000, the data **is** migrated to 1000:1000, and `Migrating
PostgreSQL data ownership` **is** logged. The rename is not cosmetic — leaving the name
`auto_adapt` on a scenario that asserts the absence of auto-adapt is how the next reader
concludes the product regressed.

**D6 — the TLS suite's cert directory is made world-traversable at creation.** `chmod 755
"$CERT_DIR"` immediately after `mktemp -d`, with a comment naming the Docker Desktop asymmetry
in F3. This is what a real deployment looks like — a mounted secret the application user can
read — so it makes the scenarios test the thing they were written to test rather than testing
the host's `umask`. Only the directory: the `.crt` files are already 644 from `openssl`'s
default umask, the client key stays 600 and is copied out by `00-fix-pg-ssl-key.sh` as root, and
the server keys are consumed by the `postgres`/`redis` containers, which chown their own copies.

**D7 — issue #41 is fixed in this PR, before anything is re-measured.** It is labelled
`ready-for-agent`, its mechanism is a two-line ordering bug in `cleanup_scenario`, and it is a
live confound for F4: `pg_major_upgrade` runs 17th of 20 on a runner with single-digit gigabytes
free, behind ~16 leaked PostgreSQL data volumes. Fixing the leak first is both the cheap
correctness fix and the first hypothesis-elimination step for the one failure this spec cannot
classify. The second leak in F5 (the missing `--entrypoint`) is fixed alongside it; it is a
different mechanism and gets its own line in the issue rather than a new issue.

**D8 — `pg_major_upgrade` is triaged by a bounded local reproduction under a written decision
rule, not by guesswork.** The rule is in the plan (§ Triage, T4) and it is binary: if the
entrypoint reaches `uwsgi started with PID` given more time or less disk pressure, it is a
CI-environment defect and the fix is a budget; if the entrypoint blocks or errors inside
`02-postgres.sh`, it is a product defect, gets an issue, and the scenario is quarantined with
`log_skip` and a comment naming that issue. Nothing else is an acceptable outcome, and in
particular "delete the scenario" is not.

**D9 — the suite's diagnostics are widened in the same change.** `dump_logs_on_fail`'s `tail
-60` is what made F4 unclassifiable from CI. It goes to `tail -200` with PostgreSQL's repeated
`collation version mismatch`/`DETAIL:`/`HINT:` triplets filtered out. This is not scope creep:
the whole point of the goal is that the next red run must be readable, and the current diagnostic
demonstrably is not.

**D10 — `durable-state.ts` gains relations, and it stays one shared helper.** Both lifecycle
specs call `seedDurableState`/`assertDurableState`; the review's finding is about what those two
functions cover, not about where they live. Adding a second helper would let restart and upgrade
drift apart, which is the exact failure the shared file was built to prevent.

**D11 — the relation set is seven items, each chosen because a migration can lose it while every
scalar row survives.** Ordering, membership, foreign keys and files are the shapes a rewrite
drops silently:

| Relation | Created by | Asserted by |
|---|---|---|
| Channel → Streams, **in order** | `seed.upstreamChannel` (two provider channel ids) | `channel.streams` deep-equals the recorded id array, order included |
| Channel Profile ↔ Channel membership | `seed.channelProfile` + a membership write | the profile's `channels` contains the channel id |
| EPG source → `EPGData` → `ProgramData` | `seed.upstreamEpgSource` + `POST …/set-epg/` (F9) | `/api/epg/programs/search/?channel_id=` returns the recorded programme titles |
| XC user credentials | `seed.xcUser` | `player_api.php?username=&password=` authenticates **after** the event |
| VOD `Movie` / `Series` / `Episode` | `seed.xcAccount` against an XC scenario with a catalogue, then a refresh | each read back by id, and `episode.series.id` still points at the recorded series |
| A scheduled `Recording` | `POST /api/channels/recordings/` | read back by id, `channel` still the recorded channel |
| An uploaded logo's **bytes** | `seed.logo` | `GET logo.cache_url` body `Buffer.equals(logoPayload(logo.name))` |

The channel↔stream and profile-membership rows are the two the disposition named as the
motivating examples; the logo bytes are the only assertion in the set that leaves the database,
which is what makes it worth its cost across a restart or an upgrade (and, per F10, worthless
across a restore — see D14).

**D12 — the ordering assertion is the point of the channel↔stream row, so it uses two streams,
not one.** `Channel.streams` is an ordered set through `ChannelStream` and the order decides
which upstream is primary and which is the failover target (`seed.upstreamChannel`'s comment
says so, and creates its streams serially for exactly this reason). A single-stream channel
cannot distinguish "the link survived" from "the ordering survived", and ordering is the half a
migration is more likely to lose.

**D13 — the extension is paid for by the provider, on both lifecycle instances.** The relations
that matter most (streams, programmes, VOD rows) cannot be conjured by hand — they are ingest
products. F8 establishes the provider is available and that `up({ reset: true })` recreates it
before seeding, so the upgrade spec's baseline boots against a fresh provider and seeds after
it. The cost is real: the upgrade spec grows an M3U refresh, an EPG refresh and a VOD catalogue
refresh, perhaps 90 seconds against a 1,800,000 ms project timeout and a 45-minute job budget.
The restart spec pays the same on a 900,000 ms budget. Neither is close to its ceiling.

**D14 — backup restore gets its own project and its own instance: `lifecycle-restore`.** It
drops and recreates the `public` schema under whatever else is running (F10). The COVERAGE row
already says so. Its shape is the only one that proves anything: seed state **A**, take a
backup, mutate to state **B**, restore, then assert **A** is back *and* **B** is gone. A test
that only asserts A is back cannot tell a working restore from a restore that did nothing.

**D15 — the restore spec asserts in-place recovery, with no container restart.** The product
offers restore as a running operation (`POST /api/backups/<filename>/restore/` returns 202 and a
`task_token`; `restore_backup_task` finishes with `migrate --noinput`), so that is the claim
under test. Requests immediately after the schema drop may fail while pooled connections
reconnect, so assertions poll rather than fire once. If in-place recovery genuinely does not
work, that is a finding to file and pin with `test.fail()`, not a reason to bolt a restart onto
the test until it goes green.

**D16 — the restore spec must not assert that logo bytes survive.** F10: a v2 backup carries
`database.dump` and `metadata.json` and no files at all. The `Logo` **row** comes back with the
restore; the bytes under `/data/logos` were never in the archive and were never removed, so a
byte assertion here would pass for the wrong reason and would start failing the day backups
learn to carry files. The spec states this in the test's own comment and in `COVERAGE.md`, and
the shared `assertDurableState` is therefore called with the logo assertion opted out — an
explicit parameter, not a silent divergence.

**D17 — scheduling gets its own project and its own instance: `lifecycle-scheduling`.** A
non-zero `refresh_interval` yields `should_be_enabled = true` (`core/scheduling.py`), so the
instance ends up with an **enabled** hourly beat task re-refreshing that account for the life of
the container. On the shared `seeded` container that is intolerable — it is exactly G3's D10 and
the reason the ledger row exists. It is doubly intolerable on the lifecycle instances, where F8
means the provider will have forgotten the scenario the account points at, so a background
refresh would mutate rows under the durable-state assertions.

**D18 — the scheduling spec asserts scheduling artefacts, never a firing.** `IntervalSchedule`'s
smallest unit here is `every=1, period=HOURS` (`core/scheduling.py` clamps with `max(int(interval_hours), 1)`),
so waiting for a tick is an hour. What is observable in seconds is the whole of what the
COVERAGE row asks for: the enabled-task branch, the `IntervalSchedule` row, `cron_expression`,
and `_cleanup_orphaned_interval` on delete.

**D19 — every test G12 adds is `@characterization`, and the assertion-portability split is
recorded in the comment rather than in the tag.** An earlier draft of this decision split the
scheduling spec `@contract`/`@characterization` down the middle. That is not available: ADR 0002
says "anything on a `tests/guards/allowlist.ts` capability list is `@characterization` by
construction", both new specs destructure the `instance` fixture to own their container, and the
`instance` fixture **is** the `CONTAINER_LIFECYCLE` capability. The tag is a property of the
file, not of the assertion. The split is still real and still worth writing down, so it goes
where G11 already requires prose — the `// @characterization: <fact it pins>` comment — which
must say which assertions would survive a behaviour-preserving rewrite and which are coupled to
django-celery-beat's tables or the AIO layout. Per F11, `refresh_interval` and `cron_expression`
round-trip through the REST API and `cron_expression` is derived from the linked
`PeriodicTask.crontab`, so the interval↔cron half is portable in substance; `PeriodicTask.enabled`,
`IntervalSchedule.every` and orphan cleanup on delete have no REST surface at all (F7) and are
not. Recording that inside the comment is strictly more useful than a tag would have been: a
migration branch reads the sentence, not the label.

**D20 — G11 has landed; G12 uses its mechanism verbatim and invents nothing.** The taxonomy is
`docs/adr/0002-e2e-test-taxonomy.md`: exactly two tags, `@contract` (the default, no
justification needed) and `@characterization` (must carry a `// @characterization: <fact>`
comment immediately above the declaration). They are applied through Playwright's native tag
option as an **inline object literal second argument** —
`test('title', { tag: '@characterization' }, async ({ … }) => { … })` — and the same form works
for `test.fail(...)` and for an enclosing `test.describe(...)`. A details object passed *by
reference* makes the declaration unverifiable and the guard fails. `e2e/tests/guards/tags.spec.ts`
fails closed on every declaration it cannot read, and `KNOWN_UNVERIFIABLE` is empty. **Every new
`test(` G12 writes must carry a tag or CI fails** — there is no warning mode left to fall back
on.

**D21 — `#7`'s pre-warm rule is satisfied structurally, and the README's enumeration is
updated anyway.** The rule (`e2e/README.md`, "Non-zero `refresh_interval` values, and what they
cost") is that any non-zero value used from a parallel test must be unique per test and never
pre-warmed from a worker. `lifecycle-scheduling` runs `workers: 1`, `fullyParallel: false`, on
an instance nothing else touches, and declares no `bootstrap` dependency — so there is no
concurrent create and the race is impossible rather than merely avoided. That is not a licence
to leave the values undocumented: the README's set is an enumeration and the section says in
terms that a stale one is worse than none. The values this spec adds go in it, with a sentence
saying they are exempt from the uniqueness rule *because of the isolation*, so that anyone who
later moves the spec to a shared project sees the condition they would be breaking.

**D22 — both new projects run in `lifecycle-tests.yml`, not `e2e-tests.yml`.** Same reasoning as
G7's D16, re-checked against the actual costs. Restore is a `pg_dump`, a `DROP SCHEMA CASCADE`,
a `pg_restore` and a `migrate`; scheduling is a container boot plus a handful of writes and two
`dumpdata` calls. The longest job in `e2e-tests.yml`'s matrix is 284s, and `lifecycle-tests.yml`
already builds and loads the image both need. One new job runs both projects sequentially — one
image load, two projects — rather than two jobs each paying a 3.6 GB `docker load`.

The gating is now concrete rather than a request to a future goal. The new job carries **the
same `if:` as `upgrade-migrations`** — `if: needs.changes.outputs.lifecycle == 'true' ||
needs.changes.outputs.full == 'true'` — so it runs on an ordinary pull request that touches
lifecycle paths, and always on a `migration/*` branch or a `workflow_dispatch` with `full:
true`. There is **no separate project list in this workflow** to add the two names to: the
JSON-matrix arrangement with its "A NEW PROJECT MUST BE ADDED TO BOTH LINES" comment lives in
`e2e-tests.yml`, and these two projects do not go there (that is the whole of this decision).
The one list that does need editing is `lifecycle-result`'s `needs:`, which currently reads
`[changes, build, suites, upgrade-migrations]`; a job absent from it can fail while the
aggregate reports green, which is the exact failure mode that check exists to prevent.

## Triage — the fifteen scenarios, classified

Every classification below is evidence-backed at F1–F6. The plan implements this table; it does
not re-derive it.

| # | Scenario | Failed assertion(s) | Class | Disposition |
|---|---|---|---|---|
| **T1** | `upgrade_explicit_puid` | `PG role 'postgres' not superuser (got: '<missing>')`; `Ownership migration logged (pattern not found: Migrating PostgreSQL data ownership)` | **Suite defect — dead premise** (F1) | Fix here. D4: seed from `setup_old_pg_data_manual` unconditionally; delete `RELEASE_IMAGE`/`USE_RELEASE_IMAGE`/`BASE_IMAGE`. No issue — nothing in the product is wrong |
| **T2** | `upgrade_auto_adapt`, `bind_mount_auto_adapt` | `Ownership … UID: expected 102, got 1000` ×2; `Auto-adapt logged (pattern not found: PUID not set)` ×2; `No migration on auto-adapted bind mount (unexpected pattern found: …)` | **Suite defect — removed feature** (F2) | Fix here. D5: rewrite as `upgrade_default_puid` / `bind_mount_default_puid` asserting post-`7e221720` behaviour. No issue — the removal was deliberate and is documented in its own commit message |
| **T3** | 7 TLS scenarios: `modular_mtls_no_password`, `modular_mtls_with_password`, `modular_tls_server_only`, `modular_tls_key_permission`, `modular_pg_verify_full`, `modular_redis_tls`, `modular_full_tls_celery` | `Container failed to start …` ×7, all from `PermissionError: … '/certs/ca.crt'` | **Suite defect — host portability** (F3) | Fix here. D6: `chmod 755 "$CERT_DIR"`. **Plus one product issue filed** (F12a): `_validate_tls_cert_paths` raises an unhandled `PermissionError` instead of its own `ImproperlyConfigured`. Filed, cited in a comment, **not** reproduced (D3) |
| **T4** | `pg_major_upgrade` | `Container failed to start after pg_upgrade` (300s timeout) | **Under-determined** (F4) | D7 first (remove the volume-leak confound), D9 (make the log readable), then reproduce locally under D8's decision rule. **One product issue filed regardless** (F12b): `pg_upgrade`'s exit status is unchecked and the `mv` runs anyway |
| **T5** | `restart_idempotent` | `Timeout (180s)` — red on 33247491371, green on 33384550684 | **CI-environment defect** (F6) | Fix here: raise `STARTUP_TIMEOUT` and say in a comment that the budget is for a loaded runner, not for a slow product |
| **T6** | — (fails nothing) | Volumes and host directories leaked on every run | **Suite defect — silent leak** (F5) | Fix here (D7). Closes [#41](https://github.com/D10Scot/Dispatcharr/issues/41) and its second mechanism |

Two of the six rows produce product issues; four do not. That ratio is the actual answer to the
disposition's question, and it is the opposite of what "8 ownership-migration failures" implied:
the workflow is red almost entirely because the suites encode a product that changed underneath
them.

**Definition of green.** `lifecycle-tests.yml`'s `suites` matrix exits 0 on both jobs on a
post-merge run of `main`, with `Failed: 0` in both summaries, and with `Skipped` accounted for
line by line in the plan's final task. A scenario quarantined under D8 counts as green only if
its `log_skip` message names the issue number.

## Piece B — durable state, from rows to relations

`seedDurableState` and `assertDurableState` keep their signatures' shape and grow. The seven
existing scalar rows are untouched; the seven relations of D11 are added to the same
`DurableState` record and the same assertion function, so **both** the restart spec and the
upgrade spec get them with no change to either spec file beyond their call-site arguments. Both
are already tagged `@characterization` at HEAD (D19), so neither needs a retag; each one's
existing `@characterization:` comment gains a sentence about the relations, per § Tags.

Three properties of the existing file are load-bearing and survive:

- **Serial by construction.** The header records that the lifecycle projects run one worker with
  `fullyParallel: false`, which is what makes creating an M3U account and an EPG source safe on a
  container `bootstrap` has never pre-warmed — two concurrent creates would both insert an
  `IntervalSchedule` row and brick the instance (#7). Adding an XC account and a second source
  does not change that; it makes it more important, and the extended header must say so.
- **Postgres-backed only.** Redis is excluded because AIO configures no persistence and
  `scripts/wait_for_redis.py` calls `flushdb()` on every boot. Nothing in D11 is Redis-backed.
- **By id, against a value recorded at creation.** Roadmap rule 4. The programme-row assertion is
  the one that needs care: it filters by `channel_id` and asserts the recorded titles are
  present, never that the count is N.

The one genuinely new hazard is F8. The restart spec's `instance.restart()` takes the provider
down with it, so between seeding and asserting the upstream ceases to exist. Every assertion in
D11 reads Dispatcharr's own database through Dispatcharr's own API, which is why the set is
safe — and the file must say that in a comment, because the obvious "re-refresh and compare"
extension anyone would reach for next is the one thing that cannot work here.

## Piece C — backup restore

One test, one file, one project (`lifecycle-restore`), on an instance it owns:

1. `instance.up({ reset: true })`, `provisionAdmin`, seed state **A** via the extended
   `seedDurableState`.
2. `POST /api/backups/create/` → 202 + `task_id`; poll `/api/backups/status/<task_id>/` to
   completion; record the archive name from `GET /api/backups/` by matching that name, never by
   taking `[0]`.
3. Mutate to state **B**: create a second, differently-named channel and delete one of A's rows.
   Both halves matter — a restore that never ran passes an "A is back" assertion trivially, and a
   restore that flushed without restoring passes a "B is gone" assertion trivially. Only both
   together pin it.
4. `POST /api/backups/<filename>/restore/` → 202 + `task_id` + `task_token`; poll the status
   endpoint (the token path exists precisely because a restore can invalidate the session).
5. Assert, with polling (D15): **A** reads back by id — including its relations, minus the logo
   bytes (D16) — and **B**'s channel is a 404.

The instance is torn down in a `finally` that captures `instance.logs()` first, exactly as
`upgrade-migrations.spec.ts` does and for the same reason.

## Piece D — refresh-interval and cron scheduling

One file, two tests, one project (`lifecycle-scheduling`), on an instance it owns.

Both tests are `@characterization` (D19): the file owns its container. What differs is how
portable the assertions are, and that difference belongs in each test's `@characterization:`
comment.

**Test 1 — portable assertions.** Through the REST API only:

- Create an `M3UAccount` with a non-zero `refresh_interval`; read it back and confirm the value
  persisted rather than being coerced to the default.
- `PATCH` a `cron_expression`; read it back and get the same expression — which per F11 proves a
  `CrontabSchedule` exists and is linked to the account's `PeriodicTask`, because that is where
  `to_representation` reads it from.
- `PATCH` back to an interval; `cron_expression` reads back empty, proving the task's `crontab`
  was cleared.
- The same three steps for an `EPGSource`, whose serializer has the identical shape.

**Test 2 — coupled assertions.** Through `instance.manage(['dumpdata', …, '--format=json'])`
(F7), justified in its comment as coupling to django-celery-beat's tables because the product
exposes no other view of them:

- The `PeriodicTask` named for the account exists, `enabled` is `true`, and its `interval`
  points at an `IntervalSchedule` whose `(every, period)` matches what
  `create_or_update_periodic_task` computes.
- `refresh_interval: 0` on a second source yields a `PeriodicTask` with `enabled: false` — the
  other side of `should_be_enabled = enabled and (use_cron or interval_hours > 0)`, and the
  reason the whole suite can use 0 safely.
- Deleting the source removes the `PeriodicTask` and, once nothing references it, the
  `IntervalSchedule` too (`_cleanup_orphaned_interval`).

The interval values used are recorded in `e2e/README.md`'s enumerated set per D21, with the
isolation exemption spelled out.

## Tags

G11 owns the taxonomy (D20). Every test G12 adds or touches is `@characterization`, and the
reason is the same in all four cases and is a property of the **file**, not of the assertion:
each of these specs destructures the `instance` fixture, `instance` is the `CONTAINER_LIFECYCLE`
capability in `e2e/tests/guards/allowlist.ts`, and ADR 0002 makes anything on a capability list
`@characterization` by construction. Both existing lifecycle specs already carry the tag at
HEAD — `restart-persistence.spec.ts:23` and `upgrade-migrations.spec.ts:163` — so the two files
G12 deepens need no retag at all.

| Test | Tag | The `@characterization:` comment must say |
|---|---|---|
| `restart-persistence.spec.ts` (touched — assertions deepened) | `@characterization` (already) | Its existing comment pins the AIO container as the unit of restart, and stands. The added relations do not change it: extend it to say the relations themselves are portable — rows and orderings surviving a restart is behaviour any rewrite must preserve — and that only the *unit* being one container is not |
| `upgrade-migrations.spec.ts` (touched — same) | `@characterization` (already) | Its existing comment pins Django's migration state and the AIO image layout, and stands unedited. The `showmigrations` and `migrate --check` assertions are the coupled half; the relations added here are the portable half |
| `backup-restore.spec.ts` | `@characterization` | Every step is a documented REST endpoint and would survive any rewrite that kept `apps/backups` — but the test owns and resets a container, so it is on `CONTAINER_LIFECYCLE`. Say exactly that: the assertions are portable, the container ownership is not |
| `refresh-scheduling.spec.ts` test 1 | `@characterization` | Same shape. `refresh_interval` and `cron_expression` round-trip through the REST API (F11), so the assertions themselves are portable; the container ownership is what fixes the tag |
| `refresh-scheduling.spec.ts` test 2 | `@characterization` | Genuinely coupled on both counts: `manage.py dumpdata` against `django_celery_beat`'s tables, read through the AIO container layout, because the product exposes no other view of `PeriodicTask.enabled`. A rewrite that preserved behaviour but changed scheduler is expected to change this test |

**The concrete guard requirement.** `allowlist.ts` compares each capability's `allow` array with
`toEqual`, so a missing entry fails and a stale entry fails too. G12 must add both new spec
paths to `CONTAINER_LIFECYCLE.allow`:

```ts
    'tests/lifecycle/backup-restore.spec.ts',
    'tests/lifecycle/refresh-scheduling.spec.ts',
```

`e2e/tests/guards/allowlist.ts` therefore joins this goal's file list. Nothing else on the five
lists needs touching, and in particular `instance.manage(['dumpdata', …])` does **not** trip
`CONTAINER_INTROSPECTION`: that detector matches the literals `pgrep`, `docker ` and `manage.py`
in string and template literals only, and none of those tokens appears in a `dumpdata` argument
array. The `instance` fixture use is what is policed, through `CONTAINER_LIFECYCLE`.
`GLOBAL_SETTINGS_WRITE` already carries `tests/lifecycle/durable-state.ts`, for the
`system_settings` PATCH it has always made; **the seven relations of D11 add no `core/settings`
write of any kind** — they are channels, streams, profiles, EPG, XC, VOD, a recording and a logo
— so that list is correct as it stands and must not grow.

This also retires the open question in
[#42](https://github.com/D10Scot/Dispatcharr/issues/42) ("the `instance` fixture is guarded only
by a comment"): `CONTAINER_LIFECYCLE` is that guard. G12 touches the list and may say so in the
diff, but **closing #42 is G11's business, not this goal's** — the mechanism landed there.

## Bug policy, restated for this goal's findings

Unchanged from the roadmap, with the one wrinkle D3 records:

- Playwright tests assert **correct** behaviour and invert with `test.fail()` plus a comment
  naming the defect and its location.
- Bash scenarios have no `test.fail()`. A product defect found in the bash suites is filed and
  **not** reproduced, because a deliberately-red scenario re-breaks the workflow this goal exists
  to fix. A comment at the site names the issue instead.
- Issues are filed with `gh issue create --repo D10Scot/Dispatcharr`. The `--repo` flag is
  mandatory (`docs/agents/issue-tracker.md`).
- No product file is patched. Not `docker/init/*`, not `docker/entrypoint.sh`, not
  `dispatcharr/settings.py`, not `apps/**`. Fixing the `pg_upgrade` exit-status defect in this PR
  would be the single most tempting deviation in the goal, and it is out.

Expected filings: two product issues (F12a, F12b), plus whatever T4's reproduction turns up.
Issue #41 is *closed*, not filed.

## Test inventory

| Row | File | Tests | Project |
|---|---|---|---|
| Lifecycle relations survive a restart | `restart-persistence.spec.ts` (existing test, deeper) | 0 new | `lifecycle` |
| Lifecycle relations survive an upgrade | `upgrade-migrations.spec.ts` (existing test, deeper) | 0 new | `lifecycle-upgrade` |
| Backup → mutate → restore recovers the backed-up state and discards the later state | `backup-restore.spec.ts` | 1 | `lifecycle-restore` |
| Non-zero `refresh_interval` and `cron_expression` round-trip and switch | `refresh-scheduling.spec.ts` | 1 | `lifecycle-scheduling` |
| The scheduled `PeriodicTask` is enabled, its `IntervalSchedule` matches, and delete cleans up | `refresh-scheduling.spec.ts` | 1 | `lifecycle-scheduling` |
| 20 puid-pgid scenarios green | `docker/tests/test-puid-pgid.sh` | — | `lifecycle-tests.yml` |
| 8 tls-postgres scenarios green | `docker/tests/test-tls-postgres.sh` | — | `lifecycle-tests.yml` |

Three new Playwright tests. The relation work adds no test titles by design (D10) — it makes two
existing tests mean roughly seven times more.

## Risks

| Risk | Mitigation |
|---|---|
| The upgrade spec's **baseline** image is an older `main` commit that cannot ingest the extended seed (an XC account, a VOD catalogue) | Every seeding step runs on the baseline; a baseline that cannot do it fails loudly at seed time with the fixture's own error. The oldest reachable baseline post-dates G8, which added XC to the provider. If this ever bites, the answer is to narrow the seed, never to widen the fallback |
| `pg_upgrade` proves to be a real product defect (F12b), and the scenario must be quarantined to reach green | D8's decision rule allows exactly that, and requires the `log_skip` message to name the issue. A quarantine that does not name its issue is not green |
| Fixing #41 changes the disk profile enough to mask, rather than fix, T4 | The plan re-runs and records the outcome either way; D8's rule is about *where the entrypoint blocks*, not about whether the run happened to pass |
| Restore leaves pooled connections pointing at dropped tables and the instance never recovers | D15: poll, and if in-place recovery genuinely does not work, that is a finding — file it and `test.fail()` the assertion, do not add a restart to get green |
| The two new projects collide with G11's edits to `playwright.config.ts` and `lifecycle-tests.yml` | Retired: G11 merged as `4211cbb7`/`7a408c2b`, and G12 branches from `origin/main` at or after `45a33a4a`. Both edits are additive to what is now on `main` |
| A new spec is written without a tag, or with the details object hoisted to a const | `e2e/tests/guards/tags.spec.ts` fails closed on both, in the `guards` job, in about a second. The failure names the declaration. This is the cheapest guard in the suite to satisfy and the easiest to forget (D20) |
| The new spec paths are added to `playwright.config.ts` but not to `CONTAINER_LIFECYCLE.allow` | `capabilities.spec.ts` compares with `toEqual`, so the omission fails rather than passing silently — and so would a stale entry left behind if a spec were renamed (§ Tags) |
| The scheduling spec's enabled beat task fires during the run and mutates rows | Its instance is its own, nothing else asserts on it, and the smallest interval is one hour against a test that finishes in seconds |

## Non-goals — deliberately out of scope

- **Any change to product code.** `docker/init/*`, `docker/entrypoint.sh`,
  `dispatcharr/settings.py` and everything under `apps/` are read-only here. The two defects in
  F12 are filed, not fixed. This is the roadmap's rule 5 and it is the single most likely place
  for this goal to over-reach.
- **Reproducing either filed product defect in a test.** D3. A bash suite cannot express
  `test.fail()`, and a red scenario re-breaks the workflow.
- **Waiting out a real `refresh_interval` tick.** D18. The smallest schedulable interval is one
  hour.
- **DVR execution.** A recording that actually fires is G13. G12 creates a `Recording` **row** as
  a durable-state relation and asserts it survives; it never lets it run.
- **The remaining accepted coverage gaps** — EPG fuzzy matching, ACL 403 negatives, behavioural
  settings, plugin run lifecycle, bulk operations, M3U profiles, product WebSocket events. All
  G14.
- **Backporting `test.fail()` premise guards, deepening thin frontend specs, `expectWellFormedXml`,
  the residual first-byte-only TS assertions.** All G15, whose file list is fixed and disjoint
  from this one.
- **Defining the `@contract`/`@characterization` taxonomy, generalising the capability guard, or
  building the full-run CI mode.** All G11, and all landed. G12 applies the tags, adds its two
  spec paths to `CONTAINER_LIFECYCLE.allow`, and gives its new job the same `if:` as
  `upgrade-migrations`. It changes no guard's logic and adds no capability.
- **Adding `Lifecycle result` to the Main ruleset.** G12 is what makes that possible — the
  workflow's header says the check "must not be added to the Main ruleset until G12 leaves both
  bash suites green" — but the ruleset itself is a repository setting, not a file in this diff,
  and turning it on is a judgement about merge policy the maintainer makes once the green run
  exists. **G12's Definition of done is a green run, not a changed ruleset**; the plan says so,
  and the follow-up is the maintainer's.
- **Absorbing G14's `CoreSettings` handoff.** G14's D10 hands G12 one new `COVERAGE.md` row for
  "every global `CoreSettings` group with behavioural effect", on the reasoning that G12 is
  already standing up isolated instances so one more row costs it a fixture call. **Declined.**
  G12 is the largest goal in wave 6 — four pieces, two bash suites, three new Playwright tests
  and a workflow job — and that row is a different subject: it is about instance-wide settings
  affecting matching, streaming and proxying, not about what survives a container event. Taking
  it would widen the goal that can least afford it, and it would arrive with no owner for the
  streaming-side assertions it implies. **G14 records the gap as unowned** rather than
  attributing it here. Worth naming for whoever picks it up: the migration-relevant member of
  that set is `network_access["STREAMS"]`, the ACL on `/proxy/ts/stream/` — the endpoint the
  relay extraction moves, gated by `network_access_allowed(request, "STREAMS")` in
  `apps/proxy/live_proxy/views.py:stream_ts` with no user, and by the same call **with** a user
  in `:stream_xc`. A later goal should own it, on an isolated instance, and should own it before
  the extraction rather than after.
- **Re-litigating anything in the disposition's "Refuted" section** — the logo byte-length claim,
  the `m3u-ingest.spec.ts` source-text assertion, "`lifecycle-tests.yml` has never run", "the
  suite isn't black-box enough". C1–C4 above correct the disposition where re-checking showed it
  wrong; they do not reopen anything it refuted.
- **Repairing the release-image seeding path rather than removing it.** D4. There is no version
  of `ghcr.io/dispatcharr/dispatcharr:latest` that will be pre-PUID again.
- **A repo-wide Dockerfile pinning sweep.** Roadmap non-goal. `docker/Dockerfile` and
  `docker/DispatcharrBase` still carry floating tags; leave clean anything this goal touches and
  go no further. Note the tension and accept it: `RELEASE_IMAGE` and `postgres:16` are floating
  tags in *test* files, and D4 removes one of them because it broke a test premise — not as part
  of a pinning programme.
- **Performance or load testing.** Roadmap non-goal.
