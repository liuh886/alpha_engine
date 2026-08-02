# v4.2 TQQQ precursor path-efficiency result

**Evidence date:** 2026-08-02  
**QQQ-proxy sample:** 2020-06-01 through 2026-07-30  
**Precursor events:** 15  
**Status:** research-only; not trade-ready

## Executive decision

1. The dominant failure mechanism is **underlying QQQ path and entry timing**, not TQQQ tracking or compounding drag.
2. Across the nine failed events, 97.96% of attributed negative components come from the directional leverage component; only 2.04% comes from negative TQQQ tracking/compounding residuals.
3. Clear false recoveries lose immediately and materially. Their median first-session QQQ return is -3.31%, and their median five-session QQQ adverse excursion is -3.93%.
4. The six events that later reach formal state 2 but still lose from 50% TQQQ are milder but economically distinct: median event QQQ return -0.40%, median five-session QQQ return -0.27%, and median time to formal state 2 of eight sessions.
5. Successful events show positive QQQ follow-through from the first session, shallower paths and lower five-session realized volatility.
6. The mechanism is sufficiently stable for prospective path recording, but not for a new signal rule. The late segment still contains three successes and no failures.

**Decision:** `monitor_path_mechanism_prospectively_without_new_rule`.

## 1. Attribution identity

For each frozen precursor event, the raw economic effect of replacing 25% QQQ with 25% TQQQ is decomposed as:

```text
25% × (TQQQ return − QQQ return)
=
25% × (daily-3x QQQ counterfactual − QQQ return)
+
25% × (TQQQ return − daily-3x QQQ counterfactual)
```

The first term is the directional leverage component. The second is the TQQQ tracking and compounding component. The daily-3x QQQ path is an attribution device and not a tradable synthetic-security claim.

The event-level decomposition reconciles exactly before the official strategy-cost and portfolio-compounding difference.

## 2. Aggregate loss attribution

Across the nine failed events:

| Component | Attributed negative component |
|---|---:|
| Underlying direction and leveraged entry timing | **7.61 percentage points** |
| TQQQ tracking and compounding residual | **0.16 percentage points** |
| Directional share | **97.96%** |

TQQQ residuals are measurable, but they are too small to explain the failure of the 50% precursor. Replacing TQQQ with a mechanically perfect daily-3x QQQ instrument would not solve the main problem.

## 3. Three path types

### Successful recovery — 6 events

Median outcomes:

- strategy marginal 50%-versus-25% return: **+0.38%**;
- event QQQ return: **+0.94%**;
- event TQQQ return: **+2.68%**;
- directional leverage component: **+0.47%**;
- tracking/compounding component: **-0.03%**;
- first-session QQQ return: **+0.51%**;
- five-session QQQ return: **+1.83%**;
- five-session QQQ maximum adverse excursion: **+0.51%**;
- five-session realized QQQ volatility: **13.85% annualized**;
- five-session QQQ sign reversals: **2**.

The median successful path remains positive even at its five-session minimum. The extra leverage works because the underlying recovery follows through quickly.

### Failed but later reaches state 2 — 6 events

Median outcomes:

- strategy marginal return: **-0.30%**;
- event QQQ return: **-0.40%**;
- event TQQQ return: **-1.42%**;
- directional leverage component: **-0.24%**;
- tracking/compounding component: **-0.02%**;
- first-session QQQ return: **-0.18%**;
- five-session QQQ return: **-0.27%**;
- five-session QQQ maximum adverse excursion: **-1.18%**;
- five-session maximum favourable excursion: **+0.40%**;
- five-session realized QQQ volatility: **19.89% annualized**;
- median time to formal state 2: **8 sessions**.

These events are not primarily wrong-direction calls. The market eventually reaches formal state 2, but the precursor window occurs during a low-return, unstable interval. The extra 25% TQQQ pays for several days of uncertainty before formal confirmation.

### Failed and reverts before state 2 — 3 events

Median outcomes:

- strategy marginal return: **-1.78%**;
- event QQQ return: **-3.31%**;
- event TQQQ return: **-9.87%**;
- directional leverage component: **-1.65%**;
- tracking/compounding component: **+0.01%**;
- first-session QQQ return: **-3.31%**;
- five-session QQQ return: **-2.45%**;
- five-session QQQ maximum adverse excursion: **-3.93%**;
- five-session maximum favourable excursion: **-2.45%**;
- five-session realized QQQ volatility: **23.85% annualized**;
- median time to state-0 reversion: **3 sessions**.

These are genuine false recoveries. Losses are immediate, directional and too large to attribute to leverage-product decay.

## 4. Intraday and overnight paths

Five-session median log-return contributions show different structures:

| Path type | QQQ intraday | QQQ overnight |
|---|---:|---:|
| Successful | **+1.17%** | **+0.65%** |
| Later reaches state 2 but loses | **-0.52%** | +0.28% |
| Reverts before state 2 | **-1.68%** | **-2.03%** |

The milder failures are mainly weak during regular-session trading while overnight performance is slightly positive. Clear false recoveries are negative in both components. This is explanatory only; it does not authorize an intraday execution rule.

## 5. Stable path mechanisms

Eleven post-execution features preserve their successful-versus-failed direction in the full and early samples and pass the predeclared leave-one-event-out standard. The strongest include:

- event directional leverage component;
- five-session QQQ maximum favourable excursion;
- five-session QQQ return;
- five-session TQQQ return;
- first- and third-session QQQ returns;
- five-session QQQ maximum adverse excursion;
- five-session QQQ intraday return;
- five-session sign reversals;
- TQQQ residual versus daily-3x QQQ.

These variables diagnose the realized path. They are not admissible signal inputs because they become observable only after execution.

## 6. Research interpretation

The evidence rejects the hypothesis that historical failures were mainly caused by TQQQ tracking inefficiency or volatility decay. The core mechanism is simpler:

> The precursor sometimes increases leverage before QQQ has produced immediate positive follow-through. When the first few sessions are flat, negative or choppy, the extra TQQQ exposure loses even if the broader recovery later qualifies for formal state 2.

This reinforces two existing conclusions:

- unconditional 50% TQQQ pre-release should remain rejected;
- formal state 2 remains the only validated leverage gate.

It does not yet prove that a specific one-, three- or five-session confirmation rule would improve the strategy. Selecting such a delay from these same events would be retrospective threshold fitting.

## 7. Prospective evidence extension

For every future frozen precursor, record the following outcome fields in addition to the existing signal-close features:

- QQQ and TQQQ 1/2/3/5-session returns;
- five-session QQQ favourable and adverse excursion;
- five-session QQQ realized volatility and sign reversals;
- intraday and overnight return contributions;
- directional leverage component;
- TQQQ tracking/compounding component;
- time to formal state 2 or state-0 reversion.

A separately pre-registered timing hypothesis may be discussed only after the late/prospective sample contains at least one failed event and the same mechanism persists without selecting a delay or threshold from the expanded sample.

## 8. Governance decision

- retain v4.2 unchanged as the only actionable baseline and Telegram source;
- retain 25% and 50% precursors as frozen research comparators;
- reject TQQQ product inefficiency as the primary explanation;
- record path outcomes prospectively;
- do not introduce a delay, persistence rule, threshold or new weight;
- do not modify Telegram targets.

## 9. Evidence

- workflow: `QQQI v4.2 TQQQ Path Efficiency`;
- workflow run: `30744871452`;
- artifact ID: `8832544076`;
- artifact digest: `sha256:aa0217a44d4aee3c471dbb5e7f2b49c40bf5890d904ea1e12c0c854463d302ff`;
- notebook: `notebooks/26_qqqi_qqq_tqqq_v4_2_tqqq_path_efficiency.ipynb`.
