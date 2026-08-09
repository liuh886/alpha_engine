import { useEffect, useState } from 'react';

interface AccountSnapshot {
  loading?: boolean;
  isPro?: boolean;
  user?: { id?: string } | null;
}

interface HaoAccountApi {
  getState?: () => AccountSnapshot;
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

  return {
    loading: snapshot.loading === true,
    isPro: snapshot.isPro === true,
    signedIn: Boolean(snapshot.user?.id),
    openAccount: () => window.HaoAccount?.open?.(),
  };
}
