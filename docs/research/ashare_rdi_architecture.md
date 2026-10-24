# A-share Risk Density Index (RDI) — architecture and research charter

**State (2026-10-24):** design prototype / uncalibrated, research-only.
**Repository:** Alpha Engine; not an active strategy. **Never** present prototype
scores as a validated prediction or place orders from this module.

## Objective and hypothesis

Test whether a **concentration of contemporaneously *known* adverse events**,
especially when the market is already in a persistent bearish regime, predicts
downside or weaker forward returns for A-shares over **7, 14 and 28 exchange
trading sessions**. These are hypotheses, not findings. An additional hypothesis
is that verified sector restructuring, exit and capacity reduction may foreshadow
risk clearing. Policy rescue rumors are **not** evidence of a durable bottom.

Market-level primary benchmark: governed CN **CSI300 / 000300.SH** from
`configs/pools/reference_instrument_registry_v1.yaml`, an **index**, not an ETF.
Sector-level instruments: *research candidate* sector ETFs only after identity,
taxonomy, track record, lifecycle, distribution-adjusted prices and liquidity
are confirmed. An index and a tradable tracking ETF must not be conflated.

## Layers and ownership

| Layer | Function | Owner or existing authority |
| --- | --- | --- |
| Source adapters | Holidays, filing windows, CNINFO disclosures, insider selling, restricted share unlocks, IPO/refinancing calendars, macro, sector distress, restructurings | Existing `src/data` source families and company event store; record source family and content hash |
| Canonical event claims | Event identity, story clustering, sector mapping, announcement/availability times, effective window, revisions, evidence stage | `RiskEvent` research projection of source-bound records; **not** a second source of truth |
| Feature extraction | Event concurrency, forward-known density, bearish regime, leader distress, genuine clearing, verified policy, favorable-news failure | `src/research/ashare_rdi`; candidates only until calibrated |
| Outcome labels | PIT-aligned forward returns and path downside on XSHG sessions | `outcomes.forward_outcomes`; never used in feature creation |
| Research evaluation | Frozen specs, purged walk-forward, baselines, sector transfer, failed results | Existing Alpha Engine research and evidence/run discipline |
| Publication | Only after independent validation and user authorization | Existing EvidenceBundle/promotion boundary; **no** new workflow, dashboard page or alert today |

No new provider database, strategy registry, active model, scheduler, CLI or
consumer is authorized by this PR. Keep `research_only=true`,
`trade_ready=false`.

## Factor catalogue — keep scores independently interpretable

- **E / Event risk density:** overlapping event windows for holiday pre-positioning,
  quarterly earnings calendar, insider selling, unlock *potential* (not equivalent
  to actual selling), IPO/refinancing cash demand, macro and external shocks.
  Exposure must distinguish events *known now* from events first learned later.
- **B / Persistent bear state:** trend, market breadth, drawdown duration,
  turnover and financing net reduction. This is a state conditioning feature,
  not independent causal news; overlapping proxies need deduplication.
- **S / Sector leader distress:** representative leaders' margin, cash flow,
  debt service, going-concern and real financing problems; corroborate
  company-specific weakness against peers before inferring sector impairment.
- **C / Verified clearing:** consolidation, creditors' accepted restructurings,
  completed exits, capacity actually retired, and verified improvement in
  utilization, spreads, balance sheets or inventory. Stage separately as
  announced/approved/executed/verified. No blanket offset across sectors.
  Restructuring can be unfavorable for original equity holders.
- **P / Policy confirmation:** keep rumors, announcements, executed flows and
  sustained market effects separate. Never assume a rescue bottom or use rumors
  as automatic negative risk points.
- **G / Good-news response asymmetry:** earnings surprises with weak/negative
  subsequent reactions versus adverse surprise reactions; must use surprise
  expectations and price bars available at that time, avoid conditioning on
  future labels or choosing thresholds on test data.

Do **not** freeze the earlier illustrative 55/25/20 blend or any threshold such
as 'four simultaneous risks means certain correction'. First estimate
independent contribution, horizon dependence, interaction terms, reliability
and out-of-sample calibration. Stronger candidate: separate probability of
negative return, expected forward downside and prospective regime state;
a display-only 0–100 index may be calibrated later. Do not interpret it as a
literal probability until probabilistic calibration succeeds.

## Event semantics and PIT safety

Keep event_id and real-world story_id separate. A syndicated article cannot
become ten 'events'. Revisions are separately identified and become eligible
only from their **actual** known time; never rewrite historic feature rows.
Preserve announced_at, available_at (publication and provider latency),
effective start/end, source identity/hash, scope (market or *specified* sector),
stage and revision chain. The `contracts.py` helper refuses naive timestamps,
filters to available_at <= decision cutoff, and counts each story once per day.
This is a **coverage-independent event-calendar skeleton**, not a scored index.

Market decisions are after a verified completed Shanghai trading session;
availability is compared with a timezone-aware cutoff and bar-availability
contract. Session alignment uses the existing XSHG calendar, **never weekdays
as a holiday proxy**. Scheduled future events disclosed before cutoff may be
used as features. Future *realizations* and future article revisions may not.
Historical news coverage gaps remain unknown, **never zero**. Explicitly flag
source families unavailable for a date, missing mapping and questionable
publication timestamps. Canonical filing fields should reuse the existing
CNINFO PIT event store and reference its underlying evidence ID rather than
duplicating financial facts.

## Outcome protocol: 7 / 14 / 28 sessions

Snapshot at end of completed session **t**. Label `h` uses **h distinct
subsequent exchange sessions**:
- **Nontraded CSI300 index:** close(t) to close(t+h), a *directional forecast*
  evaluation, **not** a tradable P&L.
- **Sector ETF:** if eligible and properly adjusted, next open(t+1) to
  close(t+h), including fees/slippage/spreads **only** in separately specified
  execution experiments. The prototype outcome helper is *gross*, not net.
- Report end-of-horizon return *and* worst intrahorizon excursion, conditional
  drawdown and downside hit rates. Distinguish intrahorizon low drawdown from
  close-to-close maximum drawdown.
- Exclude unresolved horizon tails; do not substitute h calendar days, partial
  windows, ETF prices before listing, or absent sessions. Sector instruments
  require valid price adjustments, survivorship checks and period coverage.

## Falsification-first backtest

1. **Freeze before analysis:** factor definitions, event timestamps, sector
   taxonomy, source eligibility, target population, 7/14/28 horizons, costs,
   sample intervals, benchmark, versions and feature lags.
2. **Baselines and ablation:** market drawdown/trend, realized volatility,
   breadth, financing alone, simple equal-count events, E+B alone, E+B+S,
   then C/P/G additions. Test incremental value, not only pretty charts.
3. **Blocked chronological development/validation/untouched test.** No random
   shuffling. Purge training rows whose **forward label interval intersects**
   test, with at least 28-session boundary protection for maximum horizon.
   Apply any embargo with correct time direction; calendar-block or episode
   bootstrap for correlated overlapping labels; multiple-testing correction.
4. **Targets and metrics:** sign, severe-return quantiles, path downside,
   ROC-AUC/PR-AUC where justified, Brier score and reliability curves for
   probabilities, rank IC, conditional downside probability and realized
   regime durations; compare economic utility after conservative costs if an
   explicit ETF decision policy is later authorized.
5. **Robustness:** multiple non-overlapping market regimes (including bull,
   structural bear and policy rescue periods), walk-forward recalibration using
   training information only, source lag perturbation, date sensitivity and
   alternate but predeclared sector taxonomies. Sector ETF results are never
   assumed transferable from CSI300 by default.
6. **Failure gates:** leakage, insufficient historical event coverage, incorrect
   ETF adjustment, stale prices, invented event history, too few distinct stress
   episodes, unstable split performance, inconclusive incremental utility =>
   status 'not validated'. Retain failures and null outcomes.

Treat **2026 July–October** as a motivating prospective evaluation case, not
a threshold-tuning target retroactively masquerading as out-of-sample.

## Deferred decisions (tracked, not silently assumed)

| Open question | First experiment / required evidence |
| --- | --- |
| 7/14/28 calendar days vs trading sessions | Initial default trading sessions, compare only in a separately frozen study |
| Event effect and decay | Compare fixed pre/post windows vs empirically estimated kernels on development sample |
| Correlated factors and '3+/4+ risks' | Report clusters and marginal contribution; calibrate against counterfactual baselines |
| How much sector S/C contributes to CSI300 | Test cap-weighted exposure using PIT sector mapping, separately from within-sector features |
| Sector ETF selection | Propose liquid historical instruments; confirm ticker, creation date, NAV adjustments, constituents and tracking error |
| Industry distress tagging | Documented thresholds, peer validation, duplicates and disclosed counterexamples |
| Clearing stage and policy influence | Compare announced vs executed vs independently verified; forbid rumor-based rescue discount |
| G surprise and good-news failure | PIT pre-announcement consensus, event-time adjusted response, control for market and sector returns |
| Composite scale/weights/thresholds | Freeze only after out-of-sample evaluation; preserve raw features |
| Availability of old events | Establish coverage era and reporting completeness; test missing-not-at-random risk |
| Predictive deployment | Separate predictive performance from action-policy economics and formal EvidenceBundle gate |

## Deliverables of this foundation PR

- Versioned, unactivated study configuration.
- Typed source-traceable PIT event contract + future-known exposure timeline.
- Forward outcome helper for index/ETF horizons (no data connector and no
  trades), and contract tests.
- This architecture charter and explicit hypotheses/deferred decisions.
- **Not delivered:** actual history, tuned coefficients, backtest claims,
  sector ETF candidate approval, UI/automation integration.

Next phase: reuse existing company event facts and market reference adapters,
assemble documented historical coverage, freeze a walk-forward plan, run
CSI300 first, then eligible sector ETFs. Produce manifest-bound evidence
including *negative* experiments before considering any production integration.
