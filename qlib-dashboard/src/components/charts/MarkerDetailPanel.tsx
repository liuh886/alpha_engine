import {
  MARKER_DETAIL_DISCLOSURE,
  formatMarkerDelta,
  formatMarkerWeight,
  markerSideLabel,
  type MarkerDetailView,
} from '@/lib/chart-markers';
import { SecurityLink } from '@/components/SecurityLink';
import { cn } from '@/lib/utils';

export interface MarkerDetailPanelProps {
  detail: MarkerDetailView;
  testId: string;
  ariaLabel: string;
  onClear?: () => void;
  /** `status` for live selection announcements, `region` for a static panel. */
  role?: 'status' | 'region';
  live?: boolean;
  className?: string;
  /** Market evidence catalog for an instrument link on model markers. */
  market?: string;
  /** Exact formal model identity used to build the instrument route. */
  model?: string;
}

function modelLabel(entry: MarkerDetailView['entries'][number]): string | null {
  if (!entry.modelLabel) return entry.modelId ?? null;
  return entry.modelLabel;
}

/**
 * One selected-marker detail panel for strategy trades and security model
 * events. It states the ledger date and direction, names every model and action,
 * shows from/to weights and the retained reason, and repeats the shared
 * no-live-fill disclosure.
 */
export function MarkerDetailPanel({
  detail,
  testId,
  ariaLabel,
  onClear,
  role = 'status',
  live = false,
  className,
  market,
  model,
}: MarkerDetailPanelProps) {
  const unit = detail.count === 1 ? detail.unit : `${detail.unit}s`;
  return (
    <div
      data-testid={testId}
      role={role}
      aria-label={ariaLabel}
      aria-live={live ? 'polite' : undefined}
      className={cn('mt-3 rounded-lg border bg-muted/20 p-3 text-xs', className)}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold">
          {detail.date} · {markerSideLabel(detail.side)} · {detail.count} {unit}
        </p>
        {onClear && (
          <button
            type="button"
            className="min-h-8 rounded border bg-card px-2 text-[11px] text-muted-foreground hover:text-foreground"
            onClick={onClear}
          >
            Clear marker
          </button>
        )}
      </div>

      {detail.models.length > 1 && (
        <ul aria-label="Selected marker models" className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
          {detail.models.map(model => (
            <li key={model.modelId} className="inline-flex items-center gap-1.5">
              {model.color && (
                <span
                  aria-hidden="true"
                  className="inline-block h-2.5 w-2.5 rounded-sm"
                  style={{ backgroundColor: model.color }}
                />
              )}
              <span>{model.label}</span>
              <span className="font-mono text-[10px] text-muted-foreground">{model.modelId}</span>
            </li>
          ))}
        </ul>
      )}

      <dl className="mt-2 divide-y rounded-md border bg-card">
        {detail.entries.map(entry => {
          const label = modelLabel(entry);
          const hasWeight = entry.previousWeight !== undefined || entry.targetWeight !== undefined;
          return (
            <div key={entry.key} className="space-y-1 px-2 py-1.5">
              <div className="grid grid-cols-[110px_minmax(0,1fr)] gap-2">
                {label && (
                  <>
                    <dt className="text-muted-foreground">Model</dt>
                    <dd className="flex flex-wrap items-center gap-1.5 break-words">
                      {entry.color && (
                        <span
                          aria-hidden="true"
                          className="inline-block h-2.5 w-2.5 rounded-sm"
                          style={{ backgroundColor: entry.color }}
                        />
                      )}
                      <span>{label}</span>
                      {entry.modelId && (
                        <span className="font-mono text-[10px] text-muted-foreground">{entry.modelId}</span>
                      )}
                    </dd>
                  </>
                )}
                {entry.action && (
                  <>
                    <dt className="text-muted-foreground">Action</dt>
                    <dd className="font-semibold">{entry.action}</dd>
                  </>
                )}
                {entry.instrument && (
                  <>
                    <dt className="text-muted-foreground">Instrument</dt>
                    <dd className="break-words font-mono">
                      {market ? (
                        <SecurityLink market={market} model={model} instrument={entry.instrument}>
                          {entry.instrument}
                        </SecurityLink>
                      ) : entry.instrument}
                    </dd>
                  </>
                )}
                {hasWeight && (
                  <>
                    <dt className="text-muted-foreground">Weight</dt>
                    <dd className="font-mono">
                      {formatMarkerWeight(entry.previousWeight)} → {formatMarkerWeight(entry.targetWeight)}
                    </dd>
                  </>
                )}
                {entry.reason && (
                  <>
                    <dt className="text-muted-foreground">Reason</dt>
                    <dd className="break-words" title={entry.reasonTitle ?? undefined}>{entry.reason}</dd>
                  </>
                )}
              </div>
            </div>
          );
        })}
        {detail.netWeightDelta !== undefined && (
          <div className="grid grid-cols-[110px_minmax(0,1fr)] gap-2 px-2 py-1.5">
            <dt className="text-muted-foreground">Net weight change</dt>
            <dd className="font-mono">
              {detail.netWeightDelta === null ? 'Not retained' : formatMarkerDelta(detail.netWeightDelta)}
            </dd>
          </div>
        )}
      </dl>

      <p className="mt-2 text-[10px] leading-4 text-muted-foreground">{MARKER_DETAIL_DISCLOSURE}</p>
    </div>
  );
}
