# CN130 disclosure-gap overlay one-shot validation preregistration

Issue: #552  
Status: frozen before E1 validation output is inspected  
Boundary: `research_only=true`, `trade_ready=false`

## Purpose

PR #551 found a supported new-information component but judged the overlay using an independent-model gate. This experiment does not reopen that search. It freezes `abnormal_gap_1` and `E1_recent_event_rerank` exactly, reproduces their incremental calibration evidence, and then performs one untouched 2024–2025 validation pass.

## Frozen overlay

R0 continues to select four sectors and define the Top3 shortlist. When at least two Top3 names have a completed disclosure event no more than 20 sessions old, the name with the highest abnormal opening gap relative to CSI300 is selected. Otherwise the original R0 Top1 is retained.

No feature, threshold, event-age, shortlist-size, weight, sector-count or architecture alternative is allowed.

## Stage separation

1. Reproduce inherited calibration evidence on `2022H2`, `2023H1`, `2023H2`.
2. Open `2024H1`–`2025H2` only when every inherited incremental gate passes.
3. Apply the frozen overlay once; validation output cannot change the rule.
4. Report 2026 separately; it cannot change the decision.

## Interpretation boundary

The calibration gate evaluates E1 as an incremental overlay on E0, because the proposed model retains R0 sector selection and only alters the final name decision when a recent disclosure reaction exists. Validation remains strict: E1 must preserve all four positive E0 validation half-years, beat E0 at 20 and 40bps, and retain absolute leave-one robustness.

## Promotion boundary

Even a validation pass creates only a research candidate. It cannot automatically modify CN x1.0, create CN x1.1, become trade-ready, or merge into production without a separate promotion review.
