import { describe, expect, it } from 'vitest';

import { publicModelDisplayName, QQQR_DISPLAY_NAME } from './model-presentation';

describe('public model presentation', () => {
  it('presents every QQQ Rotation version as QQQR without changing its identity', () => {
    expect(publicModelDisplayName('QQQ Rotation v4.3', { modelId: 'qqqi_qqq_tqqq_v4_3' })).toBe(QQQR_DISPLAY_NAME);
    expect(publicModelDisplayName('Future verbose name', { modelFamilyId: 'qqq_rotation', modelVersionId: 'future-version' })).toBe(QQQR_DISPLAY_NAME);
  });

  it('preserves other public aliases and fallback names', () => {
    expect(publicModelDisplayName('Legacy BYD name', { modelId: 'byd_dividend_sleeve_v1_0' })).toBe('BYD v1.1');
    expect(publicModelDisplayName('US x1.1', { modelId: 'us_x1_1' })).toBe('US x1.1');
  });
});
