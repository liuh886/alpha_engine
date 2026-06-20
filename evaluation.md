# Alpha Engine Functional Outcome Evaluation

Date: 2026-06-20
Status: Release acceptance contract

## Purpose

These requirements evaluate Alpha Engine from observable product outcomes rather than implementation claims. The platform cannot guarantee profitable alpha, but it must guarantee that incomplete, irreproducible, incomparable, statistically unsupported, stale, or incorrectly displayed results cannot be presented as release-ready or tradable.

## Evaluation Rules

- Every requirement is pass/fail. "Implemented", "test exists", or "page renders" is not sufficient evidence.
- Passing requires code behavior, hermetic automated tests, a real persisted artifact, and operator-visible proof where applicable.
- Missing, contradictory, stale, or unbound evidence fails closed.
- Any failed P0 result blocks the affected model, market, feature, or release candidate.
- Explicit artifact or model selection must never silently fall back to `latest`.

## Data Outcomes

1. **A data update must not report success when only part of the configured universe was updated.**
   - Acceptance: configured-symbol coverage is 100%, or every exclusion is explicitly approved with a reason; otherwise the update is partial and cannot publish `latest`.

2. **A new data update must not destroy the ability to reproduce an earlier experiment.**
   - Acceptance: after publishing snapshot N+1, snapshot N remains resolvable and retains identical files, schema, universe, calendar, feature values, and checksums.

3. **Different data content must not share one snapshot identity.**
   - Acceptance: identical content produces the same content-addressed ID; any change to bytes, schema, universe, source, adjustment policy, or calendar produces a different ID.

4. **Training, backtesting, inference, and inspection must not use an unknown or mutable data version.**
   - Acceptance: every result records and resolves an exact DataSnapshot ID with source versions, window, universe, schema, quality verdict, storage URI, and checksums.

## Model Training Outcomes

5. **A trained model must not be impossible to reconstruct.**
   - Acceptance: a clean process can use the saved snapshot, resolved configuration, code/dependency identity, feature/label schema, and random seeds to retrain the model and reproduce predictions and metrics within declared tolerances.

6. **Training must not finish with only transient console output.**
   - Acceptance: durable logs contain stage transitions, parameters, data identity, sample/feature counts, timing, losses, validation diagnostics, warnings, failure context, and final artifact locations.

7. **A trained model must not lack the standard metrics required for comparison.**
   - Acceptance: every comparable model provides the same versioned definitions and units for IC, Rank IC, ICIR, consistency, sample/coverage, return, benchmark/excess return, volatility, Sharpe, information ratio, max drawdown, turnover, costs, and net return.

8. **A model binary must not be detached from its training configuration, features, labels, and data.**
   - Acceptance: one immutable ModelArtifact binds the binary, resolved workflow, feature/label schema, DataSnapshot, windows, benchmark, costs, code/lock identity, seeds, logs, predictions, labels, diagnostics, and checksums.

9. **The active model registry must not contain test records, duplicate identities, missing paths, corrupt artifacts, or metric-empty models.**
   - Acceptance: registry rebuild from validated ModelArtifacts is deterministic and yields zero dummy/test entries, zero dangling paths, zero checksum failures, and zero missing required fields.

## Backtest Outcomes

10. **Repeated backtests with identical inputs must not produce materially different results.**
    - Acceptance: identical DataSnapshot, ModelArtifact, strategy, calendar, benchmark, costs, and seeds reproduce orders, holdings, NAV, and metrics within approved tolerances.

11. **A model must not be accepted using only in-sample performance.**
    - Acceptance: independent test or walk-forward evidence identifies train/validation/test windows and passes temporal leakage, universe leakage, and look-ahead checks.

12. **A strategy must not be called tradable when profitability disappears after realistic costs.**
    - Acceptance: backtests report gross and net results, turnover, fees, slippage, liquidity assumptions, and net excess return; failure of the versioned cost gate blocks promotion.

13. **Backtest performance must not be accepted from source-code claims alone.**
    - Acceptance: ordinary and optimized paths are behaviorally equivalent on a golden corpus, and measured wall time, peak memory, data-fetch count, and throughput meet the documented release budget.

## Signal and Stock-Selection Outcomes

14. **A trading signal must not have an unknown model origin.**
    - Acceptance: every signal returns ModelVersion, run ID, prediction checksum, DataSnapshot, prediction timestamp, evaluation window, and validity expiry.

15. **A model must not be promoted if it produces predictions but cannot produce actionable signals.**
    - Acceptance: covered stocks receive direction, strength, cross-sectional rank, effective period, and any non-tradable reason; inability to produce a valid signal blocks operational promotion.

16. **Signal effectiveness must not reward the wrong trading direction.**
    - Acceptance: buy-then-rise and sell-then-fall are successes; buy-then-fall and sell-then-rise are failures; automated tests cover all four cases.

17. **Small-sample or statistically unsupported stock recommendations must not be presented as effective.**
    - Acceptance: results expose independent sample count, coverage, confidence interval, benchmark excess return, and cost-adjusted return; failing evidence is labelled unqualified rather than recommended.

18. **The stock screener must not silently omit stocks or evaluate them with a different model.**
    - Acceptance: the screener evaluates the declared universe with the selected ModelVersion and reports qualified, excluded, insufficient-data, failed, and missing-prediction counts with reasons.

## Portfolio and Continuous-Operation Outcomes

19. **Valid signals must not stop at a ranking when the platform claims portfolio decision support.**
    - Acceptance: qualified signals produce an explainable ExecutionPlan with target weights, rebalance quantities, cash, expected costs, and position/sector/liquidity/turnover/risk constraints that reconcile numerically.

20. **A degraded or invalid model must not remain operationally approved.**
    - Acceptance: stale data, artifact damage, drift, signal decay, cost-gate failure, or risk breach blocks new plans and creates an auditable continue/retrain/demote/stop/rollback decision.

## Frontend Outcomes

21. **The frontend must not display a result without making its exact identity visible.**
    - Acceptance: data, model, backtest, signal, portfolio, and report views display and deep-link their DataSnapshot, ModelVersion, run, evidence, and generated-at identities; model selection survives navigation and reload without changing identity.

22. **The frontend must not show success when data is partial, stale, missing, or contradictory.**
    - Acceptance: release pages have distinct loading, empty, partial, stale, failed, blocked, and success states; success is rendered only from a validated backend verdict, never inferred from HTTP 200 or non-empty data.

23. **Long-running frontend actions must not lose their job after navigation, refresh, disconnect, or restart.**
    - Acceptance: update, training, reconstruction, backtest, and evaluation jobs retain stable IDs, resume status/log streaming, avoid duplicate submission, and provide retry or recovery actions after failure.

24. **Different frontend pages must not show conflicting facts for the same artifact.**
    - Acceptance: Dashboard, Models, Backtest, Compare, Signals, Reports, and Operations read shared typed contracts; automated tests verify identical identity, status, metric value, unit, benchmark, and window across pages.

25. **The frontend must not compare models whose evidence is not comparable.**
    - Acceptance: Compare allows only matching metric-schema versions, markets, benchmarks, evaluation windows, cost policies, and evidence classes; incompatible models are blocked with the exact mismatch reason.

26. **The frontend screener must not hide uncertainty or filtering decisions.**
    - Acceptance: every ranking shows sample count, confidence, coverage, model identity, evaluation period, qualification status, and exclusion reason; users can filter qualified/unqualified records without recomputing scores in the browser.

27. **Destructive or lifecycle-changing frontend actions must not be ambiguous or accidentally repeatable.**
    - Acceptance: delete, promote, demote, rollback, stop, full data refresh, and portfolio rebalance show target identity, impact, gate evidence, confirmation, pending state, idempotency protection, and durable result.

28. **Release-scale data must not make the frontend unresponsive or unstable.**
    - Acceptance: defined large model/run/stock/log datasets meet route-load, interaction, memory, polling, and rendering budgets; tables/charts use bounded queries or virtualization and release tests detect leaks or unbounded growth.

29. **Supported desktop viewports and keyboard users must not receive an unusable interface.**
    - Acceptance: release workflows pass keyboard navigation, focus management, semantic labels, contrast, reduced-motion, and zero critical/serious accessibility violations at 1024x768, 1440x900, and 1920x1080 without overlap or clipping.

30. **A production frontend build must not be accepted from unit tests or screenshots alone.**
    - Acceptance: Playwright executes the complete data-update-to-qualified-stock journey against deterministic fixtures plus an archived real candidate; zero broken routes, console errors, unhandled rejections, unexpected failed requests, identity drift, or contradictory success states are allowed, and traces/screenshots are retained on failure.

## AAA-to-VVV Signal-Grade Ecosystem Outcomes

The six directional grades are model outputs, not permanent stock labels. `AAA`, `AA`, and `A` represent descending long-side strength; `V`, `VV`, and `VVV` represent increasing short-side or avoidance strength. A neutral region remains ungraded. A GradeObservation records the cross-sectional rank, while GradeQualification separately states whether historical evidence is sufficient for research, screening, or trading use.

31. **A grade must not change meaning because the evaluated universe became smaller.**
    - Acceptance: a versioned GradePolicy fixes the six mutually exclusive rank or percentile bands, neutral band, minimum universe, rebalance frequency, forecast horizon, and tie policy. With the current ten-stock bands, fewer than 80 eligible stocks produces `insufficient_universe`; the engine must not shrink or overlap the bands.

32. **A grade must not be displayed without an exact and resolvable origin.**
    - Acceptance: every GradeObservation binds ModelVersion, run ID, prediction checksum, DataSnapshot, GradePolicy version, market, universe ID, as-of timestamp, forecast horizon, score, rank, percentile, and grade. An explicitly selected identity that cannot be resolved fails closed and never falls back to `latest`.

33. **A historical grade must not use information unavailable at its as-of time.**
    - Acceptance: prediction, feature, universe-membership, price, and corporate-action timestamps are all at or before the grade timestamp; a request before prediction history returns no grade, and automated tests prove that future predictions or prices cannot enter assignment.

34. **A stock must not receive ambiguous or non-deterministic grades.**
    - Acceptance: within one model, universe, horizon, and timestamp, each eligible stock receives at most one of `AAA/AA/A/V/VV/VVV`; neutral and excluded stocks remain explicit, and repeated evaluation with tied scores produces the same disclosed assignment and counts.

35. **A rank grade must not be presented as statistically qualified merely because it was assigned.**
    - Acceptance: GradeObservation and GradeQualification are separate persisted records. Per-stock qualification requires at least 20 independent observations; model-market-grade qualification requires at least 100 independent out-of-sample observations and 95% prediction/price coverage. Anything below a gate is labelled `unqualified` with the failed reasons.

36. **Grade effectiveness must not reward the wrong side of a trade or be recomputed differently by the browser.**
    - Acceptance: long-grade success requires positive cost-adjusted excess return and short-grade success requires negative cost-adjusted excess return. The backend alone computes direction-adjusted hit rate, raw return, benchmark/excess return, costs, net return, and score; tests cover profitable and losing outcomes on both sides, and frontend code contains no duplicate scoring formula.

37. **The six grades must not be accepted when their realized outcomes contradict their ordering.**
    - Acceptance: out-of-sample mean net excess return follows the expected order `AAA > AA > A > neutral > V > VV > VVV`; grade order and realized return have Spearman correlation of at least 0.8, and the 95% confidence-interval lower bound of the cost-adjusted `AAA - VVV` spread is greater than zero. Any exception blocks grade qualification and is reported explicitly.

38. **A grade policy must not be called stable from one favorable period or market regime.**
    - Acceptance: evidence covers at least three non-overlapping evaluation windows and the declared bull, bear, and high-volatility regimes where data exists; AAA and VVV retain the expected direction in at least 70% of eligible windows, with sample counts, confidence intervals, decay, and failed regimes visible.

39. **The grade statistics table must not hide the evidence needed to interpret a result.**
    - Acceptance: every grade row shows model and policy identity, evaluation period, horizon, independent sample count, coverage, direction-adjusted hit rate, mean and median raw return, benchmark and excess return, cost-adjusted return, 95% confidence interval, qualification status, and failure reasons; missing values remain missing rather than becoming zero.

40. **Stock Screening must not rank a hidden subset or a model other than the selected model.**
    - Acceptance: Stock Screening evaluates the complete declared universe against the selected ModelVersion and GradePolicy, reports total, eligible, graded, neutral, unqualified, excluded, failed, and missing-prediction counts with reasons, and supports filtering and sorting by grade, qualification, direction-adjusted performance, confidence, coverage, and effective period without changing identity.

41. **Grade visualization must not imply confidence or profitability through color alone.**
    - Acceptance: chart markers and grade distributions use the same persisted observations as the statistics table and screener; tooltips expose exact identity, timestamp, rank, score, grade, qualification, horizon, and realized direction-adjusted return. Sell-side colors and success states use sell-side semantics, while unqualified, stale, neutral, and unavailable states are visually distinct.

42. **The AAA-to-VVV feature must not disagree across its table, screener, chart, and API surfaces.**
    - Acceptance: an end-to-end test selects one immutable model and date, then proves identical identities, grade assignments, universe counts, qualification verdicts, metrics, and exclusions across API responses, the statistics table, Stock Screening, stock detail, and chart. Selecting a missing model must fail visibly on every surface rather than substitute another model.

## Release Verdict

Alpha Engine is functionally release-ready only when all requirements applicable to the declared release scope pass against one immutable ReleaseCandidate. A failed model or market may remain available for research only when it is explicitly marked experimental or blocked and cannot generate operationally approved decisions.
