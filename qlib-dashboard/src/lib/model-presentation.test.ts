import { describe, expect, it } from 'vitest';

import { publicModelDisplayName } from './model-presentation';

describe('public model presentation', () => {
  it('keeps the formal QQQ Rotation version in the public QQQR name', () => {
    expect(publicModelDisplayName('QQQ Rotation v4.3', { modelId: 'qqqi_qqq_tqqq_v4_3' })).toBe('QQQR v4.3');
    expect(publicModelDisplayName('QQQ Rotation v4.4', { modelFamilyId: 'qqq_rotation', modelVersionId: 'qqqi_qqq_tqqq_v4_4' })).toBe('QQQR v4.4');
  });

  it('preserves other public aliases and fallback names', () => {
    expect(publicModelDisplayName('Legacy BYD name', { modelId: 'byd_dividend_sleeve_v1_0' })).toBe('BYD v1.1');
    expect(publicModelDisplayName('US x1.1', { modelId: 'us_x1_1' })).toBe('US x1.1');
  });
});
