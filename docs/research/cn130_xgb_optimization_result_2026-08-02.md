# CN130 XGBoost bounded optimization result

## Decision

`baseline_only`; `trade_ready=false`.

None of the eight pre-registered XGBoost variants improved the ranking-aligned development objective over the existing `cn_balanced_ohlcv` baseline. The frozen 2026H1 challenge therefore compared the baseline with itself and confirmed that no new candidate should replace it.

## Evidence identity

- PR: #344
- Workflow run: `30733728747`
- Artifact: `8828889722`
- Artifact digest: `sha256:8696b9d12a11b86f8732b571ea225fed3e6c23f27a29f977a7ed925d3bf08307`
- Provider cutoff: 2026-07-31
- Provider identity: differs from the PR #289 provider because all 131 source CSV snapshots and the calendar were refreshed
- Development windows: 2024H1, 2024H2, 2025H1, 2025H2
- Frozen challenge: 2026H1
- Development variants attempted: 8

## Winning development configuration

The existing baseline remained best:

- Feature group: `cn_balanced_ohlcv`
- XGBoost calibration:
  - gain bins: 5
  - boosting rounds: 100
  - leaves: 31
  - minimum leaf data: 10
  - learning rate: 0.05
- Strategy: Top-15 equal weight, 10-session holding/rebalance
- Cost convention: unchanged inherited 20 bps portfolio cost

## Development evidence on the refreshed provider

| Metric | Baseline |
|---|---:|
| Compounded strategy return | 58.91% |
| Compounded CSI 300 return | 40.29% |
| Compounded relative excess | 13.27% |
| Mean ICIR | 0.1190 |
| Mean Rank IC | 0.0042 |
| Mean Top-Bottom spread | 0.85% |
| Positive excess windows | 3/4 |
| Worst drawdown | -19.10% |

No alternative factor group or regularization setting produced a higher ranking-aligned selection score while satisfying the pre-registered eligibility requirements.

## Frozen 2026H1 baseline evidence

| Metric | Value |
|---|---:|
| Total return | 53.11% |
| CSI 300 return | 4.27% |
| Simple excess | 48.84% |
| ICIR | 0.8883 |
| Rank IC | 0.1177 |
| Top-Bottom spread | 4.75% |
| Maximum drawdown | -12.00% |
| Turnover units | 6.17 |

The 2026H1 window strongly supports the score orientation and ranking mechanism, but it does not validate a new model because the selected configuration is unchanged from the baseline.

## Reproducibility warning

The same baseline configuration reported 20.1818% compounded relative excess in PR #289 but 13.2736% on the refreshed provider used here. The benchmark return is unchanged, while candidate returns differ across the four historical windows.

This is not XGBoost seed drift: the implementation fixes `seed=42`. The provider identity changed from:

- PR #289: `83f5251f77851e8c4766f086db71a7ee456a24ee7c1938f971228f04cf7779f2`
- PR #344: `bf5fa1373a0b5ebfedcd90c2cf3c4748300efd2b25da0adfbfb1daab8c6405d8`

The calendar extended from 2026-06-18 to 2026-07-31 and all 131 source CSV snapshot hashes changed. Before further CN model search, the pipeline must distinguish legitimate appended observations from historical-bar or adjustment revisions and quantify their effect on model selection.

## Interpretation

The current evidence says:

1. the original CN XGBoost baseline remains the best tested configuration;
2. the broader OHLCV factor search does not justify replacement;
3. 2026H1 ranking evidence is strong;
4. historical economic results are materially sensitive to provider snapshot identity;
5. further optimization should pause until provider-drift attribution and repeated-seed/data-snapshot stability are documented.

## Next gate

Proceed with the existing baseline only after:

- comparing overlapping historical bars and adjustment factors across provider identities;
- rerunning the baseline on at least two immutable provider snapshots;
- confirming Top-15 overlap and contribution stability;
- separating data-revision sensitivity from model instability;
- retaining the 2026H1 evidence as already consumed challenge data.
