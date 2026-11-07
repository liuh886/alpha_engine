# BD-01 feature and transition boundaries — proposed draft

Prepared 2026-10-28 for [the Bottom Detection RFC](bottom_detection_capture_rfc.md).
Status: **DRAFT, NOT PREREGISTERED**. These proposed numerical conventions and
synthetic expected cases make the remaining implementation reviewable. They do
not select RFC A–D, freeze thresholds/allocation/execution/OOS rules, implement a
study, authorize a fifth strategy or establish research effectiveness.
`research_only=true`, `trade_ready=false`.

## Feature validity and causal timing

Use only the declared price basis and evidence available by the decision cutoff.
Never combine raw OHLC with adjusted close. A T-close feature cannot execute at
the same already-observed close. Execution price, friction and holding horizons
remain dependent on decision A. Backfilled current source bytes do not prove
historical availability.

Proposed conventions for a later immutable specification:

| Feature | Definition and availability |
| --- | --- |
| Drawdown 20 | `1 - C[t] / max(C[t-19:t+1])`; require 20 consecutive valid official sessions, positive closes, include current close. |
| Wilder RSI 14 | Require 15 consecutive closes for the first 14 deltas. Seed mean gains/losses arithmetically, then Wilder recurrence `(13 * previous + current) / 14`. Both zero means 50; zero loss with positive gain means 100; zero gain with positive loss means 0. |
| CLV | `(2*C-H-L)/(H-L)` for a valid non-flat bar. When `H=L`, return unavailable with reason `flat_bar`; do not replace it with a fabricated neutral/positive value. |
| Lower wick | `(min(O,C)-L)/(H-L)` on a valid non-flat bar; flat bar unavailable. Require `L <= min(O,C) <= max(O,C) <= H`. |
| Relative return | The RFC's `t-2 -> t` spans **two** session-to-session returns, despite its name `RS_3`. Proposed resolution: call it `relative_return_2_sessions`, using `C[t]/C[t-2]-1` minus the same QQQ return. Require three consecutive paired observations. Choosing a three-return horizon would be a different contract. |
| Volume ratio 20 | `V[t]/mean(V[t-19:t+1])`; require 20 consecutive finite nonnegative volumes. A positive denominator permits a zero current ratio; zero denominator is unavailable. Neither zero volume nor a flat bar alone proves a halt. |
| Confirmation SMA 5 | Arithmetic mean of five consecutive closes through T; compare T close against the previous two closes and this declared SMA. Strict `>` comparisons do not trigger on equality. |

An unavailable feature has `value=null` and a specific reason; do not encode it
as zero or let a three-valued condition accidentally become true. Warm-up is
not a bearish observation. A missing session breaks the contiguous indicator
segment; resume only after the required warm-up in the new segment. Forward
labels remain unavailable until their full horizon is observed.

## Session and lifecycle boundaries

Use the existing official market calendar and shared lifecycle reader. A weekend
or exchange holiday is not a missing session. Before observed history, record
unavailable history; first observation is not a certified listing date. After a
governed suspension/terminal boundary, record lifecycle ineligibility and retain
historical rows. EA's post-2026-08-04 tail is explained by the existing terminal
listing, not an instruction to download or fabricate replacement bars.

Unexpected missing bars, required benchmark absence and required-but-missing
earnings evidence block the affected decision. The tolerance/veto policy still
requires decision C; a short gap must never authorize filling unknown prices.
An earnings veto may not silently switch to technical-only evaluation. No order
or new entry may cross an unresolved tradability boundary. Cash settlement,
re-entry after gaps and event-cluster continuity must be frozen before replay.

## Proposed same-session precedence

Evaluate a session from the previous session's state. Proposed precedence is:

1. Evidence/tradability gate: emit `BLOCKED` and no actionable transition; retain
   prior state/reason for audit. A blocked session must not reset a timeout.
2. For an existing probe, a hard low breach invalidates before confirmation.
3. Expiry invalidates before confirmation when the deadline is already exceeded.
4. Otherwise allow at most one transition: `IDLE -> WATCH`, `WATCH ->
   PROBE_ELIGIBLE`, or `PROBE_ELIGIBLE -> CONFIRMED`. Do not cascade into several
   entries using the same bar.

For a probe entered at official session index p with timeout K, age is `i-p` in
official sessions, including blocked sessions. Proposed inclusive deadline:
confirmation at age K is allowed; age `> K` is expired. A simultaneous low
breach and confirmation is invalidated. Confirmed-position exits and re-arming
after invalidation depend on the unresolved exit/clustering contract, so this
draft does not invent them.

## Synthetic acceptance matrix for the future implementation

These are expected cases, **not executed tests or measured performance**:

| Synthetic input / prior state | Proposed expected result |
| --- | --- |
| `O=H=L=C=100` | CLV and wick null (`flat_bar`); neither reversal branch passes. |
| `O=101,H=110,L=90,C=106` | CLV `0.6`, lower wick `0.55`. |
| 14 identical closes / 15 identical closes | RSI null (`warmup`) / RSI 50. |
| 15 strictly rising / strictly falling closes | RSI 100 / 0. |
| 20 valid closes with maximum 100, current 80 | Drawdown `0.2`. |
| Current volume 0, positive 20-session mean / all 20 volumes 0 | Ratio 0 / null (`zero_denominator`); no inferred halt. |
| Stock `[100,110,121]`, QQQ `[100,100,100]` | Two-session relative return `0.21`, not a three-return horizon. |
| One unexpected missing official session inside warm-up | Null dependent feature; no compression of the gap into consecutive bars. |
| Friday and next Monday with no exchange session between | Consecutive sessions; no weekend gap. |
| Required QQQ or earnings evidence absent | `BLOCKED`; no technical-only fallback. |
| EA after governed suspension boundary | Lifecycle ineligible; preserve historical membership/rows, no synthetic bar. |
| `IDLE` and every watch/probe/confirmation predicate true | `WATCH` only. |
| Existing probe, low breach and confirmation both true | `INVALIDATED`, reason low breach. |
| Existing probe, confirmation at age K / K+1 | `CONFIRMED` / `INVALIDATED`, reason expiry. |
| Existing probe, missing bar at K+1 | `BLOCKED`; next valid session remains beyond deadline. |
| Close equals previous two-close maximum or SMA5 | Confirmation condition false. |
| T-close event with only T's open as execution candidate | Reject same-session causal execution. |

Before implementation, copy the accepted conventions and cases into the
versioned experiment spec with dated decisions, evidence identities and exact
execution/exit/clustering rules. Reuse the existing study executor and test
paths. Do not label this draft or its table as completed BD-01 acceptance.
