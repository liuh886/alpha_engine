import { describe, expect, it } from 'vitest';
import type { SecurityBar, SecurityEvent } from './security-evidence';
import { securityMarkers, unmatchedMarkerEvents } from './security-markers';

const bars: Array<Pick<SecurityBar, 'time'>> = [
  { time: '2026-01-02' },
  { time: '2026-01-05' },
  { time: '2026-01-06' },
];

const event = (overrides: Partial<SecurityEvent> = {}): SecurityEvent => ({
  time: '2026-01-05',
  model_id: 'model_a',
  run_id: 'run_1',
  instrument_id: 'us:QQQ',
  action: 'BUY',
  previous_weight: 0,
  target_weight: 0.5,
  reason: 'frozen rule',
  ...overrides,
});

describe('security markers', () => {
  it('groups one marker per exact date and direction on observed sessions', () => {
    const markers = securityMarkers(bars, [
      event(),
      event({ model_id: 'model_b' }),
      event({ action: 'INCREASE' }),
      event({ action: 'SELL' }),
    ]);
    expect(markers).toHaveLength(2);
    expect(markers[0]).toMatchObject({ time: '2026-01-05', positive: true });
    expect(markers[0].events).toHaveLength(3);
    expect(markers[1]).toMatchObject({ time: '2026-01-05', positive: false });
    expect(markers[1].events).toHaveLength(1);
  });

  it('never moves or invents dates for events without a matching bar', () => {
    const events = [event({ time: '2026-01-03' }), event({ time: '2026-01-05' })];
    const markers = securityMarkers(bars, events);
    expect(markers.map(marker => marker.time)).toEqual(['2026-01-05']);
    expect(events[0].time).toBe('2026-01-03');
    expect(unmatchedMarkerEvents(bars, events)).toEqual([events[0]]);
  });

  it('orders markers by date and then buy before sell deterministically', () => {
    const markers = securityMarkers(bars, [
      event({ time: '2026-01-06', action: 'SELL' }),
      event({ time: '2026-01-05', action: 'SELL' }),
      event({ time: '2026-01-05', action: 'BUY' }),
    ]);
    expect(markers.map(marker => `${marker.time}:${marker.positive ? 'buy' : 'sell'}`)).toEqual([
      '2026-01-05:buy',
      '2026-01-05:sell',
      '2026-01-06:sell',
    ]);
  });
});
