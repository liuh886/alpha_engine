import { MARKER_SIDE_ORDER, markerSideColor, type MarkerSide } from '@/lib/chart-markers';
import { cn } from '@/lib/utils';

/** Small static glyph for the direction legend; the chart uses the same geometry. */
export function MarkerGlyph({ side }: { side: MarkerSide }) {
  const points = side === 'buy'
    ? '5,1 10,10 0,10'
    : side === 'sell'
      ? '0,0 10,0 5,9'
      : '5,0 10,5 5,10 0,5';
  return (
    <svg aria-hidden="true" viewBox="0 0 10 10" className="h-2.5 w-2.5" fill={markerSideColor(side)}>
      <polygon points={points} />
    </svg>
  );
}

export interface MarkerLegendModel {
  modelId: string;
  label: string;
  color: string;
  count?: number;
  visible?: boolean;
  onToggle?: () => void;
}

export interface MarkerLegendProps {
  /** Direction key; always shown when markers can appear. */
  showSides?: boolean;
  /** Model identity key. Color comes from the fixed categorical assignment. */
  models?: readonly MarkerLegendModel[];
  sideAriaLabel?: string;
  modelAriaLabel?: string;
  className?: string;
}

/**
 * The one marker legend used by strategy and security charts. Direction keeps
 * reserved polarity tokens and shape; model identity keeps categorical color
 * and always carries its text label, so color is never the only encoding.
 */
export function MarkerLegend({
  showSides = false,
  models = [],
  sideAriaLabel = 'Activity marker key',
  modelAriaLabel = 'Model marker key',
  className,
}: MarkerLegendProps) {
  return (
    <div className={cn('space-y-1.5', className)}>
      {showSides && (
        <ul aria-label={sideAriaLabel} className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-muted-foreground">
          {MARKER_SIDE_ORDER.map(item => (
            <li key={item.side} className="inline-flex items-center gap-1.5">
              <MarkerGlyph side={item.side} />
              {item.label}
            </li>
          ))}
          <li>Markers appear only on retained observation dates.</li>
        </ul>
      )}

      {models.length > 0 && (
        <ul aria-label={modelAriaLabel} className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-muted-foreground">
          {models.map(model => (
            <li key={model.modelId} data-model-id={model.modelId} title={model.modelId} className="inline-flex min-h-8 items-center gap-1.5">
              {model.onToggle ? (
                <label className="research-touch inline-flex min-h-8 cursor-pointer items-center gap-1.5 text-foreground">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-primary"
                    checked={model.visible !== false}
                    onChange={model.onToggle}
                  />
                  <span
                    aria-hidden="true"
                    data-testid="model-marker-swatch"
                    className="inline-block h-2.5 w-2.5 rounded-sm"
                    style={{ backgroundColor: model.color }}
                  />
                  <span>{model.label}</span>
                  {typeof model.count === 'number' && (
                    <span className="font-mono text-[10px] text-muted-foreground">{model.count} in range</span>
                  )}
                </label>
              ) : (
                <>
                  <span
                    aria-hidden="true"
                    data-testid="model-marker-swatch"
                    className="inline-block h-2.5 w-2.5 rounded-sm"
                    style={{ backgroundColor: model.color }}
                  />
                  <span className="text-foreground">{model.label}</span>
                  {typeof model.count === 'number' && <span className="font-mono">{model.count}</span>}
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
