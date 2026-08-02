# v4.2 recovery-precursor failure taxonomy result

**Evidence date:** 2026-08-02  
**QQQ-proxy sample:** 2020-06-01 through 2026-07-30  
**Precursor events:** 15  
**Official cost:** 10 basis points per turnover unit  
**Status:** research-only; not trade-ready

## Executive decision

1. The 15-event taxonomy contains six successful and nine failed 50%-versus-25% TQQQ precursor events.
2. Only three failures reverted to state 0 before formal state 2. Six failures eventually reached state 2 but the additional 25% TQQQ still lost money relative to the 25% precursor.
3. The strongest descriptive separation is faster five-session VIX/VXN compression, a fresher state-1 decision, a lower VXN level and greater QQQ distance above the 20-session repair reference.
4. Eight pre-execution features pass the descriptive full-sample, early-sample and leave-one-event-out stability standard.
5. The post-2024 late segment contains three successes and zero failures. No separator can therefore be validated in both chronological segments.
6. Prospective feature recording is justified, but a new trading rule, threshold, classifier, target allocation or Telegram alert is not.

**Decision:** `monitor_features_prospectively_without_new_rule`.

## 1. Failure taxonomy

| Category | Events | Interpretation |
|---|---:|---|
| Successful recovery | 6 | 50% TQQQ outperformed 25% during the frozen precursor event |
| Failed, reverted before state 2 | 3 | The recovery was not durable enough to reach formal leverage before returning to state 0 |
| Failed, later reached state 2 | 6 | The broad recovery eventually qualified, but 50% TQQQ was introduced too early |

The six failures that later reached state 2 are important. They show that the problem is not only a binary false-recovery signal. In many cases the direction of recovery was ultimately correct, but the additional 25% TQQQ was exposed during an unstable interval before the formal state-2 transition.

The three reversion failures were more damaging:

- median 50%-versus-25% event return: **-1.78%**;
- mean event return: **-1.49%**.

The six failures that later reached state 2 were smaller but more frequent:

- median event return: **-0.30%**;
- mean event return: **-0.66%**.

## 2. Strongest descriptive features

| Feature at signal close | Successful median | Failed median | Full-sample LOO stability | Early-sample LOO stability |
|---|---:|---:|---:|---:|
| VIX five-session return | **-23.32%** | -9.90% | 100% | 100% |
| VXN five-session return | **-20.72%** | -6.03% | 100% | 100% |
| VXN close | **22.65** | 25.70 | 100% | 83.3% |
| State-1 decision age | **2 sessions** | 4 sessions | 100% | 100% |
| VXN one-session return | **-7.96%** | -3.78% | 100% | 91.7% |
| QQQ distance above 20-session MA | **+2.83%** | +0.92% | 100% | 100% |
| VIX close | **17.50** | 19.59 | 100% | 83.3% |
| VXN retreat from 20-session peak | **-24.44%** | -19.72% | 100% | 91.7% |

The same directions remain visible inside the early segment, which contains both three successful and nine failed events. This reduces—but does not eliminate—the risk that the full-sample result is merely a post-2024 calendar effect.

The four most interpretable signals are:

- **faster volatility compression:** successful recoveries followed much larger five-session VIX and VXN declines;
- **freshness:** successful events occurred earlier in the state-1 decision run;
- **stronger short repair:** QQQ stood further above its existing 20-session reference;
- **lower residual Nasdaq volatility:** successful events generally had a lower VXN level.

These are descriptive relationships. No cut-off was selected.

## 3. Features that did not provide stable separation

The following did not meet the complete descriptive standard:

- VIX and VXN normalization margins, whose directions changed between full and early samples;
- shock-memory age and remaining duration;
- distance to the 50- and 200-session references;
- signal-date QQQ drawdown;
- next-open QQQ or TQQQ gap;
- VIX one-session return;
- current position state at the signal close.

This means the existing precursor cannot be repaired simply by requiring a larger normalization margin or by waiting for a specific shock-memory age. The evidence does not support those claims.

## 4. Outcome-path observations

The event table records 1-, 5-, 10-, 20- and 40-session QQQ/TQQQ returns, maximum favourable and adverse excursion, and subsequent state transitions.

Two different failure modes are visible:

### Immediate or durable reversion

The three events that returned to state 0 before state 2 include the larger losses. These are the clearest false recoveries.

### Correct eventual direction, poor entry timing

Six events reached state 2 before returning to state 0 but still produced a negative 50%-versus-25% event return. The model eventually recognized the recovery correctly; the 50% precursor merely paid too much for being early.

This supports retaining formal state 2 as the leverage gate and rejecting unconditional 50% pre-release.

## 5. Chronological limitation

| Segment | Successful | Failed |
|---|---:|---:|
| Early: 2020-06-01 to 2024-02-07 | 3 | 9 |
| Late: 2024-02-08 to 2026-07-30 | 3 | 0 |

The early segment supports the direction of the main descriptive features. The late segment cannot test them because it contains no failed event.

Therefore, the evidence cannot distinguish between:

- a genuinely improved post-2024 recovery environment;
- a temporary favourable run;
- a structural separator that would remain valid during the next failed recovery.

A failed late/prospective event is required before any new rule can be considered.

## 6. Governance decision

Authorized:

- add the strongest features to non-actionable prospective event records;
- continue recording hypothetical 25% and 50% allocations;
- compare feature values when a future precursor succeeds or fails;
- retain the event taxonomy as a durable research artifact.

Not authorized:

- changing v4.2;
- promoting 25% or 50% TQQQ;
- choosing VIX/VXN cut-offs;
- adding a state-1 age threshold;
- fitting a classifier or composite score;
- changing Telegram targets;
- opening another retrospective weight search.

The five primary prospective fields are:

1. VIX five-session return;
2. VXN five-session return;
3. VXN close;
4. state-1 decision age;
5. VXN one-session return.

QQQ distance above the 20-session MA, VIX close and VXN retreat from peak remain secondary descriptive fields.

## 7. Next decision gate

A new pre-registered recovery hypothesis may be discussed only after the late/prospective evidence contains both:

- at least one failed recovery-precursor event; and
- multiple events sufficient to verify that the same feature directions persist without selecting thresholds from the expanded sample.

Until then, v4.2 remains the only actionable baseline, and the static QQQI/SGOV profile remains the drawdown-focused alternative.

## 8. Evidence

- workflow: `QQQI v4.2 Recovery Failure Taxonomy`;
- workflow run: `30740263682`;
- artifact ID: `8831040334`;
- artifact digest: `sha256:0e4d355e8e01cf71e66eb92622e77048627305e4d355ae2dd479389205252bfa`;
- notebook: `notebooks/25_qqqi_qqq_tqqq_v4_2_recovery_precursor_failure_taxonomy.ipynb`.
