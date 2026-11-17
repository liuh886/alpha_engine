import type { SecurityBar, SecurityEvent } from './security-evidence';

/**
 * Events from one model inside one marker cluster. The model identity is kept
 * so the chart can color each model's marker and the detail panel can name it;
 * it is never collapsed into an anonymous event list.
 */
export interface SecurityMarkerModel {
  modelId: string;
  events: SecurityEvent[];
}

/**
 * One chart marker stands for every exact ledger event of the same direction on
 * the same observed session. Buy/increase and sell/decrease never collapse into
 * each other, an event without a matching price bar is never plotted, and the
 * models inside a shared session/direction stay separately attributable.
 */
export interface SecurityMarker {
  time: string;
  positive: boolean;
  events: SecurityEvent[];
  models: SecurityMarkerModel[];
}

const ACTION_ORDER: Readonly<Record<SecurityEvent['action'], number>> = {
  BUY: 0,
  INCREASE: 1,
  SELL: 2,
  DECREASE: 3,
};

function orderedEvents(events: SecurityEvent[]): SecurityEvent[] {
  return events.slice().sort((left, right) =>
    (ACTION_ORDER[left.action] ?? 99) - (ACTION_ORDER[right.action] ?? 99)
    || left.run_id.localeCompare(right.run_id)
    || left.model_id.localeCompare(right.model_id),
  );
}

interface MarkerGroup {
  time: string;
  positive: boolean;
  byModel: Map<string, SecurityEvent[]>;
}

/**
 * Group exact ledger events by observed session and direction, then retain
 * per-model attribution inside the cluster. Marker dates are the retained
 * ledger dates: no snapping, interpolation or synthetic sessions.
 */
export function securityMarkers(
  bars: readonly Pick<SecurityBar, 'time'>[],
  events: readonly SecurityEvent[],
): SecurityMarker[] {
  const dates = new Set(bars.map(bar => bar.time));
  const groups = new Map<string, MarkerGroup>();
  for (const event of events) {
    if (!dates.has(event.time)) continue;
    const positive = event.action === 'BUY' || event.action === 'INCREASE';
    const key = `${event.time}:${positive ? 'buy' : 'sell'}`;
    const group = groups.get(key) ?? { time: event.time, positive, byModel: new Map<string, SecurityEvent[]>() };
    const model = group.byModel.get(event.model_id) ?? [];
    model.push(event);
    group.byModel.set(event.model_id, model);
    groups.set(key, group);
  }
  return [...groups.values()]
    .map(group => {
      const models = [...group.byModel.entries()]
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([modelId, modelEvents]) => ({ modelId, events: orderedEvents(modelEvents) }));
      return {
        time: group.time,
        positive: group.positive,
        events: models.flatMap(model => model.events),
        models,
      };
    })
    .sort(
      (left, right) => left.time.localeCompare(right.time) || Number(right.positive) - Number(left.positive),
    );
}

/** Stable model ids inside one marker cluster, in display order. */
export function securityMarkerModelIds(marker: SecurityMarker): string[] {
  return marker.models.map(model => model.modelId);
}

/** Events whose exact ledger date has no matching bar in the supplied coverage. */
export function unmatchedMarkerEvents(
  bars: readonly Pick<SecurityBar, 'time'>[],
  events: readonly SecurityEvent[],
): SecurityEvent[] {
  const dates = new Set(bars.map(bar => bar.time));
  return events.filter(event => !dates.has(event.time));
}
