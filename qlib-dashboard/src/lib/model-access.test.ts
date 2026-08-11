import { describe, expect, it } from 'vitest';

import { canAccessTier, mergeAccessPolicies, resolveRequiredTier } from './model-access';

describe('module access policy', () => {
  it('orders Guest, Member, Pro and Owner monotonically', () => {
    expect(canAccessTier('public', 'authenticated')).toBe(false);
    expect(canAccessTier('authenticated', 'authenticated')).toBe(true);
    expect(canAccessTier('pro', 'authenticated')).toBe(true);
    expect(canAccessTier('owner', 'pro')).toBe(true);
  });

  it('keeps remote policy limited to independent product modules', () => {
    const policies = mergeAccessPolicies([{ productCode: 'alpha_engine', resourceType: 'module', resourceId: 'securities', requiredTier: 'pro' }]);
    expect(resolveRequiredTier(policies, 'module', 'securities')).toBe('pro');
    expect(resolveRequiredTier(policies, 'module', 'unknown')).toBe('public');
  });
});
