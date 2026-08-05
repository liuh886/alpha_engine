# QQQ rotation candidate-model convergence through v4.26

Date: 2026-08-05

## Final candidate

The candidate-model search has converged on:

**QQQ Rotation v4.2 — `qqqi_qqq_tqqq_vxn_bridge_v4_2`**

v4.2 remains research-only and not automatically trade-ready. It is nevertheless the sole explicit candidate for prospective evidence accumulation because no governed challenger demonstrated a stable replacement.

The current objective is no longer to generate additional retrospective variants. It is to operate v4.2 consistently, record every fresh transition and execution, and evaluate whether its historical state logic survives prospective observation.

## Candidate definition

v4.2 is a slow daily recovery-risk-budget state machine.

| State | Interpretation | Target allocation |
|---|---|---|
| 0 | Defense | 100% QQQI |
| 1 | Unconfirmed recovery bridge | 50% QQQI + 50% QQQ |
| 2 | Confirmed leveraged recovery | 25% QQQ + 75% TQQQ |

Its core information structure is deliberately limited:

- QQQ long-, medium- and short-horizon price repair;
- shock memory;
- VIX normalization and stress;
- VXN stress;
- next-session-open execution under a fixed 10 bps turnover-cost assumption.

The model does not continuously optimize weights. It changes between three economically interpretable risk states.

## Why v4.2 remains the candidate

### 1. Its advantage is architectural, not a single factor

v4.2 combines:

- slow regime persistence;
- an intermediate bridge that reduces failed-recovery damage;
- delayed leverage until recovery and volatility conditions agree;
- continued participation in convex upside once state 2 is reached;
- lower turnover than reactive learned-action policies.

Several challengers improved local classification or selected isolated successful events, but their false defensive exits and unstable leverage decisions weakened compounding.

### 2. The main state-2 tail risk is not visible at the prior daily close

The state-2 tail audit found that the largest leveraged losses were predominantly formed intraday. The preceding close supplied no warning for the worst ten leveraged sessions.

This means a more reactive daily close model cannot reliably remove the principal damage after the fact. Intraday tail control requires a separate data, timestamp and execution contract rather than another daily threshold.

### 3. Linear and regularized models did not supply a stable replacement

Ridge, logistic, state-conditioned and action-advantage studies found fragments of ranking information, especially in credit and duration variables. They did not support stable magnitude calibration, executable action thresholds or superior out-of-sample portfolios.

### 4. XGBoost did not solve the information problem

Three distinct XGBoost architectures tested complementary hypotheses.

#### v4.23: grouped terminal-return ranking

- found non-random ranking structure;
- beat all deterministic ranking placebos;
- selected almost exclusively 100% cash or 100% TQQQ;
- action descriptors dominated SHAP;
- learned a convex endpoint prior rather than stable market timing.

#### v4.24: adjacent path-utility transitions

- removed action descriptors;
- retained defense, bridge, core and controlled leverage states;
- used exact path-aware utility;
- selected all four states;
- produced mean edge AUC below 0.50 and worsened regret by 17.34%.

Once the action prior was removed, the current daily features did not predict adjacent path improvement.

#### v4.26: joint ordinal risk-budget model

- fitted one four-class model rather than three independent edges;
- used the posterior expected risk level to avoid endpoint over-selection;
- produced macro AUC 0.4925, weighted kappa -0.0117 and macro recall 0.2076;
- worsened regret by 7.35%;
- beat only half of label placebos;
- failed again in the 2024+ quarantine window.

The realized optimal state was usually defense or leveraged. The model mapped uncertainty about these endpoints into bridge and core, selecting the wrong middle risk budget.

Together, these studies show that neither model capacity nor decision topology is the present bottleneck. The missing element is stable independent information about future path risk.

## Why the search stops here

Continuing to change XGBoost parameters, class weights, labels, probability mappings or state definitions after v4.26 would convert a governed exploration into retrospective model mining.

The following paths are now closed on the current 35 daily features:

- deeper or alternative boosters;
- class-weight and focal-loss experiments;
- argmax versus posterior-mean selection searches;
- probability thresholds and calibration;
- defense/leveraged endpoint-only classifiers;
- removing bridge or core after observing poor recall;
- changing the ten-session horizon or MAE penalty;
- SHAP-driven feature deletion;
- additional v4.27 variants without new admitted information.

## New-information boundary

v4.25 audited option-tail pricing, direct credit spreads, survivorship-safe breadth and option-positioning sources before permitting another model.

No complete public family passed the requirements for:

- sufficiently long history;
- current coverage;
- point-in-time availability;
- revision or vintage safety;
- survivorship safety;
- reproducibility and licensing clarity.

A future learned candidate must first introduce a genuinely new information family under a separate Phase 0 contract. It may not be built by splicing incompatible histories or treating revised data as historical real-time observations.

## Prospective convergence program

Issue #348 is now the primary research program.

For every fresh v4.2 state change, the ledger should record:

- signal and governed data dates;
- current and target state and weights;
- alert delivery status and fingerprint;
- theoretical next-open execution;
- observed or paper execution and deviation;
- 5-, 10-, 20- and 40-session outcomes;
- transition confirmation, reversal or unresolved status;
- frozen non-actionable hypotheses where already authorized.

Reconsideration of the historical one-session `1→2` confirmation effect requires both:

- at least eight new prospective `1→2` events; and
- at least 24 months of monitoring.

Historical search cannot substitute for either gate.

## Operating decision

- candidate model: QQQ Rotation v4.2;
- status: explicit converged research candidate;
- alert source: v4.2 only;
- XGBoost candidate: none;
- direct trading promotion: not authorized;
- next model search: blocked until new information passes Phase 0;
- immediate work: prospective event ledger, execution evidence and rolling outcome summaries.

Machine-readable candidate pointer:

`configs/research_paradigms/qqqi_qqq_tqqq_converged_candidate.yaml`
