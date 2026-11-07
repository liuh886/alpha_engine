# E4 US73 · 288-task research review and E5 handoff (2026-11-07)

**Research decision: EXECUTION_VERIFIED / SIGNAL_PROVISIONAL / TRADE_PROMOTION_BLOCKED.** The private owner-operated E4 Colab run has finished 288/288. Eight retrospective, survivor-biased validation folds cannot establish future PIT or capacity. **Do not execute additional `full` reruns, resume v6 Checkpoints, choose a live model, or treat the planned next 744 tasks as already executable.**

## 1. Evidence inspected and independently reconciled

- Private E4 checkpoint folder: `AlphaEngine/03_Data/Research_Exchange_P2/incoming_unreviewed/e4-us73-long-history-20261107`. Owner full report `e4-us73-full-20261107T072615189079Z-comparison.json`; final immutable ZIP `e4-us73-20261107T072614258127Z-ea0e7ccd.zip`; pointer `e4-us73-tip.json`.
- ZIP **SHA256 `f689d5494dcec4022218acadc94768e3e669ed308dadc331d660ba60091551d4`**, index **SHA256 `c8c6a4446f4eacb3adb3a7e03a7077ea9febb0102651c3c0339fd10f9dc11dc4`**, frozen plan SHA256 `5146093d121b2fc2fa291450dea3ef7b0a2cf7d00ab26dc44dec8d771eddb2c5`. All matched the separately read Drive pointer.
- ZIP CRC `PASS`; exactly **290 ZIP members**: `plan.json`, `index.json`, **288 different `records/<task>.json`**. Recomputed SHA256 of **all 288** and verified no missing or duplicate planned task IDs; 288 `ready`, all `research_only=true / trade_ready=false / pit_certified=false`.
- Recalculated every config's fold-median cumulative return, paired same-fold 20-day momentum delta, win counts, worst drawdown and daily-trace compound net/QQQ returns and turnover; **all 36 published configuration rows reconciled** within documented decimal rounding.
- Real measured sum of 288 **per-task executor timers** = **1,035.7258 seconds = 17.26 minutes**, median per-task **2.23795 seconds**. Does *not* equal end-to-end Colab wall time or Compute Units; runner does not log complete initialization/Drive time. Source/Runner: v6 history archive `b4745e46...`, frozen native Git `0c8152496e...`, E4 driver SHA `ff44d808...`. Note: independent verifier did not reproduce model fitting on a separate machine; integrity checks verify stored receipts, not market-vintage PIT.

## 2. Financial evidence (fold-aligned, cumulative excess relative to QQQ, not annualized)

| Configuration | Median excess vs QQQ | Median **paired** improvement vs 20-day momentum | Positive folds / 8 | Worst intra-fold drawdown |
| --- | ---: | ---: | ---: | ---: |
| **XGB p03** | **+35.47 pp** | **+19.62 pp** | **6** | **-45.82%** |
| 60-day momentum | +15.44 pp | +13.82 pp | 5 | -38.01% |
| XGB p00 | +28.73 pp | +11.27 pp | 5 | -48.90% |
| 120-day momentum | +37.48 pp | +9.89 pp | 5 | -48.51% |
| XGB p11 | +29.68 pp | +9.42 pp | 6 | -51.56% |
| LightGBM p05 | +24.98 pp | +8.82 pp | 5 | -43.41% |
| 20-day momentum | +10.41 pp | 0.00 pp | ref | -41.58% |

*Important:* values called `net_excess_return` are **period cumulative net portfolio return minus the same period cumulative QQQ return** in percentage points, not annualized alpha or statistical significance. Same-fold pairing, never subtraction of independent medians. Source plan uses **Top 5**, daily rebalance, cost=3 bps + slippage=5 bps per turnover, retrospective static US73; no genuine PIT roster.

**XGB p03's paired differences vs 20-day momentum** for 2023H1, 2023H2, 2024H1, 2024H2, 2025H1, 2025H2, 2026H1, 2026H2 respectively: **+43.50, +17.86, +21.37, +84.77, +17.79, -28.41, +67.71, -0.66 pp**.

**Crucial stronger benchmark:** XGB p03 versus the **60-day momentum** same-fold control has paired differences **+80.06, -6.60, +35.77, +51.14, +4.44, -42.71, +6.88, +5.70 pp**; **median +6.29 pp, 6/8 folds positive**. That is a much more modest model-complexity premium after recognizing 60-day momentum's strength. This is retrospective on the same eight folds and cannot be a new unseen test.

**Regime flip:** 2026H1 XGB p03 absolute net return **+233.50%** (QQQ **+20.16%**, excess **+213.34 pp**); 2026H2 (ending **2026-10-30**) absolute net **-32.30%** (QQQ **-6.14%**, excess **-26.17 pp**). Distinct market-state risk and selection effects may dominate headline medians. In 2025H1 p03 worst within-fold drawdown was -45.82%; model has not established acceptable downside control. These return magnitudes warrant source/causality/exposure validation, not extrapolation.

**Concentration:** Across 8 fold's `top5_score_signals_not_executed_trades`, five most repeated tickers represent **about 45% of ~4,905 top-5 signal slots**; p03's single top ticker appears in **654 of ~981 rebalance dates**. These are **signal memberships, not verified executed holdings, transaction sizes, capacity, or P&L attribution**. The highest concentration was ~56% of signal slots in 2026H2. Persist actual portfolio state before making constituent profit-contribution claims.

**Rank IC mismatch:** p03 mean of eight recorded `mean_rank_ic` values is ~**0.00413**. E4 native tree training target is **5-session future cross-sectional rank**, but current reported IC uses **next-session** return rank. This difference in horizons means existing IC alone cannot refute/confirm the intended 5-day signal; record both target-horizon 5d rank IC (using only fully matured OOS labels) and tradable next-session IC with consistent as-of timing. Near-zero next-session IC alongside huge Top5 P&L is a substantial financial validity question.

**Search bias:** 36 configurations share the same 8 retrospective folds, and original v6 knowledge influenced the v7 grid. Six positive folds out of eight for the selected winner are descriptive, not a multiple-comparison-adjusted significance test. Since user has already observed full 2023–2026 outcomes, **do not label any of these periods “independently untouched.”**

## 3. E5 implementation priorities — increase scientific validity before increasing workload

| Priority | Functional slice | Concrete output and acceptance |
| --- | --- | --- |
| **P0 / E5-01 Portfolio ledger + risk attribution** | Build a **new evaluator revision**, leaving E4/v6 hashes frozen. Replay **at least p03, 60-day momentum, 120-day momentum, LGB p05** with daily weights drift, actual target/rebalance trades, turnover, cash, cost drag, holdings and as-of signals. Record gross→net→QQQ and exposure attribution per asset per day, liquidity capacity proxies and risk budgets. | independently reproduce E4 daily net/turnover to rounding under E4's exact assumptions; prove aggregate P&L = ledger sum; report top 5 contribution shares, max single-asset exposure, exposure correlation with market/QMI vol, worst monthly/weekly drawdown |
| **P0 / E5-02 Baseline and cost fairness** | Compare same 8 folds and same universe against **QQQ, 20d, 60d, 120d momentum, equal-weight, optional low-vol**. Replay each shortlist's **0/8/25/50 bps** friction-per-turnover *without refit only if fit/score identity proven*, Top 3/5/10, weekly vs daily rebalance only with a separate properly frozen execution contract. | paired same-fold advantage vs **best predeclared strong baseline**, turnover-adjusted incremental return, cost break-even in bps; no leakage or unrealistic financing/borrow assertions |
| **P0 / E5-03 Data and chronological causality audit** | Validate historical adjusted price/volume semantics, survivorship of static US73, delisting, corporate action/restatement availability, end-of-day vs next-day execution, five-session label purge/embargo and source rights. Introduce a **date-stamped eligible-universe contract**, no silent dropna. | independent source evidence for historical constituents, observed at each decision time; 2023–2026 stays `RETROSPECTIVE_SURVIVOR_BIASED` until actual PIT evidence; no fake US Alpha158 or VWAP |
| **P1 / E5-04 Model diagnostics + regimes** | Repeat on **shortlist only** with matched 5d/1d Rank IC, regime segmentation using only past market information (QQQ trend/realized vol), persistent candidates and risk constraints. | explain why extreme 2026H1 returns / 2026H2 reversal occur, confirm positive advantage not concentrated in one fold or handful of names |
| **P1 / E5-05 New genuinely forward OOS** | Freeze model/hyperparameters/rebalancing before observing fresh future data. Store independent owner-registered no-prior-consumption forward period after 2026-11-07 and paper-score it without selection access. | new data period and source snapshot hash, daily authenticated forward ledger; only then assess promotion with multiple-comparison-aware methodology |
| **P2 / E5-06 Next campaigns** | Build **US-D date-varying universe** and **CN130 native market simulator** separately, after P0 gates. Adaptive HPO and stochastic seeds only after scientific baseline superiority. | 216 US-D and 288 CN gated tasks, not launched; 192 HPO and 48 new seed tasks remain gated. Do not expand solely because Colab has spare Compute Units |

The near-term next run should **not be another 1,032 model fits**. First produce ledger & targeted cost replay for four shortlist strategies (subject to approved rights). This is a richer decision per unit than recycling the same 8 folds for more parameter mining.

## 4. Engineering and delivery

- Freeze E4 immutable private ZIP, pointer, and full report; **do not modify or rerun 288 historical jobs**. Capture their exact file IDs and hashes as research-release receipt.
- Existing PR #1380 has v6/R1 research executor controls and E4 campaign RFC; this document closes E4 run evidence, **but no new E5 code or replay has been executed by this report**. Implement E5 slices in fresh code/run identity; retain old E4 checkpoint and legacy v6 unaffected. E5 scope can be a new follow-on issue only after the existing stacked PR's boundaries are reviewed.
- Cloud resources: current US73 E4 used CPU native XGB/LGB with per-task wall timers summing ~17.26 min. This does **not** certify an effective 2/4 worker speedup; cost-per-effective-trial and end-to-end utilization still need measurement. CPU-first benchmark against serial same-code baseline before parallel default.
- Report status: **E4 EXECUTION_VERIFIED; RESEARCH SIGNAL HYPOTHESIS; NO LIVE TRADING**.
