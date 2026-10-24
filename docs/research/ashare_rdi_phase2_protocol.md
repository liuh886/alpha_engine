# A-share RDI — Phase 2 research protocol and evidence-readiness review

**Review date:** 2026-10-24 | **State:** research prototype, **not validated**.

## Execution already implemented

- `src/research/ashare_rdi/coverage.py` audits a per-session, per-family
  **archived** source-completeness statement. Absent/partial/unverified events
  are `unknown`, not zero. No weights are inferred.
- `src/research/ashare_rdi/phase2.py` creates as-of-known risk/clearing
  concurrency and 60-session price-regime candidate features; computes CSI300
  7/14/28-trading-session realized labels. It evaluates one **blocked**
  chronological 70%/30% train/test split with end-date purging and compares
  constant event probability, price-only and price+event logistic diagnostics.
  Results remain `diagnostic_only`, not predictive evidence for RDI.
- `src/research/ashare_rdi/sector_etfs.py` guards ETF lifecycle, adjustments,
  history and liquidity, without changing formal strategy/reference registries.
- `src/research/ashare_rdi/phase2_audit.py` prints a non-network readiness
  receipt with explicit **blocked** state when PIT source coverage is missing.

To run on the existing repository price file:

```bash
uv run python -m src.research.ashare_rdi.phase2_audit \
    --benchmark-csv data/csv_source/000300.csv
uv run pytest tests/test_ashare_rdi_contracts.py tests/test_ashare_rdi_phase2.py -q
```

## Verified repository inventory and current blocker

The existing CSI300 daily CSV has **5,934 rows** spanning
**2002-01-04 through 2026-06-25**. Discard its pre-inception backfill:
**5,152 rows** remain from index inception **2005-04-08** through
**2026-06-25**. This cannot test July–October 2026 until more data are
sourced, validated and appended under existing provider discipline.

Canonical reference `CSI300` is **index** `000300.SH`, never a tradable
ETF. The existing `515180.SH` verified research bundle is a broad dividend
ETF, **not** an industry ETF. Price inventory is not a validated as-of market
data production snapshot. Receipt:
`docs/evidence/ashare_rdi_phase2/csi300_input_readiness_2026-10-24.json`.

The source inventory `configs/research_experiments/ashare_rdi_phase2_sources.yaml`
lists ten families and explicitly labels all archived historical PIT
completeness **unverified**. Canonical `src/data/company_events` adapters
supply partial disclosure inputs for earnings, holdings and unlocks; they do
not furnish complete historical first-availability and absence evidence. A
CNINFO disclosure date cannot be replaced with a later retrieval timestamp,
nor can a 2026 download retroactively prove a historical data feed.

**Result:** no full composite scores, predictive accuracies, sector ETF
backtests or verified risk-index results can yet be claimed. Do not invent
historical news/events to force a complete matrix.

## First real-market price-only control (NOT an RDI backtest)

To avoid waiting for non-existent historical news coverage, Phase 2 records a
fully reproducible **descriptive-only** CSI300 index control. Run:

```bash
uv run python -m src.research.ashare_rdi.price_baseline \\
    --prices data/csv_source/000300.csv
```

Using a **predefined** prior-60-session drawdown threshold of -10%, the
historical frequency of close(t)->close(t+h) losses at least -5% is:

| h trading sessions | In >=10% trailing drawdown | Other states |
|---|---:|---:|
| 7 | 13.91% (1,258 overlapping samples) | 6.74% (3,828) |
| 14 | 17.25% (1,258) | 11.99% (3,821) |
| 28 | 23.21% (1,258) | 20.62% (3,807) |

This is a correlation on reused overlapping time windows. It **does not**
establish predictive significance or robust event-risk density, nor
does it address the October 2026 collapse; prices end June 25.
It suggests severe downside and direction deserve separate labels, not
that a fixed drawdown rule should control position sizing. Raw output with
source Git blob anchor is retained at
`docs/evidence/ashare_rdi_phase2/csi300_price_only_descriptive_2026-10-24.json`.

## 7 / 14 / 28 session research design

Observation time is the **completed CN exchange close** `t`. Known announced
future events may affect the forecast only if the announcement's
`available_at` is no later than the close of t. Never include later event
revisions, outcome prices or late-ingested facts.

CSI300 labels: close(t) -> close(t+h), for each h in **7/14/28 distinct XSHG
sessions**; directional *index* research, not P&L. ETF research uses the
existing next-open(t+1) -> close(t+h) gross-return helper only after ETF
source admission. Fees/slippage and distribution adjustment are mandatory
for any separately authorized tradable ETF simulation.

Preliminary **not fitted** raw features: average overlapping distinct known
risk stories per forward-known trading session, clearing stories separately,
and realized prior-60-session drawdown. Deduplicate by real-world story ID;
distress and clearing in different industries cannot silently net out.

Evaluation functions implement an initial fixed chronological split with
**train labels purged when their actual end date overlaps the test start**.
This alone is not sufficient to establish significance, since daily forward
labels overlap each other. Before any predictive conclusion, introduce
pre-registered walk-forward folds, independent episode/block bootstrap,
confidence intervals, calibration curves, baseline controls, and
multiple-testing checks. Realized outcomes cannot be features.

Compare **B** (price-only bear-regime), **E** (unweighted event), and **E+B**
incrementally. Then test S/C/P/G individually under audited coverage. Compare
conditional downside hit rates, index forward return, worst intrahorizon
excursion, AUC (only when both classes occur), Brier scores, calibration and
incremental out-of-sample utility. A favorable backtest after tuning on
2026 July–October is not independent evidence. Multiple adverse risk
episodes, including bullish and bearish contexts, are required.

## Sector research candidates, not registered

`ashare_rdi_phase2_sector_candidates.yaml` records semiconductor
`512480.SH`, banks `512800.SH`, real estate `512200.SH`, liquor
`512690.SH`. Sources:

- SSE fund facts for 512480, including 2019-06-12 listing:
  https://www.sse.com.cn/disclosure/fund/announcement/c/new/2025-04-09/512480_20250409_VFF0.pdf
- SSE fund facts for 512800, including 2017-08-03 listing:
  https://www.sse.com.cn/disclosure/fund/announcement/c/new/2025-03-20/512800_20250320_GZLN.pdf
- Issuer for 512200, fund inception 2017-08-25:
  https://www.nffund.com/new/personal-financing/detail.html?fundCode=512200
- Fund detail for 512690, fund inception 2019-04-04:
  https://fundf10.eastmoney.com/jbgk_512690.html

Fund inception does not establish exchange listing. Actual price, adjustment,
liquidity, tracking error and point-in-time sector exposure are all pending.
All four instruments remain research-only and **unapproved**.

## Deferred items / falsification checks

1. Audit historical event completeness; issue explicit *not identifiable*
   results where record coverage is incomplete. No proxy zero-filling.
2. Verify 2026-07 onwards index prices and daily calendar/adjustments.
3. Confirm a small sector ETF basket and source-hash archived daily OHLCV.
4. Resolve time windows, risk decay, sector weighting and correlations using
   training evidence only. Validate the 3/4 risk count threshold as a hypothesis.
5. Apply full multi-fold rolling walk-forward and episode-block confidence
   intervals; preserve failed studies, not only positive discoveries.
6. Leave policy rescue rumors out of automatic clearing offsets and distinguish
   announced, executed and *verified* sector restructuring.
7. Only consider a 0–100 score after calibration, and any official strategy
   risk overlays only after the existing EvidenceBundle promotion gate and
   explicit owner approval.

No UI, alerts, new scheduler, automatic strategy promotion or live trading.
