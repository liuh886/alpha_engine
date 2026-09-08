# CN_27 V1.0 historical challenge evidence

## Decision

`historical_common_window_challenge_passed_no_fresh_holdout`

- `research_only=true`
- `trade_ready=false`
- fresh historical holdout: `false`
- automatic promotion: forbidden
- selected-pool readiness claimed: `false`

CN_27 V1.0 passed every frozen historical challenge gate against the accepted
BYD v1.3 formal trace on the exact 720-session common window from 2023-09-01
through 2026-08-24. The result is retrospective because all of this history had
already been observed before the contract was frozen.

## Model identity

- Model contract: `configs/research_paradigms/cn_27_v1_0.yaml`
- Candidate record: `configs/research_candidates/cn_27_v1_0.yaml`
- Strategy-specific pool: `configs/pools/cn_all_weather_alpha_rotation_v1.yaml`
- Candidate equities: 27
- Defensive executable sleeve: `515180.SH`
- Non-executable market benchmark: `000300.SH`
- Signal time: session close
- Execution time: next eligible session open
- SMA20 slope: three-session relative change
- Maximum positions: 5 at 15% target weight each
- Residual allocation: `515180.SH`

## Exact common-window comparison

| Metric | CN_27 V1.0 | BYD v1.3 | CN_27 result |
| --- | ---: | ---: | :---: |
| Total return | 35.97% | 32.35% | better |
| CAGR | 11.35% | 10.31% | better |
| Annual volatility | 22.58% | 33.10% | better |
| Daily log-excess Sharpe | 0.3951 | 0.2400 | better |
| Maximum drawdown | -22.22% | -36.88% | better |
| Calmar | 0.5110 | 0.2795 | better |
| Annual one-way turnover | 17.49x | 1.00x | worse |

Net results include each model's frozen transaction-cost implementation. CN_27
paid 5.07% in summed daily portfolio cost deductions during the common window;
BYD v1.3 paid 1.14% plus 0.04% financing cost. The cost sums are path-level
deductions and must not be interpreted as simple terminal-return differences.

## Full CN_27 evaluation window

- Window: 2023-09-01 through 2026-09-04, 729 sessions
- Total return: 34.15%
- CAGR: 10.69%
- Annual volatility: 22.54%
- Daily log-excess Sharpe: 0.3688
- Maximum drawdown: -22.22%
- Calmar: 0.4811
- Annual one-way turnover: 17.70x
- Average stock allocation: 26.69%
- Average defensive ETF allocation: 73.31%

The corrected three-session relative slope changed some entrant ordering but did
not change the realized membership, trades, or full-window performance relative
to the first real bottom-up audit implementation.

## Bound evidence

- CN_27 evidence manifest identity:
  `3f8565733bc6c73ad156de52780b791ad4ad467848b2789d570159c9d1b11890`
- CN_27 implementation SHA-256:
  `61ec6415a6e7dc9da0a812bcf34c77ebb8c53f92c304dd1218844cf05a500962`
- Source OHLCV SHA-256:
  `1e7713e8c2387ac70d4ff9346fc0f553453318dd2fd0fd8ee76e25c52fb26e35`
- BYD v1.3 formal manifest SHA-256:
  `306d1d0ea4bb95a2e81ab44bcf6fc1bb990bf326828d3548b2e61ded0477deeb`
- BYD v1.3 performance SHA-256:
  `fe7649e0bbd658a496308c842c2815972a162323eb79e7da3a63c6aa11d7ab64`
- Local evidence directory: `artifacts/evidence/cn_27_v1_0`

The local evidence bundle contains the full factor history, daily positions,
trades, round trips, coverage, paired BYD comparison trace, metrics, decision,
report, and output hashes.

## Reproduction

```powershell
python scripts/run_cn_27_v1_0.py `
  --prices-csv artifacts/evidence/cn_all_weather_alpha_rotation_v1/source_ohlcv.csv
```

Omit `--prices-csv` to perform a new provider refresh. A refreshed data artifact
is a new source identity and must not be presented as reproducing the hash-bound
run above unless its SHA-256 is identical.

## Interpretation and next gate

CN_27 V1.0 achieved historical risk-return dominance over BYD v1.3 on the exact
common window, but did not beat its turnover efficiency. No parameter, factor,
cost, or membership change may now be made on this same history and described as
fresh validation. Formal promotion requires prospective observations after the
2026-09-04 CN_27 cutoff under the unchanged contract.
