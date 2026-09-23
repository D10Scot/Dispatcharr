# Fix plan, category F — frontend

**Category.** F, frontend (the React 19 + Mantine 8 SPA in `frontend/`). Five tracker issues: #58,
#62, #65, #73, #137.

**Seed SHA.** `a54b09a9` (`main`, 2026-09-23, "metrics(curated): the Phase 2 phase-done milestone
row (#342)"). Every `file:line` below was opened at that SHA. Line numbers drift, so each task's
first step re-greps its anchor rather than trusting the number.

**Ordering position.** Tenth and last (B, A, J, C, D, E, G, H, I, F). No earlier category changes a
product file this plan changes (§ Overlap). Two non-product files are shared. In `e2e/COVERAGE.md`,
B, D and H edit other rows. In `e2e/tests/frontend/dvr.spec.ts`, E-3 makes comment-only edits and
F-3 changes one locator and its comment.

**Shape.** Three PRs, plus a fourth that is optional and waits on Open question Q1.

| PR | Branch | Issues | Size |
|---|---|---|---|
| F-1 | `fix/F-1-deep-link-routing` | #58 | M |
| F-2 | `fix/F-2-connect-badge-key` | #62 | S |
| F-3 | `fix/F-3-accessible-names` | #65, #73, #137 | M |
| F-4 (only if Q1 is yes) | `fix/F-4-accessible-name-ratchet` | none; guards F-3 | S |

None of these PRs touches `docker/`, `relay/httpapi/` or `docker/nginx.conf`, so none takes a
`migration/` branch name (brief rule 3). None maps to a backend test label:
`python3 scripts/ci_backend_test_labels.py frontend/src/App.jsx e2e/tests/frontend/helpers.ts e2e/COVERAGE.md frontend/src/components/tables/UsersTable.jsx`
prints `[]` at the seed.

**Two findings the plan rests on, both measured at the seed in this plan's worktree and never
committed.**

1. **Upstream has already fixed #58, and its fix applies cleanly here but is incomplete.** Upstream
   `Dispatcharr/Dispatcharr` merged "Fix/UI routing" (#1578, commit `5d0ec618f8`, 2026-08-20). The
   fork does not have it: `frontend/src/utils/loginRedirect.js` does not exist at `a54b09a9`.
   `git apply --check --exclude=CHANGELOG.md` of that commit's diff succeeds on the seed. Upstream's
   `isCheckingAuth` gate fixes the case #58 reports, where a valid session loads a deep link.
   **Its redirect-back after sign-in does not work.** A test that renders the real `Login` page and
   the real `LoginForm` inside the real `App` lands on `/channels`, not on the requested `/stats`.
   The reason is that `LoginForm` is the only reader of `?next=`. The sign-in that sets
   `isAuthenticated` also removes the `/login` route in the same render, so `LoginForm` unmounts
   before its effect runs. PR F-1 ports #1578 and adds a small fix for that.
2. **Every existing test of an F-3 component mocks `@mantine/core`**, and every mock drops
   `aria-label` from its destructured props. Those mocks also stand in for the accessibility tree:
   the mocked `Switch` renders a plain checkbox where real Mantine renders `role="switch"`. A role
   query against those mocks would test the mock. So F-3's tests go in new sibling files that render
   the **real** `@mantine/core`. That recipe was prototyped on `BackupManager`, `UsersTable` and
   `StreamConnectionCard`, and the partial-real fallback on `Plugins`. Each file failed on the seed
   for the missing name, with its row or card visibly rendered, and passed once the labels were
   added. The existing mock-based test files for the three components passed unchanged beside them.

**Nothing in this plan is implemented.** The only file this branch commits is this document.

---

## Files this plan touches

| File | PRs | Issues |
|---|---|---|
| `frontend/src/App.jsx` | F-1 | #58 |
| `frontend/src/store/auth.jsx` (three lines, from the upstream port) | F-1 | #58 |
| `frontend/src/pages/Login.jsx` (one line, from the upstream port) | F-1 | #58 |
| `frontend/src/components/forms/LoginForm.jsx` (from the upstream port) | F-1 | #58 |
| `frontend/src/components/forms/__tests__/LoginForm.test.jsx` (from the upstream port) | F-1 | #58 |
| `frontend/src/utils/loginRedirect.js` (new, from the upstream port) | F-1 | #58 |
| `frontend/src/utils/__tests__/loginRedirect.test.js` (new) | F-1 | #58 |
| `frontend/src/__tests__/App.test.jsx` (new) | F-1 | #58 |
| `frontend/src/__tests__/App.signIn.test.jsx` (new) | F-1 | #58 |
| `e2e/tests/frontend/direct-navigation.spec.ts` (new) | F-1 | #58 |
| `e2e/tests/frontend/helpers.ts` (doc comments only) | F-1 | #58 |
| `e2e/tests/frontend/{logos,users,backups,stats,settings,connect,guide}.spec.ts` (comments only) | F-1 | #58 |
| `e2e/COVERAGE.md` (one new Frontend row after `:141`) | F-1 | #58 |
| `frontend/src/pages/Connect.jsx` (`:208`) | F-2 | #62 |
| `frontend/src/pages/__tests__/Connect.test.jsx` (one appended `it`) | F-2 | #62 |
| `e2e/tests/frontend/connect.spec.ts` (one comment sentence, `:255-257`) | F-2 | #62 |
| `frontend/src/components/tables/UsersTable.jsx` (`:60`, `:90`, `:100`) | F-3 | #65 |
| `frontend/src/components/tables/LogosTable.jsx` (`:60`, `:69`, `:461`) | F-3 | #65 |
| `frontend/src/components/cards/RecordingCard.jsx` (`:369-427`) | F-3 | #65 |
| `frontend/src/components/cards/StreamConnectionCard.jsx` (`:213`, `:581`, `:648`) | F-3 | #137 |
| `frontend/src/components/backups/BackupManager.jsx` (`:64`, `:76`, `:86`) | F-3 | #137 |
| `frontend/src/components/cards/PluginCard.jsx` (`:546`) | F-3 | #73 |
| `frontend/src/pages/Plugins.jsx` (`:493`) | F-3 | #73 |
| `frontend/src/components/cards/AvailablePluginCard.jsx` (`:1009`) | F-3 | #73 |
| Eight new `*.a11y.test.jsx` files beside the existing tests of the eight components above | F-3 | #65, #73, #137 |
| `e2e/tests/frontend/users.spec.ts` (`:152-175`, `:182`, `:193`, `:195-199`) | F-3 | #65 |
| `e2e/tests/frontend/dvr.spec.ts` (`:258-274`) | F-3 | #65 |
| `e2e/tests/frontend/plugins.spec.ts` (`:183-192`, `:289`) | F-3 | #73 |
| `frontend/src/__tests__/accessibleNames.ratchet.test.js` (new) | F-4 | none |

`frontend/src/components/forms/User.jsx` and `User.test.jsx` are **not** in this list. `User.jsx`
carries two icon-only `ActionIcon`s of the same shape (`:317`, `:376`), and they are left alone on
purpose so that this plan and B-6 never touch the same file (§ Overlap).

## Overlap

Checked against `sweep-report.md` and against every `origin/docs/fixplan-*` plan branch that
existed on 2026-09-23 (A2, B, C, D, E, H, J). Plans G and I had no branch yet, and their issue files
cite no `frontend/` or `e2e/tests/frontend/` path.

| File | Other plan | What that plan does there | What F does | First | Conflict handling |
|---|---|---|---|---|---|
| `frontend/src/components/forms/User.jsx`, `__tests__/User.test.jsx` | **B** (B-6, #204/#205) | Swaps `Math.random` for `generateSecurePassword` at `:77` and `:109`, and tightens one assertion. | Nothing. | B | None. F leaves `User.jsx`'s two unlabelled `ActionIcon`s for the follow-up list so that it never enters B-6's files. |
| `e2e/COVERAGE.md` | **B** (B-7, `:170`), **D** (rows 90, 93, 94, 97, 101, 125), **H** (Guards table, `:191`, `:200`, new Streaming and DVR rows) | Row-level edits in other sections. | F-1 inserts one Frontend row after `:141`. | B, D, H | Adjacent-line rebase only. F-1 re-greps the anchor row ("An archive uploaded through the Backups panel") rather than trusting `:141`. |
| `e2e/tests/frontend/dvr.spec.ts` | **E** (E-3, #71; E plan line 846 on `origin/docs/fixplan-E`) | Comment-only edits. E's plan names no line range. | F-3 replaces the cancel locator (`:274` at the seed) and the comment block above it (`:258-270`). | E | Rebase F-3 onto E-3's merge. Task 3.2 re-greps both anchors, `button:has(svg.lucide-square-x)` and "the same defect #65 already tracks", rather than trusting the seed lines. If E-3 rewrote that comment block, keep E's wording for anything about #71 and replace only the sentences about the missing accessible name. |
| `frontend/src/utils/pages/DVRUtils.js` | **E** (E-3, #71) | Changes the upcoming-card grouping key at `:68`. | Nothing. F-3 edits `RecordingCard.jsx`, which renders those cards. | E | None. E-3's plan mentions `RecordingCard.jsx` only in prose. |
| `frontend/src/components/forms/settings/ProxySettingsForm.jsx` | **E** (#257) | Proxy-settings defaults. | Nothing. | E | None. |

Inside category F, `e2e/tests/frontend/connect.spec.ts` is touched by F-1 (`:125-127`) and F-2
(`:255-257`), and `users.spec.ts` by F-1 (`:112-114`) and F-3 (`:152-201`). Every one of those is a
different comment or locator block. Land the PRs in order F-1, F-2, F-3, and rebase each on the
last.

## What the implementer runs

- **Worktree.** One worktree per PR, off `main`, anchored by absolute path (CLAUDE.md § Isolation).
  In each new worktree, run `cd <wt>/frontend && npm ci` first. For F-1 and F-3, which edit
  `e2e/**/*.ts`, also run `cd <wt>/e2e && npm ci`. **Without `node_modules` both hooks skip
  silently:** the vitest hook prints "Did NOT run", and the commit gate says frontend tests "were
  NOT run" and lets the commit through. If you see either message, the work is not verified.
- **The edit hook.** Editing any `frontend/**/*.test.jsx` or `*.test.js` runs **that file only**,
  and blocks on a failure. In a red-first step that block is the expected red, not a mistake.
  Editing a `.jsx` source file runs only eslint, which is advisory. So after a source edit, run the
  relevant test files yourself:
  ```bash
  cd <wt>/frontend && npx vitest --run <file> [<file> ...]
  ```
  Editing `e2e/**/*.ts` runs `tsc --noEmit` for the e2e package, which blocks.
- **Before every commit**, run the whole suite yourself. The commit gate runs it too, but reading its
  failure through the gate is slower:
  ```bash
  cd <wt>/frontend && npx vitest --run
  ```
  At the seed that is 203 files and 6,134 tests, all passing, in about 19 seconds. Each PR section
  gives its expected count.
- **The e2e guards** are static analysis and need no container. Run them after any
  `e2e/tests/frontend/` edit:
  ```bash
  cd <wt>/e2e && npx playwright test --project=guards
  ```
- **The e2e `frontend` project** runs in CI on every PR that touches `frontend/` or `e2e/`
  (`.github/workflows/e2e-tests.yml:110`), under the required `E2E result`. **For F-1 and F-3, run
  the affected specs locally before pushing.** A failure found only in CI costs a slow round.
  Because other agents may have e2e stacks up in this session, start your own stack with its own
  image tag, so that `e2e_up.sh` builds this worktree's frontend. It builds the AIO image only
  when the tag is absent (`scripts/e2e_up.sh:143-145`), and the default tag is shared. Put
  everything on one command line, because shell variables do not persist between Bash calls:
  ```bash
  cd <wt> && DISPATCHARR_E2E_IMAGE=dispatcharr-e2e:fix-F-<n> DISPATCHARR_E2E_CONTAINER=dispatcharr-e2e-f<n> DISPATCHARR_E2E_VOLUME=dispatcharr-e2e-f<n>-data DISPATCHARR_E2E_NETWORK=dispatcharr-e2e-f<n>-net DISPATCHARR_E2E_PORT=<port> ./scripts/e2e_up.sh
  cd <wt>/e2e && npx playwright install chromium && E2E_BASE_URL=http://localhost:<port> npx playwright test --project=frontend <spec files>
  ```
  Use `<port>` 9195 for F-1 and 9197 for F-3, after checking with `docker ps` that nothing else
  publishes it. The first build of the AIO image takes several minutes. The `frontend` project depends on
  `bootstrap`, which Playwright runs first. When you are done, remove only your own stack:
  ```bash
  docker rm -f dispatcharr-e2e-f<n> && docker volume rm dispatcharr-e2e-f<n>-data && docker network rm dispatcharr-e2e-f<n>-net
  ```
  **Never run `e2e_up.sh --reset`, `--down` or `--stop` in this session**, with or without the
  overrides. `--reset` and `--down` call `destroy()` (`scripts/e2e_up.sh:68-73`), which also
  removes the shared fake provider `e2e-upstream`. `--stop` does not call `destroy()`, but it
  runs `docker stop` on that same provider directly (`:120-127`). Either way the overrides do not
  protect it, and every other agent's run breaks mid-test (#168). For the same reason, if an `e2e-upstream` container is already running (`docker ps
  --filter name=e2e-upstream`), add `DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD=1` to the first command.
  Otherwise a rebuild whose image id differs recreates that shared container
  (`scripts/e2e_up.sh:181-194`).
- **Formatting and lint.** `npx prettier --write <files>`. Then `npx eslint <files>`, which is
  advisory: about 112 errors already exist, and lint is commented out in CI
  (`.github/workflows/frontend-tests.yml:117-118`).
- **Commits.** Stage and commit in separate Bash calls. Write the message with the Write tool and
  commit with `git commit -F <file>`.
- **Stuck.** Escalate a stuck implementer from `sonnet` to `opus`. The real-Mantine test files are
  the part most likely to need it, because each one must re-create its component's store mocks.

---

## Per issue

### #58 — a direct load of a protected route other than /channels lands on /channels

- **Root cause.** `frontend/src/store/auth.jsx:28-29` starts `isAuthenticated` and `isInitialized` as
  `false` on every page load. They become `true` only when `checkAuth()` (`App.jsx:84-104`) has run
  `initializeAuth()` and then `initData()` (`auth.jsx:137-141`). Until then, `App.jsx:150-170`
  registers only `/login`. Every other URL matches the catch-all at `App.jsx:171-183`, whose
  `<Navigate replace>` sends the browser to `/login` and overwrites the requested URL. When the
  check resolves, the URL is `/login`, which the authenticated branch does not register. The
  catch-all fires again, now targeting `defaultRoute = '/channels'` (`App.jsx:40`). A reload
  behaves exactly like a deep link, because it is also a fresh document load, as the reporter's
  second comment records for `/settings#user-agents`.
- **The fix.** Port upstream #1578 as it stands. It adds an `isCheckingAuth` store flag that starts
  `true`, and `App` renders `LoginLoadingCard` instead of `<Routes>` while it is set. Nothing
  navigates while the check runs, so the requested URL survives. An unauthenticated deep link goes
  to `/login?next=<path>` through `getSafeNextPath`. Then make two changes on top.
  - **The authenticated catch-all reads `?next=`.** A new `AuthedRedirect` navigates to
    `getSafeNextPath(next) || defaultRoute`. Without it, the redirect-back never fires (finding 1
    above).
  - **`LoginRedirect` also carries the hash**, so `/settings#backups` survives sign-in too.
  Appendix A holds both hunks.
- **Why port rather than write it fresh.** The port applies cleanly, keeps the fork one commit
  closer to upstream, and brings upstream's own `LoginForm` tests with it. The first prototype for
  this plan carried the requested location in router state instead of `?next=`. It passed the same
  `App` tests, but it would have diverged from upstream for no behavioural gain.
- **Tests.**
  - New `frontend/src/__tests__/App.test.jsx`, seven tests (Appendix B). It uses the real `App` and
    the real `useAuthStore`, with its three actions stubbed, and stub pages. On the seed's
    `App.jsx`, five of the seven fail. Two pass there, and both are meant to: the default route
    for an unknown path, which must not change, and the `/login`-chain test, which pins
    `getSafeNextPath`'s use and ends on `/channels` on the seed as well.
  - New `frontend/src/__tests__/App.signIn.test.jsx`, one test (Appendix C). It uses the real
    `Login` page and the real `LoginForm`. It fails on the seed, and it also fails on the bare
    upstream port, landing on `/channels`. It passes once `AuthedRedirect` is added.
  - New `frontend/src/utils/__tests__/loginRedirect.test.js`, the `getSafeNextPath` table
    (Appendix D).
  - `LoginForm.test.jsx` changes as the port brings it. One assertion changes, listed in PR F-1.
  - New e2e `e2e/tests/frontend/direct-navigation.spec.ts` (Appendix E). It makes a real
    `page.goto` of every surface in `SURFACES`, then reloads a settings section.
- **Size** M. **Upstreamable**: as a whole, no, because the port is already upstream and the e2e
  suite is fork-only. The `AuthedRedirect` and hash hunks, on their own, apply to upstream `dev`'s
  `App.jsx`, whose authenticated catch-all is still `<Navigate to={defaultRoute} replace />` and
  whose `LoginRedirect` still omits the hash. They fix an upstream defect (§ Follow-ups).
- **Duplicates.** None in the fork. Upstream's own tracker filed the same defect as #715, #1526 and
  #1576, and #1578 closed all three. Those numbers belong to the upstream tracker, not this fork's.

### #62 — Connect subscription badges render without a React key

- **Root cause.** `frontend/src/pages/Connect.jsx:205-212` maps `integration.subscriptions` to
  `<Badge>` elements (`:208`) with no `key`. React therefore reconciles the badges by index. Removing
  an earlier badge makes React reuse its DOM node for the next subscription and delete the later
  node instead.
- **The fix.** `key={sub.id}`. The serializer always sends `id`
  (`apps/connect/serializers.py:6-15`, `EventSubscriptionSerializer.Meta.fields`). `sub.event` would
  be a weaker key: nothing makes `(integration, event)` unique, because `EventSubscription`
  (`apps/connect/models.py:37-42`) declares neither `unique_together` nor a constraint.
- **Tests.** One new `it` in the existing `Connect.test.jsx` (Appendix F). It renders two enabled
  subscriptions, keeps a reference to the second badge's DOM node, and re-renders without the
  first. It then asserts that the same node now shows the second badge's text. On the seed it fails
  because the node is a different element that "serializes to the same string". It passes with the
  key. No existing test changes.
- **Why not assert on the console warning.** React deduplicates its missing-key warning per owner
  component for the life of the module. `Connect.test.jsx` renders the keyless list in most of its
  tests, because `makeIntegration`'s default fixture (`:111-120`) carries an enabled subscription.
  A console spy added later in that file could therefore see no warning even before the fix, and
  pass for the wrong reason. The reporter's own follow-up comment on #62
  asks for exactly this: verify reconciliation, not the console. E2E cannot see the warning at all,
  because the e2e image is a production build (`e2e/COVERAGE.md:138`).
- **Size** S. **Upstreamable** yes. Upstream `dev`'s `Connect.jsx:204-208` has the same keyless
  `.map`.
- **Duplicates.** None. The `wontfix` label came from a triage-bot comment about the ownership
  lease, and the user removed it on 2026-09-23.

### #65 — icon-only row actions have no accessible name (Users, Logos, DVR)

- **Root cause.** A Mantine `ActionIcon` renders a `<button>` whose only child is an SVG, and no
  site passes `aria-label`, `aria-labelledby` or `title`. A wrapping `Tooltip` adds
  `aria-describedby` on hover and never a name. A probe with real Mantine in jsdom confirmed this:
  `<Tooltip label="Stop"><ActionIcon>x</ActionIcon></Tooltip>` is named `x`, its child text, and
  nothing else. The sites:
  - `UsersTable.jsx:90` and `:100`, the row's edit and delete.
  - `UsersTable.jsx:60`, the XC-password eye toggle in the same table. The reporter did not list it,
    but `users.spec.ts:171-172` names it as "the only other button a row can carry".
  - `LogosTable.jsx:60` and `:69`, edit and delete. `LogosTable.jsx:461`, the open-URL button in
    the same table.
  - `RecordingCard.jsx:419`, cancel or delete. `:373` and `:400`, extend and stop. The reporter
    named all three in their third comment.
- **The fix.** One `aria-label` per control, following the naming rule in PR F-3. `RecordingCard`'s
  delete tooltip is a three-way ternary (`:410-418`). It moves into a `deleteLabel` constant that
  both the `Tooltip` and the `aria-label` read, so the two cannot drift apart.
- **Tests.** New `UsersTable.a11y.test.jsx`, `LogosTable.a11y.test.jsx` and
  `RecordingCard.a11y.test.jsx`, rendering real Mantine. Two e2e locator swaps: `users.spec.ts`
  drops its positional `.nth(0)` and `.nth(1)`, and `dvr.spec.ts` drops its lucide-class selector.
  Both are listed in PR F-3.
- **Size** M, shared with #73 and #137. **Upstreamable** yes for the product hunks. A `patch
  --dry-run` of this plan's prototype hunks for `UsersTable`, `BackupManager` and
  `StreamConnectionCard` applies to upstream `dev`'s copies. The test files are shaped for the fork.
- **Duplicates.** None. #137 is the same class of defect in different files, and its reporter filed
  it separately on purpose. Both close in F-3.

### #73 — plugin enable switches have no accessible name

- **Root cause.** Mantine's `Switch` renders `<input type="checkbox" role="switch">` inside a
  `<label>` body whose only text is the track. The track is `aria-hidden`, so `onLabel="On"` and
  `offLabel="Off"` name nothing (`@mantine/core` 8.0.2, `esm/components/Switch/Switch.mjs`). A probe
  with real Mantine confirmed it: a bare `Switch` has the name `''`, while `aria-label="…"` or
  `label="…"` each give it a name. The sites:
  - `PluginCard.jsx:546-553`, the per-card enable toggle.
  - `Plugins.jsx:492-499`, the import modal's "Enable now". The sibling `<Text>` there is not
    associated with the input.
  - `AvailablePluginCard.jsx:1008-1013`, the install modal's "Enable plugin". The reporter did not
    list it. It is the same control, with the same sibling-`Text` shape, on the Plugin Browse page.
    It is included because #73's title is "plugin enable/disable switches", and leaving the third
    of three would leave that title half-true.
- **The fix.** `aria-label`, never `label`. `label` would render visible text inside the card
  header and change the layout. In the two modals, the `aria-label` repeats the visible sibling
  text word for word ("Enable now", "Enable plugin"), which satisfies WCAG 2.5.3's label-in-name
  rule. `PluginCard`'s label carries the plugin's name, `` `Enable ${plugin.name}` ``, because
  several cards sit on one page and anonymous twins are the defect.
- **Tests.** New `PluginCard.a11y.test.jsx`, `Plugins.a11y.test.jsx` and
  `AvailablePluginCard.a11y.test.jsx`. One e2e locator change in `plugins.spec.ts`, at two sites,
  listed in PR F-3.
- **Size** shared with F-3. **Upstreamable** yes. `PluginCard.jsx` and `AvailablePluginCard.jsx`
  are byte-identical to upstream `dev`, by git blob SHA.
- **Duplicates.** None.

### #137 — icon-only controls on Stats and Backups have no accessible name

- **Root cause.** The same as #65. The sites are `StreamConnectionCard.jsx:213` (Disconnect client),
  `:581` (Stop Channel) and `:648` (Preview Channel), and `BackupManager.jsx:64` (Download), `:76`
  (Restore) and `:86` (Delete). Each is wrapped only in a `Tooltip`, and neither file contains
  `aria-label` at the seed.
- **The fix.** One `aria-label` each, following the naming rule in PR F-3.
  - The `StreamConnectionCard` labels repeat the tooltips word for word, as the reporter proposed.
  - The `BackupManager` labels **add a noun** ("Delete backup", not "Delete"). The same component's
    `ConfirmationDialog`s are labelled `Restore` (`:755`) and `Delete` (`:771`), and they render
    while the rows are still in the document. A row button named exactly `Delete` would make any
    future page-wide `getByRole('button', { name: 'Delete', exact: true })` ambiguous. That is the
    exact query `users.spec.ts:201` already makes on the Users page.
- **Tests.** New `StreamConnectionCard.a11y.test.jsx` and `BackupManager.a11y.test.jsx`. Neither
  was clickable before, so no existing e2e test clicks them, and nothing e2e changes.
- **Size** shared with F-3. **Upstreamable** yes, for the product hunks.
- **Duplicates.** None.

---

## PR F-1 — deep links and reloads land on the route that was asked for

- **Branch** `fix/F-1-deep-link-routing`
- **Closes** #58.
- **Files** `frontend/src/App.jsx`, `frontend/src/store/auth.jsx`, `frontend/src/pages/Login.jsx`,
  `frontend/src/components/forms/LoginForm.jsx`,
  `frontend/src/components/forms/__tests__/LoginForm.test.jsx`, `frontend/src/utils/loginRedirect.js`
  (new), `frontend/src/utils/__tests__/loginRedirect.test.js` (new),
  `frontend/src/__tests__/App.test.jsx` (new), `frontend/src/__tests__/App.signIn.test.jsx` (new),
  `e2e/tests/frontend/direct-navigation.spec.ts` (new), `e2e/tests/frontend/helpers.ts` (comments),
  seven `e2e/tests/frontend/*.spec.ts` (comments), `e2e/COVERAGE.md` (one row).
- **Labels** none backend. The whole frontend suite runs, both in the commit gate and in `Frontend
  result`, and so does the e2e `frontend` project.
- **Ledger/matrix/metrics** none. #58 has no `metrics/curated/defects.yml` entry and is not a
  CLAUDE.md known-defect item, and no `test.fail()` pin exists for it.
- **upstreamable** no as a whole. The Appendix A hunks on their own, yes (§ #58).

### Task 1.1 — port upstream #1578, as its own commit

1. Fetch the upstream commit's diff into your scratch directory:
   ```bash
   gh api repos/Dispatcharr/Dispatcharr/commits/5d0ec618f8 -H "Accept: application/vnd.github.diff" > <scratch>/pr1578.diff
   ```
   It touches seven files: `CHANGELOG.md`, `App.jsx`, `LoginForm.jsx`, `LoginForm.test.jsx`,
   `Login.jsx`, `store/auth.jsx`, and the new `utils/loginRedirect.js`.
2. From the worktree root:
   ```bash
   git apply --check --exclude=CHANGELOG.md <scratch>/pr1578.diff
   ```
   This succeeds at `a54b09a9`. Apply it for real with the same flags. **`CHANGELOG.md` is
   excluded on purpose.** The fork's changelog has not moved since the v0.29.0 release
   (`d9abece0`), and no fork PR since has edited it. If `--check` fails because the tree has moved
   since the seed, retry with `--3way`. If `App.jsx`'s `<Routes>` block conflicts, stop and
   escalate rather than hand-merging it.
3. Run the `LoginForm` tests:
   ```bash
   npx vitest --run src/components/forms/__tests__/LoginForm.test.jsx
   ```
   They pass, including the two tests the port adds. Then run the whole suite. **Expect 203 files and
   6,136 tests**, the seed's 6,134 plus those two.
4. Commit the port alone. The subject is `fix(frontend): port upstream #1578, UI routing after
   sign-in`, and the body says "Port of Dispatcharr/Dispatcharr#1578 (5d0ec618f8), applied with
   `git apply --exclude=CHANGELOG.md`; no other change." A reviewer can then diff this commit
   against upstream byte for byte.

### Task 1.2 — the tests, red on the port

1. Write `frontend/src/utils/__tests__/loginRedirect.test.js` from Appendix D. All 13 tests pass at
   once, because it pins the ported helper rather than the defect.
   **Break-check.** Replace `getSafeNextPath`'s body with `return path || null;`. Seven of the 13
   redden: every rejection row except "no value" and "an empty string". Revert.
2. Write `frontend/src/__tests__/App.test.jsx` from Appendix B, and
   `frontend/src/__tests__/App.signIn.test.jsx` from Appendix C. Run both. **Exactly three tests
   fail on the bare port**, and each lands on `/channels`:
   - `App.signIn`'s only test.
   - `App.test`'s "an unauthenticated deep link goes to /login and returns to the requested route
     after sign-in".
   - `App.test`'s "an unauthenticated deep link to a settings section returns to the section after
     sign-in".
   The other five `App.test` tests pass on the port. Three of them, the two direct loads and the
   in-flight test, are the part of #58 that upstream already fixed. The remaining two pin behaviour
   that must hold either way.
3. Optional. Check out the seed's `App.jsx` (`git show "a54b09a9:frontend/src/App.jsx"`) and run
   both files again. `App.signIn` fails, and five of the seven `App.test` tests fail. The two that
   pass are "an authenticated load of an unknown path still goes to the default route" and "a
   next parameter that points back at /login is not followed after sign-in". Both land on
   `/channels` on the seed too, which is correct. Restore the port's `App.jsx`.

### Task 1.3 — the fix on top of the port

1. Apply Appendix A to `frontend/src/App.jsx`. It imports `useSearchParams`, adds `location.hash` to
   `LoginRedirect`'s target, adds `AuthedRedirect`, and swaps the authenticated catch-all's
   `<Navigate to={defaultRoute} replace />` for `<AuthedRedirect />`.
2. Run `App.test.jsx`, `App.signIn.test.jsx`, `loginRedirect.test.js` and `LoginForm.test.jsx`. All
   pass. Run the whole suite. **Expect 206 files and 6,157 tests**, which is 6,136 + 7 + 1 + 13.
3. **Break-checks.** Run each against `App.test.jsx` and `App.signIn.test.jsx`, and revert after
   each one.
   - **(a)** Replace `{isCheckingAuth ? (` with `{false ? (`. Only "holds the requested URL while
     the auth check is still in flight" reddens. The deep-link tests stay green because the
     redirect-back now rescues them, and that is expected.
   - **(b)** In `AuthedRedirect`, use `to={defaultRoute}`. Three tests redden: `App.signIn`, and
     the two unauthenticated redirect-back tests.
   - **(c)** Remove `+ location.hash` from `LoginRedirect`. Only the settings-section redirect-back
     test reddens.
   - **(d)** In `AuthedRedirect`, use `searchParams.get('next') || defaultRoute`, without
     `getSafeNextPath`. Only "a next parameter that points back at /login is not followed after
     sign-in" reddens. That test exists because a `next` of `//evil.example` cannot tell the two
     apart: the router cannot leave the origin, so it lands on `/channels` either way. An earlier
     draft of this plan used that probe, and check (d) showed it was hollow.
4. Commit: `fix(frontend): return to the requested route after sign-in (#58)`.

### Task 1.4 — e2e: the real path, and the comments that stop being true

1. Write `e2e/tests/frontend/direct-navigation.spec.ts` from Appendix E. It is one `@contract` test
   per `SURFACES` entry, each a real `adminPage.goto(surface.route)`, plus one that reloads a
   settings section. Every test destructures `pageErrors`, which
   `e2e/tests/guards/pageerrors-enforcement.spec.ts` requires. Run the guards project. If it
   rejects the `for` loop's shape as unverifiable, unroll the loop into nine literal `test()` calls
   rather than adding a `KNOWN_UNVERIFIABLE` entry.
2. `e2e/tests/frontend/helpers.ts`. **`gotoSurface`'s code does not change.** It still drives the
   sidebar, which is a real user path worth keeping. Rewrite only the prose that says a direct load
   cannot work:
   - `:6-8`, the module comment: `route` "is **never** handed to `page.goto()` directly".
   - `:71-90`, the `gotoSurface` doc comment, from "`page.goto(route)` alone cannot reach any
     surface" through "that would notice".
   Replace it with prose that says three things. #58 was fixed in this PR. `gotoSurface` is the
   sidebar path by choice. The direct path is `direct-navigation.spec.ts`'s job.
3. The seven spec comments that say `page.goto(...)` "cannot reach this surface". In each, rewrite
   only the sentence that makes that claim, and leave the call to `gotoSurface` as it is:
   - `logos.spec.ts:117-121`
   - `users.spec.ts:112-114`
   - `backups.spec.ts:117-120`
   - `stats.spec.ts:63-71`
   - `settings.spec.ts:101-103`, plus the reload paragraph at `:149-162`, which says "What *doesn't*
     work is a bare `reload()`". Keep that paragraph's reasoning about why `gotoSurface` already
     wipes the store.
   - `connect.spec.ts:125-127`
   - `guide.spec.ts:10-13`
   Re-grep `#58` in `e2e/tests/frontend/` afterwards. Every remaining hit must describe the defect in
   the past tense.
4. `e2e/COVERAGE.md`. After the row "An archive uploaded through the Backups panel re-appears…"
   (`:141` at the seed), add:
   `| Frontend | A fresh document load of every G6 surface, by direct URL and by reload, lands on that surface rather than /channels (#58) | F-1 | done |`
5. Run the guards project and the e2e typecheck, which the edit hook also runs. **Before pushing,
   run the `frontend` project locally** against this worktree's own stack (§ What the implementer
   runs, with `<n>` = 1), for `tests/frontend/direct-navigation.spec.ts` plus every spec whose
   comments you edited. All pass. Commit:
   `test(e2e): direct navigation to every surface (#58)`.

### Test changes in this PR (rule 5)

| Test | Before | After |
|---|---|---|
| `LoginForm.test.jsx` `'navigates to "/channels" when authenticated'` (`:289-300`), changed by the port | `expect(mockNavigate).toHaveBeenCalledWith('/channels')` | `expect(mockNavigate).toHaveBeenCalledWith('/channels', { replace: true })`. The behaviour it pins, how `LoginForm` navigates, is what #1578 changes, from a push to a replace. |
| `LoginForm.test.jsx`'s `react-router-dom` mock (`:6-9`) and `beforeEach` (`:159-163`), changed by the port | `useNavigate` only | Adds `useSearchParams: () => [mockSearchParams]`, which is reset in `beforeEach`. This is infrastructure the new `next` tests need. No assertion changes. |
| `LoginForm.test.jsx`, two new tests from the port | — | `'navigates to the "next" param when authenticated'` and `'falls back to "/channels" for an unsafe "next" param'`. |
| e2e specs and `helpers.ts` | Comments claiming a direct load cannot work | Comments only. No assertion, locator or navigation changes. |

### PR description draft

> **fix(frontend): deep links and reloads land where they were asked to (#58)**
>
> A fresh load of any protected route other than `/channels` landed on `/channels`, and so did a
> page reload. That includes a valid session, `/settings#backups` and a bookmark. The catch-all
> route replaced the URL with `/login` before the async auth check had resolved.
>
> The first commit ports upstream Dispatcharr/Dispatcharr#1578 (`5d0ec618f8`) unchanged, except
> for its changelog line. It gates the router on a new `isCheckingAuth` flag, and sends an
> unauthenticated deep link to `/login?next=…`. The second commit fixes the part of #1578 that
> never ran. `LoginForm` was the only reader of `next`, and sign-in unmounts it before its effect
> runs, so the visitor still landed on `/channels`. The authenticated catch-all now reads `next`
> itself, and `next` now keeps the URL hash. `App.signIn.test.jsx` pins this with the real login
> form, and it fails on the bare port.
>
> The third commit adds `e2e/tests/frontend/direct-navigation.spec.ts`: a real `page.goto` of all
> nine G6 surfaces, plus a reload. It also rewrites the comments that said a direct load could not
> work. `gotoSurface` still drives the sidebar, by choice.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## PR F-2 — Connect subscription badges get a key

- **Branch** `fix/F-2-connect-badge-key`
- **Closes** #62.
- **Files** `frontend/src/pages/Connect.jsx`, `frontend/src/pages/__tests__/Connect.test.jsx`,
  `e2e/tests/frontend/connect.spec.ts` (one comment sentence).
- **Labels** none backend. The whole frontend suite runs.
- **Ledger/matrix/metrics** none. #62 has no ledger entry.
- **upstreamable** yes, for the `Connect.jsx` hunk.

### Task 2.1

1. In `Connect.test.jsx`, inside `describe('subscription badges')` (`:355`), add the test from
   Appendix F just before `'falls back to the raw event name when not in SUBSCRIPTION_EVENTS'`
   (`:378`). Run the file. The new test fails with `Expected: <span data-testid="badge" …>` and
   `Received: serializes to the same string`. That is the index-reconciled node, which is the
   defect. The other 26 tests pass.
2. At `Connect.jsx:208`, change `<Badge size="sm" variant="light" color="green">` to
   `<Badge key={sub.id} size="sm" variant="light" color="green">`. Run the file: 27 pass. Run the
   whole suite: **expect 203 files and 6,135 tests** at the seed, or the F-1 count plus 1 if F-1
   has merged.
3. **Break-check.** Change the key to `key={sub.event}`. The new test still passes, because the
   events in the test differ. Then change it to `key={0}`. The new test reddens. Revert to
   `sub.id`. The point of the pair: the test pins identity-preserving keys, and `sub.id` is chosen
   over `sub.event` by the serializer argument in § #62, not by the test.
   Optionally, give `makeIntegration`'s default subscriptions ids (`{ id: 1, … }`, `{ id: 2, … }`
   at `Connect.test.jsx:117-118`). That is a fixture tidy that moves no assertion: the file still
   passes 27 of 27 with it. Several tests pass their own subscription arrays without ids, so it
   does not remove every `key={undefined}`.
4. `e2e/tests/frontend/connect.spec.ts:255-257`. The sentence "#62 itself is unaffected (the
   missing `key` is still there in source, and still a real reconciliation risk)" becomes "#62 is
   fixed (`Connect.jsx` keys each badge by `sub.id`), and the reconciliation test in
   `Connect.test.jsx` pins it". Leave the rest of the comment, about what this harness can observe.
   It stays true, and `e2e/COVERAGE.md:138` says the same. Run the e2e typecheck and the guards
   project.

### Test changes in this PR (rule 5)

None changed. One test is added:
`keeps a badge on its own DOM node when an earlier badge goes away (#62: badges had no key)`. One
e2e comment sentence is corrected.

### PR description draft

> **fix(frontend): key the Connect subscription badges (#62)**
>
> `Connect.jsx` rendered each integration's enabled subscriptions as a keyless list, so React
> matched badges by position. Removing an earlier subscription reused its DOM node for the next
> one. Each badge is now keyed by `sub.id`, which `EventSubscriptionSerializer` always sends.
> `sub.event` is not unique per integration in the model.
>
> The new test asserts DOM-node identity across a re-render, rather than React's console warning.
> The warning is deduplicated per component for the life of the test module, so it cannot pin
> this. It is also compiled out of the production build the e2e suite runs
> (`e2e/COVERAGE.md:138`).
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## PR F-3 — accessible names on icon-only controls and plugin switches

- **Branch** `fix/F-3-accessible-names`
- **Closes** #65, #73, #137.
- **Files** eight product files, eight new `*.a11y.test.jsx` files, and three e2e specs. They are
  listed in § Files this plan touches.
- **Labels** none backend. The whole frontend suite runs, and so does the e2e `frontend` project.
- **Ledger/matrix/metrics** none. No ledger entry, and no `test.fail()` pin for any of the three.
- **upstreamable** yes, for the eight product hunks (§ #65).

### The naming rule

Three rules decide every name below:

1. **Start with the tooltip's text** when the control has one. The spoken name then contains what a
   sighted user sees on hover.
2. **Add the object's noun** when the tooltip is a bare verb that a confirm dialog or a sibling
   control in the same component also uses. `Restore` becomes `Restore backup`, and `Cancel`
   becomes `Cancel recording`.
3. **For a switch, use `aria-label`, never `label`.** `label` renders visible text, while
   `aria-label` changes nothing on screen.

Every string is exact. Tests match it with `getByRole(role, { name })`, which is an exact match for
a string.

| Site at the seed | Control | `aria-label` |
|---|---|---|
| `UsersTable.jsx:60` | XC-password eye toggle | `{isVisible ? 'Hide password' : 'Show password'}` |
| `UsersTable.jsx:90` | row edit | `"Edit user"` |
| `UsersTable.jsx:100` | row delete | `"Delete user"` |
| `LogosTable.jsx:60` | row edit | `"Edit logo"` |
| `LogosTable.jsx:69` | row delete | `"Delete logo"` |
| `LogosTable.jsx:461` | open the logo's URL | `"Open logo URL"` |
| `RecordingCard.jsx:373` | extend-by menu trigger | `"Extend recording"` |
| `RecordingCard.jsx:400` | stop | `"Stop recording (keep partial content)"` |
| `RecordingCard.jsx:419` | cancel or delete | ``{`${deleteLabel} recording`}``. `deleteLabel` is the tooltip's ternary from `:410-418`, hoisted after `isUpcoming` (`:110`), and the `Tooltip` becomes `label={deleteLabel}`. |
| `StreamConnectionCard.jsx:213` | disconnect a client | `"Disconnect client"` |
| `StreamConnectionCard.jsx:581` | stop the channel | `"Stop Channel"` |
| `StreamConnectionCard.jsx:648` | preview the channel | `"Preview Channel"` |
| `BackupManager.jsx:64` | download | `"Download backup"` |
| `BackupManager.jsx:76` | restore | `"Restore backup"` |
| `BackupManager.jsx:86` | delete | `"Delete backup"` |
| `PluginCard.jsx:546` | enable switch | ``{`Enable ${plugin.name}`}`` |
| `Plugins.jsx:493` | import modal's enable switch | `"Enable now"` |
| `AvailablePluginCard.jsx:1009` | install modal's enable switch | `"Enable plugin"` |

Appendix G is the complete product diff, 18 attributes and one hoisted constant, as measured in
this plan's prototype.

### The test recipe

Each component gets a new `<Component>.a11y.test.jsx` beside its existing test file. **Do not add
these tests to the existing files.** Their `@mantine/core` mocks drop `aria-label`, and they replace
the accessibility tree the tests are meant to measure (finding 2). The edit hook matches
`*.a11y.test.jsx`, because the name ends in `.test.jsx`.

- **Recipe A, all real.** Real `@mantine/core`, real `lucide-react`, real `CustomTable`. Mock only
  stores, API, utilities and child forms or dialogs. Wrap in `<MantineProvider theme={mantineTheme}>`
  (`frontend/src/mantineTheme.jsx`). The theme matters: `UsersTable`, `LogosTable` and
  `StreamConnectionCard` read `theme.tailwind.*`. Used for six components.
- **Recipe B, partial real.** Keep the existing file's `@mantine/core` mock factory, but make it
  `async (importOriginal)`, add `MantineProvider` and `Switch` from `importOriginal()`, and delete
  the mocked `Switch` entry. Used for `Plugins` and `AvailablePluginCard`, where the only path to
  the switch runs through a mocked `FileInput` or modal flow that real Mantine would make
  impractical in jsdom. The control under test is still real.
- **Every test first asserts that its row or card rendered**, by awaiting a text, and only then
  queries by role and name. A red test therefore means "no name", never "never rendered". In the
  prototype, every red read `Unable to find an accessible element with the role "…" and name "…"`
  after the render assertion had passed.

### Task 3.1 — per component, tests first

Do the steps below for each row of the table. **Before touching the product file**, write the test
file and run it: every test in it fails with the message above. Then add that component's labels
from the naming table, and run both the new file and the existing test file. Both pass, and the
existing file needs no change.

| Component | Test file (new) | Recipe | Source of the file | Tests | Break-check (revert after) |
|---|---|---|---|---|---|
| `UsersTable` | `frontend/src/components/tables/__tests__/UsersTable.a11y.test.jsx` | A | Appendix H1, verbatim | 3 | Delete `aria-label="Edit user"`. Only "the Edit user control…" reddens. |
| `LogosTable` | `…/tables/__tests__/LogosTable.a11y.test.jsx` | A | Appendix H2, verbatim | 3 | Delete `aria-label="Open logo URL"`. Only that test reddens. |
| `RecordingCard` | `frontend/src/components/cards/__tests__/RecordingCard.a11y.test.jsx` | A | Appendix H3: a header, then `RecordingCard.test.jsx` lines `5-37`, `124-134` and `139-247` verbatim, then the describe block | 5 | Replace the delete control's `aria-label` with the literal `"Delete recording"`. The upcoming and in-progress cancel tests redden, and the completed one stays green. This pins the shared `deleteLabel`. |
| `StreamConnectionCard` | `…/cards/__tests__/StreamConnectionCard.a11y.test.jsx` | A | Appendix H4: a header, then `StreamConnectionCard.test.jsx` lines `4-58` with two edits, then `72-73` and `182-286` verbatim, then the describe block | 3 | Delete `aria-label="Preview Channel"`. Only that test reddens. |
| `BackupManager` | `frontend/src/components/backups/__tests__/BackupManager.a11y.test.jsx` | A | Appendix H5, verbatim | 3 | Change `"Restore backup"` to `"Restore"`. Only the Restore test reddens. |
| `PluginCard` | `…/cards/__tests__/PluginCard.a11y.test.jsx` | A | Appendix H6: a header, then `PluginCard.test.jsx` lines `9-33` verbatim, then the fixture and describe block | 1 | Change the label to `"Enable plugin"`. The test reddens: two cards now share one name, and neither matches. |
| `Plugins` (page) | `frontend/src/pages/__tests__/Plugins.a11y.test.jsx` | B | Appendix H7: `Plugins.test.jsx` lines `1-30`, the Mantine mock at `32-154` converted, `155-181`, and `184-219`, then the test | 1 | Delete `aria-label="Enable now"`. The test reddens. |
| `AvailablePluginCard` | `…/cards/__tests__/AvailablePluginCard.a11y.test.jsx` | B | Appendix H8: `AvailablePluginCard.test.jsx` lines `1-85`, the Mantine mock at `86-152` converted, and `153-266`, then the test | 1 | Delete `aria-label="Enable plugin"`. The test reddens. |

After all eight, run the whole suite. **Expect 211 files and 6,154 tests** at the seed: 8 new files
and 20 new tests. If F-1 and F-2 have merged first, expect their totals plus 8 files and 20 tests.

### Task 3.2 — e2e: locators that relied on the defect

These three specs located the controls by position, by an icon class or by a Mantine-internal class,
because the controls had no name. Now they locate them by name. No assertion changes. Line numbers
are the seed's. Re-grep each anchor first (`row.locator('button').nth(`,
`button:has(svg.lucide-square-x)`, `label.mantine-Switch-body`), because E-3 edits comments in
`dvr.spec.ts` before this PR lands (§ Overlap). Run the e2e typecheck and the guards project
afterwards. **Before pushing, run `tests/frontend/users.spec.ts`, `tests/frontend/dvr.spec.ts` and
`tests/frontend/plugins.spec.ts` in the `frontend` project locally**, against this worktree's own
stack (§ What the implementer runs, with `<n>` = 3). All pass.

| Spec | Before | After |
|---|---|---|
| `users.spec.ts:182` | `await row.locator('button').nth(0).click();` | `await row.getByRole('button', { name: 'Edit user', exact: true }).click();` |
| `users.spec.ts:193` | `await row.locator('button').nth(1).click();` | `await row.getByRole('button', { name: 'Delete user', exact: true }).click();`. The `Username: ${username}` assertion that follows (`:200`) stays. It still proves the right row. |
| `users.spec.ts:152-175`, comment | Explains that the buttons have no name and why positional selection is safe | Rewrite to one sentence: the row actions are located by name (#65, fixed in F-3), and the row is still scoped by the generated username because `CustomTable` renders `div.tr`, not `<table>` rows. Keep the `CustomTable` reasoning and drop the ordering argument. |
| `users.spec.ts:195-199`, comment | "asserting it here turns the `.nth(1)` ordering above from inference into proof" | "asserting it here proves the click landed on this row's delete control, not another row's". The assertion itself is unchanged. |
| `dvr.spec.ts:274` | `await card.locator('button:has(svg.lucide-square-x)').click();` | `await card.getByRole('button', { name: 'Cancel recording', exact: true }).click();`. The recording is upcoming (`:240-247` asserts `start_time` more than a week ahead), so its control is `Cancel recording`. |
| `dvr.spec.ts:258-270`, comment | Explains the missing name and the lucide-class workaround | Replace it with one line saying the control is located by name (#65, fixed in F-3). |
| `plugins.spec.ts:192` and `:289` | `await card.locator('label.mantine-Switch-body').first().click();` | `await card.locator('label.mantine-Switch-body', { has: adminPage.getByRole('switch', { name: `Enable ${displayName}`, exact: true }) }).click();` |
| `plugins.spec.ts:183-191`, comment | Says the label-body click is needed because the switch has no name | Keep the actionability explanation: the real `<input role="switch">` is zero-size, so Playwright will not click it directly, and the click still goes through the label body. Replace the #73 sentence with: the label body is now selected by the switch's accessible name, so the locator fails if the name is ever lost. |

The plugin locator keeps the label-body click on purpose. The comment at `:183-188` records, from
the real DOM, that Playwright refuses to click Mantine's zero-size input. `getByRole('switch')
.click()` would therefore fail on actionability rather than on the name. `{ has: … }` makes the
click depend on the name without changing what is clicked. `displayName` is `` `E2E ${key}` ``
(`:133` and `:255`), and `PluginCard` names the switch from `plugin.name`, which the zip's manifest
sets to `displayName` (`:156`).

### Test changes in this PR (rule 5)

| Test | Change | Why this is allowed |
|---|---|---|
| Eight new `*.a11y.test.jsx` files, 20 tests | Added | New behaviour, new tests named after the defect. |
| Existing unit tests of the eight components | **None** | Their Mantine mocks drop `aria-label`, so nothing they assert moves. Confirmed in the prototype: each existing file passed unchanged beside its new `a11y` file. |
| `users.spec.ts`, `dvr.spec.ts`, `plugins.spec.ts` | Locators only, listed above | The behaviour these locators routed around, controls without an accessible name, is the thing this PR changes. Every assertion is unchanged. |

### PR description draft

> **fix(frontend): accessible names for icon-only controls and plugin switches (#65, #73, #137)**
>
> Eighteen controls in eight components had no accessible name. That covers the edit and delete
> row actions on Users and Logos, the DVR card's extend, stop and cancel, the Stats card's
> disconnect, stop and preview, the Backups row's download, restore and delete, and three plugin
> enable switches. Mantine's `Tooltip` adds a description, not a name, and a `Switch`'s On/Off
> track text is `aria-hidden`. Each control now has an `aria-label`. The names start with the
> tooltip's own text. Where the tooltip was a bare verb that a confirm dialog also uses, a noun is
> added (`Restore backup`). The per-card plugin switch carries the plugin's name.
>
> The new `*.a11y.test.jsx` files render the real `@mantine/core`. The existing tests mock Mantine
> in a way that drops `aria-label` and replaces the accessibility tree, so a role query against
> them would test the mock. Each new test failed on `main` for the missing name, after asserting
> that its row or card had rendered.
>
> Three e2e specs stop working around the defect. Users row actions and the DVR cancel control are
> now located by name, and the plugin switch's label-body click is scoped by the switch's name.
>
> The same pattern remains at 89 other controls in 35 files. They are out of this PR's scope and
> listed as a follow-up.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## PR F-4 — a count-down ratchet on unnamed controls (only if Q1 is yes)

**Do not start this PR unless the user answers yes to Q1.**

- **Branch** `fix/F-4-accessible-name-ratchet`
- **Closes** nothing. It keeps F-3's fix from regressing and stops the remaining pattern growing.
- **Files** `frontend/src/__tests__/accessibleNames.ratchet.test.js` (new).
- **Labels** none backend. The whole frontend suite runs.
- **upstreamable** no. It is a fork policy.

**Why a vitest scan and not a lint rule.** This answers the lead's question.
- `eslint-plugin-jsx-a11y` is not installed, and `frontend/eslint.config.js` loads only
  `react-hooks` and `react-refresh`.
- Installing it would ratchet nothing, because lint is commented out in CI
  (`frontend-tests.yml:117-118`) and the edit hook's eslint is advisory.
- Its `control-has-associated-label` rule is not in the recommended set. Mantine components also
  need a `settings['jsx-a11y'].components` mapping before the rule sees them, and that mapping
  cannot express "a `Switch` is named by `label`".

A vitest file runs in `Frontend result` on every PR, blocks there, and needs no new dependency.
It runs in the `node` environment (`// @vitest-environment node`). It scans every non-test `.jsx`
file under `frontend/src` for `<ActionIcon`/`<Switch` opening tags that carry no naming attribute,
and asserts two things:
- the count is at most `FLOOR`;
- each of F-3's eight files has zero.

**Its blind spot, and the escape hatch.** The scan reads source text. A control named through a
prop spread (`<ActionIcon {...a11yProps}>`) or by a wrapper component is named at runtime but
unnamed to the scan. Such a tag is marked on the line directly above it: `{/* a11y-name: <reason>
*/}` inside JSX, or `// a11y-name: <reason>` outside it. A marker with no reason clears nothing, the
rule `relay/internal/credlint`'s `// credential-logging: ok - <reason>` already uses. The file's
header states the blind spot and the marker. The marker was prototyped on the F-3 tree: an
unmarked unnamed tag reddens two tests, `{/* a11y-name: */}` and `{/* a11y-name */}` redden the same
two, and `{/* a11y-name: <a reason> */}` passes 9 of 9.

### Task 4.1

1. After F-3 has merged, measure the count on `main`. The prototype of this file, run on the tree
   F-3 produces, printed **89 in 35 files**, against **107 in 43 files** at the seed. Set `FLOOR`
   to the number measured on `main`, not to 89. The file's header carries the counting rule and
   both measurements, so the number never travels without its formula.
2. Write the file from Appendix I. Run it: 9 tests pass, the floor test and one for each of the
   eight files.
3. **Break-check.** Delete `aria-label="Edit user"` from `UsersTable.jsx`. Two tests redden: the
   floor test, whose message lists every offending site by file, and "components/tables/UsersTable.jsx
   has none left". Revert.
4. A PR that later names more controls lowers `FLOOR` in the same PR. A PR that exceeds the floor
   either names its new controls or, where the name comes from a spread or a wrapper that the scan
   cannot see, marks them with `a11y-name: <reason>` as above. The floor is never raised to make a
   run green.

### PR description draft

> **test(frontend): ratchet the count of controls with no accessible name**
>
> F-3 named the 18 controls behind #65, #73 and #137. The same pattern remains at 89 other sites.
> This adds a source scan in vitest that fails if the count rises above the floor measured on
> `main`, or if any of F-3's eight files regains an unnamed control. `eslint-plugin-jsx-a11y` is
> not installed, lint does not run in CI, and the plugin cannot see through Mantine's components
> without per-component configuration. So this is a test, not a lint rule.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## Coverage

| Issue | Planned in | Closes on merge of |
|---|---|---|
| #58 | PR F-1 | F-1 |
| #62 | PR F-2 | F-2 |
| #65 | PR F-3 | F-3 |
| #73 | PR F-3 | F-3 |
| #137 | PR F-3 | F-3 |

No issue in this category is a rule-4 policy item, so there are no decision memos. No issue here
is a duplicate of another fork issue.

## Open questions

- **Q1 — add the F-4 ratchet?** Yes or no. With yes, F-4 is planned above and runs after F-3. With
  no, F-4 is dropped, and nothing stops the 89 remaining unnamed controls from growing. The
  recommendation is **yes**. It costs one test file, needs no dependency, and is the only
  mechanism in reach that would actually block in CI.

## Follow-ups for the lead (not filed; tracker writes are yours)

- **Upstream #1578's redirect-back does not work upstream either.** Upstream `dev`'s authenticated
  catch-all is still `<Navigate to={defaultRoute} replace />`, and `LoginForm` is still the only
  reader of `next`. Appendix A's two hunks, `AuthedRedirect` and the hash, would fix it upstream
  too. Reporting that upstream is an outward-facing act, and it is the user's call.
- **89 unnamed icon-only controls remain in 35 files** after F-3, measured by the scan in
  Appendix I. They include `User.jsx:317` and `:376`, which were left alone because of B-6, and
  the `ServerGroupsTable`, `ChannelsTable`, `StreamsTable`, `M3UsTable` and `EPGsTable` row actions.
  They are the same defect as #65 and #137, but neither issue names them. A follow-up issue should
  cover them, and F-4 would count them down.
- **Two hard redirects still drop the requested path.** Both set `window.location.href =
  '/login'`, a full page load with no `next`:
  - `App.jsx:72-77`, a 401 from `fetchSuperUser`.
  - `api.js:189-194`, a refresh-token call that fails with 401 or "does not exist". This one is
    reached from `initializeAuth()` on every page load that holds a refresh token.
  So a deep link opened with an **expired** refresh token still lands on `/login` without `next`,
  and then on `/channels` after sign-in. #58 reported the valid-session case, which F-1 fixes. The
  expired-session case is adjacent, and F-1 does not change it.
- **`gotoSurface` is kept by choice after F-1.** Its sidebar-click path is real user coverage. The
  new `direct-navigation.spec.ts` covers the direct path. Nothing needs doing, but a later "why do
  we still click through the sidebar?" question has its answer in `helpers.ts`'s rewritten comment.

---

## Appendices

Every appendix below was run in this plan's worktree at `a54b09a9` and then removed. The test
files are copied from the prototypes that produced the counts and break-check results quoted
above. Run `npx prettier --write` over each file after writing it. The appendices are not
prettier-formatted, and formatting does not change behaviour.

### Appendix A — F-1: the two hunks on top of the upstream port (`frontend/src/App.jsx`)

Apply after Task 1.1. The context lines are the port's `App.jsx`, not the seed's.

```diff
--- a/frontend/src/App.jsx
+++ b/frontend/src/App.jsx
@@ -5,6 +5,7 @@
   Routes,
   Navigate,
   useLocation,
+  useSearchParams,
 } from 'react-router-dom';
 import Sidebar from './components/Sidebar';
 import Login, { LoginLoadingCard } from './pages/Login';
@@ -42,11 +43,27 @@
 
 const LoginRedirect = () => {
   const location = useLocation();
-  const target = getSafeNextPath(location.pathname + location.search);
+  const target = getSafeNextPath(
+    location.pathname + location.search + location.hash
+  );
   const next = target ? `?next=${encodeURIComponent(target)}` : '';
   return <Navigate to={`/login${next}`} replace />;
 };
 
+// The catch-all once signed in. LoginForm's own effect never gets to read
+// ?next=: the sign-in that flips isAuthenticated also unregisters /login in
+// the same render, so LoginForm unmounts before its effect runs, and this
+// route is what renders next (#58).
+const AuthedRedirect = () => {
+  const [searchParams] = useSearchParams();
+  return (
+    <Navigate
+      to={getSafeNextPath(searchParams.get('next')) || defaultRoute}
+      replace
+    />
+  );
+};
+
 const App = () => {
   const [open, setOpen] = useLocalStorage('dispatcharr_sidebar_open', true);
   const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
@@ -183,7 +200,7 @@
                         path="*"
                         element={
                           authReady ? (
-                            <Navigate to={defaultRoute} replace />
+                            <AuthedRedirect />
                           ) : (
                             <LoginRedirect />
                           )
```

### Appendix B — F-1: `frontend/src/__tests__/App.test.jsx`

```jsx
// #58: routing on a fresh document load. The real App and the real auth
// store run here. The store's three network-bound actions are stubbed, and
// every page is a stub that only says which page it is.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';

const { page } = vi.hoisted(() => ({
  page: (id) => () => ({ default: () => <div data-testid={`page-${id}`} /> }),
}));
vi.mock('../pages/Login', () => ({ default: () => <div data-testid="page-login" />, LoginLoadingCard: () => <div data-testid="auth-pending" /> }));
vi.mock('../pages/Channels', page('channels'));
vi.mock('../pages/ContentSources', page('sources'));
vi.mock('../pages/Guide', page('guide'));
vi.mock('../pages/Stats', page('stats'));
vi.mock('../pages/DVR', page('dvr'));
vi.mock('../pages/Settings', page('settings'));
vi.mock('../pages/Plugins', page('plugins'));
vi.mock('../pages/PluginBrowse', page('plugin-browse'));
vi.mock('../pages/Connect', page('connect'));
vi.mock('../pages/Users', page('users'));
vi.mock('../pages/Logos', page('logos'));
vi.mock('../pages/VODs', page('vods'));
vi.mock('../components/Sidebar', () => ({ default: () => <nav data-testid="sidebar" /> }));
vi.mock('../components/FloatingVideo', () => ({ default: () => null }));
vi.mock('../components/M3URefreshNotification', () => ({ default: () => null }));
vi.mock('../WebSocket', () => ({ WebsocketProvider: ({ children }) => children }));
vi.mock('../api', () => ({
  default: { fetchSuperUser: vi.fn().mockResolvedValue({ superuser_exists: true }) },
}));

import App from '../App';
import useAuthStore from '../store/auth';

const signedIn = () =>
  useAuthStore.setState({ isAuthenticated: true, isInitialized: true, isCheckingAuth: false });

const stubAuth = ({ loggedIn }) => {
  useAuthStore.setState({
    initializeAuth: vi.fn().mockResolvedValue(loggedIn),
    initData: vi.fn(async () => signedIn()),
    logout: vi.fn(async () =>
      useAuthStore.setState({ isAuthenticated: false, isInitialized: false, isCheckingAuth: false })
    ),
  });
};

describe('App routing on a fresh load (#58)', () => {
  beforeEach(() => {
    useAuthStore.setState(useAuthStore.getInitialState(), true);
  });
  afterEach(() => {
    window.history.replaceState(null, '', '/');
  });

  it('a direct load of a protected route with a valid session stays on that route (#58: it bounced to /channels)', async () => {
    window.history.pushState(null, '', '/guide');
    stubAuth({ loggedIn: true });
    render(<App />);
    expect(await screen.findByTestId('page-guide')).toBeInTheDocument();
    expect(window.location.pathname).toBe('/guide');
  });

  it('a reload on a settings section keeps the path and the hash (#58: it landed on /channels)', async () => {
    window.history.pushState(null, '', '/settings#backups');
    stubAuth({ loggedIn: true });
    render(<App />);
    expect(await screen.findByTestId('page-settings')).toBeInTheDocument();
    expect(window.location.pathname).toBe('/settings');
    expect(window.location.hash).toBe('#backups');
  });

  it('holds the requested URL while the auth check is still in flight (#58: the catch-all replaced it with /login)', async () => {
    window.history.pushState(null, '', '/dvr');
    let resolveAuth;
    stubAuth({ loggedIn: true });
    useAuthStore.setState({
      initializeAuth: vi.fn(() => new Promise((r) => (resolveAuth = r))),
    });
    render(<App />);
    expect(screen.getByTestId('auth-pending')).toBeInTheDocument();
    expect(window.location.pathname).toBe('/dvr');
    await act(async () => resolveAuth(true));
    expect(await screen.findByTestId('page-dvr')).toBeInTheDocument();
    expect(window.location.pathname).toBe('/dvr');
  });

  it('an unauthenticated deep link goes to /login and returns to the requested route after sign-in (#58: it went to /channels)', async () => {
    window.history.pushState(null, '', '/stats');
    stubAuth({ loggedIn: false });
    render(<App />);
    expect(await screen.findByTestId('page-login')).toBeInTheDocument();
    expect(window.location.pathname).toBe('/login');
    act(() => signedIn());
    expect(await screen.findByTestId('page-stats')).toBeInTheDocument();
    expect(window.location.pathname).toBe('/stats');
  });

  it('an authenticated load of an unknown path still goes to the default route', async () => {
    window.history.pushState(null, '', '/no-such-page');
    stubAuth({ loggedIn: true });
    render(<App />);
    expect(await screen.findByTestId('page-channels')).toBeInTheDocument();
    expect(window.location.pathname).toBe('/channels');
  });

  it('an unauthenticated deep link to a settings section returns to the section after sign-in (#58: the hash was dropped)', async () => {
    window.history.pushState(null, '', '/settings#backups');
    stubAuth({ loggedIn: false });
    render(<App />);
    expect(await screen.findByTestId('page-login')).toBeInTheDocument();
    act(() => signedIn());
    expect(await screen.findByTestId('page-settings')).toBeInTheDocument();
    expect(window.location.pathname + window.location.hash).toBe('/settings#backups');
  });

  it('a next parameter that points back at /login is not followed after sign-in (getSafeNextPath)', async () => {
    window.history.pushState(null, '', '/login?next=' + encodeURIComponent('/login?next=/stats'));
    stubAuth({ loggedIn: false });
    render(<App />);
    expect(await screen.findByTestId('page-login')).toBeInTheDocument();
    act(() => signedIn());
    expect(await screen.findByTestId('page-channels')).toBeInTheDocument();
    expect(window.location.pathname).toBe('/channels');
  });
});
```

### Appendix C — F-1: `frontend/src/__tests__/App.signIn.test.jsx`

```jsx
// #58, the half upstream #1578 left open: signing in through the real
// LoginForm must return to the deep link that sent the visitor to /login.
// Everything is real here except the pages behind the sign-in, the sidebar,
// the WebSocket provider and the store's network-bound actions. A stub Login
// page would hide the defect: the only reader of ?next= used to be
// LoginForm's own effect, which never runs because the sign-in unmounts it.
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';

const { page } = vi.hoisted(() => ({
  page: (id) => () => ({ default: () => <div data-testid={`page-${id}`} /> }),
}));
vi.mock('../pages/Channels', page('channels'));
vi.mock('../pages/ContentSources', page('sources'));
vi.mock('../pages/Guide', page('guide'));
vi.mock('../pages/Stats', page('stats'));
vi.mock('../pages/DVR', page('dvr'));
vi.mock('../pages/Settings', page('settings'));
vi.mock('../pages/Plugins', page('plugins'));
vi.mock('../pages/PluginBrowse', page('plugin-browse'));
vi.mock('../pages/Connect', page('connect'));
vi.mock('../pages/Users', page('users'));
vi.mock('../pages/Logos', page('logos'));
vi.mock('../pages/VODs', page('vods'));
vi.mock('../components/Sidebar', () => ({ default: () => <nav /> }));
vi.mock('../components/FloatingVideo', () => ({ default: () => null }));
vi.mock('../components/M3URefreshNotification', () => ({ default: () => null }));
vi.mock('../WebSocket', () => ({ WebsocketProvider: ({ children }) => children }));
vi.mock('../api', () => ({
  default: {
    fetchSuperUser: vi.fn().mockResolvedValue({ superuser_exists: true }),
    getVersion: vi.fn().mockResolvedValue({ version: '0.0.0' }),
  },
}));

import App from '../App';
import useAuthStore from '../store/auth';

describe('signing in from a deep link (#58)', () => {
  it('the real login form returns the visitor to the route they asked for (#58: it went to /channels)', async () => {
    window.history.pushState(null, '', '/stats');
    useAuthStore.setState({
      initializeAuth: vi.fn().mockResolvedValue(false),
      logout: vi.fn(async () =>
        useAuthStore.setState({ isAuthenticated: false, isInitialized: false, isCheckingAuth: false })
      ),
      login: vi.fn(async () => {}),
      initData: vi.fn(async () =>
        useAuthStore.setState({ isAuthenticated: true, isInitialized: true, isCheckingAuth: false })
      ),
    });
    render(<App />);

    const username = await screen.findByLabelText(/username/i);
    expect(window.location.pathname + window.location.search).toBe('/login?next=%2Fstats');
    fireEvent.change(username, { target: { value: 'admin' } });
    fireEvent.change(screen.getByLabelText(/password/i, { selector: 'input' }), {
      target: { value: 'secret' },
    });
    await act(async () => {
      fireEvent.submit(username.closest('form'));
    });

    expect(await screen.findByTestId('page-stats')).toBeInTheDocument();
    expect(window.location.pathname).toBe('/stats');
  });
});
```

### Appendix D — F-1: `frontend/src/utils/__tests__/loginRedirect.test.js`

`frontend/src/utils/__tests__/` already exists at the seed, holding `dateTimeUtils.test.js` and
`networkUtils.test.js`.

```js
import { describe, it, expect } from 'vitest';
import { defaultRoute, getSafeNextPath } from '../loginRedirect';

describe('getSafeNextPath', () => {
  it.each([
    ['no value', null],
    ['an empty string', ''],
    ['a relative path', 'stats'],
    ['a protocol-relative URL', '//evil.example'],
    ['a backslash-escaped host', '/\\evil.example'],
    ['an absolute URL', 'https://evil.example/stats'],
    ['the login page', '/login'],
    ['the login page with its own next', '/login?next=/stats'],
    ['a path under the login page', '/login/x'],
  ])('rejects %s', (_, path) => {
    expect(getSafeNextPath(path)).toBeNull();
  });

  it.each([['/stats'], ['/settings#backups'], ['/guide?day=1']])(
    'accepts the in-app path %s unchanged',
    (path) => {
      expect(getSafeNextPath(path)).toBe(path);
    }
  );

  it('the default route is /channels', () => {
    expect(defaultRoute).toBe('/channels');
  });
});
```

### Appendix E — F-1: `e2e/tests/frontend/direct-navigation.spec.ts`

Checked in the worktree: `npx tsc --noEmit` exits 0. `npx playwright test --project=guards`
passes all 18 guards with this file present. With `pageErrors` removed from the loop's test, the
page-errors guard fails naming `direct-navigation.spec.ts:16`, which shows it reads the loop's
shape. The `frontend` project itself needs the stack and runs in CI.

```ts
import { test, expect } from '../../fixtures';
import { SURFACES, gotoSurface } from './helpers';

// #58: a fresh document load of any protected route other than /channels
// used to land on /channels, because App.jsx's catch-all route replaced the
// URL before the async auth check resolved. Every other spec in this
// directory reaches its surface through `gotoSurface`, which clicks through
// the sidebar, so none of them covers the path a bookmark, a shared link or
// a reload takes. These do: a real `page.goto` of every surface, and a
// reload of a settings section.
//
// The URL is asserted as well as the test id. A landing on /channels whose
// page happened to render the same id would otherwise pass, and the path
// plus hash is what #58 lost.
for (const surface of SURFACES) {
  test(`a direct load of ${surface.route} lands on ${surface.name} (#58)`, { tag: '@contract' }, async ({
    adminPage,
    pageErrors,
  }) => {
    await adminPage.goto(surface.route);

    await expect(adminPage.getByTestId(surface.testId)).toBeVisible();
    const url = new URL(adminPage.url());
    expect(url.pathname + url.hash).toBe(surface.route);
    // `settings-page` is visible whether or not the section's lazy chunk
    // loaded (helpers.ts, `gotoSurface`'s Settings branch), so wait for the
    // Suspense fallback to go as well.
    if (surface.testId === 'settings-page') {
      await expect(adminPage.locator('.mantine-Loader-root')).toHaveCount(0);
    }

    await pageErrors.expectClean();
  });
}

test('a reload on a settings section stays on that section (#58)', { tag: '@contract' }, async ({
  adminPage,
  pageErrors,
}) => {
  const settings = SURFACES.find((s) => s.name === 'Settings');
  if (!settings) {
    throw new Error('direct-navigation.spec.ts: no "Settings" entry in SURFACES — check helpers.ts');
  }
  await gotoSurface(adminPage, settings);

  await adminPage.reload();

  await expect(adminPage.getByTestId(settings.testId)).toBeVisible();
  await expect(adminPage.locator('.mantine-Loader-root')).toHaveCount(0);
  const url = new URL(adminPage.url());
  expect(url.pathname + url.hash).toBe(settings.route);

  await pageErrors.expectClean();
});
```

### Appendix F — F-2: the new test in `frontend/src/pages/__tests__/Connect.test.jsx`

Insert inside `describe('subscription badges')`, immediately before
`it('falls back to the raw event name when not in SUBSCRIPTION_EVENTS'`.

```jsx
    it('keeps a badge on its own DOM node when an earlier badge goes away (#62: badges had no key)', () => {
      const first = { id: 101, event: 'channel_start', enabled: true };
      const second = { id: 102, event: 'recording_start', enabled: true };
      setupStore({ integrations: [makeIntegration({ subscriptions: [first, second] })] });
      const { rerender } = render(<ConnectPage />);
      const before = screen.getByText('Recording Started');

      setupStore({ integrations: [makeIntegration({ subscriptions: [second] })] });
      rerender(<ConnectPage />);

      expect(screen.queryByText('Channel Started')).not.toBeInTheDocument();
      expect(screen.getByText('Recording Started')).toBe(before);
    });
```

### Appendix G — F-3: the product diff (eight files)

```diff
diff --git a/frontend/src/components/backups/BackupManager.jsx b/frontend/src/components/backups/BackupManager.jsx
index 5f3e4f29..45d41af2 100644
--- a/frontend/src/components/backups/BackupManager.jsx
+++ b/frontend/src/components/backups/BackupManager.jsx
@@ -62,6 +62,7 @@ const RowActions = ({
     <Flex gap={4} wrap="nowrap">
       <Tooltip label="Download">
         <ActionIcon
+          aria-label="Download backup"
           variant="transparent"
           size="sm"
           color="blue.5"
@@ -74,6 +75,7 @@ const RowActions = ({
       </Tooltip>
       <Tooltip label="Restore">
         <ActionIcon
+          aria-label="Restore backup"
           variant="transparent"
           size="sm"
           color="yellow.5"
@@ -84,6 +86,7 @@ const RowActions = ({
       </Tooltip>
       <Tooltip label="Delete">
         <ActionIcon
+          aria-label="Delete backup"
           variant="transparent"
           size="sm"
           color="red.9"
diff --git a/frontend/src/components/cards/AvailablePluginCard.jsx b/frontend/src/components/cards/AvailablePluginCard.jsx
index 497a5435..1e31051b 100644
--- a/frontend/src/components/cards/AvailablePluginCard.jsx
+++ b/frontend/src/components/cards/AvailablePluginCard.jsx
@@ -1007,6 +1007,7 @@ const AvailablePluginCard = ({
               <Group justify="space-between" align="center">
                 <Text size="sm">Enable plugin</Text>
                 <Switch
+                  aria-label="Enable plugin"
                   size="sm"
                   checked={enableNow}
                   onChange={(e) => setEnableNow(e.currentTarget.checked)}
diff --git a/frontend/src/components/cards/PluginCard.jsx b/frontend/src/components/cards/PluginCard.jsx
index 76b9da26..2f44d857 100644
--- a/frontend/src/components/cards/PluginCard.jsx
+++ b/frontend/src/components/cards/PluginCard.jsx
@@ -544,6 +544,7 @@ const PluginCard = ({
               </Badge>
             )}
             <Switch
+              aria-label={`Enable ${plugin.name}`}
               checked={!missing && enabled}
               onChange={handleEnableChange()}
               size="xs"
diff --git a/frontend/src/components/cards/RecordingCard.jsx b/frontend/src/components/cards/RecordingCard.jsx
index 97481deb..de94f08e 100644
--- a/frontend/src/components/cards/RecordingCard.jsx
+++ b/frontend/src/components/cards/RecordingCard.jsx
@@ -108,6 +108,12 @@ const RecordingCard = ({
     status !== 'completed' &&
     status !== 'stopped';
   const isUpcoming = isBefore(now, start);
+  // One string for the delete control's tooltip and its accessible name (#65).
+  const deleteLabel = isInProgress
+    ? 'Cancel & delete'
+    : isUpcoming
+      ? 'Cancel'
+      : 'Delete';
   const isSeriesGroup = Boolean(
     recording._group_count && recording._group_count > 1
   );
@@ -371,6 +377,7 @@ const RecordingCard = ({
                 <Menu withinPortal position="bottom-end" shadow="md">
                   <Menu.Target>
                     <ActionIcon
+                      aria-label="Extend recording"
                       variant="transparent"
                       color="teal.5"
                       onMouseDown={(e) => e.stopPropagation()}
@@ -398,6 +405,7 @@ const RecordingCard = ({
           {isInProgress && (
             <Tooltip label="Stop recording (keep partial content)">
               <ActionIcon
+                aria-label="Stop recording (keep partial content)"
                 variant="transparent"
                 color="yellow.6"
                 onMouseDown={(e) => e.stopPropagation()}
@@ -407,16 +415,9 @@ const RecordingCard = ({
               </ActionIcon>
             </Tooltip>
           )}
-          <Tooltip
-            label={
-              isInProgress
-                ? 'Cancel & delete'
-                : isUpcoming
-                  ? 'Cancel'
-                  : 'Delete'
-            }
-          >
+          <Tooltip label={deleteLabel}>
             <ActionIcon
+              aria-label={`${deleteLabel} recording`}
               variant="transparent"
               color="red.9"
               onMouseDown={(e) => e.stopPropagation()}
diff --git a/frontend/src/components/cards/StreamConnectionCard.jsx b/frontend/src/components/cards/StreamConnectionCard.jsx
index 3f515051..43e9fbaa 100644
--- a/frontend/src/components/cards/StreamConnectionCard.jsx
+++ b/frontend/src/components/cards/StreamConnectionCard.jsx
@@ -211,6 +211,7 @@ const StreamConnectionCard = ({
             <Center>
               <Tooltip label="Disconnect client">
                 <ActionIcon
+                  aria-label="Disconnect client"
                   size="sm"
                   variant="transparent"
                   color="red.9"
@@ -579,6 +580,7 @@ const StreamConnectionCard = ({
             <Center>
               <Tooltip label="Stop Channel">
                 <ActionIcon
+                  aria-label="Stop Channel"
                   variant="transparent"
                   color="red.9"
                   onClick={() => stopChannel(channel.channel_id)}
@@ -646,6 +648,7 @@ const StreamConnectionCard = ({
               {channel.name && (
                 <Tooltip label="Preview Channel">
                   <ActionIcon
+                  aria-label="Preview Channel"
                     size="md"
                     variant="transparent"
                     color={theme.tailwind.green[5]}
diff --git a/frontend/src/components/tables/LogosTable.jsx b/frontend/src/components/tables/LogosTable.jsx
index ff5784d5..6e5bed68 100644
--- a/frontend/src/components/tables/LogosTable.jsx
+++ b/frontend/src/components/tables/LogosTable.jsx
@@ -58,6 +58,7 @@ const LogoRowActions = ({ theme, row, editLogo, handleDeleteLogo }) => {
     <Box style={{ width: '100%', justifyContent: 'left' }}>
       <Group gap={2} justify="center">
         <ActionIcon
+          aria-label="Edit logo"
           size={iconSize}
           variant="transparent"
           color={theme.tailwind.yellow[3]}
@@ -67,6 +68,7 @@ const LogoRowActions = ({ theme, row, editLogo, handleDeleteLogo }) => {
         </ActionIcon>
 
         <ActionIcon
+          aria-label="Delete logo"
           size={iconSize}
           variant="transparent"
           color={theme.tailwind.red[6]}
@@ -459,6 +461,7 @@ const LogosTable = () => {
             </Box>
             {getValue()?.startsWith('http') && (
               <ActionIcon
+                aria-label="Open logo URL"
                 size="xs"
                 variant="transparent"
                 color="gray"
diff --git a/frontend/src/components/tables/UsersTable.jsx b/frontend/src/components/tables/UsersTable.jsx
index 541452c7..9cb1a812 100644
--- a/frontend/src/components/tables/UsersTable.jsx
+++ b/frontend/src/components/tables/UsersTable.jsx
@@ -58,6 +58,7 @@ const XCPasswordCell = ({ getValue }) => {
       </Text>
       {password !== 'N/A' && (
         <ActionIcon
+          aria-label={isVisible ? 'Hide password' : 'Show password'}
           size="xs"
           variant="transparent"
           color="gray"
@@ -88,6 +89,7 @@ const UserRowActions = ({ theme, row, editUser, handleDeleteUser }) => {
   return (
     <Group gap={2} justify="center" wrap="nowrap">
       <ActionIcon
+        aria-label="Edit user"
         size={iconSize}
         variant="transparent"
         color={theme.tailwind.yellow[3]}
@@ -98,6 +100,7 @@ const UserRowActions = ({ theme, row, editUser, handleDeleteUser }) => {
       </ActionIcon>
 
       <ActionIcon
+        aria-label="Delete user"
         size={iconSize}
         variant="transparent"
         color={theme.tailwind.red[6]}
diff --git a/frontend/src/pages/Plugins.jsx b/frontend/src/pages/Plugins.jsx
index acc8ab10..0d64f5e2 100644
--- a/frontend/src/pages/Plugins.jsx
+++ b/frontend/src/pages/Plugins.jsx
@@ -491,6 +491,7 @@ export default function PluginsPage() {
                 <Group justify="space-between" mt="sm" align="center">
                   <Text size="sm">Enable now</Text>
                   <Switch
+                    aria-label="Enable now"
                     size="sm"
                     checked={enableAfterImport}
                     onChange={(e) =>
```

### Appendix H1 — `frontend/src/components/tables/__tests__/UsersTable.a11y.test.jsx`

```jsx
// Accessible names on UsersTable's icon-only controls (#65).
// Renders the REAL @mantine/core and the real CustomTable: the accessibility
// tree is what is under test, and UsersTable.test.jsx mocks both.
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import mantineTheme from '../../../mantineTheme';

const state = vi.hoisted(() => ({
  users: [{ id: 2, username: 'alice', user_level: 1, channel_profiles: [], custom_properties: { xc_password: 'pw' } }],
  profiles: {},
  user: { id: 1, username: 'admin', user_level: 10 },
  isWarningSuppressed: () => false,
  suppressWarning: () => {},
}));
const selectorStore = () => ({ default: (sel) => sel(state) });
vi.mock('../../../api', () => ({ default: { deleteUser: vi.fn() } }));
vi.mock('../../../store/users', () => ({ default: (sel) => sel(state) }));
vi.mock('../../../store/channels', () => ({ default: (sel) => sel(state) }));
vi.mock('../../../store/auth', () => ({ default: (sel) => sel(state) }));
vi.mock('../../../store/warnings', () => ({ default: (sel) => sel(state) }));
vi.mock('../../forms/User', () => ({ default: () => null }));
vi.mock('../../ConfirmationDialog', () => ({ default: () => null }));

import UsersTable from '../UsersTable';

describe('UsersTable controls have accessible names (#65)', () => {
  it.each(['Edit user', 'Delete user', 'Show password'])(
    'the %s control is reachable by role and name (#65: it had none)',
    async (name) => {
      render(<MantineProvider theme={mantineTheme}><UsersTable /></MantineProvider>);
      expect(await screen.findByText('alice')).toBeInTheDocument();
      expect(screen.getByRole('button', { name })).toBeInTheDocument();
    }
  );
});
```

### Appendix H2 — `frontend/src/components/tables/__tests__/LogosTable.a11y.test.jsx`

```jsx
// Accessible names on LogosTable's icon-only controls (#65).
// Renders the REAL @mantine/core and the real CustomTable: the accessibility
// tree is what is under test, and LogosTable.test.jsx mocks both.
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import mantineTheme from '../../../mantineTheme';

const state = vi.hoisted(() => ({
  logos: {
    1: {
      id: 1,
      name: 'Test Logo',
      url: 'http://example.com/logo.png',
      cache_url: '/cached/logo.png',
      channel_count: 0,
      channel_names: [],
      is_used: false,
    },
  },
  fetchAllLogos: () => Promise.resolve(),
  updateLogo: () => {},
  addLogo: () => {},
  isLoading: false,
  suppressWarning: () => {},
  isWarningSuppressed: () => false,
}));
vi.mock('../../../store/logos', () => ({
  default: (sel) => (typeof sel === 'function' ? sel(state) : state),
}));
vi.mock('../../../store/warnings', () => ({ default: (sel) => sel(state) }));
vi.mock('../../../utils/notificationUtils.js', () => ({ showNotification: vi.fn() }));
vi.mock('../../forms/Logo', () => ({ default: () => null }));
vi.mock('../../ConfirmationDialog', () => ({ default: () => null }));

import LogosTable from '../LogosTable';

describe('LogosTable controls have accessible names (#65)', () => {
  it.each(['Edit logo', 'Delete logo', 'Open logo URL'])(
    'the %s control is reachable by role and name (#65: it had none)',
    async (name) => {
      render(
        <MantineProvider theme={mantineTheme}>
          <LogosTable />
        </MantineProvider>
      );
      expect(await screen.findByText('Test Logo')).toBeInTheDocument();
      expect(screen.getByRole('button', { name })).toBeInTheDocument();
    }
  );
});
```

### Appendix H3 — `frontend/src/components/cards/__tests__/RecordingCard.a11y.test.jsx`

Assemble in this order:
1. The header below.
2. `RecordingCard.test.jsx` lines `5-37` verbatim: the store, utility and
   `@mantine/notifications` mocks.
3. Lines `124-134` verbatim: the `RecordingSynopsis` and logo mocks. **Skip** `39-122`, the
   `@mantine/core` and `lucide-react` mocks.
4. Lines `139-247` verbatim: the imports after the mocks, `makeMoment`, `PAST`, `FUTURE`, `NOW`,
   `makeRecording`, `makeChannel` and `setupMocks`.
5. The tail below.

Header:

```jsx
// Accessible names on RecordingCard's icon-only controls (#65).
// Renders the REAL @mantine/core: the accessibility tree is what is under
// test, and RecordingCard.test.jsx mocks Mantine. Everything else below is
// copied verbatim from RecordingCard.test.jsx (see the fix plan for ranges).
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { MantineProvider } from '@mantine/core';
import RecordingCard from '../RecordingCard';
```

Tail:

```jsx
const renderCard = (recording) => {
  setupMocks({ recording });
  render(
    <MantineProvider>
      <RecordingCard recording={recording} channel={makeChannel()} />
    </MantineProvider>
  );
  expect(screen.getByText('Test Show')).toBeInTheDocument();
};

describe('RecordingCard controls have accessible names (#65)', () => {
  it('a completed recording names its delete control (#65: it had none)', () => {
    renderCard(makeRecording());
    expect(screen.getByRole('button', { name: 'Delete recording' })).toBeInTheDocument();
  });

  it('an upcoming recording names its cancel control (#65: it had none)', () => {
    renderCard(
      makeRecording({
        start_time: FUTURE,
        end_time: FUTURE,
        custom_properties: { status: 'scheduled', program: { title: 'Test Show' } },
      })
    );
    expect(screen.getByRole('button', { name: 'Cancel recording' })).toBeInTheDocument();
  });

  it.each(['Extend recording', 'Stop recording (keep partial content)', 'Cancel & delete recording'])(
    'an in-progress recording names its %s control (#65: it had none)',
    (name) => {
      renderCard(
        makeRecording({
          end_time: FUTURE,
          custom_properties: { status: 'recording', program: { title: 'Test Show' } },
        })
      );
      expect(screen.getByRole('button', { name })).toBeInTheDocument();
    }
  );
});
```

### Appendix H4 — `frontend/src/components/cards/__tests__/StreamConnectionCard.a11y.test.jsx`

Assemble in this order:
1. The header below.
2. `StreamConnectionCard.test.jsx` lines `4-58`, with two edits inside the
   `StreamConnectionCardUtils.js` mock. File line `50` (not the 47th line of the excerpt) becomes
   `getChannelStreams: vi.fn(() => Promise.resolve([{ id: 42, name: 'S1' }])),` and file line `55`
   becomes `getStreamOptions: vi.fn(() => [{ value: '42', label: 'S1' }]),`. The Preview button
   renders only when the card has streams (`StreamConnectionCard.jsx:626`,
   `availableStreams.length > 0`).
3. Lines `72-73` verbatim: the logo mock. **Skip** `60-70`, the `CustomTable` and `helpers`
   mocks, because the real table must render the client row. Skip `75-180` too, the
   `@mantine/core` and `lucide-react` mocks.
4. Lines `182-286` verbatim: the imports after the mocks, then the helpers through `setupStores`.
5. The tail below.

Header:

```jsx
// Accessible names on StreamConnectionCard's icon-only controls (#137).
// Renders the REAL @mantine/core and the real CustomTable: the accessibility
// tree is what is under test, and StreamConnectionCard.test.jsx mocks both.
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MantineProvider } from '@mantine/core';
import mantineTheme from '../../../mantineTheme';
```

Tail:

```jsx
describe('StreamConnectionCard controls have accessible names (#137)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupLocation('/stats');
    setupStores();
  });

  it.each(['Stop Channel', 'Disconnect client', 'Preview Channel'])(
    'the %s control is reachable by role and name (#137: it had none)',
    async (name) => {
      render(
        <MantineProvider theme={mantineTheme}>
          <StreamConnectionCard {...defaultProps()} />
        </MantineProvider>
      );
      expect(await screen.findByText('192.168.1.10')).toBeInTheDocument();
      expect(await screen.findByRole('button', { name })).toBeInTheDocument();
    }
  );
});
```

### Appendix H5 — `frontend/src/components/backups/__tests__/BackupManager.a11y.test.jsx`

```jsx
// Accessible names on BackupManager's icon-only row actions (#137).
// Deliberately renders the REAL @mantine/core: the accessibility tree is what
// is under test, and BackupManager.test.jsx's Mantine mock defines its own.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';

vi.mock('../../../utils/components/backups/BackupManagerUtils.js', async (importOriginal) => ({
  ...(await importOriginal()),
  listBackups: vi.fn(),
  getBackupSchedule: vi.fn(),
}));
vi.mock('../../../utils/notificationUtils.js', () => ({ showNotification: vi.fn() }));

import BackupManager from '../BackupManager';
import { listBackups, getBackupSchedule } from '../../../utils/components/backups/BackupManagerUtils.js';

describe('BackupManager row actions have accessible names (#137)', () => {
  beforeEach(() => {
    vi.mocked(listBackups).mockResolvedValue([
      { name: 'backup-2024-01-01.zip', size: 1024, created: '2024-01-01T10:00:00Z' },
    ]);
    vi.mocked(getBackupSchedule).mockResolvedValue({
      enabled: false, frequency: 'daily', time: '03:00', day_of_week: 0,
      retention_count: 0, cron_expression: '',
    });
  });

  it.each(['Download backup', 'Restore backup', 'Delete backup'])(
    'the %s row action is reachable by role and name (#137: it had none)',
    async (name) => {
      render(<MantineProvider><BackupManager /></MantineProvider>);
      expect(await screen.findByText('backup-2024-01-01.zip')).toBeInTheDocument();
      expect(screen.getByRole('button', { name })).toBeInTheDocument();
    }
  );
});
```

### Appendix H6 — `frontend/src/components/cards/__tests__/PluginCard.a11y.test.jsx`

Assemble in this order:
1. The header below.
2. `PluginCard.test.jsx` lines `9-33` verbatim: the `notificationUtils`, `PluginCardUtils` and
   `Field` mocks. **Skip** `35-84`, the `@mantine/core` mock.
3. The tail below.

Header:

```jsx
// Accessible name on PluginCard's enable switch (#73).
// Renders the REAL @mantine/core: the accessibility tree is what is under
// test, and PluginCard.test.jsx mocks Mantine (its Switch mock renders a
// plain checkbox, where real Mantine renders role="switch").
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import PluginCard from '../PluginCard';
```

Tail:

```jsx
const plugin = {
  key: 'test-plugin',
  name: 'Test Plugin',
  description: 'A test plugin',
  version: '1.0.0',
  enabled: true,
  ever_enabled: true,
  settings: {},
  fields: [],
  actions: [],
};

const props = {
  onSaveSettings: vi.fn(),
  onRunAction: vi.fn(),
  onToggleEnabled: vi.fn(),
  onRequireTrust: vi.fn(),
  onRequestDelete: vi.fn(),
  onRequestConfirm: vi.fn(),
};

describe('PluginCard enable switch has an accessible name (#73)', () => {
  it('the enable switch is named after its plugin (#73: it had none)', () => {
    render(
      <MantineProvider>
        <PluginCard plugin={plugin} {...props} />
        <PluginCard plugin={{ ...plugin, key: 'other', name: 'Other Plugin' }} {...props} />
      </MantineProvider>
    );
    expect(screen.getByText('Test Plugin')).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Enable Test Plugin' })).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Enable Other Plugin' })).toBeInTheDocument();
  });
});
```

### Appendix H7 — `frontend/src/pages/__tests__/Plugins.a11y.test.jsx` (recipe B)

Assemble in this order:
1. The four comment lines of the header below.
2. `Plugins.test.jsx` lines `1-2`, then `import { MantineProvider } from '@mantine/core';`, then
   lines `3-30` verbatim: the imports, the store mock, and the `PluginsUtils` and
   `notificationUtils` mocks.
3. The `@mantine/core` mock at `32-154`, converted in three ways:
   - line `32` `vi.mock('@mantine/core', async () => {` becomes
     `vi.mock('@mantine/core', async (importOriginal) => {` followed by
     `  const actual = await importOriginal();`;
   - after line `33` (`  return {`), add `    MantineProvider: actual.MantineProvider,` and
     `    Switch: actual.Switch,`;
   - delete the mocked `Switch` entry at lines `75-85`.
   Every other entry stays exactly as it is.
4. Lines `155-181` verbatim: the `@mantine/dropzone` and `PluginCard` mocks.
5. `describe('Plugins import modal switch has an accessible name (#73)', () => {`, then lines
   `184-219` verbatim (`mockPlugins`, `mockPluginStoreState` and the `beforeEach`), then the test
   and closing brace below.

Header comment:

```jsx
// Accessible name on the import modal's "Enable now" switch (#73).
// Mantine stays mocked as in Plugins.test.jsx, EXCEPT Switch and
// MantineProvider, which are real: the flow to reach the switch runs through
// a mocked FileInput, and the switch itself is what is under test.
```

Test, placed after the copied `beforeEach`:

```jsx
  it('the Enable now switch is reachable by role and name (#73: it had none)', async () => {
    importPlugin.mockResolvedValue({
      success: true,
      plugin: { key: 'new-plugin', name: 'New Plugin', description: 'New Description', ever_enabled: false, enabled: false },
    });
    render(
      <MantineProvider>
        <PluginsPage />
      </MantineProvider>
    );
    fireEvent.click(screen.getByText('Import Plugin'));
    fireEvent.change(screen.getByPlaceholderText('Select plugin .zip'), {
      target: { files: [new File(['content'], 'plugin.zip', { type: 'application/zip' })] },
    });
    fireEvent.click(screen.getAllByText('Upload').find((btn) => btn.tagName === 'BUTTON'));
    await waitFor(() => {
      expect(screen.getByText('Enable now')).toBeInTheDocument();
    });
    expect(screen.getByRole('switch', { name: 'Enable now' })).toBeInTheDocument();
  });
});
```

### Appendix H8 — `frontend/src/components/cards/__tests__/AvailablePluginCard.a11y.test.jsx` (recipe B)

Assemble in this order:
1. The four comment lines of the header below.
2. `AvailablePluginCard.test.jsx` lines `1-2`, then
   `import { MantineProvider } from '@mantine/core';`, then lines `3-85` verbatim.
3. The `@mantine/core` mock at `86-152`, converted in three ways:
   - line `86` `vi.mock('@mantine/core', () => ({` becomes
     `vi.mock('@mantine/core', async (importOriginal) => {`, `  const actual = await importOriginal();`,
     `  return {`, `    MantineProvider: actual.MantineProvider,`, `    Switch: actual.Switch,`;
   - delete the mocked `Switch` entry at lines `134-145`;
   - line `152` `}));` becomes `  };` then `});`.
   Every other entry stays as it is, re-indented by two spaces or not, as prettier decides.
4. Lines `153-266` verbatim: the `lucide-react` mock, the imports after the mocks, `makePlugin`,
   `APP_VERSION`, `setupMocks` and `getModalActionButton`.
5. The tail below.

Header comment:

```jsx
// Accessible name on the install modal's "Enable plugin" switch (#73).
// Mantine stays mocked as in AvailablePluginCard.test.jsx, EXCEPT Switch and
// MantineProvider, which are real: the flow to reach the switch runs through
// mocked modals, and the switch itself is what is under test.
```

Tail:

```jsx
describe('AvailablePluginCard enable switch has an accessible name (#73)', () => {
  it('the install modal names its Enable plugin switch (#73: it had none)', async () => {
    const { mockInstallPlugin } = setupMocks();
    mockInstallPlugin.mockResolvedValue({
      success: true,
      plugin: { key: 'test-plugin', enabled: false },
    });
    render(
      <MantineProvider>
        <AvailablePluginCard plugin={makePlugin()} appVersion={APP_VERSION} />
      </MantineProvider>
    );
    fireEvent.click(screen.getByTestId('sized-install-button'));
    fireEvent.click(getModalActionButton('Install'));
    await waitFor(() => {
      expect(screen.getByText('Enable plugin')).toBeInTheDocument();
    });
    expect(screen.getByRole('switch', { name: 'Enable plugin' })).toBeInTheDocument();
  });
});
```

### Appendix I — F-4 (only if Q1 is yes): `frontend/src/__tests__/accessibleNames.ratchet.test.js`

Set `FLOOR` to the count measured on `main` after F-3 merges (Task 4.1). `89` is the prototype's
measurement on F-3's tree.

```js
// @vitest-environment node
// A count-down ratchet on icon-only controls with no accessible name.
//
// Counting rule (the only definition this number has): every `<ActionIcon` or
// `<Switch` opening tag in a non-test `frontend/src/**/*.jsx` file whose tag
// text contains none of `aria-label`, `aria-labelledby`, `title=` or `label=`.
// The tag ends at the first `>` outside `{…}` that is not part of `=>`.
//
// Known blind spot: a control named through a prop spread
// (`<ActionIcon {...a11yProps}>`) or by a wrapper component is named at
// runtime and unnamed to this scan, which reads source text. Mark such a tag
// on the line directly above it with `{/* a11y-name: <reason> */}` inside JSX,
// or `// a11y-name: <reason>` outside it. A marker with no reason clears
// nothing, the same rule as the relay's `// credential-logging: ok - <reason>`.
//
// Measured, never computed: 107 in 43 files at a54b09a9; 89 in 35 files on
// the tree PR F-3 produced (F-3 named 18 controls in eight files). FLOOR is
// the count measured on main after F-3 merged. A change that fixes more
// lowers FLOOR in the same PR. A change that exceeds it names its controls,
// and never raises FLOOR.
import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const FLOOR = 89; // prototype value: Task 4.1 step 1 replaces it with the count on main
const SRC = fileURLToPath(new URL('..', import.meta.url));
const NAMED = ['aria-label', 'aria-labelledby', 'title=', 'label='];
const MARKER = /a11y-name:\s*[^\s*]/;
const FIXED_BY_F3 = [
  'components/tables/UsersTable.jsx',
  'components/tables/LogosTable.jsx',
  'components/cards/RecordingCard.jsx',
  'components/cards/StreamConnectionCard.jsx',
  'components/backups/BackupManager.jsx',
  'components/cards/PluginCard.jsx',
  'pages/Plugins.jsx',
  'components/cards/AvailablePluginCard.jsx',
];

const jsxFiles = (dir) =>
  readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === '__tests__' ? [] : jsxFiles(path);
    return name.endsWith('.jsx') ? [path] : [];
  });

const unnamedIn = (source) => {
  const found = [];
  for (const match of source.matchAll(/<(ActionIcon|Switch)\b/g)) {
    let i = match.index + match[0].length;
    let depth = 0;
    for (; i < source.length; i += 1) {
      const c = source[i];
      if (c === '{') depth += 1;
      else if (c === '}') depth -= 1;
      else if (c === '>' && depth === 0 && source[i - 1] !== '=') break;
    }
    const tag = source.slice(match.index, i + 1);
    const before = source.slice(0, match.index).split('\n');
    const lineAbove = before.length > 1 ? before[before.length - 2] : '';
    if (!NAMED.some((n) => tag.includes(n)) && !MARKER.test(lineAbove)) {
      found.push(`${match[1]}@${source.slice(0, match.index).split('\n').length}`);
    }
  }
  return found;
};

const scan = () =>
  Object.fromEntries(
    jsxFiles(SRC)
      .map((f) => [relative(SRC, f), unnamedIn(readFileSync(f, 'utf8'))])
      .filter(([, sites]) => sites.length > 0)
  );

describe('icon-only controls without an accessible name', () => {
  it('stay at or below the floor', () => {
    const byFile = scan();
    const total = Object.values(byFile).flat().length;
    expect(total, JSON.stringify(byFile, null, 1)).toBeLessThanOrEqual(FLOOR);
  });

  it.each(FIXED_BY_F3)('%s has none left (#65, #73, #137)', (file) => {
    expect(scan()[file] ?? []).toEqual([]);
  });
});
```
