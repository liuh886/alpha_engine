import {
  INDICATOR_DISCLOSURE,
  INDICATOR_REGISTRY_LABEL,
  overlayRoleCssColor,
  type IndicatorLegendItem,
  type IndicatorUnavailableItem,
} from '@/lib/indicator-overlays';

/**
 * One shared legend/notes area for every governed indicator on the chart.
 * Values are browser-derived; identities and formula versions come from the
 * compiled registry snapshot. Text stays in ink tokens and the swatch carries
 * the only colour.
 */
export function IndicatorNotes({
  legend,
  unavailable,
  marketNote,
}: {
  legend: readonly IndicatorLegendItem[];
  unavailable: readonly IndicatorUnavailableItem[];
  marketNote?: string;
}) {
  if (legend.length === 0 && unavailable.length === 0 && !marketNote) return null;
  return (
    <div data-testid="indicator-notes" className="mt-2 space-y-1.5 text-[11px] leading-4 text-muted-foreground">
      {legend.length > 0 && (
        <ul aria-label="Indicator series" data-testid="indicator-legend" className="flex flex-wrap items-center gap-x-4 gap-y-1">
          {legend.map(item => (
            <li key={item.key} className="inline-flex items-center gap-1.5">
              <span
                aria-hidden="true"
                className="inline-block w-4 shrink-0"
                style={item.dashed
                  ? { borderTop: `2px dashed ${overlayRoleCssColor(item.colorRole)}` }
                  : { borderTop: `2px solid ${overlayRoleCssColor(item.colorRole)}` }}
              />
              <span>{item.label}</span>
            </li>
          ))}
        </ul>
      )}

      {marketNote && (
        <p role="note" data-testid="indicator-vix-unavailable" className="font-medium text-warning">
          {marketNote}
        </p>
      )}

      {unavailable.length > 0 && (
        <ul aria-label="Unavailable indicators" data-testid="indicator-unavailable" className="space-y-0.5">
          {unavailable.map(item => (
            <li key={item.id}>
              <span className="font-medium text-foreground">{item.label} omitted.</span> {item.reason}
            </li>
          ))}
        </ul>
      )}

      <p data-testid="indicator-disclosure">
        {INDICATOR_DISCLOSURE} Registry: <span className="font-mono text-[10px]">{INDICATOR_REGISTRY_LABEL}</span>.
      </p>
    </div>
  );
}
