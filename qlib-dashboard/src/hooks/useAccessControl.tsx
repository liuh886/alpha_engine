import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import {
  canAccessTier,
  DEFAULT_ACCESS_POLICIES,
  mergeAccessPolicies,
  resolveRequiredTier,
  type AccessPolicy,
  type AccessResourceType,
  type AccessTier,
} from '@/lib/model-access';
import { useAlphaMembership, type SupabaseAccessClient } from './useAlphaMembership';

interface AccessControlValue {
  loading: boolean;
  policyLoading: boolean;
  policyError: string | null;
  tier: AccessTier;
  signedIn: boolean;
  isPro: boolean;
  isOwner: boolean;
  policies: AccessPolicy[];
  openAccount: () => void;
  getClient: () => Promise<SupabaseAccessClient | undefined>;
  canAccess: (required: AccessTier) => boolean;
  requiredTier: (type: AccessResourceType, id: string) => AccessTier;
  savePolicy: (type: AccessResourceType, id: string, tier: AccessTier) => Promise<void>;
  reloadPolicies: () => Promise<void>;
}

const AccessControlContext = createContext<AccessControlValue | null>(null);

function parsePolicies(rows: unknown): AccessPolicy[] {
  if (!Array.isArray(rows)) return [];
  return rows.flatMap((row) => {
    if (!row || typeof row !== 'object') return [];
    const value = row as Record<string, unknown>;
    const resourceType = String(value.resource_type);
    const requiredTier = String(value.required_tier) as AccessTier;
    if (!['module', 'strategy'].includes(resourceType) || !['public', 'authenticated', 'pro', 'owner'].includes(requiredTier)) return [];
    const resourceId = String(value.resource_id ?? '');
    if (!resourceId) return [];
    return [{
      productCode: 'alpha_engine' as const,
      resourceType: resourceType as AccessResourceType,
      resourceId,
      requiredTier,
      updatedAt: typeof value.updated_at === 'string' ? value.updated_at : undefined,
    }];
  });
}

export function AccessControlProvider({ children }: { children: ReactNode }) {
  const membership = useAlphaMembership();
  const [policies, setPolicies] = useState<AccessPolicy[]>(DEFAULT_ACCESS_POLICIES);
  const [policyLoading, setPolicyLoading] = useState(true);
  const [policyError, setPolicyError] = useState<string | null>(null);

  const tier: AccessTier = membership.isOwner
    ? 'owner'
    : membership.isPro
      ? 'pro'
      : membership.signedIn
        ? 'authenticated'
        : 'public';

  const reloadPolicies = useCallback(async () => {
    setPolicyLoading(true);
    setPolicyError(null);
    try {
      const client = await membership.getClient();
      if (!client) throw new Error('Shared account client is unavailable.');
      const { data, error } = await client
        .from('product_access_policies')
        .select('product_code,resource_type,resource_id,required_tier,updated_at')
        .eq('product_code', 'alpha_engine');
      if (error) throw error;
      setPolicies(mergeAccessPolicies(parsePolicies(data)));
    } catch (error) {
      setPolicies(DEFAULT_ACCESS_POLICIES);
      setPolicyError(error instanceof Error ? error.message : String(error));
    } finally {
      setPolicyLoading(false);
    }
  }, [membership.getClient]);

  useEffect(() => {
    if (membership.loading) return;
    void reloadPolicies();
  }, [membership.loading, reloadPolicies]);

  const requiredTier = useCallback(
    (type: AccessResourceType, id: string) => resolveRequiredTier(policies, type, id),
    [policies],
  );

  const savePolicy = useCallback(async (type: AccessResourceType, id: string, required: AccessTier) => {
    if (!membership.isOwner || !membership.userId) throw new Error('Owner access is required.');
    const client = await membership.getClient();
    if (!client) throw new Error('Shared account client is unavailable.');
    const { error } = await client.from('product_access_policies').upsert({
      product_code: 'alpha_engine',
      resource_type: type,
      resource_id: id,
      required_tier: required,
      updated_by: membership.userId,
      updated_at: new Date().toISOString(),
    }, { onConflict: 'product_code,resource_type,resource_id' });
    if (error) throw error;
    await reloadPolicies();
  }, [membership.getClient, membership.isOwner, membership.userId, reloadPolicies]);

  const value = useMemo<AccessControlValue>(() => ({
    loading: membership.loading || policyLoading,
    policyLoading,
    policyError,
    tier,
    signedIn: membership.signedIn,
    isPro: membership.isPro,
    isOwner: membership.isOwner,
    policies,
    openAccount: membership.openAccount,
    getClient: membership.getClient,
    canAccess: (required) => canAccessTier(tier, required),
    requiredTier,
    savePolicy,
    reloadPolicies,
  }), [membership.getClient, membership.loading, membership.openAccount, membership.isOwner, membership.isPro, membership.signedIn, policies, policyError, policyLoading, reloadPolicies, requiredTier, savePolicy, tier]);

  return <AccessControlContext.Provider value={value}>{children}</AccessControlContext.Provider>;
}

export function useAccessControl(): AccessControlValue {
  const value = useContext(AccessControlContext);
  if (!value) throw new Error('useAccessControl must be used within AccessControlProvider.');
  return value;
}
