import { describe, expect, it } from 'vitest';

import {
  canAccessTier,
  mergeAccessPolicies,
  resolveRequiredTier,
  type AccessPolicy,
} from './model-access';

function strategyPolicy(resourceId: string, requiredTier: AccessPolicy['requiredTier']): AccessPolicy {
  return {
    productCode: 'alpha_engine',
    resourceType: 'strategy',
    resourceId,
    requiredTier,
  };
}

describe('access policy', () => {
  it('orders Public, Member, Pro and Owner monotonically', () => {
    expect(canAccessTier('public', 'authenticated')).toBe(false);
    expect(canAccessTier('authenticated', 'authenticated')).toBe(true);
    expect(canAccessTier('pro', 'authenticated')).toBe(true);
    expect(canAccessTier('owner', 'pro')).toBe(true);
  });

  it('keeps remote policy support for independent product modules', () => {
    const policies = mergeAccessPolicies([{ productCode: 'alpha_engine', resourceType: 'module', resourceId: 'securities', requiredTier: 'pro' }]);
    expect(resolveRequiredTier(policies, 'module', 'securities')).toBe('pro');
    expect(resolveRequiredTier(policies, 'module', 'unknown')).toBe('public');
  });

  it('fails a missing strategy policy closed to Owner', () => {
    expect(resolveRequiredTier([], 'strategy', 'future_strategy')).toBe('owner');
  });

  it('resolves every strategy tier by stable strategy id without model-specific branches', () => {
    const policies = [
      strategyPolicy('strategy_public', 'public'),
      strategyPolicy('strategy_member', 'authenticated'),
      strategyPolicy('strategy_pro', 'pro'),
      strategyPolicy('strategy_owner', 'owner'),
    ];

    expect(resolveRequiredTier(policies, 'strategy', 'strategy_public')).toBe('public');
    expect(resolveRequiredTier(policies, 'strategy', 'strategy_member')).toBe('authenticated');
    expect(resolveRequiredTier(policies, 'strategy', 'strategy_pro')).toBe('pro');
    expect(resolveRequiredTier(policies, 'strategy', 'strategy_owner')).toBe('owner');
  });
});
