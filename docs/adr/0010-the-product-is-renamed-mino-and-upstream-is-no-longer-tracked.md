# 10. The product is renamed Mino, and upstream is no longer tracked

Date: 2026-10-28

## Status

Accepted. Amends [ADR 0008](0008-phase-4-reopens-the-programme-for-apple-native-live-playback.md)
where it says "The rename itself is not Phase 4 work", and the Phase 4 spec's ruling R15 ("No
renaming now"): the rename is now chartered, as its own programme, by
`docs/superpowers/specs/2026-10-28-mino-rename-design.md`. Every other part of ADR 0008 stands.

## Context

`CONTEXT.md` has called the product "Mino" since Phase 4 began: the server and the Apple app
together. The Apple app already ships under that name (`D10Scot/mino-apple`, bundle
`scot.d10.mino`), and every identifier added since Phase 4 is named for Mino or named neutrally
(`/api/mino/capabilities/`, `/hls/<token>/…`). Everything older still says "Dispatcharr": about
7,200 lines in 694 tracked files at `632f1d3d`.

The fork has also stopped being a fork in practice. Since the relay extraction, the live path, the
process model and most of the test machinery have no counterpart upstream. GitHub already records
the repository as a standalone one (`isFork: false`), and the local checkout has no `upstream`
remote, so `git fetch upstream` fails. A merge from `Dispatcharr/Dispatcharr` would conflict with
nearly every file this programme touched.

There is one deployment, the owner's, and it must upgrade in place with its data intact.

## Decision

1. **The product is renamed Mino.** The repository becomes `D10Scot/mino` and the image becomes
   `ghcr.io/d10scot/mino`. Everything a user, an operator or a client sees says Mino. The rename
   design spec orders the work into a PR sequence and decides each category of identifier.
2. **Upstream is no longer tracked.** No `upstream` remote is kept, nothing is merged or
   cherry-picked from `Dispatcharr/Dispatcharr`, and an idea from upstream is reimplemented
   here, never merged. The cost of conflicting with upstream no longer constrains any decision.
   The fork's AGPL-3.0 licence and its attribution to Dispatcharr are kept: the README and the
   About dialog say that Mino is derived from Dispatcharr.
3. **Decision records keep the old name.** ADRs, specs, plans, analyses, Done logs, the changelog
   and `docs/comparisons/` describe what was true when they were written. They are never edited
   to say Mino, and they are never moved, because other repositories pin links to them.
4. **Internal names that persisted data, or a third party, depend on stay as they are.** Examples
   are the Django app labels `dispatcharr_channels` and `dispatcharr_connect` (which name tables),
   the PostgreSQL database `dispatcharr` and its role `dispatch`, the `dispatcharr/` settings
   package, and the plugin manifest keys `min_dispatcharr_version` and `max_dispatcharr_version`.
   Each one is listed with its reason in the spec. `CONTEXT.md` records them as internal names so
   that no one "finishes" the rename by changing one of them.

## Consequences

- The rename spans the image name, signer identities, the Pages URL and the env var names. The
  owner performs the repository rename at the point the spec names. One PR before it makes CI
  independent of the repository's name; one PR after it moves every hard-coded reference.
- Old image tags under `ghcr.io/d10scot/dispatcharr` remain. They are the owner's rollback, and the
  upgrade test's baseline. The old package must not be deleted.
- GitHub redirects the old repository URL only while no new repository takes the name
  `D10Scot/Dispatcharr`. Re-forking upstream under that name would break every old link,
  including those in decision records and in `D10Scot/mino-apple`.
- A grep for "dispatcharr" never reaches zero. A ratchet (`scripts/check_product_name.py`, the
  spec's first implementation PR) exempts the records and counts what is left per file, so that the
  remaining occurrences are visible and can only go down.
- Ruling R15's protection, that no new identifier is named for Dispatcharr, is kept, and the
  ratchet now enforces it.
