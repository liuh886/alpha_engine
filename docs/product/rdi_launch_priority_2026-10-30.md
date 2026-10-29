# RDI launch priority — status audit and the shortest honest path to a published A-share risk assessment

**Date:** 2026-10-30 · **Type:** product priority / launch specification (docs only)
**Baseline:** main `2dfb2a8` · **Companion issue:** #1272 (RDI phase 2, open)
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
   July or October 2026 episodes. This blocker is now removable by renewal,
   not new sourcing: governed CN evidence elsewhere in this repository
   already reaches 2026-10-28 (#1316, #1319).
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

Net: the machinery is built and honest; the **evidence** is what is missing.
RDI did not fail in July or October — it was never in a state where it
could have spoken.

## 2. Framing guardrails (read before §3)

- RDI's hypothesis is **forward downside frequency over 7/14/28 sessions**
  conditional on known-event density and market state. It is not, and must
  not be sold as, a drawdown-depth predictor. A launched RDI would have
  said "downside is materially more likely than usual in this state"; it
  would not have said how deep July or October would go.
- **July–October 2026 is a prospective evaluation case, never a tuning
  target** (charter, falsification-first protocol). Thresholds or weights
  chosen because they "would have caught" those two episodes are
  overfitting with extra steps and are rejected by this specification.
- "Launch" in §3 means a **dated, evidence-bound published assessment**
  inside the existing Operating Status RDI section. It does not mean a
  composite 0–100 score (forbidden until probabilistic calibration
  succeeds), a new navigation destination, an alert, a strategy overlay, or
  any change to `research_only=true` / `trade_ready=false`.

## 3. Launch ladder — priority order, each step independently shippable

### Step 1 — Renew the price layer (first; days, not weeks)

Extend the reviewed CSI300 price/calendar evidence from 2026-06-25 to the
current governed CN cutoff by reusing the repository's existing governed
evidence path (CN through 2026-10-28 at baseline), under existing provider
discipline. Re-run `price_baseline` and the B (persistent bear state)
features through July–October 2026 and issue a renewed dated readiness
receipt; the Status RDI section then shows the renewed cutoff and review
date.

Acceptance:

- `phase2_audit` no longer reports price recency as a blocker.
- The renewed descriptive table (same predefined −10% / ≥5% definitions,
  unchanged) covers the July–October 2026 window and labels it
  prospective/descriptive.
- B-state values for July and October 2026 sessions are published in the
  receipt, so the owner can see what the price layer alone would have said,
  with no event-layer claim attached.

Rationale for first: B needs no event coverage, is computable today, and is
the only layer that could have spoken during the two episodes. It converts
RDI from "cannot see 2026 at all" to "price-state assessment current".

### Step 2 — Certify ONE narrow event family end-to-end

Pick a single family whose availability times are mechanically verifiable
against existing `company_events` adapters — earnings disclosure windows or
restricted-share unlocks are the candidates — and certify it: coverage era,
per-session completeness verdicts, first-availability evidence, story
identity. Produce the coverage matrix for that family and wire the verdict
into `coverage.py`. All other families remain `unknown`; nothing is
zero-filled.

Acceptance:

- The corresponding #1272 data-contract checklist items are closed with
  evidence links for this family only.
- `rdi_study` remains blocked for uncertified families and unblocks only
  the certified family's features.

### Step 3 — Frozen multi-episode evaluation (pre-registered before running)

Freeze, in a dated spec committed before any run: features B, E (certified
families only), E+B; purged walk-forward folds with ≥28-session boundary
protection; episode/block bootstrap confidence intervals; the charter's
baselines and metrics (conditional downside hit rates, AUC where both
classes occur, Brier/calibration for any probability claim, incremental
out-of-sample utility of E over B). July–October 2026 sits in the test
partition as prospective episodes; every threshold comes from the
development sample only.

Acceptance:

- Manifest-bound evidence is published **either way**. A negative result is
  a retained result: RDI stays "not validated", the failure record states
  which gate failed, and this ladder is re-planned from that record — not
  quietly retried with new thresholds.

### Step 4 — Definition of "launched"

Only if Step 3 passes its predeclared gates: the Operating Status RDI
section graduates from readiness display to a **dated current assessment**
for the latest completed session — B state plus certified E density, with
7/14/28 conditional downside frequencies and their intervals. Still no
composite score until calibration succeeds; still no strategy overlay
without the existing EvidenceBundle promotion gate and explicit owner
approval. If Step 3 fails, "launched" does not happen and §3 is revised
from the failure record.

## 4. Sequencing and boundaries

- Steps 1–2 are data/evidence work under existing provider discipline and
  reuse existing entrypoints (`phase2_audit`, `briefing`). No new workflow,
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

## 6. Decisions requested from the owner (do not block Steps 1–2)

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
