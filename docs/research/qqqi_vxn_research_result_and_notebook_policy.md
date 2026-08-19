# QQQI / QQQ / TQQQ research evidence and notebook policy

Last updated: 2026-08-19

## Purpose

Preserve enough evidence to understand and audit QQQ research decisions **without retaining every historical execution path in the live repository**.

The current strategy identity is owned by `configs/strategies/registry.json`. Formal Bundle v2 is the persisted formal evidence authority. Historical notebook names, retired paradigm files and one-shot runners never define the active strategy.

## Durable research evidence

A completed experiment should retain the smallest durable record that makes the decision auditable:

| Layer | Durable record | Purpose |
|---|---|---|
| Decision | result report or ResearchReceipt | conclusion, economics, limitations and gate result |
| Machine evidence | compact snapshot / receipt / evidence digest | reproducible metrics, source identity and hashes |
| Research memory | experiment ledger or current factor/research index | prevents rejected ideas being rediscovered as new |
| Formal/prospective evidence | immutable governed evidence when applicable | preserves current formal or untouched-forward claims |

A historical implementation, notebook or experiment config is **not** durable evidence by itself.

## Live-code retention

Keep implementation code only when it is reachable from at least one of:

1. active strategy execution or current-target inference;
2. current exact replay / Formal Bundle v2 production;
3. an open preregistered research mission;
4. an active prospective-validation program;
5. a maintained test that protects one of the above.

When none applies, delete the implementation from the live tree. Do not move it to an archive runtime, add a compatibility wrapper, create a migration registry or keep a fallback entry point. Git history is the archive.

The same rule applies to experiment YAML, runner scripts and model-specific glue.

## Notebook policy

Notebooks are optional visual inspection tools, not a required layer for every experiment.

Keep a notebook only while it supports a current baseline, open mission, prospective program or maintained diagnostic. Once a one-shot study is complete and its result/snapshot/ledger evidence exists, delete the notebook from the live tree.

Do not create scheduled refresh infrastructure for historical notebooks. A retained current notebook must consume canonical evidence rather than independently recreate strategy state.

## Research execution policy

New experiments should run through maintained research/data/training/evaluation planes wherever those semantics already exist. A mission may add a narrow one-shot runner only when the maintained path cannot express the experiment cleanly; that runner must be deleted after the decision unless it becomes part of an active maintained path.

Research history therefore converges to:

```text
Mission
  -> canonical data
  -> maintained factor / training / rule implementation
  -> canonical evaluator
  -> ResearchReceipt / result + snapshot
  -> accept / reject
```

Rejected or superseded runtime code does not remain wired into production or research discovery.

## Alert and operating boundary

Current market decisions are created only by the governed scheduled/manual market-evaluation path. Code pushes validate implementation but do not create canonical market decisions.

Delivery consumes the canonical decision and records a separate delivery receipt. GitHub/Telegram delivery must not independently recreate strategy state.

## Pull-request completion rule

A PR that completes or supersedes a QQQ research path must explicitly answer:

- What durable evidence remains?
- Is the experimental runner/config/notebook still reachable from active execution, an open mission or prospective governance?
- If not, was it deleted in the same closeout or a bounded follow-up?

The default is deletion, not retention.
