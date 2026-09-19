# Phase 2 Stage 2d-3 — the nginx flip

**Goal:** send production live traffic to the Go relay. Four nginx locations move from
`uwsgi_pass` to `proxy_pass http://relay_go`, a new `upstream relay_go` block and its boot-time
sed appear, the Go relay's dev-routes flag is set in its supervisord conf, and the five E2E
assertions that break at the flip are rewritten in the same commit so the suite is green on
both sides of it.

**Architecture:** no Python changes at all. A10.11 measured that every `relay_client` branch but
`dev` reaches nginx, so the whole Django→relay direction is a `docker/` concern. The client→relay
direction is nginx's location table. The only non-`docker/`, non-`e2e/` file this PR touches is one
new Go test file.

**Tech Stack:** nginx config, supervisord config, two shell scripts, one Dockerfile line, one Go
test file, four TypeScript test/allowlist files, two docs files. No new dependency, no migration, no
Python edit, no frontend edit, no workflow edit.

**Spec:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` § Stage 2d (the
`uwsgi_buffering`/`proxy_buffering` trap, the four locations, `upstream relay_go`, the
`dispatcharr_api_params_proxy.conf` twin, the `proxy_set_header` replace-not-merge rule and the six
server-level headers, the four-test rewrite of `nginx-stream-buffering.spec.ts`, the forged-marker
`@contract` test re-point) and deletion-list entry **3** as amended by Amendment A10 —
A10.1, A10.2, A10.7, A10.9, A10.10, A10.11, A10.12, A10.13, A10.16. Rulings below that refine or
contradict the spec land as **Amendment A13** in the same PR (A11 is 2d-1's, A12 is 2d-2's).

**Seed:** `d5be64d58940eeb4a3ad3e6af0bd2e6c1eb32410` —
`relay(phase2): 2d-1 — the boot-trap relocation (#325)`, i.e. **2d-1 merged**. Every appendix was
produced against that SHA and round-tripped there. The CI measurement and the local smoke checks
were taken one commit earlier, at `2f721bfd`, and they carry: `git diff --name-only 2f721bfd
d5be64d5 | grep -E '^(docker/|e2e/|relay/)'` is **empty**, so nothing 2d-3 flips, rewrites or
measures moved between the two. What did move is `CLAUDE.md`, the spec and
`docs/relay-parity-matrix.md`, and all three are accounted for below.

---

## THIS PLAN MUST BE RE-SEEDED BEFORE IT IS IMPLEMENTED

2d-3 runs **after 2d-1 and after 2d-2**. **2d-1 has merged** (`d5be64d5`, #325) and this plan is
seeded there; **2d-2 has not**, so Task 0 re-seeds against the tree its merge produces and stops if
it is missing. What that re-seed has to absorb is small and known, because both predecessors were
checked file by file — and the 2d-1 column below is now measured against a merged tree rather than
against a plan document:

| File 2d-3 touches | 2d-1 | 2d-2 | Consequence for this plan |
|---|---|---|---|
| `docker/**` (7 files) | not touched (its File structure says `docker/**` explicitly) | not touched (its Constraint 7 forbids it; its R10 reads `nginx.conf:62`/`:248` only as evidence) | **no drift** |
| `e2e/**` (4 files) | not touched (`e2e/**` in its "deliberately not touched") | not touched (Constraint 7; its R10 says `nginx-stream-buffering.spec.ts` is unaffected) | **no drift** |
| `relay/**` (1 new file) | not touched | not touched | **no drift** |
| `docs/relay-parity-matrix.md` | **touched** — row 9's `constants.py:122` → `:40` citation and one Notes sentence (`git diff --stat 2f721bfd d5be64d5 -- docs/relay-parity-matrix.md` → `2 +-`) | not touched (its R11 measured the four `views.py` citations as all below line 896) | **benign, and re-checked**: row 11 is still `docs/relay-parity-matrix.md:184` on the merged tree, so R7's citation still resolves. Task 0 Step 7 greps for it rather than assuming. 2d-3 edits no matrix row. |
| `e2e/COVERAGE.md` | not touched | not touched | **no drift** |
| `CLAUDE.md` | § Test hooks + § Structural constraints | § Commands + § Routing | **different sentences**, but line numbers move. Appendix F is written as verbatim-string replacement, not line-anchored hunks, for exactly this reason — 2d-2's own idiom, adopted here. |
| the spec (`…phase2-go-relay-design.md`) | Amendment A11 + four in-place corrections | Amendment A12 + three in-place corrections | **different passages**, same file. Appendix G is verbatim-string replacement for the same reason. |

So the re-seed work is re-running Task 0's greps, confirming the two verbatim-replacement scripts
still find their anchors, and `git apply --check --whitespace=error`-ing the ten diffs. If any
anchor is missing or any patch is rejected, **stop and report** — do not re-derive the edit by hand.
The two scripts were both **run** at `d5be64d5`, after 2d-1's own `CLAUDE.md` and spec edits landed:
six replacements and ten respectively, no assertion fired.

---

## Global Constraints

1. **Branch: `migration/phase2d-nginx-flip`.** The `migration/**` prefix is load-bearing: it is what
   makes `e2e-tests.yml`'s `changes` job set `full=true` (`:87`) and run every Playwright project,
   and `lifecycle-tests.yml`'s the same (`:120`). This PR's gate is the full matrix; a branch named
   anything else runs a path-gated subset and proves less.
2. **Do not edit any `*.py` file.** A10.11 measured that nothing in Python dials 5657 and that every
   `get_relay_control_base_url` branch but `dev` reaches nginx. If you believe a Python file must
   change, **stop and report** — that is a finding, not a step.
3. **Do not edit `docs/relay-parity-matrix.md`.** R7 measured why: keeping
   `output-profile-sharing.spec.ts`'s test title byte-identical is what makes row 11's pin keep
   resolving, and row 11's Notes cell already states the Go relay's no-owner-lock shape.
4. **Do not edit `metrics/curated/`.** R12 measured that no `defects.yml` row cites a path or a test
   this PR moves, and that no architecture metric moves.
5. **Do not touch `apps/proxy/live_proxy/` or delete anything.** Every deletion in stage 2d is
   2d-4's. This PR flips routing and fixes the tests that break at the flip; nothing more.
6. **`Go result` must already be a required check on the Main ruleset before this merges.** A10.1
   makes it a precondition, not a deliverable. Task 0 Step 6 re-verifies it and **stops** if it is
   absent.
7. **Every appendix is either a `git apply --check`-able diff hunk against the re-seeded tree or a
   whole new file verbatim or a verbatim-string replacement script.** Never splice by eye.
8. **Do not lower an asserted count or widen a tolerance to make a test pass.** If a rewritten
   assertion is red, the config is wrong, not the assertion.

---

## Rulings

Every ruling below was measured. Measurements were taken at `2f721bfd` and on the measurement
branch below; the appendices were produced and round-tripped at the seed, `d5be64d5`. The two are
interchangeable for everything this plan touches, because 2d-1's merge changed no file under
`docker/`, `e2e/` or `relay/` — measured, not assumed. The measurement branch is
`migration/phase2d-nginx-flip-measure` at `09bf567b057ea80d349d25330ce692a9420b4a62`
(**PR #324, draft, deleted after this plan merged** — the run URLs below outlive it), which carries
the minimal flip and nothing else: no spec rewrite, no allowlist edit, no `COVERAGE.md`, no matrix
edit. That is what makes its failure set the design input rather than a guess.

### R0 — The measurement, and the failure set

**A10.1's precondition is satisfied.** Run at the seed:

```
$ gh api repos/D10Scot/Dispatcharr/rulesets/21229979 \
    --jq '.rules[] | select(.type=="required_status_checks") | .parameters.required_status_checks[].context'
E2E result
Lifecycle result
Backend result
Frontend result
agent
safe_outputs
Go result
```

**Seven contexts, and `Go result` is among them.** A10 recorded six at `1326de3e` with `Go result`
absent; the user has since performed the repository-settings action A10.1 asked for. Task 0 Step 6
re-runs this command and stops if the list regresses.

**The full `migration/**` matrix on the minimal flip.** Runs, all on `09bf567b`:

| Workflow | Run | Result |
|---|---|---|
| E2E Tests | [35469742032](https://github.com/D10Scot/Dispatcharr/actions/runs/35469742032) | **failure** — one job |
| Lifecycle Tests | [35469742009](https://github.com/D10Scot/Dispatcharr/actions/runs/35469742009) | **success**, every job |
| Backend Tests | [35469742075](https://github.com/D10Scot/Dispatcharr/actions/runs/35469742075) | success (heavy jobs skipped — see the caveat) |
| Frontend Tests | [35469741981](https://github.com/D10Scot/Dispatcharr/actions/runs/35469741981) | success |
| Go Tests | [35469741958](https://github.com/D10Scot/Dispatcharr/actions/runs/35469741958) | success (heavy jobs skipped — see the caveat) |
| Lint | [35469741993](https://github.com/D10Scot/Dispatcharr/actions/runs/35469741993) | success |
| CI Pipeline | [35469742002](https://github.com/D10Scot/Dispatcharr/actions/runs/35469742002) | success |

E2E per job — **thirteen pass, one fails**:

```
Detect relevant changes  success      lifecycle           success
guards                   success      streaming-split     success
Build AIO image          success      pristine            success
upstream                 success      dvr                 success
seeded                   success      streaming-failover  success
frontend                 success      streaming           success
streaming-greybox        FAILURE      E2E result          failure
```

Lifecycle per job — **every one green**: `Detect relevant changes`, `Build AIO image`,
`lifecycle-extras`, `upgrade-migrations`, `tls-postgres`, `puid-pgid`, `Lifecycle result`. That last
pair is the one that could not be inferred from the AIO measurement and had to be run:
`docker/tests/test-puid-pgid.sh`'s `test_role_split` is the programme's only cross-container relay
scenario, and it is the only place `RELAY_GO_UPSTREAM` seds to a **service name** (`relay:5658`)
rather than to loopback. `docker/tests/test-tls-postgres.sh` is `tls-postgres`, also green. Both are
in this PR's own gate, not just the measurement's.

**The failure set, complete — five tests in one file family:**

| # | Project | File:line | Test | Message |
|---|---|---|---|---|
| 1 | streaming-greybox | `nginx-stream-buffering.spec.ts:167` | `every relay-bound location keeps uwsgi_buffering off` | `location block "location ^~ /proxy/ts/stream/ {" does not set uwsgi_buffering off` |
| 2 | streaming-greybox | `nginx-stream-buffering.spec.ts:230` | `every relay-bound location authorizes through the hop` | `location "location ^~ /proxy/ts/stream/ {" captures but does not forward HTTP_X_RELAY_CHANNEL` |
| 3 | streaming-greybox | `nginx-stream-buffering.spec.ts:313` | `every location outside the hop blanks the trust params` | `location "location ^~ /proxy/relay/ {" does not include the blanking params` |
| 4 | streaming-greybox | `nginx-stream-buffering.spec.ts:387` | `the relay control API is routed to the relay and gated by no nginx-level authorizer` | `the relay control API must reach the relay` |
| 5 | streaming-greybox | `output-profile-sharing.spec.ts:47` | `two clients on one output profile share a single transcode` | `expect(received).toHaveLength(expected)` — `Expected length: 1  Received: 0  Received array: []` |

**That is exactly the set § Stage 2d and A10.10 predicted, and nothing else.** The same five, with
the same messages, reproduced locally against a hand-built flipped container
(`plan2d3-e2e`, port 9291) running the `streaming` and `streaming-greybox` projects:
`5 failed, 64 passed (32.4s)`.

**Three things the measurement establishes that were open questions:**

- **All twenty-two black-box `streaming` specs pass against the Go relay through nginx**, first
  time any Playwright project has ever driven it (A10.7's "no Playwright project drives `relay-go`
  today"). Including `authorize-matrix.spec.ts:82`, the forged-marker `@contract` test, which R6
  covers.
- **`streaming-split` passes.** It does not fail at the flip; it goes **vacuous**, precisely as
  A10.10 said. R8 disposes of it.
- **`guards` passes**, so the parity-matrix guard and the capability guards are green *before* any
  of this PR's own `e2e/` edits — which is what makes R7's and R9's "these two edits must land in
  the same commit" claims load-bearing rather than theoretical.

**The caveat, stated rather than papered over.** `Backend Tests` and `Go Tests` reported success
with every heavy job **skipped**: the measurement branch touches no backend path and no `relay/`
path, so both change detectors gated their matrices off and the aggregates passed through their
not-required branch. So the measurement says **nothing** about either. 2d-3 itself touches `relay/`
(R10's new test file), so `go-tests.yml`'s `build`, `lint`, `coverage` and `differential` jobs all
run on it for real — including the Go coverage gate and, per A10.13,
`TestDeletingOneClientDisconnectsItAndLeavesTheOtherStreaming`. **A10.13's precondition is
satisfied**: [#318](https://github.com/D10Scot/Dispatcharr/issues/318) is CLOSED, fixed by
`16fbb952` (`relay(httpapi): #318 -- an admin stop cannot interrupt a blocked write (#320)`), which
is an ancestor of the seed. 2d-3 touches no backend Python path, so `Backend result` will skip its
heavy jobs on this PR exactly as it did here — that is correct, not a gap, and the PR body says so.

### R1 — The nginx diff: four locations, one upstream, one new params file

The three byte-path locations (`^~ /proxy/ts/stream/` `:269`, `^~ /live/` `:377`, the XC
three-segment regex `:500`) each lose their thirteen-line `uwsgi_*` body and gain a twenty-line
`proxy_*` one. The `auth_request` preamble — the subrequest, the eight `auth_request_set` lines and
`error_page 403 = @authorize_denied;` — is **unchanged on all three**: those directives are
directive-family-agnostic, and the measurement confirms it (test 2's failure names
`HTTP_X_RELAY_CHANNEL`, not `auth_request` or any `auth_request_set`).

Each flipped byte-path body, verbatim, in this order (Appendix A carries it as a diff hunk):

```nginx
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Host $host:$server_port;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
        proxy_set_header X-Dispatcharr-Authorized "RELAY_TRUST_TOKEN";
        proxy_set_header X-Relay-Channel $relay_channel;
        proxy_set_header X-Relay-Output  $relay_output;
        proxy_set_header X-Relay-Client  $relay_client;
        proxy_set_header X-Relay-User    $relay_user;
        proxy_set_header X-Relay-Output-Format $relay_output_format;
        proxy_set_header X-Relay-Client-IP     $relay_client_ip;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_http_version 1.1;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        client_max_body_size 0;
        proxy_pass http://relay_go;
```

**The six re-declared headers are the spec's fix part (1) and they are not optional.**
`proxy_set_header` is an array directive: the moment a location declares one of its own it inherits
**none** of `nginx.conf:51-56`'s six. `include uwsgi_params;` is dropped — it builds the uwsgi wire
protocol's variable block, which `proxy_pass` does not speak. `client_max_body_size` and
`proxy_read_timeout` are simple directives and inherit normally; they are repeated here only because
the location already repeated them, not because they were at risk, and naming which family is and is
not affected is what stops an implementer over-correcting.

`^~ /proxy/relay/` (`:372-376`) becomes, in full:

```nginx
    location ^~ /proxy/relay/ {
        include /etc/nginx/dispatcharr_api_params_proxy.conf;
        proxy_read_timeout 30s;
        proxy_pass http://relay_go;
    }
```

and **deliberately re-declares none of the six** — the spec's own exemption, whose reason is that
its client is Django rather than a viewer and the Go control API reads neither a forwarded address
nor a forwarded `Host`. Losing `Host: $host` between two internal processes is inert.

The new upstream goes immediately after `upstream relay_py` (`:21-23`), with the comment Appendix A
carries. **The `map $relay_name $relay_upstream` block and `relay_py` are untouched**, per D3.

`docker/dispatcharr_api_params_proxy.conf` is a new file, seven `proxy_set_header … "";` lines and
its header comment (Appendix B, verbatim). Under `proxy_pass`, a `proxy_set_header` with an empty
value does not forward an empty header — nginx drops the client's header and sends nothing under
that name, the same outcome the `HTTP_`-prefixed `uwsgi_param ""` rule produces. `docker/Dockerfile`
gains one `COPY` line beside its uwsgi twin at `:65`, **or nginx fails config load with "open() …
No such file or directory"** — measured: without it the container does not start.

**Verified:** `docker exec plan2d3-e2e nginx -t` →
`nginx: configuration file /etc/nginx/nginx.conf test is successful`, and the resolved config shows
`upstream relay_go { server 127.0.0.1:5658; }` with four `proxy_pass http://relay_go;` lines at
`:326`, `:408`, `:453`, `:595`. An actual tune through it returned 93 ms to first TS packet
(`time-to-first-byte.spec.ts`, ceiling 10 000 ms).

### R2 — One stale comment in `nginx.conf` is corrected, and one is not

The `map` block's own comment (`:35-36`) ends "`default` covers the two relay-bound locations that
run no subrequest, where `$relay_name` is unset." **That sentence is already false at the seed** —
both of those locations (`^~ /proxy/relay/` `:375` and the nested
`~ ^/api/channels/recordings/\d+/file/$` `:209`) pass to the literal group `relay_py`, not to
`$relay_upstream` — and the flip makes it worse: after it, every one of the six locations still
using `$relay_upstream` runs the hop, so `default` covers none. **Ruling: correct it, in one
sentence, in this PR.** It sits three lines from the new `upstream relay_go` block a reader will be
comparing it against, and a comment that misdescribes which locations a map serves is exactly the
kind of thing that makes the next person add a second map entry D3 refused.

`upstream relay_py`'s own comment (`:8-13`) is **not** touched: "The relay's uWSGI process (Phase 1
PR 4)" stays true, narrowed to VOD and catch-up, and § Stage 2d says that process stays for the
remainder of Phase 3.

### R3 — `DISPATCHARR_RELAY_GO_DEV_ROUTES="1"`, and the `dev` shape is unaffected

A10.2 option (c): one line, `docker/supervisord.d/relay-go.conf:27`'s `environment=` gains
`,DISPATCHARR_RELAY_GO_DEV_ROUTES="1"`. Without it `relay/httpapi/server.go:62-89` registers no
route but `/healthz` and `/readyz` and **every tune 404s** — loud, which is the one mercy. It
reddens none of the five tests that pin the flag (A10.2 enumerates them): it changes a deployment
file, not the flag's semantics.

**`DISPATCHARR_ENV=dev` is unaffected, and the reason is structural rather than a decision.** The
`all-dev` rung runs vite and **no nginx** (CLAUDE.md § Architecture), so there is no location table
to flip; `:5656` is the API uWSGI and `/proxy/relay/…` is served by the API process, exactly as
CLAUDE.md § Commands already records. `devRoutes()` already returns true there from
`DISPATCHARR_ENV == "dev"` (`relay/config/config.go:146-155`), so setting the variable explicitly in
`relay-go.conf` changes nothing for that rung either. And A10.2's last paragraph:
`POST /_dispatcharr/authorize-internal` is a **Django** route the Go side reaches only when the
trust marker is absent — after the flip nginx's `auth_request` supplies the marker on every live
location so the fallback is never taken in production, and disabling it would break `dev`, which has
no nginx. **Nothing about the dev shape changes and nothing needs to.**

### R4 — `RELAY_GO_UPSTREAM` reads `DISPATCHARR_RELAY_GO_PORT`, and `entrypoint.sh` defaults it

A10.16. The sed goes immediately after the `RELAY_UPSTREAM` one in
`docker/init/03-init-dispatcharr.sh` (inside the same `all`/`api` role gate, reusing the `RELAY_HOST`
that block already computed — so the modular shape gets `<relay host>:<port>` and every other shape
gets `127.0.0.1:<port>` with no second hostname-validation branch), and copies
`:88-93`'s default-and-validate shape exactly: default on a non-integer, warn, carry on.
`docker/entrypoint.sh` gains `export DISPATCHARR_RELAY_GO_PORT=${DISPATCHARR_RELAY_GO_PORT:-5658}`
beside `:231`'s `DISPATCHARR_RELAY_PORT` — with a comment saying it is **not** a uWSGI `$(VAR)`
(`relay/config/config.go:63` reads it directly, `docker/healthcheck.sh:33` probes it, and this sed
now reads it, so all three must see one value).

**Verified:** the sed resolves. In the built container the block reads
`upstream relay_go {\n    server 127.0.0.1:5658;\n}`, and `nginx -t` passes.

### R5 — The four-test rewrite of `nginx-stream-buffering.spec.ts`

The `parseLocationBlocks` parser (`:32-60`) is **unchanged** — it is already directive-agnostic, and
the measurement proves it: all four failures are assertion failures on correctly parsed blocks, none
a parse failure. Only what each test asserts changes. `RELAY_BOUND_TARGETS` (`:155-165`) splits into
two constants; **both halves keep the `toEqual` on a sorted array**, so the vacuous-pass guard
survives on each.

- **Test 1** — `UWSGI_BOUND_TARGETS` (six: `/proxy/vod/`, `/proxy/catchup/`, `/movie/`, `/series/`,
  `/timeshift/`, `/streaming/timeshift.php`) asserted `uwsgi_buffering off`; `PROXY_BOUND_TARGETS`
  (three: `/proxy/ts/stream/`, `/live/`, the XC regex literal) asserted `proxy_buffering off`.
  Renamed to `'every relay-bound location keeps buffering off, in its own directive family'` — the
  title change is safe, R7 measured that nothing pins this file's titles.
- **Test 2** — the `auth_request`, the eight `AUTH_REQUEST_SET_VARS` and the `error_page` loops run
  over **both** sets unchanged. The forwarding loop and the marker split by family: the six keep
  `uwsgi_param HTTP_X_RELAY_*` / `uwsgi_param HTTP_X_DISPATCHARR_AUTHORIZED`, the three take
  `proxy_set_header X-Relay-*` / `proxy_set_header X-Dispatcharr-Authorized`, both still matching
  `/"[0-9a-f]{64}"/`. **A seventh assertion is added to the three flipped blocks, and it is the
  point of the whole section**: each must carry all six server-level `proxy_set_header` names. An
  implementer who pastes the `uwsgi_*` block and changes only `_pass` produces a config that passes
  every other assertion in this file and silently reports nginx's own address as every viewer's
  `ip_address`. Nothing else in the suite would catch it (R6's measurement found no test that reads
  `ip_address` at all).
- **Test 3** — `/proxy/relay/` leaves the thirteen-target `blanked` list, which becomes twelve. The
  `paramsFile` regex is unchanged and still matches only `dispatcharr_api_params.conf` (the new
  `_proxy.conf` banner does not match `params\.conf:`); a **second** block is added asserting the
  same seven names are blanked in `dispatcharr_api_params_proxy.conf`, by `proxy_set_header` — the
  same "asserting the include's presence alone cannot tell a five-name file from a seven-name one"
  reasoning the existing comment at `:352-355` gives.
- **Test 4** — `proxy_pass http://relay_go;` present, `internal;` still absent, `auth_request` still
  absent, `dispatcharr_api_params_proxy.conf`'s include present, `proxy_read_timeout 30s` present.

### R6 — The forged-marker `@contract` test needs no edit, and this was measured, not assumed

The Phase 1 PR 5 test is `e2e/tests/streaming/authorize-matrix.spec.ts:83`,
`'a client-supplied trust marker does not authorize a hidden channel'`, `@contract`. It requests
`/proxy/ts/stream/<uuid>` — one of the three flipped locations — forging all five of
`X-Dispatcharr-Authorized`, `X-Relay-Channel`, `X-Relay-User`, `X-Relay-Output-Format` and
`X-Relay-Client-IP` (`:125-135`) at a `hidden_from_output` channel, and asserts an **exact** 403 via
`expectRefused` (`:370-391`, which rethrows anything that is not a `StreamStatusError` with
`error.status === 403`).

**It passes under `proxy_pass`, measured** — CI run 35469742032's `streaming` job and the local run
both report it green. So the spec's "must be re-pointed at the new location" is satisfied by the
test already pointing there, and "re-verified to still 403, not assumed to carry over" is satisfied
by this measurement plus the rerun in this PR's own gate. **Ruling: no edit to
`authorize-matrix.spec.ts`.** The one thing to state plainly, because it is what the spec was
worried about: the mechanism did change — `uwsgi_param HTTP_X_…` overriding a client header became
`proxy_set_header` unconditionally setting it — and R5's test 2 is what pins the new mechanism
statically, while this test pins the outcome dynamically. Neither alone is the pin.

Note for the reader tempted to widen it: **no test in `e2e/` sends a forged marker at the XC
three-segment regex or at `^~ /proxy/relay/`.** Every XC-live request in the suite uses the `/live/`
prefix form, which `^~ /live/` claims before the regex is evaluated. That is a pre-existing gap, not
one this PR opens, and closing it is not 2d-3's.

### R7 — `output-profile-sharing.spec.ts`: drop the Redis half, keep the title, touch no matrix

`e2e/tests/streaming-greybox/output-profile-sharing.spec.ts` loses exactly two ranges: the import at
`:5` and the comment-plus-assertion at `:125-144`. The `pgrep` half (`:1-2`, `:7`, `:9-12`,
`:14-40`, `:72`, `:109-123`) **stays in full** — `countFfmpegProcesses()` is language-agnostic and
`relay/output` spawns one transcode per `(channel, profile)` pair, which the measurement confirms:
the test reached `:144` on the flipped container, so `:123`'s `expect(…).toBe(1)` had already passed
against the Go relay.

**The test title is kept byte-identical**, and that is a ruling, not an accident.
`docs/relay-parity-matrix.md:184` (row 11) pins
`` `e2e/tests/streaming-greybox/output-profile-sharing.spec.ts::two clients on one output profile
share a single transcode` ``, and `testRefProblem` resolves a `.spec.ts` reference by **literal
title** (`parity-matrix.ts:481-489`). A10.5 names keeping it "the cheap answer and the one to
prefer"; keeping it means **this PR edits no matrix row at all**, and the matrix's Python column —
which 2d-4 rewrites one PR later — is not disturbed by a PR that would be editing it for an
unrelated reason. Row 11's Notes cell already says "spec D2 deletes `output_owner`/`output_state`,
so 'across the cluster' becomes 'in the one relay process' and the sharing is the registry's
refcount", so the matrix is already correct about what this PR removes.

The `@characterization` rationale comment at `:42-46` is justified entirely by the `pgrep` half and
stays correct. The comment at `:125-141` goes with the assertion it explains (the deletion range is
`:125-144`), and two sentences saying why there is no owner-lock half any more are added to the
`:109-122` comment block that survives above the `pgrep` assertion.

### R8 — `allowlist.ts` empties, and `fixtures/greybox/redis.ts` survives until Phase 3

`e2e/tests/guards/allowlist.ts:76-83`'s `GREYBOX_REDIS.allow` is a one-element array naming
`tests/streaming-greybox/output-profile-sharing.spec.ts`, and `capabilities.spec.ts:130` compares it
with `toEqual` on a sorted array — so **removing the last use reddens `guards` unless the allowlist
is emptied in the same commit**, exactly as adding one would. `expectConfined` handles the empty
case correctly (`[]` vs `[...[]].sort()` is `[]`).

**Ruling: empty `GREYBOX_REDIS.allow` to `[]` with a comment; do NOT delete
`e2e/fixtures/greybox/redis.ts` and do NOT delete the capability.** Three reasons, in order of
weight. (a) An empty allowlist is a **stronger** ratchet than a deleted guard: with it, any
reintroduction of Redis coupling anywhere in `tests/`, `fixtures/` or `setup/` reddens `guards` by
name. Deleting the helper deletes that. (b) The helper is also on `SUBPROCESS.allow` (`:65`, it
imports `node:child_process`), so deleting it is a three-capability edit inside the cutover PR
rather than a one-line one. (c) CLAUDE.md's stated purpose for the quarantine is that "Phase 3
removes Redis from the data path, at which point every greybox test is rewritten or deleted; one
file keeps that a single grep" — the file is the bookmark for that refactor, and 2d-3 is not it.
The comment says so, so the next reader does not have to re-derive it.

### R9 — `process-restart.spec.ts` Scenario B: two restarts, two clocks, measured

Scenario B (`'a relay restart is bounded, and leaves a Celery task queued across it to finish'`,
`:468-693`) does not fail at the flip — CI's `streaming-split` job passed. It goes **vacuous**: it
restarts `relay-uwsgi`, which after the flip serves no live traffic, and then asserts a tune
succeeds, which it does, from the Go relay, unperturbed. Its own budget justification (`:78-105`,
derived from `relay-uwsgi.conf`) becomes a claim about the wrong process. Worse, the comment at
`:624-627` — "The running stream died with the process it was served by" — is simply false.

**The test carries two independent claims and they belong to two different processes now:**

1. **Bounded restart** — after the flip only `relay-go` can make this claim.
2. **D15 / Celery** — the mechanism is `wait-for-stores.sh` → `wait_for_redis.py` on
   **`relay-uwsgi`'s** start path. `relay-go.conf` has no `wait-for-stores.sh` wrapper by design
   (its own header, `:15-19`: "The Go relay opens no Postgres connection and no Redis connection …
   so it has no store to wait for"). Retargeting the whole test at `relay-go` swaps one vacuity for
   another: a process with no Redis client cannot demonstrate that no start path flushes Redis.

**Three shapes were measured, on the flipped container, with a stream running, each timed from
before the blocking `supervisorctl` call to the first 200 aligned TS packets of a fresh tune:**

| Shape | `supervisorctl` returned | First TS bytes | Margin under the 30 000 ms ceiling |
|---|---|---|---|
| `restart relay-go` | 17 147 ms | **17 311 ms** | 12 689 ms |
| `restart relay-uwsgi` | 6 722 ms | **6 867 ms** | 23 133 ms |
| `restart relay-uwsgi relay-go` (one command) | 23 791 ms | **23 946 ms** | **6 054 ms** |

`relay-go`'s 17.3 s is D6's drain doing its job inside `stopwaitsecs=20` — a five-second client
grace, the channel teardown, and the three-second events flush — where `relay-uwsgi`'s `die-on-term`
returns in well under a second. **The one-command shape is rejected on the measurement**: 6 s of
margin on a developer laptop, against CI runners that are reliably slower, is a flake, and
`supervisorctl restart a b` stops each in turn so its configured worst case is 20 + 20 = 40 s,
past the ceiling.

**Ruling: one test, two restarts, two clocks.** In order: seed as today → open the held stream →
restart **`relay-go`** and measure a fresh tune against `RELAY_GO_RESTART_CEILING_MS` → trigger the
decoy and tracked M3U refreshes → restart **`relay-uwsgi`**, take the in-flight assertion the
instant it returns, and poll the tracked refresh to `success:bumped`. Both claims stay real, the
setup is not duplicated, and each clock is independently inside its own ceiling (17.3 s and 6.9 s
measured). The title becomes `'both relay processes restart bounded, and a Celery task queued
across the uWSGI one still finishes'`; nothing pins it (R7's measurement covers the matrix,
and `e2e/COVERAGE.md:200` cites this spec by **file**, not by title). The ceiling stays
**30 000 ms** and its justification is re-derived rather than copied: `relay-go.conf` carries
`stopwaitsecs=20` (`:34`) and `startsecs=5` (`:32`), the same 25 s configured worst case
`relay-uwsgi.conf` has, and the drain's own fifteen-second budget sits inside the 20.

The `@characterization`/`@contract` question (ADR 0002): the test is `@contract` today and stays
so. Both claims are about externally-observable behaviour — a viewer gets bytes again inside a
bounded window, a queued job still completes — not about the process table; `instance.supervisorctl`
is on the `CONTAINER_LIFECYCLE` allowlist, which ADR 0002 makes a `@characterization` *signal*, but
this file already carries the same `@contract`-despite-allowlist reasoning
`nginx-stream-buffering.spec.ts:91-97` states for itself, and the flip does not change it.

### R10 — The Go priority test, and why it cannot move the coverage gate

A10.9: nothing asserts that `relay-go` shares supervisord `priority=205` with `relay-uwsgi`, and the
arithmetic in `relay-go.conf:7-13` (a separate priority takes the container stop budget from 155 s
to 175 s against a 160 s `stop_grace_period`) is a comment. **A new Go test file,
`relay/drain/supervisord_priority_test.go`**, in package `drain`, reads **both** confs through
`relaytest.RepoRoot()` exactly as `drain_test.go:37-58` already does, and **fails rather than
defaults** when either file or either key is absent — the same "a helper that fell back to 20 would
turn a renamed key into a permanently green test" rule `drain_test.go:33-36` states for
`stopwaitsecs`. Not `docker/tests/` and not lifecycle: the reader who needs it is the one editing
the drain budget, the `RepoRoot()` mechanism is already in this package, and a second independently
maintained directory walk is the drift `corpus.go:41-49` warns about.

**Appendix E's file was written, compiled and run during planning, and both of Task 3's
break-checks were executed rather than imagined.** Against the measurement tree:
`go test -race -run TestBothRelayProgramsShareOnePriorityGroup ./drain/` → `ok`, `go vet ./...`
clean, `golangci-lint run ./...` → `0 issues.`. Setting `relay-go.conf`'s `priority=206` printed
exactly the four-line message Task 3 Step 3 quotes; deleting `relay-uwsgi.conf`'s `priority=` line
printed `docker/supervisord.d/relay-uwsgi.conf declares no priority=<n>. …` and **failed** rather
than defaulting, which is the property the helper exists for.

**Touching `relay/` runs the whole of `go-tests.yml`, including `scripts/coverage_relay_go.sh
--gate`, and the gate cannot move on this edit.** Its three equality checks are `shape=`
(the stopping rule / test command / cover mode — unchanged), `packages=` (a hash of
`go list -deps .` from `relay/` — a new `_test.go` file in an already-linked package adds no
package), and `gomod=` (a hash of `relay/go.mod`'s bytes — untouched). `statements` is recorded
provenance and never compared. And `missing` is a **maximum**, lower being better
(`coverage_relay_go.sh:301`): a test that reads two files and calls no `drain` function leaves it
where it is. **So this PR ships no floor edit.** If the gate fires anyway, that is a finding to
investigate per package and then per block, never a floor bump on this PR —
`scripts/coverage_relay_go.floor`'s own `HOW TO MOVE THIS FLOOR`.

### R11 — `nice`, and why the fix is safe in the cutover PR

A10.9's second half. `relay-go.conf:25`'s `command=` is a bare `setpriv` while `relay-uwsgi.conf:2`
and `api-uwsgi.conf:2` both prefix `nice -n %(ENV_UWSGI_NICE_LEVEL)s`, and the conf's own comment at
`:21-23` promises the prefix from 2c-2 onward. At the default (`UWSGI_NICE_LEVEL=0`) this is inert.
For an operator who took the documented recommendation — `UWSGI_NICE_LEVEL=-5`, printed as a
commented example in four compose files at five places, including
`docker/docker-compose.yml:190` for the `relay:` service `relay-go` actually runs in — **the flip
makes the byte-carrying process the lowest-priority of the three.**

**Ruling: one line, here.** `nice -n %(ENV_UWSGI_NICE_LEVEL)s` ahead of `setpriv`, matching
`relay-uwsgi.conf:2` exactly, and `:21-23`'s now-false comment rewritten. The failure mode is mild,
which is what makes it safe inside a cutover: every one of those five compose blocks pairs the
example with a commented `cap_add: SYS_NICE`, and GNU `nice` asked for a negative value without that
capability warns on stderr and **still execs** the program — so the prefix degrades to today's
behaviour rather than putting `relay-go` into a supervisord BACKOFF loop. The alternative is
shipping a cutover that silently degrades exactly the deployments whose operators followed the
documentation.

### R12 — `metrics/curated/` and `docs/relay-parity-matrix.md` were checked, and neither moves

- **`metrics/curated/defects.yml`**: `grep -n "process-restart\|nginx-stream-buffering\|output-profile-sharing" metrics/curated/*.yml` returns nothing at the seed, so `metrics/build/curated.py:320-325`'s
  path-existence check has nothing to fail on. A10.15's three at-risk rows are 2d-4's and none is in
  this PR's diff.
- **`docs/relay-parity-matrix.md`**: R7 keeps the one title it pins. No `Source` citation in the
  matrix names a `docker/` or `e2e/` path this PR edits (the guard reads the working tree for both
  columns, and `guards` passed on the measurement branch with all four flipped locations in place).
- **No architecture metric moves**: `scripts/metrics/collect_architecture.py`'s counters are over
  Python imports; this PR edits no `*.py`.
- Consequence: `python -m metrics.build --validate-only` is **not** in this PR's gate, because the
  commit gate runs it only when a `metrics/` path is staged and none is. Stated in the PR body so it
  is a decision rather than an omission.

### R13 — What the flip assumes from the job 2d-4 deletes

A10.7's last paragraph, which this plan is required to state in as many words. The `differential`
job (`.github/workflows/go-tests.yml:380`) is the only thing in CI that **drives** the Go binary
against a real Django — `test_relay_differential.py` runs it against its own `LiveServerTestCase`,
so the `next-source` call is real with the real `SECRET_KEY`. 2d-4 deletes it, and nothing replaces
it. **What takes over that role is this PR's E2E coverage**: from 2d-3 onward the E2E container
drives `relay-go` through nginx, end to end, on every `migration/**` run — thirteen Playwright
projects, measured green at R0. That is a broader integration point than the differential's focused
byte-for-byte assertion and a weaker one per assertion; what the differential proved, two
implementations agreeing, has no meaning once there is one. It is recorded here so nobody discovers
in 2d-4 that a job vanished and wonders what covered it.

### R14 — A10.12's four fields, exercised through the flipped nginx

Not a deliverable; an acceptance criterion, and it has been run once already so Task 7 has expected
outputs rather than a wish. All four, on the flipped container, through nginx:

- **`stream_profile.argv`** — a transcode tune (`seed.streamProfile()`, an ffmpeg remux) delivered
  200 aligned TS packets and `GET /proxy/ts/status/<uuid>` came back with
  `"state": "active"`, `"video_codec": "h264"`, `"resolution": "640x360"`, `"source_fps": "25.0"`,
  `"audio_codec": "aac"` — ffmpeg-derived fields that exist only because the Go relay spawned the
  argv Django built. `stream-profiles.spec.ts:37` asserts the same thing in the suite and is green.
- **`output_profiles[*].argv`** — an Output Profile tune delivered 200 aligned packets, and
  `output-profile-sharing.spec.ts`'s `pgrep -x ffmpeg` count reached exactly 1.
- **The null-`argv` arm** — an Output Profile whose `parameters` carry an unterminated quote
  (`-i pipe:0 -c copy "unterminated -f mpegts pipe:1`) is accepted by the API (**201**) and then
  tuning against it answers **`500 Internal Server Error`**, which is A7/R4's specified behaviour: a
  profile Django's `shlex` refused is a 500 for the client that selects it, where a profile merely
  absent from the map is a client served with no profile at all.
- **`BUFFER_CHUNK_SIZE`** — the status payload's `buffer_stats` reads
  `"avg_chunk_size": 255868`, `"recent_chunk_sizes": [255868, 255868, 255868, 255868]`, and
  `first_chunk` `{"size": 255868, "ts_packets": 1361, "aligned": true, "first_byte": 71}`. That is
  `188 × 1361` exactly — `apps/proxy/config.py:15`'s `BUFFER_CHUNK_SIZE`, carried on the
  `next-source` answer (A1.4) and sized in the Go ring from it, not from a Go-side constant.
- **`ip_address`** — `"ip_address": "172.26.0.1"`, the Docker bridge gateway, i.e. the **real
  client**, not nginx's `127.0.0.1`. This is the whole point of R1's six re-declared headers plus
  the `X-Relay-Client-IP` hop resolution, and it is the one A10.12 kept on the list because the
  *transport* under it is new.

### R15 — `e2e/fixtures/types.ts`'s three required fields are filled; nothing is relaxed

A10.10's named unknown: `worker_id: string` (`types.ts:455`), `ip_address: string` (`:456`) and
`owner: string | null` (`:498`) are typed as **required** properties of a concept the Go relay might
not have. Measured on the flipped container:

```
[A1012] ip_address values: ["172.26.0.1"]
[A1012] worker_id values:  ["unknown"]
[A1012] owner:             "unknown"
```

All three present, all three non-null. **Ruling: no type relaxation, no assertion change, no Go-side
fix.** Two further facts make this a closed question rather than a lucky pass: (a) these are
compile-time types over a JSON cast, so a missing field would not have thrown at runtime anyway; and
(b) `grep -rn "worker_id\|ip_address" e2e/` returns **exactly two lines — the two declarations** —
and no `.owner` property access exists anywhere in `e2e/`, so no assertion in the suite reads any of
the three. The Go relay's `"unknown"` for `owner` and `worker_id` is parity-matrix row 14's
documented asymmetry reproduced per D5, not a gap.

---

## File structure

**Created (2)**

| Path | What |
|---|---|
| `docker/dispatcharr_api_params_proxy.conf` | The `proxy_set_header` twin of `dispatcharr_api_params.conf`, 7 blanking lines + header comment (Appendix B) |
| `relay/drain/supervisord_priority_test.go` | R10's assertion that both relay confs share `priority=205` (Appendix E) |

**Modified (12)**

| Path | What | Ruling |
|---|---|---|
| `docker/nginx.conf` | 4 locations flipped, 1 upstream added, 1 comment corrected | R1, R2 |
| `docker/Dockerfile` | 1 `COPY` line for the new params file | R1 |
| `docker/init/03-init-dispatcharr.sh` | the `RELAY_GO_UPSTREAM` sed | R4 |
| `docker/entrypoint.sh` | `DISPATCHARR_RELAY_GO_PORT` default | R4 |
| `docker/supervisord.d/relay-go.conf` | dev-routes env var, `nice` prefix, comment 3 rewritten | R3, R11 |
| `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts` | the four-test rewrite | R5 |
| `e2e/tests/streaming-greybox/output-profile-sharing.spec.ts` | Redis half removed, title kept | R7 |
| `e2e/tests/guards/allowlist.ts` | `GREYBOX_REDIS.allow` → `[]` + comment | R8 |
| `e2e/tests/streaming-split/process-restart.spec.ts` | Scenario B: two restarts, two clocks | R9 |
| `e2e/COVERAGE.md` | four rows: `:196`, `:197`, `:200`, `:259-261` | R5, R7, R9 |
| `CLAUDE.md` | six passages | Appendix F |
| `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` | Amendment A13 + three in-place corrections + the Done-log row | Appendix G |

**2 created + 12 modified = 14 paths**, which is exactly what Task 9 Step 1 asserts
`git diff --stat origin/main` names. Five are `docker/`, four are `e2e/` test or allowlist source,
one is `e2e/COVERAGE.md`, one is `relay/`, and two are docs (`CLAUDE.md` and the spec). No `*.py`,
no `frontend/`, no `.github/workflows/`, no `metrics/`.

**Deliberately not touched**, each checked rather than assumed:

- **Every `*.py` file** — Constraint 2, A10.11.
- `docs/relay-parity-matrix.md` and `metrics/curated/**` — R12, measured.
- `e2e/fixtures/greybox/redis.ts` — R8: kept as Phase 3's bookmark, its allowlist emptied instead.
- `e2e/fixtures/types.ts` — R15: all three at-risk fields measured present.
- `e2e/tests/streaming/authorize-matrix.spec.ts` — R6: the forged-marker test passes unedited.
- `docker/nginx.conf`'s `map $relay_name $relay_upstream` **values**, `upstream relay_py`, and the
  five VOD/catch-up locations plus `= /streaming/timeshift.php` — D3, and R2 for the map's comment.
- `.github/workflows/**` — this PR adds no job and removes none; A10.7's `go-tests.yml` edit is
  2d-4's.
- `frontend/**` — nothing here reaches it.

---

## Task 0: Verify the seed

**Files:** none modified.

- [ ] **Step 1 — the tree.** From the worktree root:
      `git -C <worktree> fetch origin && git -C <worktree> log --oneline -3 origin/main`.
      **2d-1 has merged** as `d5be64d5`, this plan's seed, so only 2d-2 is outstanding:
      `git merge-base --is-ancestor d5be64d5 origin/main` and
      `git merge-base --is-ancestor <2d-2's merge sha> origin/main`, each exiting 0. **If 2d-2 is
      not merged, STOP and report.** Record the new seed SHA; it replaces `d5be64d5` for every
      `file:line` below, and 2d-2 touches none of the files this PR edits except `CLAUDE.md` and
      the spec — both of which are handled by scripts precisely so the shift costs nothing.
- [ ] **Step 2 — `git status --porcelain` is empty.** Anything else means someone else is in this
      tree. STOP.
- [ ] **Step 3 — the four locations are still where R1 says.** `grep -F` with one pattern per
      line, **not** a single alternation: BSD grep (this project's own darwin host) treats a
      mid-pattern `^` as an anchor in a BRE and matches nothing, while GNU and BusyBox treat it as
      a literal — so an alternation written `'location ^~ /proxy/…'` prints one line on macOS and
      four in a container, and this step would STOP falsely on half the machines that run it.
      ```
      grep -nF -e 'location ^~ /proxy/ts/stream/ {' \
               -e 'location ^~ /proxy/relay/ {' \
               -e 'location ^~ /live/ {' \
               -e 'location ~ ^/[^/]+/[^/]+/' docker/nginx.conf
      grep -c 'uwsgi_pass \$relay_upstream;' docker/nginx.conf    # expect 9
      grep -c 'uwsgi_buffering off;'         docker/nginx.conf    # expect 10
      ```
      Four lines, at `269` / `372` / `377` / `500` at the seed, then **9** and **10**. A different
      count means the location table moved and Appendix A will not apply — STOP and report rather
      than re-splicing.
- [ ] **Step 4 — the E2E anchors.** Expect each to print exactly one line:
      ```
      grep -n "const RELAY_BOUND_TARGETS" e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts
      grep -n "greybox/redis" e2e/tests/streaming-greybox/output-profile-sharing.spec.ts
      grep -n "export const GREYBOX_REDIS" e2e/tests/guards/allowlist.ts
      grep -n "restart', 'relay-uwsgi'" e2e/tests/streaming-split/process-restart.spec.ts
      ```
- [ ] **Step 5 — the Go anchors.** `grep -n "priority=205" docker/supervisord.d/relay-go.conf
      docker/supervisord.d/relay-uwsgi.conf` → two lines. `grep -n "func RepoRoot"
      relay/internal/relaytest/corpus.go` → one line.
- [ ] **Step 6 — A10.1, re-verified.** Run the `gh api … /rulesets/21229979` command from R0 and
      confirm **`Go result` is in the output**. **If it is absent, STOP and report** — it is a
      repository-settings action the user performs, not something this PR can do.
- [ ] **Step 7 — the parity matrix's row 11 still resolves.** R7's whole argument is that keeping
      `output-profile-sharing.spec.ts`'s title byte-identical means no matrix edit. 2d-1's merge
      DID touch `docs/relay-parity-matrix.md` (row 9's citation), so confirm the pin is still there:
      ```
      grep -c 'output-profile-sharing.spec.ts::two clients on one output profile share a single transcode' docs/relay-parity-matrix.md
      ```
      Expect **1**. Zero means someone edited row 11 and R7 needs re-deciding — STOP and report.
- [ ] **Step 8 — `docker/tests/*.sh` are in your gate, not just the measurement's.** Nothing to
      verify at seed time; noted here so it is not forgotten at Task 9: this PR's `Lifecycle result`
      must be green including `puid-pgid` (`test-puid-pgid.sh`, whose `test_role_split` is the only
      exercise of the modular shape, where `RELAY_GO_UPSTREAM` seds to `relay:<port>` rather than
      loopback) and `tls-postgres` (`test-tls-postgres.sh`). Both were green on the measurement
      branch; a red one on yours is a finding, not a flake to retry.
- [ ] **Step 9 — your container.** Start a scratch AIO container named `plan2d3impl-e2e` per the
      commands in Task 7. Do **not** use `dispatcharr-testrunner` and do **not** use the shared
      `dispatcharr-e2e` names.

## Task 1: The nginx flip

**Files:** `docker/nginx.conf`, `docker/dispatcharr_api_params_proxy.conf` (new),
`docker/Dockerfile`.

- [ ] **Step 1** — write Appendix A to a file and
      `git apply --check --whitespace=error <file>`, then `git apply <file>`. It was round-tripped
      at the seed both alone and in sequence with the other nine. If the check fails, an anchor
      moved: **STOP and report** — do not splice by hand, and do not `--3way` your way past it.
- [ ] **Step 2** — create `docker/dispatcharr_api_params_proxy.conf` verbatim from Appendix B.
- [ ] **Step 3** — `git apply` Appendix C (`docker/Dockerfile`, the one `COPY` line).
- [ ] **Step 4 — verify statically:**
      ```
      grep -c 'proxy_pass http://relay_go;' docker/nginx.conf          # expect 4
      grep -c 'uwsgi_pass \$relay_upstream;' docker/nginx.conf         # expect 6
      grep -c 'uwsgi_buffering off;'         docker/nginx.conf         # expect 7
      grep -c 'proxy_buffering off;'         docker/nginx.conf         # expect 3
      grep -c 'proxy_set_header X-Real-IP'   docker/nginx.conf         # expect 4  (1 server + 3 locations)
      grep -c 'uwsgi_pass relay_py;'         docker/nginx.conf         # expect 1  (the nested recordings regex)
      ```
      **Every one of those six numbers is an assertion, and all six were measured**, in the order
      the block above lists them — `proxy_pass http://relay_go;`, `uwsgi_pass $relay_upstream;`,
      `uwsgi_buffering off;`, `proxy_buffering off;`, `proxy_set_header X-Real-IP`,
      `uwsgi_pass relay_py;`:

      | grep | at the seed | after Appendix A |
      |---|---|---|
      | `proxy_pass http://relay_go;` | 0 | **4** |
      | `uwsgi_pass $relay_upstream;` | 9 | **6** |
      | `uwsgi_buffering off;` | 10 | **7** |
      | `proxy_buffering off;` | 0 | **3** |
      | `proxy_set_header X-Real-IP` | 1 | **4** |
      | `uwsgi_pass relay_py;` | 2 | **1** |

      `uwsgi_buffering off` at 7 rather than 10 is the three flipped
      locations leaving; `proxy_set_header X-Real-IP` at 4 rather than 1 is R1's replace-not-merge
      fix present on all three plus the one at server level; `uwsgi_pass relay_py;` at 1 rather
      than 2 is `/proxy/relay/` leaving and the nested recordings regex staying.

## Task 2: The boot-time plumbing

**Files:** `docker/init/03-init-dispatcharr.sh`, `docker/entrypoint.sh`,
`docker/supervisord.d/relay-go.conf`.

- [ ] **Step 1** — `git apply` Appendix D's three diffs (D.1 the `RELAY_GO_UPSTREAM` sed, D.2 the
      `DISPATCHARR_RELAY_GO_PORT` export, D.3 `relay-go.conf`'s env var + `nice` prefix + comment).
- [ ] **Step 2 — verify:**
      ```
      grep -n 'RELAY_GO_UPSTREAM' docker/init/03-init-dispatcharr.sh docker/nginx.conf   # 2 lines: the sed, the placeholder
      grep -n 'DISPATCHARR_RELAY_GO_PORT' docker/entrypoint.sh docker/init/03-init-dispatcharr.sh
      grep -n 'DISPATCHARR_RELAY_GO_DEV_ROUTES' docker/supervisord.d/relay-go.conf
      grep -n '^command=' docker/supervisord.d/relay-go.conf   # must begin: command=nice -n %(ENV_UWSGI_NICE_LEVEL)s setpriv
      grep -n 'priority=205' docker/supervisord.d/relay-go.conf
      ```
      The `priority=205` line must be **unchanged** — R10's new test asserts it and R11's edit must
      not disturb it.
- [ ] **Step 3 — `bash -n` both scripts.** `bash -n docker/init/03-init-dispatcharr.sh && bash -n
      docker/entrypoint.sh`. Both silent.

## Task 3: The Go priority test

**Files:** `relay/drain/supervisord_priority_test.go` (new).

- [ ] **Step 1** — create it verbatim from Appendix E.
- [ ] **Step 2 — run it:** from `relay/`, `go test -race -run TestBothRelayProgramsShareOnePriorityGroup ./drain/`.
      Expect `ok`.
- [ ] **Step 3 — the break-check, run not read.** Temporarily change `docker/supervisord.d/relay-go.conf`'s
      `priority=205` to `priority=206`, re-run the test, and confirm it prints:
      ```
      relay-go.conf declares priority=206 and relay-uwsgi.conf declares priority=205.
      They must share one supervisord priority group: a group of its own adds relay-go's
      stopwaitsecs to the container's stop budget as a separate window, taking the sum from
      155s to 175s against a 160s stop_grace_period.
      ```
      **Then revert the conf** and re-run to green. A second break-check: delete the
      `priority=` line from `relay-uwsgi.conf`, confirm the test **fails** rather than defaulting
      (`relay-uwsgi.conf declares no priority=<n>`), and revert. Record both outputs in the PR body.
- [ ] **Step 4 — the whole module:** `go build ./... && go vet ./... && go test -race ./... &&
      golangci-lint run ./...` from `relay/`, plus
      `scripts/check_go_stdlib_only.sh relay` and `scripts/check_go_credential_logging.sh`. All
      green. **Do not run `scripts/coverage_relay_go.sh --write-floor` for any reason** — R10.

## Task 4: The four-test rewrite

**Files:** `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts`.

- [ ] **Step 1** — `git apply` Appendix H.
- [ ] **Step 2 — typecheck:** `cd e2e && npm run typecheck`. Clean (the edit hook runs
      `tsc --noEmit` for this package on every `.ts` write and is blocking).
- [ ] **Step 3 — run all four against your flipped container** (Task 7 builds it):
      `npx playwright test --project=streaming-greybox -g "relay-bound location|outside the hop|relay control API"`.
      All four green.
- [ ] **Step 4 — break-checks, run not read.** Four reversions, each in `docker/nginx.conf`, each
      re-run against a rebuilt container; record the failure message each prints, then revert:
      1. Change `proxy_buffering off;` to `uwsgi_buffering off;` on `^~ /proxy/ts/stream/` →
         test 1 must say that block does not set `proxy_buffering off`.
      2. Delete `proxy_set_header X-Relay-Channel $relay_channel;` from `^~ /live/` →
         test 2 must say that location captures but does not forward `X-Relay-Channel`.
      3. Delete `proxy_set_header X-Real-IP $remote_addr;` from the XC regex location →
         test 2's new seventh assertion must name `X-Real-IP` and that block.
         **This is the break-check that matters most** — it is the one the whole of R1's
         replace-not-merge section exists for, and before this PR nothing in the suite could
         have caught it.
      4. Change `/proxy/relay/`'s include back to `dispatcharr_api_params.conf` →
         test 4 must say the relay control API must still blank the trust params.

## Task 5: The three other E2E edits

**Files:** `e2e/tests/streaming-greybox/output-profile-sharing.spec.ts`,
`e2e/tests/guards/allowlist.ts`, `e2e/tests/streaming-split/process-restart.spec.ts`.

- [ ] **Step 1** — `git apply` Appendix I's two diffs (the Redis half + the allowlist, which
      **must be one commit**: `capabilities.spec.ts:130`'s `toEqual` reddens if either lands
      alone).
- [ ] **Step 2** — `git apply` Appendix J (Scenario B).
- [ ] **Step 3 — `cd e2e && npm run typecheck`.** Clean.
- [ ] **Step 4 — run:** `npx playwright test --project=guards` (all green),
      `--project=streaming-greybox` (**seven** green — the project's six `test(` declarations
      across three spec files, plus the `bootstrap` dependency `playwright.config.ts:149-152`
      gives it; five was the count of tests that were *failing*, not what the project runs),
      `--project=streaming-split` (both scenarios green). Record Scenario B's two printed
      elapsed times — expect roughly 17 s for `relay-go` and 7 s for `relay-uwsgi` against the
      30 000 ms ceiling; **if either is within 5 s of the ceiling on your machine, STOP and report**
      rather than raising the ceiling.
- [ ] **Step 5 — break-checks, run not read.**
      1. Re-add `'tests/streaming-greybox/output-profile-sharing.spec.ts'` to `GREYBOX_REDIS.allow`
         without restoring the import → `guards` must fail naming the extra entry. Revert.
      2. Re-add the import to `output-profile-sharing.spec.ts` without restoring the allowlist entry
         → `guards` must fail naming the file. Revert. **Both directions**, because `toEqual` is
         what makes the removal a deliberate edit in the first place.
      3. In Scenario B, change `['restart', 'relay-go']` back to `['restart', 'relay-uwsgi']` →
         the test must still **pass** (that is the vacuity R9 is fixing, and demonstrating it is
         how the implementer confirms the retarget was the point). Record it and revert.
- [ ] **Step 6 — `e2e/COVERAGE.md`.** `git apply` Appendix K: rows `:196` (the control API no longer
      reaches the relay by `uwsgi_pass relay_py`), `:197` (the buffering directive on
      `/proxy/ts/stream/` is now `proxy_buffering off`), `:200` (two restart measurements, two
      processes) and `:259-261` (the shared-owner-key half is gone). Per the standing rule, in the
      same PR as the tests.

## Task 6: CLAUDE.md

**Files:** `CLAUDE.md`.

- [ ] **Step 1** — run Appendix F's replacement script. It is **verbatim-string** replacement, not
      line-anchored: 2d-1 and 2d-2 both edit this file first and every line number below 200 moves.
      The script asserts each anchor is found **exactly once** and exits non-zero otherwise.
- [ ] **Step 2 — verify:** `git diff --stat -- CLAUDE.md` shows one file; `git diff -- CLAUDE.md`
      shows six hunks and no seventh. If a hunk is missing, the anchor moved — **STOP and report.**

## Task 7: Build, smoke, and the full local gate

**Files:** none modified.

- [ ] **Step 1 — build a flipped container of your own:**
      ```
      cd <your worktree> && DISPATCHARR_E2E_CONTAINER=plan2d3impl-e2e \
        DISPATCHARR_E2E_VOLUME=plan2d3impl-e2e-data \
        DISPATCHARR_E2E_IMAGE=plan2d3impl-e2e:local \
        DISPATCHARR_E2E_PORT=9292 DISPATCHARR_E2E_NETWORK=plan2d3impl-net \
        ./scripts/e2e_up.sh
      ```
      Do **not** pass `--reset`: it destroys the shared `e2e-upstream` provider other agents use.
- [ ] **Step 2 — `nginx -t` and the resolved config:**
      ```
      docker exec plan2d3impl-e2e nginx -t
      docker exec plan2d3impl-e2e sh -c 'grep -n -A2 "upstream relay_go" /etc/nginx/sites-enabled/default'
      docker exec plan2d3impl-e2e sh -c 'grep -c "proxy_pass http://relay_go;" /etc/nginx/sites-enabled/default'
      docker exec plan2d3impl-e2e supervisorctl -c /app/docker/supervisord/supervisorctl.conf status
      ```
      Expected: `test is successful`; `server 127.0.0.1:5658` (the sed resolved, no placeholder
      left); `4`; all ten programs `RUNNING` including `relay-go`.
- [ ] **Step 3 — the A10.12 smoke check.** Run
      `npx playwright test --project=streaming --project=streaming-greybox --project=streaming-failover --project=streaming-split`
      against it and confirm, from the run's own output rather than by inspection:
      - `streaming/stream-profiles.spec.ts:37` (`the FFmpeg profile spawns a subprocess and reports
        its progress`) **green** — `stream_profile.argv`.
      - `streaming-greybox/output-profile-sharing.spec.ts` **green** — `output_profiles[*].argv`,
        with `pgrep -x ffmpeg` at exactly 1.
      - `streaming/time-to-first-byte.spec.ts` **green**.
      Then, by hand against the container, the two A10.12 fields no spec reads. Tune any channel and
      `GET /proxy/ts/status/<uuid>` as admin, and confirm:
      - `buffer_stats.avg_chunk_size` is **255868** and `first_chunk.ts_packets` is **1361** —
        `188 × 1361`, `BUFFER_CHUNK_SIZE` off the `next-source` answer. A different number means
        the Go ring sized itself from a Go-side constant and the contract field is not being read.
      - `clients[0].ip_address` is the **Docker bridge gateway** (`172.x.0.1`), **not** `127.0.0.1`.
        `127.0.0.1` means a `proxy_set_header` re-declaration is missing and Task 4's break-check 3
        should have caught it.
      - `clients[0].worker_id` and `owner` are present (`"unknown"` is correct — row 14's
        documented asymmetry, reproduced per D5).
      Then create an Output Profile whose `parameters` are `-i pipe:0 -c copy "unterminated -f
      mpegts pipe:1` (the API accepts it, **201**) and tune with `?output_profile=<id>`: expect
      **500**, the null-`argv` arm.
- [ ] **Step 4 — the remaining projects locally:** `--project=seeded --project=guards
      --project=frontend --project=dvr --project=lifecycle --project=pristine`. All green.
- [ ] **Step 5 — remove your container, volume and network** when Task 8 has pushed.

## Task 8: Amendment A13, the in-place spec corrections, and the Done-log row

**Files:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`.

- [ ] **Step 1** — run Appendix G's replacement script: Amendment A13 (appended after A12), three
      in-place corrections to § Stage 2d / the deletion list, and the Done-log row.
- [ ] **Step 2 — verify the spec carries no contradicting pair.**
Each of these greps must distinguish the post-edit state from the pre-edit one, which is why
      they name the **new** strings rather than the old ones a surviving anchor would also match:
      ```
      S=docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
      grep -c "127.0.0.1:5658 outside modular" "$S"          # expect 0 -- A10.16's literal is gone
      grep -c "Satisfied before 2d-3 was planned" "$S"       # expect 1 -- A10.1's ruling updated
      grep -c "re-pointed at the post-flip location" "$S"    # expect 0 -- § Testing corrected
      grep -c "the re-pointed forged-marker test" "$S"       # expect 0 -- entry 3's Gate corrected
      grep -c "Amendment A13" "$S"                           # expect 2 -- the heading and its Done-log mention
      grep -c "^| 2d-3 -- the nginx flip" "$S"               # expect 1 -- the Done-log row
      ```
      **Do not grep `"A10.1 is a precondition"`**: it returns 1 before the edit as well as after, so
      it cannot see its own change — the trap this step exists to avoid. And **do not grep
      `"re-pointed at the new location"` expecting 0**: A13.3 quotes that phrase when explaining
      which three sentences it corrected, so 1 is the right answer and 0 would mean A13 did not
      land. A surviving `127.0.0.1:5658` means the spec carries both the baked literal and the
      variable — **STOP.**

## Task 9: Open the PR

**Files:** none modified.

- [ ] **Step 1** — `git diff --stat origin/main` names **exactly 14 paths** and no others.
- [ ] **Step 2** — stage and commit in **separate** Bash calls, message written with the Write tool
      and passed as `git commit -F <file>` (the commit gate matches on command text).
- [ ] **Step 3** — push and open a **draft** PR with the body below. Wait for
      `E2E result`, `Lifecycle result`, `Go result`, `Backend result` and `Frontend result`.
- [ ] **Step 4** — mark ready for review only when all five are green.

### PR body template

```markdown
## What

The cutover. Four nginx locations move from `uwsgi_pass` to `proxy_pass http://relay_go`, and from
this commit the Go relay carries every live viewer in production.

- `docker/nginx.conf` — `^~ /proxy/ts/stream/`, `^~ /live/` and the XC three-segment regex each
  swap their `uwsgi_*` body for a `proxy_*` one; `^~ /proxy/relay/` moves too, or Django keeps
  asking the Python relay for a client list it no longer has and every live stream-limit check
  fails open forever. New `upstream relay_go`, sed'd at boot like `relay_py`.
- `docker/dispatcharr_api_params_proxy.conf` — new. The `proxy_set_header` twin of the uwsgi
  blanking include, for `/proxy/relay/` only, plus a `COPY` line in the Dockerfile.
- `docker/init/03-init-dispatcharr.sh`, `docker/entrypoint.sh` — `RELAY_GO_UPSTREAM` reads
  `DISPATCHARR_RELAY_GO_PORT` with the default-and-validate shape `DISPATCHARR_RELAY_PORT` uses,
  and the variable gets an exported default (A10.16).
- `docker/supervisord.d/relay-go.conf` — `DISPATCHARR_RELAY_GO_DEV_ROUTES="1"` (A10.2; without it
  every tune 404s), `nice -n %(ENV_UWSGI_NICE_LEVEL)s` (A10.9; without it the byte-carrying
  process is the lowest-priority of the three for any operator who took the documented
  `UWSGI_NICE_LEVEL=-5`), and its own third comment rewritten to stop promising a prefix it now has.
- `relay/drain/supervisord_priority_test.go` — new. Both relay confs share `priority=205`, read
  from the confs and failing rather than defaulting (A10.9).
- Five E2E assertions that break at the flip, rewritten in the same commit, plus their
  `COVERAGE.md` rows.

## The trap this stage exists not to repeat, arriving from the opposite direction

`uwsgi_buffering off` is **inert** under `proxy_pass`. The directive that matters there is
`proxy_buffering off`. CLAUDE.md records a past incident where the wrong directive family
(`proxy_buffering off` under `uwsgi_pass`) let nginx spool live TS to disk; getting the wrong
protocol's directive for the *new* protocol is this cutover's version of the same mistake, and it is
easy to make by pasting the working block and changing only `_pass`.

A second face of the same rule bites harder. `proxy_set_header` is an **array** directive: a
location that declares one of its own inherits **none** of the six the `server` block declares at
`:51-56`. Uncaught, the Go relay would see `Host: relay_go`, no `X-Real-IP` and no
`X-Forwarded-For`, and every live client's `ip_address` on both status endpoints would silently
become nginx's own address — invisible in dev, invisible in a smoke test, wrong in production,
while VOD and catch-up (still `uwsgi_pass`) kept reporting correctly. All three byte-path locations
re-declare the six. `/proxy/relay/` deliberately does not: its client is Django, not a viewer.

## The measurement this PR was designed against

Per A10.10, the design opened with a measurement rather than a guess: the minimal flip on a throwaway
`migration/**` branch, full matrix, failure set recorded. Thirteen of fourteen E2E jobs passed —
including all twenty-two black-box `streaming` specs, the first Playwright coverage the Go relay has
ever had — and the failure set was exactly the five assertions this PR rewrites. `streaming-split`
passed and went **vacuous**, which is why Scenario B is retargeted here rather than discovered
later.

## What this PR does NOT do

- **No Python change at all.** A10.11 measured that nothing in Python dials 5657 and that every
  `relay_client` branch but `dev` reaches nginx. The flip is entirely `docker/`.
- **No deletion.** `apps/proxy/live_proxy/`, its tests, the parity matrix's Python column, the
  `differential` job and `metrics/curated/`'s three at-risk rows are all 2d-4's.
- **No parity-matrix edit.** Keeping `output-profile-sharing.spec.ts`'s test title byte-identical is
  what keeps row 11's pin resolving, and row 11's Notes already describe the Go relay's
  no-owner-lock shape.
- **No `e2e/fixtures/greybox/redis.ts` deletion.** Its allowlist is emptied instead: an empty
  allowlist is a stronger ratchet than a deleted guard, and the file is Phase 3's single-grep
  bookmark.
- **No coverage-floor edit, Python or Go.** A `_test.go` file in an already-linked package moves
  none of `shape=`, `packages=` or `gomod=`, and `missing` is a maximum.
- **`DISPATCHARR_ENV=dev` is unchanged**, and structurally so: that rung runs no nginx.

## Rollback

An image rollback reverts the flip and the routes it enables **together** — D3's stated story. The
nginx location table, the `RELAY_GO_UPSTREAM` sed and
`relay-go.conf`'s `DISPATCHARR_RELAY_GO_DEV_ROUTES="1"` all live in the image, so the previous tag
serves live traffic from the Python relay with no configuration to undo and no per-channel state to
drain. That is the whole reason A10.2 chose to set the flag in the supervisord conf rather than
delete it or invert its default: reverting the image reverts both.

## Gate

- `E2E result` green **including** the four rewritten buffering tests, the edited
  `output-profile-sharing.spec.ts`, `guards` with the emptied allowlist, the re-verified
  forged-marker `@contract` test and the retargeted `streaming-split` Scenario B.
- `Lifecycle result` green, `puid-pgid` included — the modular role split is the one shape where
  `RELAY_GO_UPSTREAM` seds to a service name rather than to loopback.
- `Go result` green in full: `build`, `lint`, `coverage` and `differential` all run, because this
  PR touches `relay/`. `Go result` is a **required** check on the Main ruleset as of this PR's seed
  — A10.1's precondition, verified and recorded in the plan.
- `Backend result` **and** `Frontend result` green with their heavy jobs **skipped**, and that is
  correct rather than a gap in both cases: `labels_for_changed_paths()` returns `[]` for all
  fourteen touched paths, and none of them matches `frontend-tests.yml`'s own change detector.
  Stated for both so a skipped matrix is read as a decision rather than a problem — the
  measurement run reported exactly this shape for each.
- `nginx -t` inside a built container, and an actual tune through it.
- `python -m metrics.build --validate-only` is deliberately **not** in this gate: no `metrics/`
  path is staged, and R12 measured that none needs to be.
```

---

## Appendices

**Every appendix below is either a unified diff that `git apply --check --whitespace=error`
accepts at the re-seeded tree, a whole new file verbatim, or a verbatim-string replacement script
with an `assert count == 1` on every anchor.** No appendix is prose, and none says "replace the
block that begins … with"; the predecessor lesson is 2d-1's own
(`docs/superpowers/plans/2026-09-19-phase2-2d1-boot-trap-relocation.md`): *an appendix written as
prose or as a paragraph replacement goes stale and is spliced wrong.*

**How these were produced, and how to apply them.** Every edit in this plan was made in a scratch
worktree at the seed, then extracted with `git diff --cached`, then replayed into a **second**
pristine worktree at the same SHA — each patch on its own, and then all ten in sequence — with
`git apply --check --whitespace=error`. All ten passed both ways. **Write each to a file and
`git apply` it; do not retype a hunk.** A rejection means an anchor moved, which is a **STOP**, not
an invitation to splice.

The two files whose line numbers genuinely move before this PR runs — `CLAUDE.md` (2d-1 edits
§ Test hooks and § Structural constraints; 2d-2 edits § Commands and § Routing) and the spec
(A11, then A12) — are verbatim-string replacement **scripts** instead, which is 2d-2's own idiom for
exactly this reason. Everything else is a diff, because `git diff --name-only 2f721bfd d5be64d5 |
grep -E '^(docker/|e2e/|relay/)'` is **empty**: 2d-1's merge touched none of those trees, and 2d-2
touches none of them either (its Global Constraint 7 forbids it).

### Appendix A — `docker/nginx.conf`

One diff, four changes: the new `upstream relay_go` block, the `map` comment's stale sentence
(R2), the three byte-path bodies, and `^~ /proxy/relay/` with the two sentences of its own comment
that become false.


```diff
diff --git a/docker/nginx.conf b/docker/nginx.conf
index b9155b83..6be88610 100644
--- a/docker/nginx.conf
+++ b/docker/nginx.conf
@@ -22,6 +22,20 @@ upstream relay_py {
     server RELAY_UPSTREAM;
 }
 
+# The Go relay (Phase 2 stage 2d). A second literal upstream group, not a
+# second entry in the $relay_upstream map: the map keys on $relay_name,
+# which authorize_views.py sets to one process-wide constant, so it cannot
+# say "these four locations resolve differently than those five" (D3, and
+# ADR 0005's canary machinery is deliberately not used here). RELAY_GO_UPSTREAM
+# is sed'd at boot exactly like RELAY_UPSTREAM above, from
+# DISPATCHARR_RELAY_GO_PORT -- 127.0.0.1:<port> outside modular,
+# <relay host>:<port> in modular. Same load-time resolution caveat as
+# relay_py: the Go relay runs in the same `relay` container/role, so the
+# existing depends_on already covers it.
+upstream relay_go {
+    server RELAY_GO_UPSTREAM;
+}
+
 # $relay_name is set per relay-bound location by auth_request_set, from the
 # X-Relay-Name header the authorize hop returns (settings.RELAY_DEFAULT_NAME,
 # "py" in Phase 1). auth_request_set is the ONLY context in which a
@@ -32,8 +46,12 @@ upstream relay_py {
 # variable holding a bare host:port needs a `resolver` and fails without
 # one, while a declared group needs none. Phase 2's canary is a second map
 # entry and a second upstream block — not a code change on either side
-# (ADR 0005). `default` covers the two relay-bound locations that run no
-# subrequest, where $relay_name is unset.
+# (ADR 0005). Since stage 2d-3 every location still passing to
+# $relay_upstream runs the hop, so $relay_name is always set and `default`
+# is a fallback rather than a route: the two relay-bound locations that run
+# no subrequest -- ^~ /proxy/relay/ and the nested recordings regex -- name
+# their upstream group literally and never consulted this map even before
+# the flip.
 map $relay_name $relay_upstream {
     default relay_py;
     py      relay_py;
@@ -278,19 +296,44 @@ server {
         auth_request_set $authorize_status $upstream_http_x_authorize_status;
         error_page 403 = @authorize_denied;
 
-        include uwsgi_params;
-        uwsgi_param HTTP_X_DISPATCHARR_AUTHORIZED "RELAY_TRUST_TOKEN";
-        uwsgi_param HTTP_X_RELAY_CHANNEL $relay_channel;
-        uwsgi_param HTTP_X_RELAY_OUTPUT  $relay_output;
-        uwsgi_param HTTP_X_RELAY_CLIENT  $relay_client;
-        uwsgi_param HTTP_X_RELAY_USER    $relay_user;
-        uwsgi_param HTTP_X_RELAY_OUTPUT_FORMAT $relay_output_format;
-        uwsgi_param HTTP_X_RELAY_CLIENT_IP     $relay_client_ip;
-        uwsgi_buffering off;
-        uwsgi_read_timeout 300s;
-        uwsgi_send_timeout 300s;
+        # The six server-level proxy_set_header directives (:51-56) are
+        # RE-DECLARED here, not inherited. proxy_set_header is an array
+        # directive: a location that declares any of its own inherits none
+        # from the enclosing level -- the identical rule
+        # dispatcharr_api_params.conf's header documents for uwsgi_param.
+        # Without these the Go relay sees Host: relay_go, no X-Real-IP and
+        # no X-Forwarded-For, and every live client's ip_address on both
+        # status endpoints silently becomes nginx's own address. Simple
+        # directives (client_max_body_size, proxy_read_timeout) inherit
+        # normally and are NOT at risk -- repeating those too would be
+        # over-correcting.
+        proxy_set_header X-Real-IP $remote_addr;
+        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
+        proxy_set_header X-Forwarded-Host $host:$server_port;
+        proxy_set_header X-Forwarded-Proto $scheme;
+        proxy_set_header Host $host;
+        proxy_set_header X-Forwarded-Port $server_port;
+        # proxy_set_header unconditionally SETS the outgoing header, which is
+        # what overrides whatever the client sent under the same name -- the
+        # same second layer the HTTP_-prefixed uwsgi_param rule provided.
+        proxy_set_header X-Dispatcharr-Authorized "RELAY_TRUST_TOKEN";
+        proxy_set_header X-Relay-Channel $relay_channel;
+        proxy_set_header X-Relay-Output  $relay_output;
+        proxy_set_header X-Relay-Client  $relay_client;
+        proxy_set_header X-Relay-User    $relay_user;
+        proxy_set_header X-Relay-Output-Format $relay_output_format;
+        proxy_set_header X-Relay-Client-IP     $relay_client_ip;
+        # proxy_buffering, NOT uwsgi_buffering: uwsgi_buffering is inert under
+        # proxy_pass, and a buffered live TS stream gets spooled to disk. This
+        # is CLAUDE.md's historical incident arriving from the opposite
+        # direction -- the wrong protocol's directive for the new protocol.
+        proxy_buffering off;
+        proxy_request_buffering off;
+        proxy_http_version 1.1;
+        proxy_read_timeout 300s;
+        proxy_send_timeout 300s;
         client_max_body_size 0;
-        uwsgi_pass $relay_upstream;
+        proxy_pass http://relay_go;
     }
     location ^~ /proxy/vod/ {
         auth_request /_dispatcharr/authorize;
@@ -361,18 +404,24 @@ server {
     # blanking include is still here, so a client-supplied X-Relay-*
     # header never reaches the relay on this path.
     #
-    # No uwsgi_buffering off: these serve short JSON, not a stream.
-    # uwsgi_read_timeout is explicit rather than nginx's 60s default
+    # No proxy_buffering off: these serve short JSON, not a stream.
+    # proxy_read_timeout is explicit rather than nginx's 60s default
     # because one route has a real budget behind it --
     # POST .../advance waits on ChannelService.change_stream_url, whose
     # non-owner path polls for the owner's confirmation for up to
     # STREAM_SWITCH_CONFIRM_TIMEOUT = 15s. relay_client's own read
     # timeout for that call is 20s; 30s here leaves the client's timeout
     # as the one that fires.
+    #
+    # Go-relay-bound since stage 2d-3, and the ONLY flipped location that
+    # deliberately re-declares none of the six server-level
+    # proxy_set_header lines: its client is Django, not a viewer, and the
+    # Go control API reads neither a forwarded address nor a forwarded
+    # Host. Losing Host: $host between two internal processes is inert.
     location ^~ /proxy/relay/ {
-        include /etc/nginx/dispatcharr_api_params.conf;
-        uwsgi_read_timeout 30s;
-        uwsgi_pass relay_py;
+        include /etc/nginx/dispatcharr_api_params_proxy.conf;
+        proxy_read_timeout 30s;
+        proxy_pass http://relay_go;
     }
     location ^~ /live/ {
         auth_request /_dispatcharr/authorize;
@@ -386,19 +435,44 @@ server {
         auth_request_set $authorize_status $upstream_http_x_authorize_status;
         error_page 403 = @authorize_denied;
 
-        include uwsgi_params;
-        uwsgi_param HTTP_X_DISPATCHARR_AUTHORIZED "RELAY_TRUST_TOKEN";
-        uwsgi_param HTTP_X_RELAY_CHANNEL $relay_channel;
-        uwsgi_param HTTP_X_RELAY_OUTPUT  $relay_output;
-        uwsgi_param HTTP_X_RELAY_CLIENT  $relay_client;
-        uwsgi_param HTTP_X_RELAY_USER    $relay_user;
-        uwsgi_param HTTP_X_RELAY_OUTPUT_FORMAT $relay_output_format;
-        uwsgi_param HTTP_X_RELAY_CLIENT_IP     $relay_client_ip;
-        uwsgi_buffering off;
-        uwsgi_read_timeout 300s;
-        uwsgi_send_timeout 300s;
+        # The six server-level proxy_set_header directives (:51-56) are
+        # RE-DECLARED here, not inherited. proxy_set_header is an array
+        # directive: a location that declares any of its own inherits none
+        # from the enclosing level -- the identical rule
+        # dispatcharr_api_params.conf's header documents for uwsgi_param.
+        # Without these the Go relay sees Host: relay_go, no X-Real-IP and
+        # no X-Forwarded-For, and every live client's ip_address on both
+        # status endpoints silently becomes nginx's own address. Simple
+        # directives (client_max_body_size, proxy_read_timeout) inherit
+        # normally and are NOT at risk -- repeating those too would be
+        # over-correcting.
+        proxy_set_header X-Real-IP $remote_addr;
+        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
+        proxy_set_header X-Forwarded-Host $host:$server_port;
+        proxy_set_header X-Forwarded-Proto $scheme;
+        proxy_set_header Host $host;
+        proxy_set_header X-Forwarded-Port $server_port;
+        # proxy_set_header unconditionally SETS the outgoing header, which is
+        # what overrides whatever the client sent under the same name -- the
+        # same second layer the HTTP_-prefixed uwsgi_param rule provided.
+        proxy_set_header X-Dispatcharr-Authorized "RELAY_TRUST_TOKEN";
+        proxy_set_header X-Relay-Channel $relay_channel;
+        proxy_set_header X-Relay-Output  $relay_output;
+        proxy_set_header X-Relay-Client  $relay_client;
+        proxy_set_header X-Relay-User    $relay_user;
+        proxy_set_header X-Relay-Output-Format $relay_output_format;
+        proxy_set_header X-Relay-Client-IP     $relay_client_ip;
+        # proxy_buffering, NOT uwsgi_buffering: uwsgi_buffering is inert under
+        # proxy_pass, and a buffered live TS stream gets spooled to disk. This
+        # is CLAUDE.md's historical incident arriving from the opposite
+        # direction -- the wrong protocol's directive for the new protocol.
+        proxy_buffering off;
+        proxy_request_buffering off;
+        proxy_http_version 1.1;
+        proxy_read_timeout 300s;
+        proxy_send_timeout 300s;
         client_max_body_size 0;
-        uwsgi_pass $relay_upstream;
+        proxy_pass http://relay_go;
     }
     location ^~ /movie/ {
         auth_request /_dispatcharr/authorize;
@@ -509,19 +583,44 @@ server {
         auth_request_set $authorize_status $upstream_http_x_authorize_status;
         error_page 403 = @authorize_denied;
 
-        include uwsgi_params;
-        uwsgi_param HTTP_X_DISPATCHARR_AUTHORIZED "RELAY_TRUST_TOKEN";
-        uwsgi_param HTTP_X_RELAY_CHANNEL $relay_channel;
-        uwsgi_param HTTP_X_RELAY_OUTPUT  $relay_output;
-        uwsgi_param HTTP_X_RELAY_CLIENT  $relay_client;
-        uwsgi_param HTTP_X_RELAY_USER    $relay_user;
-        uwsgi_param HTTP_X_RELAY_OUTPUT_FORMAT $relay_output_format;
-        uwsgi_param HTTP_X_RELAY_CLIENT_IP     $relay_client_ip;
-        uwsgi_buffering off;
-        uwsgi_read_timeout 300s;
-        uwsgi_send_timeout 300s;
+        # The six server-level proxy_set_header directives (:51-56) are
+        # RE-DECLARED here, not inherited. proxy_set_header is an array
+        # directive: a location that declares any of its own inherits none
+        # from the enclosing level -- the identical rule
+        # dispatcharr_api_params.conf's header documents for uwsgi_param.
+        # Without these the Go relay sees Host: relay_go, no X-Real-IP and
+        # no X-Forwarded-For, and every live client's ip_address on both
+        # status endpoints silently becomes nginx's own address. Simple
+        # directives (client_max_body_size, proxy_read_timeout) inherit
+        # normally and are NOT at risk -- repeating those too would be
+        # over-correcting.
+        proxy_set_header X-Real-IP $remote_addr;
+        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
+        proxy_set_header X-Forwarded-Host $host:$server_port;
+        proxy_set_header X-Forwarded-Proto $scheme;
+        proxy_set_header Host $host;
+        proxy_set_header X-Forwarded-Port $server_port;
+        # proxy_set_header unconditionally SETS the outgoing header, which is
+        # what overrides whatever the client sent under the same name -- the
+        # same second layer the HTTP_-prefixed uwsgi_param rule provided.
+        proxy_set_header X-Dispatcharr-Authorized "RELAY_TRUST_TOKEN";
+        proxy_set_header X-Relay-Channel $relay_channel;
+        proxy_set_header X-Relay-Output  $relay_output;
+        proxy_set_header X-Relay-Client  $relay_client;
+        proxy_set_header X-Relay-User    $relay_user;
+        proxy_set_header X-Relay-Output-Format $relay_output_format;
+        proxy_set_header X-Relay-Client-IP     $relay_client_ip;
+        # proxy_buffering, NOT uwsgi_buffering: uwsgi_buffering is inert under
+        # proxy_pass, and a buffered live TS stream gets spooled to disk. This
+        # is CLAUDE.md's historical incident arriving from the opposite
+        # direction -- the wrong protocol's directive for the new protocol.
+        proxy_buffering off;
+        proxy_request_buffering off;
+        proxy_http_version 1.1;
+        proxy_read_timeout 300s;
+        proxy_send_timeout 300s;
         client_max_body_size 0;
-        uwsgi_pass $relay_upstream;
+        proxy_pass http://relay_go;
     }
 
     # --- Plain prefix fallback: SPA + everything else. NEVER ^~ -- that
```

### Appendix B — `docker/dispatcharr_api_params_proxy.conf` (new file, verbatim)

```nginx
# The proxy_pass twin of dispatcharr_api_params.conf, included by the one
# relay-bound location that is Go-relay-bound AND deliberately outside the
# authorize hop: ^~ /proxy/relay/ (spec amendment S8).
#
# Why it exists: proxy_pass_request_headers is on by default, so a client's
# own X-Dispatcharr-Authorized or X-Relay-* header would otherwise reach the
# Go relay untouched. proxy_set_header with an empty value does not forward
# an empty header -- nginx drops the client's header and sends nothing under
# that name -- which is the same outcome the HTTP_-prefixed uwsgi_param ""
# rule produces on the uwsgi side, and the correct one: a request on this
# location was never authorized by a subrequest.
#
# Why an include repeated per location rather than a server-level block: the
# same replace-not-merge rule dispatcharr_api_params.conf's header states for
# uwsgi_param. proxy_set_header is an array directive, so a location that
# declares any of its own inherits none from the enclosing level.
#
# DELIBERATELY no twin of the six server-level proxy_set_header lines that
# nginx.conf declares at :51-56 (X-Real-IP, X-Forwarded-For,
# X-Forwarded-Host, X-Forwarded-Proto, Host, X-Forwarded-Port). The three
# byte-path locations re-declare all six because a viewer's address is
# externally observable there (parity-matrix row 17); this location's client
# is Django, not a viewer, and the Go control API reads neither a forwarded
# address nor a forwarded Host. Losing Host: $host on a JSON API between two
# internal processes is inert.
#
# There is no `include uwsgi_params;` counterpart: uwsgi_params exists to
# build the uwsgi wire protocol's variable block, which proxy_pass does not
# speak.
#
# Why it matters at all: D1 keeps one urlconf in both processes, so every
# Django-bound location can reach a stream view.
proxy_set_header X-Dispatcharr-Authorized "";
proxy_set_header X-Relay-Channel "";
proxy_set_header X-Relay-Output  "";
proxy_set_header X-Relay-Client  "";
proxy_set_header X-Relay-User    "";
proxy_set_header X-Relay-Output-Format "";
proxy_set_header X-Relay-Client-IP     "";
```

### Appendix C — `docker/Dockerfile`

Without this line nginx fails config load with `open()
"/etc/nginx/dispatcharr_api_params_proxy.conf" failed (2: No such file or directory)` and the
container does not start — reproduced by building, and by the reviewer independently.


```diff
diff --git a/docker/Dockerfile b/docker/Dockerfile
index 6f2a3465..349a6b9c 100644
--- a/docker/Dockerfile
+++ b/docker/Dockerfile
@@ -63,6 +63,7 @@ COPY . /app
 # Copy nginx configuration
 COPY ./docker/nginx.conf /etc/nginx/sites-enabled/default
 COPY ./docker/dispatcharr_api_params.conf /etc/nginx/dispatcharr_api_params.conf
+COPY ./docker/dispatcharr_api_params_proxy.conf /etc/nginx/dispatcharr_api_params_proxy.conf
 # Fix line endings and make entrypoint scripts executable
 RUN for f in /app/docker/entrypoint*.sh; do \
     if [ -f "$f" ]; then \
```

### Appendix D — the boot-time plumbing

**D.1 — `docker/init/03-init-dispatcharr.sh`**, the `RELAY_GO_UPSTREAM` sed (R4/A10.16), inside the
same `all`/`api` role gate and reusing the `RELAY_HOST` that block already computed:


```diff
diff --git a/docker/init/03-init-dispatcharr.sh b/docker/init/03-init-dispatcharr.sh
index 9c10f043..0870e68d 100644
--- a/docker/init/03-init-dispatcharr.sh
+++ b/docker/init/03-init-dispatcharr.sh
@@ -92,6 +92,22 @@ if [[ "$DISPATCHARR_ROLE" == "all" || "$DISPATCHARR_ROLE" == "api" ]]; then
     fi
     sed -i "s/RELAY_UPSTREAM/${RELAY_HOST}:${RELAY_PORT}/g" /etc/nginx/sites-enabled/default
 
+    # The Go relay's upstream (Phase 2 stage 2d), same shape and the same
+    # RELAY_HOST -- so modular gets the relay service name and every other
+    # shape gets loopback, with no second hostname-validation branch. Read
+    # from DISPATCHARR_RELAY_GO_PORT rather than baking 5658:
+    # relay/config/config.go binds from that variable and
+    # docker/healthcheck.sh probes it, so an operator who sets it would
+    # otherwise get the relay on their port and nginx proxying to 5658 --
+    # a 502 on every tune, in exactly the deployments that customise ports
+    # because something else already occupies the defaults.
+    RELAY_GO_PORT="${DISPATCHARR_RELAY_GO_PORT:-5658}"
+    if ! [[ "$RELAY_GO_PORT" =~ ^[0-9]+$ ]]; then
+        echo "⚠️  Warning: DISPATCHARR_RELAY_GO_PORT is not a valid integer, using default port 5658"
+        RELAY_GO_PORT=5658
+    fi
+    sed -i "s/RELAY_GO_UPSTREAM/${RELAY_HOST}:${RELAY_GO_PORT}/g" /etc/nginx/sites-enabled/default
+
     # The relay's trust marker: HMAC(SECRET_KEY, "relay-trust"), the value
     # nginx puts in X-Dispatcharr-Authorized on every relay-bound location
     # (Phase 1 PR 5, D11). python3 rather than openssl: the entrypoint
```

**D.2 — `docker/entrypoint.sh`**, the `DISPATCHARR_RELAY_GO_PORT` default:


```diff
diff --git a/docker/entrypoint.sh b/docker/entrypoint.sh
index 4bf5d8b6..136e44f4 100755
--- a/docker/entrypoint.sh
+++ b/docker/entrypoint.sh
@@ -229,6 +229,11 @@ export DISPATCHARR_API_HARAKIRI=${DISPATCHARR_API_HARAKIRI:-120}
 export DISPATCHARR_API_MAX_REQUESTS=${DISPATCHARR_API_MAX_REQUESTS:-5000}
 export DISPATCHARR_RELAY_GEVENT=${DISPATCHARR_RELAY_GEVENT:-1600}
 export DISPATCHARR_RELAY_PORT=${DISPATCHARR_RELAY_PORT:-5657}
+# Not a uWSGI $(VAR), unlike the four above: relay-go reads it directly
+# (relay/config/config.go), docker/healthcheck.sh probes it, and
+# docker/init/03-init-dispatcharr.sh seds the nginx upstream from it.
+# Exported here so all three see one value.
+export DISPATCHARR_RELAY_GO_PORT=${DISPATCHARR_RELAY_GO_PORT:-5658}
 
 # Translate Dispatcharr POSTGRES_SSL_* env vars into libpq-recognized PGSSL*
 # env vars. Called once before any external PostgreSQL connection; all child
```

**D.3 — `docker/supervisord.d/relay-go.conf`**: the dev-routes variable (R3/A10.2), the `nice`
prefix (R11/A10.9), the header's "THREE DIFFERENCES" becoming four, and item 1 gaining the sentence
that names R10's new test. `priority=205` is **unchanged** — R10's test asserts it.


```diff
diff --git a/docker/supervisord.d/relay-go.conf b/docker/supervisord.d/relay-go.conf
index a12529cb..585906b7 100644
--- a/docker/supervisord.d/relay-go.conf
+++ b/docker/supervisord.d/relay-go.conf
@@ -2,7 +2,7 @@
 # relay rung picks it up through its existing relay-*.conf glob, the two
 # `all` rungs name it explicitly.
 #
-# THREE DIFFERENCES FROM relay-uwsgi.conf, each deliberate:
+# FOUR DIFFERENCES FROM relay-uwsgi.conf, each deliberate:
 #
 # 1. priority=205, the SAME as relay-uwsgi, not 206. supervisord stops one
 #    priority group at a time and waits out each group's stopwaitsecs before
@@ -10,7 +10,8 @@
 #    155s today, against a 160s stop_grace_period. A separate priority with
 #    stopwaitsecs=20 would take it to 175s and start SIGKILLing every deploy
 #    mid-shutdown. Sharing the group makes the two stop concurrently and the
-#    group cost max(20, 20).
+#    group cost max(20, 20). Asserted since stage 2d-3 by
+#    relay/drain/supervisord_priority_test.go, which reads both confs.
 #
 # 2. No wait-for-stores.sh wrapper. The Go relay opens no Postgres connection
 #    and no Redis connection -- those are the phase's two checkable invariants
@@ -18,13 +19,28 @@
 #    /data/jwt, and docker/entrypoint.sh blocks on that file for every role
 #    before it execs supervisord, so it is present by the time this starts.
 #
-# 3. No `nice`. UWSGI_NICE_LEVEL exists to keep the streaming path ahead of
-#    Celery; at 2c-1 this process serves two health endpoints. It joins the
-#    uWSGI nice level in 2c-2, when it starts carrying bytes.
+# 3. It carries the SAME `nice` as relay-uwsgi and api-uwsgi. Added at 2d-3,
+#    the PR that first routes nginx here: UWSGI_NICE_LEVEL exists to keep the
+#    streaming path ahead of Celery, and from the flip onward this process IS
+#    the streaming path. At the default (0) the prefix is inert; for an
+#    operator who took the documented UWSGI_NICE_LEVEL=-5 -- a commented
+#    example in four compose files at five places, including
+#    docker/docker-compose.yml:190 for the `relay:` service this runs in --
+#    its absence would have made the byte-carrying process the lowest-priority
+#    of the three. GNU nice asked for a negative value without CAP_SYS_NICE
+#    warns on stderr and still execs, so the prefix degrades to the old
+#    behaviour rather than producing a supervisord BACKOFF loop.
+#
+# 4. DISPATCHARR_RELAY_GO_DEV_ROUTES=1 in `environment=`. relay/httpapi/
+#    server.go registers every route but /healthz and /readyz behind
+#    config.DevRoutes, so without this the flip produces a 404 on every tune.
+#    Set here rather than by deleting the flag or inverting its default (spec
+#    A10.2): it keeps the flip and the routes it needs one reviewable change,
+#    and reverting the image reverts both -- D3's rollback story.
 [program:relay-go]
-command=setpriv --reuid=%(ENV_POSTGRES_USER)s --regid=%(ENV_POSTGRES_USER)s --init-groups /usr/local/bin/relay-go
+command=nice -n %(ENV_UWSGI_NICE_LEVEL)s setpriv --reuid=%(ENV_POSTGRES_USER)s --regid=%(ENV_POSTGRES_USER)s --init-groups /usr/local/bin/relay-go
 directory=/app
-environment=HOME="%(ENV_DISPATCHARR_HOME)s",USER="%(ENV_POSTGRES_USER)s"
+environment=HOME="%(ENV_DISPATCHARR_HOME)s",USER="%(ENV_POSTGRES_USER)s",DISPATCHARR_RELAY_GO_DEV_ROUTES="1"
 priority=205
 autostart=true
 autorestart=true
```

### Appendix E — `relay/drain/supervisord_priority_test.go` (new file, verbatim)

Written, compiled and run during planning: `go test -race` passes, `go vet` is clean,
`golangci-lint run ./...` reports `0 issues.`, and both of Task 3's break-checks were executed
against this exact text.

```go
package drain

import (
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// supervisordPriorityRe finds the ONE key this test's claim rests on. Anchored
// and comment-aware, for the same reason supervisordStopWaitRe in drain_test.go
// is: `#priority=206` in a note must not be read as the setting, and
// supervisord's own ini parser would not read it either.
var supervisordPriorityRe = regexp.MustCompile(`(?m)^[ \t]*priority[ \t]*=[ \t]*([0-9]+)[ \t]*$`)

// supervisordPriority reads one program conf's priority= out of the file that
// actually ships. It FAILS rather than skipping or defaulting when the file or
// the key is missing -- a helper that fell back to 205 would turn a renamed or
// deleted key into a permanently green test asserting a relationship nothing in
// the repository states any more, which is the silence-read-as-pass shape this
// test exists to avoid one level up.
func supervisordPriority(t *testing.T, conf string) int {
	t.Helper()
	rel := filepath.Join("docker", "supervisord.d", conf)
	path := filepath.Join(relaytest.RepoRoot(), rel)
	raw, err := os.ReadFile(path) // #nosec G304 -- a path this test computed from the repo root
	if err != nil {
		t.Fatalf("cannot read %s: %v -- this test's whole claim is a relationship between two "+
			"supervisord confs, so it must not pass without reading both", rel, err)
	}
	match := supervisordPriorityRe.FindSubmatch(raw)
	if match == nil {
		t.Fatalf("%s declares no priority=<n>. Either supervisord's start/stop ordering for this "+
			"program moved to another key, or it was removed -- both change what this test is "+
			"asserting, so neither may be defaulted through", rel)
	}
	value, err := strconv.Atoi(string(match[1]))
	if err != nil { // unreachable while the pattern is [0-9]+, kept so a widened pattern cannot pass silently
		t.Fatalf("%s: priority=%q is not an integer: %v", rel, match[1], err)
	}
	return value
}

// The container's stop budget is a SUM ACROSS PRIORITY GROUPS, not a maximum:
// supervisord signals one group at a time and waits out that group's
// stopwaitsecs before moving on. relay-go and relay-uwsgi share priority=205
// deliberately, so the pair costs max(20, 20) = 20s rather than 20 + 20; a
// priority of its own would take the container total from 155s to 175s against
// docker-compose's 160s stop_grace_period and start SIGKILLing every deploy
// mid-shutdown.
//
// That arithmetic is stated as a comment in relay-go.conf:7-13 and, until
// stage 2d-3, asserted by nothing at all -- drain_test.go reads stopwaitsecs
// and only stopwaitsecs. After 2d the claim stays load-bearing, because
// relay-uwsgi survives narrowed to VOD and catch-up, so the shared group
// survives with it.
//
// READ from both confs rather than restated as Go constants, for the reason
// drain_test.go's own helper gives: a derived threshold copied into the test
// goes stale silently.
func TestBothRelayProgramsShareOnePriorityGroup(t *testing.T) {
	goPriority := supervisordPriority(t, "relay-go.conf")
	uwsgiPriority := supervisordPriority(t, "relay-uwsgi.conf")

	if goPriority != uwsgiPriority {
		t.Fatalf("relay-go.conf declares priority=%d and relay-uwsgi.conf declares priority=%d.\n"+
			"They must share one supervisord priority group: a group of its own adds relay-go's\n"+
			"stopwaitsecs to the container's stop budget as a separate window, taking the sum from\n"+
			"155s to 175s against a 160s stop_grace_period.",
			goPriority, uwsgiPriority)
	}
}
```

Note what this test deliberately does **not** assert: that the shared value is the literal 205.
Pinning the number would turn a deliberate, coordinated move of both confs into a test failure,
where the property that actually matters — one group, one window — is the equality.

### Appendix F — `CLAUDE.md` (verbatim-string replacement script)

A script rather than a diff, because 2d-1 and 2d-2 both edit this file first and every line number
below 200 moves. All six anchors were verified `count == 1` at the re-seeded tree
(`d5be64d5`, i.e. **after** 2d-1's own CLAUDE.md edits landed). Run it from the worktree root; it
exits non-zero if any anchor is not found exactly once.

```python
#!/usr/bin/env python3
import sys

p = "CLAUDE.md"
t = open(p).read()
REPLACEMENTS = [
    # 1. § Architecture -- the relay uWSGI process's route list.
    ("serves `/proxy/ts/stream/`, `/proxy/vod/`, `/proxy/catchup/`, `/streaming/timeshift.php`, "
     "`/proxy/relay/…` and the XC streaming roots",
     "served `/proxy/ts/stream/`, `/proxy/vod/`, `/proxy/catchup/`, `/streaming/timeshift.php`, "
     "`/proxy/relay/…` and the XC streaming roots until Phase 2 stage 2d-3, and since that flip "
     "serves the VOD and catch-up half of them only — `/proxy/vod/`, `/proxy/catchup/`, "
     "`/streaming/timeshift.php`, `/movie/`, `/series/`, `/timeshift/`, plus the nested "
     "recordings-file regex"),

    # 2. § Architecture -- the Go relay's own paragraph.
    ("Still no nginx location routes to it until stage 2d.",
     "Since stage 2d-3 nginx routes four locations to it — `^~ /proxy/ts/stream/`, `^~ /live/`, "
     "the XC three-segment regex and `^~ /proxy/relay/` — by `proxy_pass http://relay_go`, an "
     "`upstream relay_go` sed'd at boot from `DISPATCHARR_RELAY_GO_PORT`, with "
     "`DISPATCHARR_RELAY_GO_DEV_ROUTES=\"1\"` set in `relay-go.conf` because every route but the "
     "two probes is behind that flag. It carries the same `nice -n $(UWSGI_NICE_LEVEL)` as both "
     "uWSGIs from the same commit, and `relay/drain/supervisord_priority_test.go` asserts the "
     "shared `priority=205` by reading both confs."),

    # 3. § Architecture -- the uwsgi_buffering bullet.
    ("- nginx **`uwsgi_buffering off`** on every relay-bound location",
     "- nginx **buffering off, in the directive family that location's `_pass` speaks** — "
     "`proxy_buffering off` on the three Go-bound since stage 2d-3 (`/proxy/ts/stream/`, `/live/`, "
     "the XC three-segment regex), `uwsgi_buffering off` on every relay-bound location still on "
     "`uwsgi_pass`"),

    # 4. § Auth -- the param count and the blanking mechanism.
    ("the marker `X-Dispatcharr-Authorized` (an HMAC of `SECRET_KEY`) and the four `X-Relay-*` "
     "params are overridden to empty on every other location",
     "the marker `X-Dispatcharr-Authorized` (an HMAC of `SECRET_KEY`) and the seven `X-Relay-*` "
     "params are overridden to empty on every other location — by "
     "`dispatcharr_api_params.conf`'s `uwsgi_param … \"\"` lines, and since stage 2d-3 by "
     "`dispatcharr_api_params_proxy.conf`'s `proxy_set_header … \"\"` twin on `^~ /proxy/relay/`"),

    # 5. Operationally -- the bounded relay restart.
    ("**Restarting `relay-uwsgi` is bounded for the process** — a fresh tune is served well inside "
     "the 30s `stopwaitsecs=20` + `startsecs=5` budget.",
     "**Both relay processes restart bounded**, each against the same 30s budget its own conf's "
     "`stopwaitsecs=20` + `startsecs=5` has to fit within: `relay-uwsgi` measured at ~6.9s and, "
     "since stage 2d-3 put live traffic there, `relay-go` at ~17.3s — the difference being D6's "
     "drain, which spends its fifteen seconds inside `stopwaitsecs` where `die-on-term` returns "
     "immediately."),

    # 6. § Testing -- what streaming-split does.
    ("it stops `api-uwsgi` with a stream running and restarts `relay-uwsgi` with a Celery task "
     "queued",
     "it stops `api-uwsgi` with a stream running, and restarts `relay-go` with a stream running "
     "and `relay-uwsgi` with a Celery task queued — two processes, two clocks, since stage 2d-3 "
     "made a `relay-uwsgi` restart invisible to a live viewer"),
]
for old, new in REPLACEMENTS:
    if t.count(old) != 1:
        sys.exit(f"anchor found {t.count(old)} times, expected 1: {old[:70]!r}")
    t = t.replace(old, new)
open(p, "w").write(t)
print("ok, 6 replacements")
```

**Two CLAUDE.md passages are deliberately left alone**, each checked:

- **§ Commands' `all-dev` paragraph.** It says `DISPATCHARR_ENV=dev` "starts **both** `api-uwsgi`
  and `relay-uwsgi` and no nginx, so `:5656` is the API uWSGI and `/proxy/relay/…` is served by the
  API process rather than the relay." Every clause stays true: that rung has no location table to
  flip (R3).
- **§ Auth's "`^~ /proxy/relay/` is deliberately **not** `internal;` in nginx"** sentence. D9's
  reasoning is unaffected by the language change, which is exactly what the fourth buffering test
  asserts.

### Appendix G — the spec: Amendment A13, eight in-place corrections, the Done-log row

Same form, same reason: 2d-1 inserts A11 and 2d-2 inserts A12 into this file before 2d-3 runs. The
A13 insertion anchors on `## Stage 2d — cutover, and its trap`, which puts it **after** A12
automatically without this plan knowing A12's text; the Done-log row anchors on `## Risks` and is
inserted as the **last table row**, `rstrip`ping whatever blank lines the previous inserter left, so
it does not depend on how 2d-2's own insertion was shaped. Every anchor was verified `count == 1` at
the re-seeded tree, and the whole script was **run** there: ten edits, no assertion fired.

This appendix carries the **full** A13 text inline. It is not a list of paragraph summaries for the
implementer to author — that was this plan's first draft and it was wrong.

```python
import pathlib

p = pathlib.Path("docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md")
s = p.read_text()

# ------------------------------------------------------------ 1. A10.1's ruling
OLD = """and require the flip's plan to record that output, naming `Go result`, before the nginx change
merges. Do not perform it from a PR; it is the user's action on repository settings."""
NEW = """and require the flip's plan to record that output, naming `Go result`, before the nginx change
merges. Do not perform it from a PR; it is the user's action on repository settings.
**Satisfied before 2d-3 was planned** (A13.1): re-run at `2f721bfd`, the ruleset requires **seven**
contexts and `Go result` is among them. 2d-3's Task 0 re-verifies it and stops if it regresses."""
assert s.count(OLD) == 1, s.count(OLD)
s = s.replace(OLD, NEW, 1)

# ------------------------------------------- 2. the upstream snippet's baked port
OLD = """    server RELAY_GO_UPSTREAM;   # sed'd at boot by docker/init/03-init-dispatcharr.sh,
                                 # exactly like RELAY_UPSTREAM and NGINX_PORT --
                                 # 127.0.0.1:5658 outside modular, <relay host>:5658 in modular."""
NEW = """    server RELAY_GO_UPSTREAM;   # sed'd at boot by docker/init/03-init-dispatcharr.sh,
                                 # exactly like RELAY_UPSTREAM and NGINX_PORT --
                                 # 127.0.0.1:<port> outside modular, <relay host>:<port> in
                                 # modular, the port from DISPATCHARR_RELAY_GO_PORT (A10.16)."""
assert s.count(OLD) == 1, s.count(OLD)
s = s.replace(OLD, NEW, 1)

# ------------------------------------ 3. entry 3's measurement task, now done
OLD = """**A10.10: this PR's plan
   opens with a measurement task**"""
NEW = """**A10.10: this PR's plan
   opened with a measurement task, and it is done** (A13.1) -- the minimal flip on a throwaway
   `migration/**` branch, full matrix: thirteen of fourteen E2E jobs green, `Lifecycle result`
   green including `puid-pgid`, and the failure set exactly the five assertions named above.
   The original instruction, kept because it is what the plan answers to:
   **its plan opens with a measurement task**"""
assert s.count(OLD) == 1, s.count(OLD)
s = s.replace(OLD, NEW, 1)

# ------------- 4. entry 3's Gate line: the third "re-pointed" sentence (A13.3)
OLD = "spec and the re-pointed forged-marker test."
NEW = ("spec and the re-**verified** forged-marker test -- `authorize-matrix.spec.ts:83` already "
       "requests `/proxy/ts/stream/`, one of the three flipped locations, and passes unedited "
       "under `proxy_pass` (A13.3).")
assert s.count(OLD) == 1, s.count(OLD)
s = s.replace(OLD, NEW, 1)

# --------------------------- 5. § Stage 2d's own "re-pointed" sentence (A13.3)
OLD = """re-pointed at the new location and re-verified to still 403, not assumed to carry over because the
outcome used to be the same."""
NEW = """re-verified to still 403 under `proxy_pass`, not assumed to carry over because the outcome used to
be the same. **It needs no re-pointing** (A13.3): measured at `2f721bfd`, it already requests
`/proxy/ts/stream/<uuid>`, one of the three flipped locations, and it passes unedited on the
flipped tree. What changed is the mechanism under it, and that is pinned statically by the
buffering spec's second test rather than by moving this one."""
assert s.count(OLD) == 1, s.count(OLD)
s = s.replace(OLD, NEW, 1)

# ------------------------------ 6. § Testing's "re-pointed" sentence (A13.3)
OLD = """- **The forged-marker `@contract` test** (Phase 1 PR 5) — re-pointed at the post-flip location in
  `migration/phase2d-nginx-flip`, verified to still 403 under `proxy_pass`, not assumed."""
NEW = """- **The forged-marker `@contract` test** (Phase 1 PR 5) — re-**verified** to still 403 under
  `proxy_pass` in `migration/phase2d-nginx-flip`, not assumed, and not re-pointed: it already
  requests one of the three flipped locations (A13.3)."""
assert s.count(OLD) == 1, s.count(OLD)
s = s.replace(OLD, NEW, 1)

# ------------------------------------------- 7. A10.2's own miscount (A13.10)
OLD = "Four tests pin the flag and none of them obstructs (c)"
NEW = "**Five** tests pin the flag -- corrected from \"four\" by A13.10 -- and none of them obstructs (c)"
assert s.count(OLD) == 1, s.count(OLD)
s = s.replace(OLD, NEW, 1)

# ------------------------------------ 8. A10.10's types.ts unknown, now closed
OLD = "But `e2e/fixtures/types.ts` types three fields of a concept"
NEW = ("**Closed by measurement in A13.2, and the paragraph below is the question rather than the "
       "answer:** all three fields are present and non-null on the flipped tree, and no assertion "
       "in `e2e/` reads any of them. But `e2e/fixtures/types.ts` types three fields of a concept")
assert s.count(OLD) == 1, s.count(OLD)
s = s.replace(OLD, NEW, 1)

# ------------------------------------------------------- 9. Amendment A13
A13 = """#### Amendment A13 (stage 2d-3) — ten rulings from the cutover, measured before it was designed

**Measured at `2f721bfd` and on `migration/phase2d-nginx-flip-measure` (`09bf567b`, PR #324,
closed and deleted once recorded).** That branch carried the minimal flip and nothing else -- no
spec rewrite, no allowlist edit, no `COVERAGE.md`, no matrix edit -- which is what makes its failure
set a design input rather than a guess. Where an item contradicts a sentence in § Stage 2d, its
deletion list or an earlier amendment, that sentence is **edited in place** and the item says so.

**A13.1 — the measurement, its failure set, and one caveat that must not be read as coverage.**
The full `migration/**` matrix on the minimal flip: **E2E thirteen of fourteen jobs green**
(`guards`, `seeded`, `frontend`, `lifecycle`, `streaming-split`, `pristine`, `dvr`,
`streaming-failover`, `streaming`, `upstream`, `Build AIO image`, `Detect relevant changes`), one
failing -- `streaming-greybox`, with exactly five tests: the four in
`nginx-stream-buffering.spec.ts` and `output-profile-sharing.spec.ts`'s Redis half, each with the
message § Stage 2d and A10.10 predict. **`Lifecycle result` green, every job**, including
`puid-pgid`, whose `test_role_split` is the only exercise of the modular shape and therefore the
only place `RELAY_GO_UPSTREAM` seds to a service name rather than loopback. Three things it settled
that were open: **all twenty-two black-box `streaming` specs pass against the Go relay through
nginx**, the first Playwright coverage `relay-go` has ever had (A10.7's "no Playwright project
drives `relay-go` today"); **`streaming-split` passes and goes vacuous** rather than red, exactly as
A10.10 said; and **`guards` is green before any of 2d-3's own `e2e/` edits**, which is what makes
the "these two edits must land in the same commit" claims of A10.10 operative rather than
theoretical. **The caveat, stated rather than papered over**: `Backend Tests` and `Go Tests`
reported success with every heavy job **skipped**, because that branch touches no backend path and
no `relay/` path. The measurement says nothing about either. 2d-3 itself touches `relay/`, so
`go-tests.yml` runs in full there.

**A13.2 — `e2e/fixtures/types.ts`'s three required fields are filled, and nothing is relaxed.**
A10.10 names `worker_id: string` (`:455`), `ip_address: string` (`:456`) and `owner: string | null`
(`:498`) as required properties of a concept the Go relay might not have, and calls it the
un-enumerable part. Measured through the flipped nginx: `ip_address` `"172.26.0.1"` (the real
client), `worker_id` `"unknown"`, `owner` `"unknown"` -- all present, none null. Two further facts
close it rather than luckily passing it: these are compile-time types over a JSON cast, so a missing
field would not have thrown at runtime; and `grep -rn "worker_id\\|ip_address" e2e/` returns
**exactly the two declarations**, with no `.owner` property access anywhere in `e2e/`, so no
assertion in the suite reads any of the three. **Ruling: no type relaxation, no assertion change, no
Go-side fix.** The `"unknown"` for `owner` and `worker_id` is parity-matrix row 14's documented
asymmetry reproduced per D5. A10.10's paragraph is corrected in place.

**A13.3 — the forged-marker test needs re-VERIFYING, not re-POINTING, and three sentences said
otherwise.** `e2e/tests/streaming/authorize-matrix.spec.ts:83` requests
`/proxy/ts/stream/<uuid>` (`:122`) with all five headers forged (`:125-135`) at a
`hidden_from_output` channel, and asserts an exact 403 through `expectRefused` (`:370-391`). That
path **is** one of the three flipped locations, so there is nothing to re-point; and it passes
unedited on the flipped tree, in CI and locally. The spec said "re-pointed at the new location" in
**three** places, not two: § Stage 2d's own paragraph, § Testing's bullet, and deletion-list entry
3's Gate line. All three are corrected in place. What genuinely changed is the mechanism --
`uwsgi_param HTTP_X_…` overriding a client header became `proxy_set_header` unconditionally setting
it -- and the buffering spec's second test is what pins the new mechanism statically while this test
pins the outcome dynamically. Neither alone is the pin.

**A13.4 — `docker/nginx.conf`'s `map` comment is already stale at the seed, and the flip makes it
worse.** `nginx.conf:35-36` ends "`default` covers the two relay-bound locations that run no
subrequest, where `$relay_name` is unset." Both of those locations -- `^~ /proxy/relay/` and the
nested `~ ^/api/channels/recordings/\\d+/file/$` -- pass to the literal group `relay_py`, never
through the map, so the sentence was false before 2d-3 touched anything. After the flip every one of
the six locations still using `$relay_upstream` runs the hop, so `default` covers none at all.
**Ruling: corrected in 2d-3**, in one sentence. It sits three lines from the new `upstream relay_go`
block a reader will be comparing it against, and a comment that misdescribes which locations a map
serves is what makes the next person add the second map entry D3 refused.

**A13.5 — `process-restart.spec.ts` Scenario B becomes two restarts with two clocks, and the
alternative was rejected on a measurement.** A10.10 calls the vacuity "a judgement call the flip's
plan must make rather than discover". The judgement is made on three measured shapes, each timed
from before the blocking `supervisorctl` call to the first 200 aligned TS packets of a fresh tune,
with a stream running: `restart relay-go` **17,311 ms**, `restart relay-uwsgi` **6,867 ms**,
`restart relay-uwsgi relay-go` **23,946 ms** -- the last against the spec's own 30,000 ms ceiling,
6 s of margin on a developer laptop and a configured worst case of 20 + 20 = 40 s, since
supervisorctl stops each named program in turn. **Rejected as a flake.** Retargeting the whole test
at `relay-go` was rejected for a different reason: `relay-go.conf` carries no `wait-for-stores.sh`
by design (its own header: the Go relay "opens no Postgres connection and no Redis connection ... so
it has no store to wait for"), so a process with no Redis client cannot demonstrate that no start
path flushes Redis DB 0 -- it would swap one vacuity for another. **Ruling: one test, two restarts,
two clocks** -- `relay-go` for the live claim, `relay-uwsgi` for D15's Celery claim, each measured
independently against the same ceiling, whose justification is re-derived from `relay-go.conf`'s
own `stopwaitsecs=20`/`startsecs=5` rather than copied. The title changes; nothing pins it
(`e2e/COVERAGE.md` cites the spec by file, and the parity matrix does not cite it at all).

**A13.6 — `e2e/fixtures/greybox/redis.ts` survives; only its allowlist empties.** A10.10 specifies
the `allowlist.ts:76-83` edit and leaves the helper's own fate unstated. **Ruling: empty
`GREYBOX_REDIS.allow` to `[]` with a comment; do not delete the helper and do not delete the
capability.** An empty allowlist is a **stronger** ratchet than a deleted guard -- with it, any
reintroduction of Redis coupling anywhere under `tests/`, `fixtures/` or `setup/` reddens `guards`
by name, and `expectConfined`'s `toEqual` handles the empty case correctly. The helper is also on
`SUBPROCESS.allow` (`allowlist.ts:65`, it imports `node:child_process`), so deleting it is a
three-capability edit inside the cutover PR rather than a one-line one. And it is Phase 3's
single-grep bookmark for CLAUDE.md's own "every greybox test is rewritten or deleted".

**A13.7 — `docker/Dockerfile` needs a `COPY` line that § Stage 2d never names.** The new-file
paragraph specifies `docker/dispatcharr_api_params_proxy.conf`'s contents and its one consumer, and
says nothing about getting it into the image. Without a `COPY` beside `Dockerfile:65`'s uwsgi twin,
nginx fails config load with `open() "/etc/nginx/dispatcharr_api_params_proxy.conf" failed (2: No
such file or directory)` and **the container does not start** -- reproduced by building. One line,
in 2d-3.

**A13.8 — two `e2e/COVERAGE.md` rows beyond A10.10's ownership table.** That table names
`:259-261` (the output-profile-sharing bullet) for PR 3 and assigns `:50` and `:202` to 2d-6. It
names neither `:196`, which states the relay control API "reaches the relay (`uwsgi_pass relay_py`)"
and "still blanks the four `X-Relay-*` params", nor `:197`, which names `uwsgi_buffering off` as the
directive pinned for `/proxy/ts/stream/`. Both are claims 2d-3 falsifies, and both are edited here,
with `:200` (A13.5's two measurements). `:50` and `:202` stay 2d-6's, as A10.10 rules: they describe
mechanisms rather than assert them.

**A13.9 — 2d-3 ships no Go coverage floor edit, and the reason is mechanical.**
`relay/drain/supervisord_priority_test.go` is a `_test.go` file in a package the shipped binary
already links, so it moves none of `scripts/coverage_relay_go.sh --gate`'s three equality checks:
`shape=` (the stopping rule, test command and cover mode), `packages=` (a hash of
`go list -deps .`'s output -- a test file adds no package) or `gomod=`. `statements` is recorded
provenance and never compared, and `missing` is a **maximum**, lower being better, so a test that
reads two files and calls no `drain` function cannot raise it. **If the gate fires anyway, it is a
finding to investigate per package and then per block -- never a floor bump on this PR**, per
`scripts/coverage_relay_go.floor`'s own `HOW TO MOVE THIS FLOOR`.

**A13.10 — two counts corrected, both the spec's own.** (i) A10.13 requires #318 fixed before
2d-4 and notes 2d-3 is the only other 2d PR that runs the Go suite at all:
[#318](https://github.com/D10Scot/Dispatcharr/issues/318) is **CLOSED**, by `16fbb952`, an ancestor
of 2d-3's seed, so that precondition is met and 2d-3 runs `go-tests.yml` against a fixed test.
(ii) A10.2 says "**Four** tests pin the flag" and then enumerates **five** --
`config_test.go:114`, `:126`, `:163-176`, `httpapi/server_test.go:71-105` and
`httpapi/stream_test.go:388-393`. The enumeration is right and the count is the stale half;
corrected in place at no cost, because a reader who trusts the number will look for the fifth and
conclude the list is wrong rather than the count.

"""
ANCHOR = "\n## Stage 2d — cutover, and its trap\n"
assert s.count(ANCHOR) == 1, s.count(ANCHOR)
s = s.replace(ANCHOR, "\n" + A13 + ANCHOR.lstrip("\n"), 1)

# ---------------------------------------------------------- 10. Done-log row
ROW = """| 2d-3 -- the nginx flip (`migration/phase2d-nginx-flip`). Four locations move from `uwsgi_pass` to `proxy_pass http://relay_go` -- the three byte-path ones plus `^~ /proxy/relay/`, without which Django keeps asking the Python relay for a client list it no longer has and every live stream-limit check fails open -- behind a new `upstream relay_go` sed'd at boot from `DISPATCHARR_RELAY_GO_PORT` (A10.16) and a new `dispatcharr_api_params_proxy.conf` blanking twin, with the `COPY` line § Stage 2d never named (A13.7). The three byte-path locations RE-DECLARE all six server-level `proxy_set_header` lines, because `proxy_set_header` is an array directive and a location declaring any of its own inherits none -- uncaught, every live client's `ip_address` silently becomes nginx's own address while VOD and catch-up keep reporting correctly; `/proxy/relay/` deliberately re-declares none. `relay-go.conf` gains `DISPATCHARR_RELAY_GO_DEV_ROUTES="1"` (A10.2, without which every tune 404s) and the `nice` prefix its own comment promised at 2c-2 (A10.9), and `relay/drain/supervisord_priority_test.go` asserts both relay confs share `priority=205` by reading them. The plan opened with A10.10's measurement rather than a guess -- the minimal flip on a throwaway `migration/**` branch, full matrix -- and the failure set was exactly five assertions in two greybox specs, with all twenty-two black-box `streaming` specs passing against the Go relay through nginx for the first time. Amendment A13, ten items, five of which correct A10 or § Stage 2d in place: the forged-marker test needs re-VERIFYING, not re-pointing, because it already requests one of the flipped locations -- and the spec said otherwise in three places, not two (A13.3); `e2e/fixtures/types.ts`'s three required fields are measured present, so nothing is relaxed (A13.2); `streaming-split` Scenario B becomes two restarts with two clocks rather than a retarget, because `relay-go.conf` carries no `wait-for-stores.sh` and a one-command restart of both measured 23,946ms against a 30,000ms ceiling (A13.5); A10.1's precondition is recorded as satisfied (A13.1); and A10.2's own "four tests" is corrected to five (A13.10). A10.12's four contract fields were exercised through the flipped nginx before the plan was written: a transcode tune, an Output Profile tune, the null-`argv` arm answering 500, `avg_chunk_size` at 255,868 (188 x 1361, off the `next-source` answer) and `ip_address` reading the real client rather than nginx. | `migration/phase2d-nginx-flip` | pending |
"""
# Insert as the LAST row of the Done-log table, whatever blank lines separate
# it from the next heading -- 2d-2 inserts its own row here first and this must
# not depend on how many newlines that left behind.
ANCHOR = "\n## Risks\n"
assert s.count(ANCHOR) == 1, s.count(ANCHOR)
head, tail = s.split(ANCHOR, 1)
assert head.rstrip().endswith("|"), "the Done log's last line is not a table row"
s = head.rstrip("\n") + "\n" + ROW + ANCHOR + tail

p.write_text(s)
print("ok, 10 edits")
```

### Appendix H — `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts`

The four-test rewrite, as one diff. The brace-depth `parseLocationBlocks` parser (`:32-60`) is
untouched — it is already directive-agnostic, and the measurement proves it: all four failures were
assertion failures on correctly parsed blocks, none a parse failure.

Three things in this diff are worth reading for:

1. **The JSDoc at `:118-154` goes with the array it documents.** Replacing only the array
   (`:155-165`) would leave 37 lines above the new constants still saying that all nine locations
   are `uwsgi_pass` and that `^~ /proxy/relay/` is `relay_py`.
2. **`FORWARDED_RELAY_PARAMS` becomes `FORWARDED_RELAY_HEADERS` and changes its values**, so test 3
   — which consumes it at `:360-368` inside a `uwsgi_param` regex against
   `dispatcharr_api_params.conf` — derives the old spelling with `uwsgiParamName()` rather than
   keeping a second hand-written list. Without that, test 3 either fails to compile or asserts
   `uwsgi_param X-Relay-Channel ""` against a file that spells it `HTTP_X_RELAY_CHANNEL`.
   `npm run typecheck` is clean on the applied tree.
3. **The six-header assertion is new**, and it is the only thing in the suite that could catch a
   config that pastes the working `uwsgi_*` block and changes only `_pass`.


```diff
diff --git a/e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts b/e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts
index b67d0912..e88e1175 100644
--- a/e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts
+++ b/e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts
@@ -113,81 +113,126 @@ function parseLocationBlocks(config: string): LocationBlock[] {
  * elsewhere would still let a request into a non-relay-bound Django view
  * carry a forged `X-Relay-Channel`, since both processes share one urlconf
  * (D1). The pair together is what makes the trust marker unforgeable.
+ *
+ * Stage 2d-3 splits every assertion below by DIRECTIVE FAMILY rather than
+ * changing what any of them claims. Three of the nine relay-bound locations
+ * moved from uwsgi_pass to proxy_pass http://relay_go, where uwsgi_buffering
+ * is inert and uwsgi_param is meaningless; the properties are identical and
+ * the spellings are not. One assertion is genuinely NEW and is the reason
+ * this file earns its keep at the flip: proxy_set_header is an ARRAY
+ * directive, so a location declaring any of its own inherits none of the six
+ * the server block declares -- and a config that pastes the working uwsgi
+ * block and changes only _pass passes every other assertion here while
+ * reporting nginx's own address as every viewer's ip_address.
  */
 
 /**
- * Every relay-bound location as of Phase 1 PR 4 (docker/nginx.conf), by the
- * exact `target` `parseLocationBlocks` produces for it. Widened from the
- * original single `/proxy/` prefix once that block split into eight
- * relay-bound locations plus the XC three-segment regex — this list is what
- * keeps the buffering pin covering the whole relay surface rather than the
- * one route it happened to be written against.
+ * The six relay-bound locations still served by the Python relay over
+ * `uwsgi_pass` after stage 2d-3: VOD, catch-up, the XC VOD roots and
+ * timeshift.
  *
  * **Exact targets, deliberately, not `startsWith` prefixes.** A prefix test
  * on `/proxy/vod/` also matches the `= /proxy/vod/stats/` and
  * `= /proxy/vod/stop_client/` exact locations, which stay on the API and
- * correctly carry no `uwsgi_buffering off` — the same trap applies to the
- * three `/proxy/catchup/` control routes. Comparing whole targets keeps the
- * filter naming exactly the nine blocks it means.
- *
- * Two locations are absent on purpose, for different reasons: `^~ /proxy/`
- * stays on the API — it is the API's own short IsAdmin control routes, never
- * `uwsgi_pass relay_py`. `^~ /proxy/relay/` *is* relay-bound
- * (`uwsgi_pass relay_py`) but carries no `uwsgi_buffering off`, correctly:
- * it is the relay control API Phase 1 PR 7 mounted, and it serves short
- * JSON rather than a stream. Its own properties are pinned by the fourth
- * test in this file.
- *
- * A third is absent because it cannot appear: PR 4 also routes
- * `^/api/channels/recordings/\d+/file/$` to the relay, but that location is
- * **nested inside `^~ /api/`**, and `parseLocationBlocks` walks by brace
- * depth from each `location` header — so the nested block's lines are part
- * of `/api/`'s own `body`, and it never surfaces as a separate entry with a
- * `target` of its own. Adding it to this list would make the set assertion
- * below fail on a correct config. Its `uwsgi_buffering off` is pinned by
- * `docker/nginx.conf` review and Task 5's grep counts instead.
- *
- * The last entry is the XC three-segment root form: `parseLocationBlocks`
- * strips a regex location's leading `^` from its `target`, so this is the
- * literal the parser produces for
- * `location ~ ^/[^/]+/[^/]+/\d+(?:\.[A-Za-z0-9]+)?$`.
+ * correctly carry no buffering directive at all — the same trap applies to
+ * the three `/proxy/catchup/` control routes. Comparing whole targets keeps
+ * the filter naming exactly the blocks it means.
  */
-const RELAY_BOUND_TARGETS = [
-  '/proxy/ts/stream/',
+const UWSGI_BOUND_TARGETS = [
   '/proxy/vod/',
   '/proxy/catchup/',
-  '/live/',
   '/movie/',
   '/series/',
   '/timeshift/',
   '/streaming/timeshift.php',
+];
+
+/**
+ * The three relay-bound locations stage 2d-3 moved to the Go relay over
+ * `proxy_pass http://relay_go`. The last entry is the XC three-segment root
+ * form: `parseLocationBlocks` strips a regex location's leading `^` from its
+ * `target`, so this is the literal the parser produces for
+ * `location ~ ^/[^/]+/[^/]+/\d+(?:\.[A-Za-z0-9]+)?$`.
+ */
+const PROXY_BOUND_TARGETS = [
+  '/proxy/ts/stream/',
+  '/live/',
   '/[^/]+/[^/]+/\\d+(?:\\.[A-Za-z0-9]+)?$',
 ];
 
+/**
+ * Both halves, for the assertions that are directive-family-agnostic: the
+ * authorize subrequest, the eight `auth_request_set` variables and the
+ * `error_page` that restores the hop's real status.
+ *
+ * Two locations are absent on purpose, for different reasons, and a third
+ * because it cannot appear. `^~ /proxy/` stays on the API — it is the API's
+ * own short IsAdmin control routes, never relay-bound. `^~ /proxy/relay/`
+ * *is* relay-bound — Go-bound since 2d-3 — but runs no hop and carries no
+ * buffering directive, correctly: it is the relay control API Phase 1 PR 7
+ * mounted, and it serves short JSON rather than a stream. Its own properties
+ * are pinned by the fourth test in this file.
+ *
+ * The third is absent because it cannot appear: PR 4 also routes
+ * `^/api/channels/recordings/\d+/file/$` to the relay, but that location is
+ * **nested inside `^~ /api/`**, and `parseLocationBlocks` walks by brace
+ * depth from each `location` header — so the nested block's lines are part
+ * of `/api/`'s own `body`, and it never surfaces as a separate entry with a
+ * `target` of its own. Adding it to either list would make the set
+ * assertions below fail on a correct config. Its `uwsgi_buffering off` is
+ * pinned by `docker/nginx.conf` review and the plan's grep counts instead.
+ */
+const RELAY_BOUND_TARGETS = [...UWSGI_BOUND_TARGETS, ...PROXY_BOUND_TARGETS];
+
+/**
+ * The six the `server` block declares at `docker/nginx.conf:51-56`. Every
+ * `proxy_pass` location must re-declare all six, because `proxy_set_header`
+ * is an array directive and declaring one of your own discards the lot.
+ * Names only: the values are nginx variables this test has no business
+ * duplicating.
+ */
+const SERVER_LEVEL_PROXY_HEADERS = [
+  'X-Real-IP',
+  'X-Forwarded-For',
+  'X-Forwarded-Host',
+  'X-Forwarded-Proto',
+  'Host',
+  'X-Forwarded-Port',
+];
+
 test(
-  'every relay-bound location keeps uwsgi_buffering off',
+  'every relay-bound location keeps buffering off, in its own directive family',
   { tag: '@contract' },
   async () => {
     const { stdout } = await execFileAsync('docker', ['exec', CONTAINER_NAME, 'nginx', '-T']);
     const blocks = parseLocationBlocks(stdout);
-    const relayBlocks = blocks.filter((b) => RELAY_BOUND_TARGETS.includes(b.target));
-
-    // Vacuous-pass guard: if nginx's config ever stops declaring these
-    // locations (renamed, merged, or the relay split reverted), the loop
-    // below would pass over an empty array and this test would silently
-    // stop meaning anything. Fail loudly instead — and assert the full set,
-    // not just "more than zero", so losing eight of the nine is a failure
-    // rather than a pass.
-    expect(
-      relayBlocks.map((b) => b.target).sort(),
-      `expected every relay-bound location in nginx -T's output (${RELAY_BOUND_TARGETS.join(', ')}); found blocks: ${blocks.map((b) => b.header).join(', ')}`
-    ).toEqual([...RELAY_BOUND_TARGETS].sort());
 
-    for (const block of relayBlocks) {
+    // Two halves, two vacuous-pass guards. uwsgi_buffering is INERT under
+    // proxy_pass and proxy_buffering is inert under uwsgi_pass, so asserting
+    // one directive over all nine would pass six and silently mean nothing on
+    // the other three — which is exactly the trap CLAUDE.md's historical
+    // incident describes, arriving from the opposite direction.
+    //
+    // Each half asserts the full set rather than "more than zero", so losing
+    // five of the six (or two of the three) is a failure rather than a pass.
+    for (const [targets, directive] of [
+      [UWSGI_BOUND_TARGETS, 'uwsgi_buffering'],
+      [PROXY_BOUND_TARGETS, 'proxy_buffering'],
+    ] as const) {
+      const found = blocks.filter((b) => targets.includes(b.target));
       expect(
-        block.body.some((line) => /^\s*uwsgi_buffering\s+off\s*;/.test(line)),
-        `location block "${block.header}" does not set uwsgi_buffering off:\n${block.body.map((l) => l.replace(/"[0-9a-f]{64}"/, '"<marker>"')).join('\n')}`
-      ).toBe(true);
+        found.map((b) => b.target).sort(),
+        `expected every ${directive} relay-bound location in nginx -T's output ` +
+          `(${targets.join(', ')}); found blocks: ${blocks.map((b) => b.header).join(', ')}`
+      ).toEqual([...targets].sort());
+
+      for (const block of found) {
+        expect(
+          block.body.some((line) => new RegExp(`^\\s*${directive}\\s+off\\s*;`).test(line)),
+          `location block "${block.header}" does not set ${directive} off:\n` +
+            block.body.map((l) => l.replace(/"[0-9a-f]{64}"/, '"<marker>"')).join('\n')
+        ).toBe(true);
+      }
     }
   }
 );
@@ -218,15 +263,23 @@ const AUTH_REQUEST_SET_VARS = [
 // principle 5: capturing a variable and forwarding it are two different
 // things, and a test that checks only the first leaves nine locations'
 // worth of middle unpinned.
-const FORWARDED_RELAY_PARAMS = [
-  'HTTP_X_RELAY_CHANNEL',
-  'HTTP_X_RELAY_OUTPUT',
-  'HTTP_X_RELAY_CLIENT',
-  'HTTP_X_RELAY_USER',
-  'HTTP_X_RELAY_OUTPUT_FORMAT',
-  'HTTP_X_RELAY_CLIENT_IP',
+//
+// HEADER names, not uwsgi_param names: since 2d-3 the same seven values
+// travel as `uwsgi_param HTTP_X_RELAY_CHANNEL` on six locations and
+// `proxy_set_header X-Relay-Channel` on three. One list, two spellings
+// derived from it, so the halves cannot drift apart.
+const FORWARDED_RELAY_HEADERS = [
+  'X-Relay-Channel',
+  'X-Relay-Output',
+  'X-Relay-Client',
+  'X-Relay-User',
+  'X-Relay-Output-Format',
+  'X-Relay-Client-IP',
 ];
 
+/** `X-Relay-Channel` -> `HTTP_X_RELAY_CHANNEL`, nginx's HTTP_-prefixed form. */
+const uwsgiParamName = (header: string) => `HTTP_${header.toUpperCase().replace(/-/g, '_')}`;
+
 test(
   'every relay-bound location authorizes through the hop',
   { tag: '@contract' },
@@ -257,18 +310,21 @@ test(
         ).toBe(true);
       }
 
+      const proxied = PROXY_BOUND_TARGETS.includes(block.target);
+
       // The other half of the chain. auth_request_set copies the
-      // subrequest's response header into a variable; only a
-      // uwsgi_param sends it to the relay -- and the HTTP_-prefixed
-      // form is also what overrides whatever the client sent under the
-      // same name. A location that captures but does not forward looks
-      // correct in the config and silently strips the header.
-      for (const param of FORWARDED_RELAY_PARAMS) {
+      // subrequest's response header into a variable; only a uwsgi_param or
+      // a proxy_set_header sends it to the relay -- and either form is also
+      // what overrides whatever the client sent under the same name. A
+      // location that captures but does not forward looks correct in the
+      // config and silently strips the header.
+      for (const header of FORWARDED_RELAY_HEADERS) {
+        const pattern = proxied
+          ? new RegExp(`^\\s*proxy_set_header\\s+${header}\\s+\\$relay_`)
+          : new RegExp(`^\\s*uwsgi_param\\s+${uwsgiParamName(header)}\\s+\\$relay_`);
         expect(
-          block.body.some((line) =>
-            new RegExp(`^\\s*uwsgi_param\\s+${param}\\s+\\$relay_`).test(line)
-          ),
-          `location "${block.header}" captures but does not forward ${param}`
+          block.body.some((line) => pattern.test(line)),
+          `location "${block.header}" captures but does not forward ${header}`
         ).toBe(true);
       }
 
@@ -277,12 +333,38 @@ test(
       // value is a 64-character hex digest, and the placeholder itself
       // reaching a running container means 03-init-dispatcharr.sh did not
       // substitute it — which would 403 every tune.
-      const marker = block.body.find((line) =>
-        /uwsgi_param\s+HTTP_X_DISPATCHARR_AUTHORIZED/.test(line)
-      );
+      const markerRe = proxied
+        ? /proxy_set_header\s+X-Dispatcharr-Authorized/
+        : /uwsgi_param\s+HTTP_X_DISPATCHARR_AUTHORIZED/;
+      const marker = block.body.find((line) => markerRe.test(line));
       expect(marker, `location "${block.header}" sets no trust marker`).toBeTruthy();
       expect(marker).toMatch(/"[0-9a-f]{64}"/);
 
+      // NEW at 2d-3, and the reason this file earns its keep at the flip.
+      // proxy_set_header is an ARRAY directive: the moment this location
+      // declares one of its own it inherits NONE of the six the server block
+      // declares at nginx.conf:51-56. A config that pastes the working uwsgi
+      // block and changes only _pass satisfies every assertion above and
+      // reports nginx's own address as every viewer's ip_address on both
+      // status endpoints -- invisible in dev, invisible in a smoke test,
+      // wrong in production, while VOD and catch-up keep reporting
+      // correctly. Only the three proxy_pass locations: the fourth flipped
+      // location, ^~ /proxy/relay/, deliberately needs none of the six --
+      // its client is Django, not a viewer -- and is covered by the fourth
+      // test instead.
+      if (proxied) {
+        for (const header of SERVER_LEVEL_PROXY_HEADERS) {
+          expect(
+            block.body.some((line) =>
+              new RegExp(`^\\s*proxy_set_header\\s+${header}\\s`).test(line)
+            ),
+            `location "${block.header}" does not re-declare the server-level ` +
+              `proxy_set_header ${header}; declaring any proxy_set_header of its own ` +
+              'discards all six'
+          ).toBe(true);
+        }
+      }
+
       // Without this, a 404 or 429 decision reaches the viewer as 500:
       // the auth_request module denies verbatim on 401 and 403 only.
       expect(
@@ -326,7 +408,6 @@ test(
       '/output/',
       '/hdhr',
       '/proxy/',
-      '/proxy/relay/',
       '/proxy/ts/status',
       '/proxy/vod/stats/',
       '/proxy/vod/stop_client/',
@@ -353,13 +434,18 @@ test(
     // Asserting the include's presence alone cannot tell a five-name
     // file from a seven-name one, which is exactly the drift 2b-2
     // introduces.
+    //
+    // The uwsgi_param spelling is derived from FORWARDED_RELAY_HEADERS
+    // rather than listed again: 2d-3 changed that constant to hold header
+    // names so the two families cannot drift, and a second hand-written
+    // list here would reintroduce exactly the drift it removed.
     const paramsFile = stdout.match(
       /# configuration file \/etc\/nginx\/dispatcharr_api_params\.conf:\n([\s\S]*?)(?=\n# configuration file |\n*$)/
     );
     expect(paramsFile, 'nginx -T did not dump dispatcharr_api_params.conf').toBeTruthy();
     for (const param of [
       'HTTP_X_DISPATCHARR_AUTHORIZED',
-      ...FORWARDED_RELAY_PARAMS,
+      ...FORWARDED_RELAY_HEADERS.map(uwsgiParamName),
     ]) {
       expect(
         new RegExp(`^\\s*uwsgi_param\\s+${param}\\s+""\\s*;`, 'm').test(paramsFile![1]),
@@ -367,6 +453,25 @@ test(
       ).toBe(true);
     }
 
+    // The proxy_pass twin, new at 2d-3 and asserted for the same reason.
+    // ^~ /proxy/relay/ is the only location that includes it, and the fourth
+    // test below asserts that it does; this asserts the file's contents.
+    const proxyParamsFile = stdout.match(
+      /# configuration file \/etc\/nginx\/dispatcharr_api_params_proxy\.conf:\n([\s\S]*?)(?=\n# configuration file |\n*$)/
+    );
+    expect(
+      proxyParamsFile,
+      'nginx -T did not dump dispatcharr_api_params_proxy.conf'
+    ).toBeTruthy();
+    for (const header of ['X-Dispatcharr-Authorized', ...FORWARDED_RELAY_HEADERS]) {
+      expect(
+        new RegExp(`^\\s*proxy_set_header\\s+${header}\\s+""\\s*;`, 'm').test(
+          proxyParamsFile![1]
+        ),
+        `dispatcharr_api_params_proxy.conf does not blank ${header}`
+      ).toBe(true);
+    }
+
     // The nested recordings-file location never surfaces as its own block
     // (parseLocationBlocks walks by brace depth from each header, so its
     // lines are part of /api/'s body). Assert on that body instead: it is
@@ -397,9 +502,12 @@ test(
     // reads a relay-owned Redis key, which only works if they reach the
     // relay. A literal upstream group, not $relay_upstream: no
     // subrequest runs here, so $relay_name is unset and a variable pass
-    // nothing feeds is a thing a reader has to disprove.
+    // nothing feeds is a thing a reader has to disprove -- and since 2d-3
+    // the group is relay_go, hardcoded rather than mapped, because D3 keeps
+    // the map and relay_py untouched for the five locations that did not
+    // move.
     expect(
-      block!.body.some((line) => /^\s*uwsgi_pass\s+relay_py\s*;/.test(line)),
+      block!.body.some((line) => /^\s*proxy_pass\s+http:\/\/relay_go\s*;/.test(line)),
       'the relay control API must reach the relay'
     ).toBe(true);
 
@@ -422,7 +530,7 @@ test(
     // A client-supplied X-Relay-* header still never reaches the relay
     // on this path.
     expect(
-      block!.body.some((line) => /dispatcharr_api_params\.conf\s*;/.test(line)),
+      block!.body.some((line) => /dispatcharr_api_params_proxy\.conf\s*;/.test(line)),
       'the relay control API must still blank the trust params'
     ).toBe(true);
 
@@ -431,7 +539,7 @@ test(
     // An explicit window above both keeps the client's timeout the one
     // that fires rather than nginx's 60s default.
     expect(
-      block!.body.some((line) => /^\s*uwsgi_read_timeout\s+30s\s*;/.test(line)),
+      block!.body.some((line) => /^\s*proxy_read_timeout\s+30s\s*;/.test(line)),
       'the relay control API needs a read timeout above the advance budget'
     ).toBe(true);
   }
```

**One assertion this rewrite deliberately does NOT add.** Nothing asserts `proxy_http_version 1.1`
or `proxy_request_buffering off`. Both are in the config and both matter, but neither is externally
observable the way the four properties above are, and the file's own rule — every assertion here is
a load-bearing deploy fact, not an inventory of the block — is what keeps it from becoming a
transcription of `nginx.conf` that fails on every ordinary edit.

### Appendix I — `output-profile-sharing.spec.ts` and `allowlist.ts`

**These two must land in the same commit.** `capabilities.spec.ts:130` compares
`GREYBOX_REDIS.allow` with `toEqual` on a sorted array, so removing the last use reddens `guards`
unless the allowlist empties with it, and emptying the allowlist first reddens it the other way.

**I.1 — the Redis half:**


```diff
diff --git a/e2e/tests/streaming-greybox/output-profile-sharing.spec.ts b/e2e/tests/streaming-greybox/output-profile-sharing.spec.ts
index e90711d3..2eb45e70 100644
--- a/e2e/tests/streaming-greybox/output-profile-sharing.spec.ts
+++ b/e2e/tests/streaming-greybox/output-profile-sharing.spec.ts
@@ -2,7 +2,6 @@ import { execFile } from 'node:child_process';
 import { promisify } from 'node:util';
 import { test, expect, expectTsAligned, readChannelStatus } from '../../fixtures';
 import { lockedProfile, newStreamClient } from '../streaming/helpers';
-import { greyboxRedis } from '../../fixtures/greybox/redis';
 
 const execFileAsync = promisify(execFile);
 
@@ -120,28 +119,19 @@ test('two clients on one output profile share a single transcode', { tag: '@char
     // use an ffmpeg-based stream profile, that upstream-side ffmpeg would
     // also match `pgrep -x ffmpeg` and this assertion's basis breaks silently
     // — update this comment and the count if that happens.
-    expect(await countFfmpegProcesses()).toBe(1);
-
-    // The process count proves the row's literal claim; the owner lock below
-    // is complementary, not redundant — it proves the *lock* correctly
-    // tracks the (channel, profile) pair, and its key name is more useful in
-    // a failure message than a bare process count would be.
     //
-    // `RedisKeys.output_owner(channel_id, fmt)` (apps/proxy/live_proxy/redis_keys.py)
-    // builds `live:channel:{channel_id}:output:{fmt}:owner`. The output
-    // profile manager (apps/proxy/live_proxy/output/profile/manager.py)
-    // namespaces its format as `mpegts:p{profile_id}`, and — like every
-    // live_proxy endpoint — `channel_id` here is the channel's UUID string,
-    // never its numeric DB id (confirmed via `stream_ts`'s
-    // `<str:channel_id>` route and `OutputProfileManager`'s own
-    // `channel_id[:8]` log slicing, which only makes sense for a UUID). The
-    // owner key is a single CAS'd string (`SET NX`), not a per-worker set, so
-    // this is an exact key, not a wildcard: KEYS on it can only ever return 0
-    // or 1 result. Length 1 says a manager holds the lock; length 0 would
-    // mean the transcode never started or the key shape above is wrong.
-    const ownerKey = `live:channel:${channel.uuid}:output:mpegts:p${output.id}:owner`;
-    const owners = await greyboxRedis().keys(ownerKey);
-    expect(owners).toHaveLength(1);
+    // There was a second, complementary half here until stage 2d-3: a
+    // `greyboxRedis().keys()` read of
+    // `live:channel:{uuid}:output:mpegts:p{id}:owner`, asserting the manager
+    // held the CAS'd lock. The Go relay writes no `live:channel:*` key at all
+    // — spec D2 deletes `output_owner`/`output_state`, and the sharing is an
+    // in-process registry's refcount — so that assertion returned [] the
+    // moment nginx routed this location to it. Removed rather than rewritten:
+    // there is no Go-side key to point it at, and the process count below
+    // proves the row's literal claim on its own. It was the only
+    // Redis-reading assertion in the whole suite; `e2e/tests/guards/allowlist.ts`'s
+    // GREYBOX_REDIS allowlist is empty as a result.
+    expect(await countFfmpegProcesses()).toBe(1);
   } finally {
     await Promise.all(clients.map((c) => c.close().catch(() => {})));
   }
```

**I.2 — the allowlist:**


```diff
diff --git a/e2e/tests/guards/allowlist.ts b/e2e/tests/guards/allowlist.ts
index ff92eb3c..a6b7d431 100644
--- a/e2e/tests/guards/allowlist.ts
+++ b/e2e/tests/guards/allowlist.ts
@@ -76,10 +76,17 @@ export const SUBPROCESS: Capability = {
 export const GREYBOX_REDIS: Capability = {
   name: 'the grey-box Redis helper',
   why: 'Reads Redis key shapes directly. The keys are internal and the extraction is expected to change them.',
-  allow: [
-    // The one spec the original quarantine.spec.ts allowlisted.
-    'tests/streaming-greybox/output-profile-sharing.spec.ts',
-  ],
+  // EMPTY since Phase 2 stage 2d-3, and deliberately still here rather than
+  // deleted along with `fixtures/greybox/redis.ts`. The suite's last Redis
+  // read — output-profile-sharing.spec.ts's owner-lock assertion — went with
+  // the nginx flip, because the Go relay writes no `live:channel:*` key
+  // (spec D2). An empty allowlist is a STRONGER ratchet than a deleted
+  // guard: with it, any reintroduction of Redis coupling anywhere under
+  // tests/, fixtures/ or setup/ reddens `guards` by name. The helper itself
+  // survives as Phase 3's single-grep bookmark for "every greybox test is
+  // rewritten or deleted", and stays on SUBPROCESS.allow above because it
+  // still imports node:child_process.
+  allow: [],
 };
 
 export const CONTAINER_INTROSPECTION: Capability = {
```

### Appendix J — `process-restart.spec.ts`, Scenario B

R9's ruling as one diff: the ceiling's justification re-derived from both confs, a `relay-go`
restart with its own clock inserted before the Celery half, the `relay-uwsgi` restart keeping its
own, and a **third** cold channel so the second measurement is not a warm re-tune of the first's.

Note the two things a prose appendix would have left the implementer to infer, and which this diff
carries: the `openOutcome(...)` URL at the old `:636` becomes `afterUwsgi.uuid` (the third channel
is useless otherwise), and `streamClient.close()` moves from the Celery half up into the `relay-go`
half, where the comment about the stream dying with its process is true again.


```diff
diff --git a/e2e/tests/streaming-split/process-restart.spec.ts b/e2e/tests/streaming-split/process-restart.spec.ts
index 646dc61c..b32b0cbb 100644
--- a/e2e/tests/streaming-split/process-restart.spec.ts
+++ b/e2e/tests/streaming-split/process-restart.spec.ts
@@ -77,12 +77,25 @@ const API_PROBE = '/api/accounts/initialize-superuser/';
 const RUNNING_TIMEOUT_MS = 60_000;
 
 /**
- * The spec's ceiling for a bounded relay restart, and its own justification:
- * "`stopwaitsecs=20` plus process start has to fit inside it or the restart is
- * not bounded in any useful sense". `docker/supervisord.d/relay-uwsgi.conf`
- * carries `stopwaitsecs=20` and `startsecs=5`, so 25s is the configured worst
- * case and 30s is the budget it has to fit inside. Measured from the moment
- * the restart command is issued, not from when it returns.
+ * The ceiling for a bounded restart of EITHER relay process, and its own
+ * justification: "`stopwaitsecs` plus process start has to fit inside it or
+ * the restart is not bounded in any useful sense". Both
+ * `docker/supervisord.d/relay-go.conf` and
+ * `docker/supervisord.d/relay-uwsgi.conf` carry `stopwaitsecs=20` and
+ * `startsecs=5`, so 25s is the configured worst case for each and 30s is the
+ * budget it has to fit inside. Measured from the moment each restart command
+ * is issued, not from when it returns.
+ *
+ * The two processes spend that window very differently, which is why this
+ * spec restarts both and times them separately rather than restarting one.
+ * `relay-uwsgi` is `die-on-term` and returns in well under a second;
+ * `relay-go` runs D6's drain — a five-second client grace, a concurrent
+ * channel teardown, an `http.Server.Shutdown` and a three-second events flush
+ * reserved out of the total — inside its own `stopwaitsecs`. Measured on a
+ * developer laptop with a stream running: relay-go 17311ms to first bytes,
+ * relay-uwsgi 6867ms. A single `supervisorctl restart relay-uwsgi relay-go`
+ * was measured at 23946ms and rejected: supervisorctl stops each in turn, so
+ * its configured worst case is 20 + 20 = 40s, past this ceiling.
  *
  * What this ceiling covers is the *process*: the relay serving tunes again.
  * Whether a viewer reconnecting to the SAME channel is bounded too is an open
@@ -466,16 +479,18 @@ test(
 );
 
 test(
-  'a relay restart is bounded, and leaves a Celery task queued across it to finish',
+  'both relay processes restart bounded, and a Celery task queued across the uWSGI one still finishes',
   { tag: '@contract' },
   async ({ instance, api, seed, upstream, streamClient, baseURL }) => {
     await expectRunning(instance, 'api-uwsgi', 'api-uwsgi was not RUNNING before this test began');
     await expectRunning(instance, 'relay-uwsgi', 'relay-uwsgi was not RUNNING before this test began');
+    await expectRunning(instance, 'relay-go', 'relay-go was not RUNNING before this test began');
 
     const scenario = await upstream.scenario({
       channels: [
         { id: 1, name: 'split relay running', tvgId: 'split-relay-running.e2e', logo: null },
-        { id: 2, name: 'split relay after', tvgId: 'split-relay-after.e2e', logo: null },
+        { id: 2, name: 'split relay after go', tvgId: 'split-relay-after-go.e2e', logo: null },
+        { id: 3, name: 'split relay after uwsgi', tvgId: 'split-relay-after-uwsgi.e2e', logo: null },
       ],
       rate: 20,
     });
@@ -528,10 +543,16 @@ test(
       channelIds: [1],
       streamProfileId: proxy.id,
     });
-    const { channel: after } = await seed.upstreamChannel(scenario, {
+    // Two cold channels, one per restart: re-tuning the same channel after
+    // the second restart would measure a warm channel rather than a cold one.
+    const { channel: afterGo } = await seed.upstreamChannel(scenario, {
       channelIds: [2],
       streamProfileId: proxy.id,
     });
+    const { channel: afterUwsgi } = await seed.upstreamChannel(scenario, {
+      channelIds: [3],
+      streamProfileId: proxy.id,
+    });
 
     await streamClient.open(`/proxy/ts/stream/${running.uuid}`);
     // 200, not 1: matches Scenario A's precondition idiom. The TS generator
@@ -545,6 +566,58 @@ test(
     // and has no other way to learn its uuid.
     console.log(`[relay-restart] channel ${running.uuid} is streaming before the restart`);
 
+    // ---- restart 1: relay-go, the process that now carries live traffic ----
+    //
+    // Before stage 2d-3 this spec restarted only relay-uwsgi, which was then
+    // the live relay. After the flip a relay-uwsgi restart is invisible to a
+    // viewer — the test did not fail, it went VACUOUS, asserting that a tune
+    // succeeded after restarting a process that had nothing to do with it.
+    // This half restores the claim by restarting the process that does.
+    const goRestartBegan = Date.now();
+    await instance.supervisorctl(['restart', 'relay-go']);
+    console.log(
+      `[relay-restart] relay-go: supervisorctl returned after ${Date.now() - goRestartBegan}ms`
+    );
+
+    // The running stream died with the process it was served by. Closing the
+    // client here is bookkeeping, not an assertion: nothing processed its
+    // disconnect.
+    await streamClient.close();
+    await expectRunning(instance, 'relay-go', 'relay-go did not return to RUNNING');
+
+    const goClient = newStreamClient(baseURL!);
+    await expect
+      .poll(async () => openOutcome(goClient, `/proxy/ts/stream/${afterGo.uuid}`), {
+        // Deliberately above the ceiling. The assertion below is on the
+        // measured number, so an over-budget restart fails with the number it
+        // took rather than with a bare poll timeout — the shape
+        // `tests/streaming/time-to-first-byte.spec.ts` uses.
+        timeout: 120_000,
+        intervals: [1_000],
+        message: 'the Go relay never served a tune after the restart',
+      })
+      .toBe('ok');
+    // 200, not 1: a channel coming up can emit a single synthetic packet that
+    // satisfies expectTsAligned and proves nothing. readPackets throws if the
+    // stream ends short, so a channel that never truly starts fails loudly.
+    const goPacket = await withDeadline(
+      goClient.readPackets(200),
+      60_000,
+      'the first 200 TS packets after the relay-go restart'
+    );
+    const goElapsedMs = Date.now() - goRestartBegan;
+    console.log(
+      `[relay-restart] relay-go: first TS bytes ${goElapsedMs}ms after the restart began ` +
+        `(ceiling ${RELAY_RESTART_CEILING_MS}ms)`
+    );
+    expectTsAligned(goPacket);
+    expect(
+      goElapsedMs,
+      `relay-go served its first bytes ${goElapsedMs}ms after the restart began; the ceiling is ` +
+        `${RELAY_RESTART_CEILING_MS}ms (stopwaitsecs=20 + startsecs=5, with D6's 15s drain inside it)`
+    ).toBeLessThanOrEqual(RELAY_RESTART_CEILING_MS);
+    await goClient.close();
+
     const before = await api.json<M3uAccount>(
       await api.get(`/api/m3u/accounts/${account.id}/`),
       `M3U account ${account.id} before the relay restart`
@@ -591,10 +664,23 @@ test(
         'refresh is not actually contending for a worker slot'
     ).toBe(true);
 
-    const restartBegan = Date.now();
+    // ---- restart 2: relay-uwsgi, for D15's Celery half ----
+    //
+    // relay-uwsgi no longer serves live traffic, but it still exists (narrowed
+    // to VOD and catch-up) and its start path still runs
+    // docker/supervisord.d/wait-for-stores.sh -> scripts/wait_for_redis.py.
+    // That is the one place a reintroduced flush of Redis DB 0 could bite, and
+    // DB 0 holds the Celery broker and result backend as well as the relay's
+    // channel state. relay-go cannot make this claim: it has no
+    // wait-for-stores.sh wrapper by design, because it opens no Redis
+    // connection at all (relay-go.conf's own header). So this restart stays
+    // pointed here — and the tune assertion below is deliberately a SECOND,
+    // independent bounded measurement rather than a repeat of the first.
+    const uwsgiRestartBegan = Date.now();
     await instance.supervisorctl(['restart', 'relay-uwsgi']);
     console.log(
-      `[relay-restart] supervisorctl restart returned after ${Date.now() - restartBegan}ms`
+      `[relay-restart] relay-uwsgi: supervisorctl returned after ` +
+        `${Date.now() - uwsgiRestartBegan}ms`
     );
 
     // In-flight proof, taken the instant the blocking restart call returns:
@@ -621,19 +707,17 @@ test(
         'the poll below would prove nothing about surviving the relay start path'
     ).not.toBe('success:bumped');
 
-    // The running stream died with the process it was served by. Closing the
-    // client here is bookkeeping, not an assertion: nothing processed its
-    // disconnect, so its entry stays in the channel's client set until the
-    // relay's own ghost-client sweep removes it.
-    await streamClient.close();
-
     await expectRunning(instance, 'relay-uwsgi', 'relay-uwsgi did not return to RUNNING');
 
-    // The bounded half: a tune the relay has never served answers with real,
-    // aligned TS bytes inside the ceiling.
+    // The bounded half, second measurement: a tune the Go relay has never
+    // served answers with real, aligned TS bytes inside the same ceiling,
+    // across a restart of the OTHER relay process. After 2d-3 this is the
+    // weaker of the two claims — relay-uwsgi carries no live traffic — but it
+    // is not vacuous: a start path that flushed Redis DB 0 would take the
+    // running relay's channel state with it.
     const client = newStreamClient(baseURL!);
     await expect
-      .poll(async () => openOutcome(client, `/proxy/ts/stream/${after.uuid}`), {
+      .poll(async () => openOutcome(client, `/proxy/ts/stream/${afterUwsgi.uuid}`), {
         // Deliberately above the ceiling. The assertion below is on the
         // measured number, so an over-budget restart fails with the number it
         // took rather than with a bare poll timeout — the shape
@@ -659,18 +743,18 @@ test(
     const packet = await withDeadline(
       client.readPackets(200),
       60_000,
-      'the first 200 TS packets after the relay restart'
+      'the first 200 TS packets after the relay-uwsgi restart'
     );
-    const elapsedMs = Date.now() - restartBegan;
+    const elapsedMs = Date.now() - uwsgiRestartBegan;
     console.log(
-      `[relay-restart] first TS bytes ${elapsedMs}ms after the restart began ` +
+      `[relay-restart] relay-uwsgi: first TS bytes ${elapsedMs}ms after the restart began ` +
         `(ceiling ${RELAY_RESTART_CEILING_MS}ms)`
     );
     expectTsAligned(packet);
     expect(
       elapsedMs,
-      `the relay served its first bytes ${elapsedMs}ms after the restart began; the ceiling is ` +
-        `${RELAY_RESTART_CEILING_MS}ms (stopwaitsecs=20 + startsecs=5)`
+      `relay-uwsgi served its first bytes ${elapsedMs}ms after the restart began; the ceiling ` +
+        `is ${RELAY_RESTART_CEILING_MS}ms (stopwaitsecs=20 + startsecs=5)`
     ).toBeLessThanOrEqual(RELAY_RESTART_CEILING_MS);
     await client.close();
 
```

### Appendix K — `e2e/COVERAGE.md`

Four rows. `:259-261` is a **wrapped bullet**, not a table row, so its anchor spans a newline and
two spaces of indent — a single-line OLD string finds nothing there. The diff carries the wrapping
correctly; that is the point of shipping a diff rather than a replacement instruction.

`:50` (the ownership-lease `todo` row) and `:202` (the reconnect open question) are **not** edited
here — A10.10's table assigns both to 2d-6, because they describe mechanisms rather than assert
them.


```diff
diff --git a/e2e/COVERAGE.md b/e2e/COVERAGE.md
index 869729a2..5e956489 100644
--- a/e2e/COVERAGE.md
+++ b/e2e/COVERAGE.md
@@ -193,11 +193,11 @@ resolve (see the G8/G10 Gap rows).
 | Streaming | **Gap:** the per-user `allowed_networks["STREAMS"]` branch is a cheaper observable for the same scope as the row above, needing no global write: `apps/proxy/live_proxy/views.py:stream_xc` passes `user` to `network_access_allowed`, so pointing one seeded user's `custom_properties.allowed_networks.STREAMS` at a CIDR no client can match makes the XC live route refuse, row-scoped and reversible — the same shape `network-acl.spec.ts` test 4 already proves for `XC_API`. It is a `streaming`-project test (needs a byte-level client), so this row is for whichever goal next owns those projects | G14 | todo |
 | Streaming | Authorize hop: `hidden_from_output` refuses an anonymous UUID tune on `/proxy/ts/stream/`, still refuses a forged `X-Dispatcharr-Authorized`/`X-Relay-*`, and refuses on `/proxy/catchup/` and the XC live root, while an ordinary channel still streams with no credential at all; `is_adult` against a `hide_adult_content` viewer refuses on both native routes (`/proxy/ts/stream/`, `/proxy/catchup/`) and both XC roots (live, timeshift) ([#87](https://github.com/D10Scot/Dispatcharr/issues/87), [#95](https://github.com/D10Scot/Dispatcharr/issues/95)) | P1 | done |
 | Streaming | Relay events: a `dead-air` failover posts `stream_switch` to `/api/relay/events` (not `channel_failover` — that type is reachable only from the ffmpeg buffering-timeout path, structurally dead for the Proxy profile this test locks), Django writes the `SystemEvent` row that `GET /api/core/system-events/` returns, and pushes a `relay_event` WebSocket message whose payload carries the channel uuid and no provider URL | P1 | done |
-| Streaming | Relay control API: `^~ /proxy/relay/` reaches the relay (`uwsgi_pass relay_py`), is not `internal;` so Django can dial it as an ordinary client from the worker role and through the api role's own nginx, runs no `auth_request` because the internal token is the whole gate, still blanks the four `X-Relay-*` params and the `X-Dispatcharr-Authorized` marker, and carries a read timeout above the 15s the owner-confirmation poll can take | P1 | done |
-| Streaming | Time to first byte through nginx: a live channel answers with a valid 188-byte-aligned TS packet within a 10s liveness ceiling, through whichever process serves `/proxy/ts/stream/<uuid>` — written before PR 4 gave that route its own nginx location and unchanged after it, which is what makes it a routing guard rather than a performance test. Deliberately **not** a spooling detector: at the scenario's `rate: 20` a buffered nginx would still forward inside 10s, so the `uwsgi_buffering off` directive is pinned statically in `streaming-greybox/nginx-stream-buffering.spec.ts` instead. `tests/streaming/time-to-first-byte.spec.ts` | P1 | done |
+| Streaming | Relay control API: `^~ /proxy/relay/` reaches the relay (`uwsgi_pass relay_py` until Phase 2 stage 2d-3, `proxy_pass http://relay_go` since), is not `internal;` so Django can dial it as an ordinary client from the worker role and through the api role's own nginx, runs no `auth_request` because the internal token is the whole gate, still blanks the seven `X-Relay-*` params (by `proxy_set_header … ""` since 2d-3) and the `X-Dispatcharr-Authorized` marker, and carries a read timeout above the 15s the owner-confirmation poll can take | P1 | done |
+| Streaming | Time to first byte through nginx: a live channel answers with a valid 188-byte-aligned TS packet within a 10s liveness ceiling, through whichever process serves `/proxy/ts/stream/<uuid>` — written before PR 4 gave that route its own nginx location and unchanged after it, which is what makes it a routing guard rather than a performance test. Deliberately **not** a spooling detector: at the scenario's `rate: 20` a buffered nginx would still forward inside 10s, so the buffering directive is pinned statically in `streaming-greybox/nginx-stream-buffering.spec.ts` instead — `proxy_buffering off` on this route since Phase 2 stage 2d-3, `uwsgi_buffering off` on the six locations still on `uwsgi_pass`. `tests/streaming/time-to-first-byte.spec.ts` | P1 | done |
 | Streaming | The SPA three-segment route still serves the SPA: a deep link shaped like the Xtream `/<user>/<pass>/<id>` root form falls through to the frontend catch-all instead of `stream_xc`, because PR 2 narrowed the URL pattern's `channel_id` segment (`XC_STREAM_ID_PATTERN`) to the numeric-with-optional-extension shape a real stream id has. Without it the route matched first and DRF's exception handler absorbed `get_object_or_404`'s `Http404` before Django's catch-all ever saw it. `tests/streaming/spa-three-segment-route.spec.ts` | P1 | done |
 | Streaming | Django down: with `api-uwsgi` stopped, an already-running stream keeps delivering aligned TS (nothing on the byte path calls Django once a stream runs), an ordinary `/api/` route answers **502** (`uwsgi_pass` failing directly) and a new tune answers **500** (the `auth_request` subrequest failing, which `ngx_http_auth_request_module` reports as its own error — the two codes in one outage are the distinction). Starting `api-uwsgi` again restores tunes, and the pre-existing stream is still flowing afterwards, which is D15 in observable form: no start path flushes Redis DB 0. `tests/streaming-split/process-restart.spec.ts` | P1 | done |
-| Lifecycle | Bounded relay restart: `supervisorctl restart relay-uwsgi` returns the relay to RUNNING and it serves a fresh tune with aligned TS **7559ms** after the restart command was issued, inside the 30s ceiling that `stopwaitsecs=20` plus `startsecs=5` has to fit within. An M3U refresh dispatched immediately before the restart still completes afterwards (`updated_at` bumped, status `success`) — the Celery broker and result backend live in the same Redis DB 0 as the relay's channel state, so a blind flush on a start path would take all three. `tests/streaming-split/process-restart.spec.ts` | P1 | done |
+| Lifecycle | Bounded relay restart, both processes: `supervisorctl restart relay-go` returns it to RUNNING and it serves a fresh tune with aligned TS **17311ms** after the restart command was issued, and `supervisorctl restart relay-uwsgi` the same **6867ms** after its own — each inside the 30s ceiling that `stopwaitsecs=20` plus `startsecs=5` has to fit within, the difference being D6's drain, which spends fifteen seconds inside relay-go's `stopwaitsecs` where `die-on-term` returns immediately. An M3U refresh dispatched immediately before the **relay-uwsgi** restart still completes afterwards (`updated_at` bumped, status `success`) — the Celery broker and result backend live in the same Redis DB 0 as the relay's channel state, so a blind flush on that process's start path would take all three; relay-go cannot make this claim, since it opens no Redis connection and runs no `wait-for-stores.sh`. `tests/streaming-split/process-restart.spec.ts` | P1 | done |
 | Lifecycle | Modular role split: `api`, `relay` and `worker` containers on one network, with TS bytes read through the `api` container's nginx and the relay reached across the compose network. The only test of the cross-container relay hop in either direction — `scripts/e2e_up.sh` is AIO-only — and therefore the only place a `DISPATCHARR_WEB_HOST` that Django's `get_host()` rejects (an underscore in a container name) would surface. `docker/tests/test-puid-pgid.sh`'s `test_role_split`, run by `lifecycle-tests.yml`'s `suites` job in full mode. The same scenario, not a second one: the bash-suite bullet list below already names it as "the programme's only cross-container relay scenario"; this row is the flow entry it never got | P1 | done |
 | Streaming | **Open question (found by the bounded-restart test):** the code reads as if a viewer reconnecting to the **same** channel after a relay restart can only be cleared by `_check_orphaned_metadata`'s 30s sweep, not by the restart's own bound. `_channel_setup_needed` (`apps/proxy/live_proxy/views.py`) returns "no setup needed" for a channel whose metadata still says `active` and never consults the dead owner's `live:worker:<id>:heartbeat` — the zombie check in `ProxyServer.check_if_channel_exists` sits behind that early return and is unreachable from the tune path — so the reconnecting client would attach as a follower to a channel nobody owns until the sweep runs, and the sweep declines to clean a channel that still has a live client, exactly what a retrying reconnect keeps supplying. A single hand measurement came in at **≤17s** to 1880 delivered bytes (rather than a 200 with nothing, what a follower on an ownerless channel answers) — under both the 30s sweep this reading names as the only thing that can clear the state and the 30s restart ceiling. Its clock starts before the blocking restart call, the same origin as the bounded-restart figure above, and up to 10s of the measuring probe's own timeout can only make the number look slower than the true first byte, never faster. So either the mechanism does not bite the way the code reads, or the sweep ran early on this run. The test tunes a channel that was *not* running when the relay went away, and this is filed as an open question ([#195](https://github.com/D10Scot/Dispatcharr/issues/195)) rather than asserted as a defect | P1 | todo |
 | Sources | **Gap:** `M3UAccountProfile.search_pattern`/`replace_pattern` URL rewriting is unproven, naming `apps/proxy/live_proxy/url_utils.py:transform_url` as the mechanism and the provider's `ScenarioLog` as the observable — cut before this goal started | G14 | todo |
@@ -257,8 +257,10 @@ together in `stream-profiles.spec.ts`):
 - `e2e/tests/streaming-failover/failover-buffering.spec.ts` — failover:
   buffering (ffmpeg only)
 - `e2e/tests/streaming-greybox/output-profile-sharing.spec.ts` — Output
-  Profile shared per (channel, profile), verified both by the shared owner
-  key and by counting live ffmpeg processes directly
+  Profile shared per (channel, profile), verified by counting live ffmpeg processes
+  directly; the shared-owner-key half was removed at the 2d-3 cutover, because the Go
+  relay writes no `live:channel:*` key (spec D2 deletes `output_owner`/`output_state`
+  and the sharing is an in-process registry's refcount)
 
 The twelfth G4 row, the ownership-lease fencing flagship, stays `todo`: it
 was built, shown to pass for a reason that says nothing about the defect
```

---

## Self-review

Every `file:line` cited above was opened at the seed and confirmed. What follows is the record of
both passes.

### Fix round, after the opus review of `e15d9b24`

The review's verdict was FAIL on **form, not analysis**: every ruling it could re-measure held —
the seven ruleset contexts verbatim, all seven CI runs, the complete five-test failure set with its
messages, both R10 break-checks, `golangci-lint`'s `0 issues.`, the six Task 1 Step 4 grep counts
on a tree it flipped with this plan's own script, and `nginx -t` on the rendered config including
the six re-declared headers. Fourteen of fifteen findings are accepted and applied; one is accepted
with a correction to its own remedy.

| # | Finding | Disposition |
|---|---|---|
| **B1** | Six appendices were diff *fragments* (no `diff --git`, no `---`/`+++`, bare `@@`), and A/H/J were prose replacements with two paste-placeholders; Task 1 Step 1's `git apply --check` could never succeed | **Accepted, fixed.** Every edit was made in a scratch worktree at the seed, extracted with `git diff --cached`, and replayed into a **second** pristine worktree — each patch alone and then all ten in sequence — with `git apply --check --whitespace=error`. All ten pass both ways. The "apply by hand" instructions are gone, as are both placeholders. The scripts survive only for `CLAUDE.md` and the spec, whose line numbers genuinely move. |
| **B2** | Appendix G was prose bullets telling the implementer to author ~10 paragraphs; G.1 item 3's anchor wraps at `:3822-3823` and matched 0 times; G.3 and the A13 insertion gave no anchors | **Accepted, fixed.** Appendix G is now a script in 2d-2's exact form, carrying the **full** A13 text inline, with `assert count == 1` on all ten anchors — including the wrapped one, taken from the file rather than paraphrased. A13 anchors on `## Stage 2d — cutover, and its trap` (so it lands after A12 without knowing A12's text) and the Done-log row on `## Risks`. **It was run at the seed**: ten edits, no assertion fired. |
| **B3** | H.5 said test 3 was "unchanged" while H.4 re-valued the `FORWARDED_RELAY_PARAMS` it consumes at `:360-368` in a `uwsgi_param` regex — the file would not compile, or test 3 would go red and Constraint 8 would blame the config | **Accepted, fixed.** Test 3's loop now derives the old spelling: `...FORWARDED_RELAY_HEADERS.map(uwsgiParamName)`. `npm run typecheck` is clean on the applied tree, and Appendix H's preamble names this as one of the three things worth reading the diff for. |
| **B4** | H.2's range `:155-165` left the 37-line JSDoc at `:118-154` standing, contradicting the constants directly below it | **Accepted, fixed.** The diff replaces `:118-165`. `grep -c "Every relay-bound location as of Phase 1 PR 4"` on the applied tree returns 0. |
| **S1** | Task 0 Step 3's alternation grep prints one line on BSD grep, four on GNU/BusyBox — a false STOP at Task 0 on this project's own platform | **Accepted, fixed, and reproduced first**: `grep -n 'location ^~ /proxy/ts/stream/ {' docker/nginx.conf` returns rc=1 here. Now `grep -nF -e … -e …`, one pattern per line, with the reason stated in the step. |
| **S2** | Both provenance sequences in Task 1 Step 4 were rotated one place left | **Accepted, fixed.** Replaced with a six-row table, grep by grep, re-measured at the seed (`0/9/10/0/1/2`) and on the applied tree (`4/6/7/3/4/1`). The per-grep `# expect N` comments were already right. |
| **S3** | Appendix K item 4's OLD string does not exist — `COVERAGE.md:259-261` is a wrapped bullet | **Accepted, fixed.** Appendix K is a diff, which carries the wrapping; the preamble says so, since it is the clearest illustration of why a diff beats a replacement instruction. |
| **S4** | Appendix K item 3 gave a NEW string and no OLD, on a 40-word sentence, then said the Celery sentence was "unchanged, plus one clause" | **Accepted, fixed** by the same diff: the whole row is rewritten in one hunk, and the "relay-go cannot make this claim" clause is in it rather than left to the implementer. |
| **S5** | A13.3 named two spec sentences; there are three — `:3830`, inside the very deletion-list entry this PR implements, would still say "re-pointed" after the edit | **Accepted, fixed.** Appendix G corrects all three (§ Stage 2d, § Testing, and entry 3's Gate line), and A13.3's own text now says "three places, not two". Task 8 Step 2 greps for each. |
| **S6** | Task 8 Step 2's `"A10.1 is a precondition"` grep returns 1 before the edit too, so it cannot see its own change | **Accepted, fixed.** It now greps `"Satisfied before 2d-3 was planned"` and four other post-edit strings, with a note saying explicitly not to use the old one and why. |
| **S7** | Task 5 Step 4 expected five green in `streaming-greybox`; the project runs seven (six `test(` across three files, plus the `bootstrap` dependency) | **Accepted, fixed**, with the arithmetic in the step so the next reader does not have to redo it. |
| **S8** | The Gate stated the skipped-heavy-job caveat for Backend but not Frontend, though `Frontend result` will skip for the same reason | **Accepted, fixed.** One bullet covers both, and cites `labels_for_changed_paths() → []` for all fourteen paths. |
| **S9** | J.3 change 3 named a third channel but not the `openOutcome(...)` substitution at `:636` that makes it used | **Accepted, and the remedy is structural rather than textual**: Appendix J is now a diff, so the substitution is in it. Its preamble names this and the `streamClient.close()` move as the two things a prose appendix would have left to inference. |
| **S10** | The drift table said `docs/relay-parity-matrix.md` was untouched by 2d-1; #325 edited row 9 | **Accepted, fixed, and one step added.** The table row now records the measured `2 +-` and says why it is benign (row 11 is still `:184`). Task 0 Step 9 greps for row 11's pin rather than assuming, because R7's whole no-matrix-edit argument rests on it. |
| **N1** | Two off-by-one citations (`:79-105`, `:625-627`) | Accepted; both corrected to `:78-105` and `:624-627`. |
| **N2** | "at `:125`'s former position — i.e. the tail of the `:109-122` block" names two different places | Accepted; R7 now says only that the two sentences are added to the surviving `:109-122` block, and gives the deletion range as `:125-144`. |
| **N3** | `5 failed, 64 passed` does not obviously reconcile with 55 + 6 `test(` declarations | **Accepted, and now reconciled by counting rather than asserted.** `grep -cE "^ *test(\\.fail)?\\("` over `e2e/tests/streaming/*.spec.ts` at the seed gives **50** top-level `test(`, **5** indented ones inside `upstream-to-control.spec.ts`'s single `test.describe`, and **7** `test.fail(` — 62. Plus `streaming-greybox`'s 6 and the one `bootstrap` setup both projects declare as a `dependencies:` entry: **69**, which is what the run printed (`Running 69 tests using 3 workers`). 5 + 64 = 69. The reviewer's 55 is 50 + 5 and omits the `test.fail(` seven, which Playwright counts as tests and reports as `✘` while scoring them as passes. |
| **N4** | Spec A10.2 says "Four tests pin the flag" then enumerates five; the plan's R3 says five and is right | **Accepted, and now fixed in the spec** rather than left: A13.10 corrects the count in place, since a reader who trusts the number looks for a fifth test and concludes the list is wrong rather than the count. |
| **N5** | A.5's three `assert`s caught nothing on the reviewer's run either | Noted; that is the point, and the script (now the provenance note in the Appendices preamble rather than a deliverable) says so. |

**One finding accepted with a correction to its remedy.** B2's fix asked for "heading-level anchors
for the two insertions". The A13 anchor is a heading (`## Stage 2d — cutover, and its trap`) and
works as described. The Done-log anchor cannot be used the same way: inserting `"\\n" + ROW` before
`"\\n## Risks\\n"` puts the row **after** the blank line that ends the table, breaking it — measured,
by doing it. Appendix G therefore splits on the heading, asserts the preceding text ends in a table
row, `rstrip`s the newlines and appends, which is also what makes it independent of how 2d-2's own
insertion is shaped.

### Original review pass

Corrections made while writing the plan:

- **A10.1's premise is no longer true, and the plan says so rather than repeating it.** A10 records
  six required contexts with `Go result` absent; the ruleset now returns seven with `Go result`
  present. R0 records the command's actual output and Task 0 Step 6 re-verifies.
- **A10.13's precondition is satisfied.** #318 is CLOSED (by `16fbb952`, an ancestor of the seed),
  so 2d-3 — which A10.13 names as one of only two 2d PRs that run the Go suite at all — runs it
  against a fixed test.
- **A10.12's fourth field was already partly settled and is now fully measured.** What remained
  open was whether the `proxy_pass` transport carried it. Measured: `172.26.0.1`, the real client.
- **A10.10's `e2e/fixtures/types.ts` unknown is closed by measurement**, not by argument (R15).
- **Two `e2e/COVERAGE.md` rows beyond A10.10's list** (`:196`, `:197`) are claims the flip
  falsifies; A10.10's ownership table names only `:259-261`. Recorded as A13.8.
- **`docker/Dockerfile` needs a `COPY` line** that § Stage 2d's new-file paragraph never names.
  Found by building: without it the container does not start. Recorded as A13.7.
- **`nginx.conf`'s map comment is already stale at the seed** — both locations it describes pass to
  a literal group, not through the map. Recorded as A13.4.
- **The "four flipped locations" count is right and the "six server-level headers on three of them"
  count is also right**, and the two are easy to conflate: `^~ /proxy/relay/` is the fourth flipped
  location and deliberately re-declares none of the six.

Things this plan could not settle from the tree, listed rather than guessed:

- **Nothing about `relay/` or the backend was measured by the CI run**, because the measurement
  branch touches neither and both change detectors gated their matrices off. R0 states this rather
  than letting two green aggregates read as coverage they are not.
- **No E2E test drives the XC three-segment regex location or `^~ /proxy/relay/` with a forged
  marker.** Pre-existing (every XC-live request in the suite uses the `/live/` prefix form, which
  `^~ /live/` claims first), not opened by this PR, and closing it is not 2d-3's — recorded in R6 so
  a reviewer does not read the forged-marker test as covering all four flipped locations.
- **R9's measured numbers are from a developer laptop, not CI.** They are used to *reject* a shape
  (23 946 ms against a 30 000 ms ceiling) and to justify keeping the existing ceiling for the two
  that pass with 12.7 s and 23.1 s of margin — never to set a new threshold. Task 5 Step 4 makes the
  implementer stop rather than raise the ceiling if their own numbers come within 5 s of it.
