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

Treat **2026 July–October** as an already observed, hypothesis-motivating,
retrospective descriptive stress case, never independent prospective/OOS
evidence. Do not tune thresholds to those episodes. Genuine prospective
observation starts with future completed sessions after a newly frozen
protocol/source/as-of, with 7/14/28-session outcomes eligible only when mature.
This 2026-10-30 clarification corrects the former prospective label; it does
not retune a frozen experiment or certify historical PIT event coverage.

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

## Product increment · 2026-10-24

Owner requested product development after synchronizing Phase 2 (#1274).
Product purpose: help a researcher understand which known risks deserve attention,
over which horizon, and what evidence supports that interpretation. Success is
an explainable change in the research decision, not a larger catalogue of scores.

The first increment supersedes the foundation PR's no-consumer restriction only
for a read-only **Operating Status** research briefing. It shows the dated review,
source cutoff, uncertified event families, unapproved sector candidates and the
next blocking evidence. It neither changes strategy health nor creates navigation.

Price-only 7/14/28-session severe-loss frequencies appear in an optional table,
with exact group definitions, overlapping sample counts and limitations. They
are historical associations, separate from RDI and current probabilities. Never
show event counts as zero when archival coverage is absent. The underlying source
blob and matching reviewed reports must agree before any statistics are exposed.
Changed source/contradictory report suppresses statistics; missing or invalid
evidence shows unavailable. Refresh rereads assets and never runs research.

Projection: `briefing.build_research_briefing`, exposed through the existing
`phase2_audit --product-briefing` entrypoint and existing operations asset sync.
Read-only generation hashes evidence and reads inventories; it imports no model
or provider, trains nothing, adds no store or workflow. The projection is disposable.

Next increments in order:

1. Certify a narrow reusable event-family history through existing company-event
   adapters and record explicit coverage/availability. Verified empty and unknown
   must remain different. Renew price/calendar evidence through the study period.
2. Explain changes since a previous exact cutoff: new story, revision, expiry,
   source outage; each links to underlying source evidence. Distinguish risk,
   clearing and policy stages; never cancel across unrelated sectors.
3. Display a forward-known event window on genuine 7/14/28 XSHG sessions,
   with source drill-down and explicit gaps. Display descriptive counts only
   where coverage supports them, before considering a composite risk level.
4. Run frozen purged multi-episode evaluation and show incremental utility over
   price-only baselines, including failures. Forecast probabilities require
   calibration; strategy effects require existing promotion and owner approval.

Acceptance: a first-time reader can identify the dated scope, why no current
assessment exists, the next evidence needed and the difference between a price
comparison and an event forecast. Source mismatch, missing asset, timeout and
retry must be readable on desktop and mobile without affecting valid strategies.

Verified for this increment: 29 RDI Python tests, 14 Pages dependency tests,
208 frontend tests, TypeScript/ESLint/Ruff/build/bundle budget and nine focused
browser checks across desktop, tablet and mobile passed. Governance retained
39 workflows with zero violations. No real-data event backtest or calibrated
forecast was added; the remaining data/evaluation gates above remain open.

## Frontend product specification · 2026-10-24

Owner explicitly requested a product-manager design and frontend-agent implementation.
This increment replaces the initial RDI status card inside Operating Status; it
does not add a research navigation destination. The product question is: **can I
interpret A-share event risk at this cutoff, what can the available evidence
actually establish, and which missing evidence prevents a stronger conclusion?**

### Reading order and layout

1. **Assessment first.** Header identifies RDI / A-share risk research and its
   unvalidated research state. A compact assessment explains unavailable current
   inference; missing observations never become a low-risk score. Keep reviewed
   price cutoff and review date distinct, readable and close to the assessment.
2. **Available historical evidence.** Show the 7/14/28-session price-only control
   as a directly labelled paired horizontal-bar comparison, visible by default.
   The title and surrounding copy must say historical, descriptive, not an RDI
   forecast. Compare frequency of close-to-close loss >=5% when preceding
   60-session drawdown >=10%, against other price states. No net-P&L implication.
3. **Inspect a horizon.** Default selection is 14 trading sessions. Three compact
   keyboard/touch controls select 7, 14 or 28; keep all three horizon comparisons
   visible with a common zero-based 0–100% scale. Selection highlights one group
   and updates the exact two frequencies, sample counts and percentage-point
   difference below it. No thresholds, source dates or data change on selection.
   Essential numbers are directly labelled, never hover-only. A native text/table
   alternative exposes the same underlying values and overlapping sample counts.
4. **What blocks a stronger assessment.** Concise next-evidence text prioritizes
   a narrow certified event history, study-period prices/calendar and independent
   validation. The source inventory can be expanded and filtered by all / needs
   integration; this filter is about adapter readiness, not historical certification.
   Show a count and a meaningful empty state. All source rows keep their actual
   certification state. Sector candidates remain explicitly unapproved.
5. **Trace evidence on demand.** Source links, protocol and hashes sit in a
   separate technical disclosure, keeping the default view readable. Preserve
   immutable commit links and exact source identity, without large raw datasets.

Large screens may place assessment/coverage facts and the historical comparator
side by side inside the existing Status section. Mobile stacks assessment,
cutoffs, comparator, selected-horizon detail, then optional source/provenance
disclosures. No horizontal document scroll at 360px; controls have >=40px hit
targets; labels wrap; light/dark modes retain readable contrast.
Exact frequencies and sample counts share aligned rows on narrow screens even
when one group label wraps onto two lines.

The Status header offers a **RDI research** in-page jump that scrolls and focuses
the section heading without changing the route, fetching evidence or adding a
navigation destination. This keeps the research surface discoverable below the
independent daily-operations content, including for keyboard users.

### State and engineering contract

- One tiny React-owned DOM/SVG chart (six bars); no new dependency or generic
  chart framework. Neutral context, blue comparison accents and separate focus
  treatment; amber is reserved for evidence availability. Color is redundant
  with explicit group labels. No animation needed; respect reduced motion.
- Reuse `RdiResearchBriefing` and its validated asset. Do not modify the research
  schema, registry, score, event history, evaluator or backend in this increment.
- Horizon/source filter are ephemeral local UI state, not persisted or URL-backed
  (there is no shareable current-risk claim). Refresh rereads evidence only.
- Initial load is explicit. Missing/timeout state has a local **Retry RDI** action
  which rereads only RDI; the existing Status refresh also works. Abort superseded
  requests and ignore late responses. Never redisplay old statistics as new.
- Evidence mismatch hides the entire chart and exact historical statistics,
  retaining clearly dated review metadata and its mismatch explanation.
- No fabricated risk meter, event timeline, sector heatmap, probabilities, trade
  recommendations, disabled pretend controls or notification CTA.

Acceptance: inspect all three horizons with keyboard/touch and matching values;
filter source inventory without implying complete coverage; open immutable
evidence links; recover locally from a failed read without strategy refresh;
preserve chart suppression on mismatch and ignore timed-out late responses.
Verify desktop, tablet and mobile plus narrow-width/dark-mode rendering, unit
state tests, TypeScript/lint, production build/budget and focused browser checks.

Implemented by the delegated Frontend Developer agent and reviewed by the PM.
Acceptance passed: 211 frontend tests; TypeScript and ESLint; production build
and budget; nine focused desktop/tablet/mobile browser checks. PM independent
1440px desktop and 360px light/dark checks verified actual bar geometry,
frequencies, sample counts, aligned values, keyboard selection, source filtering,
immutable links and no extra RDI reads. Screenshot review caught a window-scroll
regression and wrapped-label misalignment; both were corrected and browser/DOM
geometry checks rerun successfully. Historical-data/predictive gates remain open.

### Follow-up review: refresh continuity and keyboard recovery

A subsequent user-requested acceptance pass reproduced two interaction defects:
refresh remounted the 28-session inspection at the default 14 and closed/cleared
source disclosures/filter; keyboard retry unmounted its focused action and left
focus on BODY. Retain only horizon/filter/disclosure UI state in the parent across
reads. The underlying superseded statistics must still be absent while loading,
unavailable or source-inconsistent. Recovery uses newly verified data with the
previous inspection state. Keep a stable local read action through loading and
recovery, guard repeated pending activations and never restore focus over a user
who has moved elsewhere. This adds no persistence store or backend action.

Verified fixes: 216 frontend unit tests, TypeScript/ESLint/build/budget and twelve
desktop/tablet/mobile browser checks passed. Independent reproduction retained
28 sessions, filter and open disclosures; retry focus remained on the same
button and repeated pending activation made no extra request. Six desktop/mobile
fault cases (mismatch, invalid research boundary, invalid JSON) continued to hide
old statistics and recovered correctly. Narrow light/dark geometry and screenshot
checks passed. No unresolved frontend blocker was found in this acceptance pass;
the historical-data and predictive-validation gates above remain open.

## 2026-10-31 reviewed price evidence rebinding

The existing Status RDI section now consumes the separately reviewed versioned
price reconstruction through 2026-10-30 (5,238 post-inception XSHG rows).
`rdi_product_review_2026-10-31.json` pins the reconstruction receipt, source
manifest/archive identity, frozen repair contract, source/sector inventory and
protocol. It does not rerun a source decoder, provider or evaluator on a status
read. Schema 1.1 distinguishes retained historical Git lineage from the new
reconstructed output SHA-256 and links the reviewed source manifest.

Historical comparison details expose each horizon's last mature observation,
actual label end and immature tail. Missing or contradictory inputs hide
statistics; no legacy receipt fallback is available. The original failed
append-only preflight remains independently replayable from its old source.
This is a dated, descriptive evidence update, not Step 4 research-assessment
promotion. Event qualification remains 0/10, status stays `not_validated`, no
score/probability forecast, prospective validation or strategy overlay is added.

### Dependency maintenance and replay provenance

The captured `uv_lock_git_sha256` remains immutable source-environment
provenance. A later unrelated security dependency update may use another lock.
Offline replay still requires the exact source/API/adapter identity, original
response hashes, and byte-identical normalized CSV; changed economics cannot
pass by changing lock metadata. A new replay reports its own
`replay_uv_lock_git_sha256` and `replay_lock_matches_capture`. A different lock
is not claimed as reproduction of the original environment. Old source
contracts, receipts and product review bindings are preserved; no source replay
is introduced into the Status reader.
