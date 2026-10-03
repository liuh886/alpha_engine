import { effectivePerformanceDate } from './performanceBenchmarks';
import type { ReportRow } from './types';

export type PerformancePeriod = '1m' | '3m' | '6m' | '1y' | '3y' | 'ytd' | 'all';

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

export function periodStartIndex(report: ReportRow[], period: PerformancePeriod): number {
  if (!report.length || period === 'all') return 0;
  const end = new Date(`${effectivePerformanceDate(report[report.length - 1])}T00:00:00Z`);
  if (!Number.isFinite(end.getTime())) return -1;
  if (period === 'ytd') end.setUTCMonth(0, 1);
  else {
    const months = { '1m': 1, '3m': 3, '6m': 6, '1y': 12, '3y': 36 }[period];
    const day = end.getUTCDate();
    end.setUTCDate(1);
    end.setUTCMonth(end.getUTCMonth() - months);
    const lastDay = new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth() + 1, 0)).getUTCDate();
    end.setUTCDate(Math.min(day, lastDay));
  }
  return report.findIndex(row => Date.parse(`${effectivePerformanceDate(row)}T00:00:00Z`) >= end.getTime());
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
