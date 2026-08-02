import { useEffect, useState } from 'react';
import { getActiveResearchBundle, subscribeResearchBundle } from './research-bundle';

async function loadDeclaredNameMap(): Promise<Record<string, string>> {
  const bundle = getActiveResearchBundle();
  if (!bundle) return {};

  const artifact = bundle.manifest.artifacts.find((candidate) =>
    candidate.kind === 'name_map'
    || candidate.path.endsWith('/name-map.json')
    || candidate.path.endsWith('/name_map.json'),
  );
  if (!artifact) return {};

  try {
    const blob = await bundle.source.read(artifact.path);
    const payload = JSON.parse(await blob.text()) as unknown;
    if (!payload || typeof payload !== 'object') return {};
    const value = (payload as Record<string, unknown>).name_map ?? payload;
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .filter(([, name]) => typeof name === 'string')
        .map(([symbol, name]) => [symbol.toUpperCase(), String(name)]),
    );
  } catch {
    return {};
  }
}

/**
 * Resolve optional display names from a manifest-declared bundle artifact.
 * Missing name evidence falls back to the original ticker; no server lookup is
 * attempted.
 */
export function useNameMap() {
  const [nameMap, setNameMap] = useState<Record<string, string>>({});

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      const next = await loadDeclaredNameMap();
      if (active) setNameMap(next);
    };
    void refresh();
    const unsubscribe = subscribeResearchBundle(() => void refresh());
    return () => {
      active = false;
      unsubscribe();
    };
  }, []);

  const getName = (ticker: string): string => {
    if (!ticker) return '';
    const clean = ticker.split('.')[0].toUpperCase();
    return nameMap[clean] || nameMap[ticker.toUpperCase()] || ticker;
  };

  return { nameMap, getName };
}
