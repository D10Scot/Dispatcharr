# Phase 2 PR 2b-2 — Output Profile and User Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `X-Relay-Output-Format` and `X-Relay-Client-IP` to the authorize hop end to end, make the live relay path read both so `authorize_views.py`'s `User.objects.filter(...)` no longer runs on any live tune, and fold every active `OutputProfile`'s built command into `next-source`'s response body.

**Architecture:** Three independent changes that share one file list. (1) Two new `X-Relay-*` headers travel the existing path — `authorize_stream` resolves them, `authorize_view` sets them on the 200, `docker/nginx.conf`'s nine authorize-hop locations copy them through `auth_request_set` + `uwsgi_param`, every other location blanks them via `docker/dispatcharr_api_params.conf`, and `result_from_headers` reads them back. (2) The live path consumes both: the output format comes from the header instead of a `User` row, and the client IP comes from the header when nginx authorized the request. `AuthorizeResult.user` becomes lazily resolved so the VOD and catch-up surfaces — which D1 leaves in Python and which thread the `User` object deep into their own code — keep working unchanged while the live path never touches it. (3) `next-source`'s response gains an `output_profiles` map; it is a contract addition for the Go relay, deliberately not consumed by the Python relay (see Ruling R3).

**Tech Stack:** Django 6 + DRF, nginx `auth_request`, Playwright (`e2e/`), Django `TestCase`/`SimpleTestCase` plus the stage-2a relay harness (`apps/proxy/live_proxy/tests/harness/`).

**Spec:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` — line 1658 (2b-2's PR row), lines 1595–1600 (the Stage 2b ORM-site table), lines 660–800 (the contract's response spec), lines 1860–1960 (the nginx location contract and NB1), lines 890–912 (parity-matrix rows 16–18). ADR: `docs/adr/0005-the-relay-is-chosen-by-name-once-per-tune.md`.

---

## Global Constraints

Read `/Users/dion/git/Dispatcharr/CLAUDE.md` in full before the first edit. The constraints below are the ones this PR trips over; CLAUDE.md is the authority on the rest.

**Workspace.** Work only in `/Users/dion/git/Dispatcharr/.worktrees/phase2-2b2`, branch `migration/phase2b-output-profile-and-user`. **Anchor every Bash command with an absolute path or a leading `cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2`** — the shell's default cwd is not reliable in a multi-agent run and has been observed resolving into another agent's worktree.

**Commits.** Stage and commit in **separate Bash calls**; the `PreToolUse` hook blocks a single command whose text contains both words. Write commit messages with the Write tool to a scratch file and use `git commit -F <file>`. Do not put the words "git add" and "git commit" in the same command string.

**Test hooks.** The `PostToolUse` hook runs the whole backend package for the edited file's label inside the `dispatcharr-testrunner` container, against **whatever worktree that container is bind-mounted at**. Before the first edit, run:

```bash
docker inspect dispatcharr-testrunner --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}'
```

If it does not print `/Users/dion/git/Dispatcharr/.worktrees/phase2-2b2`, re-point it with `.claude/hooks/start-test-container.sh` from inside this worktree before editing. If Docker is down the hook says so and exits 0 — **then say the tests did not run; do not describe the work as verified.**

**Test labels for this PR.** Derived from `dispatcharr/test_discovery.py`'s `labels_for_changed_paths()` over this PR's Python/doc file list — the same function the commit gate and CI use. Exactly four:

```
apps.channels.tests
apps.proxy.live_proxy.tests
apps.proxy.tests
core.tests
```

`docker/**` and `e2e/**` route to no backend label; their gates are the Playwright greybox spec and `nginx -t`.

**Serializers, never raw dicts** (CLAUDE.md § Conventions). Every new response field is declared on a DRF serializer so it lands in the drf-spectacular schema.

**No control-plane process may read a relay-owned Redis key, and no relay process may touch the ORM for data the contract can carry.** This PR moves data onto the contract; it never adds a Redis read across the boundary.

**Credential logging.** `scripts/check_credential_logging.py` runs on every `*.py` edit. Never log a URL, header, path, or credential outside `redact_url`/`redact_headers`. A client IP is not a credential, but do not log it at INFO on a new line either — the existing `logger.info(f"[{client_id}] Requested stream ...")` line is the precedent and it carries no IP.

**nginx is not restarted by a unit test.** Changes to `docker/nginx.conf` are verified by the greybox Playwright spec, which runs `nginx -T` inside a live container. If no container is available, say the nginx half was not verified rather than claiming it was.

### The five principles this plan's tests must obey

These are not style notes. Each is a test that passed while the code was broken, found on 2b-0 and 2b-1.

1. **A pin that supplies the default pins nothing.** A test that threads a value must supply a **non-default** value for the field it claims to pin, or it passes identically with the threading deleted. Every new assertion here uses a distinctive value: `output_format` is `'fmp4'` (never the `'mpegts'` default), the client IP is `203.0.113.9` (TEST-NET-3, never `127.0.0.1`), the user id is a real row's id and never `0` or `1`.
2. **The tautological oracle.** A test whose expected value is computed by the code under test cannot fail. Expected values are **literals in the test**, never calls into production helpers. This bites hardest on `build_command()`: never assert `response['output_profiles']['3']['argv'] == profile.build_command()`. Write the literal `['ffmpeg', '-i', 'pipe:0', '-c:a', 'ac3', 'pipe:1']`.
3. **A dropped field under merge semantics is a silent lie, not absence.** Redis hash writes use `hset(mapping=…)`, which merges; a dropped key leaves the *previous* value, so a test starting from an empty hash cannot tell "written" from "dropped". Any assertion about a hash write must seed a pre-state that **differs** from the expected post-state.
4. **Owner-versus-follower is a systematic axis, not an incidental conditional.** `stream_ts` resolves the output profile and format at **two** call sites — `apps/proxy/live_proxy/views.py:605` (inside `if proxy_server.am_i_owner(channel_id):`, the tuning client) and `:712` (`if not output_options_resolved:`, every client that did not initialize the channel, which is every second and subsequent client). A test that only drives the first leaves the second unwalked; 2b-1 shipped a blocking regression on exactly that shape. `stream_ts` versus `stream_xc` is the second such axis — both reach `result_from_headers`, and `stream_xc` (`views.py:825`) passes `decision.user` positionally into `stream_ts`.
5. **"The ends of the chain are pinned" is not "the chain is pinned."** A test that asserts the authorize response carries a header, plus a test that asserts the relay reads one, with nothing asserting that **nginx forwards it**, leaves the middle unpinned. Nine locations is nine chances to miss one. Task 2's greybox edits therefore enumerate all nine and assert **both** halves — the `auth_request_set` capture *and* the `uwsgi_param HTTP_X_RELAY_*` forward — per location, not a spot check.

### Rulings made while planning (spec deviations, each deliberate)

- **R1 — `AuthorizeResult.user` is resolved per *surface*, not lazily, and not deleted.** The spec's Stage 2b table says the relay "never needs the `User` row itself." That is true of the **live** surfaces only. `decision.user` is consumed by five call sites outside `live_proxy` — `apps/proxy/vod_proxy/views.py:640`, `:1442`, `:1477` and `apps/timeshift/views.py:172`, `:298` — which thread the object deep into `_serve_catchup` and the VOD session code. **D1 (spec line 433) leaves both surfaces in Python and untouched**, so deleting the field would be a cross-app refactor far outside this PR's named blast radius.

  **A lazy-object design was drafted for this and is withdrawn: it cannot work, and the reason is worth stating so nobody redrafts it.** `result_from_headers` today has **two** distinct "no user" outcomes that both yield `user=None` — the header is absent or non-digit, and the header is a digit whose row no longer exists (a user deleted mid-stream, a stale header). A lazy proxy is never `None`, so every consumer branching on that flips on the second case. Fourteen sites consume it, and **eleven of them test identity, not truthiness** — verified line by line:

  | Test | Sites |
  |---|---|
  | `is None` / `is not None` — **11** | `client_manager.py:234`, `:274`; `live_proxy/views.py:174`; `timeshift/views.py:1274`, `:2509`, `:2524`, `:2553`, `:2965`, `:2966`; `vod_proxy/views.py:639`, `:783` |
  | `if user:` truthiness — **3** | `live_proxy/views.py:129`; `vod_proxy/views.py:138`, `:794` |

  A `__bool__` (and `__eq__`) that resolves would fix the three and leave the eleven permanently wrong, because **`is` cannot be overloaded** — no dunder makes an object `None`. `__eq__` does not affect `is` either. So the lazy design is not merely risky here; for eleven of fourteen consumers it is unfixable in principle.

  **The design instead splits on the surface, which `result_from_headers` already receives as its second parameter.** Live surfaces (`SURFACE_LIVE`, `SURFACE_LIVE_XC`) get `user=None` and `user_id` straight from the header, with no query. Every other surface keeps today's code verbatim — the query, and `user_id=str(user.id) if user is not None else ""`. Consequences, all of them good:

  - **Every one of the fourteen sites keeps a real `User` or a real `None`.** No new object semantics, no dunders, nothing to get subtly wrong. The lazy object's whole hazard class disappears rather than being managed.
  - **`user=None` on a live tune is already a reachable value today** (any anonymous tune), so every live-path consumer is on a branch it already handles. Task 3 then supersedes each of them anyway: `views.py:129` is skipped because the trusted branch returns first; `client_manager.py:234` would yield `"0"` but the explicit `user_id=` wins; `:274` yields `"unknown"`, documented; `views.py:174` leaves `user` as `None`.
  - **The seam matches the phase's own seam.** The query is removed from exactly the surfaces D1 ports to Go and kept on exactly the ones D1 leaves in Python. That is a far better justification than "lazy, so nobody notices".
  - The zero-query claim on the live path becomes **structural** — there is no user object to touch — rather than a property of a proxy's access pattern. Step 3b's capture test still earns its place, now as a guard against a future edit reintroducing a query (a logging line resolving the user), not as the thing holding the invariant up on its own.

  **Why the `else` branch really does cover every external consumer — verified, not assumed.** "Those surfaces keep exactly today's behaviour" is the kind of claim that has cost this programme a round before, so here is what it rests on. Each of the five external `decision.user` consumers sits in a view whose `resolve_authorization` call passes a surface, and **not one of them is `SURFACE_LIVE` or `SURFACE_LIVE_XC`**:

  | View | Surface passed | `decision.user` read at |
  |---|---|---|
  | `vod_proxy/views.py:634` | `SURFACE_VOD` | `:640` |
  | `vod_proxy/views.py:1417` | `SURFACE_VOD_XC` | `:1442` |
  | `vod_proxy/views.py:1454` | `SURFACE_VOD_XC` | `:1477` |
  | `timeshift/views.py:162` | `SURFACE_CATCHUP_XC` | `:172` |
  | `timeshift/views.py:292` | `SURFACE_CATCHUP` | `:298` |

  So `result_from_headers` runs its unchanged `else` branch for all five, and each of the fourteen consumers downstream of them receives a real row or a real `None`, produced by code this PR does not edit.

  **The consumer this matters most for is `vod_proxy/views.py:783`, which is a recovery path and not a guard**: `if user is None:` there re-resolves the principal from the Redis session mapping for a VOD streaming request whose token was stripped from the redirect URL. Any design that makes `user` non-`None` turns that into dead code and silently drops the user's identity on that path. The surface split leaves it reached with a genuine `None`, exactly as today — and it is the single strongest reason to prefer this design over any stand-in object, which cannot be made `None` for it at all.

  **The thing that would break this is a new non-live view passing a live surface**, so Task 3 Step 5b checks for exactly that rather than trusting the table above to stay true.

- **R1b — `user_id`'s meaning changes on the live surfaces only, and the change is deliberate.** Today `authorize_views.py:133` sets `user_id=str(user.id) if user is not None else ""`, so on the trusted path the field is *proof the row existed at relay-registration time*. Under R1 the live surfaces take it from the header, so it means *the row existed at authorize time*. This is externally observable — Task 3 threads it into `add_client`'s client hash and into the `client_connect` `SystemEvent` — so it is decided rather than absorbed: **accept it.** Three reasons. The divergence window is a single request (nginx's `auth_request` subrequest to the relay's registration), and only for a user deleted inside it. Closing it means re-querying, which is precisely the query this PR exists to remove. And the Go relay cannot re-query at all, so the contract's meaning *must* become "what the hop resolved" at 2c regardless; adopting it now is what makes 2b-2's behaviour and 2c's the same. Task 3 Step 3b pins it with a deleted-user tune, since that is the one input that distinguishes the two meanings.
- **R2 — `username` on relay events is resolved by Django, not carried in a header.** `output/ts/generator.py:134`, `:652` and `output/fmp4/generator.py:114` send `username=self.user.username` into `emit_event`, which reaches `core/relay_events.py` and becomes a `SystemEvent` row — externally observable. Touching `.user` there would re-trigger the query R1 defers. The relay sends `user_id` instead and `apply_event_batch` resolves the username in the API process, which is already where the write happens (Phase 1 PR 6's shape).
- **R3 — `output_profiles` is a contract addition the Python relay deliberately does not consume, and it carries *every* active profile, not just the one named on the request.** The spec (line 1598) decided "fold the built command into `next-source`'s response when `X-Relay-Output` names a profile." `next-source` runs **once per channel**, at tune, failover and resume; `_output_profile_for` runs **once per client**, and the second client on a running channel (`views.py:712`) never makes a `next-source` call at all. A per-request single profile therefore cannot answer the question the relay actually asks, for any client but the first. Two consequences: the map is keyed by id and lists every `is_active=True` profile, so a Go relay can cache it at tune and answer any later client; and `apps/proxy/live_proxy/views.py:152`'s `OutputProfile.objects.filter(...)` **stays**, because consuming the map from the Python relay needs either a new per-client route (the spec rejects it) or a Redis cache with its own TTL and staleness semantics (the spec does not specify one). This matches 2b-1's precedent exactly: `proxy_settings` shipped on the same response with "Nothing in the PYTHON relay consumes this yet, deliberately." **2b-3 must allowlist `views.py:152` with a citation to this ruling.** Flag it in the PR description.

  **The Redis cache alternative was considered and declined by the phase orchestrator; do not add it.** The spec already set this precedent and its argument applies here verbatim — line 1595, on the `channel_status.py` fallbacks: *"the surviving fallback, if any, is Python code that is deleted wholesale in `migration/phase2d-delete-live-proxy`, not a shape the Go relay reimplements."* `views.py:152` is that same shape. A cache would buy 2c nothing while introducing a real, unpinned parity change: today an `OutputProfile` edit reaches the next **client**; cached, it would reach only the next **tune**. Shipping an unpinned behaviour change inside a PR whose gate is "the forged-header test still 403s" puts a regression exactly where no gate is looking.

  **The allowlist reconciliation, written now so 2b-3 transcribes it rather than re-deriving it.** Spec line 1769 requires 2c-1's PR description to name, for every non-empty allowlist entry, either the contract field that closes it or the written reason the Go relay never asks the question. For this entry:

  > `views.py:152` stays. The contract field that closes it is `output_profiles` on `next-source`'s response: the Go relay caches the map at tune and serves every later client from memory. Python cannot, because `_output_profile_for` runs per client (`views.py:605` owner-init, `:712` everything else) while `next-source` runs per channel, and closing it in Python would need a cache whose staleness semantics nothing has specified.

  That paragraph goes **verbatim** into this PR's description, and into `apps/proxy/live_proxy/tests/zero_orm_allowlist.py`'s comment when 2b-3 writes it.
- **R4 — parity-matrix row 17 is not claimed by this PR; it is already pinned, and this PR must keep it green.** Row 17's `Pin` cell already names `apps/proxy/live_proxy/tests/test_client_ip_provenance.py::test_ip_address_is_the_real_client_address_on_both_status_endpoints`, and its `Notes` cell says "2b-2 replaces that source with `X-Relay-Client-IP` … the invariant this row pins is that `ip_address` stays the real client address across that change." The row is not `owed:`, so there is nothing to close. The spec's line 1599 says the Python relay "ignores it exactly as it ignores today's five" — **this plan does not follow that sentence**, because a header no consumer reads can only be tested at its two ends, which is exactly what principle 5 rules out, and because the matrix row explicitly anticipates the source changing here. Task 4 makes the Python relay read the header on the trusted path with `get_client_ip(request)` as the untrusted fallback, extends the row's existing test with a trusted-path case, and updates the row's `Source` and `Notes` cells. Row 18 belongs to 2b-3 and is not touched.
- **R5 — deferred nit `test_server_event_listener.py:273-329`: checked, not applicable.** This PR touches neither `server.py`'s event listener nor that test file (`grep add_client apps/proxy/live_proxy/tests/test_server_event_listener.py` returns nothing). Leave it for whichever PR edits that file.
- **R7 — issue #253's reads sit in files this PR edits, and this PR does not touch them.** Two of the three ORM reads #253 records are in files on 2b-2's list: `get_stream_object` at `apps/proxy/live_proxy/views.py:189` — three lines above the `client_ip` line Task 3 Step 6 edits — and at `apps/proxy/authorize.py:344`, a file Task 1 edits. `channel.get_stream_profile()` at `views.py:430` is in the same file too. **Leave all three exactly as they are.** They belong to 2b-3, they are a different question (the guard's shape blindness, not the contract's completeness), and folding them in would put an unreviewed ORM decision inside a PR whose gates cannot see it. Say in the PR description that 2b-2 edited these files and deliberately left those reads, so 2b-3's author does not read the edits as a partial fix. Issue **#257** is the settings-UI edit path (`core/api_views.py`'s `ProxySettingsViewSet`); 2b-2 touches neither that file nor `apps/proxy/config.py`, so it is confirmed unrelated.
- **R6 — deferred nit `scripts/coverage_live_path.floor:112`: checked, not applicable.** This PR touches no `scripts/coverage_live_path*` file. Note also that the "flag before dir" half of that nit is already satisfied — `scripts/coverage_live_path.sh:11` already shows `--write-floor --shape-only [dir]`. Leave the `statements`/`percent` clause for a PR that edits the floor.

### Verified blast-radius counts

Re-verified against this worktree at `93900a6f`; re-check before editing, do not trust these numbers blind.

| Thing | Today | After | Evidence |
|---|---|---|---|
| `docker/dispatcharr_api_params.conf` blanking lines | 5 | 7 | `grep -c 'uwsgi_param HTTP_X_' docker/dispatcharr_api_params.conf` → 5; lines 23–27 |
| its header comment | "setting these five to `\"\"`" | "these seven" | `docker/dispatcharr_api_params.conf:8` |
| `docker/nginx.conf` authorize-hop locations | 9 | 9 | `grep -c 'auth_request_set \$relay_name' docker/nginx.conf` → 9, at lines 90, 267, 289, 311, 363, 385, 407, 429, 470 |
| `auth_request_set` lines per location | 6 | 8 | e.g. `docker/nginx.conf:266-271` |
| forwarded `uwsgi_param HTTP_X_RELAY_*` per location | 4 | 6 | `docker/nginx.conf:274-277`; `$relay_name` is captured but never forwarded, so the two counts differ by one |
| the `uwsgi_param HTTP_X_DISPATCHARR_AUTHORIZED` marker line | 1 | 1 | unchanged |
| `docker/nginx.conf:252` comment | "The six auth_request_set lines" | "The eight" | comment carries a count; it is part of the edit |
| `^~ /proxy/relay/` (`docker/nginx.conf:356`) | blanking include, no hop | unchanged shape, gains both names via the include | it is **not** among the nine; `grep -n 'auth_request_set' docker/nginx.conf` lists no line between 356 and 361 |
| nested `~ ^/api/channels/recordings/\d+/file/$` (`docker/nginx.conf:198`) | blanking include, no hop | unchanged shape, gains both names via the include | `docker/nginx.conf:199` |
| `AUTH_REQUEST_SET_VARS` | 6 | 8 | `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts:200-209` |
| `internal_auth.py` `HEADER_RELAY_*` | 5 | 7 | `apps/proxy/internal_auth.py:59-63` |
| `internal_auth.py` `META_RELAY_*` | 4 | 6 | `apps/proxy/internal_auth.py:74-77` — note there is **no** `META_RELAY_NAME`; `X-Relay-Name` is set on the response and never read back from a request |

One correction to the brief this plan was written from: the brief said each hop location has "5 `uwsgi_param HTTP_X_RELAY_*` lines plus the `AUTHORIZED` one." It is **4** `X_RELAY_*` plus the `AUTHORIZED` one, five `HTTP_X_` lines in total. `$relay_name` is `auth_request_set`-only.

---

## File Structure

**Modified — contract and decision:**
- `apps/proxy/internal_auth.py` — two `HEADER_RELAY_*` and two `META_RELAY_*` names.
- `apps/proxy/authorize.py` — `AuthorizeResult` gains `output_format` and `client_ip`; `resolve_output_format()` moves here from `live_proxy/views.py`; `authorize_stream()` populates both fields.
- `apps/proxy/authorize_views.py` — `authorize_view` sets the two response headers; `result_from_headers` reads them and stops querying `User` eagerly.

**Modified — the live relay path:**
- `apps/proxy/live_proxy/views.py` — `_resolve_output_format` delegates to `authorize.resolve_output_format` and prefers the decision's value; `client_ip` prefers the decision's value; `user_id` is threaded to `add_client` and the generators.
- `apps/proxy/live_proxy/client_manager.py` — `add_client` gains `user_id=`.
- `apps/proxy/live_proxy/output/ts/generator.py`, `apps/proxy/live_proxy/output/fmp4/generator.py` — carry `user_id`, send it on `emit_event` instead of `username`.
- `core/relay_events.py` — resolves `username` from `user_id` in the API process.

**Modified — the next-source contract:**
- `apps/proxy/serializers.py` — `OutputProfileRefSerializer`; `output_profiles` on `NextSourceResponseSerializer`.
- `apps/proxy/next_source.py` — `_with_output_profiles()`.
- `apps/proxy/control_plane.py` — the 404-degraded answer gains the key so a client can index it unconditionally.

**Modified — nginx and its pins:**
- `docker/dispatcharr_api_params.conf`, `docker/nginx.conf`
- `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts`
- `e2e/tests/streaming/authorize-matrix.spec.ts`

**Modified — docs:**
- `docs/relay-parity-matrix.md` (row 17 only)
- `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` (lines 1598 and 1658 only — Task 6 Step 0; line 1599 deliberately untouched)

**Tests created/extended:**
- `apps/proxy/tests/test_authorize_view.py` (extend)
- `apps/proxy/tests/test_next_source_api.py` (extend)
- `apps/proxy/live_proxy/tests/test_client_ip_provenance.py` (extend)
- `apps/proxy/live_proxy/tests/test_stream_ts_client_registration.py` (extend)
- `apps/proxy/live_proxy/tests/test_output_format_from_the_hop.py` (create)
- `core/tests/test_relay_events.py` (extend)

---

## Task 1: The two headers on the decision and on the hop's response

**Files:**
- Modify: `apps/proxy/internal_auth.py:59-77`
- Modify: `apps/proxy/authorize.py:119-140` (`AuthorizeResult`), `:201-221` (beside `resolve_output_profile`), `:400-453` (`authorize_stream`)
- Modify: `apps/proxy/authorize_views.py:101-141` (`result_from_headers`), `:305-312` (`authorize_view`'s response)
- Test: `apps/proxy/tests/test_authorize_view.py`

**Interfaces:**
- Produces: `internal_auth.HEADER_RELAY_OUTPUT_FORMAT = "X-Relay-Output-Format"`, `internal_auth.HEADER_RELAY_CLIENT_IP = "X-Relay-Client-IP"`, `internal_auth.META_RELAY_OUTPUT_FORMAT = "HTTP_X_RELAY_OUTPUT_FORMAT"`, `internal_auth.META_RELAY_CLIENT_IP = "HTTP_X_RELAY_CLIENT_IP"`; `AuthorizeResult.output_format: str = ""`, `AuthorizeResult.client_ip: str = ""`; `apps.proxy.authorize.resolve_output_format(request, user, force=None) -> str`.
- Consumes: nothing.

- [ ] **Step 1: Write the failing tests**

Append to `apps/proxy/tests/test_authorize_view.py`. Read the file's existing imports first; `authorize_views`, `authorize`, `internal_auth`, `User`, `Channel`, `patch` and `TestCase` are already imported at the top.

```python
class RelayOutputFormatAndClientIpHeaderTests(TestCase):
    """The hop resolves output_format and client_ip once and says so.

    Non-default values throughout: 'fmp4' is never the default
    (CoreSettings.get_default_output_format() answers 'mpegts'), and
    203.0.113.9 is TEST-NET-3 -- never routable, never a socket peer here.
    A test using the defaults would pass with the threading deleted.
    """

    @classmethod
    def setUpTestData(cls):
        cls.channel = Channel.objects.create(name="2b2-hdr", channel_number=9211)
        cls.user = User.objects.create_user(username="2b2-hdr-user", password="x")
        cls.user.custom_properties = {"output_format": "fmp4"}
        cls.user.save(update_fields=["custom_properties"])

    def setUp(self):
        from django.test import RequestFactory

        self.factory = RequestFactory()

    def _hop(self, uri, **extra):
        request = self.factory.get(
            "/_dispatcharr/authorize",
            HTTP_X_ORIGINAL_URI=uri,
            **extra,
        )
        return authorize_views.authorize_view(request)

    def test_the_hop_answers_the_users_output_format_not_the_default(self):
        response = self._hop(f"/proxy/ts/stream/{self.channel.uuid}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response[internal_auth.HEADER_RELAY_OUTPUT_FORMAT], "fmp4"
        )

    def test_the_hop_answers_the_forwarded_client_address(self):
        # REMOTE_ADDR is 127.0.0.1 under RequestFactory, which
        # get_client_ip treats as a trusted proxy, so the forwarded
        # header is honoured exactly as it is behind nginx.
        response = self._hop(
            f"/proxy/ts/stream/{self.channel.uuid}",
            HTTP_X_FORWARDED_FOR="203.0.113.9",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response[internal_auth.HEADER_RELAY_CLIENT_IP], "203.0.113.9"
        )

    def test_result_from_headers_carries_both_new_params(self):
        request = self.factory.get(
            "/proxy/ts/stream/x",
            HTTP_X_DISPATCHARR_AUTHORIZED=internal_auth.relay_trust_token(),
            HTTP_X_RELAY_CHANNEL=str(self.channel.uuid),
            HTTP_X_RELAY_CLIENT="client_1_2",
            HTTP_X_RELAY_USER=str(self.user.id),
            HTTP_X_RELAY_OUTPUT="",
            HTTP_X_RELAY_OUTPUT_FORMAT="fmp4",
            HTTP_X_RELAY_CLIENT_IP="203.0.113.9",
        )
        with patch.object(authorize_views, "authorize_stream") as inline:
            result = authorize_views.resolve_authorization(
                request, authorize.SURFACE_LIVE, identifier="x"
            )
        inline.assert_not_called()
        self.assertEqual(result.output_format, "fmp4")
        self.assertEqual(result.client_ip, "203.0.113.9")
        self.assertEqual(result.user_id, str(self.user.id))

    def test_a_query_parameter_still_beats_the_users_preference(self):
        # _resolve_output_format's precedence is force > query > user >
        # default. The hop sees the query string through X-Original-URI,
        # so 'mpegts' here must win over the user's 'fmp4' -- the
        # opposite of the other tests' expectation, which is what makes
        # this one a real ordering assertion.
        response = self._hop(
            f"/proxy/ts/stream/{self.channel.uuid}?output_format=mpegts"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response[internal_auth.HEADER_RELAY_OUTPUT_FORMAT], "mpegts"
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && docker exec dispatcharr-testrunner \
  python /repo/manage.py test apps.proxy.tests.test_authorize_view.RelayOutputFormatAndClientIpHeaderTests -v2
```

Expected: FAIL — `AttributeError: module 'apps.proxy.internal_auth' has no attribute 'HEADER_RELAY_OUTPUT_FORMAT'`.

- [ ] **Step 3: Add the four names**

In `apps/proxy/internal_auth.py`, after line 63 (`HEADER_RELAY_NAME`):

```python
# 2b-2. The hop resolves both once so the relay never re-queries: the
# output format used to cost a User row inside the relay process
# (authorize_views.result_from_headers), and the client address cannot
# be derived from REMOTE_ADDR by a relay nginx proxy_passes to rather
# than uwsgi_passes to (spec § Stage 2d, NB1).
HEADER_RELAY_OUTPUT_FORMAT = "X-Relay-Output-Format"
HEADER_RELAY_CLIENT_IP = "X-Relay-Client-IP"
```

and after line 77 (`META_RELAY_USER`):

```python
META_RELAY_OUTPUT_FORMAT = "HTTP_X_RELAY_OUTPUT_FORMAT"
META_RELAY_CLIENT_IP = "HTTP_X_RELAY_CLIENT_IP"
```

There is deliberately no `META_RELAY_NAME`: `X-Relay-Name` is set on the hop's response and read by nginx, never forwarded to the relay. Do not add one.

- [ ] **Step 4: Move `resolve_output_format` into `authorize.py`**

The rule already has a home here: `resolve_output_profile` (`apps/proxy/authorize.py:201`) says it was "Moved verbatim from apps/proxy/live_proxy/views.py:135-151 so the rule has one home." Its sibling follows. Insert directly after `resolve_output_profile`'s `return None` (`apps/proxy/authorize.py:221`):

```python
# The format aliases a client may send. Kept beside resolve_output_profile
# for the same reason it was moved here: the hop and the inline path must
# apply one rule, not two copies of it.
_FORMAT_ALIASES = {
    "mpegts": "mpegts",
    "ts": "mpegts",
    "fmp4": "fmp4",
    "mp4": "fmp4",
}


def resolve_output_format(request, user, force=None) -> str:
    """?output_format=/?output= then the user's custom_properties.

    Moved from apps/proxy/live_proxy/views.py:114-135 (2b-2) so the hop
    can answer X-Relay-Output-Format without the relay re-reading a User
    row. `force` is the live path's own extension-derived override
    (stream_xc's .ts/.mp4 suffix); the hop never passes it, because the
    hop authorizes a URI and the override is a property of the view's
    call, not of the decision.
    """
    from core.models import CoreSettings

    if force:
        return force
    if request is not None:
        param = request.GET.get("output_format") or request.GET.get("output")
        if param in _FORMAT_ALIASES:
            return _FORMAT_ALIASES[param]
    if user:
        custom = getattr(user, "custom_properties", None) or {}
        user_format = custom.get("output_format")
        if user_format:
            return user_format
    return CoreSettings.get_default_output_format()
```

- [ ] **Step 5: Add the two fields to `AuthorizeResult` and populate them**

In `apps/proxy/authorize.py`, extend the dataclass (currently `:132-140`) — append **after** `is_internal` so no positional caller breaks:

```python
    output_format: str = ""
    client_ip: str = ""
```

and extend its docstring's first sentence from "The five string fields are the five X-Relay-\* response headers" to "The seven string fields are the seven X-Relay-\* response headers".

In `authorize_stream`'s return (`apps/proxy/authorize.py:443-453`), add both:

```python
    output_profile = resolve_output_profile(http_request, user)

    return AuthorizeResult(
        surface=surface,
        channel_uuid=str(channel.uuid) if channel is not None else "",
        output_profile_id=str(output_profile.id) if output_profile else "",
        client_id=client_id,
        user_id=str(user.id) if user is not None else "",
        relay_name=settings.RELAY_DEFAULT_NAME,
        user=user,
        trusted=False,
        is_internal=is_internal,
        # Resolved here, once, for every surface. Only the live surfaces
        # read output_format today; computing it unconditionally keeps the
        # header's presence a property of the hop rather than of the
        # surface, so the relay never has to distinguish "absent because
        # this surface has no format" from "absent because nginx dropped
        # it".
        output_format=resolve_output_format(http_request, user),
        client_ip=get_client_ip(http_request) or "",
    )
```

Add `from dispatcharr.utils import get_client_ip` to `apps/proxy/authorize.py`'s imports if it is not already there (check first: `grep -n get_client_ip apps/proxy/authorize.py`).

- [ ] **Step 6: Set the two response headers on the hop**

In `apps/proxy/authorize_views.py`, extend `authorize_view`'s response block (`:307-312`):

```python
    response = Response(status=200)
    response[HEADER_RELAY_CHANNEL] = result.channel_uuid
    response[HEADER_RELAY_OUTPUT] = result.output_profile_id
    response[HEADER_RELAY_CLIENT] = result.client_id
    response[HEADER_RELAY_USER] = result.user_id
    response[HEADER_RELAY_NAME] = result.relay_name
    # 2b-2. Both resolved by authorize_stream above, so the relay does
    # not re-read a User row (output_format) and does not need
    # get_client_ip's trusted-proxy configuration (client_ip).
    response[HEADER_RELAY_OUTPUT_FORMAT] = result.output_format
    response[HEADER_RELAY_CLIENT_IP] = result.client_ip
    return response
```

Extend the import at the top of the file to include `HEADER_RELAY_OUTPUT_FORMAT`, `HEADER_RELAY_CLIENT_IP`, `META_RELAY_OUTPUT_FORMAT`, `META_RELAY_CLIENT_IP`.

- [ ] **Step 7: Read both back in `result_from_headers`**

In `apps/proxy/authorize_views.py`'s `result_from_headers`, add to the returned `AuthorizeResult` (keep the eager `User` query for now — Task 3 removes it):

```python
        output_format=(request.META.get(META_RELAY_OUTPUT_FORMAT) or "").strip(),
        client_ip=(request.META.get(META_RELAY_CLIENT_IP) or "").strip(),
```

and update the function's docstring, which currently says "every non-relay location blanks all five" — it is now **seven**.

- [ ] **Step 8: Run the tests to verify they pass**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && docker exec dispatcharr-testrunner \
  python /repo/manage.py test apps.proxy.tests.test_authorize_view -v2
```

Expected: PASS, including the pre-existing `ResolveAuthorizationTests`.

- [ ] **Step 9: Run the two labels this task touches**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && docker exec dispatcharr-testrunner \
  python /repo/manage.py test apps.proxy.tests apps.proxy.live_proxy.tests
```

Expected: PASS. `live_proxy` is included because `_resolve_output_format` still lives in `views.py` at this point and its tests mock it by name.

- [ ] **Step 10: Commit**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && git add apps/proxy/internal_auth.py apps/proxy/authorize.py apps/proxy/authorize_views.py apps/proxy/tests/test_authorize_view.py
```

then, as a separate call, write the message to `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/0283f845-af30-4144-9f20-8de5844d6a54/scratchpad/msg1.txt` with the Write tool and

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/0283f845-af30-4144-9f20-8de5844d6a54/scratchpad/msg1.txt
```

Message body: `contract(phase2): the hop resolves output_format and client_ip (2b-2 task 1)` plus the two trailers from the session's attribution rules.

---

## Task 2: nginx carries both headers on all nine locations, and blanks them everywhere else

**Files:**
- Modify: `docker/dispatcharr_api_params.conf:1-27`
- Modify: `docker/nginx.conf` — the nine blocks at lines 88, 265, 287, 309, 361, 383, 405, 427, 468, plus the comment at `:252`
- Modify: `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts:200-209` and tests 2 and 3

**Interfaces:**
- Consumes: `X-Relay-Output-Format` / `X-Relay-Client-IP` from Task 1's hop response.
- Produces: `HTTP_X_RELAY_OUTPUT_FORMAT` / `HTTP_X_RELAY_CLIENT_IP` in the relay's `request.META`, and their absence everywhere else.

- [ ] **Step 1: Write the failing greybox assertions**

In `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts`, extend `AUTH_REQUEST_SET_VARS` (`:200-209`) to eight:

```ts
const AUTH_REQUEST_SET_VARS = [
  '$relay_name',
  '$relay_channel',
  '$relay_output',
  '$relay_client',
  '$relay_user',
  // 2b-2: resolved once by the hop so the relay re-reads no User row
  // and needs no trusted-proxy configuration of its own.
  '$relay_output_format',
  '$relay_client_ip',
  // The eighth carries the status the module cannot transport: a 404 or
  // 429 decision arrives as 403 and error_page turns it back.
  '$authorize_status',
];

// The subset that is actually forwarded to the relay. $relay_name is
// captured for `uwsgi_pass $relay_upstream` and never sent onward, so
// this list is one shorter than the one above and must stay that way --
// principle 5: capturing a variable and forwarding it are two different
// things, and a test that checks only the first leaves nine locations'
// worth of middle unpinned.
const FORWARDED_RELAY_PARAMS = [
  'HTTP_X_RELAY_CHANNEL',
  'HTTP_X_RELAY_OUTPUT',
  'HTTP_X_RELAY_CLIENT',
  'HTTP_X_RELAY_USER',
  'HTTP_X_RELAY_OUTPUT_FORMAT',
  'HTTP_X_RELAY_CLIENT_IP',
];
```

In test 2 (`'every relay-bound location authorizes through the hop'`), immediately after the existing `for (const variable of AUTH_REQUEST_SET_VARS)` loop and inside the same `for (const block of relayBlocks)`, add:

```ts
      // The other half of the chain. auth_request_set copies the
      // subrequest's response header into a variable; only a
      // uwsgi_param sends it to the relay -- and the HTTP_-prefixed
      // form is also what overrides whatever the client sent under the
      // same name. A location that captures but does not forward looks
      // correct in the config and silently strips the header.
      for (const param of FORWARDED_RELAY_PARAMS) {
        expect(
          block.body.some((line) =>
            new RegExp(`^\\s*uwsgi_param\\s+${param}\\s+\\$relay_`).test(line)
          ),
          `location "${block.header}" captures but does not forward ${param}`
        ).toBe(true);
      }
```

In test 3 (`'every location outside the hop blanks the trust params'`), the current assertion only checks that the include is present. Strengthen it by asserting the include's own contents once, outside the loop:

```ts
    // The include is the mechanism; these are the names it must blank.
    // Asserting the include's presence alone cannot tell a five-name
    // file from a seven-name one, which is exactly the drift 2b-2
    // introduces.
    const paramsFile = stdout.match(
      /# configuration file \/etc\/nginx\/dispatcharr_api_params\.conf:\n([\s\S]*?)(?=\n# configuration file |\n*$)/
    );
    expect(paramsFile, 'nginx -T did not dump dispatcharr_api_params.conf').toBeTruthy();
    for (const param of [
      'HTTP_X_DISPATCHARR_AUTHORIZED',
      ...FORWARDED_RELAY_PARAMS,
    ]) {
      expect(
        new RegExp(`^\\s*uwsgi_param\\s+${param}\\s+""\\s*;`, 'm').test(paramsFile![1]),
        `dispatcharr_api_params.conf does not blank ${param}`
      ).toBe(true);
    }
```

- [ ] **Step 2: Run the greybox spec to verify it fails**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2/e2e && npx playwright test --project=streaming-greybox nginx-stream-buffering.spec.ts
```

Expected: FAIL on `$relay_output_format` for the first relay-bound location. If no container is running, bring the suite's container up per `e2e/README.md` first; **if you cannot, say the nginx half was not verified** rather than skipping silently.

- [ ] **Step 3: Add the two blanking lines**

`docker/dispatcharr_api_params.conf` — append after line 27:

```nginx
uwsgi_param HTTP_X_RELAY_OUTPUT_FORMAT "";
uwsgi_param HTTP_X_RELAY_CLIENT_IP     "";
```

and change line 8's "so setting these five" to "so setting these seven".

- [ ] **Step 4: Add the pairs to all nine hop locations**

For **each** of the nine blocks — `docker/nginx.conf` lines 88 (`= /streaming/timeshift.php`), 265 (`^~ /proxy/ts/stream/`), 287 (`^~ /proxy/vod/`), 309 (`^~ /proxy/catchup/`), 361 (`^~ /live/`), 383 (`^~ /movie/`), 405 (`^~ /series/`), 427 (`^~ /timeshift/`), 468 (the XC three-segment regex) — insert after `auth_request_set $relay_user …`:

```nginx
        auth_request_set $relay_output_format $upstream_http_x_relay_output_format;
        auth_request_set $relay_client_ip $upstream_http_x_relay_client_ip;
```

and after `uwsgi_param HTTP_X_RELAY_USER    $relay_user;`:

```nginx
        uwsgi_param HTTP_X_RELAY_OUTPUT_FORMAT $relay_output_format;
        uwsgi_param HTTP_X_RELAY_CLIENT_IP     $relay_client_ip;
```

Do **not** touch `^~ /proxy/relay/` (`:356`) or the nested `~ ^/api/channels/recordings/\d+/file/$` (`:198`) — both are relay-bound but deliberately outside the hop and get both names through the blanking include instead. Verify afterwards:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && \
  grep -c 'auth_request_set \$relay_output_format' docker/nginx.conf && \
  grep -c 'auth_request_set \$relay_client_ip' docker/nginx.conf && \
  grep -c 'uwsgi_param HTTP_X_RELAY_OUTPUT_FORMAT \$relay_output_format' docker/nginx.conf && \
  grep -c 'uwsgi_param HTTP_X_RELAY_CLIENT_IP     \$relay_client_ip' docker/nginx.conf
```

Expected: `9` four times.

- [ ] **Step 5: Fix the comment that carries a count**

`docker/nginx.conf:252` currently reads "The six auth_request_set lines / are the only way to read the subrequest's response headers". Change "six" to "eight". Re-read the whole comment block (`:244-264`) and correct any other count it states.

- [ ] **Step 6: Run the greybox spec to verify it passes**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2/e2e && npx playwright test --project=streaming-greybox nginx-stream-buffering.spec.ts
```

Expected: all four tests PASS. Report the exact output.

- [ ] **Step 7: Commit**

Stage `docker/dispatcharr_api_params.conf docker/nginx.conf e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts` in one call, commit with `-F` in another. Message: `nginx(phase2): carry X-Relay-Output-Format and X-Relay-Client-IP on all nine hop locations (2b-2 task 2)`.

---

## Task 3: the live path reads `X-Relay-Output-Format`, and the live surfaces stop querying `User`

**Files:**
- Modify: `apps/proxy/authorize_views.py` — `result_from_headers`
- Modify: `apps/proxy/live_proxy/views.py:114-135` (`_resolve_output_format`), `:605-616`, `:712-713`, `:733-735`, `:784`, `:794-796`
- Modify: `apps/proxy/live_proxy/client_manager.py:215-238`, `:267-275`
- Modify: `apps/proxy/live_proxy/output/ts/generator.py:26-60`, `:126-135`, `:643-654`; `apps/proxy/live_proxy/output/fmp4/generator.py:28-67`, `:108-116`
- Modify: `core/relay_events.py:131-190`
- Test: `apps/proxy/live_proxy/tests/test_output_format_from_the_hop.py` (create), `apps/proxy/live_proxy/tests/test_stream_ts_client_registration.py` (extend), `core/tests/test_relay_events.py` (extend), `apps/proxy/tests/test_authorize_view.py` (extend again, Step 5b)

**Interfaces:**
- Consumes: `AuthorizeResult.output_format`, `AuthorizeResult.user_id`, `AuthorizeResult.trusted` from Task 1.
- Produces: `ClientManager.add_client(..., user_id=None)`; `create_stream_generator(..., user_id=None)` and `create_fmp4_stream_generator(..., user_id=None)`; a relay event whose `details` carry `user_id` where they used to carry `username`.

- [ ] **Step 1: Write the failing tests — the hop's format wins, on both call sites**

Create `apps/proxy/live_proxy/tests/test_output_format_from_the_hop.py`:

```python
"""The trusted output format comes from the hop, not from a User row.

Both of stream_ts's resolution sites are driven: views.py:605 (the client
that initializes the channel, reached only when am_i_owner is True) and
views.py:712 (every client that did not -- the second and subsequent
clients on a running channel). 2b-1 shipped a blocking regression because
only one branch of an owner/follower fork was walked; this file exists so
that cannot happen to this fork.

'fmp4' throughout, never 'mpegts': mpegts is what
CoreSettings.get_default_output_format() answers, so a test asserting it
would pass with the threading deleted.
"""

from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase


def _trusted_decision(output_format="fmp4", user_id="4242"):
    from apps.proxy.authorize import SURFACE_LIVE, AuthorizeResult

    return AuthorizeResult(
        surface=SURFACE_LIVE,
        channel_uuid="channel-uuid",
        client_id="client_test_1",
        user_id=user_id,
        relay_name="py",
        user=None,          # the whole point: no User row was fetched
        trusted=True,
        output_format=output_format,
        client_ip="203.0.113.9",
    )


class OutputFormatFromTheHopTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.channel_id = "channel-uuid"

    def test_the_trusted_decisions_format_is_used_with_no_user_row(self):
        from apps.proxy.live_proxy import views

        resolved = views._resolve_output_format(
            None, None, self.factory.get("/proxy/ts/stream/x"),
            decision=_trusted_decision(),
        )
        self.assertEqual(resolved, "fmp4")

    def test_a_forced_format_still_beats_the_trusted_decision(self):
        # stream_xc's .ts suffix must still win: the hop authorizes a URI
        # and knows nothing about the view's own override.
        from apps.proxy.live_proxy import views

        resolved = views._resolve_output_format(
            None, "mpegts", self.factory.get("/proxy/ts/stream/x"),
            decision=_trusted_decision(),
        )
        self.assertEqual(resolved, "mpegts")

    def test_an_untrusted_decision_falls_back_to_the_user_row(self):
        from apps.proxy.live_proxy import views
        from apps.proxy.authorize import SURFACE_LIVE, AuthorizeResult

        user = MagicMock()
        user.custom_properties = {"output_format": "fmp4"}
        untrusted = AuthorizeResult(
            surface=SURFACE_LIVE, relay_name="py", user=user, trusted=False
        )
        resolved = views._resolve_output_format(
            user, None, self.factory.get("/proxy/ts/stream/x"),
            decision=untrusted,
        )
        self.assertEqual(resolved, "fmp4")
```

- [ ] **Step 2: Write the failing tests — `user_id` reaches the client hash on both call sites**

Append to `apps/proxy/live_proxy/tests/test_stream_ts_client_registration.py`. Read its existing `_decision`, `_channel`, `_active_proxy_server`, `_request` helpers and the decorator stack on `test_owner_init_resolves_output_profile_once` first; mirror them exactly. The two new tests differ from each other in exactly one thing: `am_i_owner`.

```python
    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._output_profile_for", return_value=None)
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.resolve_authorization")
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_a_trusted_follower_registers_the_hops_user_id_and_format(
        self, proxy_server_cls, resolve, get_stream_object, _unavailable,
        _profile, _generator, _close,
    ):
        """views.py:712 -- the client that did NOT initialize the channel.

        4242 is not 0 and not 1: add_client's own fallback is "0", so a
        test asserting "0" or a real-looking small id could pass with the
        threading deleted.
        """
        from apps.proxy.live_proxy import views

        resolve.return_value = _trusted_decision()
        get_stream_object.return_value = self._channel()
        proxy_server, client_manager = self._active_proxy_server(am_i_owner=False)
        client_manager.add_client.return_value = True
        proxy_server_cls.get_instance.return_value = proxy_server

        views.stream_ts(self._request(), self.channel_id)

        _args, kwargs = client_manager.add_client.call_args
        self.assertEqual(kwargs["user_id"], "4242")
        self.assertEqual(kwargs["output_format"], "fmp4")

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._output_profile_for", return_value=None)
    @patch(
        "apps.proxy.live_proxy.views.ChannelService.is_channel_unavailable_for_new_clients",
        return_value=False,
    )
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.resolve_authorization")
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_a_trusted_owner_registers_the_hops_user_id_and_format(
        self, proxy_server_cls, resolve, get_stream_object, _unavailable,
        _profile, _generator, _close,
    ):
        """views.py:605 -- the same assertion on the other side of the fork."""
        from apps.proxy.live_proxy import views

        resolve.return_value = _trusted_decision()
        get_stream_object.return_value = self._channel()
        proxy_server, client_manager = self._active_proxy_server(am_i_owner=True)
        client_manager.add_client.return_value = True
        proxy_server_cls.get_instance.return_value = proxy_server

        views.stream_ts(self._request(), self.channel_id)

        _args, kwargs = client_manager.add_client.call_args
        self.assertEqual(kwargs["user_id"], "4242")
        self.assertEqual(kwargs["output_format"], "fmp4")
```

Add a module-level `_trusted_decision()` helper to that file identical to the one in Step 1 (repeat it; do not import across test modules).

**This is the fork that shipped a blocking regression in 2b-1, and it is the same fork Ruling R3 is about. How to reach each side is settled — read this rather than re-deriving it.**

`_active_proxy_server`'s defaults (`redis_client.exists → True`, `check_if_channel_exists → True`, `am_i_owner=False`) describe an already-active channel, so init is skipped and the test lands on **`views.py:712`**. That is what every test in the file takes except one.

`test_owner_init_resolves_output_profile_once` (`test_stream_ts_client_registration.py:295`) is the exception and the only route to **`views.py:605`**. It overrides the defaults at `:317-321` — `_active_proxy_server(am_i_owner=True)`, then `redis_client.exists → False`, `check_if_channel_exists → False`, `redis_client.hgetall → {}`, `try_acquire_ownership → True`, plus the `_get_channel_init_lock` / `_finish_channel_init_lock` / `_clear_channel_setting_up` wiring at `:322-330` and a `generate_stream_url` return value at `:308-318`. **Copy that override block into the owner test; do not invent one.**

So the follower test as written in Step 2 is correct as it stands, and the owner test needs that override block added. Confirm rather than assume, one test at a time — a coverage run over the whole module is not evidence, because two tests can between them hit both lines while neither *asserts* the behaviour that differs:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && docker exec dispatcharr-testrunner \
  python -m coverage run --include='*/live_proxy/views.py' /repo/manage.py test \
  apps.proxy.live_proxy.tests.test_stream_ts_client_registration.StreamTsClientRegistrationTests.test_a_trusted_owner_registers_the_hops_user_id_and_format \
  && docker exec dispatcharr-testrunner python -m coverage report -m | grep views.py
```

Run the same for the follower test. Read the `Missing` column: the owner test must **not** list 605 as missing, the follower test must not list 712 as missing. Record both in the task's completion note. If the owner test still lands on `:712`, the override block was copied incompletely — fix that; do not record the gap, and do not weaken an assertion to make one pass.

**Hazard A — do not put the new assertions into `test_owner_init_resolves_output_profile_once` itself.** That test patches `_output_profile_for` *and* `_resolve_output_format` and then asserts `assert_called_once()` on both. It pins **arity, not behaviour**: it says the helpers are called once, never what they return or what they do with the decision. An `output_format`/`client_ip` assertion written into a test that mocks away the thing under test asserts nothing — the exact family of defect principle 2 names. The new tests therefore leave `_resolve_output_format` **unpatched** (they want the real one) and patch only `_output_profile_for`, which is Task 5's concern, not Task 3's.

**Hazard B — `assert_called_once()` at `:343` is also pinning the `output_options_resolved` flag.** It says `:712` does *not* re-resolve after `:605` already did. A careless edit to that flag in Step 6 breaks this test, and the failure message will say "called twice", not "you broke the flag". If you see that failure, read it as a real finding about the flag, not as a fixture that needs adjusting.

**Hazard C — 18 patch sites, across five files, depend on `_resolve_output_format` staying on the call path in `views`.** Verified:

```
apps/proxy/live_proxy/tests/test_stream_ts_client_registration.py  (×7)
apps/proxy/live_proxy/tests/test_ghost_session_cleanup.py          (×5)
apps/proxy/live_proxy/tests/test_live_db_cleanup.py                (×3)
apps/proxy/live_proxy/tests/test_internal_principal_no_redirect.py (×2)
apps/proxy/live_proxy/tests/test_channel_names_on_the_contract.py  (×1)
```

all spelled `@patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")`.

**State the mechanics precisely, because the obvious framing is slightly wrong and the wrong framing leads to the dangerous fix.** `patch("...views._resolve_output_format")` rebinds a name in the `views` module's globals. `views.py:606` and `:713` call `_resolve_output_format(...)`, which resolves that global **at call time** — so the patch intercepts. That stays true whether the global is a locally-defined function (what Step 6 writes) *or* a bare re-export (`from apps.proxy.authorize import resolve_output_format as _resolve_output_format`); a re-export alone does **not** break these patches.

What breaks them, silently, is the call site ceasing to go through that global — for instance changing `:606`/`:713` to a function-local `from apps.proxy.authorize import resolve_output_format` and calling it directly, which is this codebase's house style (602 function-local imports) and therefore an easy accident. Then the `views._resolve_output_format` name still exists, all 18 patches still bind, and all 18 pass while intercepting nothing.

**Required landing shape:** `views._resolve_output_format` stays a module-level `def` in `views.py`, both call sites keep calling it by that bare name, and the delegation to `apps.proxy.authorize.resolve_output_format` happens *inside* it. Verify mechanically after Step 6:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && \
  grep -n 'def _resolve_output_format' apps/proxy/live_proxy/views.py && \
  grep -c '= _resolve_output_format(' apps/proxy/live_proxy/views.py && \
  grep -c 'resolve_output_format' apps/proxy/live_proxy/views.py
```

Expected: one `def`, **2** call sites through the bare name, and a total count of 4 (`def` + 2 calls + the one function-local import inside the wrapper). A higher total means a call site is reaching past the wrapper.

Then prove the patches still bite, once, by sabotage: temporarily make the wrapper's body `raise AssertionError("unpatched")`, run `apps.proxy.live_proxy.tests`, and confirm the tests that patch it still **pass** (the patch replaced the body) while the new Task 3 tests, which do not patch it, **fail**. Revert the sabotage. A patch that no longer intercepts is invisible in every other way.

- [ ] **Step 3: Write the failing test — Django resolves the username**

Append to `core/tests/test_relay_events.py` (read its existing imports and helpers first):

```python
class RelayEventUsernameResolutionTests(TestCase):
    """The relay posts a user id; Django turns it into a name.

    The relay has no User row after 2b-2 (authorize_views no longer
    fetches one on the trusted path), and the SystemEvent row's details
    carried `username` before this change -- externally observable, so it
    must keep carrying it.
    """

    def test_a_user_id_in_details_becomes_a_username(self):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(
            username="2b2-events-user", password="x"
        )
        with patch("core.relay_events.log_system_event") as write:
            result = apply_event_batch([
                {
                    "type": "client_connect",
                    "channel_id": "",
                    "channel_name": "Ch",
                    "details": {"user_id": str(user.id), "client_ip": "203.0.113.9"},
                }
            ])
        self.assertEqual(result["accepted"], 1)
        _args, kwargs = write.call_args
        self.assertEqual(kwargs["username"], "2b2-events-user")
        self.assertNotIn("user_id", kwargs)

    def test_an_unknown_user_id_becomes_a_null_username_not_an_error(self):
        with patch("core.relay_events.log_system_event") as write:
            result = apply_event_batch([
                {"type": "client_connect", "details": {"user_id": "99999999"}}
            ])
        self.assertEqual(result["accepted"], 1)
        _args, kwargs = write.call_args
        self.assertIsNone(kwargs["username"])

    def test_an_explicit_username_is_left_alone(self):
        # The untrusted path still has a User object and sends the name
        # directly; resolution must not overwrite it.
        with patch("core.relay_events.log_system_event") as write:
            apply_event_batch([
                {"type": "client_connect", "details": {"username": "sent-by-relay"}}
            ])
        _args, kwargs = write.call_args
        self.assertEqual(kwargs["username"], "sent-by-relay")
```

- [ ] **Step 3b: Write the failing test that pins "a live tune performs zero `User` queries"**

Under Ruling R1 the live path holds no `User` object at all, so the zero-query property is structural rather than a matter of access patterns — but structural today is not structural in six months, when a logging line nobody reviews resolves the user for a message. Pin it, do not assert it in prose. The second test here is the one that pins **Ruling R1b's decision** about what `user_id` means, and it supplies the only input that distinguishes R1b's meaning from today's: a digit header naming a user who does not exist.

**Not `assertNumQueries(0)`:** other Stage 2b residuals still query on this path (`get_stream_object`, `channel.get_stream_profile()` — issue #253), so a count would be brittle and would fail for the wrong reason. Match on the **user table** in the executed SQL instead, so the failure names its own cause.

Append to `apps/proxy/live_proxy/tests/test_stream_ts_client_registration.py`. Note this one is a `TestCase`, not the file's `SimpleTestCase` — it needs a real database connection for the query capture to mean anything.

```python
class TrustedTuneQueriesNoUserRowTests(TestCase):
    """No live tune may query the User table (2b-2, Rulings R1 and R1b).

    The output format arrives on X-Relay-Output-Format and the client
    hash is written from X-Relay-User's string, so result_from_headers
    skips the row entirely on SURFACE_LIVE/SURFACE_LIVE_XC. The VOD and
    catch-up surfaces D1 leaves in Python still resolve it eagerly and
    are unaffected. This test is what makes that a rule rather than a
    property of today's call graph.
    """

    def test_no_query_touches_the_user_table_on_a_trusted_tune(self):
        from django.contrib.auth import get_user_model
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        # Vacuous-pass guard: a substring that matches nothing passes
        # every assertion below while proving nothing, so fail loudly if
        # AUTH_USER_MODEL ever moves. 'accounts_user' is
        # settings.AUTH_USER_MODEL = "accounts.User" (dispatcharr/
        # settings.py:357) with no db_table override.
        user_table = get_user_model()._meta.db_table
        self.assertEqual(user_table, "accounts_user")

        helper = StreamTsClientRegistrationTests("setUp")
        helper.setUp()
        proxy_server, client_manager = helper._active_proxy_server(am_i_owner=False)
        client_manager.add_client.return_value = True

        with CaptureQueriesContext(connection) as captured:
            with patch("apps.proxy.live_proxy.views.ProxyServer") as proxy_server_cls, \
                 patch("apps.proxy.live_proxy.views.resolve_authorization",
                       return_value=_trusted_decision()), \
                 patch("apps.proxy.live_proxy.views.get_stream_object",
                       return_value=helper._channel()), \
                 patch("apps.proxy.live_proxy.views.ChannelService"
                       ".is_channel_unavailable_for_new_clients", return_value=False), \
                 patch("apps.proxy.live_proxy.views._output_profile_for",
                       return_value=None), \
                 patch("apps.proxy.live_proxy.views.create_stream_generator"), \
                 patch("apps.proxy.live_proxy.views.close_old_connections"):
                proxy_server_cls.get_instance.return_value = proxy_server
                from apps.proxy.live_proxy import views

                views.stream_ts(helper._request(), helper.channel_id)

        offenders = [q["sql"] for q in captured.captured_queries if user_table in q["sql"]]
        self.assertEqual(
            offenders,
            [],
            "a trusted tune queried the user table -- something read "
            "AuthorizeResult.user on a live surface; see Ruling R1",
        )

    def test_a_header_naming_a_deleted_user_still_registers_that_id(self):
        """Ruling R1b's decision, pinned on the one input that shows it.

        A digit X-Relay-User whose row no longer exists: today
        result_from_headers re-queries and the client hash records "0";
        after 2b-2 it records what the hop resolved. The window is one
        request (the auth_request subrequest to registration), closing it
        means re-querying, and the Go relay cannot re-query at all -- so
        the contract's meaning becomes "what the hop said" and this test
        is where that is written down rather than discovered.

        4242 is not a real row and not 0: "0" is add_client's own
        fallback, so asserting "0" here would pass under either meaning.
        """
        from django.contrib.auth import get_user_model
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.assertFalse(get_user_model().objects.filter(id=4242).exists())
        user_table = get_user_model()._meta.db_table

        helper = StreamTsClientRegistrationTests("setUp")
        helper.setUp()
        proxy_server, client_manager = helper._active_proxy_server(am_i_owner=False)
        client_manager.add_client.return_value = True

        with CaptureQueriesContext(connection) as captured:
            with patch("apps.proxy.live_proxy.views.ProxyServer") as proxy_server_cls, \
                 patch("apps.proxy.live_proxy.views.resolve_authorization",
                       return_value=_trusted_decision(user_id="4242")), \
                 patch("apps.proxy.live_proxy.views.get_stream_object",
                       return_value=helper._channel()), \
                 patch("apps.proxy.live_proxy.views.ChannelService"
                       ".is_channel_unavailable_for_new_clients", return_value=False), \
                 patch("apps.proxy.live_proxy.views._output_profile_for",
                       return_value=None), \
                 patch("apps.proxy.live_proxy.views.create_stream_generator"), \
                 patch("apps.proxy.live_proxy.views.close_old_connections"):
                proxy_server_cls.get_instance.return_value = proxy_server
                from apps.proxy.live_proxy import views

                views.stream_ts(helper._request(), helper.channel_id)

        _args, kwargs = client_manager.add_client.call_args
        self.assertEqual(kwargs["user_id"], "4242")
        self.assertEqual(
            [q["sql"] for q in captured.captured_queries if user_table in q["sql"]],
            [],
            "the tune re-queried to discover the user was gone -- that is "
            "the query R1 removes, and the Go relay cannot make it",
        )
```

If reusing `StreamTsClientRegistrationTests`'s helpers this way is awkward in practice, lift `_channel`, `_active_proxy_server` and `_request` to module-level functions and have both classes call them. **Do not copy them** — two drifting copies of a fixture is how the follower half stops resembling the owner half.

- [ ] **Step 4: Run all three test modules to verify they fail**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && docker exec dispatcharr-testrunner \
  python /repo/manage.py test \
  apps.proxy.live_proxy.tests.test_output_format_from_the_hop \
  apps.proxy.live_proxy.tests.test_stream_ts_client_registration \
  core.tests.test_relay_events -v2
```

Expected: FAIL — `_resolve_output_format() got an unexpected keyword argument 'decision'`, `KeyError: 'user_id'`, and the username assertions.

- [ ] **Step 5: Stop querying `User` on the live surfaces in `result_from_headers`**

`AuthorizeResult.user` stays a plain field (`user: object = None`); nothing about the dataclass changes. The whole edit is in `result_from_headers`, which already receives the surface it is answering for. Replace its query:

```python
    user_id = (request.META.get(META_RELAY_USER) or "").strip()
    user = None
    if user_id.isdigit():
        user = User.objects.filter(id=int(user_id)).first()
```

with:

```python
    # 2b-2. The live surfaces no longer need the row at all: the output
    # format arrives on X-Relay-Output-Format and the client hash is
    # written from this string, so nothing on that path reads
    # AuthorizeResult.user. Skipping the query there is what closes the
    # spec's Stage 2b row for authorize_views.py:112-141.
    #
    # Every other surface keeps it, verbatim. D1 (spec line 433) leaves
    # /proxy/vod/, /proxy/catchup/ and /streaming/timeshift.php in Python
    # and they read the row at eleven `is None`/`is not None` sites and
    # three truthiness ones (see the 2b-2 plan's Ruling R1). A lazy proxy
    # cannot serve those: `is` is not overloadable, so a stand-in object
    # is never None and every identity check flips for a user deleted
    # mid-stream. Splitting on the surface keeps a real row or a real
    # None everywhere, and it splits exactly where the phase does -- the
    # live surfaces are the ones 2c ports to Go.
    #
    # The else branch below is not a fallback: it is the whole of the
    # VOD and catch-up behaviour, unchanged. Those views pass
    # SURFACE_VOD (vod_proxy/views.py:634), SURFACE_VOD_XC (:1417,
    # :1454), SURFACE_CATCHUP_XC (timeshift/views.py:162) and
    # SURFACE_CATCHUP (:292) -- never a live surface -- so every
    # consumer downstream still gets a real row or a real None. That
    # matters most at vod_proxy/views.py:783, where `if user is None`
    # is a RECOVERY path that re-resolves the principal from the Redis
    # session mapping when a VOD redirect stripped the token; a
    # non-None stand-in there would make it dead code and silently
    # drop the user.
    user_id = (request.META.get(META_RELAY_USER) or "").strip()
    user = None
    if surface in (SURFACE_LIVE, SURFACE_LIVE_XC):
        if not user_id.isdigit():
            user_id = ""
    else:
        if user_id.isdigit():
            user = User.objects.filter(id=int(user_id)).first()
        user_id = str(user.id) if user is not None else ""
```

and in the returned `AuthorizeResult`, `user_id=user_id` replaces `user_id=str(user.id) if user is not None else ""`; the `user=user` line is unchanged.

Import `SURFACE_LIVE` and `SURFACE_LIVE_XC` in `authorize_views.py` if they are not already there (`grep -n 'SURFACE_LIVE' apps/proxy/authorize_views.py` — `_surface_for` uses them, so they almost certainly are).

**Note what this does and does not change.** On the live surfaces `user_id` now means "the row existed when the hop authorized", not "the row exists now" — Ruling R1b, decided and pinned by Step 3b's deleted-user test, not absorbed silently. On every other surface both fields are byte-identical to today. And `stream_ts`'s `if user is None: user = decision.user` (`views.py:174-175`) now leaves `user` as a genuine `None` on a trusted tune, which is a value that path already handles for every anonymous tune today — Step 6 supersedes each of its consumers regardless.

**There is no `_LazyUser` class.** An earlier draft of this plan had one; it is withdrawn for the reason in Ruling R1, and the `SimpleLazyObject` note that went with it is withdrawn with it. Do not reintroduce either — if a future reader reaches for a lazy proxy here, R1's table of eleven identity checks is the answer.

- [ ] **Step 5b: Check the surface split's premise, and pin it**

R1's correctness rests on one claim: **no view outside `live_proxy` passes a live surface to `resolve_authorization`.** If one did, its `decision.user` would become `None` and a consumer expecting a row would misbehave — worst at `vod_proxy/views.py:783`, a recovery path, where it would go quietly dead rather than fail.

Verify it against the tree rather than against R1's table:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && \
  grep -rn -A 4 'resolve_authorization(' apps/proxy/vod_proxy/views.py apps/timeshift/views.py | grep SURFACE_
```

Expected, exactly: `SURFACE_VOD`, `SURFACE_VOD_XC` (×2), `SURFACE_CATCHUP_XC`, `SURFACE_CATCHUP`. Any `SURFACE_LIVE`/`SURFACE_LIVE_XC` in that output means R1's premise is false for that view — **stop and report it** rather than working around it.

Then pin the claim so a future view cannot quietly break it. Append to `apps/proxy/tests/test_authorize_view.py`:

```python
class SurfaceSplitPremiseTests(TestCase):
    """result_from_headers skips the User row on live surfaces only.

    Asserted as the decision's own output, on both sides, because the
    split is invisible otherwise: a live surface must not resolve the
    row, and a non-live one must, and a test of only one side would
    pass if the condition were inverted.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="2b2-split", password="x")

    def _trusted(self, surface):
        from django.test import RequestFactory

        request = RequestFactory().get(
            "/proxy/ts/stream/x",
            HTTP_X_DISPATCHARR_AUTHORIZED=internal_auth.relay_trust_token(),
            HTTP_X_RELAY_USER=str(self.user.id),
        )
        return authorize_views.result_from_headers(request, surface)

    def test_a_live_surface_resolves_no_row(self):
        for surface in (authorize.SURFACE_LIVE, authorize.SURFACE_LIVE_XC):
            with self.subTest(surface=surface):
                result = self._trusted(surface)
                self.assertIsNone(result.user)
                self.assertEqual(result.user_id, str(self.user.id))

    def test_every_other_surface_still_resolves_the_row(self):
        for surface in (
            authorize.SURFACE_VOD,
            authorize.SURFACE_VOD_XC,
            authorize.SURFACE_CATCHUP,
            authorize.SURFACE_CATCHUP_XC,
        ):
            with self.subTest(surface=surface):
                result = self._trusted(surface)
                self.assertEqual(result.user.id, self.user.id)
                self.assertEqual(result.user_id, str(self.user.id))

    def test_a_non_live_surface_with_a_deleted_row_still_answers_None(self):
        # The input that separates every design considered here. On a
        # non-live surface the old meaning survives intact: no row, so
        # user is None AND user_id is "" -- which is what
        # vod_proxy/views.py:783's recovery path keys off.
        from django.test import RequestFactory

        request = RequestFactory().get(
            "/proxy/vod/movie/1/s",
            HTTP_X_DISPATCHARR_AUTHORIZED=internal_auth.relay_trust_token(),
            HTTP_X_RELAY_USER="4242",
        )
        self.assertFalse(User.objects.filter(id=4242).exists())
        result = authorize_views.result_from_headers(request, authorize.SURFACE_VOD)
        self.assertIsNone(result.user)
        self.assertEqual(result.user_id, "")
```

Check `SURFACE_VOD_XC` and `SURFACE_CATCHUP_XC` are exported from `apps/proxy/authorize.py` under those names before writing this (`grep -n '^SURFACE_' apps/proxy/authorize.py`); use whatever the module actually calls them.

- [ ] **Step 6: Thread the decision through the live path**

In `apps/proxy/live_proxy/views.py`:

Replace `_resolve_output_format`'s body (`:114-135`) with a delegating wrapper. **Keep the name, keep it a module-level `def`, keep the positional signature, and keep both call sites calling it by that bare name** — 18 patch sites across five test files depend on it staying on the call path, and Step 2's Hazard C says exactly how that goes silently wrong and how to verify it did not. `_FORMAT_ALIASES` moved to `authorize.py` in Task 1:

```python
def _resolve_output_format(user, force=None, request=None, decision=None):
    """Return the output format string to use for this client.

    The rule itself lives in apps/proxy/authorize.py (2b-2), so the hop
    and the inline path cannot drift. When nginx authorized the tune, the
    hop already applied it and the answer is on X-Relay-Output-Format --
    reading it here is what removes the User query
    authorize_views.result_from_headers used to run on every trusted tune.

    `force` still wins: it is stream_xc's extension-derived override
    (.ts/.mp4), a property of this call and not of the decision, so the
    hop never saw it.
    """
    from apps.proxy.authorize import resolve_output_format

    if force:
        return force
    if decision is not None and decision.trusted:
        return decision.output_format or CoreSettings.get_default_output_format()
    return resolve_output_format(request, user, force=None)
```

Update both call sites to pass the decision — `views.py:606` and `:713`:

```python
                        resolved_output_format = _resolve_output_format(
                            user, force_output_format, request, decision=decision
                        )
```

Replace the client-IP resolution at `views.py:195`:

```python
        # 2b-2 / parity-matrix row 17. The hop resolved this once with
        # get_client_ip's trusted-proxy rules (LOCAL_NETWORK_CIDRS /
        # DISPATCHARR_TRUSTED_PROXIES); reading it back is what lets a
        # relay behind proxy_pass -- which sees nginx as its peer, not
        # the viewer -- report the real address. Untrusted (dev
        # runserver, any request that did not come through a relay-bound
        # location) resolves it here exactly as before.
        client_ip = (
            decision.client_ip
            if decision is not None and decision.trusted and decision.client_ip
            else get_client_ip(request)
        )
```

Pass `user_id` to both `add_client` calls (`views.py:613-617` and `:732-736`) — add one keyword to each:

```python
                            client_id, client_ip, client_user_agent, user,
                            user_id=decision.user_id if decision is not None else None,
                            output_format=resolved_output_format,
                            output_profile_id=resolved_output_profile.id if resolved_output_profile else None,
```

Pass `user_id` to both generator factories (`views.py:784` and `:794-796`) — add `user_id=decision.user_id if decision is not None else None,` alongside the existing `user=user,`.

- [ ] **Step 7: `add_client` prefers the id it was handed**

In `apps/proxy/live_proxy/client_manager.py`, change the signature (`:215`) and the two derived values:

```python
    def add_client(self, client_id, client_ip, user_agent=None, user=None,
                   user_id=None, output_format='mpegts', output_profile_id=None):
```

```python
        # user_id is the string the authorize hop put on X-Relay-User.
        # Preferred over user.id so a trusted tune never has to
        # materialise the row (2b-2); `user` is still what the untrusted
        # path hands in.
        resolved_user_id = user_id or (str(user.id) if user is not None else None)
        client_data = {
            ...
            "user_id": resolved_user_id or "0",
            ...
        }
```

In the CLIENT_CONNECTED pub/sub payload (`:267-275`), leave `username` derived from `user` but add the id beside it:

```python
                        "username": user.username if user is not None else "unknown",
                        "user_id": resolved_user_id or "0",
```

`username` degrades to `"unknown"` on the trusted path. That is deliberate and invisible: the only consumer of this event is `apps/proxy/live_proxy/server.py:246`, which logs that it arrived and never reads the payload's fields. Put that sentence in the code as a comment, citing `server.py:246`.

- [ ] **Step 8: The generators send an id, not a name**

In `apps/proxy/live_proxy/output/ts/generator.py`: add `user_id=None` to the class `__init__` (`:26-60`) and to `create_stream_generator` (`:663-681`), store `self.user_id = user_id`, and at both `emit_event` sites (`:126-135` and `:643-654`) replace

```python
                    username=self.user.username if self.user else None
```

with

```python
                    # 2b-2: the relay has no User row on a trusted tune.
                    # core/relay_events.py resolves the name in the API
                    # process, which is where the SystemEvent write
                    # already happens (Phase 1 PR 6).
                    user_id=self.user_id or None,
```

Do the same in `apps/proxy/live_proxy/output/fmp4/generator.py` (`:28-67`, `:108-116`, and its factory).

**Do not leave `username=` beside `user_id=`** — two keys for one fact is how the next reader learns the wrong one is authoritative.

- [ ] **Step 9: Django resolves the name**

In `core/relay_events.py`'s `apply_event_batch`, after the three `details.pop(...)` lines and before the `log_system_event` call:

```python
        # 2b-2: the relay posts a user id because it no longer holds a
        # User row on a live surface (apps/proxy/authorize_views.py's
        # result_from_headers, 2b-2 Ruling R1). Resolve
        # the display name here, where the SystemEvent write already
        # runs. An explicit username from the untrusted path wins; an
        # unknown id becomes None, exactly what the relay used to send
        # for an anonymous client.
        user_id = details.pop("user_id", None)
        if user_id and "username" not in details:
            details["username"] = _username_for(user_id)
```

and above `apply_event_batch`:

```python
def _username_for(user_id):
    """The display name for a relay-posted user id, or None.

    Never raises: a malformed id, a deleted user and a database hiccup
    all mean "no name to show", and one bad entry must not lose the rest
    of the batch.
    """
    from django.contrib.auth import get_user_model

    try:
        return (
            get_user_model()
            .objects.filter(id=int(user_id))
            .values_list("username", flat=True)
            .first()
        )
    except (TypeError, ValueError):
        return None
    except Exception as exc:  # pragma: no cover - defensive, see docstring
        logger.warning("Could not resolve username for relay event: %s", exc)
        return None
```

- [ ] **Step 10: Run the tests to verify they pass**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && docker exec dispatcharr-testrunner \
  python /repo/manage.py test \
  apps.proxy.live_proxy.tests.test_output_format_from_the_hop \
  apps.proxy.live_proxy.tests.test_stream_ts_client_registration \
  core.tests.test_relay_events -v2
```

Expected: PASS.

- [ ] **Step 11: Run all four labels — this is the step that catches the VOD and catch-up fallout**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && docker exec dispatcharr-testrunner \
  python /repo/manage.py test apps.proxy.tests apps.proxy.live_proxy.tests apps.channels.tests core.tests
```

Expected: PASS, and **no VOD or timeshift test should change behaviour at all** — R1's surface split leaves `result_from_headers` byte-identical for every non-live surface. If one of them fails, the surface condition is wrong (most likely `SURFACE_LIVE_XC` omitted, or the `else` branch not restoring `user_id=str(user.id) if user is not None else ""`); fix the condition, never the caller.

- [ ] **Step 12: Commit**

Stage `apps/proxy/authorize_views.py apps/proxy/live_proxy/views.py apps/proxy/live_proxy/client_manager.py apps/proxy/live_proxy/output/ts/generator.py apps/proxy/live_proxy/output/fmp4/generator.py core/relay_events.py` plus the three test files, then commit with `-F`. Message: `relay(phase2): the output format comes from the hop; no User row on a trusted tune (2b-2 task 3)`.

---

## Task 4: the live path reads `X-Relay-Client-IP`, and row 17 stays true

**Files:**
- Test: `apps/proxy/live_proxy/tests/test_client_ip_provenance.py` (extend)
- Modify: `docs/relay-parity-matrix.md` — row 17 only

**Interfaces:**
- Consumes: `AuthorizeResult.client_ip` (Task 1) and the `views.py:195` change already made in Task 3 Step 6.
- Produces: nothing new.

The code change landed in Task 3 Step 6 because it sits three lines from the `user_id` threading. This task is its pin and its documentation.

- [ ] **Step 1: Write the failing test**

Append to `apps/proxy/live_proxy/tests/test_client_ip_provenance.py`. The existing test drives the **untrusted** path (no trust marker, so `get_client_ip` honours `X-Forwarded-For`); this one drives the trusted path, where a *different* address on `X-Relay-Client-IP` must win over the forwarded one — which is what makes it a real ordering assertion rather than a restatement.

```python
TRUSTED_CLIENT = "198.51.100.7"  # TEST-NET-2: different from FORWARDED_CLIENT

    def test_a_trusted_tune_reports_the_hops_client_ip_not_the_forwarded_one(self):
        """The header wins on the trusted path (parity-matrix row 17).

        Two different TEST-NET addresses: X-Forwarded-For carries one and
        X-Relay-Client-IP the other, so the assertion can only pass if
        the decision's value is the one used. Sending the same address on
        both would pass with the reading deleted.
        """
        from apps.proxy.internal_auth import relay_trust_token

        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(
                upstream_url=self.upstream.url, profile=profile
            )
            identifier = str(channel.uuid)

            with self.tuned(channel) as first:
                first.read(20 * 188)

                trusted = requests.get(
                    f"{self.live_server_url}/proxy/ts/stream/{identifier}",
                    headers={
                        "X-Dispatcharr-Authorized": relay_trust_token(),
                        "X-Relay-Channel": identifier,
                        "X-Relay-Client": "client_2b2_trusted",
                        "X-Relay-User": "",
                        "X-Relay-Output": "",
                        "X-Relay-Output-Format": "mpegts",
                        "X-Relay-Client-IP": TRUSTED_CLIENT,
                        "X-Forwarded-For": FORWARDED_CLIENT,
                    },
                    stream=True,
                    timeout=20,
                )
                self.addCleanup(trusted.close)
                self.assertEqual(trusted.status_code, 200)
                next(trusted.iter_content(chunk_size=188))

                status = requests.get(
                    f"{self.live_server_url}/proxy/relay/channels/{identifier}",
                    headers=_signed(
                        "GET", f"/proxy/relay/channels/{identifier}"
                    ),
                    timeout=10,
                )
                self.assertEqual(status.status_code, 200)
                clients = {
                    c["client_id"]: c["ip_address"]
                    for c in status.json()["clients"]
                }
                self.assertEqual(
                    clients.get("client_2b2_trusted"), TRUSTED_CLIENT
                )
```

Read the existing test's status-endpoint call and payload shape before writing this; reuse its exact URL, header helper (`_signed`) and JSON keys rather than the shapes above if they differ.

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && docker exec dispatcharr-testrunner \
  python /repo/manage.py test apps.proxy.live_proxy.tests.test_client_ip_provenance -v2
```

Expected: the new test FAILS with `'203.0.113.9' != '198.51.100.7'` **if** Task 3 Step 6's change was not made, or PASSES if it was. If it passes immediately, delete the `decision.client_ip` branch from `views.py:195`, re-run to watch it fail, and put the branch back — a test that has never been seen to fail is not a pin.

- [ ] **Step 3: Update parity-matrix row 17**

In `docs/relay-parity-matrix.md:175`, the row's `Source` and `Notes` cells change; the `Pin` cell does **not** (the row is already pinned — R4). The row must stay on one line, cells joined by exactly ` | `, no padding, no trailing whitespace, no literal `|` inside a cell — `e2e/tests/guards/parity-matrix.spec.ts` asserts all of that.

New `Behaviour` (unchanged in substance, retargeted): `` `ip_address` on both status endpoints is the real client address — resolved once by the authorize hop via `get_client_ip()` and carried on `X-Relay-Client-IP` when nginx authorized the tune, resolved inline otherwise ``

New `Source`: `` `dispatcharr/utils.py:342-370`, `apps/proxy/authorize.py:443-455`, `apps/proxy/live_proxy/views.py:195`, `apps/proxy/live_proxy/client_manager.py:215-230`, `apps/proxy/relay_serializers.py:29`, `apps/proxy/relay_serializers.py:79` ``

New `Notes`: `` 2b-2 made the hop the source; the invariant this row pins is that `ip_address` stays the real client address across that change, which is why the pin asserts a value and never a mechanism. Two tests in the pinned file: the untrusted path honours `X-Forwarded-For`, the trusted path prefers the hop's header over a different forwarded address ``

**Re-verify every line number in the `Source` cell after Tasks 1 and 3 moved code** — the guard checks that each cited line exists in each cited file, and a citation that merely resolves is not a citation that is right.

- [ ] **Step 4: Run the tests and the matrix guard**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && docker exec dispatcharr-testrunner \
  python /repo/manage.py test apps.proxy.live_proxy.tests.test_client_ip_provenance -v2
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2/e2e && npx playwright test --project=guards parity-matrix.spec.ts
```

Expected: both PASS.

- [ ] **Step 5: Commit**

Stage the test file and `docs/relay-parity-matrix.md`, commit with `-F`. Message: `relay(phase2): the client address comes from the hop (2b-2 task 4, parity row 17)`.

---

## Task 5: `output_profiles` on `next-source`'s response

**Files:**
- Modify: `apps/proxy/serializers.py` — new `OutputProfileRefSerializer`, one field on `NextSourceResponseSerializer`
- Modify: `apps/proxy/next_source.py` — `_with_output_profiles()`, applied wherever `_with_proxy_settings()` is
- Modify: `apps/proxy/api_views.py:64-76` — the 404-degraded answer
- Modify: `apps/proxy/control_plane.py:186-188` — the 404-degraded client answer
- Test: `apps/proxy/tests/test_next_source_api.py` (extend)

**Interfaces:**
- Produces: `next-source`'s 200 body gains `output_profiles`, an object keyed by stringified profile id whose values are `{"id": int, "argv": [str, ...]}`.
- Consumes: nothing. **Deliberately not read by the Python relay** — see Ruling R3.

- [ ] **Step 1: Write the failing test**

Append to `apps/proxy/tests/test_next_source_api.py` (read its existing internal-header helper and channel fixture first and reuse them):

```python
class OutputProfilesOnTheContractTests(TestCase):
    """Every active OutputProfile's built command, on every answer.

    Keyed by id and carrying them all, not just the one X-Relay-Output
    named, because next-source runs once per CHANNEL (tune, failover,
    resume) while the profile is resolved once per CLIENT -- and the
    second client on a running channel makes no next-source call at all
    (apps/proxy/live_proxy/views.py:712). A single-profile field could
    not answer that client's question. See the plan's Ruling R3.
    """

    def setUp(self):
        super().setUp()
        # core/migrations/0024_outputprofile.py seeds TWO locked,
        # is_active profiles ('Media Server (AC3 Audio)' and 'Web Player
        # (AAC Audio)'), so the table is never empty in a test database.
        # Deactivating them is what makes the assertions below exact
        # rather than "contains" -- and a `contains` assertion here would
        # pass while the filter silently returned every row, active or
        # not, which is the one thing the is_active filter exists to do.
        from core.models import OutputProfile

        OutputProfile.objects.update(is_active=False)

    def test_the_answer_carries_every_active_profiles_argv(self):
        from core.models import OutputProfile

        active = OutputProfile.objects.create(
            name="2b2-ac3",
            command="ffmpeg",
            parameters="-i pipe:0 -c:a ac3 pipe:1",
            is_active=True,
        )
        OutputProfile.objects.create(
            name="2b2-disabled",
            command="ffmpeg",
            parameters="-i pipe:0 -c:a aac pipe:1",
            is_active=False,
        )

        answer = self._next_source(self.channel.uuid)

        # A literal, never active.build_command(): an expected value the
        # code under test computes cannot fail.
        self.assertEqual(
            answer["output_profiles"],
            {
                str(active.id): {
                    "id": active.id,
                    "argv": ["ffmpeg", "-i", "pipe:0", "-c:a", "ac3", "pipe:1"],
                }
            },
        )

    def test_an_answer_with_no_source_still_carries_the_map(self):
        # The degraded shapes matter to a Go client, which indexes this
        # key unconditionally: a KeyError on the failover path is a tune
        # failure, not a missing field.
        from core.models import OutputProfile

        OutputProfile.objects.create(
            name="2b2-only", command="ffmpeg", parameters="-i pipe:0 pipe:1",
            is_active=True,
        )
        answer = self._next_source("00000000-0000-0000-0000-000000000000", expect=404)
        self.assertIn("output_profiles", answer)

    def test_no_active_profiles_is_an_empty_object_not_a_missing_key(self):
        # setUp deactivated the two seeded rows and this test adds none.
        answer = self._next_source(self.channel.uuid)
        self.assertEqual(answer["output_profiles"], {})

    def test_a_deactivated_seeded_profile_is_absent_from_the_map(self):
        # The is_active filter, asserted against a row that really
        # exists: reactivate one of the migration's own locked profiles
        # and assert only that its id appears, then deactivate it and
        # assert it does not. Without this, `is_active=True` could be
        # dropped from the queryset and every test above would still
        # pass, because they only ever create active rows.
        from core.models import OutputProfile

        seeded = OutputProfile.objects.get(name="Media Server (AC3 Audio)")
        OutputProfile.objects.filter(id=seeded.id).update(is_active=True)
        self.assertIn(
            str(seeded.id), self._next_source(self.channel.uuid)["output_profiles"]
        )
        OutputProfile.objects.filter(id=seeded.id).update(is_active=False)
        self.assertNotIn(
            str(seeded.id), self._next_source(self.channel.uuid)["output_profiles"]
        )
```

Write `_next_source(identifier, expect=200)` as a small helper on the class if the file has no equivalent: POST to `/api/relay/channels/<identifier>/next-source` with the two internal headers, assert the status, return `response.json()`.

`OutputProfile`'s fields are verified: `name` (unique), `command`, `parameters`, `locked`, `is_active` (`core/models.py:183-196`), and `build_command()` is `[self.command] + shlex_split(self.parameters)` with **no** per-tune substitution (`core/models.py:200-203`) — unlike `StreamProfile.build_command()`, which takes `stream_url`/`user_agent`/`channel_id`. That difference is the whole reason `argv` can be sent finished.

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && docker exec dispatcharr-testrunner \
  python /repo/manage.py test apps.proxy.tests.test_next_source_api.OutputProfilesOnTheContractTests -v2
```

Expected: FAIL with `KeyError: 'output_profiles'`.

- [ ] **Step 3: Declare the wire shape**

In `apps/proxy/serializers.py`, after `RelayProxySettingsSerializer`:

```python
class OutputProfileRefSerializer(serializers.Serializer):
    """One OutputProfile, already built into argv.

    `argv` and not StreamProfileRefSerializer's {command, args} pair on
    purpose: a StreamProfile's command is templated (build_command
    substitutes {streamUrl}/{userAgent}/{channelId} per tune, so only the
    relay can finish it), while an OutputProfile's is not -- it reads raw
    MPEG-TS on pipe:0 and writes to pipe:1 with no per-tune substitution
    at all (core/models.py:200-203). Sending the finished list is what
    lets a Go relay spawn the transcode without reimplementing shlex.
    """

    id = serializers.IntegerField()
    argv = serializers.ListField(child=serializers.CharField(allow_blank=True))
```

and on `NextSourceResponseSerializer`:

```python
class NextSourceResponseSerializer(serializers.Serializer):
    source = SourceSerializer(allow_null=True)
    alternates = SourceSerializer(many=True)
    error = serializers.CharField(allow_null=True)
    proxy_settings = RelayProxySettingsSerializer()
    # Phase 2 PR 2b-2. Every is_active OutputProfile, keyed by
    # stringified id -- not just the one X-Relay-Output named, because
    # next-source runs once per channel while the profile is resolved
    # once per client, and the second client on a running channel makes
    # no next-source call (apps/proxy/live_proxy/views.py:712). A
    # DictField of a nested serializer, so the value shape is still in
    # the OpenAPI schema and a Go client can generate against it.
    output_profiles = serializers.DictField(child=OutputProfileRefSerializer())
```

- [ ] **Step 4: Produce it**

In `apps/proxy/next_source.py`, beside `_with_proxy_settings`:

```python
def _with_output_profiles(answer):
    """Every active OutputProfile's built argv, on every next-source answer.

    Spec § Stage 2b, the `views.py:152` row: "A control-plane response
    body can [carry a built ffmpeg command], unlike a header."

    Deviation from that row, recorded in the 2b-2 plan as Ruling R3: the
    spec says "when X-Relay-Output names a profile", i.e. one profile per
    request. next-source is a per-CHANNEL call (initial tune, failover,
    resume); the profile is resolved per CLIENT, and the client that did
    not initialize the channel never makes a next-source call at all
    (apps/proxy/live_proxy/views.py:712). One profile per request
    therefore cannot answer any client's question but the first's, so the
    whole active set travels instead and a Go relay caches it per channel.

    Nothing in the PYTHON relay consumes this, deliberately: doing so
    would need either a per-client route (the spec rejects one) or a
    Redis cache with staleness semantics nothing has specified.
    apps/proxy/live_proxy/views.py:152's ORM read therefore stays, and
    2b-3 owns the decision to allowlist or close it.
    """
    from core.models import OutputProfile

    answer["output_profiles"] = {
        str(profile.id): {"id": profile.id, "argv": profile.build_command()}
        for profile in OutputProfile.objects.filter(is_active=True)
    }
    return answer
```

Then wrap it around `_with_proxy_settings` at **every** site that produces an answer. The cleanest edit is one line inside `_with_proxy_settings` itself — but do **not** do that; it would make a function named for one thing do two. Instead change each of the six `return _with_proxy_settings(...)` calls in `resolve_source` (`apps/proxy/next_source.py:820`, `:825`, `:828`, `:848`, `:853`, and any other the grep finds) to `return _with_output_profiles(_with_proxy_settings(...))`. Verify none is missed:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && \
  grep -c '_with_proxy_settings(' apps/proxy/next_source.py && \
  grep -c '_with_output_profiles(_with_proxy_settings(' apps/proxy/next_source.py
```

The second count must be exactly one less than the first (the first counts the `def` line too).

- [ ] **Step 5: Close the two degraded shapes**

`apps/proxy/api_views.py:69-73` — the 404 branch already wraps its dict in `next_source._with_proxy_settings(...)`; wrap it in `next_source._with_output_profiles(...)` too, same nesting as Step 4.

`apps/proxy/control_plane.py:186-188` — the client's own 404 substitution returns a bare dict. Add the key so a caller may index it unconditionally:

```python
        if exc.status == 404:
            # Shape-complete so a caller can index the contract's keys
            # without probing. proxy_settings is 2b-1's and is left as it
            # stands; output_profiles is added with the key itself.
            return {
                "source": None,
                "alternates": [],
                "error": "identifier not found",
                "output_profiles": {},
            }
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && docker exec dispatcharr-testrunner \
  python /repo/manage.py test apps.proxy.tests -v2
```

Expected: PASS.

- [ ] **Step 7: Confirm the schema records it**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && docker exec dispatcharr-testrunner \
  python /repo/manage.py spectacular --fail-on-warn --file /tmp/schema.yml && \
  docker exec dispatcharr-testrunner grep -n 'OutputProfileRef' /tmp/schema.yml
```

Expected: the command succeeds and `OutputProfileRef` appears as a component. If `--fail-on-warn` trips on a pre-existing warning unrelated to this change, re-run without it and say so.

- [ ] **Step 8: Commit**

Stage `apps/proxy/serializers.py apps/proxy/next_source.py apps/proxy/api_views.py apps/proxy/control_plane.py apps/proxy/tests/test_next_source_api.py`, commit with `-F`. Message: `contract(phase2): every active OutputProfile's argv on next-source (2b-2 task 5)`.

---

## Task 6: the spec correction, the forged-header gates, and the whole-PR verification

**Files:**
- Modify: `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md:1598` and `:1658`
- Modify: `e2e/tests/streaming/authorize-matrix.spec.ts:120-131`
- Modify: `apps/proxy/tests/test_authorize_view.py` — `test_a_forged_marker_falls_through_to_the_inline_decision`

**Interfaces:** none new.

- [ ] **Step 0: Correct the spec in place**

Spec line 1598's decision — "fold the built command and its args list into `next-source`'s response **when `X-Relay-Output` names a profile**" — is factually wrong (Ruling R3) and would mislead 2c's implementer into building a per-request single-profile client. Correct it where it stands, in the idiom of the corrections that landed in `2fc5b269`: an inline bold withdrawal naming what is true, not a footnote. Read that commit first (`git show 2fc5b269 -- docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`) so the voice matches.

Replace the final sentence of line 1598's "2b's fix" cell — everything from "**Decided in this fix round**" onward — with:

> **Decided in this fix round** (this spec's first draft left two shapes open with no decision, an implementer-facing gap flagged in review as m23): fold the built command into `next-source`'s response rather than a separate route — `next-source` already runs once per tune with the ORM open, and a separate `GET /api/relay/output-profiles/<id>/command` route would be a second round trip for data available at the same moment. **Corrected 2026-09-12, during 2b-2's own planning, and the "when `X-Relay-Output` names a profile" half of that decision is withdrawn: the response carries EVERY `is_active=True` profile, keyed by stringified id, as `{"id": int, "argv": [str, ...]}`.** `next-source` is a per-**channel** call (initial tune, failover, resume — `live_proxy/url_utils.py:56`, `input/manager.py:2076`, `services/channel_service.py:154`), while the Output Profile is resolved per **client** (`live_proxy/views.py:605` on the owner's init path, `:712` on every other client), and the second client on an already-running channel makes no `next-source` call at all. One profile per request therefore answers no client's question but the first's. The Go relay caches the map at tune and serves every later client from memory. **The Python relay does not consume the field** — `views.py:152`'s `OutputProfile.objects.filter(...)` survives 2b-2 deliberately, because closing it in Python would need a cache whose staleness semantics nothing here specifies (today an `OutputProfile` edit reaches the next client; cached, it would reach only the next tune), and it is Python that 2d deletes wholesale — the same reasoning this table already applies to the `channel_status.py` fallback rows above. 2b-3 records it in `zero_orm_allowlist.py` with this paragraph as its citation.

Then fix line 1658's 2b-2 row, whose "What it does" cell still says "folded into `next-source`'s response **when `X-Relay-Output` is set**": change that clause to "folded into `next-source`'s response as an `output_profiles` map of every active profile (see the Stage 2b table's corrected `views.py:152` row)".

Change nothing else in the spec. In particular do **not** touch line 1599's "the Python relay ignores it exactly as it ignores today's five" — Ruling R4 departs from it deliberately and the departure belongs in this PR's description and in parity-matrix row 17, where a reviewer will see it argued, not silently rewritten into the authority document by the PR that disagreed with it.

- [ ] **Step 0b: Check the spec edit did not break its own citations**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && \
  grep -n 'when `X-Relay-Output`' docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
```

Expected: no output. Then re-read both edited cells end to end and confirm no table row gained a literal `|` and no row lost its single-line shape — the Stage 2b and PR tables are Markdown tables and a wrapped cell breaks them.

- [ ] **Step 1: Extend the forged-header `@contract` test**

`e2e/tests/streaming/authorize-matrix.spec.ts::a client-supplied trust marker does not authorize a hidden channel` is this PR's named gate. A forged marker plus the two new headers must still 403. Extend its header block (`:125-130`):

```ts
      {
        'X-Dispatcharr-Authorized': '1',
        'X-Relay-Channel': channel.uuid,
        'X-Relay-User': '1',
        // 2b-2's two additions. A client that forges these gains
        // nothing: the marker still fails the constant-time compare, so
        // result_from_headers is never reached and neither value is
        // read. Sending them is what proves it.
        'X-Relay-Output-Format': 'fmp4',
        'X-Relay-Client-IP': '203.0.113.9',
      }
```

- [ ] **Step 2: Extend the unit test the spec cites beside it**

`apps/proxy/tests/test_authorize_view.py::ResolveAuthorizationTests::test_a_forged_marker_falls_through_to_the_inline_decision` — add the two headers to its `RequestFactory.get(...)` call, and add one assertion that the inline path was taken (`inline.assert_called_once()`), if the test does not already have one.

- [ ] **Step 3: Run both**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && docker exec dispatcharr-testrunner \
  python /repo/manage.py test apps.proxy.tests.test_authorize_view -v2
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2/e2e && npx playwright test --project=streaming authorize-matrix.spec.ts
```

Expected: PASS, with the forged tune still answering 403.

- [ ] **Step 4: Run every backend label this PR touches**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && docker exec dispatcharr-testrunner \
  python /repo/manage.py test apps.proxy.tests apps.proxy.live_proxy.tests apps.channels.tests core.tests
```

Expected: PASS. Report the exact counts.

- [ ] **Step 5: Measure Gate 2's coverage, do not assume it**

This PR adds production statements (`_with_output_profiles`, `_username_for`, the `resolve_output_format` move, `result_from_headers`'s surface branch) and deletes almost none, so the denominator moves in the direction that makes `missing` **easier** to regress, not harder. Measure:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && scripts/coverage_live_path_isolated.sh
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && scripts/coverage_live_path.sh --gate
```

Report the printed `missing` and `percent` and whether `--gate` exited 0. **Do not write a new floor.** `scripts/coverage_live_path.floor`'s `statements` is recorded provenance and is expected to lag; the shape hashes cover the rcfile and the module list, neither of which this PR changes. If `--gate` fails on `missing`, add tests for the uncovered new lines rather than touching the floor.

- [ ] **Step 6: Confirm the whole-branch shape**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && git log --oneline main..HEAD && git diff --stat main...HEAD
```

Check the file list against this plan's § File Structure. Anything modified that is not listed there needs a sentence in the PR description explaining why.

- [ ] **Step 7: Commit and push**

Stage the two test files **and `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`**, commit with `-F`, then:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b2 && git push -u origin migration/phase2b-output-profile-and-user
```

- [ ] **Step 8: Write the PR description**

It must state, in its own words:

1. The two headers, and that `apps/proxy/live_proxy/views.py` reads both on the trusted path — including that this **deviates from spec line 1599**, which says the Python relay ignores `X-Relay-Client-IP`. Cite Ruling R4 and parity-matrix row 17's own `Notes` cell, which anticipates the change.
2. That `result_from_headers` now splits on the surface rather than resolving `User` unconditionally, and why (Ruling R1): D1 leaves VOD and catch-up in Python, fourteen sites read the row, and **eleven of them test `is None`/`is not None`** — so a lazy stand-in could not have served them, because `is` is not overloadable. A live tune now performs zero `User` queries; every non-live surface is byte-identical to today.
2b. That `user_id` consequently means "the row existed when the hop authorized" on the live surfaces, where it used to mean "the row exists now" (Ruling R1b). Say that it is externally observable — it reaches the client hash and the `client_connect` `SystemEvent` — that the divergence window is one request, and that 2c forces the same meaning anyway because the Go relay cannot re-query. Name the test that pins it.
3. That `username` on relay events is resolved by Django (Ruling R2), and that the CLIENT_CONNECTED pub/sub payload's `username` degrades to `"unknown"` on the trusted path with no consumer.
4. That `output_profiles` carries **every active profile**, not the single one the spec's row describes, and why (Ruling R3) — and that **`apps/proxy/live_proxy/views.py:152`'s `OutputProfile.objects.filter(...)` is deliberately still there**, with 2b-3 owning the allowlist entry. This is the item most likely to be read as an omission; say it first among the caveats. Quote Ruling R3's reconciliation paragraph **verbatim** — spec line 1769 makes 2c-1 restate it, and it is written once, here.
5. That the spec itself was corrected at line 1598 and line 1658 (Step 0), and that line 1599 was deliberately **not** corrected — R4's departure is argued in the PR and recorded in parity-matrix row 17 rather than written into the authority document by the PR that disagreed with it.
6. That 2b-2 edits `apps/proxy/live_proxy/views.py` and `apps/proxy/authorize.py` and deliberately leaves issue #253's ORM reads in both (Ruling R7), so 2b-3's author does not read the surrounding edits as a partial fix.
7. The measured Gate 2 number from Step 5.
8. **A reviewer note:** treat Task 3 — the `User`/`username` ripple through `apps/proxy/authorize_views.py`, `live_proxy/views.py`, `client_manager.py`, both generators and `core/relay_events.py` — as its own review surface. It is the only half of this PR that crosses app boundaries, and it is where a mechanical-looking change can drop an externally-observable field (`username` on a `SystemEvent` row). The PR is not split because sequential merging would cost a full CI cycle and a review round for a mechanical ripple; the review is separated instead.

---

## Self-Review

**Spec coverage.**
- Line 1658's scope: `build_command()` folded into `next-source` — Task 5. Both new headers end to end across `authorize_view`, `dispatcharr_api_params.conf`, all nine nginx locations, the greybox spec's `AUTH_REQUEST_SET_VARS`, and `internal_auth.py`'s name pairs — Tasks 1 and 2. Both gates — Task 6 Step 1 (forged `@contract`) and Task 2 Step 6 (`nginx-stream-buffering.spec.ts` test 2).
- Line 1599's `User` row — Task 3, with Ruling R1's surface split and Ruling R1b's decision about what `user_id` then means.
- Lines 1860–1960's NB1 — Task 4, with Ruling R4's deviation.
- Lines 900–905: row 17 is already pinned and is kept true (R4); **row 18 is untouched** and remains 2b-3's.
- Lines 660–800's dev-shape response listing seven headers: this PR makes the seven exist. The `POST /_dispatcharr/authorize-internal` route itself is not in 2b-2's scope and is not added here.

**Placeholder scan.** No "TBD", no "add appropriate handling", no "similar to Task N". Every code step carries the code. Two steps deliberately end in a judgement the implementer must make with evidence — Task 3 Step 2's branch confirmation and Task 4 Step 2's must-fail check — and both say exactly what evidence settles them.

**The design that is NOT here.** An earlier draft resolved `AuthorizeResult.user` through a `_LazyUser` proxy. It is withdrawn: eleven of its fourteen consumers test `is None`/`is not None`, and `is` cannot be overloaded, so no dunder could have made it correct for them (Ruling R1's table). The surface split replaces it and touches none of the fourteen. If a reviewer or a later PR proposes a lazy object here, that table is the answer.

**Type consistency.** `output_format` and `client_ip` are `str` on `AuthorizeResult`, `str` in the headers, `str` in `_resolve_output_format`'s return. `user_id` is a `str` everywhere on the relay side (`"4242"`, `"0"` as `add_client`'s fallback) and an `int` only inside `_username_for`'s `int(user_id)`. `output_profiles` keys are `str`, its `id` values are `int`, its `argv` values are `list[str]`. `_resolve_output_format` keeps its name and its first three positional parameters because `test_stream_ts_client_registration.py` patches it by name.

**The plan's one open question is closed.** It was whether Task 3 Step 2's two tests walk `views.py:605` and `:712` respectively or both walk `:712`. Resolved against the tree: `_active_proxy_server`'s defaults reach `:712`, and only `test_owner_init_resolves_output_profile_once`'s override block (`test_stream_ts_client_registration.py:317-330`) reaches `:605`. Step 2 now carries the fact and the block to copy, keeps the per-test coverage confirmation as verification rather than investigation, and adds the three hazards that discovery exposed — an arity-only owner test, an `assert_called_once()` that is secretly pinning the `output_options_resolved` flag, and 18 `_resolve_output_format` patch sites across five files that fail *silently* if a call site stops going through the `views` module global.

**Spec correction:** Task 6 Step 0 corrects spec lines 1598 and 1658, whose "when `X-Relay-Output` names a profile" decision Ruling R3 shows to be unimplementable. Line 1599 is deliberately left alone; Ruling R4's departure from it is argued in the PR description and recorded in parity-matrix row 17.
