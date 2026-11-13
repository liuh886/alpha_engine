import type { Page } from '@playwright/test';

export interface MembershipFixture {
  loading: boolean;
  isPro: boolean;
  user: { id: string; app_metadata?: { alpha_engine_role?: string } } | null;
}

/**
 * Install the account shell used by the static release contract: an empty
 * account script plus a deterministic access-policy reader. Tests that need
 * current operations layer their own runtime fixture on top.
 */
export async function installMembershipFixture(page: Page, initial: MembershipFixture): Promise<void> {
  await page.route('**/admin/shared/account-shell.js*', (route) => route.fulfill({ status: 200, contentType: 'application/javascript', body: '' }));
  await page.addInitScript((snapshot) => {
    let current = snapshot;
    const listeners = new Set<(value: MembershipFixture) => void>();
    const policies = [
      { product_code: 'alpha_engine', resource_type: 'module', resource_id: 'securities', required_tier: 'authenticated', updated_at: '2026-08-12T00:00:00Z' },
      { product_code: 'alpha_engine', resource_type: 'strategy', resource_id: 'qqq_rotation', required_tier: 'pro', updated_at: '2026-08-12T00:00:00Z' },
      { product_code: 'alpha_engine', resource_type: 'strategy', resource_id: 'us_x', required_tier: 'public', updated_at: '2026-08-12T00:00:00Z' },
      { product_code: 'alpha_engine', resource_type: 'strategy', resource_id: 'cn_x', required_tier: 'public', updated_at: '2026-08-12T00:00:00Z' },
      { product_code: 'alpha_engine', resource_type: 'strategy', resource_id: 'byd', required_tier: 'public', updated_at: '2026-08-12T00:00:00Z' },
    ];
    (window as any).HaoAccount = {
      getState: () => current,
      open: () => undefined,
      subscribe: (listener: (value: MembershipFixture) => void) => {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
      getClient: async () => ({
        from: (table: string) => {
          if (table === 'product_access_policies') {
            return {
              select: () => ({
                eq: async () => ({ data: policies, error: null }),
              }),
            };
          }
          return {
            select: () => {
              const query: any = {
                eq: () => query,
                maybeSingle: async () => ({ data: null, error: null }),
              };
              return query;
            },
            upsert: async () => ({ error: null }),
          };
        },
      }),
    };
    (window as any).__setAlphaMembership = (next: MembershipFixture) => {
      current = next;
      listeners.forEach((listener) => listener(current));
    };
  }, initial);
}
