import type { SecurityBar } from './security-evidence';

const PRICE_FORMAT = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const PERCENT_FORMAT = new Intl.NumberFormat('en-US', {
  style: 'percent',
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
  signDisplay: 'exceptZero',
});

export interface VisibleCloseSummary {
  /** Last observed close in the visible range; never a carried-forward value. */
  lastClose: number | null;
  /** Close-to-close change across the last six visible closes, or the range start. */
  oneWeekChange: number | null;
  oneWeekReason: string | null;
  /** Date of the last visible close. */
  asOf: string | null;
}

/** Price evidence is presented at two decimals; a missing observation is a dash. */
export function formatSecurityPrice(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? PRICE_FORMAT.format(value) : '—';
}

/**
 * A missing return is a dash with a separate reason. It is never rendered as
 * 0.0%, because a flat observation and an unavailable window are different facts.
 */
export function formatSecurityPercent(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? PERCENT_FORMAT.format(value) : '—';
}

/** Indexed price (100 = start) as a signed percent return for chart labels. */
export function formatIndexedReturn(value: number): string {
  if (!Number.isFinite(value)) return '—';
  return formatSecurityPercent(value / 100 - 1);
}

/**
 * Last close and one-week change from the visible closes only. The weekly window
 * uses the last six observed closes (five close-to-close intervals) and falls back
 * to the range start when fewer sessions are visible. A single close cannot
 * produce a change; the caller receives a reason instead of a silent zero.
 */
export function visibleCloseSummary(bars: readonly SecurityBar[]): VisibleCloseSummary {
  const observed = bars.filter(bar => Number.isFinite(bar.close) && bar.close > 0);
  const last = observed[observed.length - 1];
  if (!last) {
    return { lastClose: null, oneWeekChange: null, oneWeekReason: 'No observed closes in this range.', asOf: null };
  }
  if (observed.length < 2) {
    return {
      lastClose: last.close,
      oneWeekChange: null,
      oneWeekReason: 'Insufficient observed closes for a one-week change.',
      asOf: last.time,
    };
  }
  const baseIndex = Math.max(0, observed.length - 6);
  const base = observed[baseIndex];
  const change = base.close > 0 ? last.close / base.close - 1 : Number.NaN;
  if (!Number.isFinite(change)) {
    return {
      lastClose: last.close,
      oneWeekChange: null,
      oneWeekReason: 'A one-week change cannot be computed from the observed closes.',
      asOf: last.time,
    };
  }
  return { lastClose: last.close, oneWeekChange: change, oneWeekReason: null, asOf: last.time };
}
