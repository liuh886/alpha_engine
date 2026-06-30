import { useState, useEffect, useRef, useCallback } from "react";

export interface UseQueryOptions<T> {
  /** Async fetcher function. Receives an AbortSignal for cancellation. */
  fetcher: (signal: AbortSignal) => Promise<T>;
  /** If false, the query will not execute. Defaults to true. */
  enabled?: boolean;
  /** Stable primitive identity that triggers a new request when it changes. */
  queryKey?: string | number | boolean | null;
}

export interface UseQueryResult<T> {
  /** The most recent successfully fetched data, or null if never fetched. */
  data: T | null;
  /** True while a request is in flight (includes background refetches). */
  loading: boolean;
  /** The most recent error, or null if the last request succeeded. */
  error: string | null;
  /** Manually trigger a refetch. */
  refetch: () => void;
}

/**
 * Lightweight data-fetching hook.
 *
 * - Returns `{ data, loading, error, refetch }`.
 * - Automatically aborts the in-flight request when the component unmounts
 *   or when `fetcher` / `enabled` changes.
 * - Preserves the last valid `data` during background refetches so the UI
 *   never flashes to an empty state on refresh.
 * - Clears stale `data` to `null` when `enabled` becomes false, preventing
 *   a previous query's data from leaking into a subsequent render cycle.
 */
export function useQuery<T>({
  fetcher,
  enabled = true,
  queryKey = null,
}: UseQueryOptions<T>): UseQueryResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Track the latest fetcher in a ref so the effect doesn't re-run on every
  // render when the caller passes an inline arrow function.
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const [trigger, setTrigger] = useState(0);

  const refetch = useCallback(() => {
    setError(null);
    setTrigger((n) => n + 1);
  }, []);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      // Clear stale data so the next enabled=true cycle starts clean.
      // Without this, the previous model's data would remain visible
      // during the transition between query keys.
      setData(null);
      return;
    }

    const controller = new AbortController();
    let cancelled = false;

    setLoading(true);
    setError(null);

    fetcherRef
      .current(controller.signal)
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          // AbortError is expected when we cancel — don't surface it.
          if (err instanceof DOMException && err.name === "AbortError") return;
          setError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
    // `trigger` is intentionally included so refetch() re-runs the effect.
  }, [enabled, queryKey, trigger]);

  return { data, loading, error, refetch };
}
