import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BASELINE_PREFERENCE_STORAGE_KEY, useBaselinePreference } from './useBaselinePreference';

const stored = () => localStorage.getItem(BASELINE_PREFERENCE_STORAGE_KEY);

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useBaselinePreference', () => {
  it('defaults both markets to the declared baseline', () => {
    const { result } = renderHook(() => useBaselinePreference());
    expect(result.current.preference).toEqual({ us: 'declared', cn: 'declared' });
  });

  it('reads a valid per-market preference', () => {
    localStorage.setItem(BASELINE_PREFERENCE_STORAGE_KEY, JSON.stringify({ us: 'market', cn: 'none' }));
    const { result } = renderHook(() => useBaselinePreference());
    expect(result.current.preference).toEqual({ us: 'market', cn: 'none' });
  });

  it('updates one market and persists only the baseline preference', () => {
    const { result } = renderHook(() => useBaselinePreference());
    act(() => result.current.setPreference('cn', 'market'));
    expect(result.current.preference).toEqual({ us: 'declared', cn: 'market' });
    expect(JSON.parse(stored() ?? '{}')).toEqual({ us: 'declared', cn: 'market' });
    expect(Object.keys(localStorage)).toEqual([BASELINE_PREFERENCE_STORAGE_KEY]);
  });

  it('ignores an invalid kind without changing state', () => {
    const { result } = renderHook(() => useBaselinePreference());
    act(() => result.current.setPreference('us', 'bogus' as never));
    expect(result.current.preference.us).toBe('declared');
  });

  it('falls back to defaults for corrupt JSON', () => {
    localStorage.setItem(BASELINE_PREFERENCE_STORAGE_KEY, '{not json');
    const { result } = renderHook(() => useBaselinePreference());
    expect(result.current.preference).toEqual({ us: 'declared', cn: 'declared' });
  });

  it('sanitizes invalid values and non-object payloads', () => {
    localStorage.setItem(BASELINE_PREFERENCE_STORAGE_KEY, JSON.stringify({ us: 'bogus', cn: 'market' }));
    const first = renderHook(() => useBaselinePreference());
    expect(first.result.current.preference).toEqual({ us: 'declared', cn: 'market' });

    localStorage.setItem(BASELINE_PREFERENCE_STORAGE_KEY, JSON.stringify([1, 2, 3]));
    const second = renderHook(() => useBaselinePreference());
    expect(second.result.current.preference).toEqual({ us: 'declared', cn: 'declared' });
  });

  it('uses defaults when storage reads throw', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage blocked');
    });
    const { result } = renderHook(() => useBaselinePreference());
    expect(result.current.preference).toEqual({ us: 'declared', cn: 'declared' });
  });

  it('keeps the in-memory preference when writes throw', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded');
    });
    const { result } = renderHook(() => useBaselinePreference());
    act(() => result.current.setPreference('us', 'none'));
    expect(result.current.preference.us).toBe('none');
  });

  it('uses defaults when localStorage access itself throws', () => {
    const descriptor = Object.getOwnPropertyDescriptor(window, 'localStorage');
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      get() {
        throw new Error('access blocked');
      },
    });
    try {
      const { result } = renderHook(() => useBaselinePreference());
      expect(result.current.preference).toEqual({ us: 'declared', cn: 'declared' });
    } finally {
      if (descriptor) Object.defineProperty(window, 'localStorage', descriptor);
    }
  });
});
