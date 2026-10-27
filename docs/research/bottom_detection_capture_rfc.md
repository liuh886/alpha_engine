# Bottom Detection & Capture Research (BDCR) — Design RFC v0.1
Status: PROPOSED / RESEARCH ONLY · 2026-10-27
Owner: Alpha Engine Investment Research Infrastructure

## Decision problem
Detect when a sharp decline is transitioning from forced selling to stabilization **before** lagging moving-average confirmation, without blindly catching falling knives. Distinguish (A) candidate, (B) actionable small-risk trigger, (C) trend confirmation. Produce reproducible evidence, not an automatic order.

### Principles
- Avoid hindsight: a bottom is not knowable at decision time. Predict *conditional forward return / adverse excursion* rather than label an ex-post trough as a live fact.
- Separate opportunity (expected upside), risk (MAE and tail loss), and uncertainty (sample size, regime, PIT quality).
- Measure false positives and missed V-shaped recoveries as rigorously as winners.
- No live trading, auto-promotion or direct portfolio positions; research_only=true; trade_ready=false; retain PIT limitations.

## Research hypotheses (falsifiable)
H1: conditioned on drawdown and volatility, relative-strength inflection versus QQQ / sector benchmark predicts better 5/10/20-session forward risk-adjusted returns than RSI<30 alone.
H2: exhausted sell pressure plus price acceptance (wick/close-position/volume and higher low) adds independent OOS predictive value after H1.
H3: two-stage early probe + confirmation increases **net** bottom-capture utility versus wait-for-20DMA and fixed-timed entry, after stop slippage and costs.
H4: signal utility varies strongly by regimes (broad selloff vs idiosyncratic earnings gap, fundamentals deteriorating vs improving).

## Decision-time feature contract
For symbol s and session t, only use observations timestamped and available by decision cutoff t close (or intraday cutoff in a separate later experiment).
- Drawdown: 20/60/120-day high-to-close, standardized by realized vol or ATR; 3/5/10-day downside intensity.
- Exhaustion: downside-volume / total-volume percentile (if actual volume valid), gap and range structure, close-location value (close-low)/(high-low), long lower wick, falling sell-volume, volatility contraction *after* expansion. Never infer buy/sell aggressor from daily bars.
- Relative strength: 5/10-day stock-minus-QQQ and stock-minus-sector returns, rolling slope, divergence when benchmark makes fresh low but stock does not, controlled for beta.
- Price acceptance: regained prior low, local higher low without future pivots, breakout above rolling resistance; causal lag of all confirmations.
- Fundamental/valuation: explicitly versioned PIT filings/consensus/financing events where actually available; missing = unknown (not favorable). GAAP cash flow, dilution/debt/maturity and guidance revision veto evidence, not fictional daily scores.
- Regime: VIX/VXN only with verified PIT coverage; QQQ trend and breadth, 10Y rates, sector ETF risk, earnings-event calendar.
- Liquidity: spreads, ADV, suspended/delisted and corporate actions; threshold defined in test specification.
Feature schema: symbol, observation_cutoff_utc, market_session, source_manifest_sha, universe_version, benchmark_role, raw_adjusted_policy, feature_version, feature_values, missing_reasons, PIT_certification.

## Scoring prototype (NOT validated)
Exhaustion 25, relative-strength improvement 20, price-volume acceptance 20, valuation/fundamental durability 20, market risk appetite 15. Normalize each subscore to [0,1] against *training-period* empirical distributions, not full-sample ranks. Missing fields carry explicit coverage & confidence penalties, never silently imputed. Weight vector / 65-80 cutoffs are research candidates, NOT trade rules.
Hard veto candidate list: restatement/major guidance withdrawal, imminent financing uncertainty, untenable liquidity, earnings within a declared exclusion window, missing corporate actions, benchmark mismatch, stale data; test veto impact individually.

## States and state machine
WATCH: oversold candidate with required coverage.
PROBE_ELIGIBLE: independent exhaust/RS/acceptance evidence plus defined invalidation and position-size risk budget.
CONFIRMED: subsequent price strength passes prospective criteria (no backfilled status).
INVALIDATED: price or fundamental veto breached.
BLOCKED: insufficient/PIT-invalid data; not scored.
All state transitions preserve t, input hash, reasons, selected threshold version; NEVER promote merely because the future trough is known. Minimum dwell/cooldown rules prevent signal churn and repeated-buy look-ahead.

## Backtest construction
Universes: frozen governed US 87 equities and eligible reference benchmarks; QQQ and sector ETFs role-separated. BE/CRDO/IREN/NBIS are *diagnostic case studies only*; never hand-pick/test exclusively on them. Include sideways, bear, bull, earnings gaps and delisting exposure where data allows.
Baselines (matched cost/folds): RSI(14)<30; Bollinger lower-band re-entry; 20DMA reclaim; 5-day reversal; random matched-drawdown entries; cash/QQQ hurdle.
Events: define *prospective* signal at close t, earliest eligible execution t+1 with spread+impact+fees, overnight gap and stop execution modeled. Examine 5/10/20 session holding periods and staged entries (e.g., 25% probe, later confirmation), max single-position loss budget, no leverage. Multiple overlapping signals per symbol deduplicated and embargoed.
Walk-forward: train-only threshold/weights, purged/embargoed rolling folds with distinct OOS periods; no cross-fold optimization on test; label horizons overlap accounted for; OOS universes and source hashes frozen; independent untouched holdout before publish. Bootstrap CIs by time/block and symbol clusters; multiple-comparison correction / trial registry. Include 0/base/15bps+ gap/slippage sensitivities, turnover, costs and portfolio capacity.
Outcomes: net excess return vs matched benchmark, win rate, expectancy, Sharpe, drawdown, tail loss, MFE/MAE, time underwater, signals/month, coverage, calibration and missed-signal rate.
Bottom Capture Efficiency is **diagnostic only**, ex-post defined after horizon H: (exit-entry)/(max_future_price_in_window-min_future_price_in_window), clipped/report anomalies, alongside actual executable net return and MAE. Do not optimize this look-ahead metric alone; pre-register H and reporting convention.
Report attribution by market regime, earnings proximity, volatility, valuation availability, and stock vs index decline.

## Research integrity & release gates
G0 Data readiness: PIT/adjusted prices/delistings/benchmark timestamps verified; otherwise BLOCKED and explicitly pit_certified=false.
G1 Baselines reproduced under identical folds and realistic costs; synthetic tests for no future leakage, splits, missing/stale prices, horizon overlaps, stop gaps and day-one execution.
G2 Out-of-sample: positive net expectancy and meaningful improvement versus strongest baseline with confidence interval; predeclare thresholds and risk limits *before* validation. No claim of universal high win rate.
G3 Robustness: stable effects by 5/10/20-day horizons, alternate regimes and 0/base/15bps+; parameter neighborhoods not a single lucky point; failure modes published.
G4 Shadow: persist daily prospective WATCH/PROBE/CONFIRMED/BLOCKED log and simulated trades for a full review window, with performance/cost drift and missed bottom reviews; no real orders.
G5 Human release review: operator reviews evidence and rollback; feature flag read-only in existing Console detail/Decision Feed if rights permit. Remains research-only until a separately authorized trading governance process (out of scope).

## Architecture / integration
- Reuse src/data/research_slice.py as sole governed data access and source manifests.
- Implement factor/execution definitions as a new template within existing src/research/study_workspace.py and src/research/walkforward/pipeline.py paths, without a second research executor or DB.
- Use existing 'alpha research study list/init/run/show/compare' interface and immutable artifacts/research_studies/<study_id>/<study_hash>.json receipts.
- Store specification under configs/research_experiments/ following existing conventions; no automatic formal model registration.
- Optional read-only UI later: instrument/strategy evidence detail showing status, evidence, counterevidence, cutoff, uncertainty, invalidation and next review; comply with PR #1305/#1306 view boundaries and #1288 privacy gate.
- Keep current four-strategy fleet, registry, current operations, scheduler and public Pages unchanged.

## Delivery slices / Agent TODO
- [ ] BD-00 Survey actual data coverage, benchmark roles, PIT availability and current study template APIs; publish dependency map and blockers.
- [ ] BD-01 Create immutable versioned spec + feature contracts + synthetic fixtures; do not bake discretionary prices from 2026 examples.
- [ ] BD-02 Implement causal daily-bar indicators + state transitions; unit/property tests for leakage and invalidation.
- [ ] BD-03 Extend existing study CLI with BDCR hypothesis family, reuse governed WFO, baseline parity and blocked receipts.
- [ ] BD-04 Run frozen US-pool OOS against ≥5 baselines; publish tables with uncertainty, net costs and failure cases.
- [ ] BD-05 Run ablations and regime diagnostics; classify surviving/failed hypotheses, register next iteration.
- [ ] BD-06 Prospective daily shadow evidence, no live trading; measure alerts, false positives, missed rebound and drift.
- [ ] BD-07 Only after passing gates, propose read-only presentation integrated into existing Decision Feed, no new navigation.
- [ ] BD-08 Explicit human GO/NO-GO review, rollback instructions, version bump and reproducible research package.

## Acceptance deliverables
One machine-readable experiment config, tested feature implementation, frozen manifests, research-only receipts, baseline+ablation comparison, complete failure ledger, shadow log and read-only usability test. Each task closes only with commit + reproducible commands + evidence link; no unearned 'done' markers.

## Outstanding decisions for experimental preregistration
Exact holding horizon and missed-bottom window; execution price realism with daily bars; score thresholds and safety veto scope; acceptable marginal net utility vs baselines; minimum number of independent event clusters and shadow duration; availability/legality of PIT fundamentals and options inputs. Treat these as questions to answer empirically, not undocumented defaults.
