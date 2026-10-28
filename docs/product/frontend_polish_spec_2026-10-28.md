# Frontend polish specification (product / UX)

Status: proposal / spec. Docs only. No runtime, data, registry, workflow, or
frontend code is changed by this document. `research_only=true`,
`trade_ready=false` are unchanged. This spec does not authorise live trading,
public scoreboard publication, automatic execution, a new navigation
structure, a new charting stack, or a scheduler.

Baseline: `main@943594a7` (2026-10-28), after #1312 (first-season six racers,
merged) and #1313 (dnspython patch, merged). Open at drafting time: #1314
(Phase A, US87 pool racer with v2 evidence) and #1307 (bottom-detection
draft RFC, not a racer). Audit evidence: read-only browser audit of the
published site https://liuh886.github.io/alpha_engine/#/app on 2026-10-28
22:22 CST, at Pages version `v0.1.0 · ba5418e`, visiting Overview /
Strategy monitor, Racetrack research (US and CN), Status, and the BYD v1.3
and US x1.3 strategy detail pages, without signing in and without clicking
Refresh / Retry / submit controls. Mobile / tablet layout was NOT audited
and is not claimed here.

Related documents: `docs/product/racetrack_vision_2026-10-27.md` (§13
frontend work design), `docs/product/racetrack_frontend.md` (#1311 landing
status), `docs/product/decision_feed_evidence_review_todo.md` (#1305),
`docs/product/first_season_six_racers_2026-10-28.md` (#1312, §10 decisions),
`docs/product/future_research_agenda_2026-10-28.md` (#1308, item A1).

Implementation note on paths: the local Agent must verify component paths
in the working tree before editing. Paths cited in #1305
(`qlib-dashboard/src/components/DailyResearchBrief.tsx`,
`qlib-dashboard/src/pages/StrategyDetailPage.tsx`) are starting points
from that TODO, not claims verified by reading frontend source in this
spec. If a path has moved, update the spec's reference in the
implementing PR rather than editing blindly.

## 1. Product verdict in one paragraph

The dashboard is precise and heavily caveated for an expert reader, and
that precision is a product asset — it must not be polished away. What
needs polishing is not visual style but language, number reconciliation,
and empty states: a first-time reader currently faces unexplained codes,
three or more date meanings per row, two different "total returns" on one
detail page, a bare "—" with four different meanings, and an entirely
empty Racetrack view whose only clear message is that it does not work on
the hosted site. Polish means making the same honest numbers readable,
not making the product look more confident than its evidence is.

## 2. Principles (acceptance lens for every item below)

1. **One screen, one answer.** Each view must state in its first line
   what question it answers. If a view needs two answers, it needs two
   sections with separate headings, not one dense table.
2. **Every number carries window, basis, and date.** A return, excess,
   drawdown, or point value without all three is incomplete, however
   correct its arithmetic is.
3. **Every code is expanded on first use.** Strategy ids, benchmark
   codes, pool codes, and ticker symbols must resolve to a human-readable
   name where they first appear. Raw identifiers belong in detail pages
   or collapsible "raw fields", never as the primary label.
4. **"—" has exactly one meaning per context, or it is replaced by
   words.** Pre-inception, incomplete-year, not-retained, and
   not-applicable must not share one glyph without a label.
5. **An empty state is an action, not a dead end.** Every empty,
   unavailable, or blocked view must name the next step the reader can
   actually take on that surface.
6. **Do not render controls that cannot work on that surface.** A
   selector or retry button that cannot succeed where it is shown must
   be disabled with a reason, or removed — never left inert.
7. **Caveats stay, but in readable form.** "Not certified", "provisional",
   "not retained", and "local only" are not clutter to delete; they are
   the product's honesty. Polish their wording and placement, not their
   existence.
8. **Desktop-first, as decided.** No mobile-first redesign is in scope.
   Tablet layout is to be verified, not redesigned, after P0/P1.

## 3. Delivery rule

Implement in small PRs, one screen per PR (Overview, Racetrack, Status,
one strategy detail pattern applied to all details), in P0 → P1 → P2
order. Do not bundle P0 fixes for all screens into one large PR: a
regression in one screen must be revertible without losing the others.
Each implementing PR must list, for each item it claims, the acceptance
test from §4–§6 that was run (page, view, and observed result), not just
"polished".

## 4. P0 — misleading or self-contradictory (fix before any visual work)

### P0-1. Date vocabulary, whole site

- **Observed (audit, Overview + details).** BYD v1.3 shows "Observed
  2026-10-27 · target dated 2026-10-27 · formal evidence 2026-10-27"
  plus "Completed market through 2026-10-28"; detail pages add "signal
  through", "observed data through", "settled returns through",
  "provisional mark to market", and "retained settlement", with a single
  strategy showing 2026-10-23, 2026-10-26, 2026-10-27, and 2026-10-28 on
  one screen.
- **Change.** Define exactly three date concepts site-wide and rename
  everything else to one of them: (a) data cutoff — the last date of
  data actually seen; (b) decision applies — the date a target/signal
  applies from; (c) backtest window — the start/end of the formal
  evidence window. Add a one-line date key at the top of Overview and
  at the top of every detail page. Remove or rename "retained
  settlement", "sparse settlements", and "provisional mark to market"
  unless each is given a one-sentence definition where it appears.
- **Acceptance.** Open any strategy detail page: no fourth date meaning
  can be found, and each displayed date can be assigned to (a), (b),
  or (c) without guessing.

### P0-2. Two "total returns" on the US x1.3 detail page

- **Observed.** Headline window "2024-01-02 → 2026-10-27", 68
  observations: strategy 511.23%, benchmark 73.94%, excess 251.41%.
  Chart-period block "2024-01-17 – 2026-10-27", 69 observations:
  strategy 593.70%, QQQ 76.08%, excess 293.97%. Drawdown is likewise
  -21.9% in one block vs -21.86% in the chart. A reader sees two
  different total returns for the same strategy on one page.
- **Change.** Every return block must carry its window and observation
  count in its own heading. Either unify the two blocks to one window
  and basis, or label the second explicitly as "different window, for
  comparison only — not the headline return". Do not silently pick one
  number and delete the other without recording which basis was kept
  and why.
- **Acceptance.** Open US x1.3 detail: each return figure's window and
  count are visible next to it, and no two figures labelled the same
  thing disagree.

### P0-3. BYD chart benchmark / excess contradict the headline

- **Observed.** Headline: benchmark return 510.57%, excess 9.75%.
  Performance-chart period summary: strategy 570.12%, benchmark "—",
  relative excess "—".
- **Change.** Either populate the chart block from the same basis as
  the headline, or replace "—" with a sentence stating why the chart
  block cannot show a benchmark/excess (basis difference, missing
  series, or other reason). A bare "—" that contradicts the page's own
  headline is not acceptable.
- **Acceptance.** Open BYD detail: the chart block either matches the
  headline basis or explains, in words, why it does not.

### P0-4. Fleet "1M" period: differing settlement windows, unexplained

- **Observed.** Switching Performance period to "1M" changes the table
  header to "DRAWDOWN (OBSERVED)" with no explanation, and each row
  shows a different settlement window: BYD 2026-09-28 – 2026-10-26,
  CN_27 2026-08-04 – 2026-09-04 (about two months old), QQQR
  2026-09-28 – 2026-10-26, US x1.3 2026-10-09 – 2026-10-27. BYD excess
  appears as "-0.0%".
- **Change.** Each row must display its own settlement window next to
  its 1M figure. A row whose window is materially older than the
  requested period must be labelled "window expired / stale window",
  not presented as a current 1M figure. Explain the "DRAWDOWN
  (OBSERVED)" header change in the period control's label or help text.
  Normalise "-0.0%" to "0.0%" (signed zero must not appear as a
  distinct value).
- **Acceptance.** Switch the fleet to 1M: every row's window is visible,
  the CN_27 row is visibly flagged as an old window, and no "-0.0%"
  remains.

### P0-5. QQQR fleet excess: bare "—"

- **Observed.** Fleet "All" period: QQQR excess vs qqq is "—" with no
  explanation, while detail pages explain missing metrics (e.g. "The
  governed formal source does not retain this metric; Bundle v2 does
  not synthesize it.").
- **Change.** Apply the detail-page explanation pattern in the fleet
  table itself (short form in the cell or a footnote keyed to the
  cell): state that the excess is not retained and why, rather than a
  bare dash.
- **Acceptance.** Open the fleet: no bare "—" remains in the excess
  column without an adjacent explanation.

### P0-6. Signal-driver tables that prove nothing

- **Observed.** BYD drivers (cutoff 2026-10-27, 8 canonical factors)
  and US x1.3 drivers (cutoff 2026-10-23, 13 canonical factors) show
  EFFECT "neutral" on every row, including bear / negative inputs
  (BYD market state bear, 20D momentum -3.78%, 60D momentum -10.91%,
  252D drawdown -23.52%), while the page conclusion is "Defensive".
  Reference columns carry raw code strings (`strategy.byd.market_state`,
  `market_regime_context`, `momentum_20d_context`, unrounded values
  such as `universe_mean -0.018961871042847633`).
- **Change.** Either (a) show each factor's actual directional
  contribution to the conclusion, or (b) remove the EFFECT column and
  retitle the table "driver factors (for reference; the conclusion is
  not derived from this table alone)". In either case, move raw code
  strings and unrounded values into a collapsed "raw fields" section;
  they must not dominate the primary reading. Round every displayed
  number to the site's standard decimal places (see P2-2).
- **Acceptance.** Open either detail page: a reader can either trace
  how "Defensive" follows from the drivers, or the table explicitly
  says it does not claim to do so — and no raw code string is in the
  primary columns.

### P0-7. Loading artefacts that read as access blocks

- **Observed.** On first load, Overview briefly shows "Loading
  evidence", "Cutoff not declared", and "Formal strategy fleet ·
  0 strategies", then populates to 4. The brief transiently shows
  "Current observations require strategy access. / Sign in or check
  access. Formal evidence remains public." before verified observations
  replace it. Status first load shows a spinner-like "C" and the RDI
  button reads "Reading RDI…" (disabled) before becoming "Refresh RDI".
  No sign-in is in fact required.
- **Change.** Loading states must be skeletons / "Loading…" only: never
  a false zero count, never a "not declared" cutoff, and never an
  access / sign-in message for public evidence. The access message, if
  it must exist for a genuinely gated record, must appear only for
  that record and must name the record.
- **Acceptance.** Hard-reload Overview and Status with a cleared cache:
  no false zero, no "not declared", and no sign-in prompt appears at
  any point before content populates.

## 5. P1 — confusing, not yet misleading

### P1-1. Expand every code on first use

- **Observed.** Fleet and detail pages use `byd_v1.2`, `000300`, `qqq`,
  `US87`, `CN130`, `CSI 300`, `515180`, and long lowercase strategy
  ids (`byd_v1_3_recovery_event_low_vol_confirmation_v1`,
  `qqqi_qqq_tqqq_v4_3`) without expansion. `byd_v1.2` is especially
  misleading: it looks like an index but is a prior strategy version,
  while `000300` / `qqq` look like market benchmarks.
- **Change.** First use, every time per view: `byd_v1.2` → "prior
  version BYD v1.2 (not a market index)"; `000300` → "CSI 300
  (000300)"; `qqq` → "QQQ ETF"; `US87` → "US 87-stock pool";
  `CN130` → "CN 130-stock pool"; `CSI 300` ↔ `000300` equivalence
  stated once where both appear (fleet vs Racetrack). `515180` gets
  its fund/ETF name; fleet tickers get company names or a hover
  expansion at minimum on detail pages. Long strategy ids stay only
  as secondary / URL identifiers, never as the primary row label —
  display names are the primary label.
- **Acceptance.** A reader who has never seen the codebase can expand
  every code on Overview, Racetrack, and one detail page without
  leaving the page.

### P1-2. One sort order, everywhere

- **Observed.** Brief order: BYD, CN_27, US x1.3, QQQR. Fleet order:
  BYD, CN_27, QQQR, US x1.3. No rule is stated.
- **Change.** Fix one rule (recommended: market first, then display
  name) and apply it to brief, fleet, Status observations, and
  Racetrack leaderboards. If any view must differ, it states its rule
  in its heading.
- **Acceptance.** The four strategies appear in the same order on
  Overview brief, fleet, and Status.

### P1-3. "Selected evidence" rail card must mean something

- **Observed.** After visiting a detail page, the rail "SELECTED
  EVIDENCE" changes (BYD v1.3 → US x1.3), but the Overview fleet is
  not filtered — it reads as a selection the user never made.
- **Change.** Either make the rail card actually filter the fleet
  (and show a visible "filtered by X — clear" state), or rename it
  "Recently viewed" and remove any selection implication.
- **Acceptance.** Clicking through a detail and back: the rail either
  filters visibly or is plainly labelled as history, never as an
  unexplained selection.

### P1-4. Navigation naming

- **Observed.** Rail item "Overview", page title "Daily Research",
  detail back link "← Overview" — three names for one layer.
- **Change.** Use one name for the layer everywhere, and make the
  detail back link read "← Back to fleet". The in-page toggle
  "Strategy monitor / Racetrack research" keeps its current clear
  pressed state.
- **Acceptance.** A reader can say, in one sentence, where "back"
  goes from any detail page.

### P1-5. Racetrack hosted empty state (the most important P1 item)

- **Observed (hosted Pages).** The view correctly states "Research
  projection unavailable — Open this Dashboard on localhost to read
  local research projections. Hosted Console pages do not publish this
  evidence." and "The four-strategy monitor remains independent."
  But the market selector (US · US87 / QQQ, CN · CN130 / CSI 300)
  remains enabled and changes the URL (`&raceMarket=cn`) without
  changing the message, and a "Retry projection" button sits beside
  it, implying retry might succeed where the message says it cannot.
  The header still promises "Published local research evidence, with
  its original dates and limitations", yet no dates, NAV, or figures
  are shown. No hosted action is offered inside the card; returning
  to the monitor requires the toggle above.
- **Change.** On the hosted surface only: disable the market selector
  with a reason ("market selection applies to the local projection"),
  remove the Retry button (or replace it with a disabled control
  labelled "retry applies to local only"), and put two real actions
  inside the empty card: "Back to Strategy monitor" and "How to open
  locally" (the exact commands and path, not just the word
  "localhost"). State the US87 / CN130 / CSI 300 ↔ 000300 equivalence
  from P1-1 in this card. Do NOT claim any local state on the hosted
  page (e.g. do not say "locally there is now 1 racer"): the hosted
  page cannot know local state, and claiming it would be stale on
  arrival.
- **Acceptance.** Open the hosted Racetrack view: no enabled control
  implies an action that cannot succeed there, and the card itself
  offers a way back and a way to open locally.
- **Local counterpart (to verify with #1314, not on Pages).** When
  the Phase A pool racer lands locally, the local Racetrack view must
  show it labelled "internal benchmark, also racing" with QQQ as
  "reference only, not racing", per #1312 §10 and #1314 — the hosted
  empty state must not be used as evidence for or against the local
  view.

### P1-6. Status page: stop duplicating Overview

- **Observed.** Status "Current observations" repeats the four brief
  rows almost verbatim; it is unclear what Status adds beyond the
  snapshot and RDI sections. "Operating Status" appears twice (page
  header and main heading). "RDI" is never expanded. Snapshot
  timestamp "Generated 2026-10-28T04:30:34Z" is UTC with no local-time
  conversion. Horizon buttons "7 / 14 / 28 trading sessions" do not
  filter the chart — all three horizons are shown at once and
  selecting 14 only highlights one detail row. Recovery links "Data
  refresh" and "Decision delivery" give a non-operator no next step.
  RDI price data end 2026-06-25, four months before the 2026-10-27
  strategy cutoff — stated, but easy to miss.
- **Change.** Status keeps only: data snapshot (with local time
  alongside UTC), RDI section (with RDI expanded on first use and the
  2026-06-25 cutoff visually adjacent to any RDI figure), and system
  health. Observations move to a link ("See current observations on
  Overview") instead of a duplicated table. Fix the duplicated
  heading. Make the horizon control either truly filter the chart or
  present the three horizons as a labelled comparison table, not as
  fake filter buttons. Recovery text must name the next step for a
  non-operator reader (e.g. "no action needed; observations remain
  readable" where that is true) instead of operator-only workflow
  names.
- **Acceptance.** Open Status: no duplicated brief table, one
  "Operating Status" heading, RDI expanded, snapshot time in local
  time, and horizon controls that do what they claim.

### P1-7. Collapsed explanations on Stale rows

- **Observed.** "Decision evidence" and, for Stale rows, "Recovery
  steps" are collapsed by default, so the explanatory text is hidden
  exactly where the reader most needs a reason.
- **Change.** For any row in a non-OK state (Stale, Blocked, attention
  needed), its reason and recovery steps are expanded by default or
  carry a visible badge ("reason hidden" is not a state). OK rows
  may stay collapsed.
- **Acceptance.** Open Overview with a Stale row present: its reason
  is visible without an extra click.

## 6. P2 — density and readability (after P0/P1)

### P2-1. Fleet and detail tables

- Fleet: six columns (strategy, return, excess/benchmark, drawdown,
  latest signal, applicable) with truncated signal text in the US row.
  Move long ids out of the primary columns (see P1-1); signal text
  must not truncate mid-sentence without an expansion control.
- Detail target table (US x1.3): 21 ticker rows under "US Top-15
  rebalance" — 15 current holdings at 6.7% each mixed with former
  holdings at 0.0% target, with no statement that the table is the
  union of current and target holdings. Split the table into
  "current holdings" and "former holdings (0.0% target)" sections
  with a one-line union explanation, and add company names or
  expansions (P1-1).
- "Source record" link appears only on the US detail, not on BYD's,
  with no indication of its destination. Either add it consistently
  with a destination label, or remove it from both.

### P2-2. Number formatting, whole site

- Round every displayed number to one consistent decimal rule per
  metric type. In particular, remove raw unrounded decimals from
  prose (observed: "net return -0.2310626845334285, relative excess
  -0.20921387779521705" in the US research-tracking assessment, and
  reference-column values with 16+ decimals in driver tables).
  "IC Not computed" / "ICIR Not computed" are well explained where
  they appear; "Rank IC 0.052" sitting beside them needs a
  one-sentence interpretation or removal.
- Monthly Returns table (2019–2026, Jan–Dec + Total, 14 columns of
  small coloured cells): mark the incomplete 2026 row ("Nov/Dec —
  year incomplete") instead of sharing the pre-inception "—" glyph
  (see principle 4), and densify equity/drawdown chart axis labels
  (observed sparse labels: "Nov 19 Aug 21 May 23 Feb 25 Oct 26").
- "Governed performance methodology" block: move untranslated code
  values (`session_close_t`,
  `next_common_independently_confirmed_eligible_open_t_plus_1`,
  `governed_adjusted_common_open`,
  `sum(abs(target_weight - previous_weight))`) into a collapsed
  "methodology (raw)" section; the primary text must be prose.

### P2-3. Repeated chrome

- "Published operations checked. Each record retains its own evidence
  cutoff." strip (with "Refresh operations") appears on every view
  without a date, count, or result. Either give it a date/count/
  result, or show it once per session, not per view.
- "RESEARCH ONLY" appears in the header, context bar, rail, and
  detail pills. Keep it in the header and on first-load context only;
  remove the per-pill repetition.
- Collapsed rail: expand control is a small "»" at the bottom left,
  and "SELECTED EVIDENCE" / version are hidden when collapsed. Keep
  the version visible in collapsed state and make the expand target
  at least as discoverable as the collapse target.

### P2-4. Verify, do not redesign, tablet layout

- Tablet layout was not audited. After P0/P1, verify the fleet table,
  Racetrack chart + leaderboard, and detail tables at tablet width
  for truncation and wrapping only. No mobile-first redesign, no new
  breakpoints as a goal in themselves; record any truncation found
  as a P2 bug with a screenshot reference.

## 7. Explicit non-goals (do not let polish drift into these)

- No new primary navigation, no new route hierarchy, no renaming of
  the product or its research-only positioning.
- No new charting stack; Lightweight Charts 5.2.1 stays pinned with
  attribution, per #1311 and vision §13.
- No public scoreboard, no publication of racetrack projections to
  hosted Pages, no backend, no scheduler, no database, no automatic
  source refresh. The hosted Racetrack empty state is a boundary to
  preserve, not a bug to "fix" by publishing.
- No removal of caveats (PIT-not-certified, provisional season,
  not-retained metrics, local-only) for visual cleanliness.
- No auto-trading, execution, or recommendation language. The
  disclaimer "Model portfolio simulation · Returns are not an
  investment recommendation" stays visible under the fleet table.
- No synthetic / demo racers in a real season view. Synthetic
  fixtures stay in tests and screenshots, labelled as such, as in
  #1311.
- No change to scoring semantics in this spec. In particular,
  return-as-points (§10 of #1312) and PointsRuleV1 are not to be
  altered, merged, or relabelled by a polish PR; polish only how
  points, ranks, and returns are displayed and explained.
- #1307 (bottom detection, draft RFC) is not a racer and gains no
  frontend surface from this spec. #1305 Decision Feed / Evidence
  Review implementation (two small PRs on existing components) is a
  separate track; this spec must not duplicate or pre-empt it, but
  P1-7 (expanded Stale reasons) is the minimum that must not wait
  for #1305.

## 8. Acceptance checklist for the whole polish (run at the end)

1. Overview: date key present; brief and fleet in the same order;
   no bare "—" in excess; 1M windows visible per row with old
   windows flagged; Stale reasons visible without a click; no false
   loading artefacts on hard reload.
2. Racetrack (hosted): selector disabled with reason, no Retry
   implying hosted success, back-to-monitor + local-open actions
   inside the card, code equivalences stated.
3. Racetrack (local, with #1314): pool racer labelled "internal
   benchmark, also racing", QQQ "reference only, not racing",
   window ranks display-only, return-points labelled as monthly
   return-points (not compounded return).
4. Status: no duplicated brief table, one heading, RDI expanded,
   snapshot in local time, horizon controls honest.
5. BYD detail: chart benchmark/excess reconciled with headline,
   515180 named, driver table either explanatory or explicitly
   non-deriving, methodology code collapsed.
6. US x1.3 detail: one reconciled total-return basis (or two
   labelled windows), target table split current/former, all
   numbers rounded to the site rule, Rank IC interpreted or removed.
7. Whole site: every code expanded on first use per view; every
   "—" labelled or replaced; no control implies an action it cannot
   perform on that surface.

## 9. Review focus

Reviewers are asked to check, in order: (1) whether any P0 item
misstates the observed evidence (page, figure, or label) — audit
evidence is Pages at ba5418e, not local; (2) whether any item
secretly changes a scoring, derivation, or publication rule (it must
not — polish is display and explanation only, except where an item
explicitly says "label" or "explain"); (3) whether the P0 → P1 → P2
order is right, and whether any P1 item should move to P0; and
(4) whether the Racetrack hosted empty state (P1-5) is correctly
scoped as a boundary, not as a missing feature to be filled by
publishing projections.
