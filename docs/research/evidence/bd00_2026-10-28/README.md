# BD-00 dated source survey

Survey complete; experiment readiness **BLOCKED**. This is an inventory of
`main@ba5418e048e0f20d8d8dc6eb5ba1ff72e76b2515` through 2026-10-27, not a
training/OOS selection, historical PIT certification or bottom-detection result.
`research_only=true`, `trade_ready=false`.

## Reproduce

From the repository root with the existing governed Python environment:

```powershell
uv run --frozen python docs/research/evidence/bd00_2026-10-28/reproduce.py --output C:/Temp/bd00-new-survey
uv run --frozen alpha research study list
```

Use a fresh output directory: the script refuses to replace evidence. It calls
the existing `get_research_data_slice` and `study_catalog`, reads existing source
files, and does no provider refresh, model execution or forward-label build.
Source files and the script have SHA-256 identities in [survey.json](survey.json).
The source commit supplies reproducible prices/configs/code; the PR supplies
this script. It checks tracked inputs against that fixed baseline and refuses
changed source bytes, rather than relabelling them with a moving `origin/main`.
Receipt `generated_at_utc` changes on reproduction, while identical
requests/sources retain the same request/data hashes.

## Observations and blockers

- All 87 declared candidates were audited, with QQQ audited separately as a
  benchmark reference. No symbol was omitted, substituted or promoted to a
  candidate role. All 88 source-byte hashes match their market catalog entries.
- [US87 slice](us87_slice.json): 116,003 OHLCV rows. [QQQ slice](qqq_reference_slice.json):
  1,399 rows. Both are readable under the cutoff request, with
  `pit_certified=false`; `ready` does not check complete session coverage.
- EA ends at 2026-08-04. Its 59 missing XNYS sessions through 2026-10-27 are
  enumerated in the survey. A follow-up check of the existing shared lifecycle
  registry identifies all 59 as post-terminal sessions, not an unexplained
  provider outage; see the [recovery diagnosis](recovery_diagnosis.md). This does
  not certify terminal proceeds/settlement or justify dropping historical EA.
- Other series have no missing XNYS sessions after their first observed bar
  within this inventory range. First observation is not a certified listing
  date; shorter prefixes remain explicit. BE has 1,399 rows from 2021-04-05;
  CRDO has 1,192 from 2022-01-27. This is not full-life coverage certification.
- No required OHLCV field is missing/nonfinite/negative (prices must be positive)
  in the surveyed bars. There are 258 zero-range and 158 zero-volume bars across
  candidates/reference: define flat-bar handling and validate lifecycle causes
  before computing indicators; do not label these observations as halts.
- Existing US corporate-action metadata declares 87/87 at 2026-09-30. Existing
  fundamental metadata declares 86/87, with SBGSY missing. These component
  manifests exist, correcting the earlier RFC claim that no US action stream
  exists. Their declared event/coverage payloads are absent from this clean
  checkout; this audit does not validate or republish those payloads. Source
  event restoration/validation and the later experiment cutoff remain blockers.
- Vendor first-known availability and multi-vintage revision lineage remain
  uncertified. No earnings-calendar, sector-reference or regime/veto readiness
  claim is made by this OHLCV inventory. A required veto with unavailable
  evidence must stay BLOCKED.

## Existing executor dependency map

`alpha research study list` exposes four implemented families:
`us_tech_vol_reversal_v1`, `cross_sectional_xgb_v1`, `factor_exploration_v1`
and `ashare_rdi_v1`. There is no `bottom_detection_v1` or
`BottomDetectionConfig` implementation.

The maintained entry points are `study_catalog`, `study_template`,
`initialize_study`, `load_study_spec`, `run_study`, `inspect_study` and
`compare_studies` in `src/research/study_workspace.py`; walk-forward execution
stays in `src/research/walkforward/pipeline.py`. Extend these only after the
dependent BD-01 contracts are frozen. A new JSON spec is not an implemented
evaluator, and archived experiment names are not runnable templates.

Next: record RFC A–D decisions and exact timing, flat-bar/warm-up, missing/halt,
transition precedence, clustering/OOS/baseline/shadow rules. Restore/validate
required source payloads and validate required terminal-event settlement before a dependent experiment.
No research score, fifth strategy, account allocation or public raw study
receipt is delivered by this survey. Only metadata, counts, paths and hashes
are retained here; no bars or formal model events/targets are copied.
