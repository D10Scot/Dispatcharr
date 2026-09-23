# Fix plan, category B — security and credential handling

**Category.** B, security and credential handling. Thirteen tracker issues: #89, #182, #61, #110,
#84, #82, #83, #134, #103, #104, #105, #204, #205.

**Seed SHA.** `a54b09a9` (`main`, 2026-09-23, "metrics(curated): the Phase 2 phase-done milestone
row (#342)"). Every `file:line` below was opened at that SHA. Line numbers drift; each task's
first step re-greps its anchor rather than trusting the number.

**Ordering position.** First of ten (B, A, J, C, D, E, G, H, I, F). Nothing precedes this plan.
Every later category that shares a file with it re-seeds on the merge of the B PR that touches that
file (§ Overlap).

**Shape.** Seven PRs. #82 was a policy item under the brief's rule 4; the maintainer closed it as
not planned on 2026-09-23 (a design decision), so it gets no memo and no PR. #182 is planned in full as PR B-7 but is **gated on Open question
Q1**, because its fix reverses a default the upstream project chose deliberately.

**Nothing in this plan is implemented.** The only file this branch commits is this document.

---

## Files this plan touches

| File | PRs | Issues |
|---|---|---|
| `apps/proxy/vod_proxy/views.py` | B-1 | #89, #110 |
| `apps/proxy/vod_proxy/multi_worker_connection_manager.py` | B-1 | #89 |
| `apps/proxy/vod_proxy/tests/test_vod_error_bodies.py` (new) | B-1 | #89 |
| `apps/proxy/vod_proxy/tests/test_vod_adult_filter.py` (new) | B-1 | #110 |
| `e2e/tests/streaming/vod-adult-streamable.spec.ts` | B-1 | #110 (pin flip) |
| `apps/output/views.py` (lines 357–560 only) | B-2 | #84, #134 |
| `apps/output/tests/test_xc_auth.py` (new) | B-2 | #84, #134 |
| `e2e/tests/seeded/xc-auth.spec.ts` | B-2 | #84 (pin flip) |
| `e2e/tests/seeded/network-acl.spec.ts` | B-2, B-7 | #134 (pin flip); #182 (comments only) |
| `apps/hdhr/api_views.py` (lines 205–233 only) | B-3 | #83 |
| `apps/output/tests/test_hdhr_device_xml.py` (new) | B-3 | #83 |
| `e2e/tests/seeded/hdhr.spec.ts` (comment only) | B-3 | #83 |
| `core/http_security.py` | B-4 | #103, #104, #105 |
| `core/tests/test_http_security.py` | B-4 | #103, #104, #105 |
| `apps/plugins/api_views.py` (lines 777–780, 1149, 1267) | B-4 | #103, #104, #105 |
| `apps/plugins/tests/test_plugin_fetch_redirects.py` (new) | B-4 | #103, #104, #105 |
| `apps/m3u/tasks.py` (lines 942–945 only) | B-5 | #61 |
| `apps/proxy/next_source.py` (line 63 only) | B-5 | #61 |
| `apps/m3u/tests/test_xc_live_url.py` | B-5 | #61 |
| `frontend/src/utils/securePassword.js` (new) | B-6 | #204, #205 |
| `frontend/src/utils/__tests__/securePassword.test.js` (new) | B-6 | #204, #205 |
| `frontend/src/components/forms/User.jsx` (lines 77, 109) | B-6 | #204, #205 |
| `frontend/src/components/forms/__tests__/User.test.jsx` | B-6 | #204, #205 |
| `dispatcharr/utils.py` (lines 298–338 only) | B-7 | #182 |
| `core/tests/test_core.py` (`GetClientIpTests`) | B-7 | #182 |
| `scripts/e2e_up.sh` | B-7 | #182 |
| `README.md` (line 109) | B-7 | #182 |
| `docker/docker-compose{,.aio,.dev,.debug}.yml` (comment blocks only) | B-7 | #182 |
| `e2e/README.md`, `e2e/COVERAGE.md` (the X-Real-IP paragraphs) | B-7 | #182 |
| `metrics/curated/defects.yml` | B-1, B-2, B-3 | #84, #110, #134, #82 (title only) |
| `CLAUDE.md` (one sentence in § Known defects, Security) | B-2 | #84 |

## Overlap with later categories

Every file above that also appears in another category's evidence in `sweep-report.md`. **B goes
first in every case.** The later plan re-seeds on B's merge and rebases over B's hunk; none of the
B hunks below edits a line another category's fix needs to change.

| File | Other category and issue | What B does there | What the other plan is assumed to do | Collision risk |
|---|---|---|---|---|
| `apps/proxy/vod_proxy/multi_worker_connection_manager.py` | **D** #98 (`:512` `raise_for_status`, the `:1386` handler, `:1409`), #64 (`:593-601`), #66 (`:1307`, `:1337-1339`, `:1156`) | B-1 changes **only the return statement at `:1409`** (the body string). It does not touch the `except` clause, the rollback block above it or `:512`. | D-#98 adds a narrower arm ahead of the broad `except Exception` (an upstream 416 becomes a 416, not a 500). That arm must answer a **fixed** body too. D rebases over B's one-line change at `:1409`; the conflict is at most adjacent context. | Low. Adjacent lines, no shared edit. |
| `apps/proxy/vod_proxy/views.py` | **D** #99 (`stream_xc_episode`, `:1468-1478`); **C** #171 (`_transform_url`, `:603`) | B-1 changes `stream_vod`'s final `except` (`:860-862`), `head_vod`'s final `except` (`:1075-1077`), adds a helper near `_content_type_for_obj` (`:61`), and adds refusals inside `stream_vod`'s two `selected` branches and in `stream_xc_movie` (`:1428-1438`). **B does not touch `stream_xc_episode`** (see #110 below: `Episode` has no `is_adult` field) and does not touch `_transform_url`. | D fixes the dead `DoesNotExist` guard in `stream_xc_episode`; C fixes the `$0` backreference in `_transform_url`. | Low. Different functions. |
| `apps/output/views.py` | **C** #91 (`:881`, `:921`, `:933`; #212 was closed as its duplicate); **D** #97 (`:1675-1680`), #94 (`:305`, `:727`); **E** #80 (`:305-306`), #85 (`:593`) | B-2 changes `xc_get_user` and the four XC views, **lines 357–560 only**, plus one import line. | Each fixes its own line range, all outside 357–560. | None beyond the import block, if another plan also adds an import. |
| `apps/m3u/tasks.py` | **C** #171 (`:3097`, inside `get_transformed_credentials`) | B-5 changes `:942-945` only. | C rewrites the backreference translation at `:3097`. | None. |
| `apps/proxy/next_source.py` | **C** #171 (`transform_url`, `:285`) | B-5 changes `:63` only. | C changes `:285`. | None. Both PRs touch a Gate 2 module and both must run the isolated coverage script. |
| `docker/nginx.conf` | **G** #81 (`:69-74`, forwarded headers on `uwsgi_pass`) | **B touches no nginx file.** B-7 changes which peers Django trusts, not what nginx sends. | G adds `uwsgi_param HTTP_X_FORWARDED_{HOST,PROTO,PORT}` for `core/utils.py`'s `get_host_and_port`. **G must not add `uwsgi_param HTTP_X_REAL_IP` or `HTTP_X_FORWARDED_FOR` expecting `get_client_ip` to honour them**: under B-7 the peer on a `uwsgi_pass` location is the client itself and is not trusted, so those headers are ignored. That is correct, and G's plan should say so rather than discover it. | None textually. A semantic dependency, recorded for G. |
| `e2e/tests/seeded/network-acl.spec.ts` | none in another category | B-2 flips the #134 pin. B-7 edits comments only. | — | B-2 and B-7 both edit it. B-2 lands first. |

The reviewer note on #182 says "Open #81 is the nginx half of the same problem; fix together." This
plan disagrees and keeps them apart. #81 is about `X-Forwarded-Host/Proto/Port` reaching
`get_host_and_port` (`core/utils.py:1012`) for URL building. #182 is about which peer's
`X-Real-IP`/`X-Forwarded-For` `get_client_ip` believes. The two share nginx's directive-family
mistake as a cause but have different readers and different fixes. Adding `uwsgi_param
HTTP_X_REAL_IP $remote_addr` would *break* the Traefik-style deployments B-7's escape hatch exists
for, because `$remote_addr` there is the outer proxy, not the client.

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
5. **A break-check is not optional.** Each task that adds a test names a deliberate wrong edit to the
   fix. The implementer applies it, runs the one test, **records the failure message and confirms it
   names the mechanism** (not a side effect of the edit), then reverts it.
6. **Backend runs use your own container**, never the shared `dispatcharr-testrunner`:
   `DISPATCHARR_TEST_CONTAINER=fixplan-B-<n> DISPATCHARR_TEST_DB_VOLUME=fixplan-B-<n>-db
   CLAUDE_HOOK_REPO_ROOT=<your worktree> <repo>/.claude/hooks/start-test-container.sh`. The
   `PostToolUse` hook still uses the shared container whatever you export. Re-point it at your tree
   or ignore its result and run the label yourself. If Docker is down, say the tests did not run.
7. **One fixed, generic body for every refusal or error that reaches an unauthenticated client.**
   Never interpolate an exception, a URL or a request value into a response body on these surfaces.
8. **Run each PR's labels once without `--keepdb`** before pushing (memory: keepdb hides seeded-row
   drift).

---

## Per-issue analysis

### #89 — provider credentials in a VOD 500 body

- **Root cause.** Two `AllowAny`, relay-served paths return the caught exception's text to the
  client. At `apps/proxy/vod_proxy/views.py:862`, `stream_vod`'s broad `except Exception as e`
  answers `HttpResponse(f"Streaming error: {str(e)}", status=500)`. At
  `apps/proxy/vod_proxy/multi_worker_connection_manager.py:1409`, `stream_content_with_session`
  answers the same string. A `requests` connection or HTTP error names the upstream URL, and an XC
  VOD URL carries `/movie/<user>/<pass>/<id>.<ext>`. Entry points are `stream_vod` (`views.py:616-619`),
  `stream_xc_movie` (`:1408-1410`) and `stream_xc_episode` (`:1445-1447`). A third instance of the
  same shape sits at `views.py:1077` (`head_vod`, `HEAD error: {str(e)}`). `head_vod` has no route
  today (CLAUDE.md § Dead or unwired) but is still callable and is fixed in the same hunk, because
  the issue asks for "any path that interpolates an exception string into a response body" in the
  VOD proxy.
- **Fix.** Replace each body with a fixed string (`"Streaming error"`, `"HEAD error"`). The existing
  `logger.error(..., exc_info=True)` beside each keeps the detail server-side. No other line in the
  handlers changes.
- **Tests.** New `apps/proxy/vod_proxy/tests/test_vod_error_bodies.py` with three tests, one per site.
  No existing test changes.
- **Size** S. **Upstreamable** yes, for this hunk alone.
- **Duplicates.** #186 (INVALID in the sweep; its subject `live_proxy/views.py` is deleted). The
  reviewer found its one surviving instance is `views.py:862`, which is this issue. **#89 survives;
  #186 is closed as superseded by #89.** That is the lead's tracker action.
- **Not in scope, filed as a follow-up.** The same three `logger.error(f"... {e}")` calls write the
  unredacted exception text, and so the provider URL, to the log at ERROR. `scripts/check_credential_logging.py`
  cannot see them, because the variable is named `e`. That is the #295 shape (credentials in logs),
  not a response body. It needs an exception-text redaction helper that does not exist yet, so it
  is a separate issue for the lead to file.

### #110 — a movie hidden by `hide_adult_content` is still streamable

- **Root cause.** `authorize_stream` applies `is_adult` to channels only
  (`apps/proxy/authorize.py:433-436`). The VOD surfaces resolve content in the view, after the hop,
  and never consult it: `stream_vod` (`apps/proxy/vod_proxy/views.py:619`) and `stream_xc_movie`
  (`:1410`). The listings do filter it: `xc_get_vod_streams` (`apps/output/views.py:1198`) and
  `xc_get_vod_info` (`:1624`), both gated on `user.user_level < 10` and the user's
  `hide_adult_content`.
- **Correction to the issue.** The title names `stream_xc_episode` too. **Only `Movie` has an
  `is_adult` field** (`apps/vod/models.py:129`). `Series` (`:76`) and `Episode` (`:159`) have none,
  and no listing filters episodes or series by adult content. An episode is therefore not
  "unlistable yet streamable". Nothing about episodes changes, and B-1 does not touch
  `stream_xc_episode`, which D-#99 edits.
- **Fix.** One helper in `vod_proxy/views.py`, `_hidden_adult_movie(user, content_type, content_obj)`,
  true when the content is a `Movie` with `is_adult`, the user is non-admin, and the user's
  `custom_properties.hide_adult_content` is set. It mirrors the listing predicate exactly. It is
  called in four places, each answering `authorize_error_response(AuthorizeDenied(403, "Forbidden"))`:
  (1) `stream_xc_movie`, right after the relation resolves, so an XC client is refused before a
  session is minted; (2) `stream_vod`'s Redirect branch, after its `if not selected:` block (`:760-766`); (3) `stream_vod`'s
  session branch, after its `if not selected:` block (`:812-818`), where `user` may have come from the Redis session
  mapping (`:783-793`); (4) `stream_vod`'s first request, before the `if not session_id:` block at
  `:724`, by UUID. Call (4) exists because of an adopted idle session. In Redirect mode `:742-749`
  answers 301 to an *existing* session. On the follow-up request, `:783-793` reads
  `vod_session_user` only when `vod_persistent_connection:{session_id}` does not yet exist. For an
  adopted session the key exists, so `user` stays `None` and call (3) cannot refuse. That happens,
  for example, with two accounts on one device, sharing an IP and a user agent. Call (4) runs when
  `content_type == "movie"` and `user` is set, and reads
  `Movie.objects.filter(uuid=content_id).only("is_adult").first()`. Calls (2) and (3) stay, because
  they check the resolved object and so cover the stream-id fallback. Selection reserves no slot (`_select_vod_stream` and `_get_m3u_profile` only
  read counters), so refusing after selection leaks nothing. The proxy-mode first request mints a
  session and redirects without resolving content (`:774-778`). Call (4) refuses that first request
  for a known UUID, and call (3) refuses the follow-up. The check is on the resolved object, not the UUID, so the stream-id fallback in
  `_get_content_and_relation` (`:236-274`) cannot route around it.
- **Tests.** New `apps/proxy/vod_proxy/tests/test_vod_adult_filter.py`. The e2e pin in
  `e2e/tests/streaming/vod-adult-streamable.spec.ts:121` flips.
- **Size** S. **Upstreamable** no. It uses `apps/proxy/authorize.py`, which is fork-only.
- **Duplicates.** None. It is the VOD analogue of #87, which is closed.

### #84 — `player_api.php` tells an unknown user from a wrong password

- **Root cause.** `xc_get_user` (`apps/output/views.py:357-377`) calls
  `get_object_or_404(User, username=username)` at `:364`. An unknown username escapes as `Http404`,
  which Django answers 404. A wrong password returns `None` (`:371-372`), which each caller answers
  401. The same helper backs `player_api.php`, `panel_api.php`, `get.php` and `xmltv.php`. It also
  compares with `!=` (`:371`), where every streaming surface has used `hmac.compare_digest` since
  Phase 1 PR 5.
- **Fix.** `xc_get_user` delegates the credential check to `apps.proxy.authorize.resolve_xc_user`
  (`apps/proxy/authorize.py:150-176`). That function already returns `None` for an unknown user, a
  missing `xc_password` or a wrong one, and compares bytes in constant time. This removes the last
  `!=` comparison of an XC password in the tree. It adds one statement to
  `reverse_imports_into_proxy` (28 to 29; `apps/output/views.py` already imports `apps.proxy.utils`,
  so no new edge). That is the cost of one implementation instead of two, and the PR description
  says so.
- **Tests.** New `apps/output/tests/test_xc_auth.py`. The e2e pin at
  `e2e/tests/seeded/xc-auth.spec.ts:145` flips. Ledger row `xc-account-enumeration` moves
  `pinned` to `fixed`.
- **Size** S. **Upstreamable** no (`resolve_xc_user` is fork-only).
- **Duplicates.** None. #134 is a different branch of the same function and ships in the same PR.

### #134 — a network-blocked XC user gets 401 and no event

- **Root cause.** `xc_get_user` returns `None` when `network_access_allowed(request, 'XC_API', user)`
  fails (`apps/output/views.py:374-375`), the same value it returns for bad credentials. Every caller
  maps `None` to 401 (`:406-407`, `:453-454`, `:489-490`, `:513-525`, `:547-559`). `get.php` and
  `xmltv.php` also run a global, user-less ACL check first (`:494-507`, `:529-541`), which is the only
  403 on the surface. `player_api.php` and `panel_api.php` have no such check and call
  `log_system_event` on no path at all. The issue's comparison with the Python `stream_xc` no longer
  applies; that code was deleted at stage 2d-4.
- **Fix.** Split the two outcomes. A new `xc_authenticate(request)` returns `(user, status)`, with
  `status` one of `None`, `401` or `403`. `xc_get_user` stays as a thin wrapper returning the user or
  `None`, because `xc_get_info` (`:403`) calls it internally after its caller has already
  authenticated. The four views call `xc_authenticate` and answer `403 {"error": "Forbidden"}` for a
  network refusal and `401 {"error": "Unauthorized"}` for bad credentials. `player_api.php` and
  `panel_api.php` gain the same global pre-check `get.php` has, so all four endpoints give the same
  status for the same cause. The two that logged nothing now log a network refusal with
  `event_type='login_failed'`, `reason='Network access denied (XC API)'`, and an `endpoint` detail.
  `login_failed` is an existing event type (`core/models.py:807`, `apps/connect/models.py:17`), so no
  migration is needed. A new event type would change `EVENT_TYPES` choices and need one.
  `get.php` and `xmltv.php` keep their existing `m3u_blocked`/`epg_blocked` events and gain the
  per-user 403.
- **Assumption.** Credential failures on `player_api.php`/`panel_api.php` still log nothing. The issue
  asks for the network-denial event. Logging every wrong password on the handshake endpoint every XC
  client polls is a volume decision this plan does not take.
- **Tests.** In `apps/output/tests/test_xc_auth.py`. The e2e pin at
  `e2e/tests/seeded/network-acl.spec.ts:375` flips. New ledger row.
- **Size** S. **Upstreamable** no (it ships with #84's fork-only import).
- **Duplicates.** None.

### #83 — `device.xml` ignores a configured `HDHRDevice` row

- **Root cause.** `HDHRDeviceXMLAPIView.get` (`apps/hdhr/api_views.py:215-233`) hardcodes
  `<DeviceID>12345678</DeviceID>` and `<FriendlyName>Dispatcharr HDHomeRun</FriendlyName>` at
  `:224-225`. `DiscoverAPIView.get` reads `HDHRDevice.objects.first()` at `:67` and prefers its
  fields when a row exists (`:86-97`).
- **Fix.** `device.xml` reads the same row and uses the same two fields, falling back to the same
  literals. `device.xml` has no profile-scoped route (`apps/hdhr/urls.py`), so only discover's
  no-slug fallback applies. Both values are XML-escaped with `xml.sax.saxutils.escape`, because
  `friendly_name` is admin-editable text going into an XML body. Today's literals need no escaping,
  so the fallback output is byte-identical.
- **Tests.** New `apps/output/tests/test_hdhr_device_xml.py` (`apps/hdhr/` has no tests directory;
  `dispatcharr/test_discovery.py:52` routes it to `apps.output` and `apps.channels`). The e2e comment
  in `e2e/tests/seeded/hdhr.spec.ts:142-156`, which explains why #83 was not pinned, is replaced by a
  one-line pointer to the backend test. No e2e test is added: the comment's parallelism argument
  still holds.
- **Size** S. **Upstreamable** yes.
- **Duplicates.** None. The issue carries `needs-info` from a bot; the source citation is enough, and
  removing the label is the lead's.

### #82 — HDHomeRun endpoints authorize nothing

Closed by the maintainer on 2026-09-23 as not planned (a design decision). No memo and no PR. The
pin at `e2e/tests/seeded/hdhr.spec.ts:294` stays a `test.fail`, and the ledger row
`hdhr-no-authorization` keeps its `pinned` status with a title clause saying why (PR B-3, Task 3.2),
as `docs/agents/metrics.md` requires for an issue closed without a fix.

### #103, #104, #105 — plugin fetches follow redirects past the SSRF check

- **Root cause.** Three `requests.get` calls validate only the first hop. `_validate_fetch_url`
  (`apps/plugins/api_views.py:83-90`) calls `validate_outbound_http_url` (`core/http_security.py:10-80`),
  which resolves the host and refuses loopback, private, link-local and reserved targets. Then each
  site fetches with `requests`' default `allow_redirects=True`: `_fetch_manifest` at `:777-780`
  (callers `:817`, `:862`, `:984`, and `apps/plugins/tasks.py:20`), the manifest-detail fetch at
  `:1144-1149`, and the plugin zip download at `:1262-1267`. A public URL answering 302 to
  `http://169.254.169.254/` or `http://127.0.0.1:5656/` is followed.
- **Fix.** A new `fetch_outbound_http(url, *, allow_private, allow_loopback, max_redirects=5,
  **kwargs)` in `core/http_security.py`. It issues each request with `allow_redirects=False`,
  validates every `Location` (resolved with `urljoin`) with the same validator before following it,
  closes each intermediate response, and raises `ValueError` past `max_redirects`. The three sites
  call it through a local `_fetch(url, **kwargs)` in `api_views.py` that fixes
  `allow_private=False, allow_loopback=False`, matching `_validate_fetch_url`. Each site's existing
  `ValueError` handling already maps a validation failure to 400.
- **Residual, accepted and stated in the PR.** DNS rebinding between the check and the connect stays
  open. Closing it means connecting to the validated address with SNI and `Host` pinned, which is
  out of proportion here: every caller is an admin POST (`permission_classes_by_method`,
  `apps/plugins/api_views.py:103-109`) or a Celery refresh of an admin-stored URL, and an admin can
  already install arbitrary plugin code. That is also why the sweep lowered the priority to p3.
- **CodeQL.** `py/full-ssrf` does not model a `ValueError`-raising validator as a sanitizer, so the
  three alerts (102, 103, 104) may stay open after the fix. If they do, the lead dismisses them as
  "won't fix" citing B-4's PR. That is a tracker action, not a code change.
- **Tests.** Four new tests in `core/tests/test_http_security.py` for the helper. Three new tests in
  `apps/plugins/tests/test_plugin_fetch_redirects.py`, one per call site. No existing test changes.
- **Size** S–M. **Upstreamable** yes.
- **Duplicates.** Not duplicates in the tracker sense. Each issue is the canonical record of one
  CodeQL alert (the `codeql-alert:` marker), so **all three survive and all three close on B-4**.

### #61 — XC live URLs carry unencoded credentials

- **Root cause.** `collect_xc_streams` builds the stored live URL prefix from raw credentials at
  `apps/m3u/tasks.py:942-945`. `build_timeshift_url_format_b` quotes the same fields with
  `quote(str(x), safe='')` (`apps/timeshift/helpers.py:424-432`). **The issue misses the site that
  actually serves live playback.** For an XC stream with a `stream_id`, the tune path never reads
  the stored URL: `_resolve_live_stream_url` (`apps/proxy/next_source.py:44-68`) rebuilds it from
  `get_transformed_credentials` at `:63`, also unquoted. Fixing `tasks.py` alone would change the
  stored row and leave the symptom, a routing miss at the provider, exactly where it is.
- **Fix.** `quote(str(x), safe='')` on both fields at both sites, as the catch-up builder does. For
  a credential of unreserved characters (`A-Za-z0-9-._~`) `quote` is the identity, so no existing
  URL changes. Stream identity is unaffected for XC: `Stream.generate_hash_key`
  (`apps/channels/models.py:158-182`) hashes `stream_id`, not the URL, for XC accounts.
- **Tests.** Two new tests in `apps/m3u/tests/test_xc_live_url.py`. No existing test changes.
- **Size** S. **Upstreamable** no (`next_source.py` is fork-only). The `tasks.py` hunk alone would apply.
- **Gate 2.** `apps/proxy/next_source.py` is one of the nine Gate 2 modules
  (`scripts/coverage_live_path.coveragerc`). The line changes, the statement count does not. Run
  `scripts/coverage_live_path_isolated.sh --gate` before pushing (memory: Gate 2 modules need the
  isolated run).
- **Not in scope, filed as follow-ups.** The same raw interpolation exists in the VOD builders
  (`apps/vod/models.py:260`, `:309`), the unused client helpers (`core/xtream_codes.py:278-286`) and,
  for Dispatcharr's *own* users' XC credentials, the generated M3U (`apps/output/views.py:311`). The
  last is a different subject: Dispatcharr's own router has to accept the encoded form, and E-#80
  edits the neighbouring lines. `get_transformed_credentials`' synthetic URL (`apps/m3u/tasks.py:3088`)
  stays raw on purpose. It is parsed back by path segment and profile patterns are written against
  raw credentials. A credential containing `/` already breaks that round trip; that is a separate
  defect.

### #204, #205 — passwords drawn from `Math.random()`

- **Root cause.** `frontend/src/components/forms/User.jsx:77` sets a new Streamer's password to
  `Math.random().toString(36).slice(2)`. `:109` (`generateXCPassword`) sets the XC password, a
  streaming credential, the same way. These are the only two `Math.random` calls under
  `frontend/src`.
- **Fix.** A new `frontend/src/utils/securePassword.js` exporting `generateSecurePassword(length = 20)`,
  which draws bytes from `crypto.getRandomValues` and maps them onto a 62-character alphanumeric
  alphabet with rejection sampling (discard bytes ≥ 248) so every character is equally likely. It
  is alphanumeric because the XC password travels in URL paths and query strings, and #61 is what
  happens when it is not. Both call sites use it. It is a new module rather than an addition to
  `utils/forms/UserUtils.js`, because `User.test.jsx:18-27` mocks that module wholesale.
- **Tests.** New `frontend/src/utils/__tests__/securePassword.test.js`; two new tests in
  `User.test.jsx`. No existing test changes.
- **Size** S. **Upstreamable** yes.
- **Duplicates.** Each issue is one CodeQL alert (16 and 17). **Both survive and both close on B-6.**

### #182 — `get_client_ip` believes a LAN client's own `X-Real-IP`

- **Root cause.** With `DISPATCHARR_TRUSTED_PROXIES` unset, `_trusted_proxy_networks` trusts every
  `LOCAL_NETWORK_CIDRS` peer (`dispatcharr/utils.py:310-312`; the list at `:17-25`).
  `get_client_ip` then returns the peer's `X-Real-IP` first (`:358-360`) and walks `X-Forwarded-For`
  second (`:362-368`). On every `uwsgi_pass` location, `REMOTE_ADDR` is the client itself: `include
  uwsgi_params` forwards nginx's `$remote_addr`, and the server-level `proxy_set_header X-Real-IP`
  (`docker/nginx.conf:69`) does not apply to `uwsgi_pass`. `dispatcharr_api_params.conf` blanks only
  the relay parameters. So a LAN client's own header reaches Django and is believed. That feeds the
  network ACL (`network_access_allowed`, `:406`), the setup gate (`setup_ip_allowed`), the login
  throttle and every event's `client_ip`. The authorize hop runs on a `uwsgi_pass` location too
  (`location = /_dispatcharr/authorize`, `docker/nginx.conf:138`), so the STREAMS ACL is reachable
  the same way.
- **Fix.** The issue's own direction: the default trusts loopback only (`127.0.0.0/8`, `::1/128`).
  Every in-container hop that should be trusted is loopback: nginx to Daphne on `/ws/` and the
  authorize hop's own subrequest. The Go relay's inline authorize carries the client address in its
  body, not a header (`apps/proxy/authorize_views.py:495-507`), so it is unaffected. A deployment
  behind an outer proxy sets `DISPATCHARR_TRUSTED_PROXIES` to that proxy's address, which
  `README.md:109` already tells it to do.
- **Why it is gated.** Upstream chose the private-network default deliberately (CHANGELOG, "Closes
  #1410"), for Docker/Traefik deployments that set nothing. For such a deployment this change is not
  just "less accurate IPs". Every request appears to come from the proxy's private address, so the
  `M3U_EPG` default ACL (private networks only) **stops refusing public clients**. That is a
  fail-open on upgrade for exactly the users who configured nothing. See Q1.
- **Tests.** One flip in `core/tests/test_core.py`, two new tests. The e2e harness has to trust its
  own bridge gateway explicitly, because `network-acl.spec.ts` simulates non-local clients with a
  spoofed `X-Real-IP`, which is exactly what this closes.
- **Size** M. **Upstreamable** the diff applies, but it reverses an upstream decision.
- **Duplicates.** None. #81 (category G) is related and stays separate (§ Overlap).

---

## PR B-1 — VOD proxy: no exception text in a 500 body, and the adult filter on movie streams

- **Branch** `fix/B-1-vod-proxy-security`
- **Closes** #89, #110. #186 is closed as superseded by #89 (lead).
- **Files** `apps/proxy/vod_proxy/views.py`, `apps/proxy/vod_proxy/multi_worker_connection_manager.py`,
  `apps/proxy/vod_proxy/tests/test_vod_error_bodies.py` (new),
  `apps/proxy/vod_proxy/tests/test_vod_adult_filter.py` (new),
  `e2e/tests/streaming/vod-adult-streamable.spec.ts`, `metrics/curated/defects.yml`.
- **Labels** `apps.proxy.vod_proxy.tests` (one label). The e2e change runs the `streaming` project,
  which the `changes` job selects for any `apps/` path.
- **upstreamable** no as a whole. The #89 hunks alone: yes.

### Task 1.1 — the fixed 500 bodies (#89)

1. Re-grep the three anchors and confirm each is unique:
   `grep -n 'Streaming error: {str(e)}\|HEAD error: {str(e)}' apps/proxy/vod_proxy/views.py apps/proxy/vod_proxy/multi_worker_connection_manager.py`
   must print exactly three lines.
2. Write `test_vod_error_bodies.py` first (Appendix A). Three `SimpleTestCase` tests, all driving an
   upstream-shaped exception whose message carries a credential:
   `requests.exceptions.ConnectionError("HTTPConnectionPool(host='provider.example', port=80): Max retries exceeded with url: /movie/alice/s3cret-pw/501.mp4")`.
   - `test_a_stream_vod_upstream_error_put_the_provider_url_in_the_500_body` — patches
     `resolve_authorization`, `_select_vod_stream` and `MultiWorkerVODConnectionManager` (the
     `test_vod_redirect.py:66-100` pattern) so `stream_content_with_session` raises. Calls
     `stream_vod(..., session_id="vod_1_1")`. Asserts status 500, body exactly `b"Streaming error"`,
     and `b"s3cret-pw"` not in the body.
   - `test_a_session_stream_error_put_the_provider_url_in_the_500_body` — builds the manager with
     `MultiWorkerVODConnectionManager.__new__` (the `test_profile_connections.py:91` pattern), sets
     `worker_id` and `redis_client`, and patches `find_matching_idle_session` to raise. With
     `redis_connection` still `None`, the handler's rollback block is skipped. Same three assertions.
   - `test_a_head_vod_error_put_the_provider_url_in_the_500_body` — the `test_vod_redirect.py:280-310`
     pattern with `_select_vod_stream` raising. Asserts 500, body exactly `b"HEAD error"`, no
     credential.
3. Run the file. **All three fail** on the body assertion; record the three messages.
4. Apply the fix (Appendix A, three one-line hunks). Run again: three pass.
5. **Break-check.** Restore `{str(e)}` at `multi_worker_connection_manager.py:1409` only. Exactly
   one test reddens, and its message shows the credential in the body. Revert.

### Task 1.2 — the adult filter on movie streams (#110)

1. Confirm the premise the fix rests on: `grep -n "is_adult" apps/vod/models.py` prints exactly one
   field (`Movie`, `:129`). If `Series` or `Episode` has gained one, STOP; the scope changes.
2. Write `test_vod_adult_filter.py` first (Appendix B). A `TestCase`, because `stream_xc_movie`
   resolves a real `M3UMovieRelation`. Users are real rows. Movies are real rows with `is_adult`
   set explicitly (memory: set the row explicitly, never rely on a seeded default).
   - `test_stream_xc_movie_streamed_an_adult_movie_to_a_hide_adult_user` — user level 1 with
     `hide_adult_content: True`, adult movie. `resolve_authorization` is patched to return that
     user. Asserts 403 and `stream_vod` never called (patched with `wraps` to count calls).
   - `test_stream_vod_redirect_branch_streamed_an_adult_movie_to_a_hide_adult_user` — Redirect
     default on. The `content_id` passed is a UUID **not in the database**, so call (4)'s lookup
     returns `None` and lets the request through. This is the stream-id fallback shape that only
     call (2) can see. `_select_vod_stream` is patched to return the real adult movie as
     `content_obj`. Asserts 403 and no `HttpResponseRedirect`.
   - `test_stream_vod_session_branch_streamed_an_adult_movie_to_a_hide_adult_user` — Redirect off,
     `session_id` set, manager patched. Asserts 403 and `stream_content_with_session` not called.
   - `test_an_adopted_idle_session_streamed_an_adult_movie_to_a_hide_adult_user` — Redirect on, no
     `session_id`, `_find_idle_vod_session` patched to return `"idle_session_abc"`, and the content
     UUID a real adult movie. Asserts 403 and no 301 to the idle session.
   - `test_an_admin_with_hide_adult_content_still_streams_an_adult_movie` — **user level 10 and
     `hide_adult_content: True`**, a non-default pairing, so the test fails if the admin bypass is
     dropped (memory: a pin that supplies the default pins nothing). Asserts the Redirect.
   - `test_a_user_without_hide_adult_content_still_streams_an_adult_movie` — level 1, the key absent.
     Asserts the Redirect.
   - `test_a_hide_adult_user_still_streams_a_non_adult_movie` — the control. Asserts the Redirect.
3. Run. The four `..._streamed_an_adult_movie_...` tests fail, each getting a redirect or a manager
   call. The three controls pass. Record the messages.
4. Apply Appendix B. Run: seven pass. Each failing test has exactly one intended refusal. If a test
   passes by a different call than this one, it is shadowed, and a break-check below will not
   redden:

   | Test | Refused by |
   |---|---|
   | `test_stream_xc_movie_streamed_...` | the `stream_xc_movie` call; `stream_vod` is never reached |
   | `test_stream_vod_redirect_branch_streamed_...` | call (2); call (4) passes, because the UUID is unknown |
   | `test_stream_vod_session_branch_streamed_...` | call (3); call (4) is skipped, because `session_id` is set |
   | `test_an_adopted_idle_session_streamed_...` | call (4), before `_find_idle_vod_session` is consulted |
5. **Break-check A.** Change the helper's admin test from `< User.UserLevel.ADMIN` to `<= User.UserLevel.ADMIN`.
   `test_an_admin_with_hide_adult_content_still_streams_an_adult_movie` alone reddens. Revert.
6. **Break-check B.** Delete the call in the session branch only. Only the session-branch test
   reddens. Revert.
6a. **Break-check C.** Delete the first-request call (4) only. Only the adopted-idle-session test
   reddens. Revert.
6b. **Break-check D.** Delete the Redirect-branch call (2) only. Only the Redirect-branch test
   reddens. Revert.
7. Flip the e2e pin (below). Run the `streaming` project's file against a local stack
   (`scripts/e2e_up.sh`, then `npx playwright test tests/streaming/vod-adult-streamable.spec.ts`) on
   the unfixed tree first: the flipped test **fails** at the status assertion, with both premise
   assertions passing. Then on the fixed tree: it passes. Record both runs in the PR.

**Test changes under the rule.**

| Test | Before | After |
|---|---|---|
| `e2e/tests/streaming/vod-adult-streamable.spec.ts` `'an adult movie a user cannot list is not streamable by that user'` | `test.fail(...)`; final assertion `expect(res.status(), ...).not.toBe(200)` | `test(...)`; final assertion `expect(res.status(), ...).toBe(403)`. The comment block above it (`:88-120`) is replaced by one paragraph saying what the test pins and naming #110 as fixed. |

The assertion is tightened from "not 200" to "403". That narrows what passes; it widens nothing.

### Task 1.3 — the ledger

Add one row to `metrics/curated/defects.yml`, directly at `fixed` (a new row has no prior status to
move backward from):

```yaml
- {id: vod-adult-streamable, title: "stream_vod and stream_xc_movie applied no is_adult filter: a movie hidden from a hide_adult_content user by the XC listings was still streamable", area: security, severity: medium, status: fixed, source: null, issue: 110, test: e2e/tests/streaming/vod-adult-streamable.spec.ts, fixed_in: <this PR>, carried_as: null, first_seen: 2026-09-01, status_changed: <merge date>}
```

Validate with `python3 -m metrics.build --validate-only --curated metrics/curated`.

### PR description draft

> **fix(vod_proxy): no exception text in a 500 body, and the adult filter on movie streams**
>
> Closes #89 and #110.
>
> **#89.** Three VOD handlers answered `Streaming error: {e}` (and `HEAD error: {e}`) with the
> caught exception's text. A `requests` error names the upstream URL, and an XC VOD URL carries the
> provider username and password. `stream_vod`, `stream_xc_movie` and `stream_xc_episode` are
> `AllowAny`. Each body is now a fixed string; the detail stays in the server log.
>
> **#110.** `hide_adult_content` hid adult movies from `get_vod_streams` and `get_vod_info` but not
> from the streaming routes. `stream_xc_movie` and both of `stream_vod`'s content-resolving branches
> now answer 403 for that user, with the listing's own predicate and its admin bypass. Episodes are
> unchanged: only `Movie` has an `is_adult` field, and nothing lists episodes by it.
>
> The e2e pin `vod-adult-streamable.spec.ts` flips from `test.fail` to `test` and now asserts 403.
>
> Follow-up to file: the same three handlers log the exception text unredacted at ERROR.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## PR B-2 — XC API: one answer for bad credentials, 403 for a refused network

- **Branch** `fix/B-2-xc-auth-status`
- **Closes** #84, #134.
- **Files** `apps/output/views.py`, `apps/output/tests/test_xc_auth.py` (new),
  `e2e/tests/seeded/xc-auth.spec.ts`, `e2e/tests/seeded/network-acl.spec.ts`,
  `metrics/curated/defects.yml`, `CLAUDE.md`.
- **Labels** `apps.output.tests` (one label). The e2e changes run the `seeded` project.
- **upstreamable** no.

### Task 2.1 — `xc_authenticate` and the credential check (#84)

1. Write `test_xc_auth.py` first (Appendix C). A `TestCase` using the Django test client
   (`REMOTE_ADDR` 127.0.0.1). One XC user with `xc_password`, one user without.
   - `test_an_unknown_xc_username_answered_404_where_a_wrong_password_answered_401` — for each of
     the four endpoints (`/player_api.php`, `/panel_api.php`, `/get.php`, `/xmltv.php`), a ghost
     username and a real username with a wrong password both answer 401 **with identical bodies**.
   - `test_a_non_ascii_xc_password_is_refused_not_500` — a wrong non-ASCII password answers 401 on
     `player_api.php`. `resolve_xc_user` already encodes to bytes; this pins that the delegation
     kept that property.
   - `test_valid_xc_credentials_still_answer_200_on_all_four_endpoints` — the control.
2. Run. The first test fails with 404 on all four endpoints; the other two pass.
3. Apply the credential half of Appendix C. Run: three pass.
4. **Break-check.** Put `get_object_or_404(User, username=username)` back in front of the
   delegation. The first test alone reddens with a 404. Revert.

### Task 2.2 — the network refusal (#134)

1. Extend `test_xc_auth.py`:
   - `test_a_network_blocked_xc_user_got_401_as_if_the_password_were_wrong` — set the user's
     `custom_properties.allowed_networks.XC_API` to `203.0.113.0/24`, which cannot contain
     127.0.0.1. All four endpoints answer 403 `{"error": "Forbidden"}`.
   - `test_player_api_and_panel_api_logged_no_event_for_a_network_refusal` — after the two
     requests, `SystemEvent.objects.filter(event_type="login_failed", details__reason="Network access denied (XC API)")`
     has exactly two rows, one per endpoint, and each carries the username. Check
     `log_system_event`'s `details` shape (`core/utils.py`) before writing the filter.
   - `test_a_global_xc_api_block_answered_401_on_player_api` — write the `network_access` settings
     group with `XC_API` set to `203.0.113.0/24` in the test's own transaction. The group is read
     through a cache (`CoreSettings.get_network_access_settings`); find how `core/tests` invalidate
     it (`CoreSettings.invalidate_group_cache` or `cache.clear()`) before writing the test, or the
     write is invisible to the view (memory: warm state hides a query). `player_api.php` and `panel_api.php` answer 403 even with a wrong
     password, matching `get.php`.
   - `test_wrong_credentials_from_an_allowed_network_still_answer_401` — the regression guard for
     the split.
2. Run. The first three fail (401, zero events, 401). The fourth passes.
3. Apply the rest of Appendix C. Run the whole file: seven pass.
4. **Break-check A.** Make `xc_authenticate` return `401` for the network branch. Only the two
   network-refusal status tests redden. Revert.
5. **Break-check B.** Remove the `log_system_event` call from `xc_player_api` only. The event test
   reddens with a count of one. Revert.

### Task 2.3 — flip the two pins

On the unfixed tree first, then on the fixed tree, run
`npx playwright test tests/seeded/xc-auth.spec.ts tests/seeded/network-acl.spec.ts` against a local
stack. Each flipped test fails before (at its final assertion, premises passing) and passes after.
Record both runs.

| Test | Before | After |
|---|---|---|
| `xc-auth.spec.ts` `'player_api.php does not distinguish an unknown user from a wrong password'` | `test.fail(...)`; asserts wrong password 401 and unknown user 401 | `test(...)`; the same two assertions. Title becomes `'player_api.php answers an unknown user and a wrong password identically'`. The comment above it (`:132-144`) is replaced by one paragraph naming #84 as fixed. |
| `network-acl.spec.ts` `'a network-blocked XC user gets 401 from player_api.php, not the correct 403 (#134)'` | `test.fail(...)`; final assertion `expect(res.status()).toBe(403); // correct behaviour; today it is 401` | `test(...)`; the same assertion without the trailing comment. Title becomes `'a network-blocked XC user gets 403 from player_api.php (#134)'`. The comment block above it (`:354-374`) is replaced by one paragraph. |
| (no test; behaviour note) | A client outside a narrowed **global** `XC_API` row got 401 from `player_api.php` and `panel_api.php` even with valid credentials, from the per-user check inside `xc_get_user` | It gets 403 from the new pre-check, as `get.php` already did. This is intended. No e2e test pins the old 401: the D2 test asserts 403 on `get.php` and `xmltv.php` only (`network-acl.spec.ts:269`, `:275`). The new backend test `test_a_global_xc_api_block_answered_401_on_player_api` pins the new answer. |
| `network-acl.spec.ts` `'a per-user XC_API allowlist refuses that user on all three XC surfaces (D4)'` | `isXcRefused(res)` (401 or 403) on three paths | **Unchanged.** Its comment at `:339-340` says it stays green whichever way #134 resolves, and it does. Tightening it to 403 is not this PR's business. |

### Task 2.4 — the ledger and CLAUDE.md

1. `metrics/curated/defects.yml`: row `xc-account-enumeration` (`:18`) becomes `status: fixed`,
   `fixed_in: <this PR>`, `status_changed: <merge date>`. `test` keeps its path.
2. Add a row for #134:
   ```yaml
   - {id: xc-network-block-401, title: "A user refused by the XC_API network ACL got 401 (as if the password were wrong) from all four XC endpoints, and player_api.php/panel_api.php logged no event", area: security, severity: low, status: fixed, source: null, issue: 134, test: e2e/tests/seeded/network-acl.spec.ts, fixed_in: <this PR>, carried_as: null, first_seen: 2026-09-02, status_changed: <merge date>}
   ```
3. `CLAUDE.md`, § Known defects and traps, Security, the Xtream-password bullet. Replace
   "but the value at rest is unchanged and the listing surfaces still compare their own way." with
   "and since the fix for #84 the listing surfaces (`xc_get_user` in `apps/output/views.py`) delegate
   to the same function, but the value at rest is unchanged."
4. Validate the ledger.

### PR description draft

> **fix(output): one answer for bad XC credentials, 403 for a refused network**
>
> Closes #84 and #134.
>
> `xc_get_user` answered 404 for an unknown username and 401 for a wrong password, so
> `player_api.php` was an account-enumeration oracle. It now delegates to `resolve_xc_user`, the
> constant-time check every streaming surface already uses. That removes the last `!=` comparison of
> an XC password in the tree.
>
> A user refused by the `XC_API` network ACL got the same 401 as a wrong password, from all four
> endpoints. They now get 403. `player_api.php` and `panel_api.php` gain the global pre-check
> `get.php` already had, and log a `login_failed` event for a network refusal.
>
> `reverse_imports_into_proxy` moves from 28 to 29. `apps/output/views.py` already imports from
> `apps.proxy`, so no new edge appears. One implementation of the credential check is worth one
> import statement.
>
> Two e2e pins flip from `test.fail` to `test`. The ledger row `xc-account-enumeration` is fixed and
> a new row records #134.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## PR B-3 — HDHomeRun `device.xml` reads the configured device

- **Branch** `fix/B-3-hdhr-device-xml`
- **Closes** #83.
- **Files** `apps/hdhr/api_views.py`, `apps/output/tests/test_hdhr_device_xml.py` (new),
  `e2e/tests/seeded/hdhr.spec.ts` (comment only), `metrics/curated/defects.yml` (one title, for #82).
- **Labels** `apps.channels.tests`, `apps.output.tests` (the alias for `apps/hdhr/`).
- **upstreamable** yes.

### Task 3.1

1. Write the test first (Appendix D). `TestCase`, Django test client.
   - `test_device_xml_ignored_a_configured_hdhr_device_row` — create
     `HDHRDevice(friendly_name="Den <Tuner> & Co", device_id="ABCD1234")`. GET `/hdhr/device.xml`.
     Assert `<DeviceID>ABCD1234</DeviceID>` and `<FriendlyName>Den &lt;Tuner&gt; &amp; Co</FriendlyName>`,
     and that the body parses with `xml.etree.ElementTree.fromstring`. Then GET `/hdhr/discover.json`
     and assert its `DeviceID` and `FriendlyName` equal the XML's text values.
   - `test_device_xml_without_a_device_row_keeps_the_default_identity` — no row. Assert the two
     literals, byte-identical to today's.
2. Run. The first fails on `DeviceID`; the second passes.
3. Apply Appendix D. Run: both pass.
4. **Break-check A.** Drop the `escape()` on `friendly_name`. The first test reddens with an XML
   parse error. That confirms the name is the part being escaped. Revert.
5. **Break-check B.** Read `device.friendly_name` but keep the hardcoded `DeviceID`. The first test
   reddens on `DeviceID`. Revert.
6. Replace the comment block at `e2e/tests/seeded/hdhr.spec.ts:142-156` with: "`device.xml` and
   `discover.json` read the same `HDHRDevice` row since #83; pinned by
   `apps/output/tests/test_hdhr_device_xml.py`, not here, because a row is instance-wide and this
   project runs `fullyParallel`." No test changes.

### Task 3.2 — the #82 ledger row

#82 was closed as not planned, not fixed. Per `docs/agents/metrics.md` § "A `wontfix`-labelled issue
keeps its ledger status", leave `hdhr-no-authorization` (`metrics/curated/defects.yml:17`) at
`status: pinned` and change nothing else in the row but its `title`, which gains: "; #82 closed as
not planned by the maintainer on 2026-09-23: the HDHomeRun surface is principal-free by design and
relies on the M3U_EPG network ACL". Validate the ledger. The `test.fail` pin stays as it is.

### PR description draft

> **fix(hdhr): device.xml reads the configured HDHRDevice row**
>
> Closes #83. `discover.json` used a configured `HDHRDevice` row for its `DeviceID` and
> `FriendlyName`; `device.xml` always answered the hardcoded defaults, so the two disagreed about the
> device's own identity. `device.xml` now reads the same row, XML-escapes the admin-editable name,
> and keeps the old literals when no row exists.
>
> The ledger row for #82 (closed as not planned) keeps its `pinned` status and gains a title clause
> saying why.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## PR B-4 — plugin fetches validate every redirect hop

- **Branch** `fix/B-4-plugin-fetch-redirects`
- **Closes** #103, #104, #105.
- **Files** `core/http_security.py`, `core/tests/test_http_security.py`, `apps/plugins/api_views.py`,
  `apps/plugins/tests/test_plugin_fetch_redirects.py` (new).
- **Labels** `core.tests`, `apps.plugins.tests`.
- **upstreamable** yes.

### Task 4.1 — the helper

1. Write four tests in `core/tests/test_http_security.py` first (Appendix E), using its existing
   `_fake_addrinfo` helper and `@patch("core.http_security.socket.getaddrinfo")` with a
   `side_effect` keyed by hostname. Patch `core.http_security.requests.get` to return fake responses.
   - `test_a_redirect_to_link_local_was_followed_after_a_validated_first_hop` — the first hop
     (`public.example`, 93.184.216.34) answers 302 to `http://169.254.169.254/latest/`. Assert
     `ValueError`, and that `requests.get` was called once.
   - `test_a_relative_redirect_is_resolved_against_the_current_hop` — a 302 with `Location:
     /next` goes to `http://public.example/next`, validated, then answers 200.
   - `test_every_hop_is_requested_with_allow_redirects_false` — inspect each recorded call's kwargs.
   - `test_more_than_max_redirects_is_refused` — six 302s with `max_redirects=5` raise `ValueError`.
2. Run. All four fail with `ImportError` (the helper does not exist). That is expected for a new
   function. The first test's real proof is break-check A.
3. Add the helper (Appendix E). Run: four pass.
4. **Break-check A.** Make the helper call `requests.get(url, allow_redirects=True, **kwargs)` once
   and return. The link-local test and the `allow_redirects` test redden. Revert.
5. **Break-check B.** Skip validation for hops after the first. Only the link-local test reddens.
   Revert.

### Task 4.2 — the three call sites

1. In `apps/plugins/api_views.py`, add `_fetch(url, **kwargs)` beside `_validate_fetch_url` (`:83`),
   calling `fetch_outbound_http(url, allow_private=False, allow_loopback=False, **kwargs)`.
2. Replace the three calls (Appendix E, second hunk). `_fetch_manifest`'s own `_validate_fetch_url`
   call becomes redundant and is removed; the two views keep theirs, because they answer a
   validation failure with a 400 before any network I/O, and that answer is useful to an admin.
3. The zip download at `:1267` wraps its fetch in `except Exception` and answers 502 with a fixed
   body (`:1269-1274`). A redirect to a refused target now raises `ValueError` inside that `try` and
   becomes the same 502 with the same fixed message.
4. **The three call sites are what #103, #104 and #105 are about, so each gets its own test.** The
   helper tests in Task 4.1 pass with every site still on `http_requests.get`. Write a new
   `apps/plugins/tests/test_plugin_fetch_redirects.py` (label `apps.plugins.tests`) **before** step 2.
   Each test patches `core.http_security.socket.getaddrinfo` with a `side_effect` keyed by hostname
   (`public.example` answers `93.184.216.34`, `127.0.0.1` answers itself) and patches
   `core.http_security.requests.get`. The first hop answers 302 with `Location:
   http://127.0.0.1:5656/x`. Each test asserts two things. First, **every** recorded call to the
   patched `get` carried `allow_redirects=False`. Second, the site's own outcome.
   - `test_fetch_manifest_followed_a_redirect_to_loopback` calls `_fetch_manifest("http://public.example/m.json")`
     and expects `ValueError`. This is #103.
   - `test_repo_manifest_detail_followed_a_redirect_to_loopback` POSTs as an admin to the
     manifest-detail view that holds `:1149`, with a real `PluginRepo` row. It expects 502. This is
     #104. Find the route name in `apps/plugins/api_urls.py` first.
   - `test_plugin_install_followed_a_redirect_to_loopback` POSTs as an admin to the install view that
     holds `:1267`, and expects 502 with the fixed body `"Failed to download plugin. Check the URL and
     try again."`. This is #105. Supply the smallest request body that reaches the download, which
     means reading the view's checks above `:1262` first.

   The `allow_redirects=False` assertion is what makes these tests real. `http_requests` in
   `api_views.py:18` is the same `requests` module object that `core.http_security` imports, so a
   site still on `http_requests.get` also hits the mock. What it does not do is pass
   `allow_redirects=False`. On the unfixed tree all three tests fail. `_fetch_manifest` and the
   install view fail on the kwarg assertion. The detail view fails on both. A mock follows nothing: the
   view receives the fake 302, `raise_for_status()` does nothing on it, and the view answers 200
   with the fake's `json()`. That is why the 502 assertion fails too.
5. **Break-check.** After step 2, revert `:1149` alone to `http_requests.get(manifest_url,
   timeout=MANIFEST_FETCH_TIMEOUT)`. Only `test_repo_manifest_detail_followed_a_redirect_to_loopback`
   reddens, and its failure names the missing `allow_redirects=False`. Revert. Repeat once for `:780`
   and once for `:1267`. Each time, only that site's test reddens.
6. Run both labels.

### PR description draft

> **fix(plugins): validate every redirect hop of a plugin fetch**
>
> Closes #103, #104 and #105 (CodeQL `py/full-ssrf`, alerts 102–104).
>
> The three plugin fetches validated the first URL against the SSRF rules, then let `requests`
> follow redirects anywhere, including loopback and 169.254.169.254. A new
> `fetch_outbound_http` in `core/http_security.py` follows redirects itself and validates each hop.
>
> Residual, accepted: a DNS answer can still change between the check and the connect. Every caller
> is an admin action, and an admin can already install arbitrary plugin code.
>
> CodeQL may keep the alerts open, because it does not model the validator as a sanitizer. If so,
> they are dismissed citing this PR.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## PR B-5 — XC live URLs percent-encode the credentials

- **Branch** `fix/B-5-xc-live-url-encoding`
- **Closes** #61.
- **Files** `apps/m3u/tasks.py`, `apps/proxy/next_source.py`, `apps/m3u/tests/test_xc_live_url.py`.
- **Labels** `apps.m3u.tests`, `apps.proxy.tests`. Plus the Gate 2 isolated run.
- **upstreamable** no as a whole. The `tasks.py` hunk alone: yes.

### Task 5.1

1. Read `apps/m3u/tests/test_xc_live_url.py` in full; reuse its account, profile and stream
   fixtures.
2. Add two tests:
   - `test_resolve_live_stream_url_interpolated_a_slash_in_the_password_raw` — an XC account whose
     password is `p/ss%w@rd`. `_resolve_live_stream_url` returns
     `.../live/alice/p%2Fss%25w%40rd/12345.ts`. Assert the exact string.
   - `test_collect_xc_streams_stored_a_slash_in_the_password_raw` — use the
     `@patch("apps.m3u.tasks.XCClient")` pattern at `apps/m3u/tests/test_memory_cleanup.py:133`.
     The mock's `__enter__` returns a client whose `server_url`, `username` and `password` are set,
     and whose `get_all_live_streams` returns `[{"stream_id": 12345, "name": "News 1",
     "category_id": 7}]`. Call `collect_xc_streams(account.id, {"News": {"xc_id": 7}})`. That
     function keys on `props["xc_id"]` (`tasks.py:924-930`). Assert that the one returned entry's
     `url` is `.../live/alice/p%2Fss%25w%40rd/12345.ts`.
3. Run. Both fail with the raw string.
4. Apply Appendix F. Run the file: all pass, including the existing
   `.../live/alice/secret/12345.ts` expectation at `:77`, which proves an unreserved credential is
   unchanged.
5. **Break-check.** Quote the username only, not the password, at `next_source.py:63`. The first
   test reddens. Revert.
6. Run `scripts/coverage_live_path_isolated.sh --gate` against your own container. It must pass with
   `missing` at or below the floor. The statement count does not move. If `missing` rises, STOP: a
   line of `next_source.py` stopped being covered, and that is a finding.

### PR description draft

> **fix(m3u,proxy): percent-encode XC credentials in live URLs**
>
> Closes #61. Catch-up URLs quote the XC username and password; live URLs did not, so a credential
> containing `/`, `%` or `@` produced a URL the provider could not route. Both live builders now
> quote them: the stored URL in `collect_xc_streams`, and the one the tune path actually dials in
> `_resolve_live_stream_url`. A credential of unreserved characters produces the same URL as
> before, and XC stream identity hashes `stream_id`, not the URL.
>
> Gate 2: `next_source.py` is a gated module; the isolated run passes (paste the line).
>
> Follow-ups to file: the VOD URL builders in `apps/vod/models.py` and `core/xtream_codes.py` have
> the same raw interpolation.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## PR B-6 — generated passwords come from `crypto.getRandomValues`

- **Branch** `fix/B-6-secure-password-generation`
- **Closes** #204, #205.
- **Files** `frontend/src/utils/securePassword.js` (new),
  `frontend/src/utils/__tests__/securePassword.test.js` (new),
  `frontend/src/components/forms/User.jsx`,
  `frontend/src/components/forms/__tests__/User.test.jsx`.
- **Labels** none backend. The whole frontend suite runs (commit gate and `Frontend result`).
- **upstreamable** yes.

### Task 6.1

1. Write `securePassword.test.js` first (Appendix G):
   - `generateSecurePassword used Math.random` — `vi.spyOn(Math, 'random').mockImplementation(() => { throw new Error('Math.random called'); })`
     and `vi.spyOn(globalThis.crypto, 'getRandomValues')`. Call it. Assert no throw and the crypto
     spy called.
   - `returns the requested length from the alphanumeric alphabet` — lengths 1, 20 and 64; every
     character matches `/^[A-Za-z0-9]+$/`.
   - `rejects bytes that would bias the alphabet` — mock `getRandomValues` to fill with `255` on the
     first call and `0` on the next. Assert the result is all `'A'` (index 0), which proves 255 was
     discarded rather than taken modulo 62.
2. Run: all fail with an import error. Add the module. Run: all pass.
3. **Break-check.** Replace the body with `Math.random().toString(36).slice(2)`. The first test
   reddens with "Math.random called". Revert.
4. In `User.test.jsx`, add `vi.mock('../../../utils/securePassword', () => ({ generateSecurePassword: vi.fn(() => 'GENERATED') }))`.
   Then make two test changes:
   - Add `creating a Streamer sends a password from generateSecurePassword`. `formValuesToPayload`
     returns `{ user_level: <STREAMER> }`. Submit with no `user` and assert that `createUser` was
     called with `password: 'GENERATED'`.
   - Tighten the existing `'calls setValues with a generated xc_password when rotate icon is
     clicked'` (`User.test.jsx:712`). It already clicks `getByTestId('icon-rotate-ccw-key')`. The
     table below gives the before and after.
5. Run: both fail. Apply the two call-site edits. Run the whole frontend suite (`npm test`) and
   `npx eslint` on the four files; eslint is advisory.

| Test | Before | After |
|---|---|---|
| `User.test.jsx` `'calls setValues with a generated xc_password when rotate icon is clicked'` (`:712`) | `expect(mockForm.setValues).toHaveBeenCalledWith(expect.objectContaining({ xc_password: expect.any(String) }))` | `expect(mockForm.setValues).toHaveBeenCalledWith(expect.objectContaining({ xc_password: 'GENERATED' }))`. The behaviour it pins, where the XC password comes from, is the thing this PR changes. |

### PR description draft

> **fix(frontend): generate passwords with crypto.getRandomValues**
>
> Closes #204 and #205 (CodeQL `js/insecure-randomness`, alerts 16 and 17). The default Streamer
> password and the generated XC password came from `Math.random()`. Both now come from
> `generateSecurePassword`, which uses `crypto.getRandomValues` with rejection sampling over an
> alphanumeric alphabet. The XC password stays URL-safe, because it travels in stream URLs.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## PR B-7 — trust forwarded client addresses from loopback only (gated on Q1)

**Do not start this PR until the user rules on Q1.** This section is written for option (a). Q1
carries the delta for (b) and (c), so any ruling can be executed without another planning round.

- **Branch** `migration/B-7-trusted-proxies-loopback`
- **Closes** #182.
- **Files** `dispatcharr/utils.py`, `core/tests/test_core.py`, `scripts/e2e_up.sh`, `README.md`,
  `e2e/tests/seeded/network-acl.spec.ts` (comments), `e2e/README.md`, `e2e/COVERAGE.md`, and the
  trusted-proxy comment block in four compose files: `docker/docker-compose.aio.yml:28-32`,
  `docker/docker-compose.yml:102-106`, `docker/docker-compose.dev.yml` and
  `docker/docker-compose.debug.yml` (each at `:25-29`; re-grep for `Outer reverse proxy trust`).
- **Labels** all fifteen. `dispatcharr/` is a shared prefix. E2E and lifecycle both run, because
  `scripts/e2e_up.sh` is in both workflows' change patterns.
- **Branch prefix.** `migration/`, under the brief's rule 3, because the PR edits `docker/`. The
  cost is small. `dispatcharr/` and `scripts/` already put B-7 on the nine-project matrix
  (`e2e-tests.yml:110`). `migration/` adds only `lifecycle-upgrade` and the two bash suites.
- **upstreamable** the diff applies; it reverses upstream's own default.

### Task 7.1 — the default

1. In `core/tests/test_core.py`'s `GetClientIpTests` (`:750`):
   - Flip `test_default_trusts_private_peer_headers` (`:779-788`), below.
   - Add `test_default_still_trusts_a_loopback_peer` — env unset, peer `127.0.0.1`, `X-Real-IP:
     203.0.113.50`, returns `203.0.113.50`.
   - Add `test_listing_the_private_ranges_restores_the_old_default` — env set to
     `10.0.0.0/8,172.16.0.0/12,192.168.0.0/16`, peer `172.18.0.1`, returns the header value. This is
     the documented escape hatch for a Traefik-style deployment.
2. Run. The flipped test fails (it gets `203.0.113.50`); the two new tests pass.
3. Apply Appendix H. Run `core.tests`: all pass.
4. **Break-check.** Add `"172.16.0.0/12"` back into the default tuple. The flipped test alone
   reddens. Revert.
5. Run every label once; `test_accounts.py`, `test_login_throttle_ip_spoofing.py` and
   `test_authorize_view.py` use a loopback peer and must stay green unchanged. If any other test
   reddens, STOP and report; this plan's grep found no other private-peer header test.

| Test | Before | After |
|---|---|---|
| `core/tests/test_core.py::GetClientIpTests::test_default_trusts_private_peer_headers` | env unset, peer `172.18.0.1`, `X-Real-IP: 203.0.113.50`; `assertEqual(get_client_ip(request), "203.0.113.50")` | renamed `test_a_lan_client_spoofed_its_address_with_x_real_ip_by_default`; same inputs; `assertEqual(get_client_ip(request), "172.18.0.1")`. Docstring: "Unset env trusts loopback only, so a private peer's own header is ignored (#182)." |

### Task 7.2 — the e2e harness trusts its own bridge gateway

`network-acl.spec.ts` simulates a non-local client with a spoofed `X-Real-IP` from the test runner.
Its first test pins that this works "in this container's topology". The peer the container sees is
the e2e network's bridge gateway (Probe A measured `172.25.0.1`; `e2e/README.md:355-363`). Under the
new default that peer is not trusted, so every test in the file loses its premise.

1. In `scripts/e2e_up.sh`, before the `docker run` at `:254`, resolve the gateway:
   `GATEWAY=$(docker network inspect "$NETWORK" -f '{{(index .IPAM.Config 0).Gateway}}')`, fail
   loudly if it is empty, and pass `-e DISPATCHARR_TRUSTED_PROXIES="$GATEWAY"`. That is what a
   deployment behind a proxy does, which makes the e2e topology a configured one instead of a
   default one.
2. Note in the script's comment that a container created before this change keeps its old
   environment; `--down` or `--recreate` picks it up (the existing `docker start` branch at `:248`).
3. Update the prose, not the assertions: `network-acl.spec.ts:20-35` and its first test's comment
   and `failureContext` (`:100-120`), `e2e/README.md:355-363`, and the `e2e/COVERAGE.md:170` row.
   Each now says the trust comes from `scripts/e2e_up.sh` setting `DISPATCHARR_TRUSTED_PROXIES` to
   the bridge gateway, not from the default. No `expect(...)` in the file changes.
4. Run the `seeded` project locally with `--recreate` on the fixed tree. `network-acl.spec.ts` stays
   green. Then run it once more with the `-e` line removed: its first test fails with its own
   `failureContext` message. That confirms the harness change, not the default, is what the file now
   depends on. Restore the line.

### Task 7.3 — the docs

The four compose comment blocks each read "When unset, private/loopback peers may set X-Real-IP /
X-Forwarded-For (typical Docker/Traefik setups)." Replace that sentence with "When unset, only
loopback peers may set X-Real-IP / X-Forwarded-For. Behind a reverse proxy such as Traefik, set this
to the proxy's IP/CIDR." Leave the two example lines as they are. These are comment-only edits, so
no test applies.

`README.md:109`: "defaults trust private/loopback peers" becomes "defaults trust loopback peers
only; set it to your proxy's address or CIDR, or the whole private range if you must, when running
behind one". Add one line to the PR description as an upgrade note. There is no fork CHANGELOG
convention; do not edit `CHANGELOG.md`, which is upstream's.

### PR description draft

> **fix(security): trust forwarded client addresses from loopback peers only**
>
> Closes #182.
>
> `get_client_ip` believed `X-Real-IP` and `X-Forwarded-For` from any private-network peer. On
> every `uwsgi_pass` location the peer is the client itself, and nginx forwards the client's own
> headers there, so a LAN client could claim any address to the network ACL, the setup gate, the
> login throttle and the event log. The default now trusts loopback only.
>
> **Upgrade note.** A deployment behind a reverse proxy on a Docker network, that has not set
> `DISPATCHARR_TRUSTED_PROXIES`, will now see the proxy's address for every client. Under the
> default `M3U_EPG` ACL that means public clients are **allowed**, because the proxy's address is
> private. Such a deployment must set `DISPATCHARR_TRUSTED_PROXIES` to the proxy's address.
>
> The e2e harness now sets it to its own bridge gateway, which is how its network-ACL tests have
> simulated a non-local client all along.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## Open questions

**Q1 — #182: is the fail-open on upgrade acceptable?** Two readings lead to different PRs.

- **(a) Loopback-only default (PR B-7 as written).** Closes the spoof for every default install.
  Behind an unconfigured outer proxy, every client looks like the proxy. The `M3U_EPG` default ACL
  then admits public clients, and every per-IP limit collapses into one bucket. The operator must
  set `DISPATCHARR_TRUSTED_PROXIES`.
- **(b) Keep the default, warn.** Change nothing in `get_client_ip`. Log one WARNING at startup when
  the variable is unset, saying a LAN client can spoof its address and naming the variable. Nothing
  breaks and nothing is closed.
- **(c) Narrow the default to the Docker bridge range.** Trust `127.0.0.0/8`, `::1/128` and
  `172.16.0.0/12` only. Traefik-in-Docker usually lives there and keeps working. A LAN client on
  `192.168.0.0/16` or `10.0.0.0/8` can no longer spoof. A LAN on `172.16.0.0/12` still can, and
  Docker sometimes allocates from `192.168.0.0/16` when its pool is exhausted. A heuristic, not a
  rule.

**Recommendation: (a)**, because it is the issue's own stated direction and the only one that is a
rule rather than a guess, provided the upgrade note ships in the PR description and the README. If
the user wants no install to change behaviour on upgrade, (b) is the honest alternative; (c) is not
recommended. **(a) is the only option under which `network-acl.spec.ts`'s first test changes
meaning.** Under (a) it pins configured trust. Under (b) and (c) it still pins the default.

**What PR B-7 becomes under each ruling.**

- **(a)** As written above.
- **(b)** No default change, no flip and no e2e change. Branch `fix/B-7-trusted-proxies-warning`.
  Files: `dispatcharr/utils.py`, `core/tests/test_core.py` and `README.md`. `_trusted_proxy_networks()` logs one
  WARNING, once per process, the first time it runs with `TRUSTED_PROXIES_ENV` unset. The message
  names the variable and says a LAN client can set its own address. Add one test,
  `test_an_unset_trusted_proxies_env_warned_nothing`, with `assertLogs` on the `dispatcharr.utils`
  logger. Its `setUp` sets `dispatcharr.utils._trusted_proxies_key = None`. The function returns
  early when the key is unchanged (`utils.py:322-323`), so the warning fires once per process. Any
  earlier test in the same process that built the default would otherwise leave `assertLogs` with
  nothing to see (memory: warm state hides a query). Break-check: delete the warning, and the test reddens. #182 then closes as `wontfix` with
  a comment linking the PR. There is no ledger row to annotate, because #182 has none. `README.md:109`
  gains one sentence about the warning. Labels: all fifteen, because `dispatcharr/` is a shared
  prefix.
- **(c)** The default tuple becomes `("127.0.0.0/8", "::1/128", "172.16.0.0/12")`. The Task 7.1
  flip must change its peer. `172.18.0.1` is inside `172.16.0.0/12`, so a flip on that peer would
  pass before the fix, and break-check 7.1.4 could not redden. Use peer `192.168.1.10`. Add a
  **second flip** with peer `10.0.0.5`, asserting that the peer is returned. `10.0.0.0/8` is trusted
  today, so this test fails before the fix too; expect two red tests, not one. Add a control for a
  `172.18.0.1` peer, asserting that its header is honoured. It passes before and after. Break-check:
  put `192.168.0.0/16` back in the tuple, and only the `192.168.1.10` test reddens. **Keep Task 7.2 anyway.** Docker
  sometimes allocates the e2e network from `192.168.0.0/16`, so explicit trust in `e2e_up.sh`
  beats relying on Docker's pool. The compose comments and the README describe the bridge-range
  default rather than loopback only. Branch `migration/B-7-trusted-proxies-bridge`.

No other item has two readings that change the plan. Assumptions taken instead of questions:
#134 logs network refusals only, under `login_failed`; #110 leaves episodes alone because the model
has nothing to filter on; #61 fixes the two live builders and files the VOD ones.

## Follow-ups for the lead to file

1. The three VOD handlers B-1 touches log the exception text, and so the provider URL, unredacted at
   ERROR (`views.py:861`, `:1076`; `multi_worker_connection_manager.py:1387`). #295's shape.
2. Raw XC credential interpolation in the VOD builders: `apps/vod/models.py:260`, `:309`, and
   `core/xtream_codes.py:278-286`. #61's shape.
3. `apps/output/views.py:311` builds Dispatcharr's own XC URLs for its users with raw credentials.
   Encoding them needs Dispatcharr's own XC routes to accept the encoded form. Coordinate with E-#80.
4. `get_transformed_credentials` (`apps/m3u/tasks.py:3088-3120`) parses credentials back out of a
   synthetic URL by path segment, which breaks for a credential containing `/`.

## Coverage table

| Issue | Where |
|---|---|
| #61 | PR B-5 |
| #82 | Closed by maintainer 2026-09-23 (design decision). Ledger title clause in PR B-3, Task 3.2 |
| #83 | PR B-3 |
| #84 | PR B-2 |
| #89 | PR B-1 (and #186 closed as superseded by it) |
| #103 | PR B-4 |
| #104 | PR B-4 |
| #105 | PR B-4 |
| #110 | PR B-1 |
| #134 | PR B-2 |
| #182 | PR B-7, gated on Q1 |
| #204 | PR B-6 |
| #205 | PR B-6 |

---

## Appendices

Each appendix is a diff against the seed `a54b09a9`. Context lines are copied from the seed. The
implementer re-greps each anchor before applying, because an earlier B PR may have moved lines.

### Appendix A — #89, the three bodies (PR B-1, Task 1.1)

```diff
--- a/apps/proxy/vod_proxy/views.py
+++ b/apps/proxy/vod_proxy/views.py
@@ -860,3 +860,3 @@
     except Exception as e:
         logger.error(f"[VOD-EXCEPTION] Error streaming {content_type} {content_id}: {e}", exc_info=True)
-        return HttpResponse(f"Streaming error: {str(e)}", status=500)
+        return HttpResponse("Streaming error", status=500)
@@ -1075,3 +1075,3 @@
     except Exception as e:
         logger.error(f"[VOD-HEAD] Error in HEAD request: {e}", exc_info=True)
-        return HttpResponse(f"HEAD error: {str(e)}", status=500)
+        return HttpResponse("HEAD error", status=500)
--- a/apps/proxy/vod_proxy/multi_worker_connection_manager.py
+++ b/apps/proxy/vod_proxy/multi_worker_connection_manager.py
@@ -1407,3 +1407,3 @@
                         logger.error(f"[{client_id}] Error during cleanup after connection failure: {cleanup_error}")
 
-            return HttpResponse(f"Streaming error: {str(e)}", status=500)
+            return HttpResponse("Streaming error", status=500)
```

### Appendix B — #110, the helper and its three calls (PR B-1, Task 1.2)

```diff
--- a/apps/proxy/vod_proxy/views.py
+++ b/apps/proxy/vod_proxy/views.py
@@ -61,6 +61,24 @@
 def _content_type_for_obj(content_obj):
     ...
 
+
+def _hidden_adult_movie(user, content_type, content_obj):
+    """True when this user may not stream this movie because of hide_adult_content.
+
+    The same predicate xc_get_vod_streams and xc_get_vod_info apply to the
+    listings (apps/output/views.py): non-admin, the preference set, the movie
+    flagged. Only Movie carries is_adult; Series and Episode have no such
+    field, so nothing else is hidden and nothing else is refused (#110).
+    """
+    if user is None or content_type != "movie":
+        return False
+    if user.user_level >= User.UserLevel.ADMIN:
+        return False
+    if not (user.custom_properties or {}).get("hide_adult_content", False):
+        return False
+    return bool(getattr(content_obj, "is_adult", False))
+
+
+def _adult_refusal():
+    return authorize_error_response(AuthorizeDenied(403, "Forbidden"))
```

Call sites, each immediately after the object is known:

- `stream_vod`, Redirect branch, after the `if not selected:` block (seed `:760-766`):
  `if _hidden_adult_movie(user, content_type, selected["content_obj"]): return _adult_refusal()`
- `stream_vod`, session branch, after the `if not selected:` block (seed `:812-818`): the same line.
- `stream_vod`, first request, immediately before `if not session_id:` (seed `:724`). It is
  gated on `not session_id` itself, so it runs on the first request only and never shadows call (3):
  ```python
  if not session_id and user is not None and content_type == "movie":
      movie = Movie.objects.filter(uuid=content_id).only("is_adult").first()
      if _hidden_adult_movie(user, content_type, movie):
          return _adult_refusal()
  ```
  `Movie` is already imported in `views.py`; `_content_type_for_obj` uses it at `:63`. A non-UUID
  `content_id` would raise `ValidationError` in `filter(uuid=...)`. So guard the lookup with
  `uuid.UUID(str(content_id))` in a `try`, the way `authorize.py:389-400` does, and skip the check on
  failure (`views.py` has no `import uuid` yet; add it at module level). No real request can reach
  that failure. The `/proxy/vod/` routes capture `<uuid:content_id>` (`apps/proxy/vod_proxy/urls.py:9-14`),
  and the XC route passes `movie_relation.movie.uuid`. The guard exists for direct callers such as
  `test_vod_redirect.py`, which passes `content_id="uuid"`. Those callers pass no user today, so they
  never reach the lookup, but a guard costs less than a 500 the day one does.
- `stream_xc_movie`, after the `except` at seed `:1437-1438` and before `return stream_vod(` at `:1440`:
  `if _hidden_adult_movie(decision.user, "movie", movie_relation.movie): return _adult_refusal()`

`User` is already imported at module level in `views.py` (`:21`).

### Appendix C — #84 and #134, `xc_authenticate` (PR B-2)

```diff
--- a/apps/output/views.py
+++ b/apps/output/views.py
@@ -357,21 +357,40 @@
-def xc_get_user(request):
-    username = request.GET.get("username")
-    password = request.GET.get("password")
-
-    if not username or not password:
-        return None
-
-    user = get_object_or_404(User, username=username)
-
-    custom_properties = user.custom_properties or {}
-
-    if "xc_password" not in custom_properties:
-        return None
-
-    if custom_properties["xc_password"] != password:
-        return None
-
-    if not network_access_allowed(request, 'XC_API', user):
-        return None
-
-    return user
+XC_DENIED_CREDENTIALS = 401
+XC_DENIED_NETWORK = 403
+
+
+def xc_authenticate(request):
+    """(user, None) on success, else (None, 401) or (None, 403).
+
+    401 means the credentials did not resolve: an unknown username, no
+    xc_password, or a wrong one are deliberately indistinguishable (#84).
+    403 means they did, and the XC_API network ACL refused this client for
+    this user (#134). The credential check is resolve_xc_user's, the same
+    constant-time comparison every streaming surface uses.
+    """
+    from apps.proxy.authorize import resolve_xc_user
+
+    username = request.GET.get("username")
+    password = request.GET.get("password")
+    if not username or not password:
+        return None, XC_DENIED_CREDENTIALS
+    user = resolve_xc_user(username, password)
+    if user is None:
+        return None, XC_DENIED_CREDENTIALS
+    if not network_access_allowed(request, 'XC_API', user):
+        return None, XC_DENIED_NETWORK
+    return user, None
+
+
+def xc_get_user(request):
+    """The authenticated XC user, or None. For callers that have already refused."""
+    user, _denied = xc_authenticate(request)
+    return user
```

The four views follow one shape. `xc_player_api` shown; `xc_panel_api` is the same with
`endpoint="panel_api"`. `xc_get` and `xc_xmltv` keep their existing pre-check and their existing
`m3u_blocked`/`epg_blocked` event, and gain an `elif denied == XC_DENIED_NETWORK` arm that logs the
same event type with `reason='Network access denied (XC API)'` and answers 403.

```python
def _xc_network_refused(request, endpoint):
    log_system_event(
        event_type='login_failed',
        user=request.GET.get('username', 'unknown'),
        reason='Network access denied (XC API)',
        endpoint=endpoint,
        client_ip=get_client_ip(request) or "unknown",
        user_agent=request.META.get('HTTP_USER_AGENT', 'unknown'),
    )
    return JsonResponse({'error': 'Forbidden'}, status=403)


def xc_player_api(request, full=False):
    if not network_access_allowed(request, 'XC_API'):
        return _xc_network_refused(request, 'player_api')
    action = request.GET.get("action")
    user, denied = xc_authenticate(request)
    if denied == XC_DENIED_NETWORK:
        return _xc_network_refused(request, 'player_api')
    if user is None:
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    ...  # the action dispatch, unchanged
```

`xc_get` keeps its global pre-check and gains the network arm **before** its existing
credentials arm. `xc_xmltv` mirrors it exactly, with `event_type='epg_blocked'`:

```python
def xc_get(request):
    if not network_access_allowed(request, 'XC_API'):
        ...  # unchanged: m3u_blocked, 'Network access denied (XC API)', 403

    action = request.GET.get("action")
    user, denied = xc_authenticate(request)

    if denied == XC_DENIED_NETWORK:
        log_system_event(
            event_type='m3u_blocked',
            user=request.GET.get('username', 'unknown'),
            reason='Network access denied (XC API)',
            client_ip=get_client_ip(request) or "unknown",
            user_agent=request.META.get('HTTP_USER_AGENT', 'unknown'),
        )
        return JsonResponse({'error': 'Forbidden'}, status=403)

    if user is None:
        ...  # unchanged: m3u_blocked, 'Invalid XC credentials', 401

    return generate_m3u(request, None, user)
```

The order matters. The network arm has to come first, because the credentials arm treats any `None`
user as a bad password.

`log_system_event` is already imported at module level (`apps/output/views.py:27`). The function-local
`from core.utils import log_system_event` lines inside `xc_get` and `xc_xmltv` can stay; removing
them is not this PR's business. `get_object_or_404` stays imported; other views use it.

The import of `resolve_xc_user` is function-local. `apps/output/views.py` already imports
`apps.proxy.utils` at module level (`:24`), so a module-level import would also work; function-local
keeps the module's import-time graph unchanged, which is the cheaper thing to be sure of. The
collector counts the statement either way.

### Appendix D — #83, `device.xml` (PR B-3)

```diff
--- a/apps/hdhr/api_views.py
+++ b/apps/hdhr/api_views.py
@@ -215,13 +215,19 @@
     def get(self, request):
         blocked = _hdhr_network_check(request)
         if blocked is not None:
             return blocked
 
         base_url = build_absolute_uri_with_port(request, "/hdhr/").rstrip("/")
+        # The same row discover.json reads (DiscoverAPIView, above), so the
+        # two documents agree on the device's identity (#83).
+        device = HDHRDevice.objects.first()
+        device_id = escape(device.device_id) if device else "12345678"
+        friendly_name = escape(device.friendly_name) if device else "Dispatcharr HDHomeRun"
 
         xml_response = f"""<?xml version="1.0" encoding="utf-8"?>
         <root>
-            <DeviceID>12345678</DeviceID>
-            <FriendlyName>Dispatcharr HDHomeRun</FriendlyName>
+            <DeviceID>{device_id}</DeviceID>
+            <FriendlyName>{friendly_name}</FriendlyName>
```

Plus `from xml.sax.saxutils import escape` at the top of the file.

### Appendix E — #103–#105, `fetch_outbound_http` (PR B-4)

```python
# core/http_security.py, appended
import requests
from urllib.parse import urljoin

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


def fetch_outbound_http(url, *, allow_private=False, allow_loopback=False,
                        max_redirects=5, **kwargs):
    """requests.get that validates every hop, not just the first.

    requests follows redirects by default, and validate_outbound_http_url
    only ever sees the URL it is handed, so a public URL answering 302 to
    169.254.169.254 used to be followed (#103-#105). Each hop here is fetched
    with allow_redirects=False and its Location validated before it is
    followed. DNS can still change between a hop's check and its connect;
    that residual is accepted for this module's callers.
    """
    kwargs.pop("allow_redirects", None)
    current = url
    for _hop in range(max_redirects + 1):
        validate_outbound_http_url(
            current, allow_private=allow_private, allow_loopback=allow_loopback
        )
        resp = requests.get(current, allow_redirects=False, **kwargs)
        if resp.status_code not in _REDIRECT_STATUSES:
            return resp
        location = resp.headers.get("Location")
        resp.close()
        if not location:
            raise ValueError("Redirect without a Location header.")
        current = urljoin(current, location)
    raise ValueError(f"More than {max_redirects} redirects.")
```

Call sites in `apps/plugins/api_views.py`:

```diff
@@ -777,5 +777,4 @@
 def _fetch_manifest(url, public_key_text=None):
     """Fetch a remote manifest JSON, validate structure, return (data, verified)."""
-    _validate_fetch_url(url)
-    with http_requests.get(url, timeout=MANIFEST_FETCH_TIMEOUT, stream=True) as resp:
+    with _fetch(url, timeout=MANIFEST_FETCH_TIMEOUT, stream=True) as resp:
@@ -1149 +1148 @@
-            resp = http_requests.get(manifest_url, timeout=MANIFEST_FETCH_TIMEOUT)
+            resp = _fetch(manifest_url, timeout=MANIFEST_FETCH_TIMEOUT)
@@ -1267 +1266 @@
-            resp = http_requests.get(download_url, timeout=60, stream=True)
+            resp = _fetch(download_url, timeout=60, stream=True)
```

Before removing `_fetch_manifest`'s own `_validate_fetch_url` call, confirm each of its four callers
(`:817`, `:862`, `:984`, `apps/plugins/tasks.py:20`) handles `ValueError` from it the way it handled
the validator's. They catch it or let the Celery task fail today; the helper raises the same type.
The manifest-detail view at `:1149` catches `Exception` at `:1182-1187` and answers 502 with
`f"Failed to fetch plugin manifest: {e}"`. A refused redirect hop therefore reaches the admin as
a 502 naming the refused address. That is acceptable and unchanged in kind: the view is `IsAdmin`,
the URL is the admin's own input, and the same view already returns the validator's message as a
400 at `:1140-1141`. This PR does not change that handler.

### Appendix F — #61 (PR B-5)

```diff
--- a/apps/m3u/tasks.py
+++ b/apps/m3u/tasks.py
@@ -942,4 +942,6 @@
             stream_url_prefix = (
                 f"{xc_client.server_url.rstrip('/')}/live/"
-                f"{xc_client.username}/{xc_client.password}/"
+                # Quoted as build_timeshift_url_format_b quotes them (#61).
+                f"{quote(str(xc_client.username), safe='')}/"
+                f"{quote(str(xc_client.password), safe='')}/"
             )
--- a/apps/proxy/next_source.py
+++ b/apps/proxy/next_source.py
@@ -61,3 +61,6 @@
         if server_url and username and password:
             base = server_url.rstrip("/")
-            return f"{base}/live/{username}/{password}/{stream.stream_id}.ts"
+            return (
+                f"{base}/live/{quote(str(username), safe='')}"
+                f"/{quote(str(password), safe='')}/{stream.stream_id}.ts"
+            )
```

`apps/m3u/tasks.py` imports `urllib.parse` only function-locally, inside `get_transformed_credentials`
(`:3060`), so `collect_xc_streams` has no binding for it. Add `from urllib.parse import quote` at
module level in both files and write the `tasks.py` hunk as `quote(...)`, not
`urllib.parse.quote(...)`.

### Appendix G — #204/#205, `securePassword.js` (PR B-6)

```js
// frontend/src/utils/securePassword.js
const ALPHABET =
  'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
// 248 = 4 * 62: the largest multiple of the alphabet size below 256. A byte
// at or above it is discarded, so every character is equally likely.
const LIMIT = 256 - (256 % ALPHABET.length);

export function generateSecurePassword(length = 20) {
  let out = '';
  const buf = new Uint8Array(length * 2);
  while (out.length < length) {
    globalThis.crypto.getRandomValues(buf);
    for (const byte of buf) {
      if (byte < LIMIT) out += ALPHABET[byte % ALPHABET.length];
      if (out.length === length) break;
    }
  }
  return out;
}
```

`User.jsx:77` becomes `payload.password = generateSecurePassword();` and `:109` becomes
`xc_password: generateSecurePassword(),`, with the import added.

### Appendix H — #182, the default (PR B-7)

```diff
--- a/dispatcharr/utils.py
+++ b/dispatcharr/utils.py
@@ -298,15 +298,19 @@
 def _trusted_proxy_networks():
     """Return networks whose peers may set X-Real-IP / X-Forwarded-For.
 
-    When DISPATCHARR_TRUSTED_PROXIES is unset, defaults to LOCAL_NETWORK_CIDRS
-    so Docker/Traefik-style reverse proxies on private networks work without
-    configuration. Set the env to a comma-separated IP/CIDR list to narrow
-    trust, or to none / off / false / empty to trust no proxy headers.
+    When DISPATCHARR_TRUSTED_PROXIES is unset, only loopback peers are
+    trusted. On nginx's uwsgi_pass locations REMOTE_ADDR is the client
+    itself and nginx forwards the client's own X-Real-IP, so trusting every
+    private peer let a LAN client choose its own address (#182). Behind a
+    reverse proxy, set the env to that proxy's IP/CIDR; set it to none / off
+    / false / empty to trust no proxy headers at all.
     """
     global _trusted_proxies_key, _trusted_proxies_networks
 
     if TRUSTED_PROXIES_ENV not in os.environ:
-        key = "__default_local__"
-        source = LOCAL_NETWORK_CIDRS
+        key = "__default_loopback__"
+        source = _DEFAULT_TRUSTED_PROXIES
```

with `_DEFAULT_TRUSTED_PROXIES = ("127.0.0.0/8", "::1/128")` beside `LOCAL_NETWORK_CIDRS`, and the
`get_client_ip` docstring (`:343-350`) updated to match. `LOCAL_NETWORK_CIDRS` itself is unchanged;
the `M3U_EPG` default and `setup_ip_allowed` still use it.
