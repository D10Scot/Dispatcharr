# Fix plan, category G — CI, hooks and tooling

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans to implement this plan task by task. Implementers are `sonnet`; a
> stuck implementer escalates to `opus`. Every PR is reviewed by `fable` (`opus` when fable credits are
> unavailable) against this plan before it leaves draft. Steps use checkbox (`- [ ]`) syntax.

| | |
|---|---|
| category | G — CI, hooks and tooling |
| seed SHA | **`a54b09a9`** (`main`, 2026-09-23). Every `file:line` below was opened there. |
| ordering | **seventh** of ten (B, A, J, C, D, E, **G**, H, I, F). The lead re-seeds when an earlier plan merges. |
| issues | #279, #278, #277, #254, #226, #16, #180, #81, #183 planned; **#133 parked by the user** (gh-aw pipelines ignored for now: no memo, no plan). |
| PRs | nine: G-1 … G-9 (§ PR sections). Three are `migration/` because they touch `docker/`. |
| memos | none. The user ruled #16 and #277 to be implementation sections, not memos. |
| upstreamable | yes: G-7, G-8, and G-4's ld.so.conf hunk by hand. No: the rest. Recorded per PR. |

**What this plan finds that the issue bodies do not say.** These are the findings a reviewer should check first.

1. **#277 has one root cause per scanner, and neither is the "standing set" the issue fears.**
   - **OSV-Scanner** fails on one transitive frontend package, `@xmldom/xmldom` 0.8.13. That is eight GHSA advisories, all at CVSS 8.7, all fixed in 0.8.15. The fix is a three-line lockfile change. I measured it with the workflow's own pinned scanner: after the bump, the worst finding is CVSS 5.7.
   - **Grype** fails on exactly **two** findings, identical on `:latest` and `:base`. Both are in the ffmpeg **8.1.2 binary**: CVE-2026-70632 (CFHD decoder) and CVE-2026-70628 (DVB-subtitle parser). Every other row of both tables is Medium. FFmpeg backported both fixes into **n8.1.3** on 2026-09-19. But linuxserver never published an 8.1.3 image. Its only fixed image is **9.0**, and that image is built on **Ubuntu 26.04**, where today's base is 24.04. Upstream Dispatcharr deliberately pinned *back* from `latest` (9.0) to 8.1.2 on 2026-08-19 (`fd413f0c`), with no recorded reason.
   - So there are two real remedies. One is an accepted-risk ignore of exactly those two CVEs, time-boxed with an expiry the workflow enforces (G-3). The other is the 24.04 → 26.04 base migration (G-9). I ran the pinned Grype with just those two rules against both published images: both exit 0. **Q1** asks the user which remedy to take; the default is both.
2. **#226 happens only on arm64.** In the base image, `/etc/ld.so.conf.d/aarch64-linux-gnu.conf` sorts *before* `libc.conf` (which carries `/usr/local/lib`). `x86_64-linux-gnu.conf` sorts *after* it. So on amd64 the linked-against librist 4.11 already wins, and CI's ffmpeg runs: the go-tests log prints `ffmpeg version 8.1.2`. On arm64 the distro librist 4.3.1 wins, and ffmpeg dies. Measured on both arches with `ghcr.io/d10scot/dispatcharr:base`. A `00-` conf file listing `/usr/local/lib`, plus `ldconfig`, fixes arm64 and changes nothing on amd64. Prototyped: ffmpeg runs, and comskip keeps its distro libav through its `DT_RPATH`.
3. **#81's premise is inverted, and the issue's suggested fix would break two things that work today.**
   - `include uwsgi_params` forwards *every* client header. So an outer proxy's `X-Forwarded-Proto/Host/Port` **already reach** `get_host_and_port` on every `uwsgi_pass` location, and branch 1 is live whenever an outer proxy sets them.
   - Setting `uwsgi_param HTTP_X_FORWARDED_HOST $host:$server_port` would *overwrite* those values with nginx's own. That breaks outer TLS proxies (`https` would become `http`). It also breaks every direct client on a Docker port remap (`-p 1234:9191`), because `$server_port` is 9191. Two e2e tests pin exactly that remap today: `e2e/tests/seeded/output-m3u.spec.ts:53-64` and `hdhr.spec.ts:97-103`.
   - Trust-gating the headers adds nothing either. `Host` is exactly as client-controlled (`ALLOWED_HOSTS=["*"]`).
   - So G-7 corrects the docstring that says "set by our nginx", and pins the three deployment shapes with backend tests so the naive fix cannot land. This is consistent with B's plan, and it goes one step further: G adds **no** `uwsgi_param` at all. **Q2** asks the user to confirm.
4. **#16 is wider than one workflow.** Exactly three Node 20 action refs exist in the repo. They appear at **22 sites across seven workflows**, not three sites in one. Every other pinned action is already Node 24 or composite; I resolved the `runs.using` of all 31 refs. The Node 24 successors are the SHAs the compiled gh-aw `.lock.yml` files already pin, and I re-resolved them as each action's latest release today. G-2 does all 22 sites. **Assumption A1** records this widening.
5. **#278's settings filter can stay a filter.** The hook docs say `if` "holds exactly one permission rule". They say Bash patterns are checked per subcommand, and that "when Claude Code can't determine which commands the Bash input runs, it runs your hook regardless" (code.claude.com/docs/en/hooks, § Bash `if` matching). `Bash(git *)` therefore catches `git -C <dir> commit`, and the script's own regex decides. That keeps the "Running tests" spinner off non-git calls.
6. **A base image with `git` changes every container job's checkout from a tarball to a real `.git`.** Go's VCS stamping then runs `git` as root against a workspace owned by another uid. The comment at `backend-tests.yml:293-300` records git refusing exactly that ("dubious ownership"). G-4 adds a guarded `safe.directory` step to go-tests' container job **before** the base changes. I did not measure the Go failure itself. The guard is cheap and correct either way.

---

## Header: files this plan touches

| file | PR | issue |
|---|---|---|
| `.claude/hooks/_hook_common.sh` (`:23-24`, `:43-48`) | G-1 | #279 |
| `.claude/hooks/pre-commit-tests.sh` (`:23-76`) | G-1 | #278, #279 |
| `.claude/hooks/run-affected-tests.sh` (`:43-52`) | G-1 | #279 |
| `.claude/hooks/tests/test_hooks.sh` (new) | G-1 | #278, #279 |
| `.claude/settings.json` (`:29-32`) | G-1 | #278 |
| `.github/workflows/lint.yml` (new job `hook-tests`; setup-node at `:201`) | G-1, G-2 | #278/#279, #16 |
| `.github/workflows/e2e-tests.yml` (`:180,202,244,292,329,366`) | G-2 | #16 |
| `.github/workflows/lifecycle-tests.yml` (`:211,258,338,367,378,494,521,532,585`) | G-2 | #16 |
| `.github/workflows/backend-tests.yml` (`:236,271`; `:258-262`) | G-2; G-5 | #16; #254 |
| `.github/workflows/go-tests.yml` (`:237,326`; new step after `:179`; comments `:62,146,154`) | G-2; G-4; G-9 | #16; #254; #277 |
| `.github/workflows/frontend-tests.yml` (`:108`) | G-2 | #16 |
| `.github/workflows/metrics.yml` (`:172`; `:150-158`) | G-2; G-5 | #16; #254 |
| `.github/workflows/vuln-scan.yml` (`:216-226` + two new steps) | G-3, G-9 | #277 |
| `frontend/package-lock.json` (`:2574-2577`) | G-3 | #277 |
| `docker/DispatcharrBase` (`:7`, `:115`, `:141-146`, new lines before `:178`) | G-4, G-9 | #254, #226, #277 |
| `docker/Dockerfile` (after `:64`) | G-6 | #180 |
| `docker/init/03-init-dispatcharr.sh` (`:67-72`, `:133-140`) | G-6 | #180 |
| `docker/nginx.conf` (comment above `:69`) | G-6 | #81 (comment only) |
| `docker/tests/test-puid-pgid.sh` (new scenario; `SCENARIOS` at `:2011-2033`) | G-6 | #180 |
| `core/utils.py` (`:1000-1012` docstring/comments only) | G-7 | #81 |
| `core/tests/test_core.py` (new class) | G-7 | #81 |
| `apps/timeshift/views.py` (`:3256-3264`) | G-8 | #183 |
| `apps/timeshift/tests/test_views.py` (new test in `StreamFromProviderStatusMappingTests`, `:134`) | G-8 | #183 |
| `metrics/curated/defects.yml` (`:31`) | G-4 | #226 |
| `CLAUDE.md` (`:63`, `:64`, `:68`, `:135`) | G-1, G-9 | #278/#279, #277 |

### Overlap with other categories

| file | other plan and its lines | what I assume it does | order | conflict |
|---|---|---|---|---|
| `docker/nginx.conf` | **B** touches no nginx file (B plan row `:71`). **J-1** edits comments `:25-58` only. **H** #179 is a test of `:698`. | B's semantic note: G must not add `uwsgi_param HTTP_X_REAL_IP`/`X_FORWARDED_FOR`. G adds no `uwsgi_param` at all (finding 3), and its only nginx edit is a comment above `:69`. | J-1, then G-6 | none textual |
| `dispatcharr/utils.py` | **B-7** `:298-338` | G no longer touches it: the trust-gate option for #81 is not the default (Q2). | — | none |
| `core/utils.py` | **I** #162 (property tests on `:79,105`); **A** #24-ish bare excepts (`:890-924`) | G-7 edits the docstring and comments at `:1000-1012` only | any | none |
| `apps/timeshift/views.py` | **D-3** `:72-76,1111-1148,1188-1208,1230-1242,1961-1979`; **I** property tests (no views edit) | disjoint from G-8's `:3256-3264` | D, then G | none |
| `apps/timeshift/tests/test_views.py` | **D-3**, **I** add tests | G-8 adds one method to `StreamFromProviderStatusMappingTests` | D, then G | append-only |
| `.github/workflows/e2e-tests.yml` | **H** #168/#187 (`scripts/e2e_up.sh`; #185, a closed duplicate, also touched this workflow) | H edits the stack scoping, not the action pins | G-2, then H | trivial rebase if H edits a step G-2 re-pinned |
| `metrics/curated/defects.yml` | B, D, J append or edit rows | G-4 edits row `:31` only | any | one row per line |
| `CLAUDE.md` | A, B, D, E, I, J edit their own prose | G edits the sentences listed per PR, anchored by text with `assert count == 1` | G last among those | none expected |
| `docker/DispatcharrBase` | **E** #128 cites `:36` (python3.13) as a premise | G-9 keeps `python3.13` from deadsnakes. Measured: `resolute` publishes `python3.13`. So E's premise holds after G-9. | any | none |
| `scripts/coverage_live_path_isolated.sh` | **J-4** forwards every argument | G does not edit it | — | none |

---

## Global constraints

Numbered so a task step can cite one. **A conflict between a constraint and a step is a STOP and report, not a judgement call.**

1. **Anchor every command** with an absolute path or a leading `cd <your worktree> &&`. The shell's cwd is shared or correlated across agents (CLAUDE.md § Repository and direction). One worktree per PR, off `main`.
2. **`set -o pipefail`** on every pipeline whose status you read. Never `2>/dev/null` a git query you interpret. Always brace refs in `git show "${ref}:path"`.
3. **Stage and commit in separate Bash calls.** Write the message with the Write tool and commit with `git commit -F <file>`. The commit gate matches on command text, and so does this plan's own prose. A heredoc containing both words is blocked. That happened while this plan was being prototyped.
4. **Test-modification rule (brief rule 5), verbatim:** a test may change only when the behaviour it pins is the thing being changed, and every such change is listed in the PR section with its before and after assertion. Never widen a tolerance, lower a count or delete an assertion to make a run green. New behaviour gets a new test named after the defect.
5. **Your own test container.** Start it with `DISPATCHARR_TEST_CONTAINER=<pr> DISPATCHARR_TEST_DB_VOLUME=<pr>-db CLAUDE_HOOK_REPO_ROOT=<your worktree> /Users/dion/git/Dispatcharr/.claude/hooks/start-test-container.sh`. Run single labels through it. The `PostToolUse` hooks still use `dispatcharr-testrunner`, whatever you export (CLAUDE.md § Test hooks). If a hook refuses on a mount mismatch, that is the hook working. Do not re-point the shared container unless `docker ps` and file mtimes show it is free.
6. **Workflow edits use the Edit tool, not `sed`,** so the zizmor `PostToolUse` hook fires on each file. The hook fires only on Write/Edit. Workflows are at zero findings: keep them there.
7. **Every new `uses:`/`FROM` pin is tool-resolved** (`gh api repos/<o>/<r>/commits/<tag> --jq .sha`; `docker buildx imagetools inspect <ref> --format '{{json .Manifest}}' | jq -r .digest`), and the publisher namespace is confirmed first (CLAUDE.md § Supply chain). The values quoted here were measured on 2026-09-23. Re-resolve them; do not copy them.
8. **`#<PR>` in a ledger or CLAUDE.md edit is the PR's real number.** Commit the code, open the draft PR, then make those edits in a second commit (`docs/agents/metrics.md`).
9. **A base-image PR is not tested by CI before merge.** `base-image.yml` builds a pull request's image but pushes it only from `main` (`base-image.yml` `push: ${{ github.event_name != 'pull_request' }}`). `backend-tests.yml`, `go-tests.yml` and `e2e-tests.yml` all consume the *published* `:base`. The e2e build passes only `REPO_OWNER` (`e2e-tests.yml:164`), so it builds on the published base too. For G-4 and G-9, the local verification steps are therefore the only runtime evidence before merge. Do them in full, and paste their output into the PR.

---

## Per-issue findings

### #279 — a stale `CLAUDE_HOOK_REPO_ROOT` exits 0 silently
- **Root cause.** `.claude/hooks/_hook_common.sh:45-47` prints the override verbatim with no check. Its callers then run `cd "$REPO_ROOT" || exit 0` (`pre-commit-tests.sh:62`, `run-affected-tests.sh:46`). Worse, when the override is a *valid* repo that does not contain the edited file, `run-affected-tests.sh:50` (`/*) exit 0`) passes silently. Measured with the prototype harness below: on the seed hooks, a nonexistent override produces only bash's own `cd:` error on stderr, and exit 0.
- **Exposure.** CLAUDE.md § Test hooks records that exported variables never reach the harness-run hooks. The real exposure is manual runs and the `--git-hook` mode (`pre-commit-tests.sh:24`), which inherits a human's shell.
- **Fix.** `hook_repo_root` validates the override with `git -C … rev-parse --show-toplevel`. It also requires the override to *be* the top level, comparing canonical paths. Failure returns **2**, distinct from 1 ("anchor in no repo", a legitimate nothing-to-do). Both callers turn status 2 into a loud note, the scripts' existing "could not run" JSON shape (exit 0, stated loudly: the `run-affected-tests.sh:27-30` header). The edit hook also refuses loudly on a file outside a valid override. Appendix A has the diffs.
- **Tests.** New `.claude/hooks/tests/test_hooks.sh`, five #279 cases (§ G-1).
- **Size / upstreamable / duplicates.** S / no (fork-only `.claude/`) / none.

### #278 — `git -C <dir> commit` bypasses the commit gate
- **Root cause.** Two layers, both keyed on the literal prefix. `.claude/settings.json:29` has `"if": "Bash(git commit*)"`, and `pre-commit-tests.sh:28` has `case … *"git commit"*`. `git -C <dir> commit` contains neither string. The refusal at `:45-47` is reached only after `:28` matched. The same blindness applies to the `git add` block at `:73`: `git -C x add … && git -C x commit` is not refused.
- **Fix.** The filter becomes `Bash(git *)` (finding 5). The script matches `git`, then any global options, then `commit` as a word, by regex. It treats `git -C <dir> commit` (optionally with `-c k=v`) as an anchor, exactly as #258 treats `cd <dir> &&`. Anything else that changes directory or repository (`cd`, `pushd`, `-C`, `--git-dir`, `--work-tree`) before the commit gets the existing "cannot safely determine" note. The add-and-commit refusal moves ahead of the directory forms and learns the same option grammar. Appendix A.
- **Tests.** Five #278 cases plus four controls (§ G-1).
- **Size / upstreamable / duplicates.** M (the harness is most of it) / no / none.

### #277 — vuln-scan.yml red on every run
- **Root cause (measured on run `35843990227`, `a54b09a9`).**
  - OSV-Scanner: `@xmldom/xmldom` 0.8.13 (`frontend/package-lock.json:2574-2577`), reached only through `mpd-parser`'s `^0.8.3`. There are eight advisories at CVSS 8.7, all fixed in 0.8.15 (the GitHub advisory API gives each range).
  - Grype: `ffmpeg` binary 8.1.2, CVE-2026-70632 and CVE-2026-70628 (NVD: "up to, but not including, 9.0"; CVSS 3.1 of 7.8). These are the only High rows on either image. Everything else is Medium and does not block.
  - FFmpeg `n8.1.3` carries both fixes (`gh api repos/FFmpeg/FFmpeg/compare/n8.1.2...n8.1.3`: "avcodec/cfhd: reject transform-2 output wider than the plane" and "avcodec/dvbsub_parser: avoid signed overflow in the capacity check", 2026-09-19). But linuxserver's tag list jumps from `8.1.2` (2026-08-07) to `9.0` builds. `lscr.io/linuxserver/ffmpeg:version-9.0-cli` reports `VERSION_ID="26.04"` (resolute), where `:base` is `24.04` (noble).
  - Trivy passes both images, because it has no ffmpeg binary matcher.
- **Why it rotted.** Nothing bumps the linuxserver digest. `renovate.json` would, but Renovate is not installed (CLAUDE.md § Supply chain: "Inert until the Renovate app is installed").
- **Fix.** G-3 (default): bump xmldom. Add an accepted-risk rule for each of the two CVEs, scoped to `ffmpeg`/`8.1.2`/`binary`, with a written reason and an `EXPIRES` date that a new step enforces. The blocking steps stay blocking, and the informational steps still print everything. G-9: migrate the base to `version-9.0-cli` on 26.04, which deletes the two rules.
- **Tests.** The workflow's own PR run is the test: `vuln-scan.yml` triggers on changes to itself and to `frontend/package-lock.json`. The break-checks are local (§ G-3).
- **Size / upstreamable / duplicates.** G-3 S, G-9 L / no / none.

### #254 — bake `git` into the base image
- **Root cause.** `docker/DispatcharrBase:141-146` installs no `git`; `grep -cw git docker/DispatcharrBase` gives 0. `backend-tests.yml:258-262` and `metrics.yml:150-158` `apt-get install git` at runtime inside `:base`.
- **Fix.** G-4 adds `git` to the final stage's apt list. G-5, after the new base is published, deletes both runtime installs.
- **Consumers that change behaviour** (the issue's "Not verified" item). With git present, `actions/checkout` does a real clone in every `container:` job: backend `test`/`coverage-label`/`coverage-gate`, go-tests `build`, metrics. Python ignores `.git`. Go stamps VCS info and would call git (finding 6), hence G-4's guard. `grep` over `*.py`, `*.go`, `*.sh` and `*.yml` finds no other code that behaves differently when git exists.
- **Size / upstreamable / duplicates.** S + S / no / none.

### #226 — ffmpeg unrunnable in the test containers
- **Root cause.** Finding 2. Measured on `ghcr.io/d10scot/dispatcharr:base`: on arm64, `ffmpeg -version` gives `undefined symbol: rist_peer_config_defaults_set_versioned`, and `ldd` resolves librist to `/usr/lib/aarch64-linux-gnu/librist.so.4` (4.3.1). On amd64 it prints `ffmpeg version 8.1.2`, and `ldd` resolves `/usr/local/lib/librist.so.4`. The distro librist comes in through `libavformat60` (`apt-cache rdepends --installed librist4`), which vlc pulls in, and vlc is a built-in stream profile. The config explains it: `/etc/ld.so.conf.d/` holds `aarch64-linux-gnu.conf` + `libc.conf` on arm64, and `libc.conf` + `x86_64-linux-gnu.conf` on amd64.
- **Fix.** G-4 writes `/etc/ld.so.conf.d/00-usr-local-lib.conf` containing `/usr/local/lib`, runs `ldconfig`, then runs `RUN ffmpeg -version` as a build-time assertion. `base-image.yml` builds both arches on a PR, so a regression fails the image build. `docker/entrypoint.sh:102`'s export stays: it is harmless, and it also covers `LIBVA` paths. Prototyped on arm64: ffmpeg runs; comskip still resolves `libavformat.so.60`/`librist.so.4`/`libfontconfig.so.1` from `/usr/lib/aarch64-linux-gnu` (DT_RPATH, `DispatcharrBase:83-87`); Python's ssl is unaffected.
- **Ledger.** `metrics/curated/defects.yml:31` `ffmpeg-unrunnable-without-ld-library-path` → `fixed`.
- **Size / upstreamable / duplicates.** S / the ld.so.conf hunk is worth offering upstream by hand; the file differs, so no / none.

### #16 — Node 20 actions
- **Root cause.** Three refs target `node20`, resolved from each ref's `action.yml` at its pinned SHA:
  - `actions/upload-artifact@ea165f8d… # v4.6.2`: 8 sites.
  - `actions/setup-node@49933ea5… # v4.4.0`: 8 sites.
  - `actions/download-artifact@d3f86a10… # v4.3.0`: 6 sites.
  - The 22 sites are in seven files (header table).
- **Successors.** Latest releases, tool-resolved 2026-09-23, each `node24`, and each already pinned by the compiled `*.lock.yml` files:
  - `actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1`
  - `actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1`
  - `actions/setup-node@820762786026740c76f36085b0efc47a31fe5020 # v7.0.0`
- **Breaking changes checked against every site:**
  - download-artifact v5 changed single-artifact-by-ID paths. No site uses `artifact-ids`.
  - v8 errors on a digest mismatch by default. That is desirable.
  - setup-node v5 auto-caches when `package.json` has `packageManager`. None of `frontend/`, `e2e/` or `e2e-upstream/` does.
  - upload-artifact v7 adds an opt-in `archive: false`. No site sets it.
- **Size / upstreamable / duplicates.** S / no / none.

### #180 — nginx templated in place
- **Root cause.** `docker/Dockerfile:64` copies `nginx.conf` straight to `/etc/nginx/sites-enabled/default`. `docker/init/03-init-dispatcharr.sh` then `sed -i`s four placeholders into it (`:72` `NGINX_PORT`, `:93` `RELAY_UPSTREAM`, `:109` `RELAY_GO_UPSTREAM`, `:140` `RELAY_TRUST_TOKEN`) and deletes IPv6 `listen` lines (`:147`). A `docker restart` keeps the writable layer, so the second boot finds no placeholders. The comment at `:133-139` says so.
- **What can actually change across a restart.** `/data/jwt`, and with it `RELAY_TRUST_TOKEN` (`03-init:120-127`). Env vars cannot change without recreating the container, and a recreate gets a fresh layer anyway.
- **Fix.** Ship a pristine copy at `/usr/share/dispatcharr/nginx.conf.template`. That is outside `/etc`, which the `readonly_rootfs` scenario replaces with a tmpfs, and outside `/app`, which a dev bind mount can replace. Render `sites-enabled/default` from it at the top of the nginx block on every boot. Appendix D.
- **Tests.** New lifecycle scenario `nginx_rerendered_on_restart` in `docker/tests/test-puid-pgid.sh`.
- **Size / upstreamable / duplicates.** M / no (upstream's 03-init has none of the relay placeholders) / none.

### #81 — `X-Forwarded-*` on `uwsgi_pass` locations
- **Root cause, as it actually is.** Finding 3.
  - `docker/nginx.conf:69-74` sets them with `proxy_set_header`, which applies only to `proxy_pass` locations (`/ws/`, the three relay_go locations, `/proxy/relay/`). None of those readers builds absolute URLs: `grep -rn -i forwarded relay/` is empty.
  - On `uwsgi_pass` locations, `include uwsgi_params` passes the client's or outer proxy's own headers as `HTTP_*`. `core/utils.py:1008-1043` consumes them, and falls back to `Host` when they are absent.
  - The issue's empirical note is the direct-client case, and it is correct behaviour: `Host: internaltest:1234` gave `http://internaltest:1234/`.
  - The only defects are the misleading docstring ("Prefers … (nginx)", `:1003`; "set by our nginx", `:1011`) and the absence of any backend test holding the three shapes.
- **Fix.** Documentation plus guard tests (G-7), and one nginx comment (G-6). No `uwsgi_param`. **Q2.**
- **Size / upstreamable / duplicates.** S / yes (`get_host_and_port` exists upstream at `core/utils.py:1034` on `dev`) / none. It is related to #182 (B-7) and stays separate, as B's plan argues.

### #183 — control bytes in the timeshift log
- **Root cause.** `apps/timeshift/views.py:3256` decodes the peek with `errors="replace"`. `:3263` strips only `\n`, so NUL, ESC and other C0 bytes reach the log line.
- **Fix.** Log `repr(peek[:120])` instead, which escapes every non-printable byte.
- **Tests.** One new method, `test_a_non_ts_body_is_logged_without_raw_control_bytes`.
- **Note.** CodeQL alerts #99/#100 sit on these lines. Their issues, #292/#293, were ruled invalid in the sweep. Changing the line may re-key the alerts; dismiss them as before if they reappear.
- **Size / upstreamable / duplicates.** S / yes (the same log call is at `apps/timeshift/views.py:3323` on upstream `dev`) / none.

### #133 — gh-aw issue-triage context
**Parked by the user** (rulings, Q5). No memo, no plan. The sweep's root cause (`issue-triage.md:89`, `--comments` prints only comments when not on a TTY) stays on the issue for when it is un-parked.

---

## PR sections (implementation order)

### PR G-1 — the commit gate sees `git -C`, and a stale root override refuses loudly

- **Branch** `fix/G-1-hook-git-dash-C-and-root-override`
- **Closes** #278, #279
- **Files** `.claude/hooks/_hook_common.sh`, `.claude/hooks/pre-commit-tests.sh`, `.claude/hooks/run-affected-tests.sh`, `.claude/hooks/tests/test_hooks.sh` (new), `.claude/settings.json`, `.github/workflows/lint.yml` (new job), `CLAUDE.md` (`:64`, `:68`)
- **Test labels** none: `scripts/ci_backend_test_labels.py` maps none of these paths. The harness runs in `lint.yml`'s new `hook-tests` job.
- **upstreamable** no

**How to test a hook change without the hook testing itself.** Read this before Task 1.

- The hooks that fire in your session are `${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/*` (`settings.json:10,16,30`). In this fork that path is pinned to the **main checkout**, not your worktree (`_hook_common.sh:5-11`). Settings are read at session start.
- Consequences:
  - (a) Your edits change nothing that guards your own session.
  - (b) A green live hook tells you nothing about your edit.
  - (c) The **old** gate guards your commits, and it has the very bug you are fixing. **Commit only with the plain `cd <your worktree> && git commit -F <file>` form, never `git -C`.** Under the old gate, `git -C` commits ungated.
- The only evidence is invoking your worktree's copies directly: `bash <wt>/.claude/hooks/tests/test_hooks.sh`, whose `HOOK_DIR` defaults to its own parent. The harness must pass before you commit.
- If `CLAUDE_PROJECT_DIR` is ever your worktree rather than main, a half-edited gate could disable itself for your commits. Running the harness before each commit covers that case too.
- After merge, the new hooks are live on `main`. Task 6 smoke-tests them there with a dry run.

**Tasks**

- [ ] **Task 0 — seed check.** `cd <wt> && git log -1 --format=%H` is on `main`. Then `grep -n 'if": "Bash(git commit\*)"' .claude/settings.json` prints `:29`, and `grep -n 'printf .%s\\n. "\$CLAUDE_HOOK_REPO_ROOT"' .claude/hooks/_hook_common.sh` prints `:46`. If either anchor has moved, STOP.
- [ ] **Task 1 — the harness first, red.** Create `.claude/hooks/tests/test_hooks.sh` from Appendix B, verbatim, and make it executable. Run `bash <wt>/.claude/hooks/tests/test_hooks.sh`. **Expected on the seed hooks: `8 passed, 9 failed`.** The nine failures are exactly the nine `test_*` cases. All eight `control_*` cases pass. This was measured on a copy of the seed hooks. If a `control_*` fails, STOP: the harness is wrong, not the hooks.
- [ ] **Task 2 — `_hook_common.sh`.** Apply Appendix A.1.
- [ ] **Task 3 — `pre-commit-tests.sh`.** Apply Appendix A.2. The old `git add` block at `:67-76` moves up into the parse block and is deleted from its old place. `grep -c 'COMMIT BLOCKED — this command stages' .claude/hooks/pre-commit-tests.sh` must print `1`.
- [ ] **Task 4 — `run-affected-tests.sh` and `settings.json`.** Apply Appendix A.3 and A.4. `bash -n` all three scripts. Re-run the harness: **`17 passed, 0 failed`**.
- [ ] **Task 5 — break-checks.** Each is a deliberate wrong edit, run and reverted. Paste the output of each into the PR.
  1. Restore `_hook_common.sh` alone to seed (`git show "a54b09a9:.claude/hooks/_hook_common.sh" > …`). Measured on the prototype: exactly `test_gate_refuses_loudly_on_a_nonexistent_override`, `test_gate_refuses_loudly_on_an_override_that_is_not_a_root` and `test_edit_hook_refuses_loudly_on_a_nonexistent_override` fail (`14 passed, 3 failed`).
  2. Replace the `COMMIT_RE` test with the seed's `case "$CMD" in *"git commit"*) ;; *) exit 0 ;; esac`. The five `test_git_*`/`test_cd_*` cases fail.
  3. Delete the canonical-path `*)` arm in `run-affected-tests.sh`'s `/*)` case, so it exits 0 as seed did. `test_edit_hook_refuses_loudly_on_a_file_outside_the_override` fails.
- [ ] **Task 6 — CI, CLAUDE.md and live proof.**
  - Add the `hook-tests` job to `lint.yml` (Appendix B.2) with the Edit tool (constraint 6).
  - CLAUDE.md, anchored edits (`assert count == 1` on each old string):
    - (i) `:68`, "`PreToolUse` on `Bash(git commit*)` gates commits" → "`PreToolUse` on `Bash(git *)` (the script itself decides which git commands are commits, including `git -C <dir> commit`) gates commits".
    - (ii) `:64`, "and a leading `cd <dir> &&` is parsed for the same anchor; any other directory-changing prefix before `git commit`" → "and a leading `cd <dir> &&` or `git -C <dir>` is parsed for the same anchor; any other directory- or repository-changing form (`cd` elsewhere, `pushd`, `--git-dir`, `--work-tree`) before `commit`".
    - (iii) Append to the same bullet: "A `CLAUDE_HOOK_REPO_ROOT` that is not a worktree root, or that does not contain the edited file, is refused with a note naming it rather than passed silently (#279); `.claude/hooks/tests/test_hooks.sh` tests both hooks directly and runs in `lint.yml`."
  - **After merge**, in a scratch worktree off the new `main`, stage a one-line change to a file under `apps/epg/` and run `git -C <scratch> commit --dry-run -m probe` from a different cwd. The live gate must fire: its note or test run appears. `--dry-run` commits nothing. Record the result on the PR, then delete the scratch worktree.

**Tests added** (all new, in `test_hooks.sh`; none changed or removed):

| name | issue |
|---|---|
| `test_git_dash_C_commit_is_gated_on_the_named_tree` | #278 |
| `test_git_dash_C_with_dash_c_options_is_gated` | #278 |
| `test_git_dash_C_add_and_commit_in_one_call_is_blocked` | #278 |
| `test_cd_then_git_dash_C_commit_is_refused_as_undetermined` | #278 |
| `test_git_dir_commit_is_refused_as_undetermined` | #278 |
| `test_gate_refuses_loudly_on_a_nonexistent_override` | #279 |
| `test_gate_refuses_loudly_on_an_override_that_is_not_a_root` | #279 |
| `test_edit_hook_refuses_loudly_on_a_nonexistent_override` | #279 |
| `test_edit_hook_refuses_loudly_on_a_file_outside_the_override` | #279 |

It also adds eight `control_*` cases, which pin today's behaviour: the plain form, the `cd &&` form, non-commit git, non-git, a valid override, and three edit-hook quiet cases.

**Ledger/matrix/metrics** none (neither issue has a `defects.yml` row).

**PR description draft**

> Closes #278, closes #279.
>
> **#278.** `git -C <dir> commit` matched neither `settings.json`'s `Bash(git commit*)` nor the gate's literal `"git commit"`, so it committed with no tests at all. The filter is now `Bash(git *)`, which the hook docs say is checked per subcommand and runs the hook when a command can't be parsed. The script decides by regex: `git`, any global options, then `commit`. `git -C <dir> commit` is anchored on `<dir>` exactly as #258 anchors `cd <dir> &&`. Other directory or repository changes get the existing "cannot determine" note. Stage-and-commit in one call is refused for the `-C` spelling too.
>
> **#279.** A `CLAUDE_HOOK_REPO_ROOT` that isn't a worktree root used to fail the caller's `cd` and exit 0 silently. So did an edited file outside a valid override. Both now produce a note naming the variable. A file in no repo at all stays quiet.
>
> **Tested directly, not through the live hooks** (which run from the main checkout). New `.claude/hooks/tests/test_hooks.sh`, run in `lint.yml`: <paste 17/17>. On the seed hooks it gives <paste 8 passed, 9 failed>. Break-checks: <paste three>. After merge: <dry-run probe>.

### PR G-2 — Node 24 actions everywhere

- **Branch** `fix/G-2-node24-actions`
- **Closes** #16
- **Files** `.github/workflows/{e2e-tests,lifecycle-tests,backend-tests,go-tests,frontend-tests,lint,metrics}.yml` (22 sites; header table)
- **Test labels** none
- **upstreamable** no

**Assumption A1.** The ruling says "bump the Node 20 actions". The issue body names only `e2e-tests.yml`, but the other 16 sites emit the same deprecation. Leaving them would leave the warning in six workflows. The plan does all 22.

- [ ] **Task 1 — resolve.** For each of the three actions: `gh api repos/actions/<name>/releases/latest --jq .tag_name`, then `gh api repos/actions/<name>/commits/<tag> --jq .sha`. Confirm `gh api "repos/actions/<name>/contents/action.yml?ref=<sha>" --jq .content | base64 -d | grep using:` says `node24`. If the result differs from finding 4's SHAs, use yours and say so in the PR.
- [ ] **Task 2 — edit.** Replace each old `uses:` line with the Edit tool, `replace_all` per file, so the zizmor hook fires on each file. The version comment changes with the SHA. Afterwards, `grep -rn -E 'ea165f8d65b6e75b540449e92b4886f43607fa02|49933ea5288caeca8642d1e84afbd3f7d6820020|d3f86a106a0bac45b974a628896c90dbdf5c8093' .github/workflows/` must print nothing (exit 1). No `with:` block changes (finding 4 checked every one).
- [ ] **Task 3 — break-check.** Revert one site to a hand-typed SHA one character off. The zizmor hook (online `impostor-commit` audit) must reject it. Restore.
- [ ] **Task 4 — prove on runs.** Push, then dispatch each workflow on the branch so every edited job actually runs:
  - `gh workflow run e2e-tests.yml --ref <branch> -f full=true`
  - `gh workflow run lifecycle-tests.yml --ref <branch> -f full=true`
  - `gh workflow run backend-tests.yml --ref <branch> -f full_suite=true`
  - `gh workflow run go-tests.yml --ref <branch>`
  - frontend-tests and lint run on the PR.
  - For each completed run: `set -o pipefail; gh run view <id> --log | grep -c 'Node.js 20 is deprecated'` must print `0` (exit 1).
  - **Not provable before merge: `metrics.yml`.** It triggers on push to `main`, schedule and dispatch, and its job writes to `metrics-data` (`contents: write`). Dispatching it from a branch would push a coverage row. Check its first `main` run after merge instead, and note that in the PR.

**PR description draft**

> Closes #16. `upload-artifact` v4.6.2 → v7.0.1, `download-artifact` v4.3.0 → v8.0.1 and `setup-node` v4.4.0 → v7.0.0 at all 22 sites in seven workflows. The issue named one workflow; the same three pins emitted the same warning in six more. The SHAs are tool-resolved and are the ones the gh-aw lock files already pin. No `with:` changes were needed: no `artifact-ids`, no `packageManager` fields, no `archive:`. zizmor stays at zero findings. Deprecation-warning counts per dispatched run: <paste>. `metrics.yml` is verified on its first `main` run.

### PR G-3 — vuln-scan goes green and stays blocking

- **Branch** `fix/G-3-vuln-scan-green`
- **Closes** #277 (the red gate). G-9 removes the accepted risk this PR records.
- **Files** `frontend/package-lock.json`, `.github/workflows/vuln-scan.yml`
- **Test labels** frontend suite (the lockfile)
- **upstreamable** no
- **Under Q1's alternative ("migration only")** this PR keeps only the lockfile half. Grype then stays red until G-9.

- [ ] **Task 1 — OSV.** `cd <wt>/frontend && npm update @xmldom/xmldom --package-lock-only --ignore-scripts`. `git diff --stat` must show `frontend/package-lock.json` alone, and the hunk must be exactly the `version`/`resolved`/`integrity` triple at `:2575-2577`, going to `0.8.15`. Anything wider is a STOP. Run the frontend suite (`npm ci && npm test`).
- [ ] **Task 2 — OSV, measured locally with the workflow's own pin.** From `<wt>`, run the exact command at `vuln-scan.yml:112-115` with `$PWD` as the worktree, then the `:116-149` script. Expected: `Highest CVSS across OSV findings: 5.7` and exit 0. That was measured on a scratch copy, where the remaining findings were `@humanfs/node` 5.7 and `djangorestframework` 5.3/4.3.
- [ ] **Task 3 — Grype accepted risk.** Apply Appendix C to the `grype` job: a step that writes the rules file, a step that refuses an expired or undated rule, and `--config` on the blocking step only. The informational step is unchanged, so both CVEs keep printing in every run's log.
- [ ] **Task 4 — measure Grype locally with the pin.** `docker run --rm -v "<rules file>:/grype.yaml:ro" anchore/grype@sha256:ddf9e9f204049f3a4a0955ef70873cabab6a31432125ad4f20a490b54950a253 ghcr.io/d10scot/dispatcharr:<tag> --platform linux/amd64 --config /grype.yaml --fail-on high --only-fixed -o table`, for `base` and `latest`. **Expected: exit 0 on both.** Measured 2026-09-23 with rules of this shape.
- [ ] **Task 5 — break-checks.**
  1. The same command without `--config` exits **2**, listing the two ffmpeg rows.
  2. Set one rule's `EXPIRES` to `2026-09-01` and run the expiry step's script locally (`RUNNER_TEMP=<dir> bash -c '<the step body>'`). It exits 1 naming the rule.
  3. Delete one `EXPIRES`. It exits 1 ("every rule needs an EXPIRES date").
  Restore each.
- [ ] **Task 6 — the PR's own run.** `vuln-scan.yml` triggers on a PR that changes itself or `frontend/package-lock.json` (`:45-50`). All five jobs must be green on the PR, and must stay blocking: no `|| true` added to a blocking step, no `continue-on-error`. Grep the diff for both. After merge, one `gh workflow run vuln-scan.yml --ref main` must go green.

**PR description draft**

> Closes #277. The gate is green again and still blocking.
>
> **OSV-Scanner:** `@xmldom/xmldom` 0.8.13 → 0.8.15, lockfile only. It was eight CVSS 8.7 advisories, reached through `mpd-parser`. The worst finding is now 5.7.
>
> **Grype:** the only High rows on either image are two ffmpeg 8.1.2 binary CVEs (CFHD, DVB-sub). FFmpeg fixed both in n8.1.3. linuxserver never published 8.1.3, and its fixed 9.0 image is an Ubuntu 26.04 platform move. This PR records them as **accepted risk until 2026-10-31**, scoped to `ffmpeg 8.1.2 binary`. The reason sits in the rule, and a step fails the job once the date passes. Everything else still blocks, and the informational step still prints both CVEs. The 9.0 migration that deletes the rules is PR G-9. Local measurements: <paste 2.0/2.1/break-checks>.

### PR G-4 — the base image gains `git`, and ffmpeg runs without the entrypoint

- **Branch** `migration/G-4-base-git-and-ldconfig` (touches `docker/`)
- **Closes** #226. **Refs** #254, which G-5 closes.
- **Files** `docker/DispatcharrBase`, `.github/workflows/go-tests.yml` (one guard step), `metrics/curated/defects.yml`
- **Test labels** none. The evidence is the local build, plus `base-image.yml`'s PR build of both arches.
- **upstreamable** no (hand-offer the ld.so.conf hunk upstream)

- [ ] **Task 0 — land the guard with the cause.** In `go-tests.yml`'s `build` job, add a step immediately after `Checkout code` (after `:179`). It must be harmless whether or not the image has git:
  ```yaml
      - name: Trust the workspace for git
        # The base image gains git (#254); a container job runs as root against a
        # checkout owned by another uid, and a raw git call (Go's VCS stamping in
        # `go build`) is refused as "dubious ownership" without this. A no-op on
        # an image without git.
        run: if command -v git >/dev/null; then git config --global --add safe.directory "$GITHUB_WORKSPACE"; fi
  ```
- [ ] **Task 1 — edit `DispatcharrBase`** (Appendix D.1): add `git` to the final stage's apt list at `:141-146`, and add the ld.so.conf + `ldconfig` + `ffmpeg -version` assertion as the last `RUN` before `ENTRYPOINT` (`:178`).
- [ ] **Task 2 — build natively and prove it** (constraint 9). `cd <wt> && docker build -f docker/DispatcharrBase -t dispatcharr-base:g4 .`, then:
  - `docker run --rm --entrypoint sh dispatcharr-base:g4 -c 'ffmpeg -version | head -1; git --version; ldd /usr/local/bin/comskip | grep -E "avformat|rist|fontconfig"'`. Expected: ffmpeg 8.1.2, a git version, and comskip still on `/usr/lib/<multiarch>/` for all three.
  - Build an AIO on it (`docker build -f docker/Dockerfile --build-arg BASE_IMAGE=dispatcharr-base:g4 -t dispatcharr-e2e-g4:local .`) and bring it up with `DISPATCHARR_E2E_IMAGE=dispatcharr-e2e-g4:local` plus the stack-scoping variables `scripts/e2e_up.sh:27-53` reads. Never touch the shared stack.
  - Run the `streaming` and `dvr` Playwright projects against it; they spawn ffmpeg, VLC and comskip. Paste results.
- [ ] **Task 3 — break-check.** Remove the ld.so.conf line and rebuild natively on arm64. The build must fail at the `ffmpeg -version` step with the librist symbol error. Restore. On an amd64 host this break-check cannot redden (finding 2), so say which host you ran it on.
- [ ] **Task 4 — ledger** (second commit, constraint 8). In `defects.yml:31`, set `status: fixed, fixed_in: <PR>, status_changed: <merge date>`. Validate with `python -m metrics.build --validate-only --curated metrics/curated`.
- [ ] **Task 5 — after merge.**
  - Wait for `base-image.yml` on `main` to finish. `docker buildx imagetools inspect ghcr.io/d10scot/dispatcharr:base` must show the new digest.
  - Run `docker run --rm --platform linux/arm64 --entrypoint ffmpeg ghcr.io/d10scot/dispatcharr:base -version | head -1` and `--entrypoint git … --version`.
  - Then `gh workflow run ci.yml --ref main`, so `:latest` is rebuilt on the new base. `docker-build.yml` on the merge commit resolved the *old* `:base` at its start, and `ci.yml` has `workflow_dispatch`. Only then open G-5.

**PR description draft**

> Closes #226, refs #254. #226 was arm64-only: `aarch64-linux-gnu.conf` sorts before `libc.conf`, so the distro librist 4.3.1 beat `/usr/local/lib`'s 4.11. amd64's `x86_64-linux-gnu.conf` sorts after it, which is why CI never saw it. A `00-usr-local-lib.conf` + `ldconfig` fixes arm64 and changes nothing on amd64. A build-time `ffmpeg -version`, run without `LD_LIBRARY_PATH`, fails the image build on either arch if it regresses. The base also gains `git` (#254), and go-tests' container job trusts its workspace first, so Go's VCS stamping isn't refused. CI cannot test a base PR before merge, so the local build, AIO boot and Playwright results are pasted below: <paste>.

### PR G-5 — drop the runtime `git` installs

- **Branch** `fix/G-5-drop-runtime-git-installs`
- **Closes** #254
- **Precondition** G-4 merged and `:base` republished (G-4 Task 5). `docker run --rm --entrypoint git ghcr.io/d10scot/dispatcharr:base --version` succeeds. If it fails, STOP: removing the steps now takes down `Backend result`, which is required.
- **Files** `.github/workflows/backend-tests.yml` (`:258-262`), `.github/workflows/metrics.yml` (`:150-158`)
- **upstreamable** no

- [ ] **Task 1.** Delete the `Install git` step in each, plus the comment block above metrics.yml's. Keep `backend-tests.yml:300`'s and `metrics.yml:202`'s `safe.directory` lines: they are still needed.
- [ ] **Task 2 — prove.** `gh workflow run backend-tests.yml --ref <branch> -f full_suite=true`. The `Coverage gate` job's "Refuse a floor edited downward" step must run `git fetch` successfully, with no `git: command not found`. Metrics is checked on its first `main` run.
- [ ] **Break-check.** Point the `coverage-gate` job's `image:` at a digest of the pre-G-4 base, on a scratch branch that is never merged. The floor step must die with exit 127. Discard the branch.

**PR description draft**

> Closes #254. `git` now ships in `:base` (G-4), so neither `backend-tests.yml`'s coverage gate nor `metrics.yml` reaches an Ubuntu mirror at runtime. A bad mirror can no longer fail `Backend result`. Proof run: <link>.

### PR G-6 — nginx rendered from a pristine template on every boot

- **Branch** `migration/G-6-nginx-render-each-boot`
- **Closes** #180. **Refs** #81 (a comment).
- **Files** `docker/Dockerfile`, `docker/init/03-init-dispatcharr.sh`, `docker/nginx.conf` (comment only), `docker/tests/test-puid-pgid.sh`
- **Test labels** none. The lifecycle `suites` job runs in full on `migration/**`.
- **upstreamable** no

- [ ] **Task 1 — the scenario first, red.** Add `test_nginx_rerendered_on_restart` (Appendix E.3) and register `nginx_rerendered_on_restart` in `SCENARIOS` after `restart_idempotent`. Build the seed image and run `bash docker/tests/test-puid-pgid.sh nginx_rerendered_on_restart`. **Expected: fail**, with "trust token not re-derived after /data/jwt rotation".
- [ ] **Task 2 — the fix.** Apply Appendix E.1 (Dockerfile: one `COPY` after `:64`; `:64` itself stays) and E.2 (03-init renders at the top of the nginx block; the `:133-139` comment is rewritten). Re-run the scenario: pass. Re-run `restart_idempotent`, `custom_port`, `readonly_rootfs` and `modular_mode`; they must be unchanged. `readonly_rootfs` skips today and must still skip, not fail.
- [ ] **Task 3 — break-check.** Keep the template `COPY` but delete the render (`cp`) line. The scenario fails again. Restore.
- [ ] **Task 4 — the #81 comment.** Above `nginx.conf:69`, add:
  ```nginx
  # proxy_set_header applies only to the proxy_pass locations below (/ws/ and
  # the relay_go ones), none of which builds absolute URLs. The uwsgi_pass
  # locations deliberately get no X-Forwarded-* of nginx's own: uwsgi_params
  # forwards the client's -- or an outer proxy's -- and core/utils.py's
  # get_host_and_port falls back to Host, which is what keeps a Docker port
  # remap and an outer TLS proxy both correct (#81).
  ```
  The e2e `nginx-stream-buffering` spec parses this file. Run `streaming-greybox` locally to confirm a comment does not disturb its parser.

**PR description draft**

> Closes #180. `/etc/nginx/sites-enabled/default` is now rendered from `/usr/share/dispatcharr/nginx.conf.template` on every boot, instead of `sed -i`'d once. A `docker restart` after a `/data/jwt` rotation therefore carries the new relay trust token, where it used to keep the old one and fall through to inline authorization. New lifecycle scenario `nginx_rerendered_on_restart`: red on the seed, green here. Break-check: <paste>. Also a comment at `nginx.conf:69` recording why the `uwsgi_pass` locations get no `X-Forwarded-*` of nginx's own (#81).

### PR G-7 — `get_host_and_port`'s documented behaviour, pinned

- **Branch** `fix/G-7-forwarded-headers-documented`
- **Closes** #81 (under Q2's default)
- **Files** `core/utils.py` (`:1000-1012`, docstring and comments only), `core/tests/test_core.py` (new class `GetHostAndPortDeploymentShapeTests`)
- **Test labels** `core.tests`
- **upstreamable** yes

- [ ] **Task 1 — tests.** Add three tests with `RequestFactory`, no DB. They pass on the seed: they are guards against the naive fix, not a defect pin. Rule 4 does not apply, because nothing existing changes.
  - `test_a_direct_client_on_a_remapped_port_keeps_its_own_host_and_port`: `HTTP_HOST="internaltest:1234"`, `SERVER_PORT="9191"`, no forwarded headers. `build_absolute_uri_with_port(req, "/x")` must return `http://internaltest:1234/x`.
  - `test_an_outer_tls_proxys_forwarded_proto_and_host_win`: `HTTP_HOST="dispatcharr:9191"`, `HTTP_X_FORWARDED_PROTO="https"`, `HTTP_X_FORWARDED_HOST="tv.example.com"`. It must return `https://tv.example.com/x`.
  - `test_a_forwarded_host_without_port_takes_the_forwarded_port`: `HTTP_X_FORWARDED_HOST="tv.example.com"`, `HTTP_X_FORWARDED_PORT="8443"`, `HTTP_X_FORWARDED_PROTO="https"`. It must return `https://tv.example.com:8443/x`.
- [ ] **Task 2 — break-checks.**
  1. Change `:1012` to read `request.META.get("HTTP_X_FORWARDED_HOST_DISABLED")`, so branch 1 goes dead. The outer-proxy and forwarded-port tests fail.
  2. Model the naive nginx fix in the first test by adding `HTTP_X_FORWARDED_HOST="internaltest:9191"` (what `$host:$server_port` would send). It fails with `:9191`. That shows exactly the regression the two e2e pins would also catch.
  Restore both.
- [ ] **Task 3 — docstring.** Replace "Prefers X-Forwarded-Host/X-Forwarded-Port (nginx)." (`:1003`) with "Prefers X-Forwarded-Host/X-Forwarded-Port when a client or an outer reverse proxy sends them; this image's nginx forwards them unchanged on uwsgi_pass locations and sets none of its own (#81)." Replace `# 1. Try X-Forwarded-Host (may include port) - set by our nginx` (`:1011`) with `# 1. Try X-Forwarded-Host (may include port) - from an outer proxy, never our nginx`.

**PR description draft**

> Closes #81. The report assumed nginx was meant to supply `X-Forwarded-*` on `uwsgi_pass` locations. It isn't, and supplying them would break things. `uwsgi_params` already forwards an outer proxy's headers, so TLS-terminating proxies get `https` URLs today. A direct client on a Docker port remap gets its own `Host`, which two e2e specs pin. nginx's `$host:$server_port` would give both of them the wrong answer. So this PR fixes the docstring that said "set by our nginx", and pins the three shapes in `core.tests`, so the tempting fix fails a test. The nginx comment is in G-6.

### PR G-8 — the "no TS sync" warning escapes its snippet

- **Branch** `fix/G-8-timeshift-log-repr`
- **Closes** #183
- **Files** `apps/timeshift/views.py` (`:3256-3264`), `apps/timeshift/tests/test_views.py`
- **Test labels** `apps.timeshift.tests`
- **upstreamable** yes

- [ ] **Task 1 — test, red.** In `StreamFromProviderStatusMappingTests` (`:134`), beside `test_php_error_200_cascades_to_next_candidate` (`:417`), add `test_a_non_ts_body_is_logged_without_raw_control_bytes`. It uses the same `_fake_upstream`/`raw.read` setup as `:420-429`, with body `b"\x00\x1b[31m<b>Warning</b>\r\n\x07tail"` followed by a TS candidate. Wrap the call in `self.assertLogs(views.logger, "WARNING") as cm`. Take the "no TS sync" record and assert two things: `not any(ord(c) < 32 for c in msg)`, and `"\\x1b" in msg`. It must fail on the seed.
- [ ] **Task 2 — fix** (Appendix F). `snippet = repr(peek[:120]) if peek else "(empty)"`, and log `snippet` as is. Drop the `.replace("\n", " ")[:120]`, because `repr` already escapes and already truncates at 120 bytes of input. Keep the `# credential-logging: ignore - …` marker on the `logger.warning(` line, so `scripts/check_credential_logging.py` still clears it.
- [ ] **Task 3 — break-check.** Restore the seed `decode(..., errors="replace")` line. The test fails on `\x1b`. Restore.
- [ ] Run `apps.timeshift.tests` in your own container (constraint 5), whole label, Redis flushed first. A log line in a Gate 2 module is not relevant here: `apps/timeshift/views.py` is not in `scripts/coverage_live_path.coveragerc`'s nine modules. Check with `grep -c timeshift scripts/coverage_live_path.coveragerc`, which should print `0`.

**PR description draft**

> Closes #183. The "no TS sync" warning decoded the peeked body with `errors="replace"` and stripped only `\n`, so NUL, ESC and BEL reached the log. The test label's output then read as a binary file to `grep`. The warning now logs `repr()` of the first 120 bytes. New test: `test_a_non_ts_body_is_logged_without_raw_control_bytes` (red on the seed, green here).

### PR G-9 — ffmpeg 9.0 on Ubuntu 26.04 (removes the accepted risk)

- **Branch** `migration/G-9-ffmpeg-9-base`
- **Refs** #277 (completes it). The lead may file a tracking issue for it, since G-3 closes #277.
- **Files** `docker/DispatcharrBase` (`:7`, `:115`, comments), `.github/workflows/vuln-scan.yml` (delete the two rules), `.github/workflows/go-tests.yml` (comments `:62`, `:146`, `:154`), `CLAUDE.md` (`:63`, `:135`)
- **Size** L. **upstreamable** no.
- **Measured facts it rests on** (2026-09-23):
  - `lscr.io/linuxserver/ffmpeg:version-9.0-cli` = `sha256:1e21ed2f3ebf2a17d654cf96e5bb7f7e7cd4b282796cc3490043683194e59cdf`. Re-resolve it (constraint 7).
  - Its OS is 26.04 `resolute`.
  - deadsnakes `resolute` publishes `python3.13`, `resolute-pgdg` publishes `postgresql-17`, and `packages.redis.io` serves `resolute`.
  - A `-c copy` remux on 9.0 prints `frame= … speed=1.54x`, so `relay/ffmpeg/progress.go:40`'s `frame=` gate still sees progress. That keeps parity-matrix row 4 alive.
  - `/usr/local/lib/x86_64-linux-gnu/dri` exists in 9.0, as `docker/entrypoint.sh:101` assumes.
  - 9.0's librist is 4.12.1.
- **Unknown:** why upstream pinned back from 9.0 (`fd413f0c`, 2026-08-19, "compatibility with the current environment"; no issue or PR records it). Treat every runtime surface as suspect until measured.

- [ ] **Task 1.** Resolve the 9.0 digest and edit both `FROM`s. Keep `python3.13`: E's #128 rests on it.
- [ ] **Task 2 — native build.** `docker build -f docker/DispatcharrBase -t dispatcharr-base:g9 .`. The most likely break is the comskip compile against resolute's libav (the `sed` at `:92-97` and the `LDFLAGS` at `:103`). The comments at `:69-76` were written for 26.04, so it may build clean. If it fails, STOP and report the compiler output. Do not patch comskip beyond what `:69-76` already anticipates without a ruling. G-4's `ffmpeg -version` assertion must pass.
- [ ] **Task 3 — runtime, locally** (constraint 9).
  - (a) Go row 4's real-ffmpeg pin in a throwaway image `FROM dispatcharr-base:g9` with `COPY --from=golang:<go.mod's version> /usr/local/go /usr/local/go`: `go test -race -run Real ./channel/`, with `CI=1` so it cannot skip (`relay/channel/source_transcode_real_test.go:24-30`).
  - (b) AIO on the new base, as in G-4 Task 2. Run the `streaming`, `streaming-failover`, `streaming-split` and `dvr` projects, plus `lifecycle` `restart-persistence`.
  - (c) Backend `apps.channels.tests`, `apps.proxy.tests` and `apps.timeshift.tests` inside a container of that AIO.
  - (d) The four blocking scanner invocations from `vuln-scan.yml`, with the pinned digests and `-v /var/run/docker.sock:/var/run/docker.sock`, against `dispatcharr-base:g9` and the AIO, **without** the rules file. All must exit 0. Paste every result.
- [ ] **Task 4.** Delete both rules from the rules-file step. Keep the step and the expiry check with an empty list (`ignore: []`), so the next accepted risk has a home. Update the prose: CLAUDE.md `:63` "the production ffmpeg (8.1.2, `docker/DispatcharrBase`)" becomes 9.0, and so do `:135`'s "production ffmpeg (8.1.2)" and go-tests.yml's three comments. The relay's captured corpus stays labelled 8.1.2 (`relay/internal/relaytest/corpus.go:23`, `CAPTURE.md`), because it is a verbatim historical capture.
- [ ] **Task 5 — break-check.** Scan the published 8.1.2 `:base` with the emptied rules file: exit 2. That shows removing the rules is only safe on the new base.
- [ ] **Task 6 — after merge.** Wait for `base-image.yml`, dispatch `ci.yml` (G-4 Task 5's reason), then dispatch `vuln-scan.yml`: green. Watch the next scheduled go-tests `build` run for row 4.

**PR description draft**

> Refs #277. The base image moves to linuxserver ffmpeg 9.0 (Ubuntu 26.04), the only published build carrying the CFHD and DVB-sub fixes. G-3 accepted those two CVEs until 2026-10-31. This PR deletes the two accepted-risk rules. Upstream pinned back from 9.0 on 2026-08-19 without a recorded reason, so every runtime surface was re-measured locally before merge: <paste Task 3 a-d>. Python stays 3.13.

---

## Decision memos

None. The user ruled #16 and #277 to be implementation sections (rulings, Q5), and parked #133.

---

## Coverage table

| # | disposition | PR section |
|---|---|---|
| 279 | planned | G-1 |
| 278 | planned | G-1 |
| 277 | planned | G-3 (closes: green and blocking), G-9 (removes the accepted risk) |
| 254 | planned | G-4 (git in base) + G-5 (closes: runtime installs removed) |
| 226 | planned | G-4 (closes; ledger row `:31` → fixed) |
| 16 | planned | G-2 (all 22 sites; assumption A1) |
| 180 | planned | G-6 |
| 81 | planned | G-7 (closes under Q2's default) + G-6 (nginx comment) |
| 183 | planned | G-8 |
| 133 | **parked by user** | — |

Duplicates: none found in this category.

---

## Open questions (for the user)

- **Q1 — #277's Grype half: accepted risk now, migration later?**
  - **Default (planned): both.** G-3 accepts CVE-2026-70632/-70628 on ffmpeg 8.1.2 until 2026-10-31 with an enforced expiry. G-9 migrates to 9.0/26.04 and deletes the rules.
  - **(b) Migration only.** G-3 ships just the xmldom fix, and Grype stays red until G-9 lands. G-9 is L, and nothing upstream records why the 9.0 move was reverted.
  - **(c) Stay on 8.1.2 and renew the ignore.** Not recommended: the 8.1 line on linuxserver is frozen at 8.1.2, so every future ffmpeg CVE lands here unfixable.
  - The accepted risk in plain terms: a malicious or compromised provider stream in AVI (CFHD) or WTV (DVB subtitles), probed by an FFmpeg-profile channel or a DVR recording, can corrupt heap memory in the spawned ffmpeg.
- **Q2 — #81: close with documentation and guard tests, or change nginx?**
  - **Default (planned): G-7 + a G-6 comment.** No behaviour change. Evidence: the naive `uwsgi_param` fix reddens two e2e pins and breaks outer TLS proxies.
  - **(b) Trust-gate the forwarded headers** on `DISPATCHARR_TRUSTED_PROXIES`, B-7's set. Blocks nothing an attacker cannot already do with `Host`, and costs unconfigured Traefik users their `https` URLs under B-7's loopback default.
  - **(c) The issue's `uwsgi_param` fix.** Rejected for the reasons in finding 3.

Follow-ups surfaced, not planned here:
- `go-tests.yml`'s `ffmpeg version` step runs `ffmpeg -version | head -1` under the default `bash -e` with no `pipefail`, so it would launder an unrunnable ffmpeg. The row 4 test would still fail.
- Installing Renovate, a repo-settings action, is what would have caught the frozen ffmpeg digest.
- A base-image PR is untested by CI before merge (constraint 9). A workflow that builds the PR's base and runs go-tests' `build` job on it would close that.

---

## Appendix A — hook diffs (prototyped; the harness gives 17/17 against them)

Generated with `diff -u` between a copy of the seed hooks and the prototype. The `@@` offsets are against the seed.

### A.1 `.claude/hooks/_hook_common.sh`

```diff
--- a/.claude/hooks/_hook_common.sh
+++ b/.claude/hooks/_hook_common.sh
@@ -21,7 +21,8 @@
 #   Django label / staged-path diff relative to, and returns 0.
 #
 #   CLAUDE_HOOK_REPO_ROOT always wins — the documented escape hatch for
-#   manual and test runs (see CLAUDE.md).
+#   manual and test runs (see CLAUDE.md) — but only once it is verified to
+#   be a worktree root; otherwise returns 2 with the reason on stderr.
 #
 #   Otherwise resolves `git -C <anchor-dir> rev-parse --show-toplevel`, which
 #   follows wherever <anchor-dir> actually lives: for a linked worktree, git
@@ -43,6 +44,28 @@
 hook_repo_root() {
   local anchor="${1:-.}"
   if [ -n "${CLAUDE_HOOK_REPO_ROOT:-}" ]; then
+    # Issue #279: the override used to be printed verbatim. A stale value
+    # (a deleted worktree, a typo, a subdirectory) then failed the caller's
+    # `cd` and the hook exited 0 with no output -- a silent pass. Validate it
+    # the same way the anchor is validated below, and require the override
+    # to BE a worktree root, not merely something inside one: a
+    # subdirectory would resolve, and every label derived relative to it
+    # would be wrong. Return 2 -- distinct from 1, "the anchor is in no
+    # repo", which is a legitimate nothing-to-do -- so callers can refuse
+    # loudly for this case alone.
+    local o_out o_st o_top o_want
+    o_out="$(git -C "$CLAUDE_HOOK_REPO_ROOT" rev-parse --show-toplevel 2>&1)"
+    o_st=$?
+    if [ $o_st -ne 0 ]; then
+      printf 'CLAUDE_HOOK_REPO_ROOT=%s is not a git worktree: %s\n' "$CLAUDE_HOOK_REPO_ROOT" "$o_out" >&2
+      return 2
+    fi
+    o_top="$(hook_canon_path "$o_out")"
+    o_want="$(hook_canon_path "$CLAUDE_HOOK_REPO_ROOT")"
+    if [ -z "$o_top" ] || [ "$o_top" != "$o_want" ]; then
+      printf 'CLAUDE_HOOK_REPO_ROOT=%s is inside the worktree %s but is not its root\n' "$CLAUDE_HOOK_REPO_ROOT" "$o_out" >&2
+      return 2
+    fi
     printf '%s\n' "$CLAUDE_HOOK_REPO_ROOT"
     return 0
   fi
```

### A.2 `.claude/hooks/pre-commit-tests.sh`

```diff
--- a/.claude/hooks/pre-commit-tests.sh
+++ b/.claude/hooks/pre-commit-tests.sh
@@ -21,12 +21,44 @@
 CONTAINER="${DISPATCHARR_TEST_CONTAINER:-dispatcharr-testrunner}"
 
 CD_ANCHOR=""
+# gate_note_exit <message>: say it in the PreToolUse JSON shape the rest of
+# this script uses for warnings, then let the command through. Used before
+# the WARNINGS machinery below exists.
+gate_note_exit() {
+  jq -cn --arg m "$1" '{systemMessage:$m,hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$m}}'
+  exit 0
+}
 if [ "${1:-}" = "--git-hook" ]; then
   CMD="git commit"
 else
   CMD="$(jq -r '.tool_input.command // empty')"
-  case "$CMD" in *"git commit"*) ;; *) exit 0 ;; esac
+  # Issue #278: settings.json used to filter on `Bash(git commit*)` and this
+  # line on the literal substring "git commit", so `git -C <dir> commit`
+  # matched neither and committed with no gate at all. settings.json now
+  # filters on `Bash(git *)` -- every git subcommand, and the harness runs the
+  # hook anyway on a command it cannot parse -- and this regex decides: `git`, then
+  # any global options (`-C <dir>`, `-c k=v`, `--git-dir=...`, `--no-pager`,
+  # ...), then `commit` as a whole word. `git log --grep commit` does not
+  # match: `log` is not an option.
+  GIT_GLOBAL='([[:space:]]+(-[Cc][[:space:]]+[^[:space:]]+|--(git-dir|work-tree|namespace)([[:space:]]+|=)[^[:space:]]+|--?[A-Za-z][-A-Za-z]*))*'
+  COMMIT_RE="(^|[;&|(\`[:space:]])git${GIT_GLOBAL}[[:space:]]+commit([[:space:]]|\$)"
+  [[ "$CMD" =~ $COMMIT_RE ]] || exit 0
+  # Everything up to and including the matched `git ... commit`.
+  UPTO="${CMD%%"${BASH_REMATCH[0]}"*}${BASH_REMATCH[0]}"
 
+  # A Bash call that stages and commits in one invocation (`git add x && git
+  # commit`, or the same with `git -C <dir>` on either half) cannot be seen
+  # correctly by this hook: PreToolUse fires BEFORE the command executes, so
+  # any index/working-tree inspection here reflects state from *before* the
+  # `git add` ran too — there is no script-side fix for that, only refusing
+  # to guess. Checked before the directory forms below, because it is
+  # refused whichever tree the commit lands in.
+  ADD_RE="(^|[;&|(\`[:space:]])git${GIT_GLOBAL}[[:space:]]+add([[:space:]]|\$)"
+  if [[ "$CMD" == *"git add"* || "$CMD" =~ $ADD_RE ]]; then
+    printf 'COMMIT BLOCKED — this command stages files with `git add` and commits in the same Bash call. PreToolUse hooks run before the command executes, so this gate cannot see what gets staged and would silently skip verification.\n\nRun `git add <files>` as its own Bash call, then `git commit` as a separate call.\n' >&2
+    exit 2
+  fi
+
   # A plain `git commit` runs inside the worktree it commits to, and the cwd
   # this script inherits already IS that worktree — but PreToolUse fires
   # BEFORE the command executes, so for `cd <dir> && git commit …` the
@@ -34,21 +66,21 @@
   # the exact defect class issue #258 fixed for this script's own path,
   # relocated to the inherited cwd instead. Measured: a commit landing in a
   # tree that staged a live_proxy test derived apps.epg.tests from the stale
-  # cwd instead. Handle only the documented, anchored simple form — refuse to
-  # guess at anything more complex (multiple `cd`s, `git -C`, a `;` before the
-  # `cd`, etc.) since general shell parsing isn't safe here.
+  # cwd instead. Handle only the documented, anchored simple forms —
+  # `cd <dir> && git commit` and (#278) `git -C <dir> commit`, optionally with
+  # `-c k=v` options — and refuse to guess at anything more complex (multiple
+  # `cd`s, `--git-dir`, a `;` before the `cd`, etc.) since general shell
+  # parsing isn't safe here.
   if [[ "$CMD" =~ ^[[:space:]]*cd[[:space:]]+([^[:space:]]+)[[:space:]]*\&\&[[:space:]]*git[[:space:]]+commit ]]; then
     CD_ANCHOR="${BASH_REMATCH[1]}"
-    CD_ANCHOR="${CD_ANCHOR%\'}"; CD_ANCHOR="${CD_ANCHOR#\'}"
-    CD_ANCHOR="${CD_ANCHOR%\"}"; CD_ANCHOR="${CD_ANCHOR#\"}"
-  else
-    BEFORE_COMMIT="${CMD%%git commit*}"
-    if [[ "$BEFORE_COMMIT" == *"cd "* || "$BEFORE_COMMIT" == *"git -C "* ]]; then
-      MSG="Commit gate: this command changes directory before \`git commit\` in a form more complex than the documented \`cd <dir> && git commit\` (PreToolUse fires before the command runs, so this hook cannot safely determine which tree the commit will land in). Backend/frontend tests were NOT run for this commit."
-      jq -cn --arg m "$MSG" '{systemMessage:$m,hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$m}}'
-      exit 0
-    fi
+  elif [[ "$CMD" =~ ^[[:space:]]*git[[:space:]]+-C[[:space:]]+([^[:space:]]+)([[:space:]]+-c[[:space:]]+[^[:space:]]+)*[[:space:]]+commit([[:space:]]|$) ]]; then
+    CD_ANCHOR="${BASH_REMATCH[1]}"
+  elif [[ "$UPTO" == *"cd "* || "$UPTO" == *"pushd "* || "$UPTO" == *"-C "* \
+          || "$UPTO" == *"--git-dir"* || "$UPTO" == *"--work-tree"* ]]; then
+    gate_note_exit "Commit gate: this command changes directory or repository before \`git commit\` in a form other than the documented \`cd <dir> && git commit\` or \`git -C <dir> commit\` (PreToolUse fires before the command runs, so this hook cannot safely determine which tree the commit will land in). Backend/frontend tests were NOT run for this commit."
   fi
+  CD_ANCHOR="${CD_ANCHOR%\'}"; CD_ANCHOR="${CD_ANCHOR#\'}"
+  CD_ANCHOR="${CD_ANCHOR%\"}"; CD_ANCHOR="${CD_ANCHOR#\"}"
 fi
 
 # A `git commit` runs inside the worktree it commits to (and a native
@@ -56,25 +88,26 @@
 # the cwd this script inherits is the right anchor for the plain form — NOT
 # this script's own location, which under CLAUDE_PROJECT_DIR is the main
 # checkout regardless of which worktree is committing (issue #258). For the
-# `cd <dir> && git commit` form, CD_ANCHOR (parsed above) is used instead;
-# anything else already exited above. Resolved before any `cd` below.
-REPO_ROOT="$(hook_repo_root "${CD_ANCHOR:-.}")" || exit 0
-cd "$REPO_ROOT" || exit 0
+# two anchored forms, CD_ANCHOR (parsed above) is used instead; anything else
+# already exited above. Resolved before any `cd` below.
+#
+# Issue #279: a stale CLAUDE_HOOK_REPO_ROOT (status 2) used to end here in a
+# silent `exit 0`. It now says so; status 1 (the anchor is in no git repo at
+# all) stays quiet, because there is nothing to gate.
+RR_ERR_FILE="$(mktemp)"
+REPO_ROOT="$(hook_repo_root "${CD_ANCHOR:-.}" 2>"$RR_ERR_FILE")"
+RR_ST=$?
+RR_ERR="$(cat "$RR_ERR_FILE")"; rm -f "$RR_ERR_FILE"
+if [ $RR_ST -eq 2 ]; then
+  gate_note_exit "Commit gate: ${RR_ERR} Tests were NOT run for this commit. Unset CLAUDE_HOOK_REPO_ROOT, or point it at a worktree root."
+elif [ $RR_ST -ne 0 ]; then
+  exit 0
+fi
+cd "$REPO_ROOT" || gate_note_exit "Commit gate: could not cd into ${REPO_ROOT}. Tests were NOT run for this commit."
 
 WARNINGS=()
 note() { WARNINGS+=("$1"); }
 
-# A Bash call that stages and commits in one invocation (`git add x && git
-# commit`) cannot be seen correctly by this hook: PreToolUse fires BEFORE the
-# command executes, so any index/working-tree inspection here reflects state
-# from *before* the `git add` ran too — there is no script-side fix for that,
-# only refusing to guess. Force the two steps apart so the gate can see what
-# is actually being committed.
-if [[ "$CMD" == *"git add"* ]]; then
-  printf 'COMMIT BLOCKED — this command stages files with `git add` and commits in the same Bash call. PreToolUse hooks run before the command executes, so this gate cannot see what gets staged and would silently skip verification.\n\nRun `git add <files>` as its own Bash call, then `git commit` as a separate call.\n' >&2
-  exit 2
-fi
-
 # `git commit -a` bypasses the index, so compare against HEAD in that case.
 case "$CMD" in
   *" -a"*|*"--all"*) PATHS="$(git diff --name-only HEAD)" ;;
```

### A.3 `.claude/hooks/run-affected-tests.sh`

```diff
--- a/.claude/hooks/run-affected-tests.sh
+++ b/.claude/hooks/run-affected-tests.sh
@@ -40,14 +40,44 @@
 [ -n "$FILE" ] || exit 0
 [ -f "$FILE" ] || exit 0
 
+# early_note <message>: the report block's JSON shape, for the two exits
+# below that happen before NOTES exists. "Could not run" exits 0 but is
+# stated loudly (header, above).
+early_note() {
+  jq -cn --arg m "$1" '{systemMessage:$m,hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$m}}'
+  exit 0
+}
+
 # REPO_ROOT is derived from the EDITED FILE's own worktree, never from this
 # script's location — see _hook_common.sh's hook_repo_root() (issue #258).
-REPO_ROOT="$(hook_repo_root "$(dirname "$FILE")")" || exit 0
-cd "$REPO_ROOT" || exit 0
+# Status 2 is a CLAUDE_HOOK_REPO_ROOT that is not a worktree root (#279):
+# that used to fall through to a silent `exit 0`. Status 1 — the edited file
+# is in no git repo at all (a scratchpad file, say) — stays quiet.
+RR_ERR_FILE="$(mktemp)"
+REPO_ROOT="$(hook_repo_root "$(dirname "$FILE")" 2>"$RR_ERR_FILE")"
+RR_ST=$?
+RR_ERR="$(cat "$RR_ERR_FILE")"; rm -f "$RR_ERR_FILE"
+case $RR_ST in
+  0) ;;
+  2) early_note "Did NOT check ${FILE}: ${RR_ERR} Unset CLAUDE_HOOK_REPO_ROOT, or point it at a worktree root. The edit was NOT verified." ;;
+  *) exit 0 ;;
+esac
+cd "$REPO_ROOT" || early_note "Did NOT check ${FILE}: could not cd into ${REPO_ROOT}. The edit was NOT verified."
 
 case "$FILE" in
   "$REPO_ROOT"/*) REL="${FILE#"$REPO_ROOT"/}" ;;
-  /*) exit 0 ;;
+  /*)
+    # Compare canonical spellings before concluding the file is elsewhere:
+    # /tmp and /private/tmp are one directory on macOS.
+    CANON_DIR="$(hook_canon_path "$(dirname "$FILE")")"
+    CANON_ROOT="$(hook_canon_path "$REPO_ROOT")"
+    case "$CANON_DIR/" in
+      "$CANON_ROOT"/*) REL="${CANON_DIR#"$CANON_ROOT"}/${FILE##*/}"; REL="${REL#/}" ;;
+      *)
+        # Only an override can put the file outside the root derived for it.
+        [ -n "${CLAUDE_HOOK_REPO_ROOT:-}" ] || exit 0
+        early_note "Did NOT check ${FILE}: it is outside CLAUDE_HOOK_REPO_ROOT=${CLAUDE_HOOK_REPO_ROOT}. Unset the variable, or point it at the worktree being edited. The edit was NOT verified." ;;
+    esac ;;
   *) REL="$FILE" ;;
 esac
 
```

### A.4 `.claude/settings.json`

```diff
--- a/.claude/settings.json
+++ b/.claude/settings.json
@@ -26,10 +26,10 @@
         "hooks": [
           {
             "type": "command",
-            "if": "Bash(git commit*)",
+            "if": "Bash(git *)",
             "command": "\"${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/pre-commit-tests.sh\"",
             "timeout": 600,
-            "statusMessage": "Running tests for the staged changes"
+            "statusMessage": "Commit gate: checking the git command"
           }
         ]
       }
```

## Appendix B — `.claude/hooks/tests/test_hooks.sh` and its CI job

### B.1 the harness (verbatim; the prototype ran from scratch with `HOOK_DIR` set)

```bash
#!/usr/bin/env bash
# Tests for the Claude Code test hooks themselves (.claude/hooks/).
#
# Runs the hook scripts DIRECTLY, with a synthetic stdin payload, against two
# throwaway git repos — never through the harness, and never against the
# live checkout. That is the point: the hooks that fire during a session are
# ${CLAUDE_PROJECT_DIR}/.claude/hooks/*, which is not necessarily the copy
# being edited, so "the hook fired and passed" proves nothing about an edit
# to a hook. Only an explicit invocation of the edited copy does.
#
# No Docker, no Django, no network. Needs bash, git, jq, python3.
#
# Probe: repo A has a staged file and no scripts/ci_backend_test_labels.py,
# so a gate that fires AND resolves its root to A reaches the label mapper,
# which fails, and says "could not map staged paths". A gate that does not
# fire, or resolves some other root (B is clean), prints nothing. So the
# presence of that sentence is the discriminator.
#
# Usage: bash .claude/hooks/tests/test_hooks.sh
#        HOOK_DIR=<dir> bash …   # test another copy of the hooks
set -uo pipefail

HOOK_DIR="${HOOK_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
GATE="$HOOK_DIR/pre-commit-tests.sh"
EDIT="$HOOK_DIR/run-affected-tests.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
A="$TMP/repo-a"; B="$TMP/repo-b"
for r in "$A" "$B"; do
  git init -q "$r"
  git -C "$r" -c user.name=t -c user.email=t@t commit -q --allow-empty -m init
done
mkdir -p "$A/sub"
printf 'x\n' > "$A/staged.txt"
git -C "$A" add staged.txt
printf 'x\n' > "$A/edited.txt"
printf "x\n" > "$TMP/not-in-a-repo.txt"

PASS=0; FAIL=0
check() {  # check <name> <want-exit> <want-substring-or-EMPTY> <exit> <output>
  local name="$1" want_st="$2" want="$3" st="$4" out="$5" ok=1
  [ "$st" = "$want_st" ] || ok=0
  if [ "$want" = EMPTY ]; then [ -z "$out" ] || ok=0
  elif [ "$want" = NONOTE ]; then [[ "$out" != *systemMessage* ]] || ok=0
  else [[ "$out" == *"$want"* ]] || ok=0; fi
  if [ $ok = 1 ]; then PASS=$((PASS+1)); printf 'ok   %s\n' "$name"
  else FAIL=$((FAIL+1)); printf 'FAIL %s\n     want exit %s and %q\n     got  exit %s and %q\n' \
    "$name" "$want_st" "$want" "$st" "$out"; fi
}
# gate <cwd> <command> [env assignments…]: run the commit gate as PreToolUse would.
gate() {
  local cwd="$1" cmd="$2"; shift 2
  ( cd "$cwd" && jq -cn --arg c "$cmd" '{tool_input:{command:$c}}' \
      | env -u CLAUDE_HOOK_REPO_ROOT DISPATCHARR_TEST_CONTAINER=hooktest-absent "$@" bash "$GATE" 2>&1 )
}
# edit <file> [env assignments…]: run the edit hook as PostToolUse would.
edit() {
  local f="$1"; shift
  ( cd "$TMP" && jq -cn --arg f "$f" '{tool_input:{file_path:$f}}' \
      | env -u CLAUDE_HOOK_REPO_ROOT DISPATCHARR_TEST_CONTAINER=hooktest-absent "$@" bash "$EDIT" 2>&1 )
}
MAPPED="could not map staged paths"

# ---- #278: git -C <dir> commit ------------------------------------------
out="$(gate "$B" "git -C $A commit -m x")"; st=$?
check "test_git_dash_C_commit_is_gated_on_the_named_tree" 0 "$MAPPED" $st "$out"
out="$(gate "$B" "git -C $A -c user.name=x commit -m x")"; st=$?
check "test_git_dash_C_with_dash_c_options_is_gated" 0 "$MAPPED" $st "$out"
out="$(gate "$B" "git -C $A add staged.txt && git -C $A commit -m x")"; st=$?
check "test_git_dash_C_add_and_commit_in_one_call_is_blocked" 2 "COMMIT BLOCKED" $st "$out"
out="$(gate "$B" "cd $B && git -C $A commit -m x")"; st=$?
check "test_cd_then_git_dash_C_commit_is_refused_as_undetermined" 0 "cannot safely determine" $st "$out"
out="$(gate "$B" "git --git-dir=$A/.git commit -m x")"; st=$?
check "test_git_dir_commit_is_refused_as_undetermined" 0 "cannot safely determine" $st "$out"
# ---- unchanged behaviour ---------------------------------------------------
out="$(gate "$A" "git commit -m x")"; st=$?
check "control_plain_commit_is_gated_on_the_cwd" 0 "$MAPPED" $st "$out"
out="$(gate "$B" "cd $A && git commit -m x")"; st=$?
check "control_cd_and_commit_is_gated_on_the_cd_target" 0 "$MAPPED" $st "$out"
out="$(gate "$B" "git -C $A log --grep commit")"; st=$?
check "control_a_non_commit_git_command_is_ignored" 0 EMPTY $st "$out"
out="$(gate "$B" "ls -la")"; st=$?
check "control_a_non_git_command_is_ignored" 0 EMPTY $st "$out"
# ---- #279: a stale CLAUDE_HOOK_REPO_ROOT ------------------------------------
out="$(gate "$A" "git commit -m x" CLAUDE_HOOK_REPO_ROOT="$TMP/deleted-worktree")"; st=$?
check "test_gate_refuses_loudly_on_a_nonexistent_override" 0 "CLAUDE_HOOK_REPO_ROOT" $st "$out"
out="$(gate "$A" "git commit -m x" CLAUDE_HOOK_REPO_ROOT="$A/sub")"; st=$?
check "test_gate_refuses_loudly_on_an_override_that_is_not_a_root" 0 "is not its root" $st "$out"
out="$(gate "$B" "git commit -m x" CLAUDE_HOOK_REPO_ROOT="$A")"; st=$?
check "control_gate_honours_a_valid_override" 0 "$MAPPED" $st "$out"
out="$(edit "$A/edited.txt" CLAUDE_HOOK_REPO_ROOT="$TMP/deleted-worktree")"; st=$?
check "test_edit_hook_refuses_loudly_on_a_nonexistent_override" 0 "CLAUDE_HOOK_REPO_ROOT" $st "$out"
out="$(edit "$A/edited.txt" CLAUDE_HOOK_REPO_ROOT="$B")"; st=$?
check "test_edit_hook_refuses_loudly_on_a_file_outside_the_override" 0 "outside CLAUDE_HOOK_REPO_ROOT" $st "$out"
out="$(edit "$A/edited.txt")"; st=$?
check "control_edit_hook_is_quiet_on_a_file_no_check_covers" 0 EMPTY $st "$out"
out="$(edit "$A/edited.txt" CLAUDE_HOOK_REPO_ROOT="$A")"; st=$?
check "control_edit_hook_is_quiet_under_a_valid_override" 0 EMPTY $st "$out"
out="$(edit "$TMP/not-in-a-repo.txt")"; st=$?
check "control_edit_hook_is_quiet_outside_any_repo" 0 NONOTE $st "$out"

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
```

### B.2 `lint.yml`, new job (append after `dashboard-tests`)

```yaml
  hook-tests:
    name: Claude Code hook tests
    # Runs the hook scripts directly against throwaway repos. The live hooks
    # run from the main checkout, so an edit to a hook is only ever tested
    # here or by hand (#278, #279).
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
        with:
          persist-credentials: false
      - name: Hook tests
        run: bash .claude/hooks/tests/test_hooks.sh
```

## Appendix C — `vuln-scan.yml`, the `grype` job

Replace `:216-226` with:

```yaml
      - name: Write the accepted-risk rules
        # Each rule names ONE finding, scoped to the exact package, version and
        # type, with a reason and an EXPIRES date that the next step enforces.
        # A rule is a decision with an end date, never a mute. The informational
        # step above is unaffected and keeps printing every accepted finding.
        run: |
          cat > "$RUNNER_TEMP/grype.yaml" <<'YAML'
          ignore:
            - vulnerability: CVE-2026-70632
              package: {name: ffmpeg, version: 8.1.2, type: binary}
              reason: >-
                EXPIRES 2026-10-31. CFHD decoder heap write. Fixed upstream in
                FFmpeg n8.1.3 (2026-09-19) and 9.0; linuxserver publishes no
                8.1.3 and its 9.0 image is an Ubuntu 26.04 move, planned as
                fixplan G-9. Reach: a provider stream in AVI probed by an
                FFmpeg-profile channel or DVR recording. #277.
            - vulnerability: CVE-2026-70628
              package: {name: ffmpeg, version: 8.1.2, type: binary}
              reason: >-
                EXPIRES 2026-10-31. DVB-subtitle parser signed overflow. Same
                fix status and plan as CVE-2026-70632. Reach: a provider stream
                in WTV. #277.
          YAML

      - name: Refuse an expired or undated accepted-risk rule
        run: |
          set -euo pipefail
          f="$RUNNER_TEMP/grype.yaml"
          rules=$(grep -c -- '- vulnerability:' "$f" || true)
          dated=$(grep -c 'EXPIRES [0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}' "$f" || true)
          if [ "$rules" != "$dated" ]; then
            echo "::error::every accepted-risk rule needs an EXPIRES date ($dated of $rules have one)"; exit 1
          fi
          today=$(date -u +%F); bad=0
          for d in $(grep -o 'EXPIRES [0-9-]*' "$f" | cut -d' ' -f2); do
            if [[ "$d" < "$today" ]]; then echo "::error::an accepted-risk rule expired on $d"; bad=1; fi
          done
          exit $bad

      - name: Grype (blocking — CRITICAL/HIGH, fixable only)
        # --fail-on high, not critical: matches the CRITICAL/HIGH policy
        # documented at the top of this file (and what Trivy's blocking
        # step above already does) — the two independent-DB blocking
        # passes should actually share a threshold, not silently diverge.
        # --config applies ONLY the rules written above, each dated.
        env:
          IMAGE_REF: ${{ steps.image.outputs.ref }}
        run: |
          # anchore/grype v0.117.0
          docker run --rm -v "$RUNNER_TEMP/grype.yaml:/grype.yaml:ro" \
            anchore/grype@sha256:ddf9e9f204049f3a4a0955ef70873cabab6a31432125ad4f20a490b54950a253 \
            "$IMAGE_REF" --config /grype.yaml --fail-on high --only-fixed -o table
```

Grype's ignore-rule fields at v0.117.0 (`grype/match/ignore.go:34-42`) are `vulnerability`, `include-aliases`, `reason`, `namespace`, `fix-state`, `package`, `vex-status`, `vex-justification` and `match-type`. There is no expiry field, hence the enforcing step. G-9 empties the list to `ignore: []`.

## Appendix D — `docker/DispatcharrBase` (G-4)

### D.1

```diff
--- a/docker/DispatcharrBase
+++ b/docker/DispatcharrBase
@@ -140,7 +140,7 @@
     && apt-get update \
     && apt-get install --no-install-recommends -y \
     python3.13 python3.13-venv libpython3.13 \
-    libpcre2-8-0 libopenblas0 procps pciutils \
+    libpcre2-8-0 libopenblas0 procps pciutils git \
     nginx libargtable2-0 \
     vlc-bin vlc-plugin-base \
     && apt-get clean && rm -rf /var/lib/apt/lists/*
@@ -175,4 +175,17 @@
 # symlink and replacing the IANA UTC zone with the host timezone.
 RUN rm -f /etc/localtime && cp -a /usr/share/zoneinfo/Etc/UTC /etc/localtime
 
+# /usr/local/lib ahead of the distro multiarch path, for every process (#226).
+# linuxserver's ffmpeg links /usr/local/lib/librist.so.4 (4.11); vlc pulls in
+# the distro's 4.3.1 through libavformat60. On arm64 aarch64-linux-gnu.conf
+# sorts before libc.conf (which lists /usr/local/lib), so the old copy won and
+# ffmpeg died on rist_peer_config_defaults_set_versioned wherever
+# docker/entrypoint.sh had not exported LD_LIBRARY_PATH -- the hook container
+# and CI's `--entrypoint ""` jobs. amd64 already sorted /usr/local/lib first.
+# comskip is unaffected: it carries DT_RPATH to the distro libs (see above).
+# The ffmpeg run fails this build if the ordering ever regresses on either arch.
+RUN printf '/usr/local/lib\n' > /etc/ld.so.conf.d/00-usr-local-lib.conf \
+    && ldconfig \
+    && ffmpeg -version > /dev/null
+
 ENTRYPOINT ["/app/docker/entrypoint.sh"]
```

## Appendix E — nginx rendering (G-6)

### E.1 `docker/Dockerfile`

```diff
--- a/docker/Dockerfile
+++ b/docker/Dockerfile
@@ -62,6 +62,10 @@
 COPY . /app
 # Copy nginx configuration
 COPY ./docker/nginx.conf /etc/nginx/sites-enabled/default
+# The pristine copy 03-init renders sites-enabled/default from on every boot
+# (#180). Outside /etc (a read-only-rootfs deployment tmpfs's it) and outside
+# /app (a dev bind mount replaces it).
+COPY ./docker/nginx.conf /usr/share/dispatcharr/nginx.conf.template
 COPY ./docker/dispatcharr_api_params.conf /etc/nginx/dispatcharr_api_params.conf
 COPY ./docker/dispatcharr_api_params_proxy.conf /etc/nginx/dispatcharr_api_params_proxy.conf
 # Fix line endings and make entrypoint scripts executable
```

### E.2 `docker/init/03-init-dispatcharr.sh`

```diff
--- a/docker/init/03-init-dispatcharr.sh
+++ b/docker/init/03-init-dispatcharr.sh
@@ -69,6 +69,12 @@
         echo "⚠️  Warning: DISPATCHARR_PORT is not a valid integer, using default port 9191"
         DISPATCHARR_PORT=9191
     fi
+    # Render from the pristine template on EVERY boot (#180). Every sed below
+    # consumes its placeholder, so templating in place kept the first boot's
+    # values across a `docker restart` -- most visibly the relay trust token
+    # after a /data/jwt rotation.
+    mkdir -p /etc/nginx/sites-enabled
+    cp /usr/share/dispatcharr/nginx.conf.template /etc/nginx/sites-enabled/default
     sed -i "s/NGINX_PORT/${DISPATCHARR_PORT}/g" /etc/nginx/sites-enabled/default
 
     # Relay upstream address (Phase 1 PR 4), sed'd exactly like
@@ -130,13 +136,8 @@
         echo "   nginx would forward an unauthorized marker and every tune would 403."
         exit 1
     fi
-    # This sed consumes the RELAY_TRUST_TOKEN placeholder on first boot: once
-    # substituted, a `docker restart` (same writable layer, no fresh copy of
-    # this file) finds no placeholder left to replace, so a later /data/jwt
-    # rotation leaves the stale, pre-rotation token in nginx. Fails safe --
-    # every hop-authorized tune then falls through to inline authorization,
-    # same as NGINX_PORT/RELAY_UPSTREAM above; re-templating from a pristine
-    # copy on every boot is a follow-up shared with those two.
+    # Re-derived on every boot, because the file was rendered fresh above:
+    # a /data/jwt rotation reaches nginx on the next restart (#180).
     sed -i "s/RELAY_TRUST_TOKEN/${RELAY_TRUST_TOKEN}/g" /etc/nginx/sites-enabled/default
 
     # Configure nginx based on IPv6 availability
```

### E.3 the scenario (in `docker/tests/test-puid-pgid.sh`, after `test_restart_idempotent`)

```bash
# A `docker restart` after a /data/jwt rotation must carry the new relay trust
# token into nginx (#180): the config is rendered from a template every boot.
test_nginx_rerendered_on_restart() {
    CURRENT_SCENARIO="nginx_rerendered_on_restart"
    section "nginx re-rendered on restart (jwt rotation)"

    local name="${TEST_PREFIX}_nginxrender"
    local vol="${name}_data"
    cleanup_scenario
    fresh_volume "$vol"
    track_container "$name"

    docker run -d --name "$name" -e DISPATCHARR_ENV=aio \
        -e PUID=1000 -e PGID=1000 -v "${vol}:/data" "$IMAGE_NAME" >/dev/null
    if ! wait_for_ready "$name"; then
        log_fail "First run failed to start"; dump_logs_on_fail "$name"; cleanup_scenario; return
    fi
    local tok1 tok2 want
    tok1=$(docker exec "$name" grep -o -m1 'HTTP_X_DISPATCHARR_AUTHORIZED "[0-9a-f]\{64\}"' /etc/nginx/sites-enabled/default)

    docker exec "$name" rm -f /data/jwt
    docker restart "$name" >/dev/null
    if ! wait_for_ready "$name"; then
        log_fail "Restart failed"; dump_logs_on_fail "$name"; cleanup_scenario; return
    fi
    tok2=$(docker exec "$name" grep -o -m1 'HTTP_X_DISPATCHARR_AUTHORIZED "[0-9a-f]\{64\}"' /etc/nginx/sites-enabled/default)
    want=$(docker exec "$name" python3 -c 'import hashlib,hmac;k=open("/data/jwt").read().strip().encode();print(hmac.new(k,b"relay-trust",hashlib.sha256).hexdigest())')

    if [ -n "$tok1" ] && [ "$tok2" = "HTTP_X_DISPATCHARR_AUTHORIZED \"${want}\"" ] && [ "$tok1" != "$tok2" ]; then
        log_pass "trust token re-derived after /data/jwt rotation"
    else
        log_fail "trust token not re-derived after /data/jwt rotation (before=${tok1:-none} after=${tok2:-none})"
    fi
    if [ "$(docker exec "$name" grep -c -E 'NGINX_PORT|RELAY_UPSTREAM|RELAY_GO_UPSTREAM|RELAY_TRUST_TOKEN' /etc/nginx/sites-enabled/default)" = "0" ]; then
        log_pass "no placeholder left unrendered"
    else
        log_fail "a placeholder survived rendering"
    fi
    dump_logs_on_fail "$name"
    cleanup_scenario
}
```

`03-init` derives the token from `DJANGO_SECRET_KEY`, which `docker/entrypoint.sh:138` reads from `/data/jwt` with CR/LF stripped. The Python `.strip()` above matches that for a `token_urlsafe` value (`:112-114`). If the entrypoint's derivation ever changes, change this line with it.

## Appendix F — `apps/timeshift/views.py` (G-8)

```diff
--- a/apps/timeshift/views.py
+++ b/apps/timeshift/views.py
@@ -3253,14 +3253,16 @@
                 winning_index = orig_idx
                 used_cached_final = cached_final
                 break
-            snippet = peek[:200].decode("utf-8", errors="replace") if peek else "(empty)"
+            # repr(), not a lossy decode: an error page can carry NUL/ESC/BEL,
+            # which made the whole log (and a test run's output) binary (#183).
+            snippet = repr(peek[:120]) if peek else "(empty)"
             logger.warning(  # credential-logging: ignore - already redacted by
                 # the local _redact_url() helper (:3621), not redact_url().
                 "Timeshift upstream returned %d but no TS sync in first %d "
                 "bytes (likely PHP error): %s, url=%s",
                 response.status_code,
                 len(peek) if peek else 0,
-                snippet.replace("\n", " ")[:120],
+                snippet,
                 _redact_url(url),
             )
             response.close()
```
