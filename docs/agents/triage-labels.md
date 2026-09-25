# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |
| (none)                     | `re-triage`          | Sweep judged it stale; a human re-decides |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Edit the right-hand column to match whatever vocabulary you actually use.

All five exist on `D10Scot/Dispatcharr` as of 2026-08-23. `wontfix` was already present as a
GitHub stock label; the other four were created during setup. Apply them with an explicit
`--repo D10Scot/Dispatcharr` — see `issue-tracker.md` for why.

`re-triage` is local to this tracker and has no counterpart in the mattpocock/skills vocabulary.
The 2026-09-23 issue sweep (178 open issues assessed against main `a54b09a9`) applied it to the
62 issues it judged stale or superseded by the Phase 2 tree — the live relay is Go and
`apps/proxy/live_proxy/` is deleted, so a report written against the Python relay may describe
code that no longer exists. It means: **a human re-decides before any agent picks the issue up.**
Treat an issue carrying it as not `ready-for-agent`, whatever other labels it holds. Note that
`issue-remediation`'s selection filter excludes only `wontfix` and `needs-info`, so an issue
carrying both `re-triage` and `ready-for-agent` is still eligible for automated pickup until a
human clears one of them. Clearing `re-triage` is a human action: either re-triage the issue
into one of the five roles above, or close it.
