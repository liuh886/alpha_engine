import { useEffect, useState } from 'react';
import { loadSecurityCatalog, resolveSecurity, securityHref } from '@/lib/security-evidence';

export type SecurityLinkStatus = 'loading' | 'resolved' | 'unresolved';

export interface SecurityLinkResolution {
  status: SecurityLinkStatus;
  /** Canonical in-app route once the catalog resolves the symbol. */
  href: string | null;
  /** Short visible fallback reason; never a dead link. */
  reason: string | null;
  /** Full retained diagnostic, for the element title. */
  detail: string | null;
}

const LOADING: SecurityLinkResolution = { status: 'loading', href: null, reason: null, detail: null };

function unavailable(detail: string, reason: string): SecurityLinkResolution {
  return { status: 'unresolved', href: null, reason, detail };
}

/**
 * Resolve one instrument against its own market's governed price catalog. The
 * catalog is read once per market for the page lifetime (the module cache
 * deduplicates reads) and only a resolved symbol becomes a route. A same-market
 * catalog can never resolve another market's instrument, so this hook cannot
 * create a cross-market link.
 */
export function useSecurityLink(
  market: string | undefined,
  instrument: string,
  model?: string,
): SecurityLinkResolution {
  const [resolution, setResolution] = useState<SecurityLinkResolution>(LOADING);

  useEffect(() => {
    if (market !== 'us' && market !== 'cn') {
      setResolution(unavailable('A market evidence catalog is not published for this market.', 'No governed market'));
      return;
    }
    let active = true;
    setResolution(LOADING);
    void loadSecurityCatalog(market)
      .then(catalog => {
        if (!active) return;
        try {
          const symbol = resolveSecurity(catalog, instrument);
          const href = securityHref(market, symbol.symbol, model);
          setResolution({ status: 'resolved', href, reason: null, detail: null });
        } catch (error) {
          const detail = error instanceof Error ? error.message : String(error);
          const reason = /unambiguous/i.test(detail) ? 'Ambiguous published history' : 'No published price history';
          setResolution(unavailable(detail, reason));
        }
      })
      .catch(error => {
        if (!active) return;
        const detail = error instanceof Error ? error.message : String(error);
        setResolution(unavailable(`Market evidence catalog unavailable. ${detail}`, 'Price catalog unavailable'));
      });
    return () => { active = false; };
  }, [market, instrument, model]);

  return resolution;
}
