# H2 / #1282 — 2026-11-01 Current Environment Replay Evidence Packet

**A5 status: PENDING_OWNER_ACCEPTANCE.** Baseline commit `main` @ `f68f1c1198e1af4b8fcdd60219dee878d5c64321`.
This packet records bounded local deterministic replay verification in the current frozen environment for Direction A Gate A5.

## 1. Commands and Direct Outcomes

```powershell
uv run --frozen alpha research replay cn_27_v1_3
uv run --frozen alpha research replay qqq_v4_3
```

- **CN_27 v1.3**: Exit code `0`, `decision: exact_replay`, `status: completed`.
  - Manifest: `data/research/formal_model_runs/cn_27_rotation/cn_27_v1_3/cn_27_v1_3-through-2026_10_30/manifest.json`
  - Manifest SHA-256: `00f3121744ecf58ad65cec02cba45090ae70a03964a7334f2f04a490f99bf2f0`
  - Bundle ID: `3212bd7cee3aa85ee92c4180c3b2681969322f58a15d473de03e13a8a2c5c32d`
  - Replay evaluation matched published allocations, trades, reports and attribution at predefined $\le 10^{-6}$ numerical tolerance.
- **QQQ v4.3**: Exit code `1`, `decision: replay_failed`, `status: blocked`.
  - Reason: `"QQQ exact replay requires a professional bundle or the exact frozen Yahoo research source"`.
  - Diagnosis: The formal backtest refresh on 2026-10-31 (#1343) updated the accepted evidence cutoff to `2026-10-30`. The local clean environment retains frozen source data through `2026-10-23` while live Yahoo access is unconfigured / network-restricted in this local session. In accordance with §12.4, missing fresh external source bytes are truthfully recorded as `BLOCKED`, rather than fabricated.

## 2. Test Verification and Path Portability

- `tests/test_formal_model_replay.py`: **15 passed**
- `tests/test_rules_formal_replay_gate.py`: **17 passed**
- Total: **32 passed, 0 failures**.
- Fixed `_load_cn_frozen_score_cross_sections` in `src/research/rules_formal_replay_gate.py` to normalize and resolve root paths across Windows junctions.

## 3. Boundary and Governance Note

Replay receipts preserve research memory and confirm execution determinism under identical inputs. They do not authorize trading, modify sealed economic history, or bypass Owner A5 acceptance.
