# Frontend design system — research terminal foundation

> **Status: visual foundation only.** This note records the shell and token
> layer for the Alpha Engine research terminal. It is **not a release**, does
> not accept Direction A, and does not grant A7 approval. It authorizes no new
> route, navigation destination, page, workflow, scheduler, database, execution
> path, or data contract. `research_only=true` and `trade_ready=false` are unchanged.

## Scope

This slice changes the visual system, application shell, reusable UI primitives,
and utility classes. Page layouts, chart composition, and page content belong to
later slices. The default theme remains light; light and dark are both
first-class. Shell contracts, headings, regions, and `data-account-slot` remain stable for E2E tests.

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
  accent plus tinted row, collapsing rail, and quiet version footer.
- Topbar: 60px desktop / 56px mobile; eyebrow, title, account slot, theme control, mobile menu. `data-account-slot` is unchanged.
- Context bar: 36px desktop / 32px mobile; horizontal scroll must not create page overflow.
- Mobile tab bar: four existing destinations, 56px rows, safe-area bottom
  padding, active top accent plus icon well.
- Coarse pointers: 44px minimum targets for navigation, chrome, and buttons.

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
7. Do not edit page content or charts here; later slices compose these utilities.
