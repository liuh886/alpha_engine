# RDI launch priority — status audit and the shortest honest path to a published A-share risk assessment

**Date:** 2026-10-30 · **Type:** product priority / launch specification (docs only)
**Baseline:** main `2dfb2a8` · **Companion issue:** #1272 (RDI phase 2, open)
**Review correction:** 2026-10-30 owner comment on #1324; governed CN renewal
candidate now reaches 2026-10-29 (#1325, `d779137d77`). This does not renew RDI's
own source or qualify an already observed episode as prospective evidence.
**Execution boundary:** the owner comment scopes the next implementation to
Step 1 price/recomputation evidence. Steps 2–4 remain proposals requiring their
declared choices, frozen scope and reviews; merging this document passes no gate.
**Authority read before drafting:** `docs/research/ashare_rdi_architecture.md`,
`docs/research/ashare_rdi_phase2_protocol.md`, `src/research/ashare_rdi/`,
`src/research/studies/rdi_study.py`,
`qlib-dashboard/src/components/RdiResearchStatus.tsx`, `AGENTS.md`.

## 0. Why this PR exists

Owner statement, 2026-10-30: the depth of the July 2026 and October 2026
drawdowns was not anticipated, especially in A-shares; this was the largest
loss source of the year. RDI (A-share Risk Density Index) was built for
exactly this class of question. The owner asked two things: check whether
RDI is implemented and how it is running, and expedite its launch.

This PR answers the first with a verified status audit (§1) and answers the
second with a launch ladder (§3) that is the shortest path consistent with
the repository's own evidence rules. It registers no score, admits no
strategy, and changes no code.

## 1. Status audit — verified 2026-10-30

### 1.1 What is implemented

RDI is **implemented as a research prototype**, not a slideware design:

| Piece | State |
| --- | --- |
| PIT event contract (`ashare_rdi/contracts.py`) | Implemented. Timezone-aware `available_at <= cutoff` filtering, story-level deduplication, revision chains. |
| Coverage audit (`coverage.py`) | Implemented. Per-session, per-family archived completeness; absent/partial/unverified = `unknown`, never zero. |
| Outcome labels (`outcomes.py`) | Implemented. CSI300 close-to-close and ETF next-open helpers over 7/14/28 distinct XSHG sessions. |
| Candidate features + diagnostic (`phase2.py`) | Implemented. As-of-known risk/clearing concurrency, 60-session price-regime features, one blocked 70/30 chronological split with purging; output labelled `diagnostic_only`. |
| Price-only control (`price_baseline.py`) | Implemented and run (see §1.2). |
| Sector ETF guard (`sector_etfs.py`) | Implemented. Four candidates (512480 / 512800 / 512200 / 512690) remain **unapproved**. |
| Readiness receipt (`phase2_audit.py`) | Implemented. Reports `blocked` when PIT source coverage is missing. |
| Study Workspace entry (`studies/rdi_study.py`) | Implemented and **fail-closed**: returns `blocked_event_pit_coverage` because `historical_pit_event_coverage_complete: false` in the governing receipt. |
| Frontend (`RdiResearchStatus` in Operating Status) | Live. Shows "Not validated", "Risk assessment unavailable", the price-only historical comparison, a source inventory, and next-evidence text. No score is published — correctly. |

Test evidence: the 2026-10-24 increments record 29 passing RDI Python tests
plus frontend acceptance. This audit read the code on current main; it did
**not** re-run the suite, and no RDI evidence renewal has landed since the
2026-10-24 review.

### 1.2 The one quantitative result that exists

Price-only descriptive control, CSI300, predefined prior-60-session
drawdown ≥ 10% state vs other states — frequency of a ≥ 5% close-to-close
loss over the next h sessions (data through **2026-06-25**):

| h sessions | In deep-drawdown state | Other states |
| --- | --- | --- |
| 7 | 13.91% (n=1,258) | 6.74% (n=3,828) |
| 14 | 17.25% (n=1,258) | 11.99% (n=3,821) |
| 28 | 23.21% (n=1,258) | 20.62% (n=3,807) |

Descriptive association on overlapping windows. It is not a forecast, and
it says nothing yet about July–October 2026 — see §1.3, blocker 1.

### 1.3 Why RDI cannot run today — the blockers, in order

1. **Its price evidence ends 2026-06-25.** The reviewed CSI300 file spans
   index inception 2005-04-08 → 2026-06-25. RDI literally cannot see the
   July or October 2026 episodes. Governed CN evidence elsewhere now reaches
   2026-10-29 (#1325), but its 2021-start history is only a renewal candidate.
   Verify index identity, source bytes, overlapping prices, calendar and price
   basis before append-only extension; never replace the 2005-start history
   with the shorter projection or assume its readiness certifies RDI.
2. **Zero of ten event families have verified historical PIT coverage.**
   `configs/research_experiments/ashare_rdi_phase2_sources.yaml` labels all
   archived completeness `unverified`; the `company_events` adapters supply
   partial disclosure inputs without first-availability or absence evidence.
   The event-density features (E) therefore cannot be computed honestly for
   any historical window, and the study entry stays blocked — by design.
3. **No frozen multi-episode evaluation has ever run on real event data.**
   No walk-forward folds, no calibration, no incremental-utility result for
   E over the price-only baseline B. Hence no validated probability and no
   composite score — by the charter's own gates, not by neglect alone.
4. **Issue #1272 has not moved since 2026-10-25.** Its data-contract and
   backtest-protocol checklists are the launch work; they are still open.

The prototype and its blocked state exist. Evidence renewal also needs explicit
code/receipt integration: `briefing.py` binds the reviewed 2026-10-24 receipts and
price path/blob. Replacing the CSV alone produces `evidence_mismatch`; the current
price-baseline CLI output is not a drop-in replacement for the reviewed receipt.
This audit cannot establish that a validated RDI would have warned in either
episode, and does not treat missing data as evidence of predictive effectiveness.

## 2. Framing guardrails (read before §3)

- RDI's hypothesis is **forward downside frequency over 7/14/28 sessions**
  conditional on known-event density and market state. It is not, and must
  not be sold as, a drawdown-depth predictor. A future validated module may
  describe contract-bound conditional frequencies and uncertainty; there is no
  evidence yet that it would have issued useful July/October warnings.
- **July–October 2026 is an already observed, hypothesis-motivating,
  retrospective descriptive stress case**, never independent prospective/OOS
  evidence. Thresholds or weights
  chosen because they "would have caught" those two episodes are
  overfitting with extra steps and are rejected by this specification.
  True prospective observation begins with future completed sessions after a
  newly frozen spec, thresholds, source identities and as-of; each 7/14/28-session
  outcome becomes observable only after its own horizon matures.
- "Launch" in §3 means a **dated, evidence-bound published assessment**
  inside the existing Operating Status RDI section. It does not mean a
  composite 0–100 score (forbidden until probabilistic calibration
  succeeds), a new navigation destination, an alert, a strategy overlay, or
  any change to `research_only=true` / `trade_ready=false`.

## 3. Launch ladder — priority order, each step independently shippable

### Step 1 — Renew the price layer (the next implementation PR only)

**2026-10-31 execution update:** the read-only renewal preflight and
[M1–M5 / ten-family audit](../research/ashare_rdi_progress_2026-10-31.md)
now make the blocking inputs replayable. The retained source lacks XSHG session
2026-06-23 and conflicts with the governed candidate on 2026-06-22 OHLC.
M1 remains BLOCKED: no price splice, baseline recomputation or Status rebinding
has been admitted. Preserve the old evidence and resolve the source discrepancy
before treating the 85 candidate append rows as a continuous price history.

Extend the reviewed CSI300 price/calendar evidence from 2026-06-25 to the
current governed CN cutoff by reusing the repository's existing governed
evidence path (CN through 2026-10-29 at review), under existing provider
discipline. Freeze exact source/price-basis/calendar/version hashes and as-of;
verify overlap and append-only continuity with the existing long history.
Re-run `price_baseline` and the B (persistent bear state) features independently
of the still-blocked event study, preserving the predefined definitions.
Deliver source-verifiable replay commands and a dated recomputation receipt.
No UI, database or scheduler change is part of this next PR. An eventual update
to the existing Status projection requires explicit evidence rebinding and
tests; file replacement does not automatically update its hard-bound reader.

Acceptance:

- Source identity/hash, actual cutoff, index/calendar/session closure and price
  basis pass replay checks. Preserve old source blobs and receipts. Do not claim
  to clear a price-recency gate that `phase2_audit` does not currently implement;
  its event-PIT status remains blocked while required event coverage is absent.
- The renewed descriptive table (same predefined −10% / ≥5% definitions,
  unchanged) reports the observed July–October price-state period as retrospective
  descriptive evidence. For each horizon, publish eligible start/end dates,
  sample count, label-end range and missing tail; include only outcomes whose
  label end is at or before cutoff. Preserve `insufficient_future_bars` rather
  than shorten a horizon, fill future bars or imply all October labels matured.
- B-state features may run through cutoff once their lookbacks are satisfied;
  7/14/28-session outcome maturity is a separate boundary. Publish these states
  and limitations without an event-layer, counterfactual warning or prediction claim.

Rationale for first: B has no event inputs. Source and lookback checks can
qualify a price-only descriptive reconstruction of observed states. This renews
price evidence without establishing event readiness or launch approval.

### Step 2 — Certify ONE narrow event family end-to-end

Pick a single family whose availability times are mechanically verifiable
against existing `company_events` adapters — earnings disclosure windows or
restricted-share unlocks are the candidates — and certify it: coverage era,
per-session completeness verdicts, first-availability evidence, story
identity. Produce the coverage matrix for that family and wire the verdict
into `coverage.py` only after the family and scope are explicitly selected
and frozen. All other families remain `unknown`; nothing is
zero-filled.

Acceptance:

- The corresponding #1272 data-contract checklist items are closed with
  evidence links for this family only.
- One certificate does not automatically unblock the current full-contract
  `rdi_study` gate. It stays blocked until its declared required coverage passes;
  any narrower research scope needs its own reviewed, frozen contract in the
  existing study framework, not silent substitution of its requirements.

### Step 3 — Frozen multi-episode evaluation (pre-registered before running)

Freeze, in a dated spec committed before any run: features B, E (certified
families only), E+B; purged walk-forward folds with ≥28-session boundary
protection; episode/block bootstrap confidence intervals; the charter's
baselines and metrics (conditional downside hit rates, AUC where both
classes occur, Brier/calibration for any probability claim, incremental
out-of-sample utility of E over B). Historical held-out folds must be declared
without claiming independence for the already observed July–October motivating
cases. Keep those cases separately labelled retrospective descriptive stress
evidence. True prospective sessions begin after the new freeze and mature per
horizon; every threshold comes from the declared development sample only.

Acceptance:

- Manifest-bound evidence is published **either way**. A negative result is
  a retained result: RDI stays "not validated", the failure record states
  which gate failed, and this ladder is re-planned from that record — not
  quietly retried with new thresholds.

### Step 4 — Definition of "launched"

Only if Step 3 and the declared prospective gates pass may a separately reviewed
product change graduate the Operating Status RDI section to a **dated
research assessment**
for the latest completed session — B state plus certified E density, with
7/14/28 conditional downside frequencies and their intervals. Still no
composite score until calibration succeeds; still no strategy overlay
without the existing EvidenceBundle promotion gate and explicit owner
approval. If Step 3 fails, "launched" does not happen and §3 is revised
from the failure record.

## 4. Sequencing and boundaries

- The next PR is Step 1 price/recomputation evidence only, as the owner comment
  requires. Later event work is separately frozen; reuse existing entrypoints
  where their actual gates and receipt contracts apply. No new workflow,
  scheduler, registry, store or navigation — the workflow ceiling and the
  `AGENTS.md` RDI boundary (no uncalibrated score, live signal or strategy
  registration from this view) are unchanged.
- The ladder is independent of #1315 (frontend polish) and of the racetrack
  phases; it must not be queued behind them. It directly advances open
  issue #1272; implementing PRs should reference and close its checklist
  items step by step.

## 5. Explicit non-goals

- No uncalibrated composite 0–100 index.
- No tuning, threshold selection or weight fitting on July–October 2026.
- No invented, backfilled or proxy-zero event history.
- No sector ETF admission (candidates stay unapproved under their own gate).
- No alerts, no new navigation, no strategy registration or risk overlay.
- No claim that RDI predicts drawdown depth.

## 6. Decisions requested from the owner (do not block Step 1)

1. **Step 2 first family:** earnings disclosure windows, or restricted-share
   unlocks?
2. **Step 4 surface:** is the Status-section published assessment the launch
   target, or is a CLI-only dated assessment sufficient for the first
   season?

## 7. Review focus

- Is the §1 audit accurate against the code and receipts on main?
- Is Step 1's reuse of the governed CN evidence path the right renewal
  route, or does the RDI price file need its own provider pass?
- Are the §3 acceptance gates strict enough that a Step 4 "launched" label
  would be trustworthy on the next drawdown — not just explanatory after
  the last two?
