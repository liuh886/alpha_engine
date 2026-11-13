import { effectivePerformanceDate } from './performanceBenchmarks';
import type { ReportRow } from './types';

export type PerformancePeriod = '1w' | '1m' | '3m' | '6m' | '1y' | '2y' | '3y' | 'ytd' | 'all';

/** Decision horizons. The existing chart ranges (`6m`, `ytd`, `all`) remain available. */
export const HORIZON_PERIODS = ['1w', '1m', '3m', '1y', '2y', '3y'] as const;
export type HorizonPeriod = (typeof HORIZON_PERIODS)[number];

export function positiveNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

export function initialAccount(report: ReportRow[]): number | null {
  return report[0]?.account_before === undefined
    ? positiveNumber(report[0]?.account)
    : positiveNumber(report[0]?.account_before);
}

/** Latest retained wealth observation, without inventing intervening daily marks. */
export function latestPerformanceObservation(report: ReportRow[]) {
  if (!report.length) return null;
  let peak = initialAccount(report);
  if (peak === null) return null;
  let previousAccount: number | null = null;
  let previousDate: string | null = null;
  let previousDrawdown: number | null = null;
  for (let index = 0; index < report.length; index++) {
    const row = report[index];
    const account = positiveNumber(row.account);
    const date = effectivePerformanceDate(row);
    if (account === null || !/^\d{4}-\d{2}-\d{2}$/.test(date) || !Number.isFinite(Date.parse(date)) || previousDate && date <= previousDate) return null;
    peak = Math.max(peak, account);
    const drawdown = account / peak - 1;
    if (index === report.length - 1) return {
      date, previousDate, drawdown,
      observedReturn: previousAccount === null ? null : account / previousAccount - 1,
      drawdownChange: previousDrawdown === null ? null : drawdown - previousDrawdown,
      provisional: row.provisional_mtm === true || row.settlement_status === 'provisional_mtm',
    };
    previousAccount = account;
    previousDate = date;
    previousDrawdown = drawdown;
  }
  return null;
}

export function isPerformanceDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

/** Calendar lower bound; callers choose the evidence date, never the wall clock. */
export function performancePeriodStart(asOf: string, period: PerformancePeriod): string | null {
  if (period === 'all' || !isPerformanceDate(asOf)) return null;
  const end = new Date(`${asOf}T00:00:00Z`);
  if (period === '1w') {
    end.setUTCDate(end.getUTCDate() - 7);
  } else if (period === 'ytd') {
    end.setUTCMonth(0, 1);
  } else {
    const monthsBack: Partial<Record<PerformancePeriod, number>> = {
      '1m': 1, '3m': 3, '6m': 6, '1y': 12, '2y': 24, '3y': 36,
    };
    const months = monthsBack[period];
    if (months === undefined) return null;
    const day = end.getUTCDate();
    end.setUTCDate(1);
    end.setUTCMonth(end.getUTCMonth() - months);
    const lastDay = new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth() + 1, 0)).getUTCDate();
    end.setUTCDate(Math.min(day, lastDay));
  }
  return end.toISOString().slice(0, 10);
}

export function periodStartIndex(report: ReportRow[], period: PerformancePeriod): number {
  if (!report.length || period === 'all') return 0;
  const start = performancePeriodStart(effectivePerformanceDate(report[report.length - 1]), period);
  if (start === null) return -1;
  return report.findIndex(row => Date.parse(`${effectivePerformanceDate(row)}T00:00:00Z`) >= Date.parse(`${start}T00:00:00Z`));
}

/** Subranges start at the first observed settlement, never an interpolated price. */
export function strategyPeriodSummary(report: ReportRow[], period: PerformancePeriod) {
  const startIndex = periodStartIndex(report, period);
  const rows = startIndex < 0 ? [] : report.slice(startIndex);
  const start = startIndex === 0 ? initialAccount(report) : positiveNumber(rows[0]?.account);
  const end = positiveNumber(rows[rows.length - 1]?.account);
  let peak = start;
  let drawdown: number | null = start === null ? null : 0;
  for (const row of rows) {
    const account = positiveNumber(row.account);
    if (account === null || peak === null) continue;
    peak = Math.max(peak, account);
    drawdown = Math.min(drawdown ?? 0, account / peak - 1);
  }
  return {
    startIndex,
    rows,
    return: start !== null && end !== null ? end / start - 1 : null,
    drawdown,
    startDate: rows.length ? effectivePerformanceDate(rows[0]) : null,
    endDate: rows.length ? effectivePerformanceDate(rows[rows.length - 1]) : null,
  };
}

export type HorizonCoverageState = 'full' | 'partial' | 'none';

export type HorizonCoverageReason =
  | 'covered'
  | 'short_history'
  | 'truncated_window'
  | 'coarse_cadence'
  | 'insufficient_observations'
  | 'invalid_dates';

export interface HorizonCoverage {
  state: HorizonCoverageState;
  /** Effective date of the last valid observation; never the wall clock. */
  asOf: string | null;
  requestedStart: string | null;
  firstObservation: string | null;
  /** Valid observations at or after `requestedStart`. */
  observations: number;
  /** Calendar days from `requestedStart` to `firstObservation` (0 when equal). */
  missingDays: number | null;
  /** Median gap between consecutive observed dates, in calendar days. */
  cadenceDays: number | null;
  reason: HorizonCoverageReason;
}

const DAY_MS = 86_400_000;

function calendarDaysBetween(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / DAY_MS);
}

function median(values: number[]): number | null {
  if (!values.length) return null;
  const ordered = [...values].sort((left, right) => left - right);
  const middle = Math.floor(ordered.length / 2);
  return ordered.length % 2 === 0
    ? (ordered[middle - 1] + ordered[middle]) / 2
    : ordered[middle];
}

function medianCadenceDays(dates: string[]): number | null {
  if (dates.length < 2) return null;
  const gaps: number[] = [];
  for (let index = 1; index < dates.length; index += 1) {
    gaps.push(calendarDaysBetween(dates[index - 1], dates[index]));
  }
  return median(gaps);
}

function invalidCoverage(): HorizonCoverage {
  return {
    state: 'none',
    asOf: null,
    requestedStart: null,
    firstObservation: null,
    observations: 0,
    missingDays: null,
    cadenceDays: null,
    reason: 'invalid_dates',
  };
}

/**
 * Explain how much of a requested horizon the retained observations cover.
 * The window ends at the last observed date, never the wall clock, and a
 * truncated start is never presented as a full-horizon return.
 */
export function horizonCoverage(report: ReportRow[], period: PerformancePeriod): HorizonCoverage {
  if (!Array.isArray(report) || report.length === 0) return invalidCoverage();

  const accountsByDate = new Map<string, number | null>();
  for (const row of report) {
    if (!row) continue;
    const date = effectivePerformanceDate(row);
    if (!isPerformanceDate(date)) continue;
    accountsByDate.set(date, positiveNumber(row.account));
  }
  const datedDates = [...accountsByDate.keys()].sort();
  if (datedDates.length === 0) return invalidCoverage();

  const observedDates = datedDates.filter(date => accountsByDate.get(date) !== null);
  if (observedDates.length === 0) {
    // Dates parse, but there is no positive account chain to observe.
    const asOf = datedDates[datedDates.length - 1];
    const requestedStart = period === 'all' ? datedDates[0] : performancePeriodStart(asOf, period);
    return {
      state: 'none',
      asOf,
      requestedStart,
      firstObservation: null,
      observations: 0,
      missingDays: null,
      cadenceDays: null,
      reason: 'insufficient_observations',
    };
  }

  const asOf = observedDates[observedDates.length - 1];
  const requestedStart = period === 'all' ? observedDates[0] : performancePeriodStart(asOf, period);
  if (requestedStart === null) return { ...invalidCoverage(), asOf };

  const windowDates = observedDates.filter(date => date >= requestedStart);
  const observations = windowDates.length;
  const firstObservation = windowDates[0] ?? null;
  const missingDays = firstObservation === null ? null : calendarDaysBetween(requestedStart, firstObservation);
  const cadenceDays = medianCadenceDays(observations >= 2 ? windowDates : observedDates);
  const base = { asOf, requestedStart, firstObservation, observations, missingDays, cadenceDays };

  if (period === '1w') {
    // A weekly curve needs both a recent and a reasonably dense observation pair.
    if (cadenceDays !== null && cadenceDays > 7) {
      return { ...base, state: 'partial', reason: 'coarse_cadence' };
    }
    if (observations < 3) {
      return { ...base, state: 'partial', reason: 'insufficient_observations' };
    }
  } else if (observations < 2) {
    return { ...base, state: 'none', reason: 'insufficient_observations' };
  }

  if (missingDays !== null && missingDays > 31) return { ...base, state: 'none', reason: 'truncated_window' };
  if (missingDays !== null && missingDays > 7) return { ...base, state: 'partial', reason: 'short_history' };
  return { ...base, state: 'full', reason: 'covered' };
}
