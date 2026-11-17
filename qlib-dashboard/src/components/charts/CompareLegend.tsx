import { X } from 'lucide-react';
import type { OverlayColorRole } from '@/lib/security-chart-extensions';
import { overlayRoleCssColor } from '@/lib/indicator-overlays';

export interface CompareLegendItem {
  id: string;
  label: string;
  detail?: string;
  colorRole: OverlayColorRole;
  dashed: boolean;
  kind: 'instrument' | 'model' | 'baseline';
  /** Present only for overlay entities the viewer can remove. */
  onRemove?: () => void;
  /** True while the entity's own series is still being read. */
  loading?: boolean;
  /** When set, the entity is not plotted and the reason is shown. */
  unavailableReason?: string;
}

/**
 * Names every displayed comparison entity. Text stays in ink tokens; the swatch
 * carries the only colour. Overlay entities are removable; the page's own
 * instrument and the active baseline are named but not removable here.
 */
export function CompareLegend({ items }: { items: readonly CompareLegendItem[] }) {
  if (items.length === 0) return null;
  return (
    <ul
      aria-label="Comparison entities"
      data-testid="compare-legend"
      className="mt-2 flex flex-wrap items-start gap-x-4 gap-y-1.5 text-[11px] leading-4 text-muted-foreground"
    >
      {items.map(item => (
        <li key={item.id} data-testid={`compare-legend-${item.id}`} className="inline-flex min-w-0 flex-wrap items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block w-4 shrink-0"
            style={item.unavailableReason
              ? { borderTop: '2px dotted hsl(var(--muted-foreground))' }
              : item.dashed
                ? { borderTop: `2px dashed ${overlayRoleCssColor(item.colorRole)}` }
                : { borderTop: `2px solid ${overlayRoleCssColor(item.colorRole)}` }}
          />
          <span className="font-medium text-foreground">{item.label}</span>
          {item.detail && <span className="text-muted-foreground">{item.detail}</span>}
          {item.unavailableReason ? (
            <span data-testid={`compare-unavailable-${item.id}`} className="text-warning">
              Not plotted: {item.unavailableReason}
            </span>
          ) : item.loading ? (
            <span data-testid={`compare-loading-${item.id}`} role="status">Loading…</span>
          ) : (
            item.kind === 'baseline' && <span className="text-muted-foreground">baseline, dashed</span>
          )}
          {item.onRemove && (
            <button
              type="button"
              aria-label={`Remove ${item.label} from comparison`}
              onClick={item.onRemove}
              className="research-touch inline-flex min-h-6 min-w-6 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <X aria-hidden="true" className="h-3 w-3" />
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}
