# RDI progress and next evidence — 2026-10-31

RDI remains research-only, unvalidated, and outside the four active strategies.
This is the implementation follow-up to [#1324](https://github.com/liuh886/alpha_engine/pull/1324)
and [#1272](https://github.com/liuh886/alpha_engine/issues/1272).
It records source failures rather than retroactively claiming July–October warnings.

## Milestones

| Milestone from #1324 review | Actual state |
| --- | --- |
| M1: renewed price evidence and replayable splice | **BLOCKED**: preflight implemented; no splice/baseline recomputation admitted |
| M2: ten-family eligibility audit | Table below published; **0/10 historically PIT-qualified**; inventory is not a coverage certificate |
| M3: select first family and freeze scope | NOT_STARTED; neither earnings nor unlocks silently selected |
| M4: freeze prospective evaluation spec | NOT_STARTED; no prospective clock is claimed |
| M5: publish frozen evaluation evidence | BLOCKED by upstream source/spec gates; no predictive result |

## Price renewal: failure is now reproducible

Run from the reviewed revision in a full Git checkout (the retained Git blob
must be available). Existing package lock and explicit XSHG range are used:

```powershell
uv run --frozen --extra dev python -m src.research.ashare_rdi.phase2_audit `
  --price-renewal-audit --as-of 2026-10-30 `
  --output artifacts/rdi/csi300-price-renewal-preflight.json
uv run --frozen --extra dev pytest tests/test_ashare_rdi_contracts.py tests/test_ashare_rdi_phase2.py -q
```

The [dated preflight receipt](../evidence/ashare_rdi_phase2/csi300_price_renewal_preflight_2026-10-31.json)
binds the original reviewed Git blob, both projection hashes, provider/source
hash claims, implementation hash, reference registry, package lock and calendar
version. It does not treat a public chart projection as raw-provider certification.

- Original RDI source: 5,152 eligible post-inception rows, 2005-04-08–2026-06-25.
- Governed CSI300 chart candidate: 1,410 rows, 2021-01-04–2026-10-30;
  complete for its declared XSHG range. It supplies 85 possible append rows.
- 1,324 shared dates were compared across open/high/low/close. Audit resolution
  is 0.01 index points (legacy float32/two-decimal vs current three-decimal
  observations); it is not permission to alter economic observations.
- Original history lacks **2026-06-23**, an XSHG trading session.
- At **2026-06-22**, old/current close differs by **10.846964843750357** index
  points and high by **5.451429687500422**. Remaining overlap is within the stated
  audit resolution. Do not increase tolerance to hide this discrepancy.
- The library's moving default history start excludes 2005 on this machine.
  The preflight explicitly requests the complete historical calendar range;
  unsupported ranges still fail closed instead of using weekdays.

Consequently, an append-only renewal cannot currently establish a complete
7/14/28-session chain. Both the missing bar and conflicting existing row need
source-governed disposition before recomputation. The command is a **read-only
preflight**, not a splice writer or admission API: even clean overlap remains
blocked until original provider bytes and index price basis are separately
verified. Old CSV bytes, receipts, source metrics and the Status briefing
binding are unchanged. Neither all October labels nor price-layer readiness
is claimed.

## Ten-family historical PIT eligibility table

Authority: `configs/research_experiments/ashare_rdi_phase2_sources.yaml`.
Every row has **UNVERIFIED historical coverage** and **no certified absence
matrix**. Existing adapters can normalize individual claims; they do not prove
that every event available at each historical cutoff was captured.

| Family | Existing source path | Availability evidence required | Gap / leakage risk | Verdict |
| --- | --- | --- | --- | --- |
| holiday_positioning | `src/research/market_session_clock.py` | Historical exchange calendar announcement/version | Calendar alone does not establish pre-holiday positioning or selling | UNKNOWN; calendar only |
| earnings_calendar | `src/data/company_events/ashare_earnings_events.py` | Original filing public time plus verified availability; announced future schedule separately | Actual forecast/preliminary filing date is not an advance earnings schedule; later retrieval cannot prove old availability | UNKNOWN; partial adapter |
| holding_change | `src/data/company_events/ashare_holding_change_events.py` | Original planned/executed change announcement, revision and first-availability evidence | Announced sale versus executed sale; duplicated or incomplete archive | UNKNOWN; partial adapter |
| restricted_unlock | `src/data/company_events/ashare_primary_announcements.py` | Original unlock announcement/public availability and effective session | Potential supply is not actual selling; incomplete archive or late revisions | UNKNOWN; partial adapter |
| ipo_refinancing | Not integrated | Exchange/CSRC disclosure and first availability, effective schedule | Retrospective issue date substituted for previously known schedule | UNKNOWN; missing integration |
| macro_external | Not integrated | Official release timestamp, vintages and provider latency | Revised releases or later external-news knowledge | UNKNOWN; missing integration |
| sector_leader_distress | `src/data/fundamentals/ashare_public_financials.py` | PIT statement/debt-notice availability plus frozen peer mapping | Financial fields alone do not establish sector-wide distress; survivorship and revised statements | UNKNOWN; partial source |
| sector_clearing | Not integrated | Original evidence distinguishing announced/approved/executed/verified stages | Announced restructuring mistaken for completed capacity removal | UNKNOWN; missing integration |
| policy_support | Not integrated | Official announcement, implementation and independently verified effect times | Rumor or later market outcome treated as contemporaneous clearing | UNKNOWN; missing integration |
| good_news_response | `src/data/company_events/ashare_earnings_events.py` | PIT expectation vintage, announcement availability and then-observed response | Missing expectations; future label or reaction leaks into pre-announcement feature | UNKNOWN; partial source |

This table audits eligibility requirements, not historical event counts. Unknown
is never encoded as zero. A single family's certificate would not qualify the
full ten-family study. Sector ETF admission remains separate and unchanged.

## Next smallest deliverables

1. Retrieve exact original CSI300 provider bytes matching the candidate's source
   digest and manifest; establish unadjusted index-point semantics, source
   availability and the June 22/23 discrepancy. Preserve the reviewed 2005-start
   blob and all failed evidence. If it requires historical repair, propose a
   versioned repair with exact changed rows and provenance; do not silently
   bypass #1324's append-only contract or overwrite the old artifact.
2. After that disposition, renew and recompute fixed B-only descriptive states
   and 7/14/28 labels. Report mature label ends and insufficient tails at the
   actual cutoff. July–October 2026 stays retrospective, not OOS/prospective.
3. Select earnings windows or unlocks with the operator and freeze a narrow
   source/coverage/time/absence contract before certifying it. This table does
   not authorize event ingestion or select a family.
4. Freeze the prospective spec independently before future-session recording;
   no earlier date can be backdated into a prospective clock. No new scheduler,
   registry, UI, score, alerts or strategy promotion is introduced here.

`research_only=true`, `trade_ready=false`; full event study stays BLOCKED.
