# 4. A release trusts the migration gate instead of running its own tests

Date: 2026-09-03

## Status

Accepted

## Context

`release.yml` was inherited from upstream and has never run on this fork. As
written it cannot: its `prepare` job bumps `version.py`, commits, and pushes
the commit and a tag straight to `main`, and the `Main` ruleset requires a pull
request for every change to `main`. It also runs no test. A release cut from it
would build and sign whatever `main` held, tested or not.

The E2E programme (G1–G15) built the migration gate — the set of result
aggregates a PR must pass — for one purpose: so that the relay extraction has a
gate it can trust. That gate is the most expensive thing this fork owns. The
question was whether a release should re-run the suites itself or rely on the
fact that every commit on `main` already passed them.

Three shapes were considered:

1. Re-run the backend, frontend and E2E workflows inside `release.yml` as
   reusable workflows. Self-contained, but doubles CI time per release and
   forces every test workflow into `workflow_call` shape.
2. Trust the gate: verify that the required checks passed on the exact SHA
   being released, tag that SHA, build and sign. No commit from the workflow.
3. Tag only, with `version.py` rewritten at image build time from the tag.
   One step, but the checked-in version is then permanently wrong and a local
   run disagrees with the image it was built into.

## Decision

A release is two steps, and the workflow commits nothing.

1. A normal pull request bumps `version.py` and merges through the gate like
   any other change.
2. A manual dispatch on `main` with a `version` input runs a `verify` job
   that refuses unless: the ref is `main`; `version.py` matches the input; the
   tag does not already exist; and **every required status check named in the
   `Main` ruleset** — read from the ruleset via the API at run time, not
   hard-coded — has a latest run of `success` on the head SHA. Only then does it
   tag that SHA, build, sign, attest and create the release.

The check list is read from the ruleset so that the release and the gate are
the same thing seen from two sides. Adding a required check to the ruleset
tightens the release with no workflow edit; hard-coding the names would let
the two drift, and a release that ran a stale list would be a release that
skipped a suite while claiming not to.

The ruleset itself requires all four result aggregates — `E2E result`,
`Lifecycle result`, `Backend result`, `Frontend result` — with squash-only
merges and the strict up-to-date policy. Each aggregate always reports, and
passes on a run where its own change detection proved the suite unnecessary.
That is what makes "the check succeeded on this SHA" meaningful: a skipped
heavy job on a run that needed it is a failure, not a pass.

## Consequences

- A release can never ship a commit the gate did not pass, and cannot ship
  from a branch.
- `release.yml` needs `contents: write` only to push a tag and create the
  release; `persist-credentials` on checkout goes back to `false`.
- The version bump is reviewed like any change, and `version.py` is always
  true on `main`.
- Cutting a release costs no test time. The cost moved to the ruleset's strict
  up-to-date policy, which re-runs the aggregates on a queued PR after each
  merge ahead of it. For unrelated diffs that is minutes; for a `migration/**`
  branch it is the full run. Accepted.
- If a required check is ever renamed, the release fails closed until the
  ruleset and the workflow producing the check agree again. That is the
  intended failure.
- The verify job reads the ruleset with the default `GITHUB_TOKEN`; on a
  private repository that needs `metadata: read`, which the default token
  carries. Confirm on the first dry run.
