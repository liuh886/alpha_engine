import { describe, expect, it } from 'vitest';
import { overlayPaneKey, toLightweightOverlayData, type SecurityChartOverlay } from './security-chart-extensions';

describe('security chart overlay extension point', () => {
  it('maps price and volume overlays to the main pane and indicator overlays to named panes', () => {
    expect(overlayPaneKey({ pane: 'price' })).toBe('__main__');
    expect(overlayPaneKey({ pane: 'volume' })).toBe('__main__');
    expect(overlayPaneKey({ pane: 'indicator' })).toBe('indicator');
    expect(overlayPaneKey({ pane: 'indicator', paneId: 'oscillator' })).toBe('oscillator');
  });

  it('passes exact finite observations through and never fills a missing point', () => {
    const overlay: Pick<SecurityChartOverlay, 'data'> = {
      data: [
        { time: '2026-01-02', value: 100 },
        { time: '2026-01-03', value: Number.NaN },
        { time: '', value: 101 },
        { time: '2026-01-05', value: 102, color: '#123456' },
      ],
    };
    expect(toLightweightOverlayData(overlay)).toEqual([
      { time: '2026-01-02', value: 100 },
      { time: '2026-01-05', value: 102, color: '#123456' },
    ]);
  });
});
