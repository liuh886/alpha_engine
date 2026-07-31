# Minimal Daily Model Path

Status: active research path  
Market frequency: daily bars, medium-frequency decisions  
Execution: manual and diagnostic only  
Trade ready: false

## Objective

Build the smallest useful model that can survive point-in-time data, costs, drawdown, turnover, and independent evidence. Complexity is allowed only after a simpler baseline is supported.

## Sequence

1. Validate the frozen fundamental-acceleration candidate against QQQ and the equal-weight pool.
2. If supported, combine no more than four non-redundant factors with equal weights and the existing low-turnover rules.
3. If the equal-weight combination is supported, test one regularized linear challenger using the same factors and portfolio contract.
4. Promote only if the linear challenger adds after-cost return or materially reduces risk without increasing turnover beyond the frozen ceiling.
5. Continue append-only forward shadow observation before any paper-execution or capital pilot decision.

## Deliberate exclusions

- no intraday data;
- no high-frequency execution;
- no tree-model restart before simple baselines pass;
- no parameter grids;
- no per-symbol formulas;
- no learned nonlinear interactions;
- no automatic order routing;
- no claim that a generated ticket is an effective trading signal before validation.

## Current PR sequence

### PR 1 — fundamental evidence

One fixed candidate, one attribution variant without SMA100, QQQ, and the equal-weight pool. Output exactly one research decision.

### PR 2 — equal-weight multifactor evidence

Use only independently admissible factor cards. Maximum four factors, equal weights, monthly evaluation, minimum 40-session holding, and annual turnover no greater than 4.0x.

### PR 3 — linear challenger

Use Ridge regression only. Inputs are the frozen factor values. The model must beat the equal-weight multifactor baseline on untouched evidence; otherwise the equal-weight model remains canonical.

## Promotion language

The only permitted progression is:

`candidate -> independent_validation_required -> forward_shadow_supported -> paper_execution_supported`

No step implies `trade_ready=true` by itself.
