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
| `qqq_tqqq_absolute_breadth_scaling_v4_2.yaml` | Superseded QQQ/QQQI v4.x research; only caller was the retired runner `scripts/run_qqq_tqqq_absolute_breadth_scaling_v4_2.py`; zero live references (2026-09-19). |
| `qqq_tqqq_credit_risk_veto_v4_2.yaml` | Superseded QQQ/QQQI v4.x research; only caller was the retired runner `scripts/run_qqq_tqqq_credit_risk_veto_v4_2.py`; zero live references (2026-09-19). |
| `qqq_tqqq_downside_vol_veto_v4_2.yaml` | Superseded QQQ/QQQI v4.x research; only caller was the retired runner `scripts/run_qqq_tqqq_downside_vol_veto_v4_2.py`; zero live references (2026-09-19). |
| `qqq_tqqq_vxn_attack_v4_1_long_history.yaml` | Superseded QQQ/QQQI v4.x research; only caller was the retired runner `scripts/run_qqq_tqqq_vxn_attack_v4_1_long_history.py`; zero live references (2026-09-19). |
| `qqq_tqqq_vxn_exit_persistence_v4_2.yaml` | Superseded QQQ/QQQI v4.x research; only caller was the retired runner `scripts/run_qqq_tqqq_vxn_exit_persistence_v4_2.py`; zero live references (2026-09-19). |
| `qqq_tqqq_vxn_v4_1_churn_diagnostics.yaml` | Superseded QQQ/QQQI v4.x research; only caller was the retired runner `scripts/run_qqq_tqqq_vxn_v4_1_churn_diagnostics.py`; zero live references (2026-09-19). |
| `qqqi_qqq_tqqq_breadth_vxn_v4.yaml` | Superseded QQQ/QQQI v4.x research; only caller was the retired runner `scripts/run_qqqi_qqq_tqqq_breadth_vxn_v4.py`; zero live references (2026-09-19). |
| `qqqi_qqq_tqqq_v4_2_post_defense_state2_accelerator_v4_10_research.yaml` | Superseded QQQ/QQQI v4.x research; only caller was the retired runner `scripts/run_qqqi_v4_2_post_defense_state2_accelerator.py`; zero live references (2026-09-19). |
| `qqqi_qqq_tqqq_v4_2_risk_confirmation_v4_3_research.yaml` | Superseded QQQ/QQQI v4.x research; only caller was the retired runner `scripts/run_qqqi_v4_2_risk_confirmation_experiment.py`; zero live references (2026-09-19). |
| `qqqi_qqq_tqqq_v4_2_sgov_defense_v4_3_research.yaml` | Superseded QQQ/QQQI v4.x research; only caller was the retired runner `scripts/run_qqqi_v4_2_sgov_defense_experiment.py`; zero live references (2026-09-19). |
| `qqqi_qqq_tqqq_v4_2_state2_tail_diagnostics.yaml` | Superseded QQQ/QQQI v4.x research; only caller was the retired runner `scripts/run_qqqi_v4_2_state2_tail_experiment.py`; zero live references (2026-09-19). |
| `qqqi_state2_intraday_meta_label_v4_21_research.yaml` | Superseded QQQ/QQQI v4.x research; only caller was the retired runner `scripts/run_qqqi_v4_21_intraday_preflight.py`; zero live references (2026-09-19). |

Orphan candidacy is derived mechanically by `scripts/check_ci_governance.py`
(`research_assets` inventory: scheduled / referenced_only / evidence_only /
orphan_candidate). Self-mentions, paradigm-to-paradigm lineage notes, docs
and sealed receipts never count as life. Moves preserve git history.

Note: QQQ v4.x specs that the live v4.3 formal path still references
(`src/research/formal_model_replay.py`, `scripts/refresh_qqq_v4_3_formal.py`,
`qqq-v4-3-signal-alert.yml`) — currently the v4.1/v4.2 bridge specs — remain in
the parent directory. Only zero-reference v4.x snapshots are archived here. See
issue #858.
