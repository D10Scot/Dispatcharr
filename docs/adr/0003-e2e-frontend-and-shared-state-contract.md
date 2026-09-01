# 3. The `data-testid` contract and the shared-instance mutation rules are enforced, not documented

Date: 2026-09-01

## Status

Accepted

## Context

Two rules governed this suite by convention, each written down in exactly one
place and depended on everywhere.

**The testId contract.** `e2e/tests/frontend/helpers.ts` states it: testIds are
"what a test waits on, and nothing here selects by text: text selectors couple
the suite to UI copy". So the `data-testid` attributes in `frontend/src/` are an
interface between two codebases. Nothing checked that the interface held.
Renaming one in the frontend produced a `getByTestId` timeout that reads like a
broken test rather than a broken contract — `e2e/README.md` says so directly,
and could not prevent it.

**The shared-instance mutation rules.** ADR-0001 established that every project
shares one container. `playwright.config.ts` twice reasons in prose about the
consequence, and twice says nobody enforces it. Of `failover-buffering.spec.ts`
raising `proxy_settings.buffering_speed`: "nothing enforces that convention, so
a future ffmpeg-profile spec added here without reading that test's header would
race the raised threshold and fail silently." The same observation is made about
`vod-redirect-profile.spec.ts` and `default_stream_profile`.

Both rules were load-bearing and both decayed silently by construction — the
failure mode this suite already named when `quarantine.spec.ts` was written: "a
convention plus a README decays silently."

## Decision

Promote both from prose to this record, and enforce the mechanically
enforceable half.

### The testId contract

- `SURFACES` in `e2e/tests/frontend/helpers.ts` is the register of surface
  testIds. Tests reach a surface through `gotoSurface`, never a direct
  `page.goto` (see that function's comment, and issue #58).
- Selecting by text is not permitted; it couples the suite to UI copy.
- `backups-panel` deliberately breaks the `<surface>-page` naming pattern,
  because Backups is a panel inside Settings rather than a route. **Do not
  "fix" it.**
- **Enforced** by `e2e/tests/guards/testid.spec.ts`: every testId in `SURFACES`
  must exist as a `data-testid` under `frontend/src/`. One-directional — an
  unused handle in the frontend is harmless, and asserting on those would make
  adding one to a component a failing build.

### The shared-instance mutation rules

- **Never assert a global count or an unfiltered list.** The instance is never
  empty. Filter on the name `seed` generated. *(Review-only — see below.)*
- **Never assert on a notification toast.** It turns a backend assertion into a
  frontend one. *(Review-only.)*
- **Instance-wide settings writes are allowlisted and argued.** **Enforced** by
  `e2e/tests/guards/global-mutation.spec.ts`: any write to `/api/core/settings/`
  from a file not on `GLOBAL_SETTINGS_WRITE`'s list fails. Adding a file
  requires saying in the diff which group it writes, why nothing else reads it,
  and how teardown restores it.

**Which rules are enforced and which are not is stated plainly here on
purpose.** Implying all three are checked would reproduce exactly the failure
this ADR exists to fix. The count and toast rules remain review-only because
neither has a reliable static signature; if one acquires a defensible one, it
gets a guard and this section gets edited.

## Why the settings rule is the endpoint, not a list of keys

`core/models.py:CoreSettings` is not one row per setting. `key` is unique,
`value` is a `JSONField`, and **each row is a whole settings group** — eight of
them (`stream_settings`, `dvr_settings`, `backup_settings`, `proxy_settings`,
`network_access`, `system_settings`, `epg_settings`, `user_limit_settings`).
Every one is instance-wide, so there is no such thing as a scoped `CoreSettings`
write. "Any write to that endpoint" is therefore exact, needs no key list to
maintain, and cannot be defeated by a group nobody enumerated — including
`epg_settings`, which has no seeding migration and must be POSTed into existence
before it can be PATCHed.

## Why serialising a project is not a substitute

`playwright.config.ts` reaches for `workers: 1` twice to contain these
mutations. That bounds concurrency, not blast radius.

`CoreSettings._get_group` caches each group in Redis for 300 seconds, and
`_REDIRECT_STREAM_PROFILE_ID_CACHE_KEY` (`core/models.py`) has **no `post_save`
invalidation at all** — it appears nowhere in `core/signals.py`, unlike the
group caches. A mutation faithfully reverted in teardown can still be live five
minutes later, in a different project, on a different worker, in a different CI
job against the same container.

Serialisation bounds concurrency; only the allowlist bounds blast radius. Both
are kept.

## Consequences

- A frontend rename that breaks the suite now fails a guard that names the
  surface, in a job that takes about a second, instead of timing out inside a
  browser test.
- Adding a global settings write is a reviewable decision with a written
  argument, not an edit nobody sees.
- The guards live in the `guards` Playwright project, which needs no container
  and runs as its own CI job.
- Every file on a capability allowlist is `@characterization` under
  [ADR-0002](0002-e2e-test-taxonomy.md).
