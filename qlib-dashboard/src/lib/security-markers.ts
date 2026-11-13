import type { SecurityBar, SecurityEvent } from './security-evidence';

/**
 * One chart marker stands for every exact ledger event of the same direction on
 * the same observed session. Buy/increase and sell/decrease never collapse into
 * each other, and an event without a matching price bar is never plotted.
 */
export interface SecurityMarker {
  time: string;
  positive: boolean;
  events: SecurityEvent[];
}

/**
 * Group exact ledger events by observed session and direction. Marker dates are
 * the retained ledger dates: no snapping, interpolation or synthetic sessions.
 */
export function securityMarkers(
  bars: readonly Pick<SecurityBar, 'time'>[],
  events: readonly SecurityEvent[],
): SecurityMarker[] {
  const dates = new Set(bars.map(bar => bar.time));
  const groups = new Map<string, SecurityMarker>();
  for (const event of events) {
    if (!dates.has(event.time)) continue;
    const positive = event.action === 'BUY' || event.action === 'INCREASE';
    const key = `${event.time}:${positive ? 'buy' : 'sell'}`;
    const group = groups.get(key) ?? { time: event.time, positive, events: [] };
    group.events.push(event);
    groups.set(key, group);
  }
  return [...groups.values()].sort(
    (left, right) => left.time.localeCompare(right.time) || Number(right.positive) - Number(left.positive),
  );
}

/** Events whose exact ledger date has no matching bar in the supplied coverage. */
export function unmatchedMarkerEvents(
  bars: readonly Pick<SecurityBar, 'time'>[],
  events: readonly SecurityEvent[],
): SecurityEvent[] {
  const dates = new Set(bars.map(bar => bar.time));
  return events.filter(event => !dates.has(event.time));
}
