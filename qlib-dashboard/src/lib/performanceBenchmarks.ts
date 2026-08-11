import type { ReportRow } from '@/lib/types';

export type BenchmarkKey = string;
export type NormalizedSeries = Array<number | null>;

export interface BenchmarkDescriptor {
  key: BenchmarkKey;
  field: string;
  label: string;
}

export interface BenchmarkOption extends BenchmarkDescriptor {
  series: NormalizedSeries;
}

const FIELD_LABELS: Record<string, string> = {
  hs300: 'CSI 300',
  qqq: 'QQQ',
  byd: 'BYD',
};

const CANONICAL_KEYS: Record<string, string> = {
  hs300: 'csi300',
};

const DECLARED_ALIASES: Record<string, string> = {
  '000300': 'hs300',
  '000300sh': 'hs300',
  csi300: 'hs300',
  qqq: 'qqq',
  byd: 'byd',
  bydv11: 'bydv11',
  bydv11baseline: 'bydv11',
};

function identity(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '');
}

function suffixLabel(suffix: string): string {
  const normalized = suffix.toLowerCase();
  const ident = identity(normalized);
  const aliased = DECLARED_ALIASES[ident] ?? normalized;
  if (FIELD_LABELS[aliased]) return FIELD_LABELS[aliased];

  const parts = suffix.split('_').filter(Boolean);
  return parts.map((part, index) => {
    if (/^v\d+$/.test(part) && index + 1 < parts.length && /^\d+$/.test(parts[index + 1])) {
      return part.toUpperCase();
    }
    if (/^\d+$/.test(part) && index > 0 && /^v\d+$/.test(parts[index - 1])) {
      return part;
    }
    return part.length <= 4 ? part.toUpperCase() : `${part[0].toUpperCase()}${part.slice(1)}`;
  }).join(' ').replace(/\bV(\d+) (\d+)\b/g, 'v$1.$2');
}

function descriptorForField(field: string, declaredBenchmarkId?: string): BenchmarkDescriptor {
  if (field === 'bench') {
    return {
      key: 'benchmark',
      field,
      label: String(declaredBenchmarkId ?? '').trim() || 'Benchmark',
    };
  }
  const suffix = field.slice('bench_'.length);
  const ident = identity(suffix);
  const aliased = DECLARED_ALIASES[ident] ?? suffix.toLowerCase();
  const canonicalSuffix = CANONICAL_KEYS[aliased] ?? aliased;
  return {
    key: `benchmark_${canonicalSuffix}`,
    field,
    label: suffixLabel(suffix),
  };
}

export function effectivePerformanceDate(row: ReportRow): string {
  const holdingEnd = typeof row.holding_end_date === 'string' ? row.holding_end_date : '';
  return /^\d{4}-\d{2}-\d{2}$/.test(holdingEnd) ? holdingEnd : row.date;
}

export function normalizeBenchmarkSeries(values: Array<number | undefined>): NormalizedSeries | null {
  const numeric = values.map(value => Number.isFinite(Number(value)) ? Number(value) : null);
  const firstIndex = numeric.findIndex(value => value !== null);
  if (firstIndex < 0) return null;
  const first = numeric[firstIndex] as number;

  if (Math.abs(first) > 0.5) {
    let previous = first;
    return numeric.map((value, index) => {
      if (index < firstIndex) return null;
      if (value !== null) previous = value;
      return previous / first - 1;
    });
  }

  let cumulative = 1;
  return numeric.map((value, index) => {
    if (index < firstIndex) return null;
    cumulative *= 1 + (value ?? 0);
    return cumulative - 1;
  });
}

function benchmarkLooksCorrupt(report: ReportRow[], values: Array<number | undefined>): boolean {
  const normalized = values.map(value => Number.isFinite(Number(value)) ? Number(value) : null);
  const first = normalized.find((value): value is number => value !== null);
  if (first === undefined || Math.abs(first) <= 0.5) return false;

  let compared = 0;
  let differs = false;
  for (let index = 0; index < Math.min(values.length, report.length); index += 1) {
    const benchmark = Number(values[index]);
    const account = Number(report[index].account);
    if (!Number.isFinite(benchmark) || !Number.isFinite(account)) continue;
    compared += 1;
    if (Math.abs(benchmark - account) > Math.max(Math.abs(account), 1) * 1e-6) {
      differs = true;
      break;
    }
  }
  return compared > 0 && !differs;
}

function benchmarkFields(report: ReportRow[]): string[] {
  const fields: string[] = [];
  for (const row of report) {
    for (const key of Object.keys(row)) {
      if ((key === 'bench' || key.startsWith('bench_')) && !fields.includes(key)) fields.push(key);
    }
  }
  return fields.sort((left, right) => {
    if (left === 'bench') return 1;
    if (right === 'bench') return -1;
    return 0;
  });
}

function sameNormalizedSeries(left: NormalizedSeries, right: NormalizedSeries): boolean {
  return left.length === right.length && left.every((value, index) => {
    const other = right[index];
    if (value === null || other === null) return value === other;
    return Math.abs(value - other) <= 1e-12;
  });
}

export function discoverBenchmarkOptions(
  report: ReportRow[],
  declaredBenchmarkId?: string,
): BenchmarkOption[] {
  if (!report.length) return [];
  const discovered = benchmarkFields(report).flatMap(field => {
    const descriptor = descriptorForField(field, declaredBenchmarkId);
    const values = report.map(row => {
      const value = row[field];
      return Number.isFinite(Number(value)) ? Number(value) : undefined;
    });
    if (benchmarkLooksCorrupt(report, values)) return [];
    const series = normalizeBenchmarkSeries(values);
    if (!series || !series.some(value => Number.isFinite(value))) return [];
    return [{ ...descriptor, series }];
  });

  return discovered.filter((option, index) => !discovered.slice(0, index).some(previous => (
    identity(previous.label) === identity(option.label)
    && sameNormalizedSeries(previous.series, option.series)
  )));
}

export function declaredBenchmarkDescriptor(
  report: ReportRow[],
  declaredBenchmarkId?: string,
): BenchmarkDescriptor | null {
  const declared = String(declaredBenchmarkId ?? '').trim();
  if (!declared) return null;
  const declaredIdentity = DECLARED_ALIASES[identity(declared)] ?? identity(declared);
  const fields = benchmarkFields(report);

  for (const field of fields) {
    const descriptor = descriptorForField(field, declared);
    const suffix = field === 'bench' ? '' : field.slice('bench_'.length);
    const suffixIdentity = identity(suffix);
    const labelIdentity = identity(descriptor.label);
    const aliasedSuffix = DECLARED_ALIASES[suffixIdentity] ?? suffixIdentity;
    if (declaredIdentity === aliasedSuffix || declaredIdentity === labelIdentity) return descriptor;
  }

  const generic = fields.includes('bench') ? descriptorForField('bench', declared) : null;
  if (generic) return generic;
  return {
    key: `benchmark_${declaredIdentity || 'declared'}`,
    field: `bench_${declaredIdentity || 'declared'}`,
    label: declared,
  };
}
