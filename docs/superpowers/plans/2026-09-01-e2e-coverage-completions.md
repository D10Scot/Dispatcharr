# G14 — Coverage Completions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the seven accepted coverage gaps from the 2026-09-01 programme review — blocked-network ACL 403 negatives, EPG matching and the `set-*-from-epg` family, row-scoped behavioural settings, plugin `run`, channel bulk operations and reordering, M3U filters, and product WebSocket events — **without adding a Playwright project, a CI job, or an isolated instance.**

**Architecture:** One pull request, one branch. Twenty-four tests across six new spec files in the existing `seeded` project, plus one test appended to `e2e/tests/frontend/plugins.spec.ts`. Every write is row-scoped; the one global `CoreSettings` write in the goal is a single named exception whose blast radius is argued to zero. No `playwright.config.ts` change, no workflow change, no `seed.ts` change.

**Tech Stack:** TypeScript, Playwright 1.62.x, Node 24, the G1 fixture set (`api`, `seed`, `waitFor`, `ws`, `asPrincipal`, `upstream`), the G2 fake upstream provider, Docker.

**Spec:** `docs/superpowers/specs/2026-09-01-e2e-coverage-completions-design.md` — **read it before Task 0.** Every task cites the decisions it implements. Test numbers below are the spec's inventory numbers.

## Global Constraints

Copied from the spec and the programme rules. Every task's requirements implicitly include this section.

- **Never assert a global count or an unfiltered list.** Roadmap rule 4. Every assertion is scoped to a name, an id or a filtered query this test owns.
- **Never mutate a global `CoreSettings` row**, with exactly one exception: `network_access["XC_API"]` in test 3, restored in `afterEach`. **`network_access["UI"]` is never written under any circumstance** — `apps/accounts/permissions.py:Authenticated` gates every DRF endpoint on it, including the one that would undo the change, and recovery would be `manage.py reset_network_access` over `docker exec`. (Spec D2.)
- **`match-epg` is called with a *non-empty* `channel_ids` list, or in its detail form.** `ChannelViewSet.match_epg` branches on `if channel_ids:`, so an omitted **or empty** list matches every EPG-less channel on the instance. (Spec D7.)
- **No EPG-matching test may land in the ML score band.** `try_epg_name_match` calls `get_sentence_transformer()` — which downloads `sentence-transformers/all-MiniLM-L6-v2` into `/data/models` — only when the fuzzy score is in `[FUZZY_MEDIUM_CONFIDENCE, FUZZY_SKIP_ML)` or `[FUZZY_LAST_RESORT_MIN, FUZZY_MEDIUM_CONFIDENCE)`. Every score must land **at or above `FUZZY_SKIP_ML`** or **below `FUZZY_LAST_RESORT_MIN`**. Task 0 measures the real scores before any test is written. (Spec D6, D6a.)
- **Never assert on a `SystemEvent` row.** `core/utils.py:log_system_event` truncates the table to `max_system_events` (default 100) instance-wide on every call. (Spec D12c.)
- **Never wait on a bare WebSocket type.** Predicate order: a Celery `task_id`; then an id in the payload this test owns; then do not wait on it at all. `epg_matching_progress` carries no id and is throttled — never a terminal predicate. (Spec D12a.)
- **`refresh_interval: 0` on every source and account.** G3's D10 is still binding, and G14 adds nothing to the `{0, 2, 3, 4, 8531, 8532}` set documented in `e2e/README.md`.
- **Drive client-facing output surfaces with the built-in `request` fixture, not `api`.** `e2e/README.md` rule 11: `ApiClient` retries once through a token refresh on *any* 401, and `network-acl.spec.ts` asserts on 401 and 403.
- **`seeded` is `fullyParallel: true`.** A file is **not** a confinement boundary — two tests in one file run in two workers. `network-acl.spec.ts` must therefore declare `test.describe.configure({ mode: 'serial' })`.
- **Import from `'../../fixtures'`, never `'@playwright/test'` directly.** A spec destructuring only `page` typechecks clean and runs with no fixtures wired in.
- **The typecheck hook is blocking.** Any edit to `e2e/**/*.ts` runs `tsc --noEmit` for that package. Run `cd e2e && npm ci` first or it degrades to a loud note.
- **Product defects are asserted correct, marked `test.fail()` naming the defect, and filed** — `gh issue create --repo D10Scot/Dispatcharr`. **The explicit `--repo` flag is mandatory**: this checkout is a fork and `gh` without it resolves to upstream's public tracker.
- **Premise guards go outside the inverted block.** A `test.fail()` whose setup can also fail is satisfied by a broken seed as convincingly as by the defect. Assert the premise and a positive control normally *first*, then invert only the defective assertion. (The G9/G10 pattern G15 is backporting.)
- **G12, G13 and G15 are in flight on five shared files** — `e2e/COVERAGE.md`, `e2e/README.md`, `e2e/fixtures/types.ts`, `e2e/fixtures/index.ts`, `e2e/fixtures/api.ts`. Every G14 edit is **appended at the end of the existing list**; no reordering, no reflowing a neighbouring paragraph. **G14 does not open `e2e/tests/seeded/xc-output.spec.ts`, anything under `e2e/tests/lifecycle/`, `e2e/tests/frontend/dvr.spec.ts`, `e2e/fixtures/seed.ts`, `e2e/playwright.config.ts`, `e2e/package.json`, `scripts/e2e_up.sh`, or any workflow.**
- **Apply G11's tag taxonomy.** Default `@contract`; the four `@characterization` tests are 1, 7, 8, 9 and 23, each with a comment justifying itself. If G11's ADR names the tags differently, follow G11.
- **Import map — every shared symbol comes from exactly one place.**

  | Symbol | From |
  |---|---|
  | `test`, `expect`, `PRINCIPALS`, `WsListener` | `'../../fixtures'` |
  | `Channel`, `EpgSource`, `EpgData`, `M3uAccount`, `Stream`, `XcUser`, `M3uFilter`, `CoreSetting`, `NetworkAccessCheck`, `PluginRunResponse` | `'../../fixtures'` (defined in `e2e/fixtures/types.ts`) |
  | `xcQuery` | `'../../fixtures'` |
  | `listRows` | `'../../setup/http'` |
  | `buildPluginZip` | `'./plugin-zip'` — from inside `e2e/tests/frontend/` only |

---

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `e2e/tests/seeded/network-acl.spec.ts` | Tests 1–5: the header-trust premise guard, the `M3U_EPG` default 403, the global `XC_API` 403, the per-user `allowed_networks` refusal, and the 401-should-be-403 known bug |
| `e2e/tests/seeded/epg-matching.spec.ts` | Tests 6–10: exact `tvg_id`, fuzzy match, fuzzy no-match, the one-id threshold asymmetry, and `epg_match`'s associations |
| `e2e/tests/seeded/epg-field-copy.spec.ts` | Tests 11–13: `set-names-from-epg`, the silent skip of an unassociated channel, and `set-tvg-ids-from-epg` with its `task_id`-correlated WebSocket event |
| `e2e/tests/seeded/ws-product-events.spec.ts` | Tests 14–15: `epg_data_created` correlated on `source_id`, and the `ADMIN_ONLY_UPDATE_TYPES` filter |
| `e2e/tests/seeded/m3u-filters.spec.ts` | Tests 16–18: exclude, include-only, and first-match-wins by `order` |
| `e2e/tests/seeded/channel-bulk-ops.spec.ts` | Tests 19–23: `edit/bulk` apply, `edit/bulk` validate-first, `bulk-delete`, `assign`, `reorder` |

**Modified:**

| Path | Change |
|---|---|
| `e2e/fixtures/api.ts` | `delete(url, data?)` — forward the optional body to the existing private `send()` |
| `e2e/fixtures/types.ts` | Append `M3uFilter`, `M3uFilterOverrides`, `CoreSetting`, `NetworkAccessCheck`, `PluginRunResponse`, `EpgMatchAssociation`, `EpgFieldCopyResponse`; extend `User`/`UserOverrides` with `custom_properties` **only if Task 0 shows it is not already there** |
| `e2e/fixtures/index.ts` | Re-export the new types; extend the header inventory for `api.delete`'s new argument |
| `e2e/tests/frontend/plugin-zip.ts` | `buildPluginZip({ key, name, actions? })` — optional actions, written into both `plugin.json` and the generated `plugin.py`; `run` returns a value derived from `params` |
| `e2e/tests/frontend/plugins.spec.ts` | Test 24 appended: run an action, and the three negatives |
| `e2e/README.md` | A network-ACL section (the three scope defaults, the `X-Real-IP` mechanism, **`UI` is never written**); the ML-band rule; a note that `seeded` is `fullyParallel` so a file confines nothing; one fixture-table line |
| `e2e/COVERAGE.md` | Eleven new flow rows, one known-bug row, one characterized-defect row, six observation rows, four gap rows |

---

## Task 0: Preflight — three probes against a live container

**This task writes no test.** It answers three questions the spec could not answer from source, and any one of them coming back differently changes what gets built. Do it first, record the answers in the PR description, and stop and re-plan if probe A fails.

Implements spec D3a, D6a, and the `types.ts` conditional above.

**Files:**
- Create: nothing permanent. Use a scratch spec deleted at the end of the task, or `curl` and `docker exec` directly.

**Interfaces:**
- Produces: three recorded answers consumed by Tasks 2, 5 and 1 respectively.

- [ ] **Step 1: Create the branch and bring the stack up**

```bash
git fetch origin
git checkout -b test/e2e-coverage-completions-g14 origin/main
./scripts/e2e_up.sh --reset
cd e2e && npm ci && npx playwright install --with-deps chromium && npm run typecheck
```

- [ ] **Step 2: Probe A — does a client-supplied `X-Real-IP` reach the ACL?**

The whole of tests 1–3 rests on this. Two reads of `POST /api/core/settings/check/`, which
returns the IP the server thinks you are:

```bash
TOKEN=$(python3 -c "import json;print(json.load(open('e2e/playwright/.auth/tokens.json'))['access'])")
curl -s -X POST http://localhost:9191/api/core/settings/check/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"key":"network_access","value":{}}'
curl -s -X POST http://localhost:9191/api/core/settings/check/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -H 'X-Real-IP: 203.0.113.5' \
  -d '{"key":"network_access","value":{}}'
```

Expected: the first `client_ip` is a private address (`172.x` or `10.x`); the second is exactly
`203.0.113.5`. Confirm the consequence directly:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:9191/output/m3u
curl -s -o /dev/null -w '%{http_code}\n' -H 'X-Real-IP: 203.0.113.5' http://localhost:9191/output/m3u
```

Expected `200` then `403`.

**If the second `client_ip` is still private, or `/output/m3u` still answers 200:** header trust
is not in force in this topology. **Stop and re-scope**: tests 1–3 become a `COVERAGE.md` gap row
naming this probe's output, and Task 3 ships tests 4 and 5 only — the per-user
`allowed_networks` path needs no header and is where the defect lives. Do **not** work around it
by narrowing `network_access["UI"]` or by setting `DISPATCHARR_TRUSTED_PROXIES`; both change what
is under test.

- [ ] **Step 3: Probe B — measure the real fuzzy scores**

`normalize_name` strips bracketed and parenthesised text, preserves a 3–5-uppercase-letter call
sign matched against the *original* string, drops all punctuation, and removes fifteen stop-words
(`tv, channel, network, television, east, west, hd, uhd, 24/7, 1080p, 720p, 540p, 480p, film,
movie, movies`). A score predicted by eye is routinely ten points out, and being ten points out
moves a test into the ML band, whose only symptom is a slow first run.

Measure the candidate pairs directly in the container:

```bash
docker exec dispatcharr-e2e su - dispatch -c \
  'cd /app && python manage.py shell -c "
from apps.channels.epg_matching import normalize_name
from rapidfuzz import fuzz
pairs = [
    (\"<candidate channel name>\", \"<candidate EPG name>\"),
]
for a, b in pairs:
    na, nb = normalize_name(a), normalize_name(b)
    print(repr(a), repr(na), \"|\", repr(b), repr(nb), \"->\", fuzz.ratio(na, nb))
"'
```

Iterate until you have three pairs, and record them verbatim for Task 5:

| Needed for | Requirement | Threshold that applies |
|---|---|---|
| Test 7 (fuzzy match, single path) | score **≥ 75** | `FUZZY_SKIP_ML` = 75 on the single-channel path |
| Test 8 (no match, bulk path) | score **< 50** against *every* row in the catalogue | `FUZZY_LAST_RESORT_MIN` = 50 on the bulk path |
| Test 9 (threshold asymmetry) | score in **[75, 80)** | matches with one id (single thresholds), not with two (bulk `FUZZY_SKIP_ML` = 80) |

Note `region_code` is always `None` (the three-site defect), so the score is exactly
`fuzz.ratio(chan_norm, epg_norm)` with no bonus term. Names must avoid every stop-word above, or
the normalised string is not what you think it is.

- [ ] **Step 4: Probe C — is `custom_properties` writable on the user endpoint?**

Test 4 needs `PATCH /api/accounts/users/<id>/` to accept `custom_properties`. `seed.xcUser()`
already writes `xc_password` there, so it almost certainly is — confirm, and check whether the
harness's `UserOverrides` already carries the field:

```bash
grep -n "custom_properties" e2e/fixtures/types.ts e2e/fixtures/seed.ts
```

If `UserOverrides` lacks it, Task 1 adds it with an evidence note; if it has it, Task 1 adds
nothing there.

- [ ] **Step 5: Record the answers**

Write all three into the PR description under "Preflight". Probe B's three pairs are quoted
verbatim into the comments Task 5 writes, so a later edit to a name is visibly a threshold
decision and not a cosmetic rename.

### Verification

- [ ] Probe A produced `203.0.113.5` and a `403`, **or** the re-scope above has been applied and written down.
- [ ] Probe B produced three pairs with measured scores in the three required bands, recorded verbatim.
- [ ] Probe C answered whether `types.ts` needs a `custom_properties` addition.
- [ ] `cd e2e && npm run typecheck` is clean (nothing has changed yet; this establishes the baseline).

---

## Task 1: Fixture groundwork

Implements spec D15 and the `types.ts` list. Small, additive, and done first so every later task
typechecks.

**Files:**
- Modify: `e2e/fixtures/api.ts`, `e2e/fixtures/types.ts`, `e2e/fixtures/index.ts`.

**Interfaces:**
- Produces: `api.delete(url, data?)`; the seven new types; their re-exports.
- Consumed by: every later task.

- [ ] **Step 1: `api.delete` forwards a body**

In `e2e/fixtures/api.ts`, `delete()` is the only verb that does not pass `data` to the private
`send()`. Change the signature to `delete(url: string, data?: unknown)` and forward it. Add a
comment stating why: `DELETE /api/channels/channels/bulk-delete/` carries `channel_ids` in the
body (`apps/channels/api_views.py:BulkDeleteChannelsAPIView.delete`), and routing it through a
raw `request` call instead would lose `ApiClient`'s 401 refresh-and-retry. Backward compatible —
every existing caller passes one argument.

- [ ] **Step 2: Append the new types to `e2e/fixtures/types.ts`**

At the **end** of the existing list, never interleaved (G12/G13/G15 are editing this file):

| Type | Fields | Evidence note it must carry |
|---|---|---|
| `M3uFilter` | `id`, `filter_type: 'group' \| 'name' \| 'url'`, `regex_pattern`, `exclude`, `order`, `custom_properties` | `apps/m3u/serializers.py:M3UFilterSerializer.Meta.fields`; the three choices from `apps/m3u/models.py:M3UFilter.FILTER_TYPE_CHOICES` |
| `M3uFilterOverrides` | the writable subset, `id` omitted | same |
| `CoreSetting` | `id`, `key`, `name`, `value: unknown` | `core/serializers.py:CoreSettingsSerializer` is `fields = "__all__"` over a four-column model; lookup is by **`id`**, not `key`, so a caller lists first |
| `NetworkAccessCheck` | `client_ip: string` plus an index signature of `string[]` | `core/api_views.py:CoreSettingsViewSet.check` returns `{...perScopeExcludedCidrs, client_ip}` |
| `PluginRunResponse` | `success: boolean`, `result?: unknown`, `error?: string` | `apps/plugins/api_views.py:PluginRunAPIView.post`. Note in the comment that `result` is **double-wrapped** unless the plugin returns a `dict` |
| `EpgMatchAssociation` | `channel_id: number`, `epg_data_id: number` | `apps/channels/epg_matching.py:apply_matched_epg_to_channels`'s return, carried in `epg_match`'s `associations` |
| `EpgFieldCopyResponse` | `message`, `task_id: string`, `channel_count: number` | `apps/channels/api_views.py:ChannelViewSet.set_names_from_epg` and its two siblings |

If Probe C showed `UserOverrides` lacks `custom_properties`, add it here with the evidence note
`apps/accounts/serializers.py` and the fact that `seed.xcUser()` already writes `xc_password`
through it.

- [ ] **Step 3: Re-export from `e2e/fixtures/index.ts`**

Append the seven type re-exports, and extend the `api` entry in the header inventory to show
`delete(url, data?)`. Nothing else in that header changes.

### Verification

- [ ] `cd e2e && npm run typecheck` clean.
- [ ] `git diff e2e/fixtures/` shows only appended lines plus the one changed `delete` signature — no reordering, no reflowed paragraphs.
- [ ] `grep -c "custom_properties" e2e/fixtures/types.ts` matches Probe C's expectation.

---

## Task 2: `network-acl.spec.ts` — tests 1 and 2, the zero-write half

Implements spec D3, D3a. Rank 1. **This is the highest-value task in the goal; do it first.**

**Files:**
- Create: `e2e/tests/seeded/network-acl.spec.ts`.

**Interfaces:**
- Produces: the file, its `test.describe.configure({ mode: 'serial' })` and its header.
- Consumed by: Task 3, which appends tests 3–5 to the same file.

- [ ] **Step 1: The file header**

Write it before any test. It must state, in prose:

- Why the file is serial: `seeded` is `fullyParallel: true`, so a file is not a worker; test 3
  writes a global row and only serial mode confines that.
- The three scope defaults from `dispatcharr/utils.py:network_access_allowed` — `M3U_EPG` is
  `LOCAL_NETWORK_CIDRS`, everything else is `0.0.0.0/0` — and that the shipped `network_access`
  row is `{}`, so those defaults are what is in force.
- The mechanism: `get_client_ip` honours `X-Real-IP` because the peer is the Docker bridge, which
  is inside the trusted set; nginx neither sets nor strips it on the `uwsgi_pass` routes
  ([#81](https://github.com/D10Scot/Dispatcharr/issues/81)).
- **`network_access["UI"]` is never written here.** `apps/accounts/permissions.py:Authenticated`
  gates every DRF endpoint on it, including the settings write itself.
- Why every request uses the `request` fixture rather than `api` (rule 11: `ApiClient` retries
  through a token refresh on any 401, which is one of the two statuses under test).

- [ ] **Step 2: Test 1 — the premise guard** — tag `@characterization`

Two `POST /api/core/settings/check/` calls with `{"key": "network_access", "value": {}}`, through
`request` with an `Authorization: Bearer` header from `api.freshAccessToken()`. Assert:

- the plain call's `client_ip` parses as an address inside `LOCAL_NETWORK_CIDRS`;
- the spoofed call's `client_ip` is exactly `203.0.113.5`.

The failure message names `DISPATCHARR_TRUSTED_PROXIES`, [#81](https://github.com/D10Scot/Dispatcharr/issues/81)
and this test's own role as the premise for tests 2 and 3. Tagged `@characterization` because it
asserts a property of *this* container's nginx/uwsgi topology — a deployment setting
`DISPATCHARR_TRUSTED_PROXIES=none` would correctly fail it.

`203.0.113.0/24` is RFC 5737 TEST-NET-3, reserved for documentation, so it cannot collide with a
real deployment address. Use it everywhere in this file; do not invent another.

- [ ] **Step 3: Test 2 — the `M3U_EPG` default refuses a non-local client** — tag `@contract`

For each of `/output/m3u`, `/output/epg`, `/hdhr/discover.json` and `/hdhr/lineup.json`, in one
test:

- a plain `request.get(path)` → `200` (the positive control, in the same test, so a broken
  instance cannot pass by 403-ing everything);
- the same with `X-Real-IP: 203.0.113.5` → `403`, body `{"error": "Forbidden"}`.

**No settings write.** This is the product's out-of-the-box behaviour, which is what makes it the
strongest form of the assertion.

`/output/epg` may need the `?days=` cache workaround the existing `output-epg.spec.ts` documents —
check that file before assuming, and reuse whatever it does rather than inventing a second answer.

### Verification

- [ ] `cd e2e && npx playwright test --project=seeded network-acl.spec.ts` — both tests green.
- [ ] Mutation check: temporarily change `203.0.113.5` to a `10.x` address; test 2 must fail. Revert.
- [ ] `cd e2e && npm run typecheck` clean.
- [ ] No `CoreSettings` row was written: `curl -s http://localhost:9191/api/core/settings/ -H "Authorization: Bearer $TOKEN" | python3 -m json.tool | grep -A3 network_access` still shows `{}`.

---

## Task 3: `network-acl.spec.ts` — tests 3, 4 and 5, and the defect

Implements spec D2, D4, D5, D17. **Read D2's exception argument before writing test 3.**

**Files:**
- Modify: `e2e/tests/seeded/network-acl.spec.ts`.

**Interfaces:**
- Produces: an `afterEach` that restores `network_access["XC_API"]`, and one filed issue.

- [ ] **Step 1: Test 3 — the global `XC_API` 403 on `get.php` and `xmltv.php`** — tag `@contract`

The one D2 exception. Steps:

1. `GET /api/core/settings/` through `api`, find the row whose `key` is `network_access`, keep its
   `id` and its **current `value`**.
2. `PATCH /api/core/settings/<id>/` with `value` = the current value plus
   `XC_API: "127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,::1/128,fc00::/7,fe80::/10"`.
   **Do not touch any other key**, and assert in the read-back that `UI` is still absent or
   unchanged. The serializer validates CIDR syntax only (`core/serializers.py:CoreSettingsSerializer.update`)
   and will 400 on a typo — that is the only guard there is.
3. `seed.xcUser()`; `GET /get.php` and `GET /xmltv.php` with `xcQuery(user)` and no header → `200`
   (the positive control: the narrowed value denies nothing real, which is the whole D2 argument
   made executable).
4. The same two with `X-Real-IP: 203.0.113.5` → `403`, body `{"error": "Forbidden"}`.

Restore in **`afterEach`**, not a body-level `finally`: Playwright tears a test down mid-`await`
on timeout and code after that point does not reliably run — the reasoning `plugins.spec.ts` and
`settings.spec.ts` already record. The `afterEach` writes back the value captured in step 1, and
follows the established non-masking shape: if the test already failed, log a cleanup failure
rather than replacing the reported cause.

The comment above the test must carry D2's blast-radius argument in full: narrowing `XC_API` to
the local CIDRs denies only requests carrying a spoofed non-local `X-Real-IP`, nothing else in the
suite sends one, and therefore even a leaked value costs the container nothing. A reader who does
not find that argument convincing should be able to delete this one test and lose nothing else.

- [ ] **Step 2: Test 4 — the per-user refusal** — tag `@contract`

**No header, no global write.** `seed.xcUser()`, then
`PATCH /api/accounts/users/<id>/` with
`{"custom_properties": {...existing, "allowed_networks": {"XC_API": "203.0.113.0/24"}}}` — read the
existing `custom_properties` first and merge, because `xc_password` lives there and overwriting it
breaks the credentials the test is about to use.

Assert a **positive control before the write** — `player_api.php` with valid credentials → `200` —
then after the write assert all three of `player_api.php`, `get.php` and `xmltv.php` **refuse**.
Assert refusal (`status !== 200` and the body is not a `user_info` envelope), not a specific
status, so this test stays green whichever way the defect in test 5 is resolved.

`network_access_allowed`'s per-user branch is authoritative when non-empty: the user must match
one of *those* CIDRs, and `203.0.113.0/24` cannot contain any real client. Zero logins are spent —
the XC surface authenticates from credentials in the URL, so no token is ever minted for this user.

- [ ] **Step 3: Test 5 — the known bug** — `test.fail()`, tag `@contract`

Same setup as test 4. The premise and the positive control are asserted **outside** the inverted
block; only the final assertion is inverted:

```
expect(res.status()).toBe(403);   // correct behaviour; today it is 401
```

The comment names the mechanism precisely: `apps/output/views.py:xc_get_user` applies
`network_access_allowed(request, 'XC_API', user)` and returns `None` on denial, and every caller
maps `None` to `401 {"error": "Unauthorized"}` — so a network-blocked client is told its password
is wrong. `get.php`/`xmltv.php` do have a real 403, but only from the global check that passes no
`user`, so the per-user branch can never produce one anywhere.

- [ ] **Step 4: File the issue**

```bash
gh issue create --repo D10Scot/Dispatcharr \
  --title "XC API returns 401 for a network-blocked user, not 403, and logs no event on player_api.php" \
  --label needs-triage \
  --body-file <path>
```

The body must contain:

- the mechanism above, cited as `apps/output/views.py:xc_get_user`, `:xc_get_info`,
  `:xc_player_api`, `:xc_get`, `:xc_xmltv`;
- the four-endpoint table: global block → 403 on `get.php`/`xmltv.php`, 401 on
  `player_api.php`/`panel_api.php`; per-user block → **401 everywhere**;
- that `player_api.php`/`panel_api.php` emit no `SystemEvent`, so the denial is invisible in the
  events log as well as mislabelled in the response;
- the three-way contract disagreement: `apps/proxy/live_proxy/views.py:stream_xc` does it
  correctly (403 then 401), and `apps/timeshift/views.py:_timeshift_proxy_impl` returns a
  plain-text 403 for both and checks credentials before the ACL;
- that this is **not** [#84](https://github.com/D10Scot/Dispatcharr/issues/84) (the
  unknown-username 404 oracle), which is a different branch of the same function;
- a note that it is pinned by `e2e/tests/seeded/network-acl.spec.ts`'s `test.fail()`.

Record the issue number; Task 12 cites it in `COVERAGE.md` and the test comment references it.

### Verification

- [ ] All five tests in the file green (test 5 as an expected `test.fail()`).
- [ ] Run the file twice back to back. The second run must pass — proving the `afterEach` restore worked.
- [ ] After the run, `network_access` contains no `XC_API` key (or its original value), and **no `UI` key**.
- [ ] Mutation check on test 5's premise guard: break the seed (use a wrong `xc_password`) and confirm the test reports the *premise* failing, not a satisfied inversion.
- [ ] `npx playwright test --project=seeded` — the whole project still green, proving test 3's window disturbed nothing.

---

## Task 4: `epg-matching.spec.ts` — test 6, the exact-`tvg_id` path

Implements spec D7a. The safest shape in the file: an ID-matched channel never reaches
`try_epg_name_match`, so no score and no ML band is involved at all.

**Files:**
- Create: `e2e/tests/seeded/epg-matching.spec.ts`.

**Interfaces:**
- Produces: the file and its header.
- Consumed by: Tasks 5 and 6.

- [ ] **Step 1: The file header**

It must state:

- **The ML band rule** (D6) with the six threshold numbers from
  `apps/channels/epg_matching.py:_get_epg_match_thresholds`, both branches, and the rule that
  every score in this file lands at or above `FUZZY_SKIP_ML` or below `FUZZY_LAST_RESORT_MIN`.
  Name `get_sentence_transformer()` and the model it downloads, so the cost of getting this wrong
  is on the page.
- **The cross-worker aliasing hazard**: `_active_epg_fuzzy_queryset` filters on
  `epg_source__is_active=True` and nothing else, so every `EPGData` row of every active source on
  the instance is a candidate — including G3's `epg-ingest.spec.ts` fixtures in the same project.
  The mitigation is entropy plus asserting *my* `epg_data_id`, and it is a mitigation rather than
  a proof.
- **D7**: `match-epg` is never called with an omitted or empty `channel_ids`.
- Probe B's measured pairs, verbatim, with their scores.

- [ ] **Step 2: Test 6** — tag `@contract`

1. `upstream.scenario()` with two channels carrying generated names and generated `tvg_id`s.
2. `seed.upstreamEpgSource(scenario)` — G3's factory, which creates the source and waits through
   `waitFor.epgRefreshComplete`. `refresh_interval: 0`.
3. Find both `EPGData` rows by `tvg_id` in `GET /api/epg/epgdata/` (unpaginated and unfiltered —
   locate with `find`, never a length or an index; G3's `epg-ingest.spec.ts` is the precedent).
4. `seed.channel({ tvg_id: <one scenario tvg_id> })` with a **deliberately unrelated** name, so
   only the ID path can succeed.
5. Register `ws.waitForMessage('single_channel_epg_match', { where: (d) => d.channel_id === channel.id })`
   **before** the POST — the id exists already, and the listener queues anything that arrives
   early.
6. `POST /api/channels/channels/<id>/match-epg/` → `202 { accepted: true, channel_id }`.
7. Await the message: `matched === true`, `epg_id` equals *my* `EPGData` row's id.
8. Read the channel back and assert `epg_data` is that id.

The comment records that this test proves the short-circuit **and** that name distance is
irrelevant to it — which is exactly why it cannot touch the ML branch.

### Verification

- [ ] Test green.
- [ ] `docker logs dispatcharr-e2e --since 5m | grep -i "sentence transformer"` returns nothing.
- [ ] `docker exec dispatcharr-e2e ls /data/models` is empty or absent.
- [ ] Mutation check: change the channel's `tvg_id` to a value no `EPGData` row carries; the test must fail (it would then fall through to the fuzzy path with an unrelated name and not match).

---

## Task 5: `epg-matching.spec.ts` — tests 7 and 8, the fuzzy paths

Implements spec D6, D6a, D7a. **Uses Probe B's measured pairs. Do not invent names here.**

**Files:**
- Modify: `e2e/tests/seeded/epg-matching.spec.ts`.

- [ ] **Step 1: Test 7 — a near-identical name matches, ML never reached** — tag `@characterization`

`test.setTimeout(120_000)`. A channel with **no** `tvg_id` and no `tvc_guide_stationid`, named
from Probe B's ≥ 75 pair. Drive the **detail** endpoint so `is_bulk_matching` is `False` and
`FUZZY_SKIP_ML` is 75; correlate on `single_channel_epg_match`'s `channel_id`; assert
`matched === true` and `epg_id` is my row.

The comment quotes: the raw pair, both normalised strings, the measured `fuzz.ratio`, the
threshold that applies and why it is above it. Tagged `@characterization` because it pins two of
the six hardcoded numbers.

- [ ] **Step 2: Test 8 — a distant name matches nothing, ML never reached** — tag `@characterization`

Use the **bulk** form with two channels, so `FUZZY_LAST_RESORT_MIN` is 50 rather than the single
path's 20 — a 30-point safety margin against a foreign `EPGData` row scoring higher than intended.
That margin is the point: `fuzz.ratio` is character-level and two unrelated strings routinely
score in the twenties, so a 20-point floor is not a safe one.

1. Two channels, both from Probe B's `< 50` pair family, both with no `tvg_id`.
2. `POST /api/channels/channels/match-epg/ {channel_ids: [a, b]}` → `202`.
3. `ws.waitForMessage('epg_match', { where: (d) => Array.isArray(d.associations) })` — but note
   this type is produced by any worker's bulk run, so **assert on the channel rows, not the
   message**: poll both channels and assert `epg_data` is still `null` after the task has had time
   to settle. Use the message only as the "the task finished" signal, correlated as best it can be,
   and say in a comment that a negative cannot be correlated exactly and why.
4. Assert neither channel id appears in any `associations` array seen in the window.

The comment names this as the test most exposed to cross-worker aliasing, with the mitigation and
its limits.

### Verification

- [ ] Both tests green.
- [ ] **The ML check is mandatory and is this task's real verification:** `docker logs dispatcharr-e2e --since 10m | grep -iE "sentence transformer|Loading sentence|huggingface"` returns nothing, and `/data/models` is still empty.
- [ ] `docker exec dispatcharr-e2e du -sh /data 2>/dev/null` shows no ~90 MB jump.
- [ ] Mutation check on test 7: change the channel name to Probe B's `< 50` string; the test must fail.
- [ ] Run the whole `seeded` project once and re-check `/data/models` — a concurrent G3 EPG fixture must not have pushed a score into the band either.

---

## Task 6: `epg-matching.spec.ts` — tests 9 and 10

Implements spec D6, D12a. Test 9 is fifth on the cut list; ship it only if Tasks 2–5 are green.

**Files:**
- Modify: `e2e/tests/seeded/epg-matching.spec.ts`.

- [ ] **Step 1: Test 9 — a one-id collection call runs the single-channel thresholds** — tag `@characterization`

`is_bulk_matching = len(channels_data) > 1`, so one id takes the aggressive branch. Using Probe B's
`[75, 80)` pair:

- `POST channels/match-epg/ {channel_ids: [a]}` → the channel matches (75 ≤ score, single
  `FUZZY_SKIP_ML`);
- a second channel with the same name, `POST channels/match-epg/ {channel_ids: [b, c]}` → `b`
  does **not** match (score < 80, bulk `FUZZY_SKIP_ML`), where `c` is a filler channel whose only
  job is to make the list length 2.

Both waits correlate on `epg_match`'s `associations` containing the relevant id. Assert on the
channel rows as well, for the same reason test 8 does.

The comment states plainly that this pins implementation, not contract, and that if G11's ADR
treats `@characterization` as something to minimise, this is the test to drop.

- [ ] **Step 2: Test 10 — `epg_match` names this test's associations, and counts changes only** — tag `@contract`

Two channels matched by exact `tvg_id` (so no score is involved), in one collection call.

- Register the wait before the POST, correlated as
  `(d) => d.associations?.some((a) => a.channel_id === channelA.id)`.
- Assert the matching association's `epg_data_id` is one of my `EPGData` rows.
- **Re-run the same call** and assert the second `epg_match` reports `matches_count: 0` and an
  `associations` array containing neither id — `apply_matched_epg_to_channels` returns changed
  rows only, so a confirming re-run legitimately reports nothing. That second half is what makes
  `matches_count` an assertable contract rather than a number that happens to be right once.

### Verification

- [ ] Both tests green; `/data/models` still empty.
- [ ] Mutation check on test 10: assert `matches_count === 2` on the *second* run; it must fail.
- [ ] Run `epg-matching.spec.ts` twice back to back — no state carries between runs (each test seeds its own scenario and channels).

---

## Task 7: `epg-field-copy.spec.ts` — tests 11, 12 and 13

Implements spec D12a. The `task_id` correlation here is the cleanest predicate in the goal; the
file exists separately from `epg-matching.spec.ts` because these three endpoints run **no**
matching — they copy from an association something else made.

**Files:**
- Create: `e2e/tests/seeded/epg-field-copy.spec.ts`.

- [ ] **Step 1: The file header**

State that `set_channels_names_from_epg` and its two siblings import nothing from
`epg_matching.py` — they read `channel.epg_data` and copy — so the precondition is an association
made by `set-epg` (G3's deterministic path, reused here rather than re-proved) or by `match-epg`.
State that a channel with `epg_data: None` is **silently skipped**, counting toward neither
`updated_count` nor `error_count`, which is what test 12 exists to make visible.

- [ ] **Step 2: Test 11 — `set-names-from-epg` copies the name** — tag `@contract`

Scenario + `seed.upstreamEpgSource` + channel + `POST channels/<id>/set-epg/ {epg_data_id}`, then
`POST channels/set-names-from-epg/ {channel_ids: [id]}` → `200 {task_id, channel_count: 1}`. Poll
the channel until `name` equals the `EPGData` name. Then **re-run** and assert the name is
unchanged and the terminal event's `updated_count` is `0` — `set_channels_names_from_epg` appends
to its batch only when the two differ.

- [ ] **Step 3: Test 12 — an unassociated channel is silently skipped** — tag `@contract`

Two channels in one call: one associated, one with `epg_data: null`. Assert the terminal
`epg_name_setting_progress` payload reports `updated_count: 1` and `error_count: 0` — the skipped
channel appears in neither total, which is exactly what makes the ordering dependency invisible in
the response and is why this assertion is worth writing. Assert the unassociated channel's `name`
is unchanged.

Correlate the wait on `task_id`, since the POST returns it before the task runs.

- [ ] **Step 4: Test 13 — `set-tvg-ids-from-epg`, correlated on `task_id`** — tag `@contract`

Seed the channel with a **deliberately wrong** `tvg_id` so the write is observable rather than a
coincidence. Register
`ws.waitForMessage('epg_tvg_id_setting_progress', { where: (d) => d.task_id === body.task_id })`
immediately after reading `task_id` from the POST response and before any further `await`. Assert
the terminal payload's `status === 'completed'` and `updated_count === 1`, and the channel's
`tvg_id` read back from the API.

Key on `status`, **never** on the presence of `updated_count`: the failure payload carries
`status: "failed"`, `progress: 0` and no counts at all.

The comment states why this is the strongest correlation available anywhere in this product — a
globally unique Celery id, returned synchronously, known before the wait registers, which is
exactly the ordering `WsListener.waitForMessage` requires.

### Verification

- [ ] All three tests green.
- [ ] Mutation check on test 13: change the `where` predicate to a bare type match and run the file alongside a second `seeded` worker doing the same; confirm the correlated version is the one that is reliable. (If reproducing the race is impractical, record that and rely on the reasoning.)
- [ ] `/data/models` still empty — none of these three touches the matcher.

---

## Task 8: `ws-product-events.spec.ts` — tests 14 and 15

Implements spec D12, D12b. Test 15 is the only coverage `ADMIN_ONLY_UPDATE_TYPES` has ever had.

**Files:**
- Create: `e2e/tests/seeded/ws-product-events.spec.ts`.

- [ ] **Step 1: The file header**

State the correction that makes this file worth existing: `core/utils.py:log_system_event` sends
**no** WebSocket message, so `apps/connect/models.py:SUPPORTED_EVENTS` is the Connect and
plugin-hook vocabulary, `core/models.py:SystemEvent.EVENT_TYPES` is the DB vocabulary, and the
socket's vocabulary is the set of `data.type` literals at `send_websocket_update()` call sites.
The three overlap only by coincidence of naming. State that `SystemEvent` is never asserted
(truncated instance-wide on every call) and that `ws-fixture.spec.ts` pins the *fixture*, while
this file pins the *product*.

- [ ] **Step 2: Test 14 — `epg_data_created`** — tag `@contract`

`POST /api/epg/sources/` with `{source_type: 'dummy', refresh_interval: 0, is_active: true}` and a
generated name. The `post_save` receiver is **synchronous** and dummy sources are excluded from
refresh scheduling, so no Celery task is dispatched at all — the cheapest correlated product event
in the application.

The correlating id does not exist until the POST returns, so register the wait *after* the
response and rely on the listener's queue (it holds a message that arrives before a matching
waiter; messages are consumed, not replayed). Say so in a comment.
`where: (d) => d.source_id === source.id`; assert `epg_data_id` is present and `source_name`
matches. Delete the source in `afterEach`.

- [ ] **Step 3: Test 15 — the admin-only filter** — tag `@contract`

Two sockets, one window:

1. The `ws` fixture (bootstrap admin).
2. `const streamer = await asPrincipal('streamer')` → `new WsListener(baseURL, await streamer.freshAccessToken())`,
   then `await listener.ready()`. `WsListener` is already exported from `e2e/fixtures/index.ts`, so
   no fixture change is needed. Close it in a `finally`.

Collect for a window comfortably longer than the beat interval (`channel_stats` arrives roughly
once a second from `apps/proxy/tasks.py:fetch_channel_stats`). Then assert:

- **the premise guard, first**: the admin socket received **at least one** `channel_stats`. If it
  did not, fail saying "no `channel_stats` traffic in the window" — an idle instance must not
  produce a vacuous pass;
- the Streamer socket received **zero**.

The comment records that `ADMIN_ONLY_UPDATE_TYPES` is a **silent drop**, not an error frame, that
admin means `user_level >= 10`, and that `asPrincipal` principals are shared and read-only so
nothing here changes one.

Reading "everything the socket saw" is not something `waitForMessage` does — it consumes. Drive
the negative with a short `waitForMessage('channel_stats', { timeoutMs })` on the Streamer socket
that is **expected to reject with a timeout**, and the positive with the same call on the admin
socket expected to resolve. State in a comment that this is why the assertion is shaped as two
waits rather than two counts.

### Verification

- [ ] Both tests green.
- [ ] Test 15's premise guard demonstrably works: stop the beat process (`docker exec dispatcharr-e2e supervisorctl stop celerybeat` or equivalent), re-run, and confirm the test fails naming the missing traffic rather than passing. **Restart it afterwards** and re-run to green.
- [ ] Mutation check on test 15: swap the Streamer token for the admin token; the test must fail.
- [ ] No `WsListener` leaks — the run exits promptly rather than hanging on an open socket.

---

## Task 9: `m3u-filters.spec.ts` — tests 16, 17 and 18

Implements rank 4. Row-scoped: filters belong to one `M3UAccount`.

**Files:**
- Create: `e2e/tests/seeded/m3u-filters.spec.ts`.

- [ ] **Step 1: The file header**

State that `_stream_passes_m3u_filters` walks filters in `order` and returns `not filter_obj.exclude`
on the **first** match, and that a stream matching nothing passes — so `exclude: false` is
first-match-wins, not a whitelist. State that `_compile_m3u_stream_filters` sets `re.IGNORECASE`
only when `custom_properties["case_sensitive"] is False`, so the flag's *absence* means
case-sensitive. Note that filters are applied on both the standard and XC ingest paths (both
`executor.submit(process_m3u_batch_direct, …)` sites in
`apps/m3u/tasks.py:_refresh_single_m3u_account_impl`) and that this file exercises the standard
path only.

Also state the ordering constraint that shapes every test here: `perform_create` takes the account
id from the URL, so the filter can only be created after the account exists — and the account must
be created **inactive**, filtered, then activated and refreshed, or the first refresh runs
unfiltered.

- [ ] **Step 2: Test 16 — `exclude: true` keeps a stream out** — tag `@contract`

`test.setTimeout(120_000)`. Three-channel scenario with generated names. Create the `M3UAccount`
**inactive** pointing at the scenario (do not use `seed.upstreamM3UAccount`, which activates and
refreshes for you). `POST /api/m3u/accounts/<id>/filters/` with
`{filter_type: 'name', regex_pattern: <one generated channel name>, exclude: true, order: 0}` →
`201`. Then `PATCH` the account to `is_active: true`, trigger the refresh and wait through
`waitFor.m3uRefreshComplete`. Assert `GET /api/channels/streams/?m3u_account=<id>` returns the
other two and not that one — a *scoped* count, legitimate under G3's D13.

Escape the generated name for regex use, or assert that `seed.generatedName` produces only
regex-safe characters and say so in a comment.

- [ ] **Step 3: Test 17 — `exclude: false` is first-match-wins, not a whitelist** — tag `@contract`

Same shape with `exclude: false` on a pattern matching exactly one channel. Assert **both** halves:
the named stream is present (its first match returned `not exclude` → `True`), **and** the two
unmatched streams are also present (they matched nothing and fell through to the default `True`).
Asserting only the first half would pass on a whitelist implementation, which is the distinction
this test exists to pin.

- [ ] **Step 4: Test 18 — `order` decides when two filters match** — tag `@contract`

Two filters over the same name: `order: 0` with `exclude: false`, `order: 1` with `exclude: true`.
The stream must survive, because the loop returns on the first match. **First on this file's cut
list.**

### Verification

- [ ] All three green.
- [ ] Mutation check on test 18: swap the two `order` values; the stream must then be excluded and the test fail.
- [ ] Each test's account is scoped: `?m3u_account=<id>` is used everywhere, never a bare streams list.
- [ ] `git grep -n "refresh_interval" e2e/tests/seeded/m3u-filters.spec.ts` — every account is `0`.

---

## Task 10: `channel-bulk-ops.spec.ts` — tests 19 to 23

Implements spec D9, D15, D18.

**Files:**
- Create: `e2e/tests/seeded/channel-bulk-ops.spec.ts`.

- [ ] **Step 1: The file header and the worker band**

Derive a four-figure `channel_number` band from the Playwright worker index plus a per-test offset,
exactly as G3's D3 does — a band well clear of the numbers `seed.channel()` and `from-stream`
assign from 1 upward. Every channel this file creates is inside its own band, and every assertion
is on the test's own ids.

State **D9** in the header, in full: `ChannelViewSet.reorder` shifts every `Channel` on the
instance whose number falls between the old and desired positions, with no account, group or
profile filter — and `insert_after_id: null` sets the desired position to 1, making the shift range
`[1, old_number)`, which on this instance is every channel any test has ever created. **`null` is
never sent.**

State **D18**: [#72](https://github.com/D10Scot/Dispatcharr/issues/72) is deliberately not
reproduced. This file creates channels and profiles but never concurrently, because provoking that
race leaves a partially-populated membership set on a shared instance and a reproduction that
fails to fire is a green test proving nothing.

- [ ] **Step 2: Test 19 — `edit/bulk` applies every valid row** — tag `@contract`

Three seeded channels in the band. One `PATCH /api/channels/channels/edit/bulk/` with a **bare
list** of `{id, ...}` objects (not an envelope), changing `user_level` and `channel_number`. Read
each back by id.

- [ ] **Step 3: Test 20 — `edit/bulk` validates before it applies** — tag `@contract`

The same list plus one entry with no `id` → `400` with an `errors` list, and **none** of the valid
rows changed. Validate-then-apply is the only thing distinguishing this endpoint from three
PATCHes, so it is the assertion that matters.

- [ ] **Step 4: Test 21 — `bulk-delete` removes exactly the ids in its body** — tag `@contract`

Four channels; `api.delete('/api/channels/channels/bulk-delete/', { channel_ids: [three ids] })`
(Task 1's new signature) → `204`. Assert the three are gone by id (a `GET` on each returns 404) and
the fourth is untouched. Do **not** pass `stop_stream` — no stream is running and the flag would
reach into the proxy for no reason.

Note in a comment that the view returns `Response({"message": …}, status=204)`, a 204 with a body,
so the body must not be asserted.

- [ ] **Step 5: Test 22 — `assign` renumbers exactly the ids it was given** — tag `@contract`

`POST /api/channels/channels/assign/ {channel_ids, starting_number}` inside the band. Assert
consecutive numbers in list order, and that a fourth seeded channel deliberately left out of the
list is untouched. `assign` performs no collision check, which is why the band matters.

- [ ] **Step 6: Test 23 — `reorder` moves one channel and shifts only the ones between** — tag `@characterization`

Three channels at *n*, *n*+1, *n*+2, all this test's own. `POST /api/channels/channels/<third>/reorder/`
with `{insert_after_id: <first>}`: desired is *n*+1, old is *n*+2, so the shift range is
`[n+1, n+2)` — which contains only the second channel. Assert all three resulting numbers.

Every row the endpoint touches is one this test created, which is what makes the global shift both
observable and safe. **Second on the overall cut list.**

### Verification

- [ ] All five green.
- [ ] `git grep -n "insert_after_id" e2e/tests/seeded/channel-bulk-ops.spec.ts` — never `null`.
- [ ] After a full `seeded` run, spot-check that no channel outside the band changed number: record `GET /api/channels/channels/?name=<another spec's prefix>` numbers before and after.
- [ ] Mutation check on test 20: remove the invalid entry; the test must fail (it would then get a 200).
- [ ] Mutation check on test 22: include the fourth channel in `channel_ids`; the "untouched" assertion must fail.

---

## Task 11: Plugin run — `plugin-zip.ts` and test 24

Implements spec D14, D14a. **This is the one task outside `tests/seeded/`.** It appends to
`e2e/tests/frontend/plugins.spec.ts` rather than creating a file, because G6's one-spec-file-per-surface
rule is what confines the plugin directory and its shared `.reload_token` to a single worker in the
`frontend` project — and `seeded` (`fullyParallel: true`) would confine nothing at all.

**Files:**
- Modify: `e2e/tests/frontend/plugin-zip.ts`, `e2e/tests/frontend/plugins.spec.ts`.

- [ ] **Step 1: `buildPluginZip` gains an optional `actions`**

Signature becomes `buildPluginZip({ key, name, actions? })`, defaulting to `[]` so G6's existing
test produces a **byte-identical** archive. When `actions` is given, write it into `plugin.json`'s
`actions` array *and* the generated `plugin.py`'s `actions` list, and make `run` return a dict
derived from `params` — e.g. `{"echoed": params.get("token")}` for an `echo` action, and
`{"status": "noop"}` otherwise.

Extend the module doc comment: the plugin remains **inert at import** — only `run()` does anything,
and only when a test calls it — and `run_action` passes a `dict` return through verbatim while
wrapping a non-dict, so returning a dict keeps the response one level shallower and the assertion
readable.

- [ ] **Step 2: Test 24 — run an action, and three negatives** — tag `@contract`

Append to `plugins.spec.ts`, reusing the file's existing import-and-enable flow and its `afterEach`
delete. Build the zip with `actions: [{ id: 'echo', label: 'Echo' }]`.

1. Positive: `POST /api/plugins/plugins/<key>/run/ {action: 'echo', params: {token: <generated>}}`
   → `200 { success: true, result: { echoed: <token> } }`. The generated token is what proves the
   parameters reached the plugin, not just that something ran.
2. `POST .../run/ {}` (no `action`) → `400`.
3. `POST /api/plugins/plugins/<a-generated-key-never-imported>/run/ {action: 'echo'}` → `404`.
   **The key must have no `PluginConfig` row at all**: a row whose module will not load raises
   `ValueError` inside `run_action` and the view catches it as a generic exception → `500`, not
   `404`. Say so in the comment.
4. `POST .../enabled/ {enabled: false}`, then `POST .../run/ {action: 'echo'}` → `403`
   `{"success": false, "error": "Plugin is disabled"}`. Re-enable, or leave disabled — the
   `afterEach` deletes it either way.

Also note in a comment, without asserting it, that `GET /api/plugins/plugins/` returns the **raw**
`PluginConfig.settings` while `run()` sees the dict merged with each field's declared default
(`PluginManager._merge_settings_with_defaults`), so a default read back from the list endpoint is
not the value the plugin used.

- [ ] **Step 3: The "task-fires" decision, recorded either way**

D14a's dispatch test is **third on the cut list**. Whether or not it ships, the file (and Task 12's
`COVERAGE.md` row) must record the asymmetry, because it is the interesting finding: a runtime-imported
plugin **can** `.delay()` an existing product task — `.delay()` only publishes a message naming a
task the Celery worker already registered through `autodiscover_tasks()` — but it **cannot** define
a new `@shared_task` an already-running worker will honour, because plugins live outside
`INSTALLED_APPS` and the only import hook is `@worker_process_init` in
`dispatcharr/celery.py:init_worker_process`, which runs once per forked child at start. A newly
forked `--autoscale` child *does* pick it up, so the failure is nondeterministic rather than clean.

If the dispatch test ships: the plugin's `run` imports `refresh_single_m3u_account` and `.delay()`s
it against **the test's own** `M3UAccount` id passed in `params`, and the assertion is that
account's own `status`/`updated_at` moving. Nothing global, nothing another worker can see.

### Verification

- [ ] `cd e2e && npx playwright test --project=frontend plugins.spec.ts` — all tests in the file green, including G6's existing two.
- [ ] G6's archive is unchanged: with `actions` omitted, `buildPluginZip` output is byte-identical to before. Assert this in the file's existing zip-builder unit test, or check it once by hand and record the check.
- [ ] `GET /api/plugins/plugins/` after the run contains no leftover key from this file.
- [ ] `docker exec dispatcharr-e2e ls /data/plugins` shows no leftover directory.

---

## Task 12: File the region-code issue; `COVERAGE.md` and `README.md`

Implements spec D8, D10, D11, D16, D17, and roadmap rule 3.

**Files:**
- Modify: `e2e/COVERAGE.md`, `e2e/README.md`.

- [ ] **Step 1: File the `get_preferred_region_code()` issue**

```bash
gh issue create --repo D10Scot/Dispatcharr \
  --title "EPG regional weighting is permanently inert: preferred-region is read at three dead sites" \
  --label needs-triage --body-file <path>
```

The body must contain:

- `apps/channels/epg_matching.py:get_preferred_region_code` reads
  `CoreSettings.objects.get(key="preferred-region")`, a row
  `core/migrations/0020_change_coresettings_value_to_jsonfield.py` deletes with
  `CoreSettings.objects.exclude(key__in=grouped_keys).delete()`;
- **three sites, not one** — `apps/channels/tasks.py:match_epg_channels` and
  `:match_selected_channels_epg` each inline their own copy, so fixing the named helper fixes
  nothing;
- `core/models.py:CoreSettings.get_preferred_region` reads
  `system_settings["preferred_region"]` correctly and no matcher calls it;
- `CoreSettings.value` is a `JSONField`, so even if the row survived, `.strip()` would raise
  `AttributeError`, which `except CoreSettings.DoesNotExist` does not catch;
- the user-facing consequence: the setting is exposed in the UI
  (`frontend/src/utils/forms/settings/SystemSettingsFormUtils.js`, System Settings) and persists
  correctly, so an operator sets a region, watches it save, and gets no behavioural change;
- the effect that is lost: `_compute_fuzzy_score`'s ±15 / +10 region bonus;
- **why no test pins it**, verbatim from D8 — the correct behaviour is only observable for a pair
  whose outcome the ±15 decides, which is inside the ML band D6 forbids, and setting a region at
  all needs a global `system_settings` write this goal forbids.

Note that `CLAUDE.md` already records the one-site version; this issue supersedes that entry's
scope. **Do not edit `CLAUDE.md`** — that is a maintainer's call, not a test PR's.

- [ ] **Step 2: `COVERAGE.md` — eleven flow rows**

Appended, in the file's existing table, one per test group, each naming the spec file that covers
it. Do **not** rewrite G5's `get.php`/`xmltv.php` row or G6's Settings/Plugins rows (D16) —
cross-reference them instead.

- [ ] **Step 3: `COVERAGE.md` — the annotation rows**

One `known-bug` row (Task 3's XC 401/403 defect, with its issue number). One characterized-defect
row (Task 12 Step 1's region code, with its issue number and D8's two reasons). Six observations:
`reorder`'s instance-wide shift; the unguarded `network_access` global loop (a list- or
empty-string-valued scope is a 500 on every gated request, deliberately not provoked); the
plugin web/Celery discovery asymmetry; `match-epg`'s empty-list foot-gun; the four dead WebSocket
handler/sender pairs (`epg_file`, `epg_channels`, `epg_sources_changed` have no sender;
`epg_tvg_id_setting_progress` has no handler); and that
`apps/channels/tests/test_epg_matching.py` does not test `epg_matching.py`. One "not reproduced"
row for [#72](https://github.com/D10Scot/Dispatcharr/issues/72), cross-referencing
[#86](https://github.com/D10Scot/Dispatcharr/issues/86).

Four gap rows, each naming the mechanism so the next owner starts from the observable:

- **→ G12**: every global `CoreSettings` group with behavioural effect —
  `epg_settings.epg_match_mode` advanced normalisation, `stream_settings.default_user_agent`,
  `system_settings.preferred_region`, the `network_access` scopes beyond G14's one exception —
  with the reason (instance-wide state four workers share) and the precedent (`proxy_settings` and
  `default_stream_profile` are already exercised from single-worker projects).
- `M3UAccountProfile.search_pattern`/`replace_pattern`, naming
  `apps/proxy/live_proxy/url_utils.py:transform_url` and the provider's `ScenarioLog` as the
  observable.
- `ServerGroup` credential pooling, naming
  `apps/m3u/connection_pool.py:group_has_capacity_for_profile` and the two-account, two-stream
  setup it needs, cross-referencing [#68](https://github.com/D10Scot/Dispatcharr/issues/68).
- The provider's `ScenarioLog` records `method`, `path` and `status` but **no request headers**
  (`e2e-upstream/src/server.ts:logRequest`), so nothing Dispatcharr sends upstream as a
  `User-Agent` is observable; closing it is one field on the log entry, and `e2e-upstream`'s scope.

- [ ] **Step 4: `e2e/README.md`**

Three additions, appended, nothing reflowed:

- A **Network access** section: the four scopes (`M3U_EPG`, `STREAMS`, `XC_API`, `UI` — no backend
  constant enumerates them; the canonical list is `frontend/src/constants.js:NETWORK_ACCESS_OPTIONS`),
  their defaults, the `X-Real-IP` mechanism and its premise guard, and the standing rule in bold:
  **never write `network_access["UI"]`**, with the reason and the out-of-band recovery.
- The **ML band rule**: the six thresholds, and that an EPG-matching test whose score lands in the
  middle downloads a ~90 MB model at test time.
- One line under "Writing a test": **`seeded` is `fullyParallel`, so a spec file is not a
  confinement boundary** — a hazard confined to one file in `frontend` needs
  `test.describe.configure({ mode: 'serial' })` here.
- One fixture-table line for `api.delete(url, data?)`.

### Verification

- [ ] Both issues exist on **`D10Scot/Dispatcharr`**: `gh issue list --repo D10Scot/Dispatcharr --limit 5` shows them.
- [ ] `git diff e2e/COVERAGE.md e2e/README.md` shows appended rows and sections only — no G5, G6 or G7 row rewritten, no paragraph reflowed.
- [ ] Every gap row names a symbol, not a description.
- [ ] The row count matches: eleven flow rows plus one known-bug, one characterized-defect, six observations, one not-reproduced and four gaps.

---

## Task 13: Full verification and the pull request

- [ ] **Step 1: Clean run from a reset container**

```bash
./scripts/e2e_up.sh --reset
cd e2e
npm run typecheck
npx playwright test --project=seeded
npx playwright test --project=frontend
```

Both green. Run `--project=seeded` a **second** time immediately: a leaked `network_access`
value, a leftover plugin, a leftover EPG source or a renumbered channel outside the band would
show up here and nowhere else.

- [ ] **Step 2: The ML check, one more time**

```bash
docker exec dispatcharr-e2e ls -la /data/models 2>&1
docker logs dispatcharr-e2e 2>&1 | grep -icE "sentence transformer|huggingface"
```

Empty and `0`. If either is non-zero, a test is in the ML band — find it with the container log's
`Validating fuzzy best match with ML model` line, and re-derive that test's name pair against
Probe B before doing anything else.

- [ ] **Step 3: Confirm nothing global was left behind**

```bash
TOKEN=$(python3 -c "import json;print(json.load(open('playwright/.auth/tokens.json'))['access'])")
curl -s http://localhost:9191/api/core/settings/ -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import json,sys;print([r for r in json.load(sys.stdin) if r['key']=='network_access'])"
curl -s http://localhost:9191/api/plugins/plugins/ -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import json,sys;print([p['key'] for p in json.load(sys.stdin)['plugins']])"
```

`network_access` back to its original value with **no `UI` key**; no G14 plugin key present.

- [ ] **Step 4: The tag audit**

```bash
grep -rn "@characterization" e2e/tests/seeded/network-acl.spec.ts e2e/tests/seeded/epg-matching.spec.ts e2e/tests/seeded/channel-bulk-ops.spec.ts
```

Exactly five: tests 1, 7, 8, 9 and 23. Every one carries a comment justifying itself. Everything
else is `@contract`. If G11 has landed by now, re-read its ADR and reconcile.

- [ ] **Step 5: The disjointness audit**

```bash
git diff --name-only origin/main
```

Must not contain: `e2e/tests/seeded/xc-output.spec.ts`, anything under `e2e/tests/lifecycle/`,
`e2e/tests/frontend/dvr.spec.ts`, `e2e/fixtures/seed.ts`, `e2e/playwright.config.ts`,
`e2e/package.json`, `scripts/e2e_up.sh`, or anything under `.github/`. If any appears, the goal has
drifted into a sibling's territory — remove it and say so.

- [ ] **Step 6: Commit and open the PR**

Conventional Commits, `test(e2e): …`. One or two commits — fixtures and docs may be separate from
the specs, but the `COVERAGE.md` update ships in the **same PR** as the tests (rule 3).

```bash
gh pr create --repo D10Scot/Dispatcharr \
  --title "test(e2e): coverage completions — ACL 403s, EPG matching, bulk ops, M3U filters, WS events (G14)" \
  --body-file <path>
```

The PR body must carry:

- Probe A, B and C's recorded answers, and whether the re-scope in Task 0 Step 2 was applied;
- the two issue numbers filed, and the explicit statement that both went to
  `--repo D10Scot/Dispatcharr`;
- **D2's exception, called out for review by name**: test 3 narrows `network_access["XC_API"]` and
  restores it, the blast-radius argument, and the note that declining it costs exactly one test;
- the cut list and which items were actually cut;
- the disjointness audit's output;
- confirmation that `/data/models` is empty after a full run.

### Verification

- [ ] `E2E result` green on the PR.
- [ ] The second consecutive `seeded` run was green (Step 1).
- [ ] `/data/models` empty (Step 2).
- [ ] `network_access` restored with no `UI` key (Step 3).
- [ ] Five `@characterization` tags, each justified (Step 4).
- [ ] The disjointness audit is clean (Step 5).
