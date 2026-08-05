# CN130 primary event-family Phase 2 result

**Decision:** `event_population_built_no_family_eligible`

This phase audits primary CNINFO announcements only. It does not inspect returns or create a model candidate.

## Family gates

| Family | Events | Symbols | Fixed eligible | Event-driven eligible |
|---|---:|---:|---:|---:|
| buyback | 2037 | 84 | False | False |
| restricted_unlock | 233 | 71 | False | False |

## Boundary

A passing data gate only authorizes a separately preregistered model experiment. Current-state buyback or unlock snapshots were not backfilled into history.
