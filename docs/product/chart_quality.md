# Strategy chart quality

Scope: the existing Overview and strategy detail. No additional navigation,
research execution or data store is required.

## Reading order

1. Performance: strategy and declared benchmark over the same observed interval.
2. Risk: a separate, aligned drawdown panel.
3. Explanation: exposure and governed state changes, with evidence on demand.

The first question is whether the strategy added value over the chosen interval,
followed by the loss and recovery experienced along the way. Chart decoration
must not obscure these questions.

## Comparison contract

- Period controls change both plotted values and summary values. Rebase each
  series using its value at the same interval boundary: `value / base - 1`.
- Preserve declared opening capital and initial losses for the full record.
  Do not invent an earlier dated observation just to draw a zero point.
- A missing boundary value makes that comparison unavailable; do not shift its
  start to a different day or substitute another benchmark.
- Relative excess is `(1 + strategy return) / (1 + benchmark return) - 1`.
  Percentage-point difference, if offered, needs a different label.
- Display the actual observed dates. A short history is not a full 1Y history.
- Historical backtest, prospective observation and provisional valuation must
  retain their real evidence boundaries and labels.

The initial implementation fixes period rebasing and unifies relative excess
between the curve and summary. Existing settlement and initial-capital semantics
remain intact.

## Source-bound opening and metric windows (2026-10-31)

The existing `public_historical_projection_v1` may publish a compact
`formal_performance_source_context_v1` in its summary and performance sections.
Canonical files, economic rows, metric values and decision receipts stay intact.
The public manifest includes the original canonical manifest bytes as metadata;
the reader verifies their SHA, bundle identity and model/run/cutoff before using
original claim section hashes or binding protected Operations to that source.
Instrument evidence continues to bind its own verified public projection ID.

Only the declared non-overlapping 10-session QQQ contract currently supports the
opening projection. It derives opening wealth from the first retained account
and net period return, verifies both wealth recurrences and non-overlapping
dates, and reconciles the declared total-return sample count/value against the
retained closing wealth. It does not hardcode an initial account, recompute costs
or invent an earlier plotted point. Other trace contracts retain their declared
boundaries without an inferred opening.

The summary carries the same small source/count/window context so initial All
can display the exact source return window without loading every wealth trace.
Detail and selected-period readers validate the context against the verified
canonical section hashes, actual rows, cutoff and source metric. Missing or
contradictory context on this projected contract blocks the affected evidence.

Source returns and chart returns retain distinct observation sets when declared
that way: for the US x1.3 source through 2026-10-29, 68 source return observations
end at the last completed holding interval, while the 69-row chart also retains
one provisional mark. Show each actual endpoint/count, preserve the first loss,
and identify the provisional inclusion explicitly. No evidence qualification,
live trading access or new research claim follows from this presentation work.

## Next improvements, in priority order

| Question | View | Quality requirement |
| --- | --- | --- |
| How did it compare? | Two return lines, strategy emphasized and benchmark dashed | Shared dates and scale; visible period returns; distinguish curves without relying on color |
| What losses did it experience? | Aligned underwater drawdown panel | Identify interval drawdown versus lifetime drawdown; retain actual dates and deepest loss |
| When did it change course? | Exposure/state strip | Step changes from sealed evidence; no smoothing or inferred events |
| Is performance consistent? | Monthly return heatmap on demand | Show partial months and missing observations; provide signed numeric values |

Prefer linear segments for observed return traces; do not smooth sparse
settlements into an implied daily path. Keep detailed attribution and turnover
available below the main comparison. Avoid overlaying returns, exposure and
turnover on one undifferentiated scale.

The separate brush has been replaced by optional start/end date controls.
Presets and custom dates now select the same observation interval for return
curves, summaries, drawdown and capital-use diagnostics. Dates snap inward to
actual observations; presets restore their declared range. A new report resets
custom indices rather than reusing positions from older evidence. Selection
remains local to the existing chart component; no new persistence is introduced.

Short intervals show day/month labels. All panels use the same sampled dates.
Return and drawdown segments are linear; invested ratio uses steps. Long
calculation notes are expandable, and range buttons have larger touch targets.
Full-history monthly returns retain a separate, explicit scope label.

Missing benchmark levels stay missing and resume only at actual observations.
A missing daily return invalidates the subsequent cumulative chain instead of
silently treating the missing return as zero. Missing comparison boundaries
remain unavailable across the selected interval.

## Interaction and validation

Retain Recharts and existing report inputs. These views do not need another chart
library or financial calculation service. Essential returns and dates stay
visible without hovering; mobile uses tap/focus for dated details. Range buttons
must wrap without horizontal page overflow. Prefer direct labels and consistent
color roles across charts, with redundant dash or text encodings.

Verify presets against independently calculated endpoints, missing boundary
values, initial losses, sparse settlement dates and provisional rows. Check the
rendered SVG and interaction at desktop and phone widths. Unit tests establish
calculation behavior; browser checks establish rendering and control behavior.
