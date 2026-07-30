# Static-to-PIT Alpha Decomposition: Final Results

**Date:** 2026-07-30  
**Issue:** #187  
**Decision:** `stop_existing_ohlcv_ranker_family`

## Executive conclusion

The full frozen decomposition completed successfully on the two authoritative,
manifest-bound providers. The apparent static-universe alpha does not survive
window-start point-in-time Nasdaq-100 membership.

The loss of benchmark-relative performance is caused primarily by the **OOS
opportunity set / constituent-definition effect**, not by a meaningful
LightGBM-versus-XGBoost training difference. The two model families continue to
rank common names similarly, but they select materially different Top-15
portfolios once the eligible universe is corrected.

The existing OHLCV ranker family is therefore stopped. It must not receive more
tree-parameter, Top-K, direction, blend-weight, cost, threshold, or observed-
window searches.

## Hard acceptance checks

The local authoritative run satisfied every required gate:

- `endpoint_reproduction=true`
- windows exactly `2024H1`, `2024H2`, `2025H1`, `2025H2`
- `decision=stop_existing_ohlcv_ranker_family`
- `missing_required_outputs=[]`
- `manifest_sha256_valid=true`
- `stable_research_candidate=false`
- `trade_ready=false`

The generated raw artifacts remain local under the ignored `artifacts/`
directory. This document is the version-controlled decision record; it does not
replace the machine-readable local evidence.

## Authoritative provider identities

| Role | Provider identity |
| --- | --- |
| Published static reference | `66129d0727beb8d7b014966651f8b72c119f99195e33553d9781c9954ef267d8` |
| Controlled repaired PIT provider | `6aa6c0c0351e7dc1f2f6e6495df053d57790bd90e289fe695a2d130774034407` |

The run used the exact locked provider pair. Provider-repair effects were kept
separate from membership effects.

## Four-cell decomposition

The controlled matrix held model, features, target, portfolio construction,
costs, embargo, benchmark, and test windows fixed.

| Cell | Training membership | OOS membership | Interpretation |
| --- | --- | --- | --- |
| S/S | Static curated | Static curated | Controlled static endpoint |
| S/P | Static curated | PIT NDX | OOS opportunity-set effect |
| P/S | PIT as-of | Static curated | Training and label effect |
| P/P | PIT as-of | PIT NDX | Authoritative PIT endpoint |

### Mean relative-return attribution

| Attribution item | LightGBM | XGBoost |
| --- | ---: | ---: |
| OOS opportunity-set effect | -19.31% | -18.94% |
| Training / label effect | -1.09% | -0.02% |
| Interaction residual | -1.75% | -6.52% |

The dominant direct effect is the OOS membership change. Training and label
changes explain little of the LightGBM result and essentially none of the
XGBoost result. XGBoost has a larger interaction residual, but this does not
alter the primary conclusion: the static eligible-stock set was the major
source of the apparent alpha.

## Selection and ranking diagnostics

| Diagnostic | LightGBM | XGBoost |
| --- | ---: | ---: |
| Static-vs-PIT Top-15 overlap | 32.9% | 33.1% |
| Common-name score correlation | approximately 0.77 | approximately 0.77 |
| Processed label-bin migration | 13.3% | 13.3% |

The models retain substantial ranking similarity on names common to both
universes, but only about one third of the final Top-15 selections overlap.
This distinguishes **ranking preservation** from **portfolio preservation**:
a model may score common names similarly while producing a different portfolio
when the eligible cross-section changes.

The 13.3% label-bin migration is real but secondary. It is not large enough to
explain the performance collapse by itself.

## Authoritative P/P results

| Metric | LightGBM | XGBoost |
| --- | ---: | ---: |
| Mean ICIR | 0.0966 | 0.1149 |
| Compounded relative return vs QQQ | -20.49% | -34.08% |
| Worst drawdown | -26.11% | -25.59% |
| Stable research candidate | false | false |
| Trade-ready | false | false |

Neither algorithm produces economically acceptable point-in-time evidence.
The modest model-family differences are immaterial relative to the common
membership-validity failure.

## Answers to Issue #187

### How much of the gap is caused by OOS opportunity-set selection?

Approximately 19 percentage points on average for both rankers. This is the
largest direct component of the static-to-PIT deterioration.

### How much is caused by changed training membership and labels?

Little: -1.09% for LightGBM and -0.02% for XGBoost. Training membership and
cross-sectional label changes are not the primary explanation.

### Did the model retain useful ranking information on the common intersection?

It retained moderate-to-strong common-name score correlation, approximately
0.77, but that information did not translate into a stable benchmark-relative
Top-15 portfolio under valid PIT eligibility.

### Is the LightGBM-versus-XGBoost choice the problem?

No. Both families fail the authoritative P/P test, and the direct OOS
opportunity-set effects are almost identical. Changing the tree implementation
would not address the validity failure.

### Is the existing OHLCV ranker family worth further tuning?

No. The approved decision is:

```text
stop_existing_ohlcv_ranker_family
```

A future challenge must introduce a genuinely new economic information source
and an untouched or independently reserved evidence plan. Favorable results
from S/P, P/S, common-intersection diagnostics, or another search over the
observed 2024H1--2025H2 windows cannot reopen this model family.

## Evidence locations

The authoritative machine-readable outputs were generated locally at:

```text
artifacts/evidence/static_to_pit_alpha_decomposition/
├── report.md
├── aggregate.json
├── decision.json
└── evidence_manifest.json
```

They are intentionally not tracked because the repository ignores generated
`artifacts/`. The provider identities, acceptance checks, headline attribution,
and final decision are preserved in this maintained research record.

## Governance consequence

This experiment demonstrates that Alpha Engine's research process must treat
universe validity as part of model identity, not as a secondary robustness
check. A strong static-universe backtest cannot be treated as candidate alpha
until it survives the applicable point-in-time membership contract.
