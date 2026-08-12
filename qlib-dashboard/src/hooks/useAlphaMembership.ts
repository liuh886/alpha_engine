import { useCallback, useEffect, useState } from 'react';

interface AccountSnapshot {
  loading?: boolean;
  isPro?: boolean;
  entitlements?: string[];
  user?: { id?: string; app_metadata?: Record<string, unknown> } | null;
}

export interface SupabaseAccessClient {
  from: (table: string) => any;
  functions: {
    invoke: <T = unknown>(name: string, options?: { body?: unknown }) => Promise<{ data: T | null; error: { message?: string } | null }>;
  };
}

interface HaoAccountApi {
  getState?: () => AccountSnapshot;
  getClient?: () => Promise<SupabaseAccessClient>;
  open?: () => void;
  subscribe?: (listener: (snapshot: AccountSnapshot) => void) => () => void;
}

declare global {
  interface Window {
    HaoAccount?: HaoAccountApi;
  }
}

function currentSnapshot(): AccountSnapshot {
  return window.HaoAccount?.getState?.() ?? { loading: true, isPro: false, user: null };
}

export function useAlphaMembership() {
  const [snapshot, setSnapshot] = useState<AccountSnapshot>(() => currentSnapshot());

  useEffect(() => {
    const sync = (next?: AccountSnapshot) => setSnapshot(next ?? currentSnapshot());
    const handleAccountChanged = (event: Event) => {
      const detail = (event as CustomEvent<AccountSnapshot>).detail;
      sync(detail);
    };

    window.addEventListener('hao:account-changed', handleAccountChanged);
    const unsubscribe = window.HaoAccount?.subscribe?.(sync);
    sync();

    return () => {
      window.removeEventListener('hao:account-changed', handleAccountChanged);
      unsubscribe?.();
    };
  }, []);

  const openAccount = useCallback(() => window.HaoAccount?.open?.(), []);
  const getClient = useCallback(() => window.HaoAccount?.getClient?.(), []);

  return {
    loading: snapshot.loading === true,
    isPro: snapshot.isPro === true,
    isOwner: snapshot.user?.app_metadata?.alpha_engine_role === 'owner',
    entitlements: Array.isArray(snapshot.entitlements) ? snapshot.entitlements : [],
    userId: snapshot.user?.id ?? null,
    signedIn: Boolean(snapshot.user?.id),
    openAccount,
    getClient,
  };
}
