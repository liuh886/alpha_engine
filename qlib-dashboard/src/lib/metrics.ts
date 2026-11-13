import { isPerformanceDate } from './performancePeriods';

/**
 * One home for display formatting and staleness rules shared by the ranking
 * table and the strategy chart. Both surfaces previously carried private
 * copies, which could drift apart under a later edit.
 */

/** Days after the evidence cutoff at which retained evidence is stale. */
export const STALE_AFTER_DAYS = 14;

/** A short-history partial window remains readable within one week of request. */
export const MAX_DISPLAYABLE_SHORTFALL_DAYS = 7;

const DAY_MS = 86_400_000;

const RETURN_FORMAT = new Intl.NumberFormat('en-US', {
  style: 'percent',
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
  signDisplay: 'exceptZero',
});

const PRICE_FORMAT = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** Calendar-day distance between two verified ISO dates. */
export function calendarDaysBetween(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / DAY_MS);
}

/**
 * Percent display with exactly one fractional digit and an explicit sign for
 * every nonzero value. A value that rounds to zero renders `0.0%`, never a
 * signed zero or a fabricated value for a missing observation.
 */
export function formatReturn(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  const rounded = Math.round(value * 1000) / 1000;
  return RETURN_FORMAT.format(rounded === 0 ? 0 : rounded);
}

/** Price level with comma grouping and exactly two decimals. */
export function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return PRICE_FORMAT.format(value);
}

/** Signed two-decimal price change; zero never renders as a signed zero. */
export function formatPriceChange(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const rounded = Math.round(value * 100) / 100;
  if (Object.is(rounded, -0) || rounded === 0) return PRICE_FORMAT.format(0);
  return `${rounded > 0 ? '+' : ''}${PRICE_FORMAT.format(rounded)}`;
}

/** ISO display for a verified date; anything else is a missing value. */
export function formatDate(value: string | null | undefined): string {
  return typeof value === 'string' && isPerformanceDate(value) ? value : '—';
}

/** Calendar days between the evidence cutoff and the last observation. */
export function staleDays(evidenceCutoff: string, asOf: string | null): number | null {
  if (!isPerformanceDate(evidenceCutoff) || !isPerformanceDate(asOf)) return null;
  return calendarDaysBetween(asOf, evidenceCutoff);
}

export function isStale(evidenceCutoff: string, asOf: string | null): boolean {
  const days = staleDays(evidenceCutoff, asOf);
  return days !== null && days > STALE_AFTER_DAYS;
}
