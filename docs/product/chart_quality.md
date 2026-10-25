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
