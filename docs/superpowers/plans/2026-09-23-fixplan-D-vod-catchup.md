# Fix plan, category D — VOD and catch-up correctness

**Category.** D, VOD and catch-up correctness. Ten tracker issues: #64, #66, #98, #99, #97, #96,
#216, #141, #111, #94.

**Seed SHA.** `a54b09a9` (`main`, 2026-09-23, "metrics(curated): the Phase 2 phase-done milestone
row (#342)"). Every `file:line` below was opened at that SHA. Line numbers drift; each task's first
step re-greps its anchor rather than trusting the number.

**Ordering position.** Fifth of ten (B, A, J, C, **D**, E, G, H, I, F). B-1 and C-4 edit two of
this plan's files first (§ Overlap); D rebases over both.

**Shape.** Four PRs and one decision memo. #94 is a policy item under the brief's rule 4 and the
user asked for a memo with more detail than usual; it is § Decision memo — #94. The other nine
issues are planned in full.

**Every fix below was prototyped, and nothing but this document is committed.** Each fix was applied
to this branch's worktree at the seed, run in a private test container (`fixplan-D`, never the
shared `dispatcharr-testrunner`), break-checked, and reverted. The appendices are the tested
prototypes, spliced from the files that ran, not re-typed. The measured numbers:

| Label | Seed | After this plan | New tests |
|---|---|---|---|
| `apps.proxy.vod_proxy.tests` | 53 OK | 76 OK | 22 in D-1, 1 in D-2 |
| `apps.timeshift.tests` | 349 OK | 363 OK | 14 in D-3 |
| `apps.output.tests` | 71 OK | 73 OK | 2 in D-4 |
| `apps.vod.tests` | 47 OK | 48 OK | 1 in D-4 |

Every run was `--keepdb`, so each PR still owes one run without it (Global constraint 8). The 76
was measured with D-1 and D-2 applied together; D-2 alone measured 54, so D-1 alone is 75.

**Where the upstream SHA comes from.** This checkout has no `upstream` remote, so `45c134d2` is not
an object here. Every "upstreamable" check below fetched the upstream file with
`gh api -H "Accept: application/vnd.github.raw" "repos/Dispatcharr/Dispatcharr/contents/<path>?ref=dev"`
on 2026-09-23, when `dev`'s head was `45c134d2e28bef520da49506c247befd68dc23b1`. The same checks
reproduce with `?ref=45c134d2e28bef520da49506c247befd68dc23b1`, placed in a throwaway `git init`
tree and checked with `git apply --check`. Under the brief's rule 7 these notes are informational only.

---

## Files this plan touches

| File | PR | Issues |
|---|---|---|
| `apps/proxy/vod_proxy/byte_range.py` (new) | D-1 | #64, #66, #98 |
| `apps/proxy/vod_proxy/multi_worker_connection_manager.py` (`get_stream` `:447-582`, `_validate_range_header` `:583-619` deleted, `stream_content_with_session` `:1107-1381`) | D-1 | #64, #66, #98 |
| `apps/proxy/vod_proxy/tests/test_byte_range.py` (new) | D-1 | #64, #66, #98 |
| `apps/proxy/vod_proxy/tests/test_vod_range_responses.py` (new) | D-1 | #64, #66, #98 |
| `e2e/tests/streaming/vod-range.spec.ts` | D-1 | three pin flips |
| `apps/proxy/vod_proxy/views.py` (`:1468-1473` only) | D-2 | #99 |
| `apps/proxy/vod_proxy/tests/test_xc_episode_not_found.py` (new) | D-2 | #99 |
| `e2e/tests/streaming/xc-vod-playback.spec.ts` | D-2 | pin flip |
| `apps/timeshift/stats.py` (`:21`, `:187`) | D-3 | #216 |
| `apps/timeshift/views.py` (`:72-76`, `:1111-1148`, `:1188-1208`, `:1230-1242`, `:1961-1979`) | D-3 | #216, #141 |
| `apps/timeshift/helpers.py` (`:159-160`) | D-3 | #111 |
| `apps/timeshift/tests/test_catchup_range_hygiene.py` (new) | D-3 | #216, #141, #111 |
| `e2e/tests/streaming/catchup-provider-timezone.spec.ts` | D-3 | pin flip |
| `apps/output/views.py` (`:1674-1705` only) | D-4 | #97 |
| `apps/output/tests/test_xc_vod_info_detailed.py` (new) | D-4 | #97 |
| `apps/vod/api_views.py` (`:624` only) | D-4 | #96 |
| `apps/vod/tests/test_vod_category_account_filter.py` (new) | D-4 | #96 |
| `e2e/tests/seeded/xc-vod-catalogue.spec.ts`, `e2e/tests/seeded/vod-ingest-fidelity.spec.ts` | D-4 | pin flips |
| `e2e/COVERAGE.md` (file lines 90, 93, 94, 97; 101; 125; 98, 99 at the seed) | D-1; D-2; D-3; D-4 | status `known-bug` to `done` |
| `metrics/curated/defects.yml` (seven appended rows) | D-1, D-2, D-3, D-4 | the seven pinned issues |

The #94 memo touches no file. If the user rules for an option that emits attributes, the
implementation edits `apps/output/views.py:304-307` and `e2e/tests/seeded/catchup-m3u-advertisement.spec.ts`.

## Overlap with other categories

Every file above that also appears in another category's evidence in `sweep-report.md`, with what
this plan assumes the other plan does there.

| File | Other category and issue | What the other plan does | What D does | Who goes first | Collision risk |
|---|---|---|---|---|---|
| `apps/proxy/vod_proxy/multi_worker_connection_manager.py` | **B** #89 (B-1, `origin/docs/fixplan-B`) | Changes only the return line at `:1409` to a fixed `"Streaming error"` body. | D-1 adds a 416 arm in `get_stream` before `raise_for_status()` (`:512`), turns the `:1110-1118` refusal into a closure used twice, and replaces the header block `:1306-1381`. It does not touch `:1386-1409`. Both new 416 answers use the existing fixed body `"Requested Range Not Satisfiable"`, which satisfies B's Global constraint 7. | B | Low. The nearest D hunk ends about 25 lines above B's. |
| `apps/proxy/vod_proxy/views.py` | **B** #89, #110 (B-1); **C** #171 (C-4) | B-1 edits `:61`, `:760-766`, `:812-818`, `:860-862`, `:1075-1077`, `:1435-1436`. B leaves `stream_xc_episode` alone on purpose, because `Episode` has no `is_adult` field. C-4 edits `_transform_url` at `:603`. | D-2 edits `stream_xc_episode` at `:1468-1473` only, and adds no adult check (see B's #110 analysis). | B, then C, then D | None. Different functions. |
| `apps/timeshift/views.py` | **G** #183 (`:3256-3264`); **I** #260, #192, #142, #215, #55 | G sanitises one log line. I writes Hypothesis properties over `_parse_client_range`, `_parse_content_range_header`, `_build_downstream_length_headers`, `_presentation_relative_content_range`, `_is_near_eof_probe` (`:1103`, `:1111`, `:1131`, `:1151`, `:1169`, `:1946`). | D-3 changes the contracts of five of those helpers. | D before G and I | **Semantic for I.** The `origin/fuzz/timeshift-*` branches encode pre-D answers, for example `_parse_client_range("bytes=-500") == (0, 500)`. After D-3 that returns `None`, an inverted range returns `None`, and `_parse_content_range_header` refuses `end < start` and `end >= total`. I's properties must be written against D-3's contracts, which is what the brief's rule 6 already says. |
| `apps/timeshift/stats.py` | **I** #55 (`stats.py:130,219`) | Properties over `compute_playback_base_from_byte_range` and a second helper. | D-3 adds `is_near_eof_offset` at `:21` and calls it at `:187`. | D | None textually. I may add a property for the new helper. |
| `apps/timeshift/helpers.py` | **B** #61 (comparison only); **I** #55, #260 | B-5 cites `:424-432` as the correct encoding and edits `apps/m3u/tasks.py`, not this file. I writes properties over `build_timeshift_candidate_urls` and `convert_timestamp_to_provider_tz`. | D-3 changes `convert_timestamp_to_provider_tz`'s return shape when the input carries seconds. | D | Semantic for I, as above. |
| `apps/output/views.py` | **B** #84, #134 (B-2); **C** #91 and its duplicate #212 (C-1); **E** #80, #85; **I** #92 | B-2 edits `:357-560`. C-1 edits `:785-940`, which covers #212's slices at `:881`, `:921` and `:933`. E's #80 escapes the `#EXTINF` attributes at `:305-306`. E's #85 edits `:593`. | D-4 edits `:1674-1705` only. | B, C, then D, then E | None for D-4. **The #94 memo's implementation, if ruled, adds attributes to the same `#EXTINF` f-string E #80 escapes.** It should land after E and pass the new values through E's escaping helper. |
| `apps/vod/api_views.py` | none (C-6 edits `apps/vod/tasks.py`) | — | D-4 edits `:624`. | — | None. D-4 and C-6 share the labels `apps.output.tests` and `apps.vod.tests`. |
| `e2e/COVERAGE.md` | **B** B-7 (`:170` paragraph) | B-7 edits one paragraph. | D edits eight table rows (by file line). | B | None. |
| `metrics/curated/defects.yml` | **B** B-1, B-2, B-3 | Append rows. | Appends seven rows. | B | Trivial append conflicts only. |

---

## Global constraints

A conflict between a constraint and a task step is a **STOP and report**, never a judgement call.

1. **Anchor every command** with an absolute path or a leading `cd <your worktree> &&`.
2. **`set -o pipefail`** on any pipeline whose exit status or emptiness you read. Never `2>/dev/null`
   a git query you interpret. Brace `git show "${ref}:path"`.
3. **Stage and commit in separate Bash calls.** Write the message with the Write tool and commit with
   `git commit -F <file>`.
4. **The test-modification rule, verbatim from the brief.** A test may change only when the behaviour
   it pins is the thing being changed, and every such change is listed in the PR section with its
   before and after assertion. A test that deliberately pins a defect is flipped to pin the fix, and
   the plan shows the flipped test failing before the fix and passing after. Never widen a
   tolerance, lower a count or delete an assertion to make a run green. New behaviour gets a new
   test named after the defect.
5. **A break-check is not optional.** Apply the named wrong edit, run the one module, record the
   failure message, confirm it names the mechanism rather than a side effect, and revert.
6. **Backend runs use your own container**, never the shared `dispatcharr-testrunner`:
   `DISPATCHARR_TEST_CONTAINER=fixplan-D-<n> DISPATCHARR_TEST_DB_VOLUME=fixplan-D-<n>-db
   CLAUDE_HOOK_REPO_ROOT=<your worktree> <repo>/.claude/hooks/start-test-container.sh`. Then run a
   label with the same `docker exec` environment `.claude/hooks/pre-commit-tests.sh:126-131` uses,
   after `docker exec <container> redis-cli flushall`. The `PostToolUse` hook still uses the shared
   container whatever you export, so ignore its result or re-point it. If Docker is down, say the
   tests did not run.
7. **One fixed body for every refusal a relay-served client sees** (B's constraint 7). Never
   interpolate an exception, URL or request value into a response body.
8. **Run each PR's labels once without `--keepdb`** before pushing.
9. **E2E runs use a private stack, and the "before" image is built from the PR's base, not from
   your branch.** `scripts/e2e_up.sh` builds `docker/Dockerfile` from the tree the script sits in
   (`:25`, `:143-145`), and only when the image tag is absent. By the time a PR's pin task runs, the
   appendix is already applied to your branch, so an image built from it is the fixed backend.
   - **Never run `e2e_up.sh --reset`, `--down` or `--stop`.** All three act on the shared
     `e2e-upstream` provider regardless of the overrides below (`destroy()` at `:68-73`, and
     `docker stop "$UPSTREAM_NAME"` at `:120-124`), which kills a sibling agent's run. `--recreate`
     is the one mode that is safe. It replaces only your container, keeps your volume, and honours
     `DISPATCHARR_E2E_IMAGE`.
   - **Set `DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD=1`** when `docker image inspect
     dispatcharr-e2e-upstream:local` succeeds. Otherwise the script rebuilds the provider image and
     recreates the shared provider if its image ID moved (`:167-195`).
   - **The environment is written out in full on every command below.** Do not collect the
     assignments in a variable and expand it: zsh does not word-split an unquoted `$VAR`, so
     `env $E2E_ENV ...` passes one argument, only the first assignment takes effect, and the
     other three fall back to the script's defaults, which are the sibling stack's names (measured
     by the round-2 review). Drop `DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD=1` only if
     `dispatcharr-e2e-upstream:local` does not exist yet.
   - **The procedure, per PR.** `<n>` is the PR number in this plan, `<wt>` your worktree, `<base>`
     the SHA your branch forked from, and `<scratch>` your scratchpad directory.
     1. `git -C <wt> worktree add --detach <scratch>/fixplan-D-base-<n> <base>`
     2. Build the before image and start the stack:

        ```bash
        DISPATCHARR_E2E_CONTAINER=e2e-fixplan-D DISPATCHARR_E2E_VOLUME=e2e-fixplan-D-data \
        DISPATCHARR_E2E_PORT=9195 DISPATCHARR_E2E_NETWORK=e2e-fixplan-D-net \
        DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD=1 \
        DISPATCHARR_E2E_IMAGE=dispatcharr-e2e:fixplan-D-<n>-before \
          <scratch>/fixplan-D-base-<n>/scripts/e2e_up.sh
        ```

     3. Once per worktree, install the e2e packages: `cd <wt>/e2e && npm ci && npx playwright
        install chromium`. (`e2e/README.md` writes it as `npx playwright install --with-deps
        chromium`; the flag installs system libraries, which matters on Linux and not on macOS.)
        Then, with the pin already flipped in `<wt>`, run it from **your**
        worktree:
        `cd <wt>/e2e && E2E_BASE_URL=http://localhost:9195 npx playwright test --project=<project>
        <spec> --reporter=json > <scratch>/d<n>-before.json`. It must fail.
     4. Build the after image into the same container name and volume. This builds from `<wt>`,
        the fixed tree:

        ```bash
        DISPATCHARR_E2E_CONTAINER=e2e-fixplan-D DISPATCHARR_E2E_VOLUME=e2e-fixplan-D-data \
        DISPATCHARR_E2E_PORT=9195 DISPATCHARR_E2E_NETWORK=e2e-fixplan-D-net \
        DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD=1 \
        DISPATCHARR_E2E_IMAGE=dispatcharr-e2e:fixplan-D-<n>-after \
          <wt>/scripts/e2e_up.sh --recreate
        ```

     5. Re-run step 3's command into `<scratch>/d<n>-after.json`. It must pass.
     6. Tear down only your own objects: `docker rm -f e2e-fixplan-D`, `docker volume rm
        e2e-fixplan-D-data`, `docker network disconnect e2e-fixplan-D-net e2e-upstream`,
        `docker network rm e2e-fixplan-D-net`, both `docker rmi` tags, and
        `git -C <wt> worktree remove <scratch>/fixplan-D-base-<n>`.
   - **Reading the JSON.** Each test is at `suites[].specs[]`, recursing through nested
     `suites[]`, with `title`, `ok`, and `tests[].results[].status` (`passed` or `failed`). A
     failure's first assertion is at `tests[].results[].errors[].location.line`. That line must be
     the assertion the plan names, not a premise assertion above it. `--project=streaming` and
     `--project=seeded` both depend on `bootstrap` (`e2e/playwright.config.ts:81-83`), which
     Playwright runs first automatically. Its results appear in the same JSON and must pass.

---

## Per-issue analysis

### #64 — a VOD suffix Range is served as a prefix

- **Root cause.** `_validate_range_header` (`apps/proxy/vod_proxy/multi_worker_connection_manager.py:583-619`)
  maps an empty start to `start_byte = 0` (`:600-601`), so `bytes=-500` becomes `bytes=0-500`. It
  runs only when `state.content_length` is known (`:468`), so the rewrite hits established
  sessions. There is a second site the issue does not name: the response headers are computed from
  the **client's** raw header, not the rewritten one (`:1320-1339`, `start = int(start_byte) if
  start_byte else 0` at `:1325`). A suffix range on a **first** request therefore reaches the
  provider intact and is served the right bytes, but under `Content-Range: bytes 0-500/<total>` and
  `Content-Length: 501`. The prototype test measured `bytes 0-100/1000` for `bytes=-100`.
- **Fix.** One resolver, `resolve_range(header, total)`, implementing RFC 9110 §14.1.2 suffix
  semantics (`bytes=-N` is `max(0, total-N)` to `total-1`; `bytes=-0` is unsatisfiable). `get_stream`
  sends the resolved absolute range. Every numeric guard in the new module is ASCII-only
  (`_digits`: `isascii() and isdigit()`), because `"²".isdigit()` is true and `int("²")` raises,
  and WSGI decodes headers as Latin-1. The one stored-length read, `parse_length`, uses the same
  guard. That also retires a latent seed crash: `get_stream` stores a `Content-Range` total that
  passed `isdigit()` (`:523-524`), and the old code later called `int()` on it (`:469`). The response headers follow what the provider sent (#66
  below), so the first-request case is fixed by the same change.
- **Tests.** New, in `test_byte_range.py` and `test_vod_range_responses.py` (D-1). E2E pin
  `vod-range.spec.ts:328` flips.
- **Size** M together with #66 and #98. **Upstreamable** no as a diff; upstream `dev` at
  `45c134d2` carries the same code at `multi_worker_connection_manager.py:653` and the change ports.
- **Duplicates.** None. #141 is the catch-up analogue, in different code.

### #66 — a Range-ignoring provider's head is served under a 206 for the slice

- **Root cause.** `stream_content_with_session` sets `status_code = 206 if range_header else 200`
  (`:1307`) and synthesises `Content-Range`/`Content-Length` from the client's range and the stored
  size (`:1320-1339`). `stream_generator` passes the upstream body through untouched (`:1156`). The
  upstream status is never read: `get_stream`'s only check is `>= 400` on a cached `final_url`
  (`:495`) and `raise_for_status()` (`:512`). A provider that answers 200 with the whole file is
  indistinguishable from one that answered 206.
- **Fix.** A pure `plan_downstream(client_range, upstream_status, upstream_content_range,
  upstream_content_length, known_total)` decides the client-facing answer from what the provider
  actually sent. On a provider 206 with a valid `Content-Range`, relay that range. On a provider 200
  to a Range request, cut the body to the requested slice (`slice_chunks(chunks, skip, limit)`) and
  send a true 206. With no length to cut against, send an honest 200 with the whole body and no
  `Content-Range`. The alternative, always an honest 200, is Open question Q2.
- **Tests.** New (D-1). E2E pin `vod-range.spec.ts:263` flips.
- **Size** M with #64 and #98. **Upstreamable** no as a diff; the same defect is at upstream
  `multi_worker_connection_manager.py:1638`.
- **Cost of the default.** A seek to byte N against a Range-ignoring provider downloads and discards
  N bytes. That is the same work ExoPlayer does client-side when it receives a 200 to a Range
  request, and it only applies to providers that ignore Range.

### #98 — a provider's 416 on a session's first request becomes a 500

- **Root cause.** On a first request `content_length` is unknown, so `get_stream` forwards the
  client's range verbatim (`:466-476`). The provider's 416 hits `raise_for_status()` (`:512`), the
  `except` at `:578-582` re-raises, and `stream_content_with_session`'s handler (`:1386`) answers
  500 at `:1409`. Only the `get_stream`-returns-`None` path answers 416 (`:1110-1118`). The
  2026-09 comment on the issue reports the same 500 on a session with three prior requests under
  load. That is consistent with this root cause: the session-less request was matched to a fresh
  session by the heuristic `find_matching_idle_session` (memory: VOD session reuse is heuristic).
  The fix covers both.
- **Fix.** In `get_stream`, a provider 416 closes the response and returns `None` before
  `raise_for_status()`. The caller's refusal becomes a closure used by both 416 paths. For a
  session this request created, it also deletes the Redis connection state, as the exception path
  already does at `:1403-1407`. Other provider 4xx/5xx still become 500 (follow-up F2).
- **Tests.** New (D-1). E2E pin `vod-range.spec.ts:150` flips.
- **Size** S within D-1. **Upstreamable** no as a diff; the same `raise_for_status()` is at
  upstream `:563`.

### #99 — `stream_xc_episode`'s `DoesNotExist` guard is dead

- **Root cause.** `apps/proxy/vod_proxy/views.py:1468-1473` wraps `.filter(...).first()` in
  `except M3UEpisodeRelation.DoesNotExist`, which `.first()` never raises. `:1476` then
  dereferences `None`. The prototype test failed with `AttributeError: 'NoneType' object has no
  attribute 'episode'`.
- **Fix.** The `if not episode_relation:` guard `stream_xc_movie` already uses (`:1435-1436`).
- **Tests.** New `test_xc_episode_not_found.py`. E2E pin `xc-vod-playback.spec.ts:222` flips.
- **Size** S. **Upstreamable** no: upstream `dev` already has this exact fix
  (`apps/proxy/vod_proxy/views.py:1505-1507` at `45c134d2`).

### #97 — `xc_get_vod_info` gates the `detailed_info` merge on the wrong object

- **Root cause.** `apps/output/views.py:1675` tests `movie.custom_properties` and `:1680` reads
  `detailed_info` from `movie_relation.custom_properties`. A movie whose `custom_properties` is
  empty or `None` skips the whole merge. `:1679` is the commented-out original read.
- **Correction to the issue.** The issue lists `cover_big` among the lost fields. It is not lost:
  `movie_data['cover_big']` is never read, because `info["cover_big"]` comes from `movie_cover`
  (`:1712-1737`). What an XC client loses is `bitrate`, `video`, `audio`, the `plot` override and
  the `name`/`year`/`genre`/`rating`/id overrides (`:1682-1704`).
- **Fix.** Read both dictionaries unconditionally (`custom_data = movie.custom_properties or {}`,
  `detailed_info = (movie_relation.custom_properties or {}).get('detailed_info', {})`), delete the
  gate and the dead comment, and dedent the block. The `or {}` on the relation also removes an
  `AttributeError` that the broad `except` at `:1706` was swallowing when the relation's dict was
  `None`.
- **Tests.** New `test_xc_vod_info_detailed.py`, with the movie's `custom_properties` set explicitly
  to `None` (memory: keepdb hides seeded-row drift). E2E pin `xc-vod-catalogue.spec.ts:427` flips.
  The existing `test_xc_vod_info.py` (4 tests) passes unchanged.
- **Size** S. **Upstreamable** yes: the hunk applies to upstream `dev` at `45c134d2` (checked with
  `git apply --check`; the guard is at upstream `:1789`).

### #96 — `VODCategoryFilter.m3u_account` names a relation `VODCategory` does not have

- **Root cause.** `apps/vod/api_views.py:624` declares `field_name="m3u_account__id"`. The reverse
  accessor is `m3u_relations` (`apps/vod/models.py:318`). The siblings use
  `m3u_relations__m3u_account__id` (`:55`). The prototype test raised `FieldError: Cannot resolve
  keyword 'm3u_account'`.
- **Fix.** The sibling's path. `M3UVODCategoryRelation` is `unique_together = [('m3u_account',
  'category')]` (`apps/vod/models.py:333`), so a single-account filter yields no duplicate rows and
  needs no `.distinct()`.
- **Tests.** New `test_vod_category_account_filter.py`. E2E pin `vod-ingest-fidelity.spec.ts:285`
  flips.
- **Size** S. **Upstreamable** no: upstream `dev` already has this exact fix (`apps/vod/api_views.py:733`
  at `45c134d2`). The bot comment on the issue concerns the deleted ownership lease and is ignored.

### #216 — every Range on a catch-up archive of 2 MiB or less is an EOF probe

- **Root cause.** `_is_near_eof_probe` returns `start >= max(0, total - _EOF_PROBE_TAIL_BYTES)`
  (`apps/timeshift/views.py:1241`). With `total <= 2_097_152` the right side is 0. **The same
  predicate is copied at `apps/timeshift/stats.py:187`**, where it decides whether a seek keeps the
  previous stats anchor. The issue names only the first copy.
- **Fix.** One helper in `stats.py` beside the constant, `is_near_eof_offset(start, total)`, which is
  true only when `total > EOF_PROBE_TAIL_BYTES and start >= total - EOF_PROBE_TAIL_BYTES`. An archive
  no larger than the window has no tail distinct from its body. Both sites call it. It lives in
  `stats.py` because `views.py` already imports from `stats.py` (`:72-76`) and the reverse would be
  a cycle.
- **Residual, not in scope.** An archive just over 2 MiB still classifies almost all of itself as
  tail (follow-up F5). The issue asks only about the degenerate case.
- **Tests.** New, in `test_catchup_range_hygiene.py`, using the issue's 1.5 MiB counterexample. No
  existing test moved: the prototype ran 349 of 349 green with the new predicate.
- **Size** S. **Upstreamable** yes (the D-3 diff applies to upstream `dev`, checked).

### #141 — catch-up emits invalid `Content-Range` or a negative `Content-Length`

- **Root cause, finding by finding.**
  1. `_parse_client_range` maps an empty start to 0 (`:1120`), so `bytes=-500` parses as `(0, 500)`.
     Its effects: `_map_client_range_through_presentation` widens it to `bytes=50-550` (`:1955-1958`),
     and `_is_near_eof_probe` misclassifies a tail request.
  2. It never checks `end >= start` (`:1125-1126`).
  3. `_build_downstream_length_headers` synthesises `Content-Range` without checking
     `start <= end` (`:1192-1202`).
  4. `_parse_content_range_header` accepts `end < start` (`:1141-1148`), the builder forwards it
     verbatim (`:1190-1191`), and computes `up_end - up_start + 1` from it (`:1205-1208`), which is
     negative.
  5. `_presentation_relative_content_range` returns the **absolute** CDN range when it cannot
     translate (`:1977-1978`).
- **Reachability.** Findings 2 and 3 need a provider that answers 206 without a `Content-Range`,
  because a compliant provider ignores an invalid range (200) or refuses an out-of-range one (416,
  passed through at `:3230-3237`). Finding 4 needs a buggy or hostile provider. Finding 1 needs only
  a client that sends a suffix range.
- **Fix.** `_parse_client_range` returns `None` for the suffix form and for an inverted range. A new
  `_is_suffix_range` makes `_is_near_eof_probe` treat `bytes=-N` as a tail probe.
  `_map_client_range_through_presentation` then passes a suffix through unchanged, which is correct
  because the presented file is always a tail of the archive (`:3344`, `remaining = total - start`).
  `_parse_content_range_header` accepts only `a-b/T` with `a <= b` and `b < T`. The builder forwards
  an upstream `Content-Range` only when it parses, synthesises only when `start <= end`, and never
  computes a length from an invalid range. `_presentation_relative_content_range` returns `None`
  when it cannot translate, instead of the absolute value. The seed's parsers used `try: int()`,
  which rejected `"²"` safely. The replacements test digits first, so they use an ASCII-only
  `_ascii_digits` rather than a bare `str.isdigit()`. Otherwise `Range: bytes=²-` would become an
  uncaught 500 (raised by the category I planner and verified; regression test below). The same
  guard also rejects `'٣'`, which is `isdecimal()` and which `int()` accepts. The seed parsed
  `bytes=٣-` as `(3, None)`; RFC 9110's grammar allows ASCII DIGIT only, so `None` is correct.
- **What a client sees now in the degenerate case.** A 206 whose provider sent no usable
  `Content-Range` now carries no `Content-Range` at all, rather than a false one. That is still not
  RFC-compliant. A 502 would be stricter, but the main path has already reserved a pool slot and
  written pool state by then (`:3308-3323`), so a 502 there needs its own unwind (follow-up F4).
- **Behaviour changes callers see.** A suffix range now records `serving_range` as `range`, not
  `start` (`_store_pool_serving_range`, `:1816-1829`), and passes `None` rather than 0 as the stats
  range start (`:3395`). Both are more accurate. No existing test pins either.
  **`_extract_representation_length` (`:1151-1166`) also changes.** It reads the total from
  `_parse_content_range_header`. A provider that sends an invalid `Content-Range` such as
  `bytes 0-1000/1000` (end not below total) used to yield 1000. It now falls through to
  `Content-Length`, which on a 206 is the partial length. That length then feeds the near-EOF
  classification and the stats anchor. The plan keeps the strict refusal: the header is invalid
  under RFC 9110, and a total taken from an invalid range is not trustworthy either. The effect is
  confined to a provider that already breaks the protocol. Narrowing the refusal for this one caller
  would mean a second parser with different rules.
- **Tests.** New (D-3), with the issue's five counterexamples verbatim. No existing test moved: 349
  of 349 green.
- **Size** M. **Upstreamable** yes (checked).
- **Duplicates.** None. It is the catch-up sibling of #64, in unrelated code.

### #111 — a non-UTC provider timezone truncates the requested start to the minute

- **Root cause.** `convert_timestamp_to_provider_tz` returns its input unchanged for no zone or
  `"UTC"` (`apps/timeshift/helpers.py:145-146`) and otherwise formats `"%Y-%m-%d:%H-%M"` (`:160`).
  `build_timeshift_candidate_urls` re-derives the colon-seconds candidate from that truncated value
  (`:479-488`).
- **Why not always emit seconds.** The value feeds `build_timeshift_redirect_url` verbatim
  (`:449-464`). Emitting `HH-MM-SS` for every non-UTC request would change the redirect URL every
  existing minute-precision client produces today, towards providers that may expect `HH-MM`.
- **Fix.** Keep the seconds when the converted instant has any: `%Y-%m-%d:%H-%M-%S` if
  `local_dt.second`, else the existing `%Y-%m-%d:%H-%M`. A request that carried seconds keeps them
  in every zone. A request that did not is byte-identical to today. `normalize_catchup_timestamp_input`
  already parses the `HH-MM-SS` shape (`:31-44`), so every downstream reader accepts it.
- **Tests.** New (D-3). The existing nine `ConvertTimestampToProviderTzTests` all use zero seconds
  and pass unchanged. E2E pin `catchup-provider-timezone.spec.ts:181` flips. Its assertion expects
  `2026-01-15:13:00:45` for candidate 2, which the prototype produced.
- **Size** S. **Upstreamable** yes (checked).
- **Triage.** The bot's `wontfix` misread the issue; the lead has already removed the label.

### #94 — the generated M3U advertises no catch-up

A policy item. See § Decision memo — #94. Two corrections to the issue body, recorded there: the
ingest reader reads `tv_archive`/`tv_archive_duration` (`apps/m3u/tasks.py:1391-1397`), not the
`catchup=` family, and `/proxy/catchup/<uuid>` cannot be reached from an anonymous playlist at all.

---

## PR D-1 — VOD Range answers describe the bytes actually sent

- **Branch** `fix/D-1-vod-range-answers`
- **Closes** #64, #66, #98.
- **Depends on** B-1 merged (it edits `:1409` of the same file). Re-seed on B-1's merge.
- **Files** `apps/proxy/vod_proxy/byte_range.py` (new),
  `apps/proxy/vod_proxy/multi_worker_connection_manager.py`,
  `apps/proxy/vod_proxy/tests/test_byte_range.py` (new),
  `apps/proxy/vod_proxy/tests/test_vod_range_responses.py` (new),
  `e2e/tests/streaming/vod-range.spec.ts`, `e2e/COVERAGE.md`, `metrics/curated/defects.yml`.
- **Labels** `apps.proxy.vod_proxy.tests` (one; `python scripts/ci_backend_test_labels.py` on the two
  source files prints exactly that). The e2e change runs the `streaming` project.
- **upstreamable** no as a diff (upstream's file differs); the change ports.
- **Size** M.

### Task 1.1 — the pure helper

1. `grep -n "_validate_range_header" -r apps/` must print only its definition (`:583`) and its one
   call (`:469`). Any other caller is a STOP: this PR deletes the method.
2. Write `test_byte_range.py` (Appendix A.2) and `byte_range.py` (Appendix A.1). The module is new,
   so there is no red run for the helper by itself; its tests are red-green through Task 1.2's
   integration tests. Run the module: 15 tests pass.
3. **Break-check.** In `resolve_range`, replace the suffix branch's return with `return 0, length`.
   Exactly `test_a_suffix_range_was_resolved_as_a_prefix` and
   `test_a_suffix_longer_than_the_file_is_the_whole_file` redden. Revert.
4. **Break-check.** Change `_digits` to `return value.isdigit()`. Exactly
   `NonAsciiDigitTests.test_a_non_ascii_digit_passed_an_isdigit_guard_and_crashed_int` errors, with
   `ValueError: invalid literal for int()` seven times: in the six subtests and in the bare
   `parse_length("²")` assertion that follows them (measured). Revert. This test has no red
   run against the seed because the module is new. The break-check is what proves it bites.

### Task 1.2 — the connection manager

1. Write `test_vod_range_responses.py` (Appendix A.4). It drives `stream_content_with_session` end
   to end: `LockAwareFakeRedis` from `test_vod_lock_contention.py` holds the session, and
   `requests.Session` is patched to a fake provider that honours Range per RFC unless a test
   overrides it. It builds the manager with `__new__` (the `test_profile_connections.py:91` pattern)
   and patches `find_matching_idle_session`, `_check_and_reserve_profile_slot`,
   `_decrement_profile_connections` and `_send_vod_event`.
2. Run it on the unfixed manager (the helper module from Task 1.1 present). **Five fail and two
   pass**, measured:

   | Test | Measured failure on the seed |
   |---|---|
   | `test_a_provider_416_on_a_first_request_was_a_500` | `AssertionError: 500 != 416` |
   | `test_a_range_ignoring_provider_had_its_head_served_as_the_requested_slice` | body is the whole 1000-byte asset, not bytes 100-199 |
   | `test_a_range_ignoring_provider_with_no_length_is_served_as_an_honest_200` | `AssertionError: 206 != 200` |
   | `test_a_suffix_range_on_a_first_request_got_a_prefix_content_range` | `'bytes 0-100/1000' != 'bytes 900-999/1000'` |
   | `test_a_suffix_range_on_an_established_session_was_served_as_a_prefix` | `['bytes=0-100'] != ['bytes=900-999']` (the range sent upstream) |
   | `test_an_unsatisfiable_range_on_an_established_session_is_still_416` | passes (control) |
   | `test_a_provider_206_is_relayed_with_its_own_content_range` | passes (control) |

3. Apply Appendix A.3. Run the module: 7 pass. Run the label: 75 pass (53 + 15 + 7).
4. **Break-check A.** Pass `0, None` instead of `plan.skip, plan.limit` to `slice_chunks`. Exactly
   `test_a_range_ignoring_provider_had_its_head_served_as_the_requested_slice` reddens, on the body.
   Revert. (Measured.)
5. **Break-check B.** Change `if response.status_code == 416:` to `if False:`. Exactly
   `test_a_provider_416_on_a_first_request_was_a_500` reddens with `500 != 416`. Revert. (Measured.)
6. **Break-check C.** Delete the `else: redis_connection.cleanup(...)` arm in
   `refuse_unsatisfiable`. `test_a_provider_416_on_a_first_request_was_a_500` reddens on the
   `hgetall` assertion. Revert. That test also asserts the provider was asked, so its empty-hash
   assertion cannot pass merely because the session was never created.

### Task 1.3 — flip the three e2e pins

Flip the three pins as tabled below, then follow Global constraint 9's procedure with
`<project>` = `streaming` and `<spec>` = `tests/streaming/vod-range.spec.ts`. Against the before
image the three flipped tests fail, each at the assertion named in its row below, with every
premise assertion above it passing. The file's two untouched tests pass. Against the after image
all five pass. Attach both JSON summaries to the PR.

**Test changes under the rule.**

| Test | Before | After |
|---|---|---|
| `'an unsatisfiable Range on a fresh session is 416, not 500'` (`:150`) | `test.fail(...)`; `expect(res.status()).toBe(416)` | `test(...)`; the same assertion, plus `expect(await res.text()).toBe('Requested Range Not Satisfiable')`. The comment block `:136-149` is replaced by one paragraph naming #98 as fixed. |
| `'a provider that ignores Range still yields the requested bytes'` (`:263`) | `test.fail(...)`; requests the session-less movie URL; asserts only the body bytes | `test(...)`; derives `sessionUrl` from `full.url()` exactly as the first test does (`:75-77`) and requests that, so the established-session path is exercised by construction (memory: VOD session reuse is heuristic); keeps the body assertion; adds `expect(partial.status()).toBe(206)` and `expect(partial.headers()['content-range']).toBe(\`bytes ${start}-${end}/${total}\`)`. The comment block `:244-262` is rewritten to say what is pinned. |
| `'a suffix Range returns the tail of the file'` (`:328`) | `test.fail(...)`; session-less request; asserts status 206, length 500, the tail bytes | `test(...)`; pinned `sessionUrl` as above; keeps all three assertions; adds `expect(res.headers()['content-range']).toBe(\`bytes ${total - 500}-${total - 1}/${total}\`)`. The comment at `:338-342` ("would make this test pass for the wrong reason") is rewritten: after the fix both paths are correct, and the pin chooses the established one because that is where the rewrite lived. |

Every change narrows what passes. None widens a tolerance or removes an assertion. The session pin
is a determinism fix the first test in the file already applies.

### Task 1.4 — COVERAGE.md and the ledger

- `e2e/COVERAGE.md` file lines 90, 93, 94 and 97 at the seed (`sed -n 90p` reaches the first):
  status `known-bug` becomes `done`, and each row's text
  gains one sentence: "Fixed in #<this PR>; the pin is now a passing `test()`." Keep the defect
  description as the record.
- Append three rows to `metrics/curated/defects.yml`, directly at `fixed` (B-1's precedent for a
  new row). In every ledger row in this plan, `status_changed` is the date the row is written, as
  `docs/agents/metrics.md:102-103` says ("today's `status_changed`"), not a merge date.

```yaml
- {id: vod-suffix-range-served-as-prefix, title: "vod_proxy resolved a suffix Range (bytes=-N) as bytes=0-N on an established session, and labelled a first request's correct tail bytes with a prefix Content-Range", area: correctness, severity: medium, status: fixed, source: null, issue: 64, test: e2e/tests/streaming/vod-range.spec.ts, fixed_in: <this PR>, carried_as: null, first_seen: 2026-08-29, status_changed: <date written>}
- {id: vod-range-ignored-206-wrong-bytes, title: "vod_proxy answered 206 with a Content-Range for the requested slice while streaming the head of the file when the provider ignored Range and sent 200", area: correctness, severity: medium, status: fixed, source: null, issue: 66, test: e2e/tests/streaming/vod-range.spec.ts, fixed_in: <this PR>, carried_as: null, first_seen: 2026-08-29, status_changed: <date written>}
- {id: vod-first-request-416-is-500, title: "A provider 416 on a VOD session's first request hit raise_for_status() and was answered 500 instead of 416", area: correctness, severity: low, status: fixed, source: null, issue: 98, test: e2e/tests/streaming/vod-range.spec.ts, fixed_in: <this PR>, carried_as: null, first_seen: 2026-08-31, status_changed: <date written>}
```

Validate with `python3 -m metrics.build --validate-only --curated metrics/curated`.

### PR description draft

> **fix(vod_proxy): Range answers describe the bytes actually sent**
>
> Closes #64, #66 and #98.
>
> The VOD proxy decided its status and `Content-Range` from the client's own `Range` header, never
> from what the provider sent. Three defects followed. A suffix range (`bytes=-N`) was resolved as
> `bytes=0-N` (#64). A provider that ignored `Range` and sent the whole file had its head served
> under a 206 naming the requested slice (#66). A provider's 416 on a session's first request hit
> `raise_for_status()` and became a 500 (#98).
>
> A new pure module, `byte_range.py`, resolves a range against a known size, parses `Content-Range`
> strictly, and plans the client-facing answer from the provider's actual status and headers. A
> provider 206 is relayed with its own range. A provider 200 to a Range request is cut to the
> requested slice, so the 206 we send is true. A provider 416 is answered 416, with the session this
> request created removed and the profile slot released.
>
> Three `test.fail()` pins in `vod-range.spec.ts` become passing tests, two of them now pinned to an
> established session and asserting `Content-Range` as well as bytes.
>
> Not changed: other provider 4xx/5xx statuses still answer 500 with B-1's fixed body.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## PR D-2 — `stream_xc_episode` answers 404 for an unknown episode

- **Branch** `fix/D-2-xc-episode-404`
- **Closes** #99.
- **Depends on** B-1 and C-4 merged (same file, other functions).
- **Files** `apps/proxy/vod_proxy/views.py`, `apps/proxy/vod_proxy/tests/test_xc_episode_not_found.py`
  (new), `e2e/tests/streaming/xc-vod-playback.spec.ts`, `e2e/COVERAGE.md`, `metrics/curated/defects.yml`.
- **Labels** `apps.proxy.vod_proxy.tests`.
- **upstreamable** no: upstream `dev` already carries this fix.
- **Size** S.

### Task 2.1

1. Re-grep: `grep -n "except M3UEpisodeRelation.DoesNotExist" apps/proxy/vod_proxy/views.py` prints
   exactly one line.
2. Write `test_xc_episode_not_found.py` (Appendix B.2). A `TestCase` (it runs a real ORM query that
   matches nothing). `resolve_authorization` and `stream_vod` are patched.
3. Run it on the unfixed tree: it **errors** with `AttributeError: 'NoneType' object has no attribute
   'episode'` (measured). That is the mechanism.
4. Apply Appendix B.1. Run: 1 passes; the label passes 54 (measured, without D-1).
5. **Break-check.** Change `if not episode_relation:` to `if episode_relation is False:`. The test
   errors with the same `AttributeError`. Revert.

### Task 2.2 — the pin, COVERAGE.md and the ledger

| Test | Before | After |
|---|---|---|
| `xc-vod-playback.spec.ts` `'an unknown episode id on the XC series route is a 404, not a 500'` (`:222`) | `test.fail(...)`; `expect(res.status()).toBe(404)` | `test(...)`; the same assertion. The explanatory comment above it (`:205-221`) is replaced by one paragraph naming #99 as fixed. |

Run it with Global constraint 9's procedure, `<project>` = `streaming`,
`<spec>` = `tests/streaming/xc-vod-playback.spec.ts`. Before: the pin fails at
`expect(res.status()).toBe(404)` (`:245`). After: every test in the file passes. Set
`e2e/COVERAGE.md` line 101 to `done` with the same one-sentence note as D-1. Append:

```yaml
- {id: xc-episode-unknown-id-500, title: "stream_xc_episode guarded .first() with a dead except DoesNotExist and dereferenced None, so an unknown episode id was a 500, not a 404", area: correctness, severity: low, status: fixed, source: null, issue: 99, test: e2e/tests/streaming/xc-vod-playback.spec.ts, fixed_in: <this PR>, carried_as: null, first_seen: 2026-08-31, status_changed: <date written>}
```

### PR description draft

> **fix(vod_proxy): an unknown XC episode id is a 404, not a 500**
>
> Closes #99. `stream_xc_episode` caught `DoesNotExist` around `.first()`, which never raises it, and
> then dereferenced `None`. It now uses the `if not episode_relation:` guard `stream_xc_movie`
> already has. Upstream `dev` made the same change independently. The `xc-vod-playback.spec.ts` pin
> becomes a passing test.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## PR D-3 — catch-up Range hygiene and timezone precision

- **Branch** `fix/D-3-catchup-ranges-and-timezone`
- **Closes** #216, #141, #111.
- **Depends on** nothing in B or C. It must merge before category I's timeshift property PR
  (§ Overlap).
- **Files** `apps/timeshift/stats.py`, `apps/timeshift/views.py`, `apps/timeshift/helpers.py`,
  `apps/timeshift/tests/test_catchup_range_hygiene.py` (new),
  `e2e/tests/streaming/catchup-provider-timezone.spec.ts`, `e2e/COVERAGE.md`,
  `metrics/curated/defects.yml`.
- **Labels** `apps.timeshift.tests` (one).
- **upstreamable** yes: the full D-3 source diff applies to upstream `dev` at `45c134d2` (checked
  with `git apply --check` against upstream's `views.py`, `helpers.py` and `stats.py`).
- **Size** M.

### Task 3.1 — the shared predicate, as a pure refactor first

1. Apply Appendix C.1 (`stats.py`) **with the old formula** (`return start >= max(0, total -
   EOF_PROBE_TAIL_BYTES)` as the body of `is_near_eof_offset`), plus the two `views.py` lines of
   Appendix C.2 that belong to #216: the `is_near_eof_offset` import and
   `return is_near_eof_offset(start, total)` in `_is_near_eof_probe`. Both copies now call the
   helper and nothing behaves differently.
2. Run the label: 349 pass. This proves the refactor is inert.
3. Write `test_catchup_range_hygiene.py` (Appendix C.3). Writing it after the refactor is
   deliberate: the module imports `is_near_eof_offset`, and before the refactor it would fail as an
   `ImportError` rather than on any mechanism.
4. Run the module. Measured: **14 tests, 12 failures and 1 error.** Subtests are counted separately.
   The error is `test_a_non_ascii_digit_passed_an_isdigit_guard_and_crashed_int`, with
   `AttributeError: ... no attribute '_is_suffix_range'`, which is expected until Task 3.3 adds the
   helper. That test pins a regression the new code could introduce, not a seed defect: the seed's
   `try: int()` already returned `None` for these inputs. Task 3.3's break-check is what proves it
   bites. The only passes are the two controls, `test_a_large_archive_tail_is_still_an_eof_probe`
   and `test_a_minute_precision_start_keeps_its_minute_shape`, plus the UTC subtest of
   `test_the_colon_seconds_candidate_keeps_the_seconds_in_every_zone`. The label measured 363 tests,
   12 failures and 1 error, all in the new module.

### Task 3.2 — #216

1. Replace the helper's body with the new formula (Appendix C.1 as written). Run the module: the four
   `SmallArchiveEofProbeTests` failures clear.
2. **Break-check.** Restore the old formula. Exactly
   `test_a_mid_file_seek_on_a_small_archive_was_classified_as_an_eof_probe` (both subtests),
   `test_a_small_archive_seek_kept_the_previous_stats_base` and `test_the_window_boundary` redden
   (measured). Revert.

### Task 3.3 — #141

1. Apply the rest of Appendix C.2's `views.py` hunks. Run the module: the seven `CatchupRangeHeaderTests` pass.
2. **Break-check.** In `_build_downstream_length_headers`, change `if parsed_upstream:` back to
   `if upstream_content_range:`. Exactly
   `test_an_inverted_upstream_content_range_gave_a_negative_content_length` reddens (measured).
   Revert.
3. **Break-check (finding 1).** Delete the `_is_suffix_range` early return in `_is_near_eof_probe`.
   Exactly `test_a_suffix_range_was_parsed_as_a_prefix` reddens. Revert.
4. **Break-check (finding 2).** In `_parse_client_range`, change `if end < start:` to `if False:`.
   Exactly `test_an_inverted_client_range_was_accepted` reddens, on its first assertion (measured).
   Revert.
5. **Break-check (finding 5).** In `_presentation_relative_content_range`, make the
   `rel_start < 0 or rel_end >= ...` branch `return upstream_content_range`. Exactly
   `test_an_untranslatable_upstream_range_leaked_absolute_coordinates` reddens (measured). Revert.
6. **Break-check (non-ASCII digits).** Change `_ascii_digits` to `return value.isdigit()`. Exactly
   `test_a_non_ascii_digit_passed_an_isdigit_guard_and_crashed_int` errors with `ValueError` in its
   subtests (measured). Revert.

### Task 3.4 — #111

1. Apply Appendix C.2's `helpers.py` hunk, which also updates the function's docstring for the
   `-SS` case. Run the module: 14 pass. Run the label: 363 pass (measured).
2. **Break-check.** Drop the `if local_dt.second:` branch. Exactly
   `test_a_non_utc_provider_zone_truncated_the_start_to_the_minute` and the Brussels subtest of
   `test_the_colon_seconds_candidate_keeps_the_seconds_in_every_zone` redden. Revert.
3. **Break-check.** Always use `%Y-%m-%d:%H-%M-%S`. Exactly
   `test_a_minute_precision_start_keeps_its_minute_shape` reddens. Revert.

### Task 3.5 — the pin, COVERAGE.md and the ledger

| Test | Before | After |
|---|---|---|
| `catchup-provider-timezone.spec.ts` `'a requested start keeps its seconds whatever the provider timezone is'` (`:181`) | `test.fail(...)`; final assertion `expect(bxlAsked[2].start, ...).toBe('2026-01-15:13:00:45')` | `test(...)`; every assertion unchanged. The "KNOWN BUG" comment (`:184-201`) and the "FAILS TODAY" comment (`:260-263`) are replaced by one paragraph saying the test pins #111's fix, and the file header's "and drops the seconds while it is at it" (`:8`) is deleted. |

Run it with Global constraint 9's procedure, `<project>` = `streaming`,
`<spec>` = `tests/streaming/catchup-provider-timezone.spec.ts`. Before: the pin fails at the
`bxlAsked[2].start` assertion (`:264-267`). After: it passes. The file's other two tests,
including the minute-precision `'...converts the requested start before it is sent'` (`:97`, which
asserts `2026-01-15:13-00`), must pass on both trees: that is the check that a minute-precision
request did not change shape.

Set `e2e/COVERAGE.md` line 125 to `done` with the one-sentence note. #216 and #141 have no e2e pin
and no COVERAGE row. Append one ledger row:

```yaml
- {id: catchup-provider-tz-drops-seconds, title: "convert_timestamp_to_provider_tz dropped the requested seconds for a non-UTC provider timezone while the UTC branch kept them, so the precision asked for depended on the provider's declared zone", area: correctness, severity: low, status: fixed, source: null, issue: 111, test: e2e/tests/streaming/catchup-provider-timezone.spec.ts, fixed_in: <this PR>, carried_as: null, first_seen: 2026-09-01, status_changed: <date written>}
```

### PR description draft

> **fix(timeshift): catch-up Range hygiene and timezone precision**
>
> Closes #216, #141 and #111.
>
> **#216.** On an archive of 2 MiB or less every Range was classified as a near-EOF probe, so a
> mid-file seek against a busy pool got a 503 instead of displacing it. The predicate had two
> copies, in `views.py` and `stats.py`. Both now call `is_near_eof_offset`, which has no tail window
> for an archive no larger than the window.
>
> **#141.** The Range and `Content-Range` parsers accepted suffix and inverted ranges and a
> `Content-Range` with `end < start`. That produced a widened provider range after a scrub, invalid
> `Content-Range` values and a negative `Content-Length`. The parsers are now strict, a suffix range
> is recognised as a tail probe, and an untranslatable provider range is dropped rather than leaked
> in absolute coordinates.
>
> **#111.** A non-UTC provider zone reformatted the start to the minute. The seconds are now kept
> when the request carried them. A minute-precision request is byte-identical to before, so the
> redirect-mode URL for existing clients does not change.
>
> The `catchup-provider-timezone.spec.ts` pin becomes a passing test.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## PR D-4 — XC VOD info and the category account filter

- **Branch** `fix/D-4-vod-catalogue`
- **Closes** #97, #96.
- **Depends on** B-2 and C-1 merged (same file, other ranges).
- **Files** `apps/output/views.py`, `apps/vod/api_views.py`,
  `apps/output/tests/test_xc_vod_info_detailed.py` (new),
  `apps/vod/tests/test_vod_category_account_filter.py` (new),
  `e2e/tests/seeded/xc-vod-catalogue.spec.ts`, `e2e/tests/seeded/vod-ingest-fidelity.spec.ts`,
  `e2e/COVERAGE.md`, `metrics/curated/defects.yml`.
- **Labels** `apps.output.tests`, `apps.vod.tests` (two; `apps/vod/` routes to both through
  `_PATH_ALIASES`).
- **upstreamable** #97's hunk yes (checked); #96's no (upstream has the fix).
- **Size** S.

### Task 4.1 — #97

1. Re-grep `if movie.custom_properties:` in `apps/output/views.py`: exactly one hit, in
   `xc_get_vod_info`.
2. Write `test_xc_vod_info_detailed.py` (Appendix D.3). Run on the unfixed tree:
   `test_detailed_info_was_dropped_when_the_movie_had_no_custom_properties` fails with
   `AssertionError: 0 != 4321` (measured). `test_movie_custom_properties_still_win_where_they_are_set`
   passes (control).
3. Apply Appendix D.1. Run: 2 pass. The existing `test_xc_vod_info.py` still passes 4 of 4.
4. **Break-check.** Re-insert `if movie.custom_properties:` around the merge. The first test reddens
   with `0 != 4321`. Revert.

### Task 4.2 — #96

1. Write `test_vod_category_account_filter.py` (Appendix D.4). Run on the unfixed tree: it errors
   with `FieldError: Cannot resolve keyword 'm3u_account' into field` (measured).
2. Apply Appendix D.2. Run: passes. Labels measured green: `apps.output.tests` 73,
   `apps.vod.tests` 48.
3. **Break-check.** Add `lookup_expr="gte"` to the fixed filter. The test fails on the name list
   (`['only-a', 'only-b']`), not with a `FieldError`, which shows the assertion checks the scoping
   and not merely the status. Revert. (Do not use a different relation path as the break: a
   relation id can coincide with an account id in a fresh test database and pass by accident.)

### Task 4.3 — the pins, COVERAGE.md and the ledger

| Test | Before | After |
|---|---|---|
| `xc-vod-catalogue.spec.ts` `'XC get_vod_info returns the advanced data the REST API returns (G9 row 20, defect)'` (`:427`) | `test.fail(...)` | `test(...)`; title loses "`, defect`"; assertions unchanged; the explanatory comments inside (`:490-500`) are rewritten to say what is pinned. |
| `vod-ingest-fidelity.spec.ts` `'GET /api/vod/categories/ accepts an m3u_account filter'` (`:285`) | `test.fail(...)` | `test(...)`; assertions unchanged; the comment at `:277-284` rewritten. |

Run both with Global constraint 9's procedure, `<project>` = `seeded`, and both files as `<spec>`
in one command. Before: the first pin fails at `expect(xcInfo.info.bitrate).toBe(restInfo.bitrate)`
(`:510`), after its REST premise `expect(restInfo.bitrate).toBe(4321)` (`:500`) has passed. The
second fails at `expect(res.status()).toBe(200)` (`:306`). After: every test in both
files passes. Rename carefully: the
`test.fail` title is referenced from comments elsewhere in `xc-vod-catalogue.spec.ts` (`:54`,
`:201`); `grep -n "row-20" e2e/tests/seeded/xc-vod-catalogue.spec.ts` and update each reference in
the same commit. Set `e2e/COVERAGE.md` lines 98 and 99 to `done`. Append:

```yaml
- {id: xc-vod-info-detailed-info-gate, title: "xc_get_vod_info gated the relation's detailed_info merge on Movie.custom_properties, so a movie with none lost bitrate, video, audio and the plot override on the XC surface", area: correctness, severity: low, status: fixed, source: null, issue: 97, test: e2e/tests/seeded/xc-vod-catalogue.spec.ts, fixed_in: <this PR>, carried_as: null, first_seen: 2026-08-31, status_changed: <date written>}
- {id: vod-category-account-filter-500, title: "VODCategoryFilter.m3u_account named m3u_account__id, a relation VODCategory does not have, so ?m3u_account= on /api/vod/categories/ was a 500", area: correctness, severity: low, status: fixed, source: null, issue: 96, test: e2e/tests/seeded/vod-ingest-fidelity.spec.ts, fixed_in: <this PR>, carried_as: null, first_seen: 2026-08-30, status_changed: <date written>}
```

### PR description draft

> **fix(output,vod): XC VOD info reads the relation's detailed info; the category account filter works**
>
> Closes #97 and #96.
>
> **#97.** `xc_get_vod_info` merged the relation's `detailed_info` only when `Movie.custom_properties`
> was non-empty. A movie with no custom properties lost `bitrate`, `video`, `audio` and the `plot`
> override on `get_vod_info`, while `/api/vod/movies/<pk>/provider-info/` returned them. Both
> dictionaries are now read unconditionally.
>
> **#96.** `VODCategoryFilter.m3u_account` used `m3u_account__id`, which `VODCategory` does not
> have, so the filter was a 500. It now uses `m3u_relations__m3u_account__id`, as the movie and
> series filters do. Upstream `dev` made the same change.
>
> Two `test.fail()` pins become passing tests.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## Decision memo — #94: advertising catch-up in the generated M3U

**The decision.** Whether, where and in which convention the generated M3U should advertise
catch-up. The pin (`e2e/tests/seeded/catchup-m3u-advertisement.spec.ts:55`) asserts some `catchup`
attribute plus a matching `catchup-days` on the **anonymous native** playlist (`/output/m3u`,
stream URLs `/proxy/ts/stream/<uuid>`). The options below differ on exactly that point.

### What Dispatcharr serves today

- **Two playlist flavours from one function.** `generate_m3u` (`apps/output/views.py`) emits
  `/live/<user>/<pass>/<channel.id>` stream URLs when the request carries XC `username`/`password`
  and resolves a user (`:213-215`, `:310-311`; this is `get.php`), and anonymous-capable
  `/proxy/ts/stream/<uuid>` URLs otherwise (`:252`, `:330`).
- **Two catch-up surfaces.** The XC layouts `/timeshift/<user>/<pass>/<duration>/<start>/<id>[.ts]`
  and `/streaming/timeshift.php?username&password&stream&start&duration` (`dispatcharr/urls.py:71-78`;
  the `.ts` suffix is stripped at `apps/timeshift/views.py:159`), and the native
  `/proxy/catchup/<uuid>?start=&duration=` (`apps/timeshift/urls.py:11`).
- **The native surface cannot be reached from an anonymous playlist.** Catch-up requires a
  principal (`_PRINCIPAL_REQUIRED`, `apps/proxy/authorize.py:82-84`; "Catch-up has never served an
  anonymous request", `:77`). The accepted credentials are a JWT header, an API key header, a
  `?token=` JWT, a session cookie, or a catch-up `session_id` minted by `POST /api/catchup/sessions/`
  (`:93-97`, `:355-365`). None of them is long-lived **and** expressible in a static URL: the query
  JWT expires, and the API key is header-only (`apps/accounts/authentication.py:48-60`). ADR 0005
  rejected signed URLs in playlists (`docs/adr/0005-the-relay-is-chosen-by-name-once-per-tune.md:12-22`).
- **What the timestamps mean.** The catch-up surfaces read the start as **UTC**
  (`apps/timeshift/views.py:116`, `:139`) and convert it to the provider's zone themselves
  (`convert_timestamp_to_provider_tz`). The XC `server_info` Dispatcharr advertises says
  `"timezone": "UTC"` (`apps/output/views.py:386-398`), so XC clients send UTC.
  `normalize_catchup_timestamp_input` accepts `YYYY-MM-DD:HH-MM[-SS]`, the underscore and colon
  forms, ISO-8601 and 10- or 13-digit epoch values (`apps/timeshift/helpers.py:46-95`).
- **What the XC surface already advertises.** `get_live_streams` carries `tv_archive` (0/1) and
  `tv_archive_duration` (days) per channel, from `channel.is_catchup` and `channel.catchup_days`,
  gated by `is_catchup_enabled(user=user)` (`apps/output/views.py:727-732`, `:758`;
  `apps/channels/utils.py:118-133`: the user's `catchup_enabled` flag, then the system setting).
- **What ingest reads.** For an M3U-type account, `tv_archive` and `tv_archive_duration` from the
  `#EXTINF` (`apps/m3u/tasks.py:1391-1397`). It does **not** read `catchup=`, `catchup-days=`,
  `catchup-source=` or `timeshift=`, so the issue body's "reads the attribute family it does not
  write" is not quite right: it reads the XC field names, not the M3U catch-up family.

### Provider-side semantics of the three attributes

As documented by Kodi's IPTV Simple client
([README](https://github.com/kodi-pvr/pvr.iptvsimple), § Catchup and § Catchup format specifiers),
the most complete public reference:

- `catchup="<mode>"`: `default` (the `catchup-source` is the whole URL), `append` (the source is
  appended to the stream URL), `shift` (appends `?utc={utc}&lutc={lutc}`), `flussonic`/`fs`, `xc`
  (the client derives the URL from an Xtream-shaped stream URL), `vod`.
- `catchup-source="<template>"` with specifiers: `{utc}` and `${start}` (programme start, epoch
  seconds), `{utcend}`/`${end}`, `{lutc}`/`${now}`, `{duration}` (seconds) and `{duration:60}`
  (minutes), `{offset:X}`, and `{Y}{m}{d}{H}{M}{S}`.
- `catchup-days="N"`: how many days back the archive reaches. The legacy `timeshift="N"` tag is
  SIPTV's older combined form.

### What each client family expects

| Family | Reads from the M3U | What it builds | Fit with Dispatcharr |
|---|---|---|---|
| **M3U-only players with no catch-up (VLC, most TV-set players)** | Nothing catch-up related | Nothing | No option changes anything for them. |
| **Kodi PVR IPTV Simple** | `catchup`, `catchup-source`, `catchup-days`, `catchup-correction`, legacy `timeshift`/`tvg-rec` | `xc` mode: from a stream URL matching `^(https?://host)/(?:live/)?user/pass/id(.m3u8)?$` it builds `host/timeshift/user/pass/{duration:60}/{Y}-{m}-{d}:{H}-{M}/id.ts` (`src/iptvsimple/data/Channel.cpp`, `GenerateXtreamCodesCatchupSource`). | The shape matches Dispatcharr's PATH route exactly, and Dispatcharr's XC live URL `/live/u/p/<id>` (no extension) matches the regex. **But `{Y}…{M}` are filled from the device's local time** (`CatchupController.cpp`, `FormatDateTime` uses `SafeLocaltime`), while Dispatcharr reads UTC. `xc` mode is therefore wrong by the device's UTC offset unless the device is on UTC or the user sets `catchup-correction`. A `default` source using `{utc}` (epoch, zone-free) has no such error. Also, a playlist requested with `?output_profile=` appends a query string, which the `xc` regex does not match, so catch-up silently disappears there. |
| **TiviMate (M3U playlist)** | `catchup`, `catchup-source`, `catchup-days`; modes default/append/shift/flussonic/xc/vod | As Kodi. TiviMate is closed-source; these facts come from secondary documentation (for example [UniPlayer's M3U reference](https://uniplayer.net/docs/specs/m3u/)) and were not verified against the app. | Same trade-off as Kodi. Whether TiviMate's `xc` mode fills the path from local time or UTC is **unknown**. |
| **XC clients (TiviMate, IPTV Smarters and others in Xtream mode)** | Nothing from the M3U. They read `player_api.php` | `tv_archive`/`tv_archive_duration` per channel, then the XC timeshift URL with the `server_info` zone (UTC here). | **Already served.** Nothing in this memo changes the XC surface. |

### Options

| | Option | What changes | Cost | Pin |
|---|---|---|---|---|
| **A** | **Advertise on the XC-flavoured M3U only, `catchup="xc"` + `catchup-days`** | Two attributes on `#EXTINF` when `is_xc_request`, `channel.is_catchup` and `is_catchup_enabled(user=user)` all hold. | S (one branch, one backend test). Kodi and possibly TiviMate request the wrong hour for every non-UTC device. A `?output_profile=` playlist loses catch-up in Kodi silently. | Moves: the pin must request the XC-flavoured playlist (`/output/m3u?username=&password=`, or `get.php`) and locate the entry by `/live/.../<channel.id>`. That is a test change under rule 5, because the behaviour it pins changes from "every playlist" to "the credentialed playlist". |
| **B** | **Advertise on the XC-flavoured M3U only, `catchup="default"` + an explicit `catchup-source`** | `catchup="default" catchup-days="N" catchup-source="<base>/timeshift/<user>/<pass>/{duration:60}/{utc}/<id>.ts"`, under the same gate as A. `{utc}` is epoch seconds, which `normalize_catchup_timestamp_input` accepts. | S, the same as A. The source repeats the credentials the stream URL already carries. It is correct in every device timezone and independent of `?output_profile=`. | Moves, as in A. The tightened assertion is `catchup === 'default'`, a `catchup-source` containing `{utc}`, and `catchup-days`. |
| **C** | **Also advertise on the anonymous native playlist** | A `catchup-source` pointing at `/proxy/catchup/<uuid>?start={utc}&duration={duration:60}`, plus a way for an anonymous client to be authorized there. | L, and a policy reversal. Either catch-up becomes anonymous by UUID, as live is (reversing `_PRINCIPAL_REQUIRED`), or the playlist embeds a long-lived credential (reversing ADR 0005). Without one of those, the attribute advertises a URL that answers 401. | Stays as written. |
| **D** | **Do not advertise in the M3U** | Document that catch-up is offered to XC clients through `tv_archive`, and to M3U players only through the XC-flavoured playlist's own `/live/` URLs in XC-aware players' own settings. | Nil. Close #94 as not planned. | Deleted, with its premise guard kept as an ordinary test, or the pin rewritten to assert the documented absence. |

### Recommendation

**Option B.** It gives Kodi and TiviMate M3U users working catch-up on the only playlist that can
authorize it. It carries no timezone error, because `{utc}` is zone-free and Dispatcharr already
reads UTC. It changes no security boundary. A is the same size and strictly worse on timezones.
C costs a reversal of two recorded decisions to reach clients that can already use the XC
playlist. D is defensible but leaves a working feature undiscoverable.

**If B is ruled, the implementation is one PR** in `apps/output/views.py:304-307`, after category E's
#80 escaping lands on the same f-string, plus the pin move, a backend test in `apps.output.tests`,
and the COVERAGE.md line 122 update. It should also decide whether `catchup-days` uses
`channel.catchup_days` as the XC surface does (`:729`). Recommended: yes, for parity.

---

## Coverage table

| Issue | Where |
|---|---|
| #64 | PR D-1 |
| #66 | PR D-1 |
| #98 | PR D-1 |
| #99 | PR D-2 |
| #216 | PR D-3 |
| #141 | PR D-3 |
| #111 | PR D-3 |
| #97 | PR D-4 |
| #96 | PR D-4 |
| #94 | Decision memo |

No duplicates in this category. #64 and #141 are the same defect class in unrelated code, and each
survives.

## Open questions for the user

- **Q1 — #94's option** (the memo). The plan recommends B. No PR is planned until you rule.
- **Q2 — #66: cut the body, or answer an honest 200?** When a provider ignores Range and sends the
  whole file, D-1 by default cuts the body to the requested slice and sends a true 206. That keeps
  the existing pin's assertion (the requested bytes) as written. The alternative sends an honest 200
  with the whole file and no `Content-Range`, which RFC 9110 §14.2 permits. It avoids the proxy
  downloading and discarding everything before the seek point, but the pin at
  `vod-range.spec.ts:263` would then have to assert "200 and the whole asset" instead. That is a
  change to what the pin asserts, not a flip, so it needs your ruling. **Default: cut the body.**

## Follow-ups for the lead to file

- **F1.** `e2e/COVERAGE.md` file lines 100, 102 and 124 still read `known-bug` for #100, #110 and #95. #100
  and #95 were fixed by #176, and B-1's plan flips #110's pin without updating line 102. The plan-B
  author may want to add line 102 to B-1's task list.
- **F2.** A provider 4xx or 5xx other than 416 on a VOD request (a 404 for a withdrawn title, for
  example) still becomes a client-facing 500. A 502, or relaying 404 as 404, would be more accurate.
- **F3.** Neither VOD 416 answer carries `Content-Range: bytes */<total>`, which RFC 9110 says a 416
  SHOULD carry. The catch-up path already does (`apps/timeshift/views.py:1445-1448`).
- **F4.** On the catch-up path, a 206 whose provider sent no usable `Content-Range` is now sent
  without one, which is truthful but still non-compliant. A 502 needs its own unwind of the pool
  state written at `apps/timeshift/views.py:3308-3323`.
- **F5.** `is_near_eof_offset` still treats almost all of a 2-4 MiB archive as tail.
- **F6.** `convert_timestamp_to_provider_tz`'s UTC branch sends epoch and ISO inputs to the provider
  verbatim, while the non-UTC branch reshapes them to colon-dash. That is the other half of #111's
  inconsistency, visible in redirect mode.
- **F8.** The same `isdigit()`-then-`int()` hazard already exists at the seed in
  `normalize_catchup_timestamp_input` (`apps/timeshift/helpers.py:70-76`). Measured:
  `parse_catchup_timestamp("²" * 10)` raises `ValueError`, so an authenticated catch-up request with
  `?start=²²²²²²²²²²` is an uncaught error. D-3 does not touch that function. The other `isdigit()`
  at `apps/timeshift/views.py:2525` reads a value Dispatcharr writes itself, not client input.
- **F7.** `TimeshiftDownstreamLengthHeaderTests.test_206_synthesizes_range_when_upstream_omits_it`
  (`apps/timeshift/tests/test_views.py:5430-5439`) pins a `Content-Range` of 9,000 bytes beside a
  `Content-Length` of 1048. That disagreement predates this plan and D-3 leaves it alone.

---

## Appendices

Each appendix is the prototype that ran, spliced from the file that ran. Diffs are against the seed
`a54b09a9`. The implementer re-greps each anchor first, because B-1 and C-4 move lines in two of
these files.

### Appendix A — PR D-1

#### A.1 `apps/proxy/vod_proxy/byte_range.py` (new)

```python
"""Byte-range arithmetic for the VOD proxy (RFC 9110 section 14).

Pure functions, no Django and no Redis, so every rule here is unit-testable
without a session. ``stream_content_with_session`` uses them to decide what
the client is told; the rule they enforce is that the client-facing status,
``Content-Range`` and ``Content-Length`` always describe the bytes actually
sent (#64, #66).
"""

from dataclasses import dataclass
from typing import Iterable, Iterator, Optional, Tuple, Union


class _Unsatisfiable:
    def __repr__(self):
        return "UNSATISFIABLE"


UNSATISFIABLE = _Unsatisfiable()

ResolvedRange = Union[None, _Unsatisfiable, Tuple[int, int]]


def _digits(value: str) -> bool:
    """ASCII digits only. ``str.isdigit()`` is also true for "²" and "³",
    which ``int()`` rejects, and WSGI decodes headers as Latin-1, so a bare
    ``isdigit()`` guard would turn ``Range: bytes=²-`` into a 500."""
    return value.isascii() and value.isdigit()


def parse_length(value) -> Optional[int]:
    """A non-negative integer from a header or stored field, else ``None``."""
    if value is None:
        return None
    text = str(value)
    return int(text) if _digits(text) else None


def resolve_range(range_header: Optional[str], total: int) -> ResolvedRange:
    """Resolve a single ``bytes=`` range against a representation of ``total`` bytes.

    Returns ``(start, end)`` inclusive; ``UNSATISFIABLE`` when the range
    selects no byte of the representation; or ``None`` when the header is
    absent or is not a single byte range this proxy understands, in which
    case the Range is ignored and the whole representation is served (RFC
    9110 section 14.2 permits a server to ignore Range).
    """
    if not range_header or not range_header.startswith("bytes="):
        return None
    spec = range_header[len("bytes="):].strip()
    if "," in spec or "-" not in spec:
        return None
    first, last = spec.split("-", 1)
    if first == "":
        # Suffix form: the final N bytes (#64). bytes=-0 selects nothing.
        if not _digits(last):
            return None
        length = int(last)
        if length == 0 or total <= 0:
            return UNSATISFIABLE
        return max(0, total - length), total - 1
    if not _digits(first):
        return None
    start = int(first)
    if last == "":
        end = total - 1
    elif _digits(last):
        if int(last) < start:
            return UNSATISFIABLE
        end = min(int(last), total - 1)
    else:
        return None
    if start >= total:
        return UNSATISFIABLE
    return start, end


def parse_content_range(value: Optional[str]) -> Optional[Tuple[int, int, Optional[int]]]:
    """Parse ``bytes START-END/TOTAL`` (TOTAL may be ``*``) into a valid triple.

    Returns ``None`` for anything that does not describe a real range:
    missing, the ``bytes */TOTAL`` form, non-numeric, END < START, or
    END >= TOTAL.
    """
    if not value or not value.startswith("bytes "):
        return None
    body = value[len("bytes "):].strip()
    if "/" not in body:
        return None
    span, total_part = body.rsplit("/", 1)
    if "-" not in span:
        return None
    first, last = span.split("-", 1)
    if not (_digits(first) and _digits(last)):
        return None
    if total_part != "*" and not _digits(total_part):
        return None
    start, end = int(first), int(last)
    total = None if total_part == "*" else int(total_part)
    if end < start or (total is not None and end >= total):
        return None
    return start, end, total


@dataclass(frozen=True)
class DownstreamPlan:
    """What the client is told, and how the upstream body is cut to match it."""

    status: int
    content_range: Optional[str] = None
    content_length: Optional[int] = None
    skip: int = 0
    limit: Optional[int] = None
    start: Optional[int] = None
    total: Optional[int] = None
    unsatisfiable: bool = False


def plan_downstream(
    client_range: Optional[str],
    upstream_status: int,
    upstream_content_range: Optional[str],
    upstream_content_length,
    known_total: Optional[int],
) -> DownstreamPlan:
    """Decide the client-facing status and length headers from what the upstream sent.

    - No client Range: 200, the whole representation.
    - Upstream 206 with a valid Content-Range: relay that range verbatim.
    - Upstream 200 to a Range request (Range ignored, #66): cut the body to
      the requested range so the 206 we send is true.
    """
    upstream_length = parse_length(upstream_content_length)
    if not client_range:
        return DownstreamPlan(status=200, content_length=known_total if known_total is not None else upstream_length)

    if upstream_status == 206:
        parsed = parse_content_range(upstream_content_range)
        if parsed is not None:
            start, end, total = parsed
            total = total if total is not None else known_total
            return DownstreamPlan(
                status=206,
                content_range=f"bytes {start}-{end}/{total if total is not None else '*'}",
                content_length=end - start + 1,
                start=start,
                total=total,
            )
        # A 206 with no usable Content-Range: the provider broke the protocol.
        # Describe the range we asked for when the size is known, else say
        # nothing rather than something false.
        resolved = resolve_range(client_range, known_total) if known_total else None
        if isinstance(resolved, tuple):
            start, end = resolved
            return DownstreamPlan(
                status=206,
                content_range=f"bytes {start}-{end}/{known_total}",
                content_length=end - start + 1,
                start=start,
                total=known_total,
            )
        return DownstreamPlan(status=206, content_length=upstream_length)

    if upstream_status == 200:
        total = upstream_length if upstream_length is not None else known_total
        if total is None:
            # Nothing to cut against: pass the whole body through honestly.
            return DownstreamPlan(status=200)
        resolved = resolve_range(client_range, total)
        if resolved is None:
            return DownstreamPlan(status=200, content_length=total)
        if resolved is UNSATISFIABLE:
            return DownstreamPlan(status=416, total=total, unsatisfiable=True)
        start, end = resolved
        return DownstreamPlan(
            status=206,
            content_range=f"bytes {start}-{end}/{total}",
            content_length=end - start + 1,
            skip=start,
            limit=end - start + 1,
            start=start,
            total=total,
        )

    return DownstreamPlan(status=upstream_status, content_length=upstream_length)


def slice_chunks(chunks: Iterable[bytes], skip: int, limit: Optional[int]) -> Iterator[bytes]:
    """Drop the first ``skip`` bytes of ``chunks`` and stop after ``limit`` more."""
    for chunk in chunks:
        if not chunk:
            continue
        if skip:
            if len(chunk) <= skip:
                skip -= len(chunk)
                continue
            chunk = chunk[skip:]
            skip = 0
        if limit is not None:
            if len(chunk) >= limit:
                yield chunk[:limit]
                return
            limit -= len(chunk)
        yield chunk
```

#### A.2 `apps/proxy/vod_proxy/tests/test_byte_range.py` (new)

```python
"""apps/proxy/vod_proxy/byte_range.py: the arithmetic behind #64, #66 and #98."""

from django.test import SimpleTestCase

from apps.proxy.vod_proxy.byte_range import (
    UNSATISFIABLE,
    parse_content_range,
    parse_length,
    plan_downstream,
    resolve_range,
    slice_chunks,
)


class ResolveRangeTests(SimpleTestCase):
    def test_a_suffix_range_was_resolved_as_a_prefix(self):
        # #64: bytes=-500 is the LAST 500 bytes, never bytes=0-500.
        self.assertEqual(resolve_range("bytes=-500", 10_000), (9_500, 9_999))

    def test_a_suffix_longer_than_the_file_is_the_whole_file(self):
        self.assertEqual(resolve_range("bytes=-500", 100), (0, 99))

    def test_a_zero_length_suffix_is_unsatisfiable(self):
        self.assertIs(resolve_range("bytes=-0", 100), UNSATISFIABLE)

    def test_open_and_closed_ranges(self):
        self.assertEqual(resolve_range("bytes=100-", 1000), (100, 999))
        self.assertEqual(resolve_range("bytes=100-199", 1000), (100, 199))
        self.assertEqual(resolve_range("bytes=100-5000", 1000), (100, 999))

    def test_a_start_at_or_past_the_end_is_unsatisfiable(self):
        self.assertIs(resolve_range("bytes=1000-", 1000), UNSATISFIABLE)
        self.assertIs(resolve_range("bytes=99999999-", 1000), UNSATISFIABLE)

    def test_an_inverted_range_is_unsatisfiable(self):
        self.assertIs(resolve_range("bytes=200-100", 1000), UNSATISFIABLE)

    def test_ranges_this_proxy_does_not_understand_are_ignored(self):
        for header in (None, "", "items=0-1", "bytes=0-1,5-9", "bytes=abc-", "bytes=5"):
            with self.subTest(header=header):
                self.assertIsNone(resolve_range(header, 1000))


class NonAsciiDigitTests(SimpleTestCase):
    """"\u00b2".isdigit() is True and int("\u00b2") raises; WSGI decodes headers
    as Latin-1, so a bare isdigit() guard turns these headers into a 500."""

    def test_a_non_ascii_digit_passed_an_isdigit_guard_and_crashed_int(self):
        for header in ("bytes=\u00b2-", "bytes=0-\u00b2", "bytes=-\u00b2"):
            with self.subTest(header=header):
                self.assertIsNone(resolve_range(header, 1000))
        for value in ("bytes \u00b2-5/10", "bytes 0-\u00b3/10", "bytes 0-5/\u00b9"):
            with self.subTest(value=value):
                self.assertIsNone(parse_content_range(value))
        self.assertIsNone(parse_length("\u00b2"))
        # "\u0663" (Arabic-Indic three) is isdecimal() and int() ACCEPTS it, so it
        # does not crash; it is still not the ASCII DIGIT RFC 9110 allows.
        self.assertIsNone(resolve_range("bytes=\u0663-", 1000))
        self.assertIsNone(parse_content_range("bytes \u0663-5/10"))
        self.assertIsNone(plan_downstream(None, 200, None, "\u00b2", None).content_length)


class ParseContentRangeTests(SimpleTestCase):
    def test_valid(self):
        self.assertEqual(parse_content_range("bytes 0-99/1000"), (0, 99, 1000))
        self.assertEqual(parse_content_range("bytes 0-99/*"), (0, 99, None))

    def test_invalid_values_are_refused(self):
        for value in (None, "", "bytes */1000", "bytes 100-50/1000", "bytes 0-1000/1000", "bytes x-1/2"):
            with self.subTest(value=value):
                self.assertIsNone(parse_content_range(value))


class PlanDownstreamTests(SimpleTestCase):
    def test_a_range_ignoring_provider_was_trusted_as_a_206(self):
        # #66: the provider sent the whole file with a 200; cut it.
        plan = plan_downstream("bytes=100-199", 200, None, "1000", 1000)
        self.assertEqual((plan.status, plan.content_range, plan.content_length), (206, "bytes 100-199/1000", 100))
        self.assertEqual((plan.skip, plan.limit), (100, 100))

    def test_a_provider_206_is_relayed_as_sent(self):
        plan = plan_downstream("bytes=-100", 206, "bytes 900-999/1000", "100", None)
        self.assertEqual((plan.status, plan.content_range, plan.content_length, plan.skip), (206, "bytes 900-999/1000", 100, 0))

    def test_an_unsatisfiable_range_against_a_whole_body_is_416(self):
        self.assertTrue(plan_downstream("bytes=5000-", 200, None, "1000", None).unsatisfiable)

    def test_no_client_range_is_a_200(self):
        plan = plan_downstream(None, 200, None, "1000", 1000)
        self.assertEqual((plan.status, plan.content_length, plan.content_range), (200, 1000, None))


class SliceChunksTests(SimpleTestCase):
    def test_slices_across_chunk_boundaries(self):
        data = bytes(range(100))
        chunks = [data[i:i + 7] for i in range(0, 100, 7)]
        self.assertEqual(b"".join(slice_chunks(chunks, 10, 20)), data[10:30])
        self.assertEqual(b"".join(slice_chunks(chunks, 0, None)), data)
        self.assertEqual(b"".join(slice_chunks(chunks, 95, None)), data[95:])
```

#### A.3 `multi_worker_connection_manager.py`

The header block `:1306-1381` is replaced whole; the seek-info bookkeeping inside it is kept, reading `plan.start` and `plan.total` instead of re-parsing the client header. B-1's one-line change at `:1409` is outside every hunk.

```diff
diff --git a/apps/proxy/vod_proxy/multi_worker_connection_manager.py b/apps/proxy/vod_proxy/multi_worker_connection_manager.py
index 04df8ee0..018caf24 100644
--- a/apps/proxy/vod_proxy/multi_worker_connection_manager.py
+++ b/apps/proxy/vod_proxy/multi_worker_connection_manager.py
@@ -13,6 +13,13 @@ from urllib.parse import urlparse
 from typing import Optional, Dict, Any
 from django.http import StreamingHttpResponse, HttpResponse
 from core.utils import RedisClient
+from apps.proxy.vod_proxy.byte_range import (
+    UNSATISFIABLE,
+    parse_length,
+    plan_downstream,
+    resolve_range,
+    slice_chunks,
+)
 from apps.vod.models import Movie, Episode
 from apps.m3u.models import M3UAccountProfile
 from dispatcharr.utils import redact_url
@@ -463,15 +470,18 @@ class RedisBackedVODConnection:
 
             # Prepare headers
             headers = state.headers.copy()
+            known_length = parse_length(state.content_length)
+            if range_header and known_length is not None:
+                # The size is known: resolve the client's Range to absolute
+                # bytes before asking the provider, suffix form included (#64).
+                resolved = resolve_range(range_header, known_length)
+                if resolved is UNSATISFIABLE:
+                    logger.warning(f"[{self.session_id}] Range not satisfiable: {range_header}")
+                    return None
+                range_header = (
+                    f"bytes={resolved[0]}-{resolved[1]}" if resolved is not None else None
+                )
             if range_header:
-                # Validate range against content length if available
-                if state.content_length:
-                    validated_range = self._validate_range_header(range_header, int(state.content_length))
-                    if validated_range is None:
-                        logger.warning(f"[{self.session_id}] Range not satisfiable: {range_header}")
-                        return None
-                    range_header = validated_range
-
                 headers['Range'] = range_header
                 logger.info(f"[{self.session_id}] Setting Range header: {range_header}")
 
@@ -509,6 +519,13 @@ class RedisBackedVODConnection:
                     allow_redirects=True
                 )
 
+            if response.status_code == 416:
+                # The provider says the Range selects nothing. That is the
+                # client's answer, not a server error (#98).
+                logger.warning(f"[{self.session_id}] Provider answered 416 for Range: {range_header}")
+                response.close()
+                return None
+
             response.raise_for_status()
 
             # Update state with response info on first request
@@ -580,44 +597,6 @@ class RedisBackedVODConnection:
             self.cleanup()
             raise
 
-    def _validate_range_header(self, range_header: str, content_length: int):
-        """Validate range header against content length"""
-        try:
-            if not range_header or not range_header.startswith('bytes='):
-                return range_header
-
-            range_part = range_header.replace('bytes=', '')
-            if '-' not in range_part:
-                return range_header
-
-            start_str, end_str = range_part.split('-', 1)
-
-            # Parse start byte
-            if start_str:
-                start_byte = int(start_str)
-                if start_byte >= content_length:
-                    return None  # Not satisfiable
-            else:
-                start_byte = 0
-
-            # Parse end byte
-            if end_str:
-                end_byte = int(end_str)
-                if end_byte >= content_length:
-                    end_byte = content_length - 1
-            else:
-                end_byte = content_length - 1
-
-            # Ensure start <= end
-            if start_byte > end_byte:
-                return None
-
-            return f"bytes={start_byte}-{end_byte}"
-
-        except (ValueError, IndexError) as e:
-            logger.warning(f"[{self.session_id}] Could not validate range header {range_header}: {e}")
-            return range_header
-
     def increment_active_streams(self):
         """Atomically increment active_streams via Redis Lua (no session lock).
 
@@ -1107,16 +1086,37 @@ class MultiWorkerVODConnectionManager:
             # Get stream from Redis-backed connection
             upstream_response = redis_connection.get_stream(range_header)
 
-            if upstream_response is None:
+            def refuse_unsatisfiable():
+                nonlocal profile_connections_incremented
                 logger.warning(f"[{client_id}] Worker {self.worker_id} - Range not satisfiable")
                 if existing_state:
                     # Roll back the active_streams increment from the else branch
                     redis_connection.decrement_active_streams()
+                else:
+                    # A session this request created serves nothing: drop it,
+                    # as the exception path below does (#98).
+                    redis_connection.cleanup(current_worker_id=self.worker_id)
                 if profile_connections_incremented:
                     self._decrement_profile_connections(m3u_profile.id)
                     profile_connections_incremented = False
                 return HttpResponse("Requested Range Not Satisfiable", status=416)
 
+            if upstream_response is None:
+                return refuse_unsatisfiable()
+
+            state = redis_connection._get_connection_state()
+            known_total = parse_length(state.content_length) if state else None
+            plan = plan_downstream(
+                range_header,
+                upstream_response.status_code,
+                upstream_response.headers.get('content-range'),
+                upstream_response.headers.get('content-length'),
+                known_total,
+            )
+            if plan.unsatisfiable:
+                upstream_response.close()
+                return refuse_unsatisfiable()
+
             # Get connection headers
             connection_headers = redis_connection.get_headers()
 
@@ -1153,7 +1153,11 @@ class MultiWorkerVODConnectionManager:
                     # Get the stop signal key for this client
                     stop_key = get_vod_client_stop_key(client_id)
 
-                    for chunk in upstream_response.iter_content(chunk_size=8192):
+                    for chunk in slice_chunks(
+                        upstream_response.iter_content(chunk_size=8192),
+                        plan.skip,
+                        plan.limit,
+                    ):
                         if chunk:
                             yield chunk
                             bytes_sent += len(chunk)
@@ -1303,8 +1307,10 @@ class MultiWorkerVODConnectionManager:
                 content_type=connection_headers.get('content_type', 'video/mp4')
             )
 
-            # Set appropriate status code
-            response.status_code = 206 if range_header else 200
+            # Status and length headers describe the bytes actually sent: the
+            # provider's own range when it honoured the Range, or the slice
+            # cut from its whole body when it ignored it (#64, #66).
+            response.status_code = plan.status
 
             # Set required headers
             response['Cache-Control'] = 'no-cache'
@@ -1315,70 +1321,39 @@ class MultiWorkerVODConnectionManager:
 
             if connection_headers.get('content_length'):
                 response['Accept-Ranges'] = 'bytes'
+            if plan.content_length is not None:
+                response['Content-Length'] = str(plan.content_length)
+            if plan.content_range:
+                response['Content-Range'] = plan.content_range
+                logger.info(f"[{client_id}] Worker {self.worker_id} - Set Content-Range: {plan.content_range}, Content-Length: {plan.content_length}")
+
+            # Store range information for the VOD stats API to calculate position
+            if plan.start and plan.total:
+                start, full_content_size = plan.start, plan.total
+                try:
+                    position_percentage = (start / full_content_size) * 100
+                    current_timestamp = time.time()
 
-                # For range requests, Content-Length should be the partial content size, not full file size
-                if range_header and 'bytes=' in range_header:
-                    try:
-                        range_part = range_header.replace('bytes=', '')
-                        if '-' in range_part:
-                            start_byte, end_byte = range_part.split('-', 1)
-                            start = int(start_byte) if start_byte else 0
-
-                            # Get the FULL content size from the connection state (from initial request)
+                    # Update the Redis connection state with seek information
+                    if redis_connection._acquire_lock():
+                        try:
+                            # Refresh state in case it changed
                             state = redis_connection._get_connection_state()
-                            if state and state.content_length:
-                                full_content_size = int(state.content_length)
-                                end = int(end_byte) if end_byte else full_content_size - 1
-
-                                # Calculate partial content size for Content-Length header
-                                partial_content_size = end - start + 1
-                                response['Content-Length'] = str(partial_content_size)
-
-                                # Content-Range should show full file size per HTTP standards
-                                content_range = f"bytes {start}-{end}/{full_content_size}"
-                                response['Content-Range'] = content_range
-                                logger.info(f"[{client_id}] Worker {self.worker_id} - Set Content-Range: {content_range}, Content-Length: {partial_content_size}")
-
-                                # Store range information for the VOD stats API to calculate position
-                                if start > 0:
-                                    try:
-                                        position_percentage = (start / full_content_size) * 100
-                                        current_timestamp = time.time()
-
-                                        # Update the Redis connection state with seek information
-                                        if redis_connection._acquire_lock():
-                                            try:
-                                                # Refresh state in case it changed
-                                                state = redis_connection._get_connection_state()
-                                                if state:
-                                                    # Store range/seek information for stats API
-                                                    state.last_seek_byte = start
-                                                    state.last_seek_percentage = position_percentage
-                                                    state.total_content_size = full_content_size
-                                                    state.last_seek_timestamp = current_timestamp
-                                                    state.last_activity = current_timestamp
-                                                    redis_connection._save_connection_state(state)
-                                                    logger.info(f"[{client_id}] *** SEEK INFO STORED *** {position_percentage:.1f}% at byte {start:,}/{full_content_size:,} (timestamp: {current_timestamp})")
-                                            finally:
-                                                redis_connection._release_lock()
-                                        else:
-                                            logger.warning(f"[{client_id}] Could not acquire lock to update seek info")
-                                    except Exception as pos_e:
-                                        logger.error(f"[{client_id}] Error storing seek info: {pos_e}")
-                            else:
-                                # Fallback to partial content size if full size not available
-                                partial_size = int(connection_headers['content_length'])
-                                end = int(end_byte) if end_byte else partial_size - 1
-                                content_range = f"bytes {start}-{end}/{partial_size}"
-                                response['Content-Range'] = content_range
-                                response['Content-Length'] = str(end - start + 1)
-                                logger.warning(f"[{client_id}] Using partial content size for Content-Range (full size not available): {content_range}")
-                    except Exception as e:
-                        logger.warning(f"[{client_id}] Worker {self.worker_id} - Could not set Content-Range: {e}")
-                        response['Content-Length'] = connection_headers['content_length']
-                else:
-                    # For non-range requests, use the full content length
-                    response['Content-Length'] = connection_headers['content_length']
+                            if state:
+                                # Store range/seek information for stats API
+                                state.last_seek_byte = start
+                                state.last_seek_percentage = position_percentage
+                                state.total_content_size = full_content_size
+                                state.last_seek_timestamp = current_timestamp
+                                state.last_activity = current_timestamp
+                                redis_connection._save_connection_state(state)
+                                logger.info(f"[{client_id}] *** SEEK INFO STORED *** {position_percentage:.1f}% at byte {start:,}/{full_content_size:,} (timestamp: {current_timestamp})")
+                        finally:
+                            redis_connection._release_lock()
+                    else:
+                        logger.warning(f"[{client_id}] Could not acquire lock to update seek info")
+                except Exception as pos_e:
+                    logger.error(f"[{client_id}] Error storing seek info: {pos_e}")
 
             logger.info(f"[{client_id}] Worker {self.worker_id} - Redis-backed response ready (status: {response.status_code})")
             return response
```

#### A.4 `apps/proxy/vod_proxy/tests/test_vod_range_responses.py` (new)

```python
"""The VOD proxy's Range answers describe the bytes it actually sends.

Each test drives ``stream_content_with_session`` end to end against an
in-memory Redis and a scripted upstream, and names the defect it pins:
#64 (suffix ranges served as prefixes), #66 (a Range-ignoring provider's
head served under a 206 for the slice), #98 (a provider 416 answered 500).
"""

from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase
from requests.structures import CaseInsensitiveDict

from apps.proxy.vod_proxy import multi_worker_connection_manager as mwcm
from apps.proxy.vod_proxy.tests.test_vod_lock_contention import (
    LockAwareFakeRedis,
    _clear_script_cache,
)
from apps.vod.models import Movie

ASSET = bytes(i % 251 for i in range(1000))


class FakeUpstream:
    """A requests.Response stand-in that serves ASSET the way a provider would."""

    def __init__(self, status, body=b"", headers=None):
        self.status_code = status
        self._body = body
        self.headers = CaseInsensitiveDict(headers or {})
        self.url = "http://provider.example/movie/u/p/1.mp4"
        self.closed = False

    def iter_content(self, chunk_size=8192):
        for i in range(0, len(self._body), 97):  # odd chunking exercises the slicer
            yield self._body[i:i + 97]

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code} for url: {self.url}")

    def close(self):
        self.closed = True


def ranged(range_header):
    """What an RFC-compliant provider answers for ``range_header``."""
    from apps.proxy.vod_proxy.byte_range import UNSATISFIABLE, resolve_range

    if not range_header:
        return FakeUpstream(200, ASSET, {"Content-Length": str(len(ASSET))})
    resolved = resolve_range(range_header, len(ASSET))
    if resolved is UNSATISFIABLE:
        return FakeUpstream(416, b"", {"Content-Range": f"bytes */{len(ASSET)}"})
    start, end = resolved
    return FakeUpstream(206, ASSET[start:end + 1], {
        "Content-Range": f"bytes {start}-{end}/{len(ASSET)}",
        "Content-Length": str(end - start + 1),
    })


class VodRangeResponseTests(SimpleTestCase):
    SESSION = "vod_1_1"

    def setUp(self):
        _clear_script_cache()
        self.redis = LockAwareFakeRedis()
        self.sent_ranges = []
        self.answer = ranged  # per-test override
        patches = [
            patch.object(mwcm.MultiWorkerVODConnectionManager, "find_matching_idle_session", return_value=None),
            patch.object(mwcm.MultiWorkerVODConnectionManager, "_check_and_reserve_profile_slot", return_value=True),
            patch.object(mwcm.MultiWorkerVODConnectionManager, "_decrement_profile_connections"),
            patch.object(mwcm.MultiWorkerVODConnectionManager, "_send_vod_event"),
            patch.object(mwcm.requests, "Session", side_effect=self._session),
        ]
        self.mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.decrement_profile = self.mocks[2]
        self.manager = mwcm.MultiWorkerVODConnectionManager.__new__(mwcm.MultiWorkerVODConnectionManager)
        self.manager.redis_client = self.redis
        self.manager.worker_id = "worker-test"
        self.profile = MagicMock(id=7, max_streams=5)
        self.profile.name = "p"
        self.profile.m3u_account.get_user_agent_string.return_value = "ua"
        self.movie = Movie(name="M")

    def _session(self):
        session = MagicMock()

        def get(url, headers=None, **kwargs):
            rng = (headers or {}).get("Range")
            self.sent_ranges.append(rng)
            return self.answer(rng)

        session.get.side_effect = get
        return session

    def _establish(self):
        """A full first request, so the session knows the size (1000)."""
        response = self._get(None)
        self.assertEqual(response.status_code, 200)
        b"".join(response.streaming_content)
        self.sent_ranges.clear()

    def _get(self, range_header):
        request = RequestFactory().get("/proxy/vod/movie/x/" + self.SESSION)
        return self.manager.stream_content_with_session(
            self.SESSION, self.movie, "http://provider.example/movie/u/p/1.mp4",
            self.profile, "1.2.3.4", "agent", request, range_header=range_header,
        )

    # --- #98 ---------------------------------------------------------------

    def test_a_provider_416_on_a_first_request_was_a_500(self):
        response = self._get("bytes=99999999-")
        self.assertEqual(self.sent_ranges, ["bytes=99999999-"])  # the provider was asked
        self.assertEqual(response.status_code, 416)
        self.assertEqual(response.content, b"Requested Range Not Satisfiable")
        self.decrement_profile.assert_called_once_with(7)
        self.assertEqual(self.redis.hgetall(f"vod_persistent_connection:{self.SESSION}"), {})

    def test_an_unsatisfiable_range_on_an_established_session_is_still_416(self):
        self._establish()
        response = self._get("bytes=99999999-")
        self.assertEqual(response.status_code, 416)
        self.assertEqual(self.sent_ranges, [])  # refused before asking the provider

    # --- #64 ---------------------------------------------------------------

    def test_a_suffix_range_on_an_established_session_was_served_as_a_prefix(self):
        self._establish()
        response = self._get("bytes=-100")
        self.assertEqual(self.sent_ranges, ["bytes=900-999"])
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Range"], "bytes 900-999/1000")
        self.assertEqual(response["Content-Length"], "100")
        self.assertEqual(b"".join(response.streaming_content), ASSET[900:])

    def test_a_suffix_range_on_a_first_request_got_a_prefix_content_range(self):
        response = self._get("bytes=-100")
        self.assertEqual(self.sent_ranges, ["bytes=-100"])
        self.assertEqual(response["Content-Range"], "bytes 900-999/1000")
        self.assertEqual(response["Content-Length"], "100")
        self.assertEqual(b"".join(response.streaming_content), ASSET[900:])

    # --- #66 ---------------------------------------------------------------

    def test_a_range_ignoring_provider_had_its_head_served_as_the_requested_slice(self):
        self._establish()
        self.answer = lambda rng: FakeUpstream(200, ASSET, {"Content-Length": "1000"})
        response = self._get("bytes=100-199")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Range"], "bytes 100-199/1000")
        self.assertEqual(response["Content-Length"], "100")
        self.assertEqual(b"".join(response.streaming_content), ASSET[100:200])

    def test_a_range_ignoring_provider_with_no_length_is_served_as_an_honest_200(self):
        self.answer = lambda rng: FakeUpstream(200, ASSET, {})
        response = self._get("bytes=100-199")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Content-Range", response)
        self.assertEqual(b"".join(response.streaming_content), ASSET)

    def test_a_provider_206_is_relayed_with_its_own_content_range(self):
        self._establish()
        response = self._get("bytes=100-199")
        self.assertEqual(self.sent_ranges, ["bytes=100-199"])
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Range"], "bytes 100-199/1000")
        self.assertEqual(b"".join(response.streaming_content), ASSET[100:200])
```

### Appendix B — PR D-2

#### B.1 `apps/proxy/vod_proxy/views.py`

```diff
diff --git a/apps/proxy/vod_proxy/views.py b/apps/proxy/vod_proxy/views.py
index 7596a44e..42a10602 100644
--- a/apps/proxy/vod_proxy/views.py
+++ b/apps/proxy/vod_proxy/views.py
@@ -1465,11 +1465,11 @@ def stream_xc_episode(request, username, password, stream_id, extension):
     # Content resolution stays here on purpose: the hop resolves the
     # principal, not the content object (spec § ORM reads that remain).
     filters = {"episode_id": stream_id, "m3u_account__is_active": True}
-    try:
-        episode_relation = M3UEpisodeRelation.objects.select_related('episode').filter(
-            **filters
-        ).order_by('-m3u_account__priority', 'id').first()
-    except M3UEpisodeRelation.DoesNotExist:
+    episode_relation = M3UEpisodeRelation.objects.select_related('episode').filter(
+        **filters
+    ).order_by('-m3u_account__priority', 'id').first()
+    if not episode_relation:
+        # .first() returns None on no match; it never raises DoesNotExist (#99).
         return JsonResponse({"error": "Episode not found"}, status=404)
 
     return stream_vod(
```

#### B.2 `apps/proxy/vod_proxy/tests/test_xc_episode_not_found.py` (new)

```python
"""stream_xc_episode answers 404 for an unknown episode id, not 500 (#99)."""

from unittest.mock import patch

from django.test import RequestFactory, TestCase

from apps.proxy.authorize import SURFACE_VOD_XC, AuthorizeResult


def _decision():
    return AuthorizeResult(surface=SURFACE_VOD_XC, user_id="", relay_name="py", user=None)


class StreamXcEpisodeNotFoundTests(TestCase):
    @patch("apps.proxy.vod_proxy.views.stream_vod")
    @patch("apps.proxy.vod_proxy.views.resolve_authorization", return_value=_decision())
    def test_an_unknown_episode_id_dereferenced_none_and_was_a_500(self, _auth, stream_vod):
        from apps.proxy.vod_proxy.views import stream_xc_episode

        request = RequestFactory().get("/series/u/p/987654321.mp4")
        response = stream_xc_episode(request, username="u", password="p", stream_id=987654321, extension="mp4")
        self.assertEqual(response.status_code, 404)
        stream_vod.assert_not_called()
```

### Appendix C — PR D-3

#### C.1 `apps/timeshift/stats.py` (#216)

```diff
diff --git a/apps/timeshift/stats.py b/apps/timeshift/stats.py
index caa74009..29a70c5d 100644
--- a/apps/timeshift/stats.py
+++ b/apps/timeshift/stats.py
@@ -20,6 +20,16 @@ logger = logging.getLogger(__name__)
 # Shared with views near-EOF classification (common ~1.88MB duration probes).
 EOF_PROBE_TAIL_BYTES = 2_097_152
 
+
+def is_near_eof_offset(start, total):
+    """True when byte ``start`` of a ``total``-byte archive is in the tail probe window.
+
+    An archive no larger than the window has no tail distinct from its body,
+    so no offset in it is a duration probe: every seek into it is a scrub
+    (#216). Shared by views' busy-pool classification and the stats anchor.
+    """
+    return total > EOF_PROBE_TAIL_BYTES and start >= total - EOF_PROBE_TAIL_BYTES
+
 _STREAM_STATS_TO_METADATA = {
     "video_codec": ChannelMetadataField.VIDEO_CODEC,
     "resolution": ChannelMetadataField.RESOLUTION,
@@ -184,7 +194,7 @@ def resolve_stats_playback_fields(
             start = None
             total = None
         if start is not None and total is not None and total > 0:
-            if start >= max(0, total - EOF_PROBE_TAIL_BYTES):
+            if is_near_eof_offset(start, total):
                 try:
                     keep_base = (
                         float(existing_playback_base)
```

#### C.2 `apps/timeshift/views.py` and `apps/timeshift/helpers.py` (#216's two call-site lines, #141, #111)

Cumulative: the `views.py` diff carries #216's import and call as well as every #141 hunk.

```diff
diff --git a/apps/timeshift/views.py b/apps/timeshift/views.py
index 7562e95c..287d139a 100644
--- a/apps/timeshift/views.py
+++ b/apps/timeshift/views.py
@@ -72,6 +72,7 @@ from .helpers import (
 from .sessions import catchup_session_exists, delete_catchup_session, resolve_catchup_playback
 from .stats import (
     EOF_PROBE_TAIL_BYTES,
+    is_near_eof_offset,
     resolve_stats_playback_fields,
     seed_stream_stats_metadata,
 )
@@ -1108,6 +1109,12 @@ def _parse_range_start(range_header):
     return parsed[0]
 
 
+def _ascii_digits(value):
+    """ASCII digits only: ``str.isdigit()`` also accepts "²", which ``int()``
+    rejects, and WSGI decodes headers as Latin-1 (#141 review)."""
+    return value.isascii() and value.isdigit()
+
+
 def _parse_client_range(range_header):
     """Return ``(start, end)`` from a client Range header; ``end`` may be None."""
     if not range_header or not range_header.startswith("bytes="):
@@ -1116,16 +1123,26 @@ def _parse_client_range(range_header):
     if "-" not in range_part:
         return None
     start_str, end_str = range_part.split("-", 1)
-    try:
-        start = int(start_str) if start_str else 0
-    except (TypeError, ValueError):
+    if not _ascii_digits(start_str):
+        # The suffix form (bytes=-N) has no start; see _is_suffix_range (#141).
         return None
+    start = int(start_str)
     if not end_str:
         return start, None
-    try:
-        return start, int(end_str)
-    except (TypeError, ValueError):
+    if not _ascii_digits(end_str):
         return None
+    end = int(end_str)
+    if end < start:
+        return None  # RFC 9110: an inverted range-spec is invalid (#141).
+    return start, end
+
+
+def _is_suffix_range(range_header):
+    """True for RFC 9110 ``bytes=-N``: the final N bytes, N > 0."""
+    if not range_header or not range_header.startswith("bytes="):
+        return False
+    length = range_header[6:]
+    return length.startswith("-") and _ascii_digits(length[1:]) and int(length[1:]) > 0
 
 
 def _parse_content_range_header(content_range):
@@ -1139,12 +1156,14 @@ def _parse_content_range_header(content_range):
     if "-" not in range_part:
         return None
     start_str, end_str = range_part.split("-", 1)
-    try:
-        start = int(start_str) if start_str else 0
-        end = int(end_str) if end_str else None
-        total = None if total_part == "*" else int(total_part)
-    except (TypeError, ValueError):
+    if not (_ascii_digits(start_str) and _ascii_digits(end_str)):
+        return None
+    if total_part != "*" and not _ascii_digits(total_part):
         return None
+    start, end = int(start_str), int(end_str)
+    total = None if total_part == "*" else int(total_part)
+    if end < start or (total is not None and end >= total):
+        return None  # Not a range any byte could satisfy (#141).
     return {"start": start, "end": end, "total": total}
 
 
@@ -1186,8 +1205,10 @@ def _build_downstream_length_headers(
         representation_length = parsed_upstream.get("total")
 
     if status_code == 206:
-        # Trust upstream partial headers; peek bytes are forwarded verbatim.
-        if upstream_content_range:
+        # Trust upstream partial headers only when they describe a real
+        # range; an invalid one is treated as absent (#141). Peek bytes are
+        # forwarded verbatim.
+        if parsed_upstream:
             headers["Content-Range"] = upstream_content_range
         elif range_header and representation_length is not None:
             client_range = _parse_client_range(range_header)
@@ -1197,12 +1218,13 @@ def _build_downstream_length_headers(
                     end = representation_length - 1
                 else:
                     end = min(end, representation_length - 1)
-                headers["Content-Range"] = (
-                    f"bytes {start}-{end}/{representation_length}"
-                )
+                if start <= end:
+                    headers["Content-Range"] = (
+                        f"bytes {start}-{end}/{representation_length}"
+                    )
         if upstream_content_length:
             headers["Content-Length"] = str(upstream_content_length)
-        elif parsed_upstream and parsed_upstream.get("end") is not None:
+        elif parsed_upstream:
             up_start = parsed_upstream["start"]
             up_end = parsed_upstream["end"]
             headers["Content-Length"] = str(up_end - up_start + 1)
@@ -1229,6 +1251,8 @@ def _build_downstream_length_headers(
 
 def _is_near_eof_probe(range_header, content_length=None):
     """True for tail/duration probes IPTV clients fire during startup."""
+    if _is_suffix_range(range_header):
+        return True  # bytes=-N asks for the tail by definition (#141).
     start = _parse_range_start(range_header)
     if start is None:
         return False
@@ -1238,7 +1262,7 @@ def _is_near_eof_probe(range_header, content_length=None):
         except (TypeError, ValueError):
             total = None
         else:
-            return start >= max(0, total - _EOF_PROBE_TAIL_BYTES)
+            return is_near_eof_offset(start, total)
     return start >= _EOF_PROBE_UNKNOWN_LENGTH_MIN
 
 
@@ -1969,13 +1993,15 @@ def _presentation_relative_content_range(
     ):
         return upstream_content_range
     parsed = _parse_content_range_header(upstream_content_range)
-    if not parsed or parsed.get("end") is None:
-        return upstream_content_range
+    if not parsed:
+        return None
     base = int(presentation_byte_base)
     rel_start = parsed["start"] - base
     rel_end = parsed["end"] - base
-    if rel_start < 0 or rel_end < rel_start:
-        return upstream_content_range
+    if rel_start < 0 or rel_end >= int(presentation_length):
+        # Not expressible in the presented file's coordinates. Never leak the
+        # absolute CDN range beside a presentation-sized length (#141).
+        return None
     return f"bytes {rel_start}-{rel_end}/{int(presentation_length)}"
 
 
diff --git a/apps/timeshift/helpers.py b/apps/timeshift/helpers.py
index 2a9997c0..cd0603f3 100644
--- a/apps/timeshift/helpers.py
+++ b/apps/timeshift/helpers.py
@@ -140,7 +140,8 @@ def convert_timestamp_to_provider_tz(timestamp_str, provider_tz_name):
             (e.g. ``Europe/Brussels``). Falsy, ``UTC``, or unknown: no conversion.
 
     Returns:
-        ``YYYY-MM-DD:HH-MM`` in the provider zone, or the input unchanged on skip/failure.
+        ``YYYY-MM-DD:HH-MM`` in the provider zone (``YYYY-MM-DD:HH-MM-SS`` when
+        the instant has non-zero seconds), or the input unchanged on skip/failure.
     """
     if not provider_tz_name or provider_tz_name == "UTC":
         return timestamp_str
@@ -157,6 +158,12 @@ def convert_timestamp_to_provider_tz(timestamp_str, provider_tz_name):
         return timestamp_str
     # timezone.utc, not ZoneInfo("UTC"): avoids mis-set Docker /etc/timezone.
     local_dt = dt.replace(tzinfo=timezone.utc).astimezone(target)
+    # Keep requested seconds. The UTC branch above returns its input
+    # unchanged, so dropping them here made the precision of the moment asked
+    # for depend on the provider's declared zone (#111). A minute-precision
+    # request keeps its minute shape: redirect mode sends this value verbatim.
+    if local_dt.second:
+        return local_dt.strftime("%Y-%m-%d:%H-%M-%S")
     return local_dt.strftime("%Y-%m-%d:%H-%M")
 
 
```

#### C.3 `apps/timeshift/tests/test_catchup_range_hygiene.py` (new)

```python
"""Catch-up Range and timestamp hygiene: #216, #141 and #111.

Each test is named for the defect it pins. The #141 and #216 inputs are the
shrunk counterexamples from the issue bodies, kept verbatim.
"""

from django.test import SimpleTestCase

from apps.timeshift import views
from apps.timeshift.helpers import (
    build_timeshift_candidate_urls,
    convert_timestamp_to_provider_tz,
)
from apps.timeshift.stats import (
    EOF_PROBE_TAIL_BYTES,
    is_near_eof_offset,
    resolve_stats_playback_fields,
)


class SmallArchiveEofProbeTests(SimpleTestCase):
    """#216: an archive no larger than the tail window has no tail to probe."""

    SMALL = 1_572_864  # 1.5 MiB, from the issue's harness

    def test_a_mid_file_seek_on_a_small_archive_was_classified_as_an_eof_probe(self):
        for start in (512_000, 1_048_576):
            with self.subTest(start=start):
                self.assertFalse(views._is_near_eof_probe(f"bytes={start}-", self.SMALL))
                self.assertTrue(
                    views._should_displace_busy_playback(f"bytes={start}-", self.SMALL, "bytes=0-")
                )

    def test_the_window_boundary(self):
        self.assertFalse(is_near_eof_offset(0, EOF_PROBE_TAIL_BYTES))
        total = EOF_PROBE_TAIL_BYTES + 1
        self.assertFalse(is_near_eof_offset(0, total))
        self.assertTrue(is_near_eof_offset(1, total))

    def test_a_large_archive_tail_is_still_an_eof_probe(self):
        total = 104_857_600
        self.assertTrue(views._is_near_eof_probe(f"bytes={total - 1000}-", total))

    def test_a_small_archive_seek_kept_the_previous_stats_base(self):
        base, _anchor = resolve_stats_playback_fields(
            timestamp_utc="2026-06-08:17-00",
            existing_programme_start="2026-06-08:17-00",
            existing_position_anchor=100.0,
            existing_playback_base="5.0",
            range_start=786_432,
            representation_length=self.SMALL,
            programme_duration_secs=600.0,
            now=200.0,
        )
        self.assertNotEqual(base, 5.0)


class CatchupRangeHeaderTests(SimpleTestCase):
    """#141: no invalid Content-Range and no negative Content-Length."""

    def test_a_suffix_range_was_parsed_as_a_prefix(self):
        self.assertIsNone(views._parse_client_range("bytes=-500"))
        self.assertTrue(views._is_near_eof_probe("bytes=-500", None))

    def test_a_suffix_range_was_widened_through_the_presentation_base(self):
        self.assertEqual(views._map_client_range_through_presentation("bytes=-500", 50), "bytes=-500")

    def test_an_inverted_client_range_was_accepted(self):
        self.assertIsNone(views._parse_client_range("bytes=100-50"))
        headers = views._build_downstream_length_headers(
            range_header="bytes=100-50", status_code=206, representation_length=100,
            upstream_content_range=None, upstream_content_length=None,
        )
        self.assertNotIn("Content-Range", headers)

    def test_a_start_beyond_eof_synthesised_an_inverted_content_range(self):
        headers = views._build_downstream_length_headers(
            range_header="bytes=5000-", status_code=206, representation_length=100,
            upstream_content_range=None, upstream_content_length=None,
        )
        self.assertNotIn("Content-Range", headers)

    def test_an_inverted_upstream_content_range_gave_a_negative_content_length(self):
        self.assertIsNone(views._parse_content_range_header("bytes 100-50/1000"))
        headers = views._build_downstream_length_headers(
            range_header="bytes=0-", status_code=206, representation_length=1000,
            upstream_content_range="bytes 100-50/1000", upstream_content_length=None,
        )
        self.assertNotEqual(headers.get("Content-Range"), "bytes 100-50/1000")
        self.assertFalse(str(headers.get("Content-Length", "0")).startswith("-"))

    def test_an_untranslatable_upstream_range_leaked_absolute_coordinates(self):
        self.assertIsNone(
            views._presentation_relative_content_range(
                "bytes 400-499/1000", presentation_byte_base=500, presentation_length=100,
            )
        )


    def test_a_non_ascii_digit_passed_an_isdigit_guard_and_crashed_int(self):
        # "\u00b2".isdigit() is True and int("\u00b2") raises. The seed's
        # try/except int() returned None for these; the stricter parsers must too.
        for header in ("bytes=\u00b2-", "bytes=0-\u00b2"):
            with self.subTest(header=header):
                self.assertIsNone(views._parse_client_range(header))
        self.assertFalse(views._is_suffix_range("bytes=-\u00b2"))
        # "\u0663" is isdecimal() and int() accepts it (the seed parsed
        # bytes=\u0663- as (3, None)); RFC 9110 allows ASCII DIGIT only.
        self.assertIsNone(views._parse_client_range("bytes=\u0663-"))
        self.assertIsNone(views._parse_content_range_header("bytes \u0663-5/10"))
        self.assertFalse(views._is_near_eof_probe("bytes=-\u00b2", None))
        for value in ("bytes \u00b2-5/10", "bytes 0-\u00b3/10", "bytes 0-5/\u00b9"):
            with self.subTest(value=value):
                self.assertIsNone(views._parse_content_range_header(value))


class ProviderTimezoneSecondsTests(SimpleTestCase):
    """#111: a non-UTC provider zone must not drop the requested seconds."""

    def test_a_non_utc_provider_zone_truncated_the_start_to_the_minute(self):
        self.assertEqual(
            convert_timestamp_to_provider_tz("2026-01-15:12-00-45", "Europe/Brussels"),
            "2026-01-15:13-00-45",
        )

    def test_the_colon_seconds_candidate_keeps_the_seconds_in_every_zone(self):
        from types import SimpleNamespace

        creds = SimpleNamespace(server_url="http://p.example", username="u", password="p")
        for zone, expected in (("UTC", "2026-01-15:12:00:45"), ("Europe/Brussels", "2026-01-15:13:00:45")):
            with self.subTest(zone=zone):
                ts = convert_timestamp_to_provider_tz("2026-01-15:12-00-45", zone)
                self.assertIn(f"/{expected}/", build_timeshift_candidate_urls(creds, "1", ts, 60)[2])

    def test_a_minute_precision_start_keeps_its_minute_shape(self):
        # The redirect URL is built from this value verbatim; a request with
        # no seconds must not grow a ":00" it never asked for.
        self.assertEqual(
            convert_timestamp_to_provider_tz("2026-01-15:12-00", "Europe/Brussels"),
            "2026-01-15:13-00",
        )
```

### Appendix D — PR D-4

#### D.1 `apps/output/views.py` (#97)

```diff
diff --git a/apps/output/views.py b/apps/output/views.py
index ff0bfed4..1e36ad6f 100644
--- a/apps/output/views.py
+++ b/apps/output/views.py
@@ -1671,37 +1671,36 @@ def xc_get_vod_info(request, user, vod_id):
             movie.refresh_from_db()
             movie_relation.refresh_from_db()
 
-        # Add detailed info from custom_properties if available
-        if movie.custom_properties:
-            custom_data = movie.custom_properties or {}
-
-            # Extract detailed info
-            #detailed_info = custom_data.get('detailed_info', {})
-            detailed_info = movie_relation.custom_properties.get('detailed_info', {})
-            # Update movie_data with detailed info
-            movie_data.update({
-                'director': custom_data.get('director') or detailed_info.get('director', ''),
-                'actors': custom_data.get('actors') or detailed_info.get('actors', ''),
-                'country': custom_data.get('country') or detailed_info.get('country', ''),
-                'release_date': custom_data.get('release_date') or detailed_info.get('release_date') or detailed_info.get('releasedate', ''),
-                'youtube_trailer': custom_data.get('youtube_trailer') or detailed_info.get('youtube_trailer') or detailed_info.get('trailer', ''),
-                'backdrop_path': custom_data.get('backdrop_path') or detailed_info.get('backdrop_path', []),
-                'cover_big': detailed_info.get('cover_big', ''),
-                'bitrate': detailed_info.get('bitrate', 0),
-                'video': detailed_info.get('video', {}),
-                'audio': detailed_info.get('audio', {}),
-            })
+        # Movie.custom_properties carries director/actors/trailer/backdrop;
+        # the relation's detailed_info carries bitrate/video/audio/plot. Read
+        # both unconditionally: gating on the movie's dict dropped the
+        # relation's data whenever the movie had none (#97).
+        custom_data = movie.custom_properties or {}
+        detailed_info = (movie_relation.custom_properties or {}).get('detailed_info', {})
+        # Update movie_data with detailed info
+        movie_data.update({
+            'director': custom_data.get('director') or detailed_info.get('director', ''),
+            'actors': custom_data.get('actors') or detailed_info.get('actors', ''),
+            'country': custom_data.get('country') or detailed_info.get('country', ''),
+            'release_date': custom_data.get('release_date') or detailed_info.get('release_date') or detailed_info.get('releasedate', ''),
+            'youtube_trailer': custom_data.get('youtube_trailer') or detailed_info.get('youtube_trailer') or detailed_info.get('trailer', ''),
+            'backdrop_path': custom_data.get('backdrop_path') or detailed_info.get('backdrop_path', []),
+            'cover_big': detailed_info.get('cover_big', ''),
+            'bitrate': detailed_info.get('bitrate', 0),
+            'video': detailed_info.get('video', {}),
+            'audio': detailed_info.get('audio', {}),
+        })
 
-            # Override with detailed_info values where available
-            for key in ['name', 'description', 'year', 'genre', 'rating', 'tmdb_id', 'imdb_id']:
-                if detailed_info.get(key):
-                    movie_data[key] = detailed_info[key]
+        # Override with detailed_info values where available
+        for key in ['name', 'description', 'year', 'genre', 'rating', 'tmdb_id', 'imdb_id']:
+            if detailed_info.get(key):
+                movie_data[key] = detailed_info[key]
 
-            # Handle plot vs description
-            if detailed_info.get('plot'):
-                movie_data['description'] = detailed_info['plot']
-            elif detailed_info.get('description'):
-                movie_data['description'] = detailed_info['description']
+        # Handle plot vs description
+        if detailed_info.get('plot'):
+            movie_data['description'] = detailed_info['plot']
+        elif detailed_info.get('description'):
+            movie_data['description'] = detailed_info['description']
 
     except Exception as e:
         logger.error(f"Failed to process movie data: {e}")
```

#### D.2 `apps/vod/api_views.py` (#96)

```diff
diff --git a/apps/vod/api_views.py b/apps/vod/api_views.py
index b0a8a5a6..ea3f3c0f 100644
--- a/apps/vod/api_views.py
+++ b/apps/vod/api_views.py
@@ -621,7 +621,7 @@ class SeriesViewSet(viewsets.ReadOnlyModelViewSet):
 class VODCategoryFilter(django_filters.FilterSet):
     name = django_filters.CharFilter(lookup_expr="icontains")
     category_type = django_filters.ChoiceFilter(choices=VODCategory.CATEGORY_TYPE_CHOICES)
-    m3u_account = django_filters.NumberFilter(field_name="m3u_account__id")
+    m3u_account = django_filters.NumberFilter(field_name="m3u_relations__m3u_account__id")
 
     class Meta:
         model = VODCategory
```

#### D.3 `apps/output/tests/test_xc_vod_info_detailed.py` (new)

```python
"""xc_get_vod_info merges the relation's detailed_info whatever Movie.custom_properties holds (#97)."""

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.m3u.models import M3UAccount
from apps.output.views import xc_get_vod_info
from apps.vod.models import M3UMovieRelation, Movie

User = get_user_model()

SPARSE = {"bitrate": 4321, "video": {"codec_name": "h264"}, "audio": {"codec_name": "aac"}, "plot": "From the provider."}


class XcGetVodInfoDetailedInfoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="xcvoddetail", password="x")
        self.user.user_level = 10
        self.user.save()
        account = M3UAccount.objects.create(
            name="P", server_url="http://p.example", username="u", password="p",
            account_type=M3UAccount.Types.XC, is_active=True, custom_properties={"enable_vod": True},
        )
        # Movie.custom_properties is None: set explicitly, never inherited from a default.
        self.movie = Movie.objects.create(name="Sparse", year=2020, custom_properties=None)
        M3UMovieRelation.objects.create(
            m3u_account=account, movie=self.movie, stream_id="s-1",
            last_advanced_refresh=timezone.now(),
            custom_properties={"detailed_fetched": True, "detailed_info": SPARSE},
        )

    def _info(self):
        return xc_get_vod_info(RequestFactory().get("/player_api.php"), self.user, str(self.movie.id))["info"]

    def test_detailed_info_was_dropped_when_the_movie_had_no_custom_properties(self):
        info = self._info()
        self.assertEqual(info["bitrate"], 4321)
        self.assertEqual(info["video"], {"codec_name": "h264"})
        self.assertEqual(info["audio"], {"codec_name": "aac"})
        self.assertEqual(info["plot"], "From the provider.")

    def test_movie_custom_properties_still_win_where_they_are_set(self):
        self.movie.custom_properties = {"director": "Movie Director"}
        self.movie.save(update_fields=["custom_properties"])
        self.assertEqual(self._info()["director"], "Movie Director")
```

#### D.4 `apps/vod/tests/test_vod_category_account_filter.py` (new)

```python
"""GET /api/vod/categories/?m3u_account=<id> filters by account (#96)."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.m3u.models import M3UAccount
from apps.vod.models import M3UVODCategoryRelation, VODCategory

User = get_user_model()


class VodCategoryAccountFilterTests(TestCase):
    def setUp(self):
        admin = User.objects.create_user(username="vodcatadmin", password="x")
        admin.user_level = 10
        admin.save()
        self.client = APIClient()
        self.client.force_authenticate(user=admin)
        self.a = M3UAccount.objects.create(name="A", server_url="http://a.example", account_type=M3UAccount.Types.XC, is_active=True)
        self.b = M3UAccount.objects.create(name="B", server_url="http://b.example", account_type=M3UAccount.Types.XC, is_active=True)
        self.cat_a = VODCategory.objects.create(name="only-a", category_type="movie")
        self.cat_b = VODCategory.objects.create(name="only-b", category_type="movie")
        M3UVODCategoryRelation.objects.create(m3u_account=self.a, category=self.cat_a)
        M3UVODCategoryRelation.objects.create(m3u_account=self.b, category=self.cat_b)

    def test_the_m3u_account_filter_named_a_relation_vodcategory_does_not_have(self):
        res = self.client.get("/api/vod/categories/", {"m3u_account": self.a.id})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        names = [c["name"] for c in (body["results"] if isinstance(body, dict) else body)]
        self.assertEqual(names, ["only-a"])
```
