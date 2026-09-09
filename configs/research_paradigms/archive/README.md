# Archived research paradigms

Paradigm specs moved here are **superseded snapshots with zero references**
from tracked code, tests, workflows, or other configs (verified via
`git grep <stem>` before each move). They are retained for provenance, not
for execution — no new caller may reference this directory.

| File | Reason |
|---|---|
| `cn_x1_0_frozen_v1_2026_08_03.yaml` | Dated snapshot superseded by `../cn_x1_0_frozen_v1.yaml`; unreferenced. |
| `qqqi_qqq_tqqq_converged_candidate.yaml` | Superseded QQQ candidate; zero live references (2026-09-09 governance pilot). |
| `qqqi_qqq_tqqq_v4_2_qqq_proxy_long_history_v4_6_research.yaml` | Superseded v4.6 research; zero live references (2026-09-09 governance pilot). |
| `qqqi_qqq_tqqq_v4_2_recovery_precursor_failure_taxonomy_v4_7_research.yaml` | Superseded v4.7 research; zero live references (2026-09-09 governance pilot). |
| `qqqi_qqq_tqqq_v4_2_sgov_episode_attribution.yaml` | Superseded attribution research; implementation lives on in `src/research/v4_2_sgov_episode_attribution*.py` + tests; zero live references to this spec (2026-09-09 governance pilot). |
| `qqqi_qqq_tqqq_v4_2_sgov_precursor_50_v4_5_research.yaml` | Superseded v4.5 research; zero live references (2026-09-09 governance pilot). |
| `qqqi_qqq_tqqq_v4_2_sgov_recovery_release_v4_4_research.yaml` | Superseded v4.4 research; zero live references (2026-09-09 governance pilot). |
| `qqqi_qqq_tqqq_v4_2_tqqq_path_efficiency_v4_8_research.yaml` | Superseded v4.8 research; zero live references (2026-09-09 governance pilot). |

Orphan candidacy is derived mechanically by `scripts/check_ci_governance.py`
(`research_assets` inventory: scheduled / referenced_only / evidence_only /
orphan_candidate). Self-mentions, paradigm-to-paradigm lineage notes, docs
and sealed receipts never count as life. Moves preserve git history.

Note: the QQQ v4.2–v4.32 history files stay in the parent directory on
purpose — the live QQQ v4.3 formal path (`src/research/formal_model_replay.py`,
`scripts/refresh_qqq_v4_3_formal.py`, `qqq-v4-3-signal-alert.yml`) still
references the v4.1/v4.2 bridge specs. See issue #858.
