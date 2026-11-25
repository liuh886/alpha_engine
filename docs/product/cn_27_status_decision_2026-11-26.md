# CN_27 V1.3 status decision memo — 2026-11-26

## Decision requested

This is an investigation and recommendation only. It changes no code, model,
registry, evidence or frontend. The Owner is asked to choose one option in
[Section 4](#4-recommendation-and-exact-owner-decision).

**Recommendation: Option A.** Record CN_27 V1.3 as a contract-frozen formal
baseline with prospective validation pending and current operations dormant,
and fix only the lifecycle *semantics* (registry/UI wording). Preserve every
sealed artifact, the `cn_27_v1_3` identity, the 2026-09-04/729-session window
and the 30-session cadence. Do not extend or rerun the trace.

Issue #1256 item 4 asks to recover CN_27 or explicitly pause/offline it with a
recorded decision. The evidence below shows there is nothing to "recover" in
the data pipeline: the 729-session trace is deliberately and contractually
sealed at 2026-09-04, and the current-target path is dormant by construction.
The remaining defect is that the product presents a contract freeze as
pipeline staleness.

---

## 0. Evidence basis

All references are to the repository at `1b073bcb2e` (2026-11-26), inspected
read-only.

| Evidence | Observed value |
| --- | --- |
| Formal run directory | `data/research/formal_model_runs/cn_27_rotation/cn_27_v1_3/cn_27_v1_3-through-2026_11_24/` |
| Manifest `evidence_cutoff` | `2026-11-24` |
| Manifest `comparability_key.end` | `2026-09-04` |
| `performance.json` `date_range` | `2023-09-01` .. `2026-09-04` |
| `performance.json` `report` rows | 729 (first 2023-09-01, last 2026-09-04) |
| `summary.json` metric `sample_count` | 729 for every retained metric |
| `summary.json` total return | `1.2735932645814865` (unchanged from contract) |
| Formal catalog record | `evidence_cutoff: 2026-11-24`, `bundle_id: ad798b16…`, `manifest_sha256: 2ef111c8…` |
| Lineage `source_freshness.status` | `frozen_historical_evidence_prospective_pending` |
| Lineage `source_freshness.latest_completed_session` | `2026-11-24` |
| Lineage `source_freshness.prospective_gate_status` | `pending` |

Live governed status read on 2026-11-26 (read-only call to
`src.research.cn_27_current_target.prospective_source_status`):

```json
{
  "active_evidence_cutoff": "2026-11-24",
  "frozen_evidence_cutoff": "2026-09-04",
  "prospective_source_available": true,
  "current_target_available": false,
  "current_target_blocking_reason": "CN_27 refreshed positions do not cover 2026-11-24"
}
```

The discrepancy between `prospective_source_available: true` and
`current_target_available: false` is explained in
[Finding 5](#finding-5--the-current-target-guard-tests-metadata-not-evidence).

---

## 1. Is `sessions: 729` a contractual cap or a data/pipeline defect?

**Verdict: neither a forward "cap" nor a data/pipeline defect. It is the exact
session count of a contractually frozen historical evaluation window
(2023-09-01 .. 2026-09-04), and the freeze is intentional.**

### Contract lines

- `configs/research_paradigms/cn_27_v1_2.yaml:86-87` is the authoritative
  declaration inherited by the discovery lineage:
  `full_window: {start: "2023-09-01", end: "2026-09-04", sessions: 729}`.
- `configs/models/cn_27_v1_3.yaml:105-108` records the same window as
  `historical_evidence.evaluation_end: "2026-09-04"` and `sessions: 729`.
  The surrounding block is named `historical_evidence` (line 105); it is a
  record of consumed history, not a forward limit.
- `configs/models/cn_27_v1_3.yaml:10-11` declares
  `fresh_historical_holdout: false` and `historical_evidence_consumed: true`.
- `configs/models/cn_27_v1_3.yaml:135-146` declares
  `prospective_validation.status: "pending"`,
  `observation_start_strictly_after: "2026-09-04"`,
  `minimum_expected_sessions: 240`, `parameters_mutable: false`,
  `pool_mutable: false`, `costs_mutable: false`, `paper_trading_only: true`.
- `configs/research_experiments/cn_27_v1_3_prospective_validation_v1.yaml`
  repeats the boundary and adds `append_only: true` and
  `allow_historical_overlap: false`.

The frozen window is not merely recorded in YAML. The runtime loader merges the
paradigm base through the discovery chain, and the merged spec was resolved
read-only on 2026-11-26:

```
evaluation.full_window = {'start': '2023-09-01', 'end': '2026-09-04', 'sessions': 729}
```

### Code paths

- `src/research/cn27_v1_3_projected.py:287-291` reads
  `contract.spec["evaluation"]["full_window"]["end"]` as the cutoff. An
  `observation_end` may only move it *forward*, never before the frozen end
  (line 291 raises `observation end cannot precede the frozen historical
  window`).
- `scripts/refresh_cn_27_v1_3_formal.py:465-468` then re-seals the trace:

  ```python
  # Keep consumed historical evidence and its metrics sealed at their original
  # window. Only the compact research operating state advances to the cutoff.
  frozen_end = pd.Timestamp(context.contract.spec["evaluation"]["full_window"]["end"])
  result = replace(result, daily=result.daily.loc[:frozen_end].copy())
  ```

  This is an explicit design comment, not an accident. The append-only refresh
  computes a fresh operating state at the cutoff (line 427) but truncates the
  published daily series to the frozen end before building `report`,
  `positions` and `trades` (lines 468-471).
- `src/research/cn27_v1_3_replay.py:179-192` requires the recomputed bars to
  end exactly at the published trace boundary:
  `recomputed bars do not end at the published trace boundary` is an
  `invalid_evidence` failure.
- `src/artifacts/formal_bundle_reader.py:68-89` documents the same invariant:
  `trace_end` is "the single source of truth" for the retained performance
  boundary, and "append-only refreshes advance `evidence_cutoff` and freshness
  while the frozen trace stays put, so callers must never infer the trace
  boundary from the cutoff."

### Formal artifacts

- The published `performance.json` has 729 rows ending 2026-09-04, even though
  the run is named `through-2026_11_24`.
- `summary.json` retains `sample_count: 729` and the contract total return.
  It carries no `evidence_cutoff` field, so a casual consumer sees
  "through-2026_11_24" and 729 samples together. This is a presentation gap,
  not corrupt evidence.
- `manifest.json` records both facts explicitly:
  `evidence_cutoff: "2026-11-24"` and `comparability_key.end: "2026-09-04"`.

### What this means

`sessions: 729` is correct for the declared frozen window. Extending it would
not be a "fix"; it would consume post-2026-09-04 data into a historical
evidence set already declared consumed and would violate the prospective
contract's `allow_historical_overlap: false`. The append-only refresh that
advances `evidence_cutoff` without extending the trace is the intended
mechanism, documented in code (`formal_bundle_reader.py:72-75`) and accepted in
the #1282 receipt (`docs/evidence/product_v1/reproduce_local_reference_1282_2026-11-15.json:15`:
"CN_27 reproduces the frozen trace boundary 2026-09-04; appended economics are
not part of this audit").

There *is* a genuine defect nearby, but it is a semantics defect, not the
session count: the run's `evidence_cutoff` and the sealed trace boundary are
allowed to diverge, and downstream consumers treat the advanced cutoff as if
the evidence itself advanced. See Findings 4 and 5.

---

## 2. Where does the UI `Stale · Nd behind cutoff` label come from, and is it semantically correct?

### Provenance chain (file:line)

1. The governed run model takes the cutoff from the **manifest**, not from the
   trace: `qlib-dashboard/src/lib/governed-run.ts:240`
   (`evidenceCutoff: manifest.evidence_cutoff`). For CN_27 that is
   `2026-11-24`.
2. The staleness threshold is 14 calendar days:
   `qlib-dashboard/src/lib/metrics.ts:10` (`STALE_AFTER_DAYS = 14`).
3. Ranking rows compute
   `staleDays = calendarDaysBetween(lastNavDate, run.evidenceCutoff)`:
   `qlib-dashboard/src/lib/model-ranking.ts:417`, then
   `stale: ... staleDays > STALE_AFTER_DAYS` at
   `qlib-dashboard/src/lib/model-ranking.ts:434`.
4. The badge text is rendered at:
   - `qlib-dashboard/src/components/ModelRankingTable.tsx:302` (desktop row)
   - `qlib-dashboard/src/components/ModelRankingTable.tsx:491` (mobile card)
   - `qlib-dashboard/src/components/StrategyChartHero.tsx:817`
     (`Stale by {staleBy} day…`, computed at line 496 from
     `run.evidenceCutoff` and the chart's effective coverage as-of).
5. The observed UAT values are recorded at
   `docs/evidence/product_v1/w2_uat_privacy_2026-11-16.json:409`
   (`latest_state_date_row`), `:417` (`stale_badge_text` =
   `"Stale · 70d behind cutoff"`) and `:479`
   (`stale_by_70_days_text` = `"Stale by 70 days"`).

### Arithmetic

- UAT on 2026-11-13: last trace date 2026-09-04 → 2026-11-13 = **70 days**.
  Matches the recorded 70d badge exactly.
- Current run cutoff 2026-11-24: 2026-09-04 → 2026-11-24 = **81 days**.
  The same code would now render `Stale · 81d behind cutoff`.

### Semantic verdict

**Numerically correct, semantically misleading for a contract-frozen trace.**

- The arithmetic is right: the retained trace really does end 81 calendar days
  before the run's manifest cutoff.
- But "stale" implies the evidence *should* have advanced and failed to. For
  CN_27 the trace is intentionally sealed at its declared historical window
  (`formal_bundle_reader.py:72-75`). The declared lifecycle is not "late"; it
  is `frozen_historical_evidence_prospective_pending` (lineage
  `source_freshness.status`), with `prospective_gate_status: pending`.
- The UI has the correct lifecycle signal available in the run evidence, but
  `governed-run.ts` hard-codes `publicationStatus: 'accepted_formal_baseline'`
  (line 236) and never surfaces `source_freshness.status`. The label therefore
  conflates "the manifest cutoff advanced" with "this strategy's evidence is
  stale."
- Consequence: the W2 UAT correctly recorded the label but the label itself
  overstates a defect. An anonymous operator sees "Stale" and reasonably
  infers a broken refresh, while the governed replay is exact and the
  prospective gate is simply pending.

The label remains correct and useful for genuinely lagging traces (for example
US models whose performance traces should advance with source refresh). The
defect is that it is applied uniformly to a contract-frozen model.

---

## 3. Options and impacts

### Option A — Explicitly mark contract-frozen / paused (recommended)

Record the lifecycle state in the existing model contract/registry and render
it accurately; preserve all history and all gates.

**Concrete follow-up (separate PR; not done here):**

- Model contract `configs/models/cn_27_v1_3.yaml`: make the existing
  `prospective_validation.status: pending` the authoritative lifecycle state,
  and add an explicit current-operations state (for example
  `current_operations: dormant` or `formal_lifecycle: contract_frozen`).
- Registry `configs/strategies/registry.json`: expose that lifecycle state on
  the existing `cn_27` row. Do not add a second registry.
- UI: when the governed run reports
  `source_freshness.status: frozen_historical_evidence_prospective_pending`,
  render a truthful label such as
  `Frozen historical evidence through 2026-09-04 · prospective validation
  pending` (detail page) and a non-alarm row state instead of
  `Stale · Nd behind cutoff`. Keep the 14-day stale rule for non-frozen runs.
- Optionally make `summary.json`/catalog projection state the trace boundary
  (`2026-09-04`) alongside the run cutoff, so "through-2026_11_24" is not read
  as an evidence-extension claim.

**Impact:** no data, model, evidence or cadence change; one small scoped
docs/registry/UI-semantics change plus tests. Resolves #1256 item 4 with a
recorded decision. Preserves the sealed #1282 replay and every bundle hash.

**Risk:** the stale chip is shared by strategy, benchmark, stock and entity
surfaces. The change must be scoped to the contract-frozen lifecycle and must
keep existing tests for genuine staleness (for example
`qlib-dashboard/src/components/StrategyFleet.test.tsx:217-223` and
`qlib-dashboard/src/lib/model-ranking.test.ts:133-148`).

### Option B — New model version with extended source

Create a new contract (for example CN_27 V1.4/V2) with an extended evaluation
window and new governed data, then publish a new formal baseline.

**Requirements:** explicit Owner direction; a new frozen discovery/prospective
contract; a declared fresh-vs-consumed split; new provider/PIT evidence; a new
run, bundle and model identity; new gates and a new promotion receipt.

**Impact:** potentially recovers a current, extended evidence series, but it is
a new model program, not a repair of V1.3. It reopens model-selection and
multiple-testing risk (`configs/models/cn_27_v1_3.yaml:156-161` known
limitations) and needs substantial data-plane work (the 2026-09-04..2026-11-24
window is only about 55 CN sessions, far short of the 240-session prospective
gate).

**Risk:** highest cost and risk; must not reuse V1.3 consumed history as a
fresh holdout; must not mutate or relabel V1.3 evidence. This memo does not
claim such a model exists or is authorized.

### Option C — Resume under the existing contract

**Verdict: not technically valid as "recovery" of the historical trace; at
most a prospective paper-observation path that does not exist yet.**

Why it cannot extend the existing trace:

- The evaluation window is frozen at 2026-09-04
  (`configs/research_paradigms/cn_27_v1_2.yaml:87`) and the historical evidence
  is declared consumed (`configs/models/cn_27_v1_3.yaml:10-11`).
- The prospective contract requires observation strictly after 2026-09-04 with
  `append_only: true` and `allow_historical_overlap: false`, and needs 240
  sessions / 12 months (`configs/research_experiments/cn_27_v1_3_prospective_validation_v1.yaml`).
- The refresh truncates the daily series at the frozen end
  (`scripts/refresh_cn_27_v1_3_formal.py:465-468`), and replay fails unless the
  bars end at the published trace boundary
  (`src/research/cn27_v1_3_replay.py:179-192`). Any manual extension would
  break both gates.
- Extending the trace would therefore require a new contract and new evidence,
  which is Option B, not "the existing contract."

Why the current-target path is also blocked today:

- `src/research/cn_27_current_target.py:35` pins
  `FROZEN_EVIDENCE_CUTOFF = "2026-09-04"`.
- The append-only refresh deliberately excludes `operating_state` from the
  published evidence block (`scripts/refresh_cn_27_v1_3_formal.py:493-507`,
  especially line 494) and sets
  `operational_monitoring.runtime_state_embedded: false` (lines 559-563).
- Consequently `_operating_state(...)` returns `None` and
  `_target_at_cutoff(positions, "2026-11-24")` fails closed with
  `"CN_27 refreshed positions do not cover 2026-11-24"`
  (`src/research/cn_27_current_target.py:91-108`, `:230-246`), matching the
  live status read in Section 0.
- Even a future governed prospective source would only produce paper
  observations under the pending gate; it would not un-seal the historical
  trace or make the UI's "stale" label disappear unless the presentation is
  also fixed (Option A).

**Impact:** attempting C as a trace recovery would violate the consumed
evidence boundary and the replay/refresh gates; it cannot be made valid
without changing the contract (which is B).

---

## 4. Recommendation and exact Owner decision

### Recommendation

**Choose Option A.** It is the only option that (a) records a decision for
#1256 item 4, (b) accurately represents what the system already does, (c)
preserves the sealed evidence and exact #1282 replay, and (d) avoids reopening
model selection on already-consumed data. Option B remains available later only
as an explicit new-model mandate. Option C is not valid under the current
contract.

### Exact Owner decision needed

> **Approve Option A:** record CN_27 V1.3 as
> `contract_frozen_prospective_pending` with dormant current operations, and
> authorize a follow-up (separate PR) that (i) exposes this lifecycle state in
> the existing `configs/models/cn_27_v1_3.yaml` / `configs/strategies/registry.json`,
> and (ii) changes the UI to render
> `Frozen historical evidence through 2026-09-04 · prospective validation pending`
> (or equivalent non-alarm wording) instead of `Stale · Nd behind cutoff` for
> runs whose lineage `source_freshness.status` is
> `frozen_historical_evidence_prospective_pending`, while leaving the 14-day
> stale rule in force for genuinely lagging runs.
>
> **Explicitly not authorized by this decision:** extending the trace,
> retraining, rerunning consumed windows, changing the 30-session cadence,
> creating a new model version, or promoting any current signal.

If the Owner instead wants an extended evidence series, that is a separate
**Option B** mandate: authorize a new model version with a new frozen contract
and new governed source, and do not modify V1.3.

### What must NOT be changed

1. **Sealed evidence and bundle identity.** Do not modify
   `data/research/formal_model_runs/cn_27_rotation/cn_27_v1_3/cn_27_v1_3-through-2026_11_24/*`
   (`bundle_id ad798b16…`, manifest `2ef111c8…`), the formal/preview catalogs,
   or the promotion/publication receipts
   (`data/research/experiment_receipts/cn_27_v1_3_user_directed_promotion_v1.json`,
   `cn_27_v1_3_formal_publication_v1.json`).
2. **Model identity.** Keep `cn_27_v1_3`, family `cn_27_rotation`, recipe
   `k2_projected_22_45_n8`, the seven-factor combination, costs, and the
   `configs/models/cn_27_v1_3.yaml` identity/hashes.
3. **Frozen evaluation window.** Keep `2023-09-01 .. 2026-09-04` and
   `sessions: 729` (`configs/research_paradigms/cn_27_v1_2.yaml:86-87`,
   `configs/models/cn_27_v1_3.yaml:105-108`).
4. **Cadence and execution semantics.** Keep `rebalance_sessions: 30`,
   `decision_cadence: "Every 30 completed CN market sessions"`, signal/execution
   timing and cost treatment.
5. **Prospective contract gates.** Do not change the thresholds, stop rules,
   observation start, or `paper_trading_only`/`order_submission_allowed`
   boundaries in `cn_27_v1_3_prospective_validation_v1.yaml`.
6. **Research boundary.** Keep `research_only=true`, `trade_ready=false`,
   `automatic_promotion_allowed=false`,
   `selected_pool_readiness_claim_allowed=false`.
7. **Replay/refresh gates.** Do not weaken
   `src/research/cn27_v1_3_replay.py` or
   `scripts/refresh_cn_27_v1_3_formal.py`, and do not rerun consumed windows.

---

## 5. Findings ledger

### Finding 1 — The 729-session window is contractual

Confirmed at `configs/research_paradigms/cn_27_v1_2.yaml:86-87`,
`configs/models/cn_27_v1_3.yaml:105-108`, and by resolving the merged discovery
contract read-only on 2026-11-26. Not a defect.

### Finding 2 — The refresh intentionally advances metadata without extending the trace

`scripts/refresh_cn_27_v1_3_formal.py:465-468` truncates at the frozen end;
`src/artifacts/formal_bundle_reader.py:72-75` documents the resulting
`evidence_cutoff` / `trace_end` split; `cn_27_v1_3_replay.py:179-192` enforces
it. The #1282 receipt accepts this boundary.

### Finding 3 — The formal run is internally consistent but the run name overstates its window

`manifest.json` says `evidence_cutoff: 2026-11-24` and
`comparability_key.end: 2026-09-04`; `performance.json` has 729 rows ending
2026-09-04; `summary.json` reports 729 samples. The bundle is consistent; the
name `through-2026_11_24` describes the refresh cutoff, not the trace end.

### Finding 4 — The UI stale label is arithmetically correct but lifecycle-blind

`governed-run.ts:240` uses the manifest cutoff; `metrics.ts:10` sets 14 days;
`model-ranking.ts:417,434` computes the gap; `ModelRankingTable.tsx:302,491`
and `StrategyChartHero.tsx:817` render it. It does not consult
`source_freshness.status`. 70d at UAT (`w2_uat_privacy_2026-11-16.json:417,479`);
81d at the current cutoff.

### Finding 5 — The current-target guard tests metadata, not evidence

`src/research/cn_27_current_target.py:212-218` treats
`evidence_cutoff > 2026-09-04` as "prospective source available." Because the
append-only refresh advances `evidence_cutoff` to 2026-11-24, the live status
read reports `prospective_source_available: true`, while the target is still
unavailable because the published positions end 2026-09-04
(`current_target_blocking_reason: "CN_27 refreshed positions do not cover
2026-11-24"`). This is why the status read looks contradictory. It is a
semantics/guard defect to fix under Option A, not a data corruption.

### Finding 6 — The current-target path is dormant by construction

The refresh excludes `operating_state` from the published evidence
(`refresh_cn_27_v1_3_formal.py:493-507`) and sets
`runtime_state_embedded: false` (lines 559-563). `_operating_state` therefore
returns `None`, and the fallback `_target_at_cutoff` fails closed. No CN_27
current signal ledger exists in the worktree
(`data/research/strategy_signal_ledgers/` contains only BYD and other US/CN
entries, not `cn_27_v1_3`).

### Finding 7 — The observation window has not yet met the prospective gate

The prospective contract requires 12 months / 240 sessions strictly after
2026-09-04. The governed CN benchmark evidence
(`data/research/market_evidence/cn/symbols/000300.json`) contains 51 sessions
after 2026-09-04 through 2026-11-24, far short of 240. The gate is genuinely
pending, not failed.

---

## 6. Non-claims

This memo does not claim that CN_27 is recovered, that a new model exists, that
any gate passed, that current operations are live, or that the 729-session
evidence can be extended without a new contract. It makes no change to code,
models, evidence, registry or frontend.
