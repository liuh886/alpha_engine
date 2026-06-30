# PR53 Training Effectiveness Diagnostic

Date: 2026-06-29

## Outcome

The inability to train a usable model came from both correctness defects and an
unstable research specification. The correctness defects are fixed, and the final US
20-day excess candidate passes historical and current holdout gates.

## Confirmed Root Causes

1. A forward Qlib label was negated while execution bought high scores.
2. Label-bearing segments lacked full trading-session purges.
3. Qlib index order differed from backtest return index order.
4. Pooled/positional IC could misstate signal quality.
5. US benchmark excess was not computed as stock minus same-date QQQ return.
6. All-feature L2 training was seed-sensitive and often stopped after one tree.
7. Stored artifact frames and inference transforms were not always reproducible.
8. The 10-day Alpha158 specification was historically unstable even after bug fixes.

## Research Resolution

Repeated falsification showed that changing only the objective, training-history
minimum, rolling window, or linear model did not solve stability. Reducing the feature
search from 163 technical expressions to 10 predeclared economic features improved
results, but the 10-day horizon still missed ICIR/consistency gates. Aligning target,
purge, and execution to 20 sessions passed all historical gates and then produced
positive current holdout excess.

Final artifact: `cc7a0c9accde4934bda6a105b83a302a`.

- WF: mean IC +0.03626, ICIR 0.6136, consistency 63.64%, 11 successful splits.
- Holdout: +27.23% vectorized excess, +31.80% grade excess, Sharpe 0.91,
  max drawdown -18.94%.
- Signal quality: mean IC +0.1026, ICIR 0.3474, 69.08% positive periods.

## Governance

The absolute-return candidate is not eligible despite +38.37% grade excess because
its historical WF is negative. Candidate ranking now applies one shared gate requiring
historical split count, mean IC, ICIR, consistency, and positive holdout excess.

## Verification

- 187 focused protocol/training tests passed before the final full suite.
- Full backend: 1281 passed, 15 skipped.
- Full frontend: 156 passed and build passed.
- Ruff, mypy, Python package build, and diff checks passed.
- Remote PR remains `UNSTABLE` on the old commit; no changes were committed or pushed.

## Merge Status

Local implementation and evidence are ready for review and push. PR53 itself is not
merge-ready until the local tree is committed, pushed, and required GitHub checks rerun
green.
