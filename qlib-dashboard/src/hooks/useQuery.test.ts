/**
 * Tests for useQuery — loading, error, data, enabled, refetch, and abort.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { useQuery } from './useQuery';

// Helper: create a fetcher that resolves after a delay.
function delayedFetcher<T>(data: T, delayMs = 0) {
  return (_signal: AbortSignal) =>
    new Promise<T>((resolve) => setTimeout(() => resolve(data), delayMs));
}

// Helper: create a fetcher that rejects.
function failingFetcher(message: string, delayMs = 0) {
  return (_signal: AbortSignal) =>
    new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error(message)), delayMs),
    );
}

describe('useQuery', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // -----------------------------------------------------------------------
  // Initial state
  // -----------------------------------------------------------------------

  it('starts with loading=true and null data when enabled', () => {
    const { result } = renderHook(() =>
      useQuery({ fetcher: delayedFetcher('hello', 100) }),
    );

    expect(result.current.loading).toBe(true);
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('starts with loading=false when enabled=false', () => {
    const { result } = renderHook(() =>
      useQuery({ fetcher: delayedFetcher('hello'), enabled: false }),
    );

    expect(result.current.loading).toBe(false);
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();
  });

  // -----------------------------------------------------------------------
  // Data resolution
  // -----------------------------------------------------------------------

  it('sets data and clears loading on success', async () => {
    const { result } = renderHook(() =>
      useQuery({ fetcher: delayedFetcher({ value: 42 }, 50) }),
    );

    await act(async () => {
      vi.advanceTimersByTime(50);
    });

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
      expect(result.current.data).toEqual({ value: 42 });
      expect(result.current.error).toBeNull();
    });
  });

  // -----------------------------------------------------------------------
  // Error handling
  // -----------------------------------------------------------------------

  it('sets error string on fetcher rejection', async () => {
    const { result } = renderHook(() =>
      useQuery({ fetcher: failingFetcher('Network down', 50) }),
    );

    await act(async () => {
      vi.advanceTimersByTime(50);
    });

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBe('Network down');
      expect(result.current.data).toBeNull();
    });
  });

  it('clears error on subsequent successful fetch', async () => {
    let shouldFail = true;
    const fetcher = (_signal: AbortSignal) =>
      new Promise<string>((resolve, reject) => {
        setTimeout(() => {
          if (shouldFail) reject(new Error('fail'));
          else resolve('ok');
        }, 10);
      });

    const { result } = renderHook(() => useQuery({ fetcher }));

    // First fetch fails
    await act(async () => {
      vi.advanceTimersByTime(10);
    });
    await waitFor(() => expect(result.current.error).toBe('fail'));

    // Second fetch succeeds
    shouldFail = false;
    await act(async () => {
      result.current.refetch();
      vi.advanceTimersByTime(10);
    });

    await waitFor(() => {
      expect(result.current.error).toBeNull();
      expect(result.current.data).toBe('ok');
    });
  });

  // -----------------------------------------------------------------------
  // Refetch
  // -----------------------------------------------------------------------

  it('refetch re-executes the fetcher', async () => {
    let callCount = 0;
    const fetcher = (_signal: AbortSignal) =>
      new Promise<number>((resolve) => {
        setTimeout(() => resolve(++callCount), 10);
      });

    const { result } = renderHook(() => useQuery({ fetcher }));

    await act(async () => {
      vi.advanceTimersByTime(10);
    });
    await waitFor(() => expect(result.current.data).toBe(1));

    await act(async () => {
      result.current.refetch();
      vi.advanceTimersByTime(10);
    });

    await waitFor(() => expect(result.current.data).toBe(2));
  });

  // -----------------------------------------------------------------------
  // Enabled toggle
  // -----------------------------------------------------------------------

  it('does not fetch when enabled=false', () => {
    const fetcher = vi.fn(delayedFetcher('x'));
    renderHook(() => useQuery({ fetcher, enabled: false }));

    expect(fetcher).not.toHaveBeenCalled();
  });

  it('refetches when the query key changes', async () => {
    const { result, rerender } = renderHook(
      ({ market }) => useQuery({
        queryKey: market,
        fetcher: () => Promise.resolve(market),
      }),
      { initialProps: { market: 'cn' } },
    );

    await waitFor(() => expect(result.current.data).toBe('cn'));
    rerender({ market: 'us' });
    await waitFor(() => expect(result.current.data).toBe('us'));
  });

  // -----------------------------------------------------------------------
  // Abort on unmount
  // -----------------------------------------------------------------------

  it('aborts the request on unmount', async () => {
    let capturedSignal: AbortSignal | null = null;
    const fetcher = (signal: AbortSignal) => {
      capturedSignal = signal;
      return new Promise<string>(() => {}); // never resolves
    };

    const { unmount } = renderHook(() => useQuery({ fetcher }));

    // Give the effect time to run
    await act(async () => {
      vi.advanceTimersByTime(0);
    });

    unmount();

    expect(capturedSignal).not.toBeNull();
    expect(capturedSignal!.aborted).toBe(true);
  });

  // -----------------------------------------------------------------------
  // Preserves last data during background refetch
  // -----------------------------------------------------------------------

  it('preserves previous data while loading new data', async () => {
    let value = 'first';
    const fetcher = (_signal: AbortSignal) =>
      new Promise<string>((resolve) => {
        setTimeout(() => resolve(value), 10);
      });

    const { result } = renderHook(() => useQuery({ fetcher }));

    await act(async () => {
      vi.advanceTimersByTime(10);
    });
    await waitFor(() => expect(result.current.data).toBe('first'));

    // Trigger refetch with new value
    value = 'second';
    await act(async () => {
      result.current.refetch();
    });

    // While loading, old data should still be present
    expect(result.current.loading).toBe(true);
    expect(result.current.data).toBe('first');

    await act(async () => {
      vi.advanceTimersByTime(10);
    });

    await waitFor(() => {
      expect(result.current.data).toBe('second');
      expect(result.current.loading).toBe(false);
    });
  });
});
