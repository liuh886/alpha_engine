# Archived research paradigms

Paradigm specs moved here are **superseded snapshots with zero references**
from tracked code, tests, workflows, or other configs (verified via
`git grep <stem>` before each move). They are retained for provenance, not
for execution — no new caller may reference this directory.

| File | Reason |
|---|---|
| `cn_x1_0_frozen_v1_2026_08_03.yaml` | Dated snapshot superseded by `../cn_x1_0_frozen_v1.yaml`; unreferenced. |

Note: the QQQ v4.2–v4.32 history files stay in the parent directory on
purpose — the live QQQ v4.3 formal path (`src/research/formal_model_replay.py`,
`scripts/refresh_qqq_v4_3_formal.py`, `qqq-v4-3-signal-alert.yml`) still
references the v4.1/v4.2 bridge specs. See issue #858.
