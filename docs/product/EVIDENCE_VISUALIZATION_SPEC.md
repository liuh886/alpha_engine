# Evidence Visualization Specification

## Governing rule

Every visible claim must be traceable to the active bundle, model index or a manifest-declared supporting artifact. Missing evidence is shown as missing; the frontend does not reconstruct, interpolate or silently substitute it.

## Data

The Data view presents scope, cutoff, integrity state, warnings, blocked gates, artifact classes, byte sizes and SHA-256 identities. A file inventory is evidence lineage, not a data-quality score by itself.

## Models

Model comparison uses exported metrics and preserves benchmark and cost context where declared. Stage labels are descriptive records only. Static/local views never expose promotion, deletion or retraining actions.

## Signal and execution timing

A signal derived at a close and a trade executed at a later open are separate events. The ledger uses distinct columns and visual accents. When no explicit ledger is exported, the frontend says so and does not infer execution dates from positions or returns.

## Factors

Feature importance is presented as model-specific diagnostic evidence. It must not be labeled as IC, economic causality or factor validation. Imported Alpha158 or proprietary formulas remain unvalidated unless separate evidence explicitly says otherwise.

## Experiments

Each model record is shown as an observed experiment outcome with identity, run, snapshot, metrics and stop-rule context. The journal does not invite parameter search over previously observed evidence.

## Reports and notebooks

Only manifest-declared reports, notebooks and methodology files are available. The browser reads those files from the active source and never scans outside the bundle root.

## Accessibility

Charts require textual summaries or tables. Tables use semantic headers, keyboard-accessible controls and explicit empty states. Color is supplementary: signal/execution distinctions are also expressed in labels and separate columns.
