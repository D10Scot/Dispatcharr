# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Edit the right-hand column to match whatever vocabulary you actually use.

All five exist on `D10Scot/Dispatcharr` as of 2026-08-23. `wontfix` was already present as a
GitHub stock label; the other four were created during setup. Apply them with an explicit
`--repo D10Scot/Dispatcharr` — see `issue-tracker.md` for why.

## Tracker-only labels

One label has no counterpart in the skills' vocabulary and is not a triage role:

| Label in our tracker | Meaning                                                                 |
| -------------------- | ----------------------------------------------------------------------- |
| `re-triage`          | The 2026-09-23 issue sweep judged this issue stale or superseded by the post-Phase-2 tree (the live relay is Go; `live_proxy/` is deleted). A human re-decides before any agent picks it up. |

`re-triage` was created by the sweep, not during setup, and it sits alongside whatever
triage label the issue already carried rather than replacing it, so an issue can carry
both `re-triage` and `ready-for-agent`. Nothing in the gh-aw pipeline knows the label
yet: `issue-remediation` excludes only `wontfix` and `needs-info`, so an issue carrying
`re-triage`, `ready-for-agent` and a priority label is still eligible for it. Treat `re-triage` as overriding whatever else the issue says — an agent choosing
work skips it until a human has removed the label (the issue is still valid as written),
re-labelled it (it needs a fresh triage) or closed it (the sweep's verdict stands).
