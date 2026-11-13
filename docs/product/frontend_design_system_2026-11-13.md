# Frontend design system — research terminal foundation

> **Status: visual foundation only.** This note records the shell and token
> layer for the Alpha Engine research terminal. It is **not a release**, does
> not accept Direction A, and does not grant A7 approval. It authorizes no new
> route, navigation destination, page, workflow, scheduler, database, execution
> path, or data contract. `research_only=true` and `trade_ready=false` are unchanged.

## Scope

This note records the visual system, application shell, reusable UI primitives,
utility classes and the component contracts converged for the four A-first
destinations. The shell, heading hierarchy, regions and `data-account-slot`
remain stable for E2E tests. Every route keeps exactly one `h1`; the shell
topbar title is not a heading. The default theme remains light; light and dark
are both first-class.

## Color tokens

All colors keep the `hsl(var(--token))` convention and are exposed through Tailwind.

| Role | Token | Use |
| --- | --- | --- |
| Working background | `background` | App canvas |
| Panel surface | `card`, `popover` | Cards, menus, dialogs |
| Text | `foreground`, `muted-foreground` | Body; labels and metadata |
| Interaction | `primary`, `ring` | Links, active nav, focus |
| Separation | `border`, `input` | 1px borders and controls |
| Positive return | `positive` | Gains only |
| Negative return | `negative` | Losses only |
| Warning | `warning` | Stale, restricted, needs review |
| Information | `info` | Neutral research context, sparingly |
| Chart structure | `chart-grid`, `chart-axis` | Chart grid and axes |

Semantic colors are reserved for signed returns, status, and warnings. They are
never the only signal: pair color with a sign, label, or icon. The `destructive`
token remains for destructive actions.

## Chart palette

The six categorical series are colorblind-safe, ordered for distinguishability, and tuned per theme.

| Series | Light HSL | Dark HSL |
| --- | --- | --- |
| `chart-1` blue | `210 90% 40%` | `207 88% 66%` |
| `chart-2` teal | `173 85% 27%` | `172 55% 50%` |
| `chart-3` amber | `38 95% 37%` | `42 92% 60%` |
| `chart-4` vermillion | `22 88% 46%` | `24 92% 65%` |
| `chart-5` magenta | `329 55% 48%` | `330 66% 70%` |
| `chart-6` sky | `199 75% 38%` | `199 82% 64%` |

Assign series in order. Do not use semantic green/red for arbitrary categories.

## Type scale

- Page title: 26px mobile / 30px desktop, semibold, tight tracking.
- Section title: 16px semibold, 24px line height.
- Body: 14px, 1.5 line height. Secondary: 11–12px; captions 11px.
- Kicker/eyebrow: 10px semibold uppercase, `0.14em` letter spacing.
- Metric: 24px semibold. All numbers use tabular numerals.
- Monospace only for identifiers and dense numeric tables.
- One sans family: Inter with Segoe UI/system fallback; no display faces.

## Spacing and surfaces

Use the 4px scale: 4, 8, 12, 16, 24, 32. Keep density calm but compact.
Surfaces use a 1px border, 10px radius, and the `shadow-card` token. Buttons use
8px height steps and a 6px radius. Popovers/dialogs use `shadow-popover`. No
gradients, glows, or glass panels. Motion is limited to 120–160ms
color/opacity/width transitions; existing `prefers-reduced-motion` rules remain
authoritative.

## Shell

- Sidebar: 240px expanded / 64px collapsed, grouped labels, a 2px left active
  accent plus tinted row, collapsing rail, and quiet version footer. The brand
  block carries only the product name; it does not repeat the research boundary.
- Topbar: 60px desktop / 56px mobile; eyebrow, title, account slot, theme control, mobile menu. `data-account-slot` is unchanged.
  The eyebrow `Alpha Engine / Research only` is the single shell statement of
  the research-only boundary. The title is a `p` element, not a heading; every
  route owns exactly one `h1` in its page content.
- Context bar: 36px desktop / 32px mobile; horizontal scroll must not create page overflow.
  On narrow screens the items wrap onto a second line instead of clipping, and
  the retired `Research only` chip does not return here.
- Mobile tab bar: four existing destinations, 56px rows, safe-area bottom
  padding, active top accent plus icon well.
- Coarse pointers: 44px minimum targets for navigation, chrome, and buttons.
  The shared `.research-touch` rule raises interactive chart, baseline and sort
  controls to 44×44 on `(pointer: coarse)` without changing desktop density.

## Component inventory

| Component | Contract |
| --- | --- |
| `ModelRankingTable` | One row model for strategies and governed index rows. Wide screens render a sortable table (`aria-sort`, `aria-pressed`); screens under 768px render one card per row with all six decision horizons, a sort strip with 44px buttons, and the same `data-testid`/`data-kind`/`data-stale` hooks. |
| `RankingCard` | Narrow-screen row: title, market, benchmark, per-row `As of`, stale badge, horizon grid, and (full density) excess/max drawdown with their own window labels plus the current signal. |
| `MissingCell` | Every hidden return renders an em dash with the full reason in `title` and `sr-only` text. Reasons are never truncated or reduced to a bare dash. |
| `StrategyChartHero` | Chart-first formal strategy summary. It reads one compact `nav.json` and one governed market-evidence read through the shared promise cache, guards a one-point baseline window, and keeps the declared/market baseline labels in display form (`QQQ`, `BYD v1.2`) while the raw identity stays the option key. |
| `NavChart` | Responsive wealth chart with a keyboard path: a marker button list (`aria-pressed`, visible focus ring, selected styling), a `role="status"` selected-marker panel, and a `<details>` data table with date, strategy, baseline and marker columns. The chart container is never recreated when only its size changes. |
| `BaselineControl` | Popover listbox with arrow/Home/End keys, display labels, unavailable reasons, and the raw benchmark identity kept as the value. |
| `BenchmarkMarketCards` | Governed US QQQ and CN 000300 cards plus an explicit non-governed SP500 placeholder with `role="group"` and no fabricated series. Sparkline tone is always supplied from the displayed return, never inferred from a different window. |
| `ResearchContextBar` | Status region for fleet count and evidence cutoffs; wrapping on narrow screens. |

Excess and max drawdown are labelled as run-window or close-window values on
every surface: they are never presented as if they were the sorted horizon.


## Reusable classes

| Class | Purpose |
| --- | --- |
| `ae-surface` / `ae-surface-muted` | Standard and secondary card surfaces |
| `ae-kicker` / `ae-page-title` / `ae-section-title` | Heading hierarchy |
| `ae-metric` / `ae-metric-label` | Large number and its label |
| `ae-delta` / `ae-delta-up` / `ae-delta-down` | Signed numeric change |
| `ae-data-table` | Dense tabular data table |
| `ae-toolbar` / `ae-chip` | Filter row and compact metadata chip |
| `ae-empty` | Empty or unavailable state |

```tsx
<section className="ae-surface p-5">
  <p className="ae-kicker">Formal evidence</p>
  <h2 className="ae-section-title">Return summary</h2>
  <div className="ae-toolbar"><span className="ae-chip">Source-bound</span><span className="ae-delta ae-delta-up">+2.4%</span></div>
  <table className="ae-data-table">
    <thead><tr><th>Strategy</th><th className="text-right">Return</th></tr></thead>
    <tbody><tr><td>QQQR v4.3</td><td className="text-right">+2.4%</td></tr></tbody>
  </table>
</section>
```

## Primitive rules

`button`, `badge`, `card`, `table`, `tabs`, `dialog`, and `skeleton` keep their
exports and variant names. Semantic badge variants (`positive`, `negative`,
`warning`, `info`, `muted`) are additive. Focus rings use `ring`; disabled states
reduce opacity and remove shadows.

## Hard rules

1. Do not add navigation destinations, pages, routes, or parallel data paths.
2. Do not rely on color alone for positive/negative meaning.
3. Use tabular numerals for every displayed number.
4. Keep 44px targets on coarse pointers and visible keyboard focus.
5. UI copy is English-only and must pass `npm run check:i18n`.
6. Preserve `aria-current`, E2E heading/region names, and `data-account-slot`.
7. Keep one page `h1` and one visible boundary statement per surface; new
   components extend the inventory above instead of adding a parallel shell or
   ranking implementation.
