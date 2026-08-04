# CN130 extreme-tail and factor-family discovery experiment log

Date: 2026-08-05  
Issue: #523  
Draft PR: #524  
Parent evidence: #509 / PR #511  
Provider cutoff: 2026-08-03  
Status: completed locally on the immutable provider; independent Actions rerun required  
Boundary: `research_only=true`, `trade_ready=false`

## Research question

The parent experiment rejected the claim that the existing model can reliably rank the full CN130 cross-section. This follow-up asks two narrower questions without changing the pool:

1. Does useful information survive only in the extreme top tail or after sector-diversified portfolio conversion?
2. Do any predeclared technical factors or factor families provide stable, incremental cross-sectional information across 2024H1–2025H2?

The two stages are separated. Stage A uses frozen parent scores. Stage B screens factors by IC, stability and incremental information; portfolio return is not used to select factors.

## Immutable inputs

- Universe: `cn_selected_equities_v3`, 130 declared members, unchanged.
- Benchmark: CSI 300 / `000300`.
- Horizon: 10 A-share sessions.
- Execution delay: one session.
- Rebalance cadence: 10 sessions.
- Provider identity: `abae71f037571a9a847d4582e0bea9fabdd71796cac54a70aa7c6d07b668eeb0`.
- Universe SHA256: `4ce5b95e60d38a13e4852fb6f7a3a6437b55d6da0fb317ad553d114e85158529`.
- Classification SHA256: `d1ef3bd06c0953c7e78fa0ba99c372da714ddce67203909d195d73e9eec61d15`.
- Selection windows: 2024H1, 2024H2, 2025H1, 2025H2.
- Reporting only: 2026H1 and 2026H2_PARTIAL.

## Stage A execution

Frozen score ledgers were rebuilt for four score sources:

- R0 current CN OHLCV;
- R2 industry-relative target with current CN OHLCV;
- R2 industry-relative target with momentum/reversal features;
- R4 two-stage hierarchical ranking with momentum/reversal features.

Each source was converted into:

- global Top3 / Top5 / Top8 / Top10 / Top15;
- global Top5 with sector cap 1 or 2;
- 3 sectors × Top1;
- 4 sectors × Top1;
- 5 sectors × Top1;
- 3 sectors × Top2.

Sector score is the mean of the top three security score percentiles in each level-1 sector. All portfolios are equal weight. Costs are tested at 10, 20 and 40 bps.

The 20 bps support gate requires:

- at least three of four positive excess windows;
- positive aggregate relative excess at both 20 and 40 bps;
- maximum absolute name contribution share no greater than 35%;
- maximum absolute sector contribution share no greater than 55%;
- positive leave-one-top-name and leave-one-top-sector relative excess.

A score source is called tail-supported only when at least two neighboring global tail variants or two sector-diversified variants pass.

## Stage A findings

### Smaller is not monotonically better

For R0 current OHLCV:

- Top3: **-20.53%** compounded relative excess; only 1/4 positive windows.
- Top5: **+15.62%**, but leave-one-sector excess is **-4.76%**; gate fails.
- Top8: **+52.09%**, 3/4 positive windows, maximum drawdown **-19.17%**; gate passes.
- Top10: **+40.19%**, 4/4 positive windows; gate passes.
- Top15: **+32.61%**, 4/4 positive windows; gate passes.

The useful tail is therefore not “the smaller the better.” The evidence points to a practical breadth around 4–10 names, not Top3 concentration.

### Sector-diversified conversion is the strongest stable architecture

R0 `sector_4x1` is the most stable architecture observed:

- 20 bps compounded relative excess: **+67.34%**;
- 40 bps compounded relative excess: **+53.59%**;
- positive windows: **4/4**;
- maximum drawdown: **-18.38%**;
- Precision@K: **50.5%**;
- maximum absolute name contribution share: **7.9%**;
- maximum absolute sector contribution share: **35.9%**;
- leave-one-top-name relative excess: **+52.59%**;
- leave-one-top-sector relative excess: **+24.35%**.

Window relative excesses are positive in every selection window:

- 2024H1: **+15.85%**;
- 2024H2: **+18.66%**;
- 2025H1: **+7.30%**;
- 2025H2: **+13.45%**.

Reporting-only windows remain positive:

- 2026H1: **+20.03%**;
- 2026H2_PARTIAL: **+0.80%**.

Neighboring R0 sector variants also pass (`3x1`, `5x1`, `3x2`), so the result is not isolated to one exact sector count.

### High-return cells remain state dependent

R2 momentum/reversal with global Top5 and sector cap 2 produces the highest aggregate relative excess, **+106.80%**, but its path is less stable:

- 2024H1: **-12.45%**;
- 2024H2: **+0.10%**;
- 2025H1: **+61.02%**;
- 2025H2: **+46.54%**;
- 2026H2_PARTIAL: **-11.35%**.

This cell is retained as evidence of state dependence, not selected as the primary robust architecture.

R4 momentum/reversal global Top5 has **+60.23%** relative excess and passes the gate, but remains negative in 2024H1 (**-7.02%**). It may be useful as a defensive tail transform, but it is not uniformly stable.

### Stage A decision

The parent conclusion remains intact: full-cross-section ranking is unsupported. However, the frozen scores contain useful information after extreme-tail and especially sector-diversified portfolio conversion.

Stage A result: **tail signal supported**.

The strongest bounded hypothesis for later validation is:

`R0 score -> select four sectors by top-three score breadth -> select Top1 security in each sector -> equal weight`

This is a portfolio architecture hypothesis only. It does not create or promote CN x1.1.

## Stage B execution

Thirty-seven predeclared trailing factors were evaluated in global and sector-relative forms. Families cover:

- trend and momentum;
- short reversal;
- breakout / price position;
- volume-price confirmation;
- risk and volatility quality;
- drawdown and recovery;
- liquidity;
- benchmark-residual strength.

Factor direction is fixed before returns are inspected. Each factor is evaluated by:

- half-year mean Rank IC and ICIR;
- positive-window count;
- worst-window Rank IC;
- mean Top-minus-Bottom spread;
- incremental Rank IC after removing the contemporaneous R0 score rank;
- leave-one-window mean stability.

Equal-weight family composites use only cross-sectional percentile ranks. No return-fitted factor weights are used.

## Stage B findings

No individual factor and no family composite passes all preregistered gates.

The nearest factor is sector-relative 20-day trend efficiency:

- Mean window Rank IC: **0.0123**;
- positive windows: **3/4**;
- mean incremental Rank IC: **0.0131**;
- mean spread: **0.35%**;
- minimum leave-one-window mean Rank IC: **0.0063**;
- worst window, 2024H1: **-0.0156**.

It satisfies four of six gates but fails the minimum Mean Rank IC and worst-window requirements.

Other apparently strong averages are generated by sign reversals:

- sector-relative intraday-range quality has Mean Rank IC **0.0162**, but changes from positive in 2024 to **-0.0732** in 2025H2 and has negative average spread;
- global distance-from-20-day-low / recovery has Mean Rank IC **0.0147** and incremental IC **0.0217**, but 2024H2 Rank IC is **-0.0720**;
- global 10-day momentum has incremental IC **0.0214**, but 2024H2 Rank IC is **-0.0354**.

The static technical factor library therefore does not provide a stable factor basis for a new model. The dominant empirical feature is factor-sign regime dependence.

### Stage B decision

- Supported individual factors: none.
- Supported factor-family composites: none.
- Non-redundant supported factors: none.
- Model rebuild authorization: **false**.

## Final decision

`tail_signal_supported_factor_rebuild_required`

Interpretation:

1. Existing scores should not be discarded entirely; their extreme tail is economically useful when portfolio construction controls sector duplication.
2. The current factor set is not strong enough to authorize a new ranker.
3. The next factor study should focus on predeclared market-state conditioning and genuinely new PIT information, rather than adding more static technical fields or tuning Top-K by return.

## Limitations and integrity notes

- The pool is static and selected with present knowledge, so survivorship bias remains.
- PIT market capitalization, shares and fundamentals are not available in the bound provider.
- 2026H1 was already consumed by earlier research; 2026H2 is incomplete. Both are reporting only.
- Eleven portfolio variants across four frozen score sources create multiple-comparison risk. No cell is promoted from this exploratory report.
- Full score ledgers, period holdings, contribution records, correlation matrix and the deterministic evidence manifest are retained in the Actions evidence artifact; compact summaries and the complete report are committed to the repository.
- The previous PR #511 evidence workflow failure was only a deterministic tie-order mismatch between equal-return R0/R1 report rows; its two full reruns and numerical decisions matched.
