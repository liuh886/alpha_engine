# CN Feature-Quality Validation

## Purpose

#90 proved that CN data can be evaluated after auto train-start alignment, but the US-derived frozen ranker/blend did not transfer:

- best CN row remained below useful strength;
- fixed US-style blend had weak ICIR and poor drawdown;
- decision status was `no_stable_candidate`.

This step tests CN-specific feature/factor quality before any further blend-weight tuning.

## Scope

This is still research-only:

- no frontend;
- no broker;
- no live trading;
- no order management;
- no execution;
- no broad parameter search.

## Candidate set

The runner evaluates a deliberately small grid:

- 4 CN feature groups;
- 2 conservative LightGBM LambdaRank calibrations;
- 4 simple factor baselines for orientation diagnostics.

Feature groups focus on:

- short-horizon reversal;
- mean reversion;
- volatility;
- price-volume pressure;
- liquidity/volume shocks.

## Runner

```bash
uv run python scripts/run_cn_feature_quality_validation.py \
  --alignment-mode auto \
  --first-test-year 2024 \
  --last-test-year 2026
```

Expected outputs:

```text
artifacts/evidence/cn_feature_quality/readiness.json
artifacts/evidence/cn_feature_quality/candidate_manifest.json
artifacts/evidence/cn_feature_quality/walk_forward_stability.json
artifacts/evidence/cn_feature_quality/model_decision_pack.json
artifacts/evidence/cn_feature_quality/model_decision_pack.md
```

If readiness or aligned windows fail, the runner writes:

```text
artifacts/evidence/cn_feature_quality/cn_feature_quality_skipped.json
```

## Decision rule

CN is not considered improved merely because the runner completes.  It must produce better rolling evidence than #90 CN baseline:

- highest-ICIR row in #90: mean ICIR about 0.096;
- fixed blend in #90: mean ICIR about 0.048 and drawdown about -31.4%;
- #90 decision: `no_stable_candidate`.

Useful improvement means at least:

- a stable research candidate appears; or
- mean ICIR rises meaningfully above 0.10 with drawdown controlled; or
- factor direction diagnostics clearly identify CN-specific signal direction for the next iteration.

Trade readiness still requires all gates:

```text
mean ICIR >= 0.30
worst drawdown >= -0.15
ready ratio >= 0.75
```

## Next step after evidence

If this produces no stable candidate, stop model/blend tuning and inspect CN label quality, universe construction, sector/state splits, and factor availability.  If it produces a stronger research candidate, only then consider a CN-specific blend or robustness validation PR.
