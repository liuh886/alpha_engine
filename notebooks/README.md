# Research notebooks

Notebooks are optional human inspection surfaces. They are **not** research authority and they are not a permanent archive for every experiment.

## Retention rule

Keep a notebook only while it is reachable from at least one current need:

- an active strategy or current baseline;
- an open, preregistered research mission;
- an active prospective-validation program;
- a maintained diagnostic that is still required to interpret current formal evidence.

Once a one-shot experiment is complete and its decision is durably recorded, delete the notebook from the live tree. Git history is the archive.

Completed research must retain the smallest durable evidence needed to understand and audit the decision, normally:

- the result report or ResearchReceipt;
- compact machine-readable snapshot / evidence identity;
- experiment-ledger decision;
- any immutable formal/prospective evidence that remains part of current governance.

Do not keep a notebook merely because it once generated a chart. Do not create an `archive/` notebook tree, compatibility notebook, or refresh workflow for superseded experiments.

## QQQ strategy authority

The current QQQ strategy identity comes from `configs/strategies/registry.json` and the current Formal Bundle v2 evidence. Notebook names and historical version labels never define the active strategy.

A retained rolling or diagnostic notebook must read current canonical evidence rather than rebuilding strategy state independently. If a notebook becomes stale or its underlying one-shot runner is retired, delete it instead of adding a fallback path.

## Development rule

New research should prefer the maintained research runner/evaluator and durable receipts. Add a notebook only when visual inspection materially improves the research decision; delete it when that role ends.
