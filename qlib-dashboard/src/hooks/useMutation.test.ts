/**
 * Tests for useMutation — duplicate prevention, callbacks, error handling, reset.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { useMutation } from './useMutation';

// Helper: mutation function that resolves after a delay.
function delayedMutator<T>(data: T, delayMs = 0) {
  return () => new Promise<T>((resolve) => setTimeout(() => resolve(data), delayMs));
}

// Helper: mutation function that rejects.
function failingMutator(message: string, delayMs = 0) {
  return () =>
    new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error(message)), delayMs),
    );
}

describe('useMutation', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // -----------------------------------------------------------------------
  // Initial state
  // -----------------------------------------------------------------------

  it('starts with loading=false, error=null, data=null', () => {
    const { result } = renderHook(() =>
      useMutation({ mutateFn: delayedMutator('ok') }),
    );

    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.data).toBeNull();
  });

  // -----------------------------------------------------------------------
  // Successful mutation
  // -----------------------------------------------------------------------

  it('sets data on success', async () => {
    const onSuccess = vi.fn();
    const { result } = renderHook(() =>
      useMutation({ mutateFn: delayedMutator({ id: 1 }, 50), onSuccess }),
    );

    act(() => {
      result.current.mutate(undefined);
    });

    expect(result.current.loading).toBe(true);

    await act(async () => {
      vi.advanceTimersByTime(50);
    });

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
      expect(result.current.data).toEqual({ id: 1 });
      expect(result.current.error).toBeNull();
      expect(onSuccess).toHaveBeenCalledWith({ id: 1 }, undefined);
    });
  });

  // -----------------------------------------------------------------------
  // Error handling
  // -----------------------------------------------------------------------

  it('sets error on failure', async () => {
    const onError = vi.fn();
    const { result } = renderHook(() =>
      useMutation({ mutateFn: failingMutator('Server error', 50), onError }),
    );

    act(() => {
      result.current.mutate('arg');
    });

    await act(async () => {
      vi.advanceTimersByTime(50);
    });

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBe('Server error');
      expect(result.current.data).toBeNull();
      expect(onError).toHaveBeenCalledWith('Server error', 'arg');
    });
  });

  // -----------------------------------------------------------------------
  // Duplicate prevention
  // -----------------------------------------------------------------------

  it('ignores duplicate calls while mutation is in flight', async () => {
    const mutateFn = vi.fn(delayedMutator('ok', 100));
    const { result } = renderHook(() =>
      useMutation({ mutateFn }),
    );

    // Fire three rapid calls
    act(() => {
      result.current.mutate(undefined);
      result.current.mutate(undefined);
      result.current.mutate(undefined);
    });

    // Only the first call should have invoked mutateFn
    expect(mutateFn).toHaveBeenCalledOnce();

    await act(async () => {
      vi.advanceTimersByTime(100);
    });

    await waitFor(() => {
      expect(result.current.data).toBe('ok');
    });
  });

  it('allows new mutation after previous one completes', async () => {
    let callCount = 0;
    const mutateFn = () =>
      new Promise<string>((resolve) => {
        setTimeout(() => resolve(`result-${++callCount}`), 10);
      });

    const { result } = renderHook(() =>
      useMutation({ mutateFn }),
    );

    // First mutation
    act(() => {
      result.current.mutate(undefined);
    });
    await act(async () => {
      vi.advanceTimersByTime(10);
    });
    await waitFor(() => expect(result.current.data).toBe('result-1'));

    // Second mutation should go through
    act(() => {
      result.current.mutate(undefined);
    });
    await act(async () => {
      vi.advanceTimersByTime(10);
    });
    await waitFor(() => expect(result.current.data).toBe('result-2'));

    expect(callCount).toBe(2);
  });

  // -----------------------------------------------------------------------
  // Reset
  // -----------------------------------------------------------------------

  it('reset clears error and data', async () => {
    const { result } = renderHook(() =>
      useMutation({ mutateFn: failingMutator('oops', 10) }),
    );

    act(() => {
      result.current.mutate(undefined);
    });
    await act(async () => {
      vi.advanceTimersByTime(10);
    });
    await waitFor(() => expect(result.current.error).toBe('oops'));

    act(() => {
      result.current.reset();
    });

    expect(result.current.error).toBeNull();
    expect(result.current.data).toBeNull();
  });

  // -----------------------------------------------------------------------
  // Variables forwarding
  // -----------------------------------------------------------------------

  it('passes variables to mutateFn and callbacks', async () => {
    const mutateFn = vi.fn(delayedMutator('ok', 10));
    const onSuccess = vi.fn();

    const { result } = renderHook(() =>
      useMutation({ mutateFn, onSuccess }),
    );

    const variables = { symbol: '600519.SH', action: 'BUY' };
    act(() => {
      result.current.mutate(variables);
    });

    await act(async () => {
      vi.advanceTimersByTime(10);
    });

    await waitFor(() => {
      expect(mutateFn).toHaveBeenCalledWith(variables);
      expect(onSuccess).toHaveBeenCalledWith('ok', variables);
    });
  });
});
