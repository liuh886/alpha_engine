/**
 * Hook to fetch and cache ticker-to-name mapping.
 * Maps stock codes like "002594" to human-readable names like "比亚迪".
 */
import { useState, useEffect } from 'react';
import { apiFetch } from './api';

let cachedNameMap: Record<string, string> | null = null;

export function useNameMap() {
  const [nameMap, setNameMap] = useState<Record<string, string>>(cachedNameMap || {});

  useEffect(() => {
    if (cachedNameMap) {
      setNameMap(cachedNameMap);
      return;
    }

    const fetchNameMap = async () => {
      try {
        const resp = await apiFetch('/api/data/name-map', { cache: 'force-cache' });
        const json = await resp.json().catch(() => ({}));
        if (resp.ok && json.ok) {
          cachedNameMap = json.name_map || {};
          setNameMap(cachedNameMap ?? {});
        }
      } catch {
        // silent
      }
    };

    fetchNameMap();
  }, []);

  /** Get display name for a ticker. Returns name if available, otherwise ticker. */
  const getName = (ticker: string): string => {
    if (!ticker) return '';
    const clean = ticker.split('.')[0].toUpperCase();
    return nameMap[clean] || nameMap[ticker.toUpperCase()] || ticker;
  };

  return { nameMap, getName };
}
