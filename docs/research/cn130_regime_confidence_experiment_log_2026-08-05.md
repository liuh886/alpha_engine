# CN130 regime-confidence experiment log

Date: 2026-08-05  
Issue: #531  
Draft PR: #532  
Parent evidence: #523 / PR #524  
Provider cutoff: 2026-08-03  
Boundary: `research_only=true`, `trade_ready=false`

## Research question

The parent experiment established that the existing score is useful only after bounded tail conversion, with `R0 -> four sectors -> Top1 per sector` the most stable tested architecture. It also found that static technical factors reverse sign across windows.

This follow-up tests two narrower hypotheses without changing CN130:

1. Can predeclared confidence or risk-off cash rules improve the four-sector architecture?
2. Can market-state-specific factor signs calibrated only on 2022–2023 survive frozen validation in 2024–2025?

## Immutable inputs

- Universe: `cn_selected_equities_v3`, unchanged.
- Benchmark: CSI 300 / `000300`.
- Horizon: 10 A-share sessions; execution delay: one session; rebalance cadence: 10 sessions.
- Provider identity: `abae71f037571a9a847d4582e0bea9fabdd71796cac54a70aa7c6d07b668eeb0`.
- Calibration: 2022-01-01 through 2023-12-31.
- Validation: 2024H1, 2024H2, 2025H1, 2025H2.
- Reporting only: 2026H1 and 2026H2_PARTIAL.

## Stage A — confidence-gated sector exposure

The frozen R0 `sector_4x1` score was evaluated under six predeclared variants:

- always invested;
- require fourth selected sector score percentile >= 0.80;
- require Top4 sector mean minus sector median >= 0.10;
- require both fixed thresholds;
- cut risk-off gross exposure to 50%;
- cut risk-off gross exposure to zero.

The fixed thresholds are economic definitions, not return-optimized cutoffs. Costs were evaluated at 10, 20 and 40 bps. The support gate required positive robustness after removing the strongest name and sector, at least three positive half-year windows, positive 40 bps excess, mean exposure >=45%, and either at least a two-point drawdown improvement or at least five points of additional relative excess without sacrificing more than five points of baseline excess.

### Findings

The always-invested baseline remains strongest:

- 20 bps compounded relative excess: **+67.34%**;
- maximum drawdown: **-18.38%**;
- positive windows: **4/4**;
- leave-one-name excess: **+52.59%**;
- leave-one-sector excess: **+24.35%**;
- 40 bps excess: **+53.59%**.

No confidence or cash variant passed the incremental support gate.

The closest risk trade-off is `risk_off_half_cash`:

- relative excess falls to **+53.02%**;
- maximum drawdown improves to **-15.31%**;
- all four windows remain positive;
- average exposure is **88.0%**.

This is a real drawdown improvement, but the 14.31 percentage-point loss of relative excess is too large under the predeclared gate. Full risk-off cash improves maximum drawdown further to **-13.25%**, but relative excess drops to **+38.64%** and only 3/4 windows remain positive.

The score-strength gates are worse. The fourth-sector threshold reduces excess to **+55.95%** without improving drawdown. The gap threshold and combined threshold hold cash too frequently and reduce excess to **+36.76%** and **+27.77%** respectively.

Stage A decision: **confidence gate not supported**. The evidence favors keeping `sector_4x1` fully invested rather than adding a coarse cash veto.

## Stage B — regime-conditioned factors

Four benchmark-observable states were frozen:

- risk-on: close above MA120, positive 20-day return, 120-day drawdown above -8%;
- repair: 120-day drawdown at or below -8% and positive 20-day return;
- risk-off: close below MA120 and non-positive 20-day return;
- neutral: otherwise.

Twelve representative factors were selected before validation. Both global and sector-relative versions were evaluated. Within each state, calibration required at least 40 dates and absolute mean Rank IC >=0.01. At most one factor per family and five factors per state were retained, with pairwise rank-correlation capped at 0.80. Signs and equal weights were frozen from 2022–2023.

### Findings

The state-conditioned composite fails validation:

- Mean window Rank IC: **-0.0027**;
- positive windows: **2/4**;
- worst window Rank IC: **-0.0835**;
- mean incremental Rank IC versus R0: **-0.0117**;
- mean Top-minus-Bottom spread: **-0.40%**.

Half-year Rank IC:

- 2024H1: **-0.0835**;
- 2024H2: **+0.0693**;
- 2025H1: **+0.0772**;
- 2025H2: **-0.0737**.

The key failure is not insufficient calibration IC. Several state-factor pairs look very strong in 2022–2023, but their signs do not persist. For example, calibration assigns a negative sign to risk-on 20-day momentum and a positive sign to repair trend efficiency; the combined rule still reverses in both 2024H1 and 2025H2.

State-level validation also fails to isolate a reliable regime:

- risk-on Mean Rank IC: **+0.0056**;
- risk-off: **+0.0117**;
- neutral: **+0.0011**;
- repair: **-0.1154**.

Stage B decision: **regime model not supported**.

## Final decision

`confidence_gate_not_supported_regime_model_not_supported`

Interpretation:

1. The sector-diversified tail architecture remains useful, but coarse signal-strength and benchmark-state cash rules reduce its economic value.
2. Simple MA/drawdown market states do not stabilize technical-factor signs out of sample.
3. The next research step should not tune cash thresholds or add more technical states. It should focus on genuinely new information: PIT fundamentals, market-cap/size controls, corporate actions, earnings revisions or event features.
4. No CN x1.1 candidate is created and no model is promoted.

## Engineering and integrity notes

- A first implementation incorrectly selected the first row within a chosen sector rather than sorting by score; focused tests exposed and fixed this before evidence publication. The corrected baseline exactly reproduces the parent `sector_4x1` result of +67.34% relative excess.
- The first factor implementation retained all 37 prior factors and caused avoidable memory pressure. The experiment was narrowed to 12 predeclared representatives because the research question is sign persistence, not field-count expansion.
- Two local complete runs produced byte-identical committed outputs before publication.
- Static-pool survivorship bias remains. PIT fundamentals and market capitalization are still unavailable in the bound provider.
