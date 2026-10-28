# First season: six racers, two tracks

Status: proposal / RFC. Docs only. No runtime, data, registry, workflow, or
frontend code is changed by this document. `research_only=true`,
`trade_ready=false` are unchanged. This proposal does not close #1288 or any
Direction A release gate, does not claim PIT certification, and does not
authorise live trading, public signals, or automatic execution.

Baseline: `main@ba5418e0` (2026-10-28), after #1306 (racetrack pipeline
v1.1 / schema v1.0), #1310 (governed evidence through US/CN 2026-10-27), and
#1311 (Racetrack research view inside the existing Overview, Lightweight
Charts 5.2.1 pinned). Related documents: `docs/product/racetrack_vision_2026-10-27.md`
(§§2, 3, 5, 11–15), `docs/architecture/racetrack_minimal_stack_spec.md`
(Phase 1), `docs/architecture/racetrack_runner_scoring_spec.md` (Phase 2),
`docs/architecture/racetrack_pipeline_spec.md` (Phase 3),
`docs/product/racetrack_frontend.md` (#1311 landing status), and
`docs/product/future_research_agenda_2026-10-28.md` (#1308, items A3, B3, B5).

## 1. Decision in one paragraph

The first season runs **six racers on two tracks, three per track** — not one
combined Top 6. The existing four formal strategies plus the two pool indices
are the starting grid. A racer is admitted only when it satisfies the Phase 2
runner contract and is replayed through the Phase 1 V & NAV engine; no formal
return is copied into the scoreboard. Until a racer is admitted, the
leaderboard stays honestly empty for that track, as #1311 already does.

## 2. Starting grid

### 2.1 US track (`market="us"`, calendar XNYS)

| Racer | Role | Macro benchmark (not a racer) | Internal benchmark (also a racer) |
|---|---|---|---|
| QQQR v4.3 | Formal strategy, to be replayed | QQQ | US 87 EW Pool Index |
| US x1.3 | Formal strategy, to be replayed | QQQ | US 87 EW Pool Index |
| US 87 EW Pool Index | Pool index, also a racer | QQQ | — (itself) |

### 2.2 CN track (`market="cn"`, calendar XSHG)

| Racer | Role | Macro benchmark (not a racer) | Internal benchmark (also a racer) |
|---|---|---|---|
| BYD v1.3 | Formal strategy, to be replayed | CSI 300 (`000300` / `000300.SH`) | CN 130 EW Pool Index |
| CN_27 V1.3 | Formal strategy, to be replayed | CSI 300 | CN 130 EW Pool Index |
| CN 130 EW Pool Index | Pool index, also a racer | CSI 300 | — (itself) |

### 2.3 Why two tracks, not one race

- Calendars differ (XNYS vs XSHG); a shared trading-day axis across markets
  would invent sessions that do not exist in one market.
- Macro benchmarks differ (QQQ vs CSI 300); a single cross-market rank would
  compare a US excess against a CN excess as if they were the same quantity.
- Pool universes differ (US 87 vs CN 130). The Phase 3 dual-market benchmark
  architecture is already market-isolated; the scoreboard must stay that way.
- The existing frontend already enforces this: #1311 provides a US/CN market
  selector with US/CN isolation. A combined Top 6 view is a non-goal of this
  proposal and must not be added as a side effect of admitting racers.

## 3. Pool indices as racers

Both pool indices are already defined as rules in the Phase 3 spec; this
proposal does not redefine them, it only admits them as racers under those
rules:

- Equal weight: US `1/87`, CN `1/130`.
- Rebalance: first official trading session of each calendar month.
- Unlisted / halted constituents: the exact `1/N` slot is held in cash
  (`w_cash = N_unlisted / N_declared`); silent redistribution across active
  assets is prohibited.
- Friction: 8 bps one-sided transaction friction, same V & NAV engine as
  every other racer.
- Excess decomposition per racer, once admitted: macro excess
  (`R_runner - R_macro`) and pool excess (`R_runner - R_pool_index`)
  reported separately, never blended into one headline number.

Labelling rule (frontend): a pool index must be labelled in the UI as
"internal benchmark, also racing", distinct from the macro benchmark
("reference only, not racing") and from ordinary strategy racers. The
dual role must be visible on the leaderboard row, the runner detail page,
and the chart legend — not explained only in this document.

Thesis rule: a pool index is not exempt from the thesis gate. Its thesis is
short but must be written, e.g. "equal-weighted monthly-rebalanced pool
average; earns the pool's average selection return, not a single-name bet".
An empty or missing thesis blocks admission exactly as for any other racer.

## 4. Admission contract (applies to all six, no exceptions)

Each racer must satisfy the Phase 2 runner contract before its first season
points are counted:

1. **Thesis gate.** A substantive written investment thesis: why it was
   built, what anomaly or structure it bets on, and under what conditions
   it fails. Empty or terse theses fail closed (`ThesisMissingError` in
   the Phase 2 spec).
2. **Decoupled logic.** `selection_logic` and `rebalance_logic` recorded
   separately, in the order the runner detail page displays them
   (thesis first, then selection, then rebalance).
3. **Pure replay.** The racer implements `run(matrix: PriceMatrix,
   ledger_path: Path) -> SimulationResult`, emitting a hash-chained,
   privacy-clean JSONL target-weight event ledger (`Q` events only; no
   shares, cost, account, or PnL fields — personal-lens fail-closed).
4. **One derivation authority.** NAV, weights, returns, monthly ranks, and
   season points are derived by the Phase 1 V & NAV engine and the Phase 2
   scoring module from `P` and the `Q` ledger. The frontend rebases / slices
   published NAV for display only and never recomputes ranks, returns, or
   points.
5. **Pool compliance.** Target symbols are checked against the track's
   pool registry (US: `us_selected_equities_v2.yaml`; CN: see §5.2).
   Out-of-pool assets and reference benchmarks (QQQ, CSI 300) as holdings
   fail closed.
6. **Reconciliation.** A replayed racer's NAV must be reconciled against its
   formal-strategy evidence (same cutoff, same friction baseline). Any
   material difference is documented as a known difference with a reason;
   it is never silently overwritten, and the racer is not admitted on the
   formal number while the replay disagrees.
7. **Provisional labelling.** Season points are provisional until the
   complete-window review at month close. Partial months are labelled
   partial; settlement is never inferred from provisional monthly ranks
   (see §6).

What admission is NOT: copying a formal backtest return, a formal target
weight, or a decision signal into the scoreboard; adding a demo / placeholder
racer to make the leaderboard look full; or promoting a racer on the basis
of a single month, a single day, or an in-sample result alone.

## 5. Landing order

### Phase A — US pool index first (unblocked)

Admit the US 87 EW Pool Index as the first racer. It needs no formal-strategy
replay and no registry extension: its rule, universe, calendar, and friction
are already specified, and the US runner registry already exists. Success
criterion: the US track shows one racing benchmark with a replayed NAV,
monthly ranks, and season points, alongside QQQ as reference-only.

### Phase B — US formal strategies, by replay

Replay QQQR v4.3 and US x1.3 through the Phase 2 contract (§4). Each needs
its thesis, decoupled logic, `Q` ledger, and reconciliation against its
formal evidence (formal evidence for all four strategies is currently
2026-10-27). Success criterion: the US track shows three racers with
comparable, replay-derived NAVs — not four numbers from four different
methods.

### Phase C — CN registry extension (spec-doc amendment + instance, corrected 2026-10-28)

Extend the runner registry to the CN market before any CN racer is admitted.
Correction to the earlier wording of this phase: the current Phase 2 *spec
document* is US-only in prose, but the Phase 2 *code* is already
dual-market (matrix calendar map XNYS/XSHG, pipeline market specs for both
markets, `RunnerRegistry` taking a `pool_id`). Phase C therefore does NOT
build a new CN registry, scorer, or pipeline. It delivers, as a versioned
spec change plus instantiation:

- CN pool registry: `cn_selected_equities_v3.yaml` (130 symbols) as the
  whitelist, with the same fail-closed behaviour as the US whitelist.
- CN calendar: XSHG via `exchange_calendars`; CN season cadence = natural
  calendar months on XSHG, settled at the close of the last XSHG session.
- CN benchmarks in the scoring module: macro CSI 300 and internal CN 130 EW
  Pool Index, with the same dual-excess decomposition as the US track.
- CN privacy and PIT handling identical to the US track: no private account
  fields in ledgers or projections; `pit_certified=false` stays visible
  until a certification path exists (agenda item B1).
- A docstring fix in `matrix.py` (currently says XNYS for US only); code
  behaviour is unchanged by that fix.

Until Phase C lands, BYD v1.3 and CN_27 V1.3 must not be admitted, even as
"CN racers in the US registry" — that would be a whitelist violation, not a
shortcut.

### Phase D — CN pool index, then CN formal strategies

Admit the CN 130 EW Pool Index first (same rule as §3, XSHG calendar), then
replay BYD v1.3 and CN_27 V1.3 under §4. Success criterion: the CN track
shows three racers with replay-derived NAVs, comparable within the CN track
only.

## 6. Known gaps this proposal does NOT close

These are recorded here so that admitting six racers is not misread as
closing them. Each remains an open item with its own closing test:

- **Per-window ranking.** The merged contract provides cumulative ranks;
  per-window Top 10 ranking is not present (#1311 frontend doc, §"Display
  and interpretation"). Window controls currently rebase / slice NAV and
  use precomputed period fields; they do not re-rank runners within the
  window. Whether the first season's "window Top 10" means cumulative rank
  sliced by window, or true per-window rank, must be decided and written
  into the frontend doc before the first season is read as a window race.
- **Settled month snapshots.** Judged drawdown / indicator series, event
  markers, rebalance ledger chunks, and measured association profiles
  require future source contracts (per #1311 landing status). Do not
  calculate them in the browser.
- **BYD whitelist question.** BYD v1.3's current formal target includes
  515180 (an ETF) alongside BYD. Whether 515180 is admissible under the CN
  pool whitelist, or must be represented differently in a runner ledger,
  is undecided and must be resolved in Phase C — not by silently dropping
  or renaming the holding.
- **CN_27 composition question.** Whether CN_27's 27 holdings are all
  within the CN 130 universe, and what happens to any holding outside it,
  is undecided and must be resolved in Phase C.
- **QQQR / US x1.3 replay feasibility.** Whether these two formal
  strategies can be expressed as pure `run()` functions over the governed
  price matrix without manual decision inputs is not yet established; if
  either cannot, it stays a formal strategy and is not admitted, and the
  US track starts with fewer than three racers rather than with a
  non-replayable one.
- **PIT, corporate actions, CN benchmark publication.** PIT certification
  (agenda B1), corporate-action source / backfill (B2), and publication of
  the CN pool index as a versioned artefact (not just a spec rule) remain
  open. Admitting racers does not certify any of them.
- **Decision loop.** Decision Feed / Evidence Review implementation
  (#1305, currently docs TODO), the private Decision Journal (agenda A2),
  season / pool review rituals (A4), and the Brief Top 3 vs Scoreboard
  Top 10 information architecture (A1) are not delivered by this proposal.
  When the first racers appear, the scoreboard must carry a one-line
  explanation of how Brief Top 3 and Scoreboard Top 10 relate, or the
  conflict will become visible the first week runners exist.

## 7. Definition of done for the first season

The first season is "running" when, per track, every admitted racer meets
§4, the local Racetrack view shows a non-empty leaderboard for that track
(hosted Pages still shows "projection unavailable" by design — local-only
is not a failure), and the following are all visible on-page: track
(US / CN), market and pool version, evidence cutoff and generation
timestamp, friction baseline (8 bps) with sensitivities kept separate,
provisional vs settled season status, and the PIT-not-certified
qualification. The first season is "complete" when one full calendar month
settles under PointsRuleV1 and the season review ritual (agenda A4) has
been run once — a review, or an explicit "no change" record, not silence.

## 8. Non-goals

- One combined US+CN Top 6 ranking.
- Copying formal returns, targets, or signals into the scoreboard.
- Demo, placeholder, or synthetic racers in a real season (synthetic
  fixtures stay in tests and screenshots, labelled as such, as in #1311).
- Retiring the four-strategy monitor: it remains the default and
  independent, per #1311; the Racetrack view is an addition inside
  Overview, not a replacement.
- Public publication of racetrack projections, live trading, automatic
  execution, or any recommendation: `research_only=true` throughout.
- Admitting #1307 (bottom detection, still a draft RFC) as a racer: it
  remains a research family under its own OOS / shadow gates and is not
  part of this six-racer grid.

## 9. Review focus

Reviewers are asked to check, in order: (1) whether the two-track framing
contradicts any merged spec; (2) whether Phase C is correctly scoped as a
spec change, not a code-only tweak; (3) whether §6's open questions are
complete — especially BYD's 515180 holding and CN_27's composition; and
(4) whether any sentence in this proposal reads as a decision on
per-window ranking, PIT, corporate actions, or the decision loop, which
are explicitly left open above.

## 10. Decisions fixed 2026-10-28 (user sign-off, supersedes §6 where stated)

These decisions were given after the architect review and are recorded
here, not silently folded into earlier sections. Where a decision changes
a merged rule, the implementation must introduce a new versioned rule,
never silently edit the old one.

1. **Window ranking: true per-window rank, display-only.** Window
   controls rank runners by that window's return (1M / 3M / 6M / 1Y),
   computed by the scoring module from rolling window returns and emitted
   as a `window_ranks` projection field; the frontend only switches its
   sort key. A runner with less history than the window is labelled
   short-history / ineligible and is never ranked on a partial return.
   Window rank awards NO window points. This replaces the interim
   "cumulative rank, window-sliced NAV" semantics in §6.
2. **Season points: return-as-points, and the pool index earns them.**
   For each calendar month, a racer's season points for that month equal
   its monthly net return in percentage points: +3.2% = 3.2 points,
   -1.5% = -1.5 points, 0% = 0 points. This is NOT PointsRuleV1
   (rank points 10 / 6 / 4 / 2 / 1 / 0); it must be implemented as a new
   versioned points rule, with PointsRuleV1 retained unchanged for
   reference. Consequences, to be labelled on-page: (a) ranking by
   season points for a month is identical to ranking by that month's
   return, and ties are equal points; (b) a season total is the
   arithmetic sum of monthly return-points, which is NOT the compounded
   NAV total return and must never be presented as such; (c) the pool
   index earns return-points like any racer — its pool excess is still
   0 by construction, but its absolute monthly return still counts as
   points, so it can rank by its own return.
3. **BYD 515180: option (a), versioned variant.** Admit a BYD-only
   runner (e.g. `byd_cn_runner_v1`) whose thesis states the deviation
   from formal BYD v1.3; the reconciliation delta against formal
   evidence is published. 515180 is never silently dropped while still
   calling the runner "BYD v1.3", and no reference-holding gate is
   introduced without a separate explicit decision and spec change.
4. **Runner identity: new ids.** Every replayed formal strategy gets a
   new runner_id / version, distinct from its formal strategy id.
5. **Season: natural calendar month.** A season is one natural calendar
   month on the track's exchange calendar, settled at the close of the
   last trading session of that month, matching `season_{market}_{YYYY_MM}`
   in code.
6. **Dashboard location: flexible, local first.** The first season is
   built for the local dashboard; publication to hosted Pages is not
   required for the first season and is not authorised by this proposal
   (it remains a separate positioning decision, gated by #1288). "Local
   first" does not mean "local only forever".
7. **Whitelist audit rule, fixed in advance.** Before any CN admission,
   audit every candidate's target symbols against CN 130. Any holding
   outside the pool is handled by the same rule as §10.3: admit a
   versioned variant with the deviation stated, or keep the strategy
   formal-only for the first season. No ad-hoc, per-holding exceptions.

Still open after these seven decisions: PIT certification, corporate-action
source / backfill, CN pool index publication as a versioned artefact,
Decision Feed / Evidence Review implementation, Decision Journal, review
rituals, and the Brief Top 3 vs Scoreboard Top 10 explanation on-page.
