import { MODEL_SERIES_TOKENS } from './chart-theme';
import { formatReturn } from './metrics';
import type { NavMarker } from './nav-series';
import { formatEventAction, humanizeEventReason } from './security-format';
import type { SecurityEvent } from './security-evidence';

/** Direction is encoded by shape/position; model identity is encoded by hue. */
export type MarkerSide = 'buy' | 'sell' | 'mixed';

export const MARKER_SIDE_ORDER: ReadonlyArray<{ side: MarkerSide; label: string }> = [
  { side: 'buy', label: 'Buy / increase' },
  { side: 'sell', label: 'Sell / decrease' },
  { side: 'mixed', label: 'Buy and sell' },
];

export function markerSideFromAction(action: string): 'buy' | 'sell' | null {
  const normalized = action.trim().toUpperCase();
  if (normalized === 'BUY' || normalized === 'INCREASE') return 'buy';
  if (normalized === 'SELL' || normalized === 'DECREASE') return 'sell';
  return null;
}

export function markerSideLabel(side: MarkerSide): string {
  return MARKER_SIDE_ORDER.find(item => item.side === side)?.label ?? 'Buy and sell';
}

/**
 * Direction is a polarity/status cue, so it keeps the reserved positive /
 * negative / warning tokens. It is never reused for model series colors.
 */
export function markerSideColor(side: MarkerSide): string {
  if (side === 'buy') return 'hsl(var(--positive))';
  if (side === 'sell') return 'hsl(var(--negative))';
  return 'hsl(var(--warning))';
}

/**
 * Categorical model-series colors in the validated fixed order. These DOM
 * values intentionally use CSS custom properties; the canvas chart resolves
 * the same tokens through `chartTheme().modelSeries`.
 */
export const MODEL_SERIES_COLORS: readonly string[] = MODEL_SERIES_TOKENS.map(
  name => `hsl(var(--${name}))`,
);

/**
 * Used only past the validated five-slot order. Overflow models keep their
 * names, legend rows and detail evidence; they just stop consuming a new hue.
 * A series is never cycled back to slot 1 under a new identity.
 */
export const MODEL_SERIES_OVERFLOW_COLOR = 'hsl(var(--muted-foreground))';

export interface ModelColorAssignment {
  modelId: string;
  index: number;
  color: string;
  token: string | null;
  overflow: boolean;
}

/**
 * Assign colors by model identity, never by filtered list position or rank.
 * Sorting the deduplicated identity list means hiding or showing one model
 * never repaints the survivors.
 */
export function modelColorAssignments(modelIds: readonly string[]): ModelColorAssignment[] {
  return [...new Set(modelIds.filter(id => typeof id === 'string' && id !== ''))]
    .sort()
    .map((modelId, index) => {
      const token = MODEL_SERIES_TOKENS[index] ?? null;
      return {
        modelId,
        index,
        color: token === null ? MODEL_SERIES_OVERFLOW_COLOR : MODEL_SERIES_COLORS[index],
        token,
        overflow: token === null,
      };
    });
}

export function modelColorIndexMap(
  assignments: readonly ModelColorAssignment[],
): Map<string, number> {
  return new Map(assignments.map(assignment => [assignment.modelId, assignment.index]));
}

export function modelColorFor(
  modelId: string,
  assignments: readonly ModelColorAssignment[],
): string {
  return assignments.find(assignment => assignment.modelId === modelId)?.color
    ?? MODEL_SERIES_OVERFLOW_COLOR;
}

const WEIGHT_FORMAT = new Intl.NumberFormat('en-US', {
  style: 'percent',
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

/** Ledger weights are fractions; a missing weight is a dash, never zero. */
export function formatMarkerWeight(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? WEIGHT_FORMAT.format(value) : '—';
}

/** Signed weight change in percentage points, using the shared return format. */
export function formatMarkerDelta(value: number | null | undefined): string {
  return formatReturn(value);
}

export const MARKER_DETAIL_DISCLOSURE =
  'Historical ledger dates only. These markers do not establish an execution price, live fill or order instruction.';

export interface MarkerDetailEntry {
  key: string;
  modelId?: string;
  modelLabel?: string;
  color?: string;
  action?: string;
  instrument?: string;
  previousWeight?: number | null;
  targetWeight?: number | null;
  reason?: string;
  reasonTitle?: string;
}

export interface MarkerDetailModel {
  modelId: string;
  label: string;
  color?: string;
}

export interface MarkerDetailView {
  date: string;
  side: MarkerSide;
  count: number;
  unit: 'trade' | 'event';
  models: MarkerDetailModel[];
  entries: MarkerDetailEntry[];
  netWeightDelta?: number | null;
}

/**
 * Map a strategy activity marker to the shared detail language. The strategy
 * ledger does not carry a per-trade model id, so the page supplies the one
 * formal run identity that owns the ledger.
 */
export function navMarkerDetail(
  marker: NavMarker,
  model: { modelId: string; label: string },
): MarkerDetailView {
  const trades = Array.isArray(marker.trades) ? marker.trades : [];
  return {
    date: marker.date,
    side: marker.side,
    count: marker.count,
    unit: 'trade',
    models: [{ modelId: model.modelId, label: model.label }],
    entries: trades.map((trade, index) => ({
      key: `${marker.date}:${index}`,
      modelId: model.modelId,
      modelLabel: model.label,
      action: formatEventAction(trade.action),
      ...(trade.instrument === null ? {} : { instrument: trade.instrument }),
      previousWeight: trade.previousWeight,
      targetWeight: trade.targetWeight,
      ...(trade.reason === null ? {} : { reason: trade.reason }),
    })),
    netWeightDelta: marker.netWeightDelta,
  };
}

/**
 * Map the session events selected on a security chart to the shared detail
 * language. Multiple models on one date each keep their own row and color.
 */
export function securityMarkerDetail(
  events: readonly SecurityEvent[],
  options: { labelFor: (modelId: string) => string; colorFor: (modelId: string) => string },
): MarkerDetailView | null {
  if (!Array.isArray(events) || events.length === 0) return null;
  const sides = new Set<'buy' | 'sell'>();
  for (const event of events) {
    const side = markerSideFromAction(event.action);
    if (side !== null) sides.add(side);
  }
  const modelIds = [...new Set(events.map(event => event.model_id))].sort();
  return {
    date: events[0].time,
    side: sides.size === 1 ? [...sides][0] : 'mixed',
    count: events.length,
    unit: 'event',
    models: modelIds.map(modelId => ({
      modelId,
      label: options.labelFor(modelId),
      color: options.colorFor(modelId),
    })),
    entries: events.map((event, index) => ({
      key: `${event.model_id}:${event.time}:${index}`,
      modelId: event.model_id,
      modelLabel: options.labelFor(event.model_id),
      color: options.colorFor(event.model_id),
      action: formatEventAction(event.action),
      previousWeight: event.previous_weight,
      targetWeight: event.target_weight,
      ...(event.reason
        ? { reason: humanizeEventReason(event.reason), reasonTitle: event.reason }
        : {}),
    })),
  };
}
