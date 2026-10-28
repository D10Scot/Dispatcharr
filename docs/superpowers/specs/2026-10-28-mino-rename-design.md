# Renaming Dispatcharr to Mino

**Date:** 2026-10-28
**Status:** Draft
**Parent:** [ADR 0010](../../adr/0010-the-product-is-renamed-mino-and-upstream-is-no-longer-tracked.md)
(the product is renamed Mino, and upstream is no longer tracked). It lands in this spec's own
branch.
**Owner rulings** (override any default here): M1 no more syncing with upstream; M2 no deployment
but the owner's, which must upgrade in place with its data; M3 the repository becomes
`D10Scot/mino` and the app is `D10Scot/mino-apple` (`scot.d10.mino`); M4 decision records keep the
old name. Restated in Appendix A.
**Verified at:** `main` `632f1d3d`. Every `file:line` below was read there. Line numbers drift.
Identifier names, route shapes and env var names are the durable part of each citation.

Implement this plan task by task with subagents, per CLAUDE.md § Delegation for phase work.

## Goal

Everything a user, an operator or a client sees says **Mino**. The repository is
`D10Scot/mino`, and the image is `ghcr.io/d10scot/mino`. The owner's instance upgrades in place
and keeps its PostgreSQL rows, its `/data` volume, recordings, plugins and settings.

Renaming is the whole charter. No PR in this programme refactors, fixes a defect it walks past, or
"tidies" an identifier this spec keeps. Each PR in § PR sequence is a legitimate stopping point.
After C1 and C2 the product already *reads* as Mino.

## How to read this spec

- § Scale gives the measured inventory.
- § The rule says how a category is decided.
- § Categories decides every category.
- § PR sequence orders the work. Each PR has its verification and a PR-description draft.
- § The repository rename covers the owner's settings action and what breaks or redirects.
- § Owner actions lists everything done by hand, in order.
- § Open questions holds decisions this spec recommends but cannot settle.

## Scale (measured at `632f1d3d`)

```bash
git grep -i -c dispatcharr 632f1d3d -- . | awk -F: '{s+=$NF; n++} END {print n" files, "s" lines"}'
#   694 files, 7200 lines
git grep -i -o dispatcharr 632f1d3d -- . | wc -l      # 8580 occurrences
git ls-files | grep -i dispatcharr | wc -l              # 31 paths
```

The dispatch brief's figures (about 7,200 hits in 694 files, 31 paths) hold. Files with a hit, by
top-level directory: apps 162, relay 113, docs 110, e2e 81, frontend 41, docker 35, scripts 22,
e2e-upstream 22, .github 19, `dispatcharr/` 17, root files 15, tests 14, core 14, .claude 14,
dashboard 9, metrics 3, .idea 3.

**Env var names.** The brief estimated 94 distinct `DISPATCHARR_*` variables. That is not what the
tree holds. In living files (records excluded), `git grep -h -o -E 'DISPATCHARR_[A-Z0-9_]*[A-Z0-9]'`
yields 58 distinct tokens:

- 34 are environment variables read by the product (Appendix B lists them).
- 16 are read only by development tooling: `DISPATCHARR_E2E_*` (12), `DISPATCHARR_TEST_*` (3) and
  `DISPATCHARR_WRITE_GOLDEN`.
- 3 are Django setting names read by `getattr(settings, …)`, never env vars:
  `DISPATCHARR_PLUGIN_IMPORT_MAX_{FILES,BYTES,FILE_BYTES}` (`apps/plugins/api_views.py:57-59`).
- 5 are fragments, not variables: the three tails of `HTTP_X_DISPATCHARR_*`, the `DISPATCHARR_E2E`
  prefix, and the local variable `DISPATCHARR_HEADERS` (`core/tasks.py:818`).

**Records.** The record globs below (§ The rule, R-1) hold 5,500 of the 7,200 lines. Nearly all
of them are in `docs/superpowers/plans/` (3,868 lines) and `docs/superpowers/specs/` (527). The
work is the remaining 1,700 or so lines in living files.

**Inventory by category.** The script is in the scratch notes. It assigns each hit *line* to the
first category whose pattern matches it, in the order below, so these are line counts, not
occurrence counts. "Living" excludes the record globs.

| # | Category | Living lines / files | Records | Representative anchor | Decision | PR |
|---|---|---|---|---|---|---|
| 1 | Go module path `github.com/D10Scot/Dispatcharr/relay` | 218 / 107 | 241 | `relay/go.mod:1` | rename | G1 |
| 2 | Repo identity: `D10Scot/Dispatcharr`, `ghcr.io/d10scot/dispatcharr`, the Pages URL | 221 / 73 | 490 | `docker/docker-compose.aio.yml:6` | rename | D1, D2 |
| 3 | Upstream identity: `Dispatcharr/Dispatcharr`, its docs site, Open Collective, Docker Hub, Plugins repo | 38 / 18 | 43 | `core/tasks.py:924` | per row (§ C-3) | C1, C2, D2 |
| 4 | Wire headers `X-Dispatcharr-*` / `HTTP_X_DISPATCHARR_*` | 126 / 37 | 247 | `apps/proxy/internal_auth.py:56-58` | rename, atomic | W1 |
| 5 | Internal routes `/_dispatcharr/authorize[-internal]` | 35 / 12 | 86 | `dispatcharr/urls.py:47,59` | rename, atomic | W1 |
| 6 | nginx include *file names* `dispatcharr_api_params*.conf` | 35 / 6 | 105 | `docker/nginx.conf:98` | keep (internal file name) | — |
| 7 | Tooling env vars `DISPATCHARR_{E2E,TEST}_*`, `_WRITE_GOLDEN` | 134 / 20 | 244 | `.claude/hooks/start-test-container.sh:19` | rename | E1 |
| 8 | Product env vars `DISPATCHARR_*` | 559 / 88 | 846 | `docker/entrypoint.sh:21` | alias, then refuse | E1, E2 |
| 9 | Django app labels and table names `dispatcharr_channels`, `dispatcharr_connect` | 137 / 58 | 52 | `apps/channels/apps.py:7` | keep | — |
| 10 | Python package `dispatcharr` (settings, wsgi, asgi, celery, urls) | 267 / 135 | 516 | `manage.py:13` | keep (owner question Q1) | — |
| 11 | venv path `/dispatcharrpy` | 30 / 20 | 88 | `docker/DispatcharrBase:10-11` | keep | — |
| 12 | Test containers, volumes and images (`dispatcharr-testrunner`, `-hookdb`, `-e2e`, …) | 75 / 24 | 395 | `.claude/hooks/_hook_common.sh:121` | keep (owner question Q6) | — |
| 13 | Hypothesis profile `dispatcharr-ci` | 54 / 28 | 57 | `tests/test_redaction.py:30` | keep | — |
| 14 | Build file names `docker/DispatcharrBase`, `docker/init/03-init-dispatcharr.sh` | 25 / 10 | 48 | `.github/workflows/base-image.yml:7` | keep | — |
| 15 | Plugin manifest keys `min_/max_dispatcharr_version` | 86 / 12 | 1 | `apps/plugins/api_views.py:1215-1216` | keep (third-party contract) | — |
| 16 | DB name and role defaults `dispatcharr` / `dispatch` | 44 / 14 | 40 | `dispatcharr/settings.py:285-286` | keep | — |
| 17 | Local checkout and memory path `~/git/Dispatcharr` | 6 / 5 | 484 | `.claude/skills/worktree-per-change/evals/evals.json` | owner action H-9 | — |
| 18 | User-Agent strings and helpers | 45 / 12 | 13 | `core/utils.py:25-33` | rename the strings; keep the helper names (C-18) | U1 |
| 19 | Browser storage keys | 22 / 7 | 5 | `frontend/src/App.jsx:43` | keep | — |
| 20 | Backup archive naming | 10 / 3 | 2 | `apps/backups/services.py:246` | rename, read both | P1 |
| 21 | Other lowercase identifiers (sample compose names, `pyproject` name, Redis keys, Celery app name, …) | 151 / 65 | 195 | `docker/docker-compose.aio.yml:14` | per row (§ C-21) | C1, D2 |
| 22 | Prose "Dispatcharr" (UI, docs, logs, comments) | 403 / 153 | 276 | `frontend/index.html:27` | rename | C1, C2 |

## The rule

**R-1. Records keep the old name (M4).** A file is a *record* when it describes a decision or event
as of a date, and is changed after acceptance only by an appended amendment. By path, the records
are exactly:

- `docs/adr/**`
- `docs/superpowers/specs/**`, `docs/superpowers/plans/**` and `docs/superpowers/analysis/**`
- `docs/comparisons/**` (untracked in the root checkout today, and a record when committed)
- `CHANGELOG.md`, whose entries are upstream's release history and the fork's v0.29.0 baseline

Every other tracked file is *living*. That includes `CLAUDE.md`, `CONTEXT.md`, `README.md`,
`docs/agents/**`, `docs/supply-chain.md`, `docs/relay-parity-matrix.md`, `e2e/COVERAGE.md`,
`e2e/README.md`, `metrics/curated/**` and the skills' `references/project.md`. A record is **never
moved or renamed**: `D10Scot/mino-apple` pins blob URLs to records (for example the Phase 4 spec at
`86e11fe6`), and GitHub's redirect preserves those pins only if the path is unchanged. R1's checker
encodes this list. It is the one place the rule is enforced, so editing that list is how the rule
is amended.

**R-2. Rename what is seen.** An identifier is renamed when a user, an operator, a client or an
external system sees it, or when it states the repository's or the image's identity.

**R-3. Keep what persists or what a third party holds.** An identifier is kept, and listed in
`CONTEXT.md` as an internal name, when:

- persisted data depends on it (table names, migration history, the database name, volume names),
- a party outside this repository depends on it (plugin manifests, Plex's view of the HDHomeRun
  device id), or
- it is an internal file or path name whose rename would buy no reader anything but would put a
  path-matched guard at risk.

CLAUDE.md warns that "a file renamed out of [a path-matched arm] stops being checked with no error
and no output". So R-3's last clause is deliberate: **this programme renames no tracked file
path**. Every one of the 31 tracked paths containing "dispatcharr" stays (Appendix C), and
consequently no hook arm, CI path filter or coverage rcfile entry can silently drop out. The one
exception would be the logo assets, if the owner supplies new art (Q3). That would be an image
swap at the same path.

**R-4. Prefer one atomic change to a transition.** Where both sides of a contract ship in the same
image (headers, internal routes, the DVR User-Agent and its matcher), they change together in one
PR with no dual acceptance. A transition window exists only where the other side is outside the
image: the owner's compose file (env vars, E1→E2) and the owner's existing backup files (P1, read
both forever).

## Categories

### C-1 Go module path — rename (G1)

`relay/go.mod:1` declares `module github.com/D10Scot/Dispatcharr/relay`. 103 files in `relay/`
import it (203 import lines). The module is stdlib-only and is never fetched by path, so the
change is purely a name. Even so, it names the repository, and per R-2 it is renamed to
`github.com/D10Scot/mino/relay`.

Five non-import sites key on the module path, and each fails closed if it is missed. The list is
complete at `632f1d3d`: `git grep -n 'D10Scot/Dispatcharr/relay' 632f1d3d -- relay scripts
':!*.md'`, minus `import` lines and `relay/go.mod`, prints these five plus one more line. That
line is `scripts/coverage_relay_go.floor:81`, a comment in the floor's PROVENANCE header that
quotes a sample coverprofile line. It gates nothing, because `--gate` reads only `key=` fields.
`--write-floor --shape-only` does **not** rewrite it: `set_field` replaces only lines matching
`^key=` (`scripts/coverage_relay_go.sh:390-401`). G1 updates the comment by hand so that it shows
the profile format as it now is.

- `scripts/check_go_stdlib_only.sh:19` (`EXPECTED=`). The stdlib check fails.
- `scripts/coverage_relay_go.sh:102` (`grep '^github.com/D10Scot/Dispatcharr/relay'`). The linked
  package list comes back empty and `packages=` mismatches.
- `scripts/coverage_relay_go.floor.packages:1-12` and the floor's `packages=40d4ba02d7d3` and
  `gomod=92baf312d30d` (`scripts/coverage_relay_go.floor:265,267`). The gate refuses the shape.
- **`relay/internal/credlint/check.go:69`**, the sanitizer key
  `"github.com/D10Scot/Dispatcharr/relay/redact.Error": true`. If it is missed, every
  `redact.Error` call stops counting as a sanitizer, and credlint reports every guarded error
  argument. That is loud, but it is the site most likely to be "fixed" wrongly by adding
  `// credential-logging: ok` markers. G1's reviewer checks that the PR adds no marker.
- **`relay/internal/credlint/check_test.go:105`**, `TestTheRedactorIsExactlyRedactError`. It
  asserts the same literal key. `go mod edit` and an import rewrite do not touch a string inside a
  test. The test then fails on purpose, and the fix is to change the literal to the new path. That
  is a rename of the pinned behaviour, so it is listed with before and after under the
  test-modification rule. Weakening the assertion is not a fix.

### C-2 Repository and image identity — rename (D1 before the repo rename, D2 after)

The image name is derived, not written. `base-image.yml:73`, `ci.yml:98`, `docker-build.yml:68-70`,
`release.yml:202` and `vuln-scan.yml:167,204` compute `ghcr.io/<owner>/<repo>` from
`github.repository`. **The moment the repository is renamed, every push publishes to
`ghcr.io/d10scot/mino` and every base lookup asks for `ghcr.io/d10scot/mino:base`**, which does not
exist until `base-image.yml` first runs on the renamed repository.

The hard-coded sites do *not* follow the rename. Two are silent hazards:

- `e2e-tests.yml:164` and `lifecycle-tests.yml:190` build with `--build-arg REPO_OWNER=…` only.
  `docker/Dockerfile:3` defaults `REPO_NAME=dispatcharr`, so after the rename the E2E and lifecycle
  images would keep building on the frozen `ghcr.io/d10scot/dispatcharr:base`. Nothing would fail,
  but those suites would stop testing the base that production ships on. `docker/tests/test-puid-pgid.sh:2042`
  has the same shape. **D1 fixes these before the rename.**
- `metrics.yml:137` runs its coverage job in `ghcr.io/d10scot/dispatcharr:base`, hard-coded. It is
  not a required check, so between the rename and D2 it runs on the stale base. That is accepted.

The remaining hard-coded identity is moved by D2: compose `image:` lines, docs, scripts, metrics,
dashboard links, skills' `project.md`, `--repo` mentions and issue links.
`docker/Dockerfile:2-3` also defaults `REPO_OWNER`/`REPO_NAME` to **upstream's** `dispatcharr/dispatcharr`,
a default inherited from upstream. D2 sets it to `d10scot/mino`.

### C-3 Upstream identity — per row

Under M1, a link that sends a user to upstream for *this* product's support is wrong, and a link
that credits upstream is right. Decided per row:

| Site | Decision | PR |
|---|---|---|
| `core/tasks.py:924` stable update check → `api.github.com/repos/Dispatcharr/Dispatcharr/releases/latest` | Repoint to `D10Scot/mino`. No release exists yet, so it answers 404. A non-200 answer already returns with no notification (`core/tasks.py:931-933`), but it logs at WARNING. That would fire on every daily beat run (`dispatcharr/settings.py:455-458`) and every worker start (`dispatcharr/celery.py:244-246`), so D2 logs a **404 specifically** at INFO ("no release published for D10Scot/mino yet"). Every other non-200 stays at WARNING. A 404 is the expected state until the first release, and a WARNING that always fires teaches the owner to ignore WARNINGs. | D2 |
| `core/tasks.py:817-907` dev-build branch: when `__timestamp__` is set it polls upstream's Docker Hub `dispatcharr/dispatcharr:dev` (`:822`) and raises an admin notification linking upstream's Docker Hub (`:878`) | **Disable it in D2**, in the same PR that repoints the stable check (C-3a). | D2 |

**C-3a, why the dev branch is disabled rather than repointed.** It is live, not dead.
`docker/Dockerfile:87-92` writes `__timestamp__` into `version.py` whenever the `TIMESTAMP`
build-arg is given, and `ci.yml:75-78,218-222` gives it. So any `:latest` that `ci.yml` published
takes this branch (`core/tasks.py:817`), and under M1 it tells the owner about *upstream's* dev
builds. Repointing it needs an equivalent signal on GHCR, and none exists without new machinery:

- Docker Hub answers `last_updated` for a tag in one anonymous request.
- GHCR's anonymous OCI API exposes manifests and config blobs but no per-tag update time. A
  multi-arch index carries no creation time, so the check would need a token request, the index,
  a platform manifest and the config blob, which is four requests and a new parser.
- The GitHub Packages REST API has `updated_at`, but it requires a token with `read:packages` even
  for a public package, and the instance has none.

Either option is a new feature, not a rename. So in D2 the dev branch makes **no network call**.
It deletes any existing `version_update` notification whose key starts with `version-dev-`,
because those all link to upstream, logs once at DEBUG that the dev-build check is disabled, and
returns. Tests (new, in `core/tests/`):

- With `__timestamp__` patched to a value, `requests.get` is asserted not called, and a seeded
  `version-dev-…` notification is gone.
- With `__timestamp__ = None` and a mocked 404, no notification is created and an INFO record is
  emitted, not a WARNING.
- With a mocked 500, a WARNING is emitted.

Break-checks: restore the Docker Hub call, and the first test reddens on `requests.get` being
called. Log the 404 at WARNING, and the second test reddens naming the level. A GHCR-backed dev
check, if the owner wants one, is Q4.
| `frontend/src/components/AboutModal.jsx:49,62,75,91`, `Sidebar.jsx:44-47`: docs, Discord, GitHub and Open Collective links | Replace with `github.com/D10Scot/mino` for code and issues. Remove the support and funding links (Q5), and add one attribution line: "Mino is derived from Dispatcharr (AGPL-3.0)", linking `github.com/Dispatcharr/Dispatcharr`. | C1 |
| `README.md:4,87-88,137,145,166,172,181`, `CONTRIBUTING.md:257`, `.github/FUNDING.yml:5` | Same treatment as the About dialog. `FUNDING.yml` per Q5. | C2 |
| `apps/output/epg.py:1146` `generator-info-url` | Repoint to `github.com/D10Scot/mino`. | D2 |
| OCI `image.documentation` annotation → `dispatcharr.github.io/Dispatcharr-Docs/` (`base-image.yml:137,208,226`, `ci.yml:197,276`, `release.yml:315,383`) | Repoint to `https://github.com/${{ github.repository }}`. | D2 |
| `apps/plugins/models.py:39` `OFFICIAL_REPO_URL`, migrations `0002`/`0003`, `apps/plugins/keys/dispatcharr-plugins.pub`, the "Dispatcharr Official" repo row | **Keep.** This is upstream's plugin registry and upstream's signing key. They are correctly named for upstream, and repointing them is a feature decision. | — |
| `debian_install.sh:228` clone URL | Repoint to `D10Scot/mino`. The script's service names and paths stay (R-3, and Q7). | D2 |
| `SECURITY.md:3,18-20`: "personal fork of Dispatcharr", upstream's advisory link | Keep, as attribution. Reword the subject to Mino. | C2 |

### C-4/C-5 Wire headers and internal routes — rename atomically (W1)

**Names.** `X-Dispatcharr-Authorized` → `X-Mino-Authorized`, `X-Dispatcharr-Internal` →
`X-Mino-Internal`, `X-Dispatcharr-Internal-Request` → `X-Mino-Internal-Request`,
`X-Dispatcharr-Session` → `X-Mino-Session` (a VOD response header, `apps/proxy/vod_proxy/views.py:1118`),
`/_dispatcharr/authorize` → `/_mino/authorize`, and `/_dispatcharr/authorize-internal` →
`/_mino/authorize-internal`.

**Sites.** The readers and writers are:

- Django: `apps/proxy/internal_auth.py:56-58,78-80`, `apps/proxy/authorize_views.py`,
  `apps/proxy/permissions.py`, `apps/proxy/authorize.py`, `apps/channels/tasks.py` (the DVR's
  ffmpeg `-headers`), and `dispatcharr/urls.py:47,59`.
- nginx: `docker/nginx.conf`. It has ten `/_dispatcharr/authorize` lines (124, 155, 305, 367, 393,
  493, 555, 581, 607, 652) and nine marker-setting lines (136, 336, 379, 405, 524, 567, 593, 619,
  683); every other hit is a comment. Also the *contents* of
  `docker/dispatcharr_api_params.conf:23` and `docker/dispatcharr_api_params_proxy.conf:38`, and
  `docker/init/03-init-dispatcharr.sh` (comment only; it computes `RELAY_TRUST_TOKEN` by value).
- The Go relay: `relay/control/token.go:29-31`, `relay/control/authorize.go:23`,
  `relay/httpapi/{stream,authorize,channels,hls}.go`, and `relay/internal/relaytest/controlplane.go:312`.
- Tests and specs: the tests, `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts`,
  `e2e/tests/streaming/authorize-matrix.spec.ts`, `e2e/tests/dvr/recording-hidden-channel.spec.ts`
  and `docker/tests/test-puid-pgid.sh`.
- Docs: `docs/relay-parity-matrix.md` (the text of rows 19, 30 and 38, at `:187`, `:203` and
  `:212`), `e2e/COVERAGE.md`, the `.gitleaks.toml:20`
  description and `CLAUDE.md`.

**Why it needs no reader transition.** nginx, Django and the relay ship in one image, and in the
modular compose every service runs the same tag (`docker/docker-compose.yml:10,146,214`). The
modular services still restart one at a time, so for a short while an old container can talk to a
new one. In that window an untrusted marker does **not** produce a refusal. It falls back to the
paths that already exist for a missing or mismatched marker:

- **The Go relay**, seeing no marker it trusts, reads no `X-Relay-*` value. It authorizes the tune
  itself, through the dev fallback `POST /_dispatcharr/authorize-internal`
  (`relay/httpapi/stream.go:395-418`, `relay/control/authorize.go:16-23`). Against a Django on the
  other version, that POST goes to a route name the other side does not serve. The answer is a
  404, and the tune fails.
- **The Python relay** (`relay-uwsgi`: VOD and catch-up), seeing no marker it trusts, authorizes
  the request inline with `authorize_stream()` (`apps/proxy/authorize_views.py:189-200`). It
  serves the request on its own decision, so the client gains no privilege. In the mixed window
  this is **silent**: the one-time WARNING at `:195` fires only when a marker is *present under
  the name the process reads* and mismatches. A marker under the other name reads as absent, so
  nothing is logged.
- **The reverse direction**, a client's new-named header passing through an *old* nginx, is
  harmless. On a relay-bound location the old nginx still sets every `X-Relay-*` value itself
  (`nginx.conf:337-342` and the `uwsgi_param` twins), so a client-supplied `X-Mino-Authorized`
  can at most make a new relay trust values that nginx, not the client, wrote. On a location
  outside the authorize hop, the marker is useful only with a valid HMAC, which the client does not
  have unless it has already leaked. That is the case the permanent old-name blanks below exist
  for.
- **Django's internal surfaces**, seeing no internal header they accept, answer 403.
- **The third container is a sender, not a reader.** The modular `celery` service (role `worker`,
  `docker/docker-compose.yml:213-241`) holds no reader on this surface, but
  `apps/channels/tasks.py:1227` puts the internal header on the DVR's ffmpeg fetch of
  `/proxy/ts/stream/`. A worker on the other version from `web` loses the internal principal until
  it restarts: the new nginx blanks the old name, and the old authorize hop ignores the new one.
  The recording of a hidden channel fails to tune in that window; an ordinary channel records as an
  anonymous client. It degrades to a client, never to a trusted one, so it is safe, and W1's
  reviewer should not rediscover it.

None of these paths accepts a header without checking its HMAC, and no reader accepts both names,
so W1 creates no such path. What W1 must still prevent is the old name passing *through* a new
nginx to an old reader. The blank lists below handle that.

**What does not change, deliberately.** The HMAC derivation labels `"relay-trust"`,
`"internal-principal"` and `"media-session"`, and the `v1.<ts>.<hex>` request format, stay as they
are (`apps/proxy/internal_auth.py:6,13`, `relay/control/token.go:9-14`). Changing a label would
rotate every token for no gain. It would also invalidate the HMAC parity vectors that
`.gitleaks.toml:20` allowlists by value. Two consequences follow:

1. **The marker value is unchanged.** A captured `X-Dispatcharr-Authorized` value is a valid
   `X-Mino-Authorized` value until `SECRET_KEY` rotates. So `SENSITIVE_HEADERS`
   (`dispatcharr/utils.py:79-80`) **adds** `x-mino-authorized` and `x-mino-internal` and **keeps**
   the two old names. Redacting a header name nothing sends costs nothing, and a log line carrying
   an old-named header is still a secret.
2. **The blank lists cover both names, permanently.** A client must not be able to deliver the
   marker or the internal pair under either name.
   - Both includes blank both marker names: `docker/dispatcharr_api_params.conf` (`uwsgi_param
     HTTP_X_DISPATCHARR_AUTHORIZED ""` and `uwsgi_param HTTP_X_MINO_AUTHORIZED ""`) and
     `docker/dispatcharr_api_params_proxy.conf` (the two `proxy_set_header … ""` twins).
   - The proxy include is the one that `^~ /proxy/relay/` and `^~ /hls/` use. It also blanks the
     **old** internal pair, `X-Dispatcharr-Internal` and `X-Dispatcharr-Internal-Request`. The
     uwsgi include blanks the same pair as `HTTP_X_DISPATCHARR_INTERNAL` and
     `HTTP_X_DISPATCHARR_INTERNAL_REQUEST`.
   - Neither include blanks the **new** internal pair. Django sends `X-Mino-Internal` and
     `X-Mino-Internal-Request` through `^~ /proxy/relay/` as an ordinary client, and the relay
     sends them to `/api/relay/…`. Blanking them would break those calls. These locations do not
     blank the pair today (`dispatcharr_api_params_proxy.conf:38-44` blanks only the marker and the
     `X-Relay-*` names) for the same reason.

   The marker locations that *set* `X-Mino-Authorized` (`nginx.conf`'s nine `uwsgi_param`/
   `proxy_set_header … "RELAY_TRUST_TOKEN"` lines, at 136, 336, 379, 405, 524, 567, 593, 619 and
   683) do not use either include. They declare their own directives, and a location that declares
   any `proxy_set_header` or `uwsgi_param` inherits none from the enclosing level
   (`nginx.conf:316-320`, and the header of `dispatcharr_api_params.conf`). So each of them gains
   explicit `""` lines for the old marker name and for the old internal pair, beside its
   `X-Mino-Authorized` line. The new internal pair passes through these locations untouched,
   because the DVR's ffmpeg sends it on `/proxy/ts/stream/` legitimately.

   The old-name blank lines **stay permanently**, for the reason `SENSITIVE_HEADERS` keeps the old
   names. Both header values are unchanged, so an old name delivered to an old reader is as good as
   the new one. Blanking a name nothing sends costs nothing, and it removes any need to reason
   about which container versions coexist. W1's tests pin that no new reader honours an old name
   and that nginx blanks both names.

W1 is security-adjacent. Its review runs on `fable` from round one.

### C-6, C-11, C-14 Internal file and path names — keep

These are kept by R-3:

- `docker/dispatcharr_api_params*.conf` and their `/etc/nginx/` install paths
  (`docker/Dockerfile:69-70`)
- `/usr/share/dispatcharr/nginx.conf.template` (`docker/Dockerfile:68`)
- `/etc/profile.d/dispatcharr.sh` (`docker/entrypoint.sh:299`) and `/run/dispatcharr-role`
  (`docker/healthcheck.sh:21`)
- `/dispatcharrpy` (`docker/DispatcharrBase:10-11`, `docker/Dockerfile:57`). Renaming it means a
  base-image rebuild and 30 living references, for no reader.
- `docker/DispatcharrBase` (the `paths:` filter at `.github/workflows/base-image.yml:7,14`) and
  `docker/init/03-init-dispatcharr.sh` (107 references, records included)
- the migration file `apps/channels/migrations/0034_remove_stream_dispatcharr_stream_id_idx_and_more.py`
  and the index names it removes (history)
- `.idea/DispatcharrSM.iml`, `frontend/src/images/dispatcharr.svg` (Q3)

### C-7/C-8 Env vars — alias window, then refusal (E1, E2)

All 50 env var names are renamed `DISPATCHARR_X` → `MINO_X`, tooling included. The three Django
setting names become `MINO_PLUGIN_IMPORT_*`. Nothing sets them, so they need no alias. Renaming
the tooling names too is what lets E2's refusal be a plain prefix rule: no process reads any
`DISPATCHARR_` name at all.

**Why a window, and why a refusal after it.** The owner's compose file is outside the repository
and sets some of these names. A hard cut would silently ignore an old name, and the code would
fall back to defaults. Some of those defaults are wrong in the owner's shape:

- `DISPATCHARR_ENV=modular` falls to `aio` (`docker/entrypoint.sh:21`, `relay/control/baseurl.go:58`).
- `DISPATCHARR_TRUSTED_PROXIES` falls to loopback-only (`dispatcharr/utils.py:27-32`).
- `DISPATCHARR_SETUP_ALLOWED_IP` falls to private networks only.

So E1 accepts both names, and E2, after the owner has moved, refuses the old ones loudly instead of
ignoring them.

**E1, the alias.** The alias applies by **prefix**, with no list: for every variable named
`DISPATCHARR_<rest>` in the environment, if `MINO_<rest>` is unset it is set to the same value, and
one WARNING per variable names both names. If both are set and they differ, `MINO_` wins and the
WARNING says so. Every reader in the tree then reads only `MINO_*`.

The alias must run before any reader, in every process that can start without the entrypoint.
There are five choke points:

1. **`docker/entrypoint.sh`**, before line 11, through a new sourced snippet,
   `docker/env-alias.sh`. Everything launched from the entrypoint inherits the result:
   supervisord's `%(ENV_X)s` (27 references in `docker/supervisord.d/*.conf` and
   `docker/uwsgi*.ini`), uWSGI's `$(X)`, the nginx `sed`, the Go relay, Celery and Daphne. The
   entrypoint's `variables=(…)` list (`docker/entrypoint.sh:276-287`), which writes
   `/etc/profile.d/dispatcharr.sh` and `/etc/environment`, switches to the `MINO_` names.
2. **`docker/healthcheck.sh`** sources the same snippet. Docker runs `HEALTHCHECK` with the
   container's *configured* environment, not the entrypoint's exports, and this script reads
   `DISPATCHARR_ROLE`/`_RELAY_GO_PORT` (`docker/healthcheck.sh:25,33`).
3. **`dispatcharr/__init__.py`**, as its first statement, before `from .celery import app`. The
   `celery` import reads `DISPATCHARR_LOG_LEVEL` at import time (`dispatcharr/celery.py:15`). This
   covers `docker exec … python manage.py …`, which also bypasses the entrypoint, and every Django
   process. The body is `dispatcharr/env_alias.py` (E1).
4. **`relay/main.go`**, first in `main()`, as one call into `relay/config`'s `AliasLegacyEnv` (E1).
   It covers a `relay-go` started by hand in dev. `go test` never runs `main()`, so the relay's
   tests set the new names themselves, and the call line is pinned by review, not by a test.
5. **`frontend/devProxy.js:25`** reads `MINO_RELAY_GO_PORT ?? DISPATCHARR_RELAY_GO_PORT` for a vite
   started on the host.

Scripts run *by* the entrypoint or supervisord inherit point 1 and need nothing.
`scripts/e2e_up.sh:373-375` **keeps passing the old names** during the window. The
lifecycle-upgrade baseline is an ancestor image that knows only the old names, and the new image
accepts them through the alias, so the old names work for both.

**E2, the refusal.** At the same five points the alias becomes a refusal. Any `DISPATCHARR_*`
variable present makes the process exit non-zero, naming each variable and its `MINO_` name. The
two exceptions:

- the healthcheck reports unhealthy rather than exiting differently;
- `devProxy.js` throws at config load.

E2 also does three other things:

- it switches `scripts/e2e_up.sh` and every remaining passer to `MINO_*`;
- it deletes `^DISPATCHARR_` lines from `/etc/environment` at entrypoint start. This is defence in
  depth, not a known path: `docker/entrypoint.sh:276-309` rewrites those lines from the
  `variables=` list on every boot, a container runs one image for its whole life, and no E1+
  image writes an old name. The scrub costs one `sed` line and makes the refusal's guarantee hold
  regardless;
- it removes `docker/env-alias.sh`'s aliasing branch.

The refusal stays. It is a few lines per choke point, and it is the only thing that stops a
forgotten compose line from silently meaning "use the default".

**Rollback hazard, written into E1's description.** An image from before E1 ignores `MINO_*`. An
owner who has already renamed their compose variables and then rolls back to such an image must
rename them back, or the old image runs on defaults.

### C-9 Django app labels and table names — keep

`apps/channels/apps.py:7` sets `label = 'dispatcharr_channels'` and `apps/connect/apps.py:8` sets
`label = 'dispatcharr_connect'`. Those labels name the tables (`dispatcharr_channels_channel` and so
on), the `django_migrations` rows, the `django_content_type` rows and every swappable or FK string.
They appear as `to='dispatcharr_channels.…'` in 47 migration files (`git grep -c -E
"dispatcharr_(channels|connect)" -- '*/migrations/*.py' | wc -l`). Raw SQL also names the tables:
`apps/channels/migrations/0038_add_catchup_fields.py:12-47` and `apps/m3u/tasks.py:2013-2048`.

Renaming the labels would require one of two things:

- (a) editing historical migrations, which are themselves records and whose edited form would no
  longer describe the database the owner's instance migrated through; or
- (b) a `SeparateDatabaseAndState` relabel with `ALTER TABLE … RENAME`, content-type and
  migration-row rewrites, and a hand-written reverse.

Option (b) touches the one irreplaceable asset (M2) to change a string no user sees. **Kept.**
`CONTEXT.md` gains an "Internal names" entry recording this, so that the label is not "finished"
later. CLAUDE.md's trap note about the label (§ Test hooks: "`apps.channels` has label
`dispatcharr_channels`, and the guess `channels` hits the *Django Channels library*") stays true
and is unaffected.

### C-10 The `dispatcharr` Python package — keep (Q1)

The settings package is named in many places:

- 74 import statements in 52 files.
- `DJANGO_SETTINGS_MODULE` defaults in `manage.py:11,13`, `dispatcharr/{wsgi,asgi,celery,admin}.py`
  and `.claude/hooks/_pending_migrations.py:20`.
- `module = dispatcharr.wsgi:application` in five uWSGI inis, and `dispatcharr.asgi` in
  `docker/supervisord.d/daphne.conf:2`.
- `DJANGO_SETTINGS_MODULE=dispatcharr.settings` written into the sample modular compose
  (`docker/docker-compose.yml:187,288`) and therefore, most likely, into the owner's own compose
  file.
- The `ENGINE` path `dispatcharr.db.backends.postgresql_psycopg3` (`dispatcharr/settings.py:281`).
- `.coveragerc:4`, `pyproject.toml:64`, `_SHARED_PATH_PREFIXES` (`dispatcharr/test_discovery.py:11`)
  and the `dispatcharr/**` path filters in six workflows (`ci.yml:11,26`, `codeql.yml:29`,
  `docker-build.yml:12`, `e2e-tests.yml:12`, `metrics.yml:21`).
- Plugins, which run in-process and may import `dispatcharr.utils` (`Plugins.md` § Accessing
  Dispatcharr APIs from Plugins).

A missed path filter fails silently, and a plugin that imports the package breaks at load. No user
sees the package name. **Kept**, and recorded as an internal name. If the owner wants it renamed
anyway, Q1 says what that PR would need.

### C-12 Tooling container, volume and image names — keep (Q6)

The names are `dispatcharr-testrunner`, `dispatcharr-hookdb`, `dispatcharr-e2e`,
`dispatcharr-e2e-upstream:local`, `dispatcharr-e2e-data` and the `dispatcharr-e2e-image` artifact.

These are dev-loop names that live agents and the shared hook container depend on
(`.claude/hooks/_hook_common.sh:121`, `.claude/hooks/start-test-container.sh`,
`e2e/fixtures/instance.ts:68,72`, `e2e-tests.yml:154-338`). Renaming `dispatcharr-hookdb` drops the
`--keepdb` database. Renaming the test container strands every running agent's hook until it is
re-pointed. No user sees them. **Kept**, with Q6 asking whether the owner wants them in a final
optional PR. The *env vars* that override them are renamed in E1 (C-7). Their default values stay
the same.

### C-13 Hypothesis profile `dispatcharr-ci` — keep

It is registered byte-identically in every `@given` module (`tests/test_redaction.py:30-32`), and
it is a test-internal label. Kept.

### C-15 Plugin manifest keys — keep

`min_dispatcharr_version` and `max_dispatcharr_version` are fields that third-party plugin
registries publish (`Plugin_repo.md:70-71,153-154`) and that this server reads
(`apps/plugins/api_views.py:1215-1258`, `frontend/src/components/cards/AvailablePluginCard.jsx:236-240`,
`PluginDetailPanel.jsx:107-112`). Renaming them would make every existing manifest
version-unconstrained. Kept. Their *user-facing text* ("requires Dispatcharr {min}") is renamed in
C1. Version numbering also continues from `0.29.0` with no reset (`version.py`), because these
comparisons read it.

### C-16 Database name and role — keep

`dispatcharr/settings.py:285-286` defaults the database to `POSTGRES_DB` → `"dispatcharr"` and the
role to `POSTGRES_USER` → `"dispatch"`. `docker/entrypoint.sh:11-12` exports the same defaults.

**Changing the default is a data-loss trap.** In AIO, `docker/init/02-postgres.sh:376-401` creates
`$POSTGRES_DB` when it does not exist. An upgraded container would start against a new, empty
`mino` database next to the owner's real one, run every migration into it and come up "working"
with no channels. The data would not be lost, but it would look lost, and the first write would
fork the history. **Kept.** The sample compose files keep `POSTGRES_DB=dispatcharr` too
(`docker/docker-compose.yml:58,178,254,306`), and so do CI's `POSTGRES_DB: dispatcharr`
(`backend-tests.yml:147,190`) and the backup's `pg_dump -d` default
(`apps/backups/services.py:70`).

### C-17 Local checkout path — owner action (H-9)

Claude Code keys project memory on the checkout path (`~/.claude/projects/-Users-dion-git-Dispatcharr/`).
Worktrees record absolute gitdir paths, and the shared test container's bind mount is a host path.
Six living files hard-code `/Users/dion/git/Dispatcharr`:
`.claude/skills/{implement-review-escalate,plan-review-fix,pr-merge-gate,worktree-per-change}/evals/evals.json`
and `.claude/skills/{pr-merge-gate,worktree-per-change}/references/project.md`. Moving the
checkout is optional, and it is the owner's step after the programme, when no worktree is live
(H-9). The six files are updated in the same sitting.

### C-18 User-Agent strings — rename (U1)

The default User-Agent becomes `Mino/<version>` instead of `Dispatcharr/<version>`
(`core/utils.py:25-28`). It is the fallback when no User-Agent row is configured
(`core/models.py:468-471`), and it is what Schedules Direct sees (`apps/epg/sd_api.py:135`,
`sd_utils.py:652`). The comment at `apps/epg/sd_tasks.py:599-601` records that SD's API asks the
client to identify itself. Continuing to claim "Dispatcharr" would misidentify this server. See Q2
for whether the owner tells SD.

The DVR's User-Agent becomes `Mino-DVR/recording-<id>` instead of `Dispatcharr-DVR/…`
(`core/utils.py:31-33`). It is matched by substring at `apps/channels/api_views.py:3252` and
`:3821`, and producer and matchers change in one commit (R-4). A recording that is running across
an upgrade has its ffmpeg killed by the restart anyway, so no live client carries the old string
into the new matcher.

The helper names `dispatcharr_user_agent`, `dispatcharr_dvr_user_agent` and
`dispatcharr_http_headers`, and the local `DISPATCHARR_HEADERS` (`core/tasks.py:818`), are
**kept**. They are internal Python identifiers that no user, operator or client sees (C-21), and
renaming them would spread U1's diff into every caller for a reason unrelated to the wire change
U1 is reviewed for. U1 changes only the two returned strings and the two matchers.

### C-19 Browser storage keys — keep

The keys are `dispatcharr_sidebar_open` (`frontend/src/App.jsx:43`), `dispatcharr_remembered_username`
and `dispatcharr_saved_password` (`frontend/src/components/forms/LoginForm.jsx:67-127`), and
`dispatcharr-player-prefs` (`frontend/src/utils/components/FloatingVideoUtils.js:1`). They are
invisible to users, and renaming them resets every browser's preferences. A read-old-write-new
migration is new code for no reader. Kept. That `dispatcharr_saved_password` stores a password in
`localStorage` is a separate concern and out of this charter.

### C-20 Backup archives — rename, read both forever (P1)

New archives are named `mino-backup-<ts>.zip`, with metadata `"format": "mino-backup"`
(`apps/backups/services.py:246,271`). `list_backups()` globs **both** `mino-backup-*.zip` and
`dispatcharr-backup-*.zip` (`services.py:343`), so the owner's existing archives stay listed,
downloadable, deletable and restorable.

The restore path never checks the `format` string (`services.py:285-334`), so it needs no change.
Reading both prefixes is not a short-lived shim. Old backups are the owner's records, and they stay
restorable indefinitely. The temp-dir prefixes (`services.py:251,293`) are internal and change with
the rest.

### C-21 Other lowercase identifiers — per row

| Identifier | Anchor | Decision |
|---|---|---|
| AIO service key and `container_name: dispatcharr`, modular `container_name: dispatcharr_{web,relay,celery,db,redis}` | `docker/docker-compose.aio.yml:2,14`, `docker/docker-compose.yml:11,147,215,301,322` | Rename to `mino` / `mino_*` (D2). These are samples. The owner's compose is their own (H-6). |
| Volume key `dispatcharr_data` | `docker/docker-compose.aio.yml:18,65` | **Keep**, with a comment. Changing a volume key in a compose file creates a new, empty volume. |
| `pyproject.toml:2` `name = "dispatcharr"`, `uv.lock:606` | | Keep (internal, and it would churn the lockfile). `description` (`pyproject.toml:3`) is prose, and is renamed in C1. `uv.lock` does not record it. |
| `e2e/package.json:2`, `e2e-upstream/package.json:2` names | | Keep (internal, lockfile churn). |
| `Celery("dispatcharr")` (`dispatcharr/celery.py:37`), `celery -A dispatcharr` | | Keep (C-10). |
| Redis cache keys `dispatcharr:ip_lookup_*` (`core/api_views.py:218,220`) | | Keep (internal, transient). |
| pg `application_name` `Dispatcharr-<role>-<pid>` (`dispatcharr/db/process_label.py:54`) | | Rename to `Mino-…` (C1). Operators see it in `pg_stat_activity`. |
| `/tmp/dispatcharr_log_level` (`dispatcharr/celery.py:21`) | | Keep (internal path). |
| `_dispatcharr_plugin_<key>` module prefix (`apps/plugins/loader.py:633`), `_dispatcharr_pool_created_at` | | Keep (internal symbols). |
| `dispatcharr_stream_id` descriptor field (`apps/timeshift/views.py:660,2248,2960`) | | Keep. It is stored in Redis session descriptors, and an in-flight catch-up session must still read it across an upgrade. |
| HDHomeRun `DeviceID` `dispatcharr-hdhr-<slug>` (`apps/hdhr/api_views.py:74`) and stored `HDHRDevice.device_id` | | **Keep.** Plex keys a tuner on its DeviceID, so a new id means a new tuner and a lost DVR setup in Plex. The *friendly name* is renamed (P1, C1). |
| Helpers `dispatcharr_user_agent`, `dispatcharr_dvr_user_agent`, `dispatcharr_http_headers` (`core/utils.py:25,31,36`) and local `DISPATCHARR_HEADERS` (`core/tasks.py:818`) | | Keep (internal symbols; C-18). Only their returned strings change, in U1. |
| Migration contents and index names `dispatcharr_stream_id_idx` and `dispatcharr_stream_chno_idx` (created at `apps/channels/migrations/0033_stream_id_stream_chno.py:199,203`, and both removed by `0034_remove_stream_dispatcharr_stream_id_idx_and_more.py:15,19`, so neither exists in a fully migrated database) | | Keep. Migration files are history. Editing them would make them no longer describe the database the owner's instance migrated through, and neither index is live state that a rename could reach. |

### C-22 Prose — rename (C1 for code, C2 for docs)

"Dispatcharr", where it names *this* product, becomes "Mino". Where it names *upstream* (the
project this was derived from), it stays, reworded to "upstream Dispatcharr" if it is ambiguous.
The implementer decides each line by that test, and the ratchet's allowlist diff makes every kept
line visible to the reviewer.

## PR sequence

All of these are sequential, under the Main ruleset's strict up-to-date policy. A PR touching the
env, wire or persistent tiers runs on a `migration/**` branch, so that every Playwright project
runs, including **`lifecycle-upgrade`**. That project is the in-place-upgrade test (M2): it starts
an ancestor commit's published image on a fresh volume, seeds durable state, swaps in the PR's
image on the same volume and asserts the data survived (`e2e/tests/lifecycle/upgrade-migrations.spec.ts:1-20`).

| PR | Tier | One line | Branch |
|---|---|---|---|
| **R0** | docs | This spec, ADR 0010, CLAUDE.md's repository paragraph | `docs/mino-rename-spec` |
| **R1** | tooling | `scripts/check_product_name.py` ratchet with a per-file allowlist, in `lint.yml` | `chore/mino-name-ratchet` |
| **C1** | cosmetic | UI and client-visible strings, operator-visible log and prose strings in code | `chore/mino-ui-strings` |
| **C2** | docs | Living docs' prose, `CONTEXT.md` Mino and Internal names entries, attribution | `docs/mino-living-docs` |
| **D1** | distribution | Make CI independent of the repository name (pre-rename) | `ci/mino-name-agnostic` |
| — | **owner** | **Rename the repository; publish `mino:base` and `mino:latest`** (§ The repository rename) | — |
| **D2** | distribution | Move every hard-coded repo, image, Pages and signer reference to Mino | `ci/mino-identity` |
| **G1** | distribution | Go module path `github.com/D10Scot/mino/relay` | `chore/mino-go-module` |
| **U1** | wire (outbound) | User-Agent `Mino/<v>` and `Mino-DVR/…` with matchers | `migration/mino-user-agent` |
| **E1** | env | `MINO_*` everywhere, with the prefix alias at five choke points | `migration/mino-env-alias` |
| **W1** | wire (internal) | `X-Mino-*` headers and `/_mino/` routes, atomically | `migration/mino-wire` |
| **P1** | persistent | Row defaults with a data migration; `mino-backup-*` archives, reading both | `migration/mino-persistent` |
| — | **owner** | **Rename compose variables; confirm no legacy WARNING** (H-7) | — |
| **E2** | env | Alias becomes refusal; `e2e_up.sh` moves to `MINO_*` | `migration/mino-env-refuse` |

Every PR after R1 lowers counts in R1's allowlist and commits the regenerated allowlist. A PR whose
allowlist diff *raises* a count says why in its description. W1, for example, adds tests and blank
lines that name the old header in order to prove it is ignored.

**What a PR changes is decided by a command, not by the file lists in this spec.** For each PR the
authoritative change list is `git grep -n -i dispatcharr <PR base> -- <the PR's globs>` over
living files (R-1), minus the identifiers § Categories keeps. The files this spec names in a PR
section are the ones with a *decision* attached (a link to repoint, a filename to change, a string
the Mino app might read). They are not the full list. Each PR body lists every file it touched,
with that file's ratchet count before and after (from `scripts/check_product_name.py`).

Every PR also corrects the CLAUDE.md facts it changes, in the same PR, and no others. Each PR's
"Hooks and gates" line lists what its paths trip, from CLAUDE.md § Test hooks. **No PR renames a
tracked file path (R-3)**, so no literal-path arm loses its subject. The reviewer confirms this with
`git diff --name-status -M <base>...<head> | grep '^R'`, which must print nothing.

### R0 — this spec

**Changes:**

- `docs/superpowers/specs/2026-10-28-mino-rename-design.md` (this file)
- `docs/adr/0010-the-product-is-renamed-mino-and-upstream-is-no-longer-tracked.md`
- `CLAUDE.md` § Repository and direction, first paragraph, and the one-sentence `CONTRIBUTING.md`
  pointer at the end of § Conventions (`CLAUDE.md:197` at `632f1d3d`: "See `CONTRIBUTING.md` for
  the upstream PR process and fuller style guide"). The upstream PR process is what M1 retires, so
  the sentence now points at the style guide only and says the process no longer applies. It is
  folded into R0 so that it is not the one CLAUDE.md sentence no PR owns; `CONTRIBUTING.md` itself
  is reworded in C2.

The CLAUDE.md change states that there is no `upstream` remote and that none is to be added.
`git remote -v` in the root checkout prints `origin` only, and `gh repo view D10Scot/Dispatcharr
--json isFork` prints `false`, both read on 2026-10-28. It also states that ideas from upstream are
reimplemented, never merged (M1), and points at ADR 0010.

**Verification:** docs only, so the `changes` detectors skip the heavy jobs. Run
`gh pr view <n> --json closingIssuesReferences` and expect `0`.

### R1 — the name ratchet

**Changes:**

- New `scripts/check_product_name.py` (stdlib only):
  - `git ls-files -z`
  - skip the R-1 record globs, which are a literal list at the top of the script
  - skip binary files
  - count case-insensitive `dispatcharr` per file
  - compare against `scripts/product_name_allowlist.txt` (`<count>\t<path>` lines)
  - fail when any file exceeds its entry, or has a hit and no entry
  - print the files whose count fell, with a reminder to run `--write`
  - `--write` rewrites the allowlist from the tree
- New `scripts/product_name_allowlist.txt`, generated at the PR's base.
- `lint.yml`: one step running the check.
- `tests/test_check_product_name.py` (label `tests`). It covers a record path ignored, a binary
  ignored, an increase failing, an unlisted file failing, a decrease passing, and `--write`
  round-tripping.

**Break-checks:**

- Delete `docs/adr/**` from the record list. The check fails, naming an ADR path.
- Make the count case-sensitive. The test "uppercase and lowercase both counted" reddens, naming
  the counted string.

**Hooks and gates:** `*.py` (credential-logging check); `tests/test_*.py` (the whole `tests`
package); `.github/workflows/lint.yml` (zizmor, blocking on every finding). CI runs lint, actionlint
and Backend result (label `tests`).

**PR description draft:**

> Adds a ratchet on the old product name, the first implementation step of the Mino rename
> (spec `docs/superpowers/specs/2026-10-28-mino-rename-design.md`, PR R1).
> `scripts/check_product_name.py` counts "dispatcharr" per tracked file, skipping the decision
> records the spec's rule R-1 names and binary files, and fails CI when any file's count rises
> above `scripts/product_name_allowlist.txt`. Later PRs in the rename lower the counts; what
> remains at the end is the list of names the spec keeps on purpose.
> Tests: `tests/test_check_product_name.py`. Break-checks: dropping `docs/adr/**` from the record
> list fails on an ADR path; a case-sensitive count fails the mixed-case test.

### C1 — UI and client-visible strings

**Changes:** prose and strings in code. No identifier the spec keeps, no env var name, no URL into
the repository (that is D2), no persisted default (that is P1).

**The authoritative list** is `git grep -n Dispatcharr <base> -- apps core dispatcharr relay
docker frontend dashboard scripts pyproject.toml .gitleaks.toml .github/ISSUE_TEMPLATE
':!**/migrations/**'`, minus the kept identifiers (C-15, C-19, C-21), minus URLs (D2). At
`632f1d3d` that is 19 non-test frontend files and 28 non-test, non-migration Python files under `apps`, `core` and `dispatcharr` (`git grep -l Dispatcharr 632f1d3d -- 'apps/*.py' 'core/*.py' 'dispatcharr/*.py' ':!**/tests/**' ':!**/migrations/**' | wc -l`).
Among them are files this section does not name: `ConnectionSecurityPanel.jsx:64,82,123,141`
(with `ConnectionSecurityPanel.test.jsx`), `ChannelsTable.jsx:1339,1351,1475`, `constants.js:29`,
and the API schema help text at `apps/timeshift/api_views.py:33,84`. The files named below are the ones with a
decision attached.

- **Frontend:**
  - `frontend/index.html:27` `<title>`
  - `Sidebar.jsx:366-369` (alt and label)
  - `AboutModal.jsx` (title, text, and links per C-3, with the attribution line)
  - `PluginWarnings.jsx:41-51`
  - plugin-compatibility text in `AvailablePluginCard.jsx` and `PluginDetailPanel.jsx` (text only;
    the keys stay, C-15)
  - `SuperuserForm.jsx:44,147,153`
- **API and clients:**
  - `dispatcharr/settings.py:349-350` (`SPECTACULAR_SETTINGS` title and description)
  - `apps/output/epg.py:1145` `generator-info-name="Mino"`
  - the EPG download filename `Mino.xml` (`apps/output/epg.py:1756`, `apps/output/views.py:100`)
  - XC `user_info.message` `"Mino XC API"` (`apps/output/views.py:468`)
  - the HDHomeRun computed friendly name (`apps/hdhr/api_views.py:75,226`)
  - the update notification text (`core/models.py:943`)
- **Operator-visible:**
  - pg `application_name` (`dispatcharr/db/process_label.py:54`, and `tests/test_process_label.py`
    if it asserts the prefix)
  - log and error message prose naming the product (Python, Go, shell)
  - `pyproject.toml:3` description
  - `.gitleaks.toml:1` title
  - the metrics dashboard's page titles and headings, "Dispatcharr fork metrics"
    (`dashboard/index.html:7,13`, and the same two lines in `dashboard/{compare,defects,explore,story}.html`).
    These trip the dashboard vitest hook.
  - the issue templates' text (`.github/ISSUE_TEMPLATE/*.yml`; the field `id: dispatcharr-version`
    stays, because it is an internal key)
- **Comments and docstrings** that name this product, per C-22.
- **One e2e pin, the oracle for the two strings every user sees first.** At `632f1d3d` nothing in
  `e2e/tests/frontend/` asserts a product string: its only "Dispatcharr" hits are a User-Agent the
  test itself types and reads back (`settings.spec.ts:122,140`), a fixture plugin's description
  (`plugin-zip.ts:135,171`), a backup filename regex (`backups.spec.ts:162`, P1's) and issue links.
  So C1 adds one `@contract` test to the existing `e2e/tests/frontend/render.spec.ts`, after the
  nine surface loops: `gotoSurface(adminPage, SURFACES[0])`, then
  `await expect(adminPage).toHaveTitle('Mino')` (`frontend/index.html:27`) and
  `await expect(adminPage.getByRole('img', { name: 'Mino' })).toBeVisible()` (the sidebar logo's
  `alt`, `Sidebar.jsx:366`), plus the sidebar brand text (`Sidebar.jsx:369`, via
  `getByText('Mino', { exact: true })`). `helpers.ts:17-19` says the project never selects by text
  because text couples a test to UI copy; this pin couples to copy on purpose, because the copy is
  its subject, and the test's comment says so.

The XC message string: the Mino app's only use of it is a fixture in its stub server
(`D10Scot/mino-apple:MinoKit/Sources/MinoStubServer/StubScenario.swift:272`). A code search of
`mino-apple` for "dispatcharr" on 2026-10-28 found no reader that parses it.

**Tests that change** (the test-modification rule: each one listed with before and after in the PR
body). Any test asserting one of the renamed strings changes, and only its expected string changes.
The implementer greps `-rn 'Dispatcharr'` across `*/tests/`, `frontend/src/**/__tests__` and
`e2e/` for the exact strings changed, and lists every hit. Measured at `632f1d3d` as the starting
list, not the full one:

- vitest files whose expectations name the product (`git grep -l Dispatcharr 632f1d3d --
  'frontend/src/**/*.test.js' 'frontend/src/**/*.test.jsx'`): `Sidebar.test.jsx:195,204,211`
  (`getByText('Dispatcharr')`), `AboutModal.test.jsx`, `PluginWarnings.test.jsx`,
  `SuperuserForm.test.jsx`, `ConnectionSecurityPanel.test.jsx`, `Login.test.jsx` and
  `RecordingCardUtils.test.js` (the last only if its string is one C1 changes).
- `apps/output/tests/test_hdhr_device_xml.py:64`, which asserts the *computed* fallback
  `<FriendlyName>Dispatcharr HDHomeRun</FriendlyName>` when no `HDHRDevice` row exists
  (`apps/hdhr/api_views.py:226`, C1's), not the model default (P1's).
- `apps/output/tests/test_views.py:37` is a helper that mirrors the download filename, not an
  assertion; it changes with `apps/output/views.py:100` for consistency.

**Break-checks:**

- No test at `632f1d3d` asserts `generator-info-name` (`git grep generator-info 632f1d3d --
  apps/output/tests` is empty), so C1 adds one in `apps/output/tests/test_views.py` that renders the
  XMLTV header and asserts `generator-info-name="Mino"`. Revert `apps/output/epg.py:1145` alone,
  and it reddens naming the attribute.
- Revert `frontend/index.html:27` alone. The `render.spec.ts` pin reddens on `toHaveTitle`, with
  Playwright's message quoting the title it found.

**Hooks and gates:** `*.py` (credential-logging check); `frontend/**/*.test.jsx` (vitest);
`frontend/**/*.jsx` (eslint, advisory); `*/models.py`: none (C1 changes no model);
`.github/ISSUE_TEMPLATE` (not workflows, so no zizmor); `e2e/**/*.ts` (`tsc --noEmit`). **Backend
labels, measured** with `python3 -I scripts/ci_backend_test_labels.py` at `632f1d3d`: C1's app
files alone give `["apps.channels.tests", "apps.output.tests", "apps.timeshift.tests",
"core.tests"]`, but C1 also edits `dispatcharr/settings.py:349-350`,
`dispatcharr/db/process_label.py:54` and `pyproject.toml:3`, each a `_SHARED_PATH_PREFIXES` entry
(`dispatcharr/test_discovery.py:11`), so the real set is the **full fifteen labels**. CI runs
Backend result (full), Frontend result, E2E result (the `frontend` project runs because C1 touches
`frontend/**`, which `e2e-tests.yml:13,110`'s change filter names; the new `render.spec.ts` pin is
the only E2E oracle for a missed product string, and the ratchet's allowlist diff is the other),
Go result if any Go log prose changed, and lint plus the ratchet.

**PR description draft:**

> Renames the product to Mino in everything a user or operator reads: the page title, sidebar and
> About dialog (with an attribution line to upstream Dispatcharr, AGPL-3.0), the API schema title,
> XMLTV `generator-info-name`, the EPG download filename, the Xtream `user_info.message`, the
> HDHomeRun friendly name, the Postgres `application_name`, and log and error prose.
> Spec PR C1 (`docs/superpowers/specs/2026-10-28-mino-rename-design.md`). Identifiers the spec
> keeps (plugin manifest keys, HDHomeRun DeviceID, browser storage keys) are untouched.
> Tests changed (expected strings only): <list, before → after>.

### C2 — living docs

**Changes:**

- Product prose in `README.md`, `CONTRIBUTING.md`, `SECURITY.md` (subject only; the image and repo
  identity wait for D2), `Plugins.md`, `Plugin_repo.md` (prose; keys stay), `docs/agents/*.md`,
  `e2e/README.md`, `e2e/COVERAGE.md` (prose only), `docs/supply-chain.md` (prose; the commands wait
  for D2) and the skills' `references/project.md` headings.
- Upstream links per C-3, and `FUNDING.yml` per Q5.
- **`CONTEXT.md`:** the "Mino" entry is rewritten. Mino is the product's name, and the paragraph
  saying "until that rename happens" goes. A new **"Internal names"** entry lists every identifier
  § Categories keeps, with its one-line reason and a pointer to this spec, so that no one
  "finishes" the rename by changing one.

**Verification:** docs only; the ratchet; `python -m metrics.build --validate-only` if
`metrics/curated/` changes.

**PR description draft:**

> Renames the product to Mino across the living documentation (README, CONTRIBUTING, SECURITY,
> Plugins, agent docs, E2E docs) and rewrites `CONTEXT.md`'s Mino entry; adds an "Internal names"
> entry listing what the rename keeps and why. Decision records (ADRs, specs, plans, analyses,
> CHANGELOG) are unchanged by design (ADR 0010). Spec PR C2.

### D1 — CI independent of the repository name (merges *before* the rename)

**Changes:**

- `e2e-tests.yml:163-164` and `lifecycle-tests.yml:189-190` pass
  `--build-arg REPO_NAME="$(basename "$GITHUB_REPOSITORY" | tr '[:upper:]' '[:lower:]')"` beside
  `REPO_OWNER`. They build on `<owner>/<this repo>:base` both before and after the rename.
- `docker/tests/test-puid-pgid.sh:2042` does the same from `GITHUB_REPOSITORY` when it is set, and
  falls back to the current default otherwise.
- `lifecycle-tests.yml:429`'s `IMAGE_REPO` becomes a list. The baseline search walks back up to
  50 ancestors, as now, and at each SHA tries `ghcr.io/<owner>/<repo>:<sha>` and then the legacy
  `ghcr.io/d10scot/dispatcharr:<sha>`. After the rename the first ancestors with an image exist
  only under the legacy name. Without this fallback the upgrade job fails closed on every PR until
  a `mino:<sha>` exists, and with it the first post-rename PRs upgrade from the real old image,
  which is exactly the owner's path.
- `e2e/tests/lifecycle/upgrade-migrations.spec.ts:34`'s local-only `FALLBACK_BASELINE` is left.
  It is refused in CI anyway (`:56-67`).

**Break-check:** the real registry before the rename already has only `dispatcharr:base`, so no
mock is needed.

```bash
docker build --build-arg REPO_OWNER=d10scot --build-arg REPO_NAME=mino -f docker/Dockerfile .
```

This fails, with `ghcr.io/d10scot/mino:base` not found. That shows the argument is honoured. The
same command with `REPO_NAME=dispatcharr` proceeds past the `FROM`.

**Hooks and gates:** `.github/workflows/*.yml` (zizmor, blocking); `docker/tests/*.sh` (no hook).
CI runs actions-lint, lint, E2E result and Lifecycle result. The branch is `ci/mino-name-agnostic`,
**not** `migration/**`: the legacy-name fallback cannot fire before the rename, because the only
registry name that exists is the legacy one, and the upgrade job already runs on
`lifecycle-tests.yml`'s own path filter, which the workflow edit trips.

**PR description draft:**

> Makes CI derive the base image and the upgrade baseline from the repository's own name, so the
> repository rename to `D10Scot/mino` (spec § The repository rename) does not leave the E2E and
> lifecycle images silently building on the frozen `ghcr.io/d10scot/dispatcharr:base`, which they
> would today because `docker/Dockerfile:3` defaults `REPO_NAME=dispatcharr` and both workflows
> pass only `REPO_OWNER`. The upgrade baseline search also tries the legacy image name, so the
> first PRs after the rename upgrade from the real pre-rename images. Spec PR D1.

### The repository rename (owner, between D1 and D2)

§ The repository rename below holds the procedure, what breaks and what redirects.

### D2 — hard-coded identity

**Changes (living files only):**

- **Compose:** `docker/docker-compose.{aio,dev,debug}.yml` and `docker/docker-compose.yml` `image:`
  move to `ghcr.io/d10scot/mino:{latest,base}`, with service and container names per C-21. The
  volume key stays.
- **Dockerfile:** `docker/Dockerfile:2-3` defaults become `REPO_OWNER=d10scot`, `REPO_NAME=mino`.
- **Workflows:**
  - `metrics.yml:137` job container becomes `ghcr.io/d10scot/mino:base`
  - OCI documentation annotations (C-3)
  - OCI `build_version` labels and annotations: `Dispatcharr version:` → `Mino version:` at
    `ci.yml:201,280` and `release.yml:319,387`, and `DispatcharrBase version:` →
    `Mino base version:` at `base-image.yml:141,212,230`. The `docker/DispatcharrBase` *file* name
    stays (C-14).
  - `lifecycle-tests.yml`'s fallback list keeps the legacy name (it costs one probe per SHA)
- **Hook:** `.claude/hooks/start-test-container.sh:19` default image becomes
  `ghcr.io/d10scot/mino:latest`.
- **Supply chain:** `docs/supply-chain.md` and `SECURITY.md`:
  - registry `ghcr.io/d10scot/mino`
  - `cosign verify` identity regex `^https://github\.com/D10Scot/mino/\.github/workflows/<workflow>\.yml@refs/.*$`
  - a second, labelled command for images published before the rename, which carry
    `D10Scot/Dispatcharr` in their certificate identity, permanently
  - `gh attestation verify … --owner D10Scot` is unchanged
- **Metrics and dashboard:**
  - `metrics/build/__main__.py:31` `REPO_SLUG`
  - `scripts/metrics/_gh.py:112-113` and `scripts/metrics/collect_events.py:347` defaults
  - `scripts/metrics/README.md:43`
  - `dashboard/pages/defects.js:7`, `dashboard/pages/story.js:6`
  - dashboard tests' expected hrefs (`dashboard/tests/{defects,story}.test.js`, the expected string
    only)
- **Repo name and links:**
  - `--repo D10Scot/mino` in `docs/agents/issue-tracker.md`, `CLAUDE.md`, the skills'
    `references/project.md` and the gh-aw `.md` prompts (if any name the repo)
  - the Pages URL `https://d10scot.github.io/mino/` in `CLAUDE.md` and `docs/agents/metrics.md`
  - `github.com/D10Scot/Dispatcharr/` → `github.com/D10Scot/mino/` in living files' issue and PR
    links (mechanical; the redirect makes both work, but the new name removes the dependency on it)
  - records keep theirs (R-1)
- **Other:**
  - `core/tasks.py`: the stable check repointed with its 404 logged at INFO, and the dev-build
    branch disabled, with its tests and break-checks (C-3, C-3a). Both branches call
    `requests.get` (`core/tasks.py:824,926`) and `__timestamp__` is imported inside the task
    (`:812`), so `patch("version.__timestamp__", …)` and `patch("core.tasks.requests.get")` are the
    two seams the tests need. Labels, measured for `core/tasks.py`, `apps/output/epg.py` and the new
    `core/tests/` module: `["apps.output.tests", "core.tests"]`.
  - `apps/output/epg.py:1146`; `debian_install.sh:228` (C-3)
  - `README.md:97-102` run commands → `ghcr.io/d10scot/mino:latest`, keeping
    `-v dispatcharr_data:/data` (the volume name stays)
  - `relay/internal/relaytest/testdata/ffmpeg_stderr/CAPTURE.md`: issue links only. It is a dated
    capture note, and the spec treats it as living only for its links.

**Not changed:** anything under the record globs.

**Verification after merge (owner, H-5):**

- `docker pull ghcr.io/d10scot/mino:latest`, then run the `cosign verify` command from the updated
  `docs/supply-chain.md` against it. Expect `Verification for … -- The following checks were
  performed`, with the `D10Scot/mino` identity.
- Run the legacy command against `ghcr.io/d10scot/dispatcharr:latest`. Expect it to verify against
  `D10Scot/Dispatcharr`.

**Hooks and gates:** zizmor on every touched workflow; `dashboard/*.js` and `dashboard/tests`
(dashboard vitest); `metrics/**` and `scripts/metrics/**` (metrics tests plus `--validate-only`);
`*.py` (credential-logging check); `.claude/hooks/*.sh` (`lint.yml` runs
`.claude/hooks/tests/test_hooks.sh`). CI runs all aggregates, `docker-build.yml` (the Dockerfile
path) and hadolint.

**PR description draft:**

> Moves every hard-coded reference to the repository, image, Pages site and signing identity to
> `D10Scot/mino` / `ghcr.io/d10scot/mino`, now that the repository has been renamed. Verification
> docs keep a second command for images signed before the rename, whose certificate identity
> permanently names `D10Scot/Dispatcharr`. Compose volume names are unchanged so an upgrade keeps
> its data. The update check stops consulting upstream: the stable check asks `D10Scot/mino`'s
> releases (a 404 until the first release, logged at INFO), and the dev-build check, which polled
> upstream's Docker Hub, is disabled because GHCR offers no equivalent anonymous signal. Decision
> records are unchanged by design. Spec PR D2.

### G1 — Go module path

**Changes:**

- `cd relay && go mod edit -module github.com/D10Scot/mino/relay`, then a mechanical rewrite of
  every import (`gofmt -l` must be empty afterwards).
- The five sites in C-1: `check_go_stdlib_only.sh:19`, `coverage_relay_go.sh:102`, the credlint
  sanitizer key (`check.go:69`) and its pin (`check_test.go:105`, listed under the
  test-modification rule), and the floor's shape fields via `scripts/coverage_relay_go.sh --write-floor
  --shape-only`. That rewrites `packages=`, `gomod=` and `scripts/coverage_relay_go.floor.packages`
  and never touches `missing` (`scripts/coverage_relay_go.sh:355`).
- Living docs that print the module path.

`missing` must not move: the rename changes no statement. CI's coverage job is the check, and a
change in `missing` is a finding, not something to re-baseline.

**Break-checks:**

- Revert only `check.go:69`. `go run ./internal/credlint ./...` reports findings at
  `redact.Error` call sites, naming `redact.Error`, **and** `TestTheRedactorIsExactlyRedactError`
  (`check_test.go:105`) reddens, naming the sanitizer key.
- Revert only `coverage_relay_go.sh:102`. The script stops **before** it measures anything: the
  `grep` matches no line of the renamed `go list -deps .` output, and under `set -uo pipefail`
  (`:56`) the pipeline's `|| die` fires with `could not list the binary's dependencies.`
  (`:101-104`). It never reaches the `packages=` comparison (`:265-267`), so "a `packages=`
  mismatch" is not the message; that would be the message of a *partial* edit of the grep that still
  matched some packages.

**Hooks and gates:** `*.go` (`run-go-checks.sh`: build, vet, `-race`, credlint and golangci-lint
under three GOOS); the commit gate's Go section. CI runs Go result (build, vet, race, lint,
stdlib-only, credlint, coverage gate) and CodeQL `go`. No backend labels: `relay/` maps to none
(CLAUDE.md § Test hooks).

**PR description draft:**

> Renames the Go module from `github.com/D10Scot/Dispatcharr/relay` to
> `github.com/D10Scot/mino/relay`. Mechanical import rewrite plus the five places that key on the
> path: the stdlib-only check, the coverage script's package filter, credlint's `redact.Error`
> sanitizer key and the test that pins it (`check_test.go:105`, expected string only), and the
> coverage floor's shape fields (`--write-floor --shape-only`; `missing`
> unchanged). Spec PR G1.

### U1 — outbound User-Agent

**Changes:** C-18, producer and matchers in one commit. The helper function names stay (C-18,
C-21). U1 touches `core/utils.py`'s two return strings (`:28,:33`), the two matchers
(`apps/channels/api_views.py:3252`, in `_stop_dvr_clients`, and `:3821`, in
`RecordingViewSet.destroy`'s background thread), the tests below, and nothing else.

**Tests that change** (the test-modification rule: expected strings only, each listed before →
after in the PR body). Every one of them feeds the matcher a **literal** string, so none of them
observes the producer; that is why the coupling test below is new rather than one of these:

- `core/tests/test_core.py:259-292` (`DispatcharrUserAgentTests`: `'Dispatcharr/1.2.3'` →
  `'Mino/1.2.3'` at `:263,:274,:284,:292`; `'Dispatcharr-DVR/recording-42'` →
  `'Mino-DVR/recording-42'` at `:267`) and `:358,:375,:378` (`"Dispatcharr/9.9.9"`,
  `"Dispatcharr/1.2.3"`, the `CoreSettings.get_default_user_agent()` fallback).
- `apps/channels/tests/test_dvr_client_teardown.py:24,38-39` (payload literals
  `"Dispatcharr-DVR/recording-7"`, `-8`).
- `apps/channels/tests/test_recording_stop_cancel.py:307-344` (payload literals
  `"Dispatcharr-DVR/recording-42"`, `-99`, `-1`).

**New test, the producer/matcher coupling.** In `apps/channels/tests/test_dvr_client_teardown.py`,
in the file's own style (`_channel()` payload, `relay_client.get_channel` and `stop_client`
patched): `test_the_matcher_recognises_what_the_producer_sends` builds the payload from the
producer, `{"client_id": "c1", "user_agent": dispatcharr_dvr_user_agent(7)}` beside a
`"VLC/3.0"` client, calls `api_views._stop_dvr_clients("abc", recording_id=7)`, and asserts the
count is 1 and `stop_client` was called once with `("abc", "c1")`, with `msg=` naming the
mechanism ("the DVR matcher does not recognise the User-Agent the DVR producer sends"). The
`destroy` matcher at `:3821` is the same substring test in a background thread; U1 changes it in
the same hunk, and the reviewer reads both sites, since no test drives `destroy` with a DVR
payload at `632f1d3d`.

**Break-checks**, each on the final tree:

- Revert only the **matcher** (`api_views.py:3252` back to `"Dispatcharr-DVR"`). The coupling test
  reddens (`0 != 1`, with the `msg=` above), because the producer still sends `Mino-DVR/…`. The
  literal-payload tests stay green, which is the point: they cannot see this edit.
- Revert only the **producer** (`core/utils.py:33` back to `Dispatcharr-DVR/…`). The coupling
  test reddens the same way, and `test_core.py:267`'s `test_dispatcharr_dvr_user_agent` reddens
  with the string inequality. Either half reverted alone is caught by the coupling test; the
  literal tests catch neither.

**Hooks and gates:** `*.py` (credential-logging check); `tests/test_*.py`. The labels measured by
`scripts/ci_backend_test_labels.py` for `core/utils.py`, `apps/channels/api_views.py` and the
three test files are `apps.channels.tests` and `core.tests`. On a `migration/**` branch the full E2E
runs, including `e2e/tests/dvr/*`, whose recording teardown depends on the DVR matcher.

**PR description draft:**

> The default outbound User-Agent becomes `Mino/<version>` and the DVR's becomes
> `Mino-DVR/recording-<id>`, with the two DVR-client matchers in `apps/channels/api_views.py`
> changed in the same commit. Schedules Direct, and any provider without a configured User-Agent,
> now sees Mino. Spec PR U1. Tests changed (expected strings only): <list>.

### E1 — env vars with the alias

**Changes:** C-7/C-8 as written. Every reader, writer and mention in living files moves to
`MINO_*`, including:

- the five choke points;
- `docker/env-alias.sh` (new);
- the `variables=(…)` list;
- supervisord and uWSGI interpolations;
- CI env blocks (`backend-tests.yml:145-193`) and the gh-aw `.md` prompts (`DISPATCHARR_LOG_LEVEL`),
  recompiled with a bare `gh aw compile`;
- hooks' `-e DISPATCHARR_LOG_LEVEL` (`.claude/hooks/pre-commit-tests.sh:163`,
  `run-affected-tests.sh:121`);
- the sample compose files;
- `CLAUDE.md` (every env var mention).

`scripts/e2e_up.sh:373-375` keeps the old names (C-8).

**Where the alias bodies live.** Each choke point is a one-line call into a body that has a test
of its own, so the uncovered part of each is the call line and nothing else:

- Python: `dispatcharr/env_alias.py`, a leaf module importing `os` and `logging` only, exposing
  `alias_legacy_env(environ=os.environ)`. `dispatcharr/__init__.py:7` is `from .celery import
  app as celery_app` and the call goes **above** it, because `dispatcharr/celery.py:15` reads the
  level at import. The WARNING goes through `logging` before Django has configured logging, so it
  reaches stderr through Python's last-resort handler, which prints WARNING and above.
- Go: `relay/config/envalias.go` in the already-linked, already-tested `relay/config` package,
  `func AliasLegacyEnv(sink func(format string, args ...any))`, which writes one warning per
  variable **through the sink** rather than returning them. `main()` gains exactly one statement,
  `config.AliasLegacyEnv(log.Printf)` before `config.Load()` (`relay/main.go:33`), and nothing
  else: a returned slice would make `main()` loop and log, and a `for` statement plus its body is
  two coverage blocks, not one (measured in round 4 on a scratch package with `go test
  -covermode=atomic -coverprofile`: a single call adds no block and raises the enclosing block's
  count by one). The test passes a collector that appends `fmt.Sprintf(format, args...)` to a
  slice. A new package would move the floor's `packages=` and need R27's re-baseline;
  `relay/config` does not.
- Shell: `docker/env-alias.sh`, POSIX `sh` because `docker/healthcheck.sh` is `#!/bin/sh`.

**New tests, one per alias mechanism, each with a break-check. No case supplies a default value:**
`celery.py:10`'s `DEFAULT_LOG_LEVEL` is `DEBUG`, `relay/config`'s default port is 5658, the role
defaults to `all`, and `devProxy.js:25-28` falls to `'5658'`, so a pin on any of those would pass
with the alias absent.

| Mechanism | Test | Break-check |
|---|---|---|
| Python | `tests/test_env_alias.py` (label `tests`). Each case runs `[sys.executable, "-c", "import dispatcharr, os; print('MINO_LOG_LEVEL=' + str(os.environ.get('MINO_LOG_LEVEL')))"]` with `cwd` at the repository root and an **allowlisted** `env`: `PATH`, `HOME`, `LANG`, `PYTHONPATH` (the repository root) and the case's own variables, never a copy of `os.environ`. The hook and CI set `*_LOG_LEVEL=WARNING` themselves (`pre-commit-tests.sh:163`, `run-affected-tests.sh:121`, `backend-tests.yml:150,193`), and after E1 those lines set `MINO_LOG_LEVEL`, which would make "only the old name set" false and the "`MINO_` wins" case tautological. (a) Only `DISPATCHARR_LOG_LEVEL=warning`: stdout carries `Celery using effective log level: WARNING` (`celery.py:33`) and `MINO_LOG_LEVEL=warning`; stderr carries exactly one WARNING naming `DISPATCHARR_LOG_LEVEL` and `MINO_LOG_LEVEL`. (b) `DISPATCHARR_LOG_LEVEL=warning` and `MINO_LOG_LEVEL=error`: stdout carries `… ERROR` and `MINO_LOG_LEVEL=error`; the WARNING says `MINO_LOG_LEVEL` wins. (c) Neither: `… DEBUG` and no WARNING. `warning` is not the default, and nothing in the tree writes `/tmp/dispatcharr_log_level` (`celery.py:21-22` is its only mention), so the broken chain below ends at the default | Move the call below `from .celery import app`. Case (a) reddens on stdout: `Celery using effective log level: DEBUG` where `WARNING` was expected, which names the mechanism, `celery.py:15` read the level before the alias ran. The `MINO_LOG_LEVEL=warning` line still prints in that state, which is why an assertion on `os.environ` alone could not see this edit |
| Go | `relay/config/envalias_test.go`, in `config_test.go`'s style (`t.Setenv`; the test registers **both** names with `t.Setenv` before the call so the function's own `os.Setenv` is restored at test end). Each case calls `AliasLegacyEnv(collect)`, where `collect` appends `fmt.Sprintf(format, args...)` to a slice. (a) Only `DISPATCHARR_RELAY_GO_PORT=5999`: afterwards `os.Getenv("MINO_RELAY_GO_PORT") == "5999"` and the slice holds exactly one line naming both. (b) `DISPATCHARR_RELAY_GO_PORT=5999` and `MINO_RELAY_GO_PORT=6001`: `6001` survives and the one line says `MINO_` wins. (c) No `DISPATCHARR_` variable: the slice is empty | A wrong edit **inside** `AliasLegacyEnv`: reverse the precedence so the old name overwrites a set new one. Case (b) reddens, `MINO_RELAY_GO_PORT = 5999, want 6001`. The call line in `main()` is pinned by the reviewer reading `relay/main.go`, not by a test: `go test` never runs `main()` (C-8 point 4), and no stand-in re-exec is added to pretend otherwise |
| Shell | `docker/tests/test-env-alias.sh`, run by `lint.yml` beside `.claude/hooks/tests/test_hooks.sh` (`lint.yml:226`); no Docker. Each case sources `docker/env-alias.sh` in a fresh `env -i` shell. (a) Only `DISPATCHARR_ROLE=api`: `MINO_ROLE=api` and one warning naming both. (b) `DISPATCHARR_ROLE=api` and `MINO_ROLE=worker`: `MINO_ROLE=worker`. (c) Nothing old: no output. `api` and `worker` are chosen because the role's default is `all` | Reverse the precedence inside `env-alias.sh`: case (b) reddens, naming `MINO_ROLE=api` |
| Healthcheck | A new case in `docker/tests/test-puid-pgid.sh`, in `test_custom_port`'s shape (`:1618-1655`): run the image with `-e DISPATCHARR_RELAY_GO_PORT=5659` (old name, **non-default**: 5658 is what `healthcheck.sh:33` falls to), `wait_for_ready`, then `docker exec "$name" /bin/sh /app/docker/healthcheck.sh` must exit 0 (the exact `HEALTHCHECK` command, `docker/Dockerfile:117-118`). `wait_for_ready` itself checks `supervisorctl status api-uwsgi` (`:181-193`) and never the healthcheck, so a container that is "ready" says nothing about this script | Drop the `.`-source of `docker/env-alias.sh` from `healthcheck.sh`: it reads an unset `MINO_RELAY_GO_PORT`, probes 5658 where nothing listens, and the `exec` exits non-zero, which the case reports as `healthcheck exited <n> with the legacy port name set` |
| devProxy | `frontend/src/__tests__/devProxy.test.js:92-94` already tables `relayGoPort` with `DISPATCHARR_RELAY_GO_PORT` (`''`, `'abc'`, `'6000'`); those three rows move to `MINO_RELAY_GO_PORT` (listed under the test-modification rule) and gain `{ DISPATCHARR_RELAY_GO_PORT: '6000' } → '6000'` and `{ MINO_RELAY_GO_PORT: '6001', DISPATCHARR_RELAY_GO_PORT: '6000' } → '6001'` | Drop the `?? env.DISPATCHARR_RELAY_GO_PORT` fallback: the old-name row reddens, `'5658'` where `'6000'` was expected |

**Hooks and gates:**

- `*.py` (credential-logging check); `tests/test_*.py`.
- The commit gate: `dispatcharr/` is a `_SHARED_PATH_PREFIXES` entry, so the **full backend set**
  runs.
- `*.go` (Go hook); `.github/workflows/*` (zizmor, `.md` plus `.lock.yml`);
  `frontend/**/*.test.js` (vitest).
- `apps/proxy/internal_base_url.py`, `relay_client.py` and `control_plane.py` are Gate 2 modules
  (`scripts/coverage_live_path.coveragerc`). Run `scripts/coverage_live_path_isolated.sh` and
  `--gate` before pushing. A pure rename moves no statement.
- **The Go coverage ratchet, with a declared raise** (CLAUDE.md § Testing, ruling R21). Package
  `main` is linked and in the floor (`scripts/coverage_relay_go.floor.packages:1`), and nothing
  tests `main()`, so the one statement E1 adds to it, the `config.AliasLegacyEnv(log.Printf)`
  call, is uncovered by construction and `missing` rises by exactly one. **Exactly one because the
  sink shape keeps `main()` to a single call**: round 4 measured on a scratch package that a
  returned slice looped and logged in `main()` costs two blocks (the `for` and its body), which
  `check_floor_raise.sh:50-52` would refuse against `raise_listed=1`. `scripts/check_floor_raise.sh`
  (`go-tests.yml`'s floor step) refuses an undeclared rise, and refuses a declaration whose
  `raise_from` is not the base floor's `missing` (`:42-45`). So E1's `scripts/coverage_relay_go.floor`
  carries `raise_from=<the floor's missing= at E1's base; 705 at 632f1d3d>` and `raise_listed=1`,
  **replacing** the `raise_from=691` / `raise_listed=14` pair 4a-3 left (a stale pair is refused),
  lists `relay/main.go:<line>` in the PR body, and sets `missing` to the worst of the 12-round CI
  census, which must be ≤ `raise_from + 1` and must show ≥ 85% on E1's added statements. The
  alias body being in `relay/config` is what makes the listed total one line: everything else E1
  adds is covered by `envalias_test.go`.
- On the `migration/**` branch: every Playwright project, including `lifecycle-upgrade`, run with
  the old names into the new image. `Lifecycle result`'s `suites` runs `test-puid-pgid.sh`, with
  the healthcheck case above, and TLS Postgres with the image's env.

**PR description draft:**

> Renames every `DISPATCHARR_*` environment variable to `MINO_*` (50 names, Appendix B of the
> spec) and adds a prefix alias at the five places a process can start: the entrypoint and the
> healthcheck (through `docker/env-alias.sh`), `dispatcharr/__init__.py`, the relay's `main()`, and
> `frontend/devProxy.js`. An old name still works and logs one WARNING naming its replacement; if
> both are set, the `MINO_` name wins. The window closes in spec PR E2, which turns the alias into
> a refusal. **Rollback note:** an image older than this PR ignores `MINO_*`; rolling back after
> renaming compose variables needs the names reverted too. Spec PR E1.

### W1 — wire headers and internal routes

**Changes:** C-4/C-5 as written.

**New tests.** Each asserts that the old name confers nothing, and each has a break-check that
re-adds the old name as an accepted alias:

| Site | Test | Break-check |
|---|---|---|
| Django `authorize_view` (`apps/proxy/authorize_views.py`) | A request carrying `X-Dispatcharr-Authorized` with the *valid* relay-trust value and X-Relay-* params is treated as untrusted (the X-Relay-* values are ignored) | Read `HTTP_X_DISPATCHARR_AUTHORIZED` as a fallback: the test reddens, naming the trust decision |
| Django `InternalRelayPermission` (`apps/proxy/permissions.py`) | A valid `X-Dispatcharr-Internal` + `-Internal-Request` pair is refused 403 | Same fallback on `META_INTERNAL`: reddens |
| Go stream (`relay/httpapi/stream.go`) | A valid old-named marker does not unlock X-Relay-* | Accept `X-Dispatcharr-Authorized`: reddens |
| Go control (`relay/httpapi/channels.go`) | A valid old-named internal pair is refused | Same: reddens |
| nginx (`e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts`) | Asserts **both** marker names blanked in each params file (`HTTP_X_MINO_AUTHORIZED` and `HTTP_X_DISPATCHARR_AUTHORIZED` in the uwsgi include; `X-Mino-Authorized` and `X-Dispatcharr-Authorized` in the proxy include), and the old internal pair blanked in both. Asserts that every location which sets `X-Mino-Authorized` also sets the old marker and the old internal pair to `""`, that neither include blanks the new internal pair, and that every `auth_request` names `/_mino/authorize` | Delete the old-name marker blank from one include: the spec reddens, naming the file and the missing name. Then add `X-Mino-Internal ""` to the proxy include: it reddens, naming the forbidden blank |

The `dispatcharr_api_params*.conf` file names stay (C-6). The e2e spec's include *file name*
assertions (`nginx-stream-buffering.spec.ts:471,489`) are unchanged; its header-name assertions
are not, and they are listed next.

**Tests that change** (the test-modification rule: expected strings only, each listed before →
after in the PR body; a test that proves the *old* name confers nothing is new, in the table
above, never a rewrite of one of these). Measured at `632f1d3d` with `git grep -n -E
'X-Dispatcharr-|HTTP_X_DISPATCHARR|_dispatcharr/authorize' 632f1d3d` over test trees:

- **Python tests naming the literal rather than a constant:** `apps/proxy/tests/test_authorize_view.py`
  (13 hits: `/_dispatcharr/authorize` request paths and the schema assertion at `:138`,
  `HTTP_X_DISPATCHARR_AUTHORIZED=` kwargs at `:237`), `test_authorize_internal_view.py` (10;
  `PATH = "/_dispatcharr/authorize-internal"` at `:46`), `test_internal_auth.py` (10; `_Req(
  HTTP_X_DISPATCHARR_AUTHORIZED=…)`, `HTTP_X_DISPATCHARR_INTERNAL=…`), `test_authorize.py` (7),
  `test_internal_relay_permission.py` (6; `HTTP_X_DISPATCHARR_INTERNAL` / `_REQUEST` at `:28,31,71,86`),
  `test_next_source_api.py:162-163`, `test_control_plane_client.py:325`, `test_hls_format.py:40`,
  `test_tune_path_query_ledger.py:235` (the path the ledger keys its authorize-hop multiset on; the
  multiset itself does not move), `apps/proxy/vod_proxy/tests/test_vod_redirect.py:359`
  (`response["X-Dispatcharr-Session"]`) and `apps/channels/tests/test_dvr_internal_principal.py:43,53`
  (the `X-Dispatcharr-Internal: ` prefix of the redacted `-headers` value).
- **e2e:** `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts:307` (`auth_request
  /_dispatcharr/authorize`), `:344-345` (the marker regexes; the new "old marker blanked"
  assertions sit **beside** these, which keep asserting the live marker under its new name),
  `:417-418` (the `= /_dispatcharr/authorize` block), `:445` (the blanked-locations list) and
  `:475,:495` (the two include blank lists); `e2e/tests/streaming/authorize-matrix.spec.ts:126`
  (the forged marker becomes `X-Mino-Authorized`, and a second forged request under the **old**
  name is a new case); `e2e/tests/dvr/recording-hidden-channel.spec.ts:15` (a comment).
- **Shell:** `docker/tests/test-puid-pgid.sh:715,722,725`, which grep
  `HTTP_X_DISPATCHARR_AUTHORIZED "<hex>"` out of the rendered nginx config to prove the trust
  token is re-derived after `/data/jwt` rotation.
- **Go:** `relay/internal/relaytest/controlplane.go:312`, the harness's `AuthorizePath` twin of
  `control.AuthorizePath` (`:310-311` says a test naming it cannot drift from the real one, and the
  two change together). `relay/httpapi/authorize_test.go:18` and `redirect_test.go:120` are
  comments. Go tests reach the header names through `relay/control/token.go`'s constants, so no
  Go test expectation changes.
- **Docs the guards project pins:** `docs/relay-parity-matrix.md` rows 19, 30 and 38 (§ C-4/C-5).

**Hooks and gates:**

- `*.py`, `tests/test_*.py`. Labels, measured at `632f1d3d`: W1's `apps/proxy/` and
  `apps/channels/` files alone give `["apps.channels.tests", "apps.proxy.tests",
  "apps.proxy.vod_proxy.tests"]` (the third from `apps/proxy/vod_proxy/views.py:1118`'s
  `X-Dispatcharr-Session`); with `dispatcharr/urls.py` and `dispatcharr/utils.py` the commit gate
  and CI run the **full set**.
- `*.go` (Go hook).
- `e2e/**/*.ts` (`tsc --noEmit`).
- `docs/relay-parity-matrix.md` (the guards parity-matrix spec). The anchors of rows 19, 30 and 38
  must still resolve, and a test file whose line counts grew is re-anchored in the same PR.
- **Gate 2:** `internal_auth.py`, `authorize.py`, `authorize_views.py` and `permissions.py` are
  rcfile-listed. Run the isolated coverage script and `--gate`. New tests may *lower* `missing`; a
  rise is a finding.
- The Go coverage gate (no statement change expected).
- On the `migration/**` branch: every Playwright project, especially `streaming`
  (`authorize-matrix.spec.ts`), `streaming-greybox`, `dvr` (the DVR's internal header) and
  `lifecycle-upgrade`.

**Review:** `fable` from round one (security-adjacent).

**PR description draft:**

> Renames the internal wire contract: `X-Dispatcharr-Authorized`/`-Internal`/`-Internal-Request`/
> `-Session` become `X-Mino-*`, and `/_dispatcharr/authorize[-internal]` becomes
> `/_mino/authorize[-internal]`, in Django, nginx and the Go relay in one commit. No reader ever
> accepts both names. In a mixed-version modular rollout an untrusted marker takes the existing
> fallback paths: the Go relay self-authorizes against a route the other version does not serve
> (the tune fails), and the Python relay authorizes inline (serves, with no privilege). The HMAC
> labels are unchanged, so token values are unchanged. The old header names therefore stay in
> `SENSITIVE_HEADERS`, and nginx permanently blanks the old marker and the old internal pair
> alongside the new marker. New tests pin that a valid token under an old name confers nothing, at
> all four verification sites, and that nginx blanks both names. Spec PR W1.

### P1 — persistent defaults and backups

**Changes:**

- `apps/dashboard/models.py:5` `server_name` default becomes `"Mino"`, and
  `apps/hdhr/models.py:4` `friendly_name` default becomes `"Mino HDHomeRun"`.
- One migration per app (`apps/dashboard/migrations/0002_…`, `apps/hdhr/migrations/0002_…`). Each
  has an `AlterField` for the default plus a `RunPython` that rewrites a row only when its value
  **equals the old default exactly**, so a user-customised name is untouched. The reverse rewrites
  rows equal to the new default back. Neither migration changes a table name or a column.
- Backups per C-20.
- **`apps/hdhr/tests/__init__.py` (new).** `apps/hdhr/` has no tests package at `632f1d3d`, so the
  hdhr migration test needs a home. Test discovery finds labels by `app_dir.rglob("tests")`
  (`dispatcharr/test_discovery.py:131`), so the package creates the label `apps.hdhr.tests`. But
  `_PATH_ALIASES` routes `apps/hdhr/` to `("apps.output", "apps.channels")`
  (`dispatcharr/test_discovery.py:52`), and an alias *replaces* prefix matching. A change under
  `apps/hdhr/` would therefore never run the new label. P1 changes that row to
  `("apps.hdhr", "apps.output", "apps.channels")`. It keeps the two existing targets, because the
  HDHomeRun views are exercised from those apps' tests. The comment above the table
  (`dispatcharr/test_discovery.py:31-32`, "`apps/hdhr/` no tests of its own; …") goes stale with
  that edit and is rewritten in the same hunk to say the app now has its own tests package and why
  the other two targets stay. At `632f1d3d`, `tests/test_ci_test_routing.py`
  has **no** `apps/hdhr/` pin (`git grep -i hdhr 632f1d3d -- tests/test_ci_test_routing.py` is
  empty). So P1 **adds** one, in the file's existing style (`self._labels(...)` against a set,
  as at `:30-49`): `test_hdhr_change_runs_hdhr_output_and_channels_tests` asserts that
  `self._labels("apps/hdhr/models.py") == {"apps.hdhr.tests", "apps.output.tests",
  "apps.channels.tests"}`. **No existing assertion in that file changes.** Break-check: drop
  `"apps.hdhr"` from the alias row, and the new test reddens with a set difference naming
  `apps.hdhr.tests`.

**Tests:**

- **Fresh DB:** `manage.py test` creates the test database from zero, so both migrations run
  forward. A model-level test asserts the new default on a newly created row.
- **Upgraded DB:** a `MigrationExecutor` test in the style of
  `apps/channels/tests/test_hls_output_profile_migration.py`. It migrates to `0001`, inserts one row
  at the old default and one with a custom name, migrates to `0002` and asserts that only the first
  changed. Then it migrates back to `0001` and asserts the first is restored and the second is
  untouched.
- **Real upgrade:** `lifecycle-upgrade` on the `migration/**` branch. Ancestor image, seeded
  volume, this image, durable state asserted.
- **Backups:** a test with one `dispatcharr-backup-*.zip` and one `mino-backup-*.zip` in the backup
  dir. Both are listed, and restoring the old one succeeds.

**Break-checks:**

- Make the `RunPython` unconditional. The custom-name assertion reddens.
- Drop the legacy glob. The old archive disappears from `list_backups()` and the test names it.

**Rollback:** each migration reverses (tested above). The image before P1 also runs fine *without*
reversing. Django ignores an applied migration it has no file for, and a row reading "Mino" is
harmless to old code.

**Hooks and gates:**

- `*/models.py`: the edit hook runs `makemigrations --check` for that app.
- **Labels, measured** with `python3 -I scripts/ci_backend_test_labels.py` at `632f1d3d`:
  - `apps/{dashboard,hdhr}/models.py`, their `0002` migrations and `apps/backups/services.py`
    alone give `["apps.backups.tests", "apps.channels.tests", "apps.dashboard.tests",
    "apps.output.tests"]`. That set has **no `core.tests`**, so `core/tests/test_no_pending_migrations.py`
    would not run.
  - P1 also edits `dispatcharr/test_discovery.py`, a `_SHARED_PATH_PREFIXES` path, so the PR's
    real set is the **full set**: the fifteen labels at `632f1d3d`, plus `apps.hdhr.tests` once the
    package exists. `core.tests`, and with it the pending-migrations test, runs in CI for that
    reason.
  - The implementer re-runs the script on the final path list and pastes its output in the PR
    body.
- **`makemigrations --check` evidence:** independent of the label set, the implementer runs
  `python manage.py makemigrations --check --dry-run` in the test container on the final tree and
  pastes its output (`No changes detected`) in the PR body.
- `tests/test_ci_test_routing.py` (label `tests`, in the full set).
- On the `migration/**` branch: every project, with `lifecycle-upgrade` and `lifecycle-restore`
  (backup restore) the ones that matter.

**PR description draft:**

> Persisted product-name defaults move to Mino with reversible data migrations that touch only
> rows still holding the old default (`dashboard.server_name`, `hdhr.friendly_name`); a
> user-chosen name is never rewritten. New backups are `mino-backup-*.zip`; existing
> `dispatcharr-backup-*.zip` archives stay listed and restorable indefinitely. Tested from a fresh
> database, across a forward-and-back migration with seeded old and custom rows, and by the
> lifecycle upgrade from an ancestor image. Spec PR P1.

### E2 — the alias becomes a refusal

**Precondition:** the owner has completed H-7, and says so on the PR.

**Changes:** C-8's E2 paragraph. `scripts/e2e_up.sh` and any remaining old-name passer moves to
`MINO_*`. The lifecycle-upgrade baseline is now an image from E1 or later, which understands
`MINO_*` through E1's rename, so the upgrade test still works.

**Tests:** E1's alias tests become refusal tests, in the same files, with the same allowlisted
environments and the same non-default values. Each asserts a non-zero exit, or the throw, and
that the message names `DISPATCHARR_X` and `MINO_X`; the no-old-name case asserts a clean start
with no message; and each mechanism gains one case with **two** old names set, asserting that
both are named, since a refusal that reports only the first would send the owner round the loop
once per variable. The bodies stay where E1 put them (`dispatcharr/env_alias.py`,
`docker/env-alias.sh`, and `relay/config/envalias.go`, where `AliasLegacyEnv(sink)` becomes
`RefuseLegacyEnv() error`), so the refusal logic is tested directly. A new entrypoint case asserts
that a stale `DISPATCHARR_` line in `/etc/environment` is removed at start.

**The Go refusal adds nothing to `main()`.** `RefuseLegacyEnv() error` returns one error naming
every `DISPATCHARR_*` variable found and its `MINO_*` name (names only, never values, so
`main.go:40`'s credential-logging marker, "config.Load's errors name a variable, a port, or the
secret FILE's path", stays true), and `config.Load()` calls it as its **first statement** and
returns that error. `main()`'s existing `cfg, err := config.Load(); if err != nil { log.Printf(
"startup failed: %v", err); os.Exit(1) }` (`relay/main.go:33-42`) already handles it, so E2
**deletes** E1's `config.AliasLegacyEnv(log.Printf)` line from `main()` and adds no line there.
Exit status is 1 rather than E1's draft 2; the message is what the owner reads, and `startretries`
shows it twenty times either way. Unlike `main()`, `Load()` is tested (`config_test.go`), so the
call site inside it is pinned by a test: `TestLoadRefusesLegacyNames` sets
`DISPATCHARR_RELAY_GO_PORT=5999` with a valid secret and asserts `Load()` returns an error naming
`DISPATCHARR_RELAY_GO_PORT` and `MINO_RELAY_GO_PORT`.

**Break-checks:**

- Comment out the refusal call in `dispatcharr/__init__.py`. The Python case reddens with
  "exited 0", and its stdout shows the alias no longer running either.
- A wrong edit inside `RefuseLegacyEnv`: skip the last variable found. The two-old-names case
  reddens, naming the one that was not reported.
- Delete the `RefuseLegacyEnv()` call from `Load()`. `TestLoadRefusesLegacyNames` reddens:
  `Load()` returned a config where an error was expected.

**Hooks and gates:** as E1, on a `migration/**` branch. **The Go floor, counted before the census
rather than from it:** `main()` loses one uncovered statement (E1's call) and gains none, so the
untested package's `missing` falls by exactly one and no raise is declared. `check_floor_raise.sh:31-33`
admits `NEW <= OLD` silently. E2 therefore **removes** E1's `raise_from`/`raise_listed` pair from
`scripts/coverage_relay_go.floor` (as 4a-1d removed 4a-1c's once its own census landed under the
cap) and sets `missing` to the worst of its 12-round CI census, which must be ≤ E1's floor − 1; a
draw above that is a finding to attribute per line, never a reason to put the pair back. E1 and E2
are consistent: both bodies live in `relay/config` and are tested there; E1's one `main()` line is
declared as `raise_listed=1`, and E2 takes it away again.

**PR description draft:**

> Closes the env var alias window opened by spec PR E1: any `DISPATCHARR_*` variable now stops the
> process at start with a message naming its `MINO_*` replacement, instead of being silently
> ignored (which would fall back to defaults such as `aio` and loopback-only proxy trust). Also
> scrubs stale `DISPATCHARR_` lines from `/etc/environment`. The owner confirmed their deployment
> runs with no legacy-name warning before this merged. Spec PR E2.

## The repository rename

**When:** after D1 merges and before D2 opens. Before the owner starts, D1's E2E and Lifecycle
results must be green on `main`.

**Procedure (owner, H-3 to H-5):**

1. Confirm the name is free: `gh api repos/D10Scot/mino`. It must print HTTP 404; it did on
   2026-10-28.
2. Settings → General → Repository name → `mino`, or
   `gh repo rename mino --repo D10Scot/Dispatcharr --yes`.
3. Immediately run `gh workflow run base-image.yml --repo D10Scot/mino --ref main` and wait for
   it. Then run `gh workflow run ci.yml --repo D10Scot/mino --ref main` to publish
   `ghcr.io/d10scot/mino:latest`. `ci.yml` is the only `:latest` publisher that can be dispatched;
   `docker-build.yml` has no `workflow_dispatch` and runs only on a push to `main`. `ci.yml` passes
   `TIMESTAMP`, so this image is a "dev build" in `core/tasks.py:817`'s sense, and it polls
   upstream's Docker Hub until D2 lands (C-3a). Accepted for the gap between step 3 and D2's merge.
   `docker-build.yml`'s own `mino:latest` arrives with D2's merge. Until D2 changes it,
   `.claude/hooks/start-test-container.sh:19`'s default keeps pulling the frozen
   `ghcr.io/d10scot/dispatcharr:latest`, which is harmless for the hook because it mounts the tree
   under test.
4. Check the new package's visibility: `gh api /users/D10Scot/packages/container/mino --jq
   .visibility`. It needs `read:packages`; the UI is Your profile → Packages → mino. It must be
   `public`, because `vuln-scan.yml` and the lifecycle baseline pull anonymously
   (`lifecycle-tests.yml:420-421`). Set it if not.
5. `git remote set-url origin git@github.com:D10Scot/mino.git` in the root checkout. Worktrees
   share the setting.
6. Open D2.

**What redirects, what breaks, what is unaffected:**

| Thing | After the rename | Action |
|---|---|---|
| Git over SSH/HTTPS to `D10Scot/Dispatcharr` | Redirects | Step 5, then forget it |
| Web, issue and PR URLs, including blob URLs pinned by `mino-apple` to records | Redirect, **as long as no new repository is created as `D10Scot/Dispatcharr`** | **Never re-fork upstream into that name.** A re-fork would break every old link. |
| REST API `repos/D10Scot/Dispatcharr/…` | Redirects (`gh` follows) | D2 moves the defaults anyway |
| Image names from workflows | Switch to `ghcr.io/d10scot/mino` on the next run | Step 3 |
| `ghcr.io/d10scot/dispatcharr` package and its tags | Unchanged; stops receiving pushes | **Keep it.** It is the owner's rollback and the upgrade baseline (D1). Do not delete it. |
| Jobs needing `:base` (backend-tests, go-tests, ci, docker-build, release) | **Fail** until `mino:base` exists | Step 3, before merging anything |
| E2E and lifecycle image builds | Use `mino:base` (D1) | — |
| `metrics.yml` coverage job | Uses the stale `dispatcharr:base` until D2 | Accepted (not required) |
| cosign certificate identity | New signatures say `…/D10Scot/mino/.github/workflows/…`; old images keep `D10Scot/Dispatcharr` forever | D2 documents both. No in-repo automation verifies identities (`git grep certificate-identity` finds only `docs/supply-chain.md:109`). |
| `gh attestation verify --owner D10Scot` | Unaffected | — |
| GitHub Pages | Moves to `https://d10scot.github.io/mino/`. Whether the old URL redirects is not verified here; assume it does not. | `curl -sI https://d10scot.github.io/Dispatcharr/` after step 3, record the answer on D2. D2 updates the links. |
| `metrics-data` branch, `pages.yml` | Move with the repository; `pages.yml` names no repository | — |
| Main ruleset (id 21229979), required checks, `release.yml`'s ruleset read | Attached to the repository, not its name; unaffected | Spot-check: open D2 and confirm the required checks are listed |
| gh-aw workflows, `COPILOT_GITHUB_TOKEN` | Workflows use `${{ github.repository }}`. A fine-grained PAT selects repositories by id, which the rename keeps. | After step 3, dispatch `issue-triage` once and confirm it runs past the engine start. A 400 "no AI credits pricing" means the PAT expired (memory note), not the rename. |
| Renovate | Not installed (`docs/supply-chain.md` § Maintenance). The app selects repositories by id. | — |
| Secrets, environments (`github-pages`), webhooks, deploy keys, branch protection | Unaffected | — |
| Badges | The only README badge is upstream's Open Collective (`README.md:172`). C2 handles it. | — |
| OpenSSF Scorecard history | Keyed by name, so it starts fresh | Accepted |
| CodeQL and code-scanning alerts | Stay with the repository | — |
| `D10Scot/mino-apple` docs | Their links redirect | A later mino-apple docs PR (H-8) |

## Owner actions

In order. Each item has a paste-ready command and its expected output.

- **H-1 (before E1, and again before P1): back up.** In the UI, Settings → Backups → Create, then
  download the zip. Or:

  ```bash
  docker exec <your-container> ls /data/backups
  ```

  Expect a new `dispatcharr-backup-<ts>.zip` (P1 renames future ones). Also snapshot the volume:

  ```bash
  docker run --rm -v <your-volume>:/data -v "$PWD":/out alpine tar czf /out/data-$(date +%F).tgz -C / data
  ```

  Expect a non-empty `.tgz`.
- **H-2 (any time):** say which compose shape the instance runs (AIO or modular) and whether it
  sets `DJANGO_SETTINGS_MODULE` or any `DISPATCHARR_*` variable. Q1, E1 and W1's rollout reasoning
  depend on the answer. Also say which update-check branch your image runs:

  ```bash
  docker exec <your-container> python -c 'import version; print(version.__timestamp__)'
  ```

  `None` means a `docker-build.yml` image, which takes the stable check. A 14-digit timestamp
  means a `ci.yml` image, which takes the dev check that polls upstream's Docker Hub until D2.
- **H-3 to H-5:** § The repository rename, steps 1–6. Afterwards, run the two `cosign verify`
  commands from the updated `docs/supply-chain.md` (D2 § Verification after merge).
- **H-6 (after D2 merges): switch the image name.** In your compose file, change `image:` to
  `ghcr.io/d10scot/mino:latest`. **Keep your existing volume name and `container_name` if your
  scripts use it.** Then:

  ```bash
  docker compose pull && docker compose up -d
  ```

  Expect the container to come up healthy (`docker ps` shows `(healthy)`), with your channels
  present in the UI.
- **H-7 (after E1 merges and is deployed): rename your compose variables.** Rename every
  `DISPATCHARR_X` to `MINO_X`. If you set `DJANGO_SETTINGS_MODULE=dispatcharr.settings`, keep it:
  the package keeps its name (C-10). Then:

  ```bash
  docker compose up -d
  docker logs <your-container> 2>&1 | grep -c 'DISPATCHARR_'
  ```

  Expect `0`. Then tell the orchestrator, which unblocks E2.
- **H-8 (any time after D2):** update `D10Scot/mino-apple`'s docs (`CLAUDE.md`, `README.md`,
  `docs/server-context.md`, the skills' `project.md`) to name `D10Scot/mino`. Pinned blob links
  keep working through the redirect. This is a mino-apple PR, not one from this repository.
- **H-9 (optional, after the programme, with no worktree live): move the local checkout.**

  ```bash
  mv ~/git/Dispatcharr ~/git/mino
  mv ~/.claude/projects/-Users-dion-git-Dispatcharr ~/.claude/projects/-Users-dion-git-mino
  cd ~/git/mino && git worktree repair && .claude/hooks/start-test-container.sh
  ```

  Expect `git worktree list` to show the new paths, and `docker inspect dispatcharr-testrunner
  --format '{{range .Mounts}}{{if eq .Destination "/repo"}}{{.Source}}{{end}}{{end}}'` to print
  `/Users/dion/git/mino`. Then update the six living files that hard-code the old path (C-17).
- **H-10 (any time):** answer § Open questions.

## Open questions for the owner

1. **Q1. Rename the `dispatcharr/` Python package?** Recommendation: **no** (C-10). If yes, it
   becomes its own PR after E2, and it needs all of the following:
   - a `dispatcharr` shim package that re-exports the new one, for plugins and for any
     `DJANGO_SETTINGS_MODULE` still set in your compose;
   - all six workflow path filters, `_SHARED_PATH_PREFIXES`, `.coveragerc`, `pyproject.toml`
     `packages`, five uWSGI inis and the Daphne conf, in one commit;
   - a `git mv`, which is exactly the path rename R-3 avoids, so the reviewer must enumerate every
     path-matched arm by hand.
2. **Q2. Schedules Direct.** U1 makes SD see `Mino/<version>`. Do you want to tell SD (a
   registered-application note), or leave it? Recommendation: tell them. It is a courtesy, not a
   dependency. No code depends on the answer.
3. **Q3. Logo.** `frontend/src/images/logo.png`, `frontend/src/assets/logo.png`,
   `frontend/public/logo.png` and `frontend/src/images/dispatcharr.svg` are upstream's art.
   Recommendation: keep them until you supply Mino art, then swap the images at the same paths (a
   swap, not a rename).
4. **Q4. A dev-build update check against GHCR.** D2 disables the dev branch (C-3a), because GHCR
   has no anonymous per-tag update time. Do you want a working dev-build check back? If so, it is
   a separate follow-up after this programme. It would be a new feature, built either on the OCI
   registry walk (token, index, platform manifest, config blob `created`) or on the Packages API
   with a `read:packages` token held by the instance. Recommendation: no. You build your own
   images and know when `main` moved.
5. **Q5. Support and funding links.** `FUNDING.yml`, the Discord and Open Collective links, and
   the docs site are upstream's community. Recommendation: remove them (C1, C2) and keep only the
   attribution line. If you want something there instead (your own issue tracker), say so before C1.
6. **Q6. Dev-loop container names** (`dispatcharr-testrunner`, `-hookdb`, `-e2e…`).
   Recommendation: **keep** (C-12). If you want them renamed, it is one optional PR after H-9,
   coordinated with every live agent, accepting a fresh `--keepdb` database.
7. **Q7. `debian_install.sh`.** It is upstream's bare-metal installer, unused by your deployment.
   D2 repoints its clone URL only. Deleting it is a separate decision.

## Scope guard

Out of this programme, even when a rename PR walks past them:

- the `localStorage` password (C-19);
- a GHCR-backed dev-build update check (Q4; D2 only disables the upstream one);
- repointing the official plugin registry (C-3);
- renaming kept identifiers (§ Categories);
- any change to HMAC labels (C-4);
- `metrics.yml`'s stale base between the rename and D2;
- version renumbering.

## Appendix A — owner rulings

- **M1.** No more syncing with upstream `Dispatcharr/Dispatcharr`. Ideas may be reimplemented,
  never merged. Merge-conflict cost against upstream is no constraint.
- **M2.** No deployments exist besides the owner's own. Back-compat shims may be short-lived or
  skipped, but the owner's instance must upgrade in place with its data preserved (PostgreSQL rows,
  the `/data` volume, recordings, plugins, settings).
- **M3.** The repository becomes `D10Scot/mino`; the app is `D10Scot/mino-apple` (bundle
  `scot.d10.mino`). Renaming the GitHub repository is a settings action the owner performs; the
  spec says when, and what breaks or redirects.
- **M4.** Decision records keep the old name as history: ADRs, specs, plans, analyses, Done logs,
  `docs/comparisons/`.

## Appendix B — env var names (living files, `632f1d3d`)

**Product (34)**, read by `apps/`, `core/`, `dispatcharr/`, `docker/`, `relay/` (non-test) or
`frontend/devProxy.js`:

`ALLOWED_SCRIPT_DIRS`, `API_HARAKIRI`, `API_MAX_REQUESTS`, `BUILD`, `CELERY_HOME`,
`CELERY_USER`, `DEBUG`, `ENABLE_IP_LOOKUP`, `ENV`, `HOME`, `INTERNAL_API_BASE_URL`,
`INTERNAL_TS_BASE_URL`, `LOG_LEVEL`, `PLUGINS_DIR`, `PORT`, `RELAY_BASE_URL`,
`RELAY_DEFAULT_NAME`, `RELAY_GEVENT`, `RELAY_GO_DEV_ROUTES`, `RELAY_GO_PORT`, `RELAY_HOST`,
`RELAY_PORT`, `ROLE`, `SCRIPT_MAX_OUTPUT`, `SCRIPT_TIMEOUT`, `SECRET_FILE`, `SETUP_ALLOWED_IP`,
`SKIP_PLUGIN_AUTODISCOVERY`, `TIMESTAMP`, `TRUSTED_PROXIES`, `UWSGI_EXTRA_ARGS`, `UWSGI_INI`,
`VERSION`, `WEB_HOST` (each prefixed `DISPATCHARR_`).

**Tooling (16):** `E2E_BASELINE_IMAGE`, `E2E_CONTAINER`, `E2E_IMAGE`, `E2E_NETWORK`, `E2E_PORT`,
`E2E_READY_ATTEMPTS`, `E2E_REPO_OWNER`, `E2E_SKIP_UPSTREAM_BUILD`, `E2E_UPSTREAM_CONTAINER`,
`E2E_UPSTREAM_IMAGE`, `E2E_UPSTREAM_PORT`, `E2E_VOLUME`, `TEST_CONTAINER`, `TEST_DB_VOLUME`,
`TEST_IMAGE`, `WRITE_GOLDEN`.

**Django settings, not env (3):** `PLUGIN_IMPORT_MAX_BYTES`, `PLUGIN_IMPORT_MAX_FILE_BYTES`,
`PLUGIN_IMPORT_MAX_FILES`.

Only in records, so they are not renamed: `RELAY_GO_BIN`, `RELAY_GO_CHANNEL_BUFFER_BYTES`,
`E2E_STACK`.

## Appendix C — the 31 tracked paths containing the name, all kept

`.idea/DispatcharrSM.iml`; `apps/channels/migrations/0034_remove_stream_dispatcharr_stream_id_idx_and_more.py`;
`apps/plugins/keys/dispatcharr-plugins.pub`; the 23 files under `dispatcharr/`
(`__init__.py`, `admin.py`, `app_initialization.py`, `asgi.py`, `celery.py`, `consumers.py`,
`db/__init__.py`, `db/backends/__init__.py`, `db/backends/postgresql_psycopg3/{__init__,base,pool}.py`,
`db/process_label.py`, `gevent_patch.py`, `jwt_ws_auth.py`, `persistent_lock.py`, `routing.py`,
`settings.py`, `settings_test.py`, `test_discovery.py`, `test_runner.py`, `urls.py`, `utils.py`,
`wsgi.py`); `docker/DispatcharrBase`; `docker/dispatcharr_api_params.conf`;
`docker/dispatcharr_api_params_proxy.conf`; `docker/init/03-init-dispatcharr.sh`;
`frontend/src/images/dispatcharr.svg`.
