export type AccessTier = 'public' | 'authenticated' | 'pro' | 'owner';
export type AccessResourceType = 'module' | 'strategy';

export interface AccessPolicy {
  productCode: 'alpha_engine';
  resourceType: AccessResourceType;
  resourceId: string;
  requiredTier: AccessTier;
  updatedAt?: string;
}

export const ACCESS_TIERS: AccessTier[] = ['public', 'authenticated', 'pro', 'owner'];

/** Safe startup policy for independent modules while the remote policy table is unavailable. */
export const DEFAULT_ACCESS_POLICIES: AccessPolicy[] = [
  { productCode: 'alpha_engine', resourceType: 'module', resourceId: 'securities', requiredTier: 'authenticated' },
];

const TIER_RANK: Record<AccessTier, number> = {
  public: 0,
  authenticated: 1,
  pro: 2,
  owner: 3,
};

export function canAccessTier(current: AccessTier, required: AccessTier): boolean {
  return TIER_RANK[current] >= TIER_RANK[required];
}

export function resolveRequiredTier(
  policies: AccessPolicy[],
  resourceType: AccessResourceType,
  resourceId: string,
): AccessTier {
  const declared = policies.find((policy) => policy.resourceType === resourceType && policy.resourceId === resourceId)?.requiredTier;
  if (declared) return declared;
  return resourceType === 'strategy' ? 'owner' : 'public';
}

export function mergeAccessPolicies(remote: AccessPolicy[]): AccessPolicy[] {
  const merged = new Map(DEFAULT_ACCESS_POLICIES.map((policy) => [`${policy.resourceType}:${policy.resourceId}`, policy]));
  remote.forEach((policy) => merged.set(`${policy.resourceType}:${policy.resourceId}`, policy));
  return [...merged.values()];
}
