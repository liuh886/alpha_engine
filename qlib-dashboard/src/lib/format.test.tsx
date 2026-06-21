import { describe, it, expect } from 'vitest';
import { formatNum, formatPct, formatCompact, shortId } from './format';

describe('formatNum', () => {
  it('formats a number with default 4 decimals', () => {
    expect(formatNum(3.14159)).toBe('3.1416');
  });

  it('formats with custom decimals', () => {
    expect(formatNum(3.14159, 2)).toBe('3.14');
  });

  it('returns N/A for null', () => {
    expect(formatNum(null)).toBe('N/A');
  });

  it('returns N/A for undefined', () => {
    expect(formatNum(undefined)).toBe('N/A');
  });

  it('returns N/A for NaN', () => {
    expect(formatNum(NaN)).toBe('N/A');
  });
});

describe('formatPct', () => {
  it('formats a fraction as percentage', () => {
    expect(formatPct(0.1234)).toBe('12.34%');
  });

  it('formats with custom decimals', () => {
    expect(formatPct(0.5, 0)).toBe('50%');
  });

  it('returns N/A for null', () => {
    expect(formatPct(null)).toBe('N/A');
  });

  it('returns N/A for NaN', () => {
    expect(formatPct(NaN)).toBe('N/A');
  });
});

describe('formatCompact', () => {
  it('formats millions', () => {
    expect(formatCompact(1500000)).toBe('1.5M');
  });

  it('formats thousands', () => {
    expect(formatCompact(1500)).toBe('1.5K');
  });

  it('formats small numbers', () => {
    expect(formatCompact(42.5)).toBe('42.50');
  });

  it('returns N/A for null', () => {
    expect(formatCompact(null)).toBe('N/A');
  });
});

describe('shortId', () => {
  it('returns full ID if short enough', () => {
    expect(shortId('abc123')).toBe('abc123');
  });

  it('truncates long IDs to 8 chars', () => {
    expect(shortId('abcdefghijklmnop')).toBe('abcdefgh');
  });

  it('returns empty string for falsy input', () => {
    expect(shortId('')).toBe('');
  });
});
