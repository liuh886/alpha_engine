# Multi-Market Readiness and CN 10D Validation

## Purpose

AlphaEngine should not remain a US-only research loop.  After the #86 stable-blend candidate and #87 model decision pack, the next validation step is multi-market readiness plus an independent CN 10D validation.

This document records the intended workflow.  It is not a trade recommendation and does not authorize live trading, broker integration, order management, or automated execution.

## Current US context

The current best US default-universe research candidate is:

```text
blend:ranker_momentum:momentum_volatility_volume:gain5_round100_leaves31_leaf10_lr0.05:ranker0.5_momentum0.5/signal_blend/original
```

Latest default-universe context:

| Metric | Value |
|---|---:|
| Mean ICIR | 0.255122 |
| Worst drawdown | -0.112241 |
| Ready ratio | 0.25 |
| Decision | stronger_research_candidate |
| Trade ready | false |

US expanded-universe robustness is still not validated because the local historical data did not cover the configured 2021-01-01 training start.

## CN validation principle

US evidence does not transfer automatically to CN.  The CN market must be validated independently:

- CN symbols must be normalized explicitly.
- Six-digit CN codes must preserve leading zeroes.
- Qlib symbol format must be selected from formats that actually exist locally.
- CN readiness must pass before model evidence is generated.
- If CN readiness fails, the runner writes a skip report rather than ICIR or drawdown conclusions.

## Added workflow

### 1. Multi-market readiness

Run:

```bash
uv run python scripts/check_multi_market_data_readiness.py
```

Expected outputs:

```text
artifacts/evidence/multi_market_readiness/readiness_report.json
artifacts/evidence/multi_market_readiness/readiness_report.md
```

The report covers at least:

- `us`
- `cn`

Each market records requested symbols, normalized symbols, retained symbols, coverage ratio, date coverage, skipped status, and skip reason.

### 2. CN 10D validation

Run only after CN readiness passes:

```bash
uv run python scripts/run_cn_10d_validation.py --first-test-year 2024 --last-test-year 2026
```

Expected outputs when CN readiness passes:

```text
artifacts/evidence/cn_10d_validation/walk_forward_stability.json
artifacts/evidence/cn_10d_validation/model_decision_pack.json
artifacts/evidence/cn_10d_validation/model_decision_pack.md
```

If CN readiness fails, the runner writes:

```text
artifacts/evidence/cn_10d_validation/cn_validation_skipped.json
```

## Fixed CN candidate set

The first CN validation uses a deliberately small fixed candidate set:

| Candidate | Purpose |
|---|---|
| `lgbm:daily_ranker:momentum_volatility_volume:gain5_round100_leaves31_leaf10_lr0.05` | frozen ranker from US research path |
| `blend:ranker_momentum:momentum_volatility_volume:gain5_round100_leaves31_leaf10_lr0.05:ranker0.5_momentum0.5` | frozen 50/50 ranker + inverted momentum blend |
| `factor:historical_momentum_10d` | momentum baseline; original/inverted orientation is still evaluated by the normal experiment API |

No new parameter search is included.

## Decision gates

Trade guidance still requires all of:

```text
mean ICIR >= 0.30
worst drawdown >= -0.15
ready ratio >= 0.75
```

CN can become a stronger research candidate if rolling evidence is cross-window stable and drawdown-aware, but it must not be described as trade-ready unless all gates pass.

## Next decisions

After running the local evidence:

- If CN readiness fails, fix CN provider / symbol mapping / history coverage first.
- If CN readiness passes but evidence is weak, move to CN-specific feature quality rather than blend-weight tuning.
- If CN produces a stronger research candidate, compare it independently with the US candidate; do not assume one market's orientation applies to the other.
