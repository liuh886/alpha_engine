import { useState, useRef, useCallback } from "react";

export interface UseMutationOptions<T, V> {
  /** Async function that performs the mutation. */
  mutateFn: (variables: V) => Promise<T>;
  /** Called with the result after a successful mutation. */
  onSuccess?: (data: T, variables: V) => void;
  /** Called with the error after a failed mutation. */
  onError?: (error: string, variables: V) => void;
}

export interface UseMutationResult<T, V> {
  /** Fire the mutation. Duplicate calls while running are silently ignored. */
  mutate: (variables: V) => void;
  /** True while a mutation is in flight. */
  loading: boolean;
  /** The most recent error, or null. */
  error: string | null;
  /** The most recent successful result, or null. */
  data: T | null;
  /** Reset error and data to their initial states. */
  reset: () => void;
}

/**
 * Lightweight mutation hook.
 *
 * - Prevents duplicate submissions while a request is in flight.
 * - Supports `onSuccess` / `onError` callbacks.
 * - Returns `{ mutate, loading, error, data, reset }`.
 */
export function useMutation<T, V = void>({
  mutateFn,
  onSuccess,
  onError,
}: UseMutationOptions<T, V>): UseMutationResult<T, V> {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<T | null>(null);

  // Guard against double-fire (e.g. rapid clicks).
  const inFlightRef = useRef(false);

  // Keep callbacks in refs so changing them doesn't require re-creating mutate.
  const onSuccessRef = useRef(onSuccess);
  onSuccessRef.current = onSuccess;
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;
  const mutateFnRef = useRef(mutateFn);
  mutateFnRef.current = mutateFn;

  const mutate = useCallback(
    (variables: V) => {
      if (inFlightRef.current) return;
      inFlightRef.current = true;
      setLoading(true);
      setError(null);

      mutateFnRef
        .current(variables)
        .then((result) => {
          setData(result);
          setError(null);
          onSuccessRef.current?.(result, variables);
        })
        .catch((err: unknown) => {
          const msg = err instanceof Error ? err.message : String(err);
          setError(msg);
          onErrorRef.current?.(msg, variables);
        })
        .finally(() => {
          setLoading(false);
          inFlightRef.current = false;
        });
    },
    [],
  );

  const reset = useCallback(() => {
    setError(null);
    setData(null);
  }, []);

  return { mutate, loading, error, data, reset };
}
