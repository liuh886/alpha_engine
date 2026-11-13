import { useCallback, useState } from 'react';
import type { BaselineKind, BaselineMarket } from '@/lib/baseline';

export const BASELINE_PREFERENCE_STORAGE_KEY = 'alpha.baseline-preference.v1';

export interface BaselinePreference {
  us: BaselineKind;
  cn: BaselineKind;
}

const DEFAULT_PREFERENCE: BaselinePreference = { us: 'declared', cn: 'declared' };
const KINDS: ReadonlySet<BaselineKind> = new Set<BaselineKind>(['declared', 'market', 'none']);
const MARKETS: readonly BaselineMarket[] = ['us', 'cn'];

/**
 * localStorage can throw on property access (sandboxed/private contexts) as
 * well as on read/write (disabled storage, quota). Preferences are a per-viewer
 * convenience, so every failure falls back to the default silently.
 */
function safeStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}

function parsePreference(raw: string | null): BaselinePreference {
  if (raw === null) return { ...DEFAULT_PREFERENCE };
  let value: unknown;
  try {
    value = JSON.parse(raw) as unknown;
  } catch {
    return { ...DEFAULT_PREFERENCE };
  }
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return { ...DEFAULT_PREFERENCE };
  const record = value as Record<string, unknown>;
  const preference = { ...DEFAULT_PREFERENCE };
  for (const market of MARKETS) {
    const kind = record[market];
    if (typeof kind === 'string' && KINDS.has(kind as BaselineKind)) preference[market] = kind as BaselineKind;
  }
  return preference;
}

function readPreference(): BaselinePreference {
  const storage = safeStorage();
  if (storage === null) return { ...DEFAULT_PREFERENCE };
  try {
    return parsePreference(storage.getItem(BASELINE_PREFERENCE_STORAGE_KEY));
  } catch {
    return { ...DEFAULT_PREFERENCE };
  }
}

function writePreference(preference: BaselinePreference): void {
  const storage = safeStorage();
  if (storage === null) return;
  try {
    storage.setItem(BASELINE_PREFERENCE_STORAGE_KEY, JSON.stringify(preference));
  } catch {
    // Quota or disabled storage: keep the in-memory preference for this view.
  }
}

/** Per-market baseline preference, persisted locally with hardened access. */
export function useBaselinePreference() {
  const [preference, setPreferenceState] = useState<BaselinePreference>(readPreference);

  const setPreference = useCallback((market: BaselineMarket, kind: BaselineKind) => {
    if (!KINDS.has(kind)) return;
    setPreferenceState(previous => {
      if (previous[market] === kind) return previous;
      const next = { ...previous, [market]: kind };
      writePreference(next);
      return next;
    });
  }, []);

  return { preference, setPreference };
}
