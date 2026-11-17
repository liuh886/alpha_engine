import { describe, expect, it } from 'vitest';
import type { NavMarker } from './nav-series';
import type { SecurityEvent } from './security-evidence';
import {
  MARKER_DETAIL_DISCLOSURE,
  MODEL_SERIES_COLORS,
  MODEL_SERIES_OVERFLOW_COLOR,
  formatMarkerDelta,
  formatMarkerWeight,
  markerSideFromAction,
  markerSideLabel,
  modelColorAssignments,
  modelColorIndexMap,
  navMarkerDetail,
  securityMarkerDetail,
} from './chart-markers';

const event = (overrides: Partial<SecurityEvent> = {}): SecurityEvent => ({
  time: '2026-01-05',
  model_id: 'model_a',
  run_id: 'run_1',
  instrument_id: 'us:QQQ',
  action: 'BUY',
  previous_weight: 0,
  target_weight: 0.5,
  reason: 'frozen_rule',
  ...overrides,
});

describe('chart marker presentation model', () => {
  it('maps ledger actions to the shared direction language', () => {
    expect(markerSideFromAction('BUY')).toBe('buy');
    expect(markerSideFromAction('increase')).toBe('buy');
    expect(markerSideFromAction('SELL')).toBe('sell');
    expect(markerSideFromAction('decrease')).toBe('sell');
    expect(markerSideFromAction('HOLD')).toBeNull();
    expect(markerSideLabel('buy')).toBe('Buy / increase');
    expect(markerSideLabel('mixed')).toBe('Buy and sell');
  });

  it('assigns categorical colors by sorted model identity, never by rank', () => {
    const assignments = modelColorAssignments(['model_b', 'model_a', 'model_a']);
    expect(assignments.map(item => item.modelId)).toEqual(['model_a', 'model_b']);
    expect(assignments.map(item => item.color)).toEqual([MODEL_SERIES_COLORS[0], MODEL_SERIES_COLORS[1]]);
    expect(modelColorIndexMap(assignments).get('model_b')).toBe(1);

    // A filter that removes model_a does not repaint model_b: the page keeps
    // the full assignment and filters only the rendered rows.
    const filtered = assignments.filter(item => item.modelId === 'model_b');
    expect(filtered[0].index).toBe(1);
  });

  it('folds identities past the validated five-slot order into a neutral ink color', () => {
    const assignments = modelColorAssignments(['a', 'b', 'c', 'd', 'e', 'f', 'g']);
    expect(assignments.slice(0, 5).every(item => !item.overflow)).toBe(true);
    expect(assignments[5]).toMatchObject({ modelId: 'f', token: null, overflow: true, color: MODEL_SERIES_OVERFLOW_COLOR });
    expect(assignments[6]).toMatchObject({ modelId: 'g', token: null, overflow: true });
  });

  it('formats weights and signed deltas without inventing zero', () => {
    expect(formatMarkerWeight(0.5)).toBe('50.0%');
    expect(formatMarkerWeight(null)).toBe('—');
    expect(formatMarkerDelta(0.5)).toBe('+50.0%');
    expect(formatMarkerDelta(-0.125)).toBe('-12.5%');
  });

  it('keeps every model and weight in a shared-date security detail', () => {
    const detail = securityMarkerDetail([
      event({ model_id: 'model_b', action: 'SELL', previous_weight: 0.4, target_weight: 0, reason: 'exit' }),
      event({ model_id: 'model_a', action: 'INCREASE', previous_weight: 0.1, target_weight: 0.3 }),
    ], {
      labelFor: id => id === 'model_a' ? 'Model A' : 'Model B',
      colorFor: id => id === 'model_a' ? 'red' : 'blue',
    });
    expect(detail).not.toBeNull();
    expect(detail!.side).toBe('mixed');
    expect(detail!.count).toBe(2);
    expect(detail!.models.map(model => model.label).sort()).toEqual(['Model A', 'Model B']);
    const increase = detail!.entries.find(entry => entry.action === 'Increase');
    expect(increase).toMatchObject({
      modelId: 'model_a',
      modelLabel: 'Model A',
      color: 'red',
      previousWeight: 0.1,
      targetWeight: 0.3,
    });
    const exit = detail!.entries.find(entry => entry.action === 'Sell');
    expect(exit).toMatchObject({ modelLabel: 'Model B', reason: 'Exit', reasonTitle: 'exit' });
    expect(MARKER_DETAIL_DISCLOSURE).toContain('do not establish an execution price');
  });

  it('maps strategy trades to the same detail fields', () => {
    const marker: NavMarker = {
      date: '2026-01-11',
      side: 'buy',
      count: 1,
      instruments: ['AAPL'],
      netWeightDelta: 0.5,
      reasons: ['momentum'],
      trades: [{ action: 'BUY', instrument: 'AAPL', previousWeight: 0, targetWeight: 0.5, reason: 'momentum' }],
    };
    const detail = navMarkerDetail(marker, { modelId: 'qqq_v1', label: 'QQQ Rotation' });
    expect(detail).toMatchObject({ date: '2026-01-11', side: 'buy', count: 1, unit: 'trade', netWeightDelta: 0.5 });
    expect(detail.models).toEqual([{ modelId: 'qqq_v1', label: 'QQQ Rotation' }]);
    expect(detail.entries[0]).toMatchObject({
      modelId: 'qqq_v1',
      action: 'Buy',
      instrument: 'AAPL',
      previousWeight: 0,
      targetWeight: 0.5,
      reason: 'momentum',
    });
  });

  it('returns no detail for an empty selection', () => {
    expect(securityMarkerDetail([], { labelFor: id => id, colorFor: () => 'blue' })).toBeNull();
  });
});
