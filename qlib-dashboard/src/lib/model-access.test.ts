import { describe, expect, it } from 'vitest';

import { canAccessTier, mergeAccessPolicies, resolveRequiredTier } from './model-access';

describe('model and module access policy', () => {
  it('orders Guest, Member, Pro and Owner monotonically', () => {
    expect(canAccessTier('public', 'authenticated')).toBe(false);
    expect(canAccessTier('authenticated', 'authenticated')).toBe(true);
    expect(canAccessTier('pro', 'authenticated')).toBe(true);
    expect(canAccessTier('owner', 'pro')).toBe(true);
  });

  it('lets remote policy override safe startup defaults without changing model identity', () => {
    const policies = mergeAccessPolicies([{ productCode: 'alpha_engine', resourceType: 'model', resourceId: 'qqq_rotation', requiredTier: 'authenticated' }]);
    expect(resolveRequiredTier(policies, 'model', 'qqq_rotation')).toBe('authenticated');
    expect(resolveRequiredTier(policies, 'module', 'securities')).toBe('authenticated');
    expect(resolveRequiredTier(policies, 'model', 'us_ranker')).toBe('public');
  });
});
