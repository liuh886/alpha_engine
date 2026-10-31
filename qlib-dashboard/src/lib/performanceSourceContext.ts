import type { ModelRunBundleV2Manifest } from './model-run-bundle-v2';
import { isPerformanceDate, positiveNumber } from './performancePeriods';
import type { ReportRow } from './types';

export interface PerformanceSourceContext {
  schema_version: 'formal_performance_source_context_v1';
  canonical_bundle_id: string;
  canonical_manifest_sha256: string;
  source_performance_sha256: string;
  source_summary_sha256: string;
  evidence_cutoff: string;
  opening_date: string;
  opening_account: number;
  opening_benchmark_field: 'bench_qqq';
  opening_benchmark: number;
  opening_basis: 'validated_retained_net_wealth_compounding';
  first_observation_date: string;
  last_observation_date: string;
  wealth_observation_count: number;
  non_provisional_count: number;
  provisional_count: number;
  total_return_window: { start: string; end: string; end_account: number; sample_count: number; scope: string; includes_provisional: boolean };
  research_only: true;
  trade_ready: false;
}

function requireContext(condition: unknown): asserts condition {
  if (!condition) throw new Error('Formal source performance context could not be verified.');
}

export function readSummaryPerformanceSourceContext(
  value: unknown, manifest: ModelRunBundleV2Manifest | null, canonical: ModelRunBundleV2Manifest | null | undefined,
  cutoff: string, summary: Record<string, unknown>,
): PerformanceSourceContext | null {
  if (value === undefined) {
    requireContext(!(manifest?.projection_contract === 'public_historical_projection_v1'
      && manifest.comparability_key.trace_frequency === 'non_overlapping_10_session'
      && manifest.comparability_key.benchmark_id === 'QQQ'));
    return null;
  }
  requireContext(value && typeof value === 'object' && !Array.isArray(value));
  const context = value as PerformanceSourceContext;
  requireContext(context.schema_version === 'formal_performance_source_context_v1'
    && context.research_only === true && context.trade_ready === false
    && context.opening_basis === 'validated_retained_net_wealth_compounding'
    && manifest?.projection_contract === 'public_historical_projection_v1'
    && context.canonical_bundle_id === manifest.source_identity?.canonical_bundle_id
    && context.canonical_manifest_sha256 === manifest.source_identity?.canonical_manifest_sha256
    && [context.canonical_bundle_id, context.canonical_manifest_sha256, context.source_performance_sha256,
      context.source_summary_sha256].every(hash => typeof hash === 'string' && /^[a-f0-9]{64}$/.test(hash))
    && canonical?.bundle_id === context.canonical_bundle_id
    && canonical.sections.find(section => section.section_id === 'summary')?.sha256 === context.source_summary_sha256
    && canonical.sections.find(section => section.section_id === 'performance')?.sha256 === context.source_performance_sha256
    && context.evidence_cutoff === cutoff
    && [context.wealth_observation_count, context.non_provisional_count, context.provisional_count].every(count => Number.isInteger(count) && count >= 0)
    && context.wealth_observation_count > 0 && context.wealth_observation_count === context.non_provisional_count + context.provisional_count
    && isPerformanceDate(context.opening_date) && isPerformanceDate(context.first_observation_date) && isPerformanceDate(context.last_observation_date)
    && context.opening_date < context.first_observation_date && context.last_observation_date <= cutoff
    && positiveNumber(context.opening_account) !== null
    && context.opening_benchmark_field === 'bench_qqq'
    && positiveNumber(context.opening_benchmark) !== null);
  const window = context.total_return_window;
  const metrics = Array.isArray(summary.metrics) ? summary.metrics : [];
  const metric = metrics.find(item => item?.metric_id === 'total_return');
  requireContext(window && typeof window === 'object' && typeof window.includes_provisional === 'boolean');
  const expectedCount = window.includes_provisional ? context.wealth_observation_count : context.non_provisional_count;
  requireContext(metric?.availability_status === 'available' && window.sample_count === metric.sample_count
    && window.scope === metric.scope && window.sample_count === expectedCount && expectedCount > 0
    && window.start === context.opening_date && isPerformanceDate(window.end)
    && window.end >= context.first_observation_date && window.end <= context.last_observation_date
    && positiveNumber(window.end_account) !== null && typeof metric.value === 'number' && Number.isFinite(metric.value)
    && Math.abs(window.end_account / context.opening_account - 1 - metric.value) <= 1e-8);
  return context;
}

export function readPerformanceSourceContext(
  value: unknown, rows: ReportRow[], manifest: ModelRunBundleV2Manifest | null,
  cutoff: string, summary: Record<string, unknown>, canonical?: ModelRunBundleV2Manifest | null,
): PerformanceSourceContext | null {
  const context = readSummaryPerformanceSourceContext(value, manifest, canonical, cutoff, summary);
  if (!context) return null;
  const settled = rows.filter(row => row.provisional_mtm !== true && row.settlement_status !== 'provisional_mtm');
  const sourceRows = context.total_return_window.includes_provisional ? rows : settled;
  requireContext(context.wealth_observation_count === rows.length && context.non_provisional_count === settled.length
    && context.provisional_count === rows.length - settled.length && rows.length > 0 && sourceRows.length > 0
    && context.opening_date === rows[0].date && context.first_observation_date === rows[0].holding_end_date
    && context.last_observation_date === rows[rows.length - 1].holding_end_date
    && context.opening_account === rows[0].account_before && context.opening_benchmark === rows[0].bench_qqq_before
    && context.total_return_window.end === sourceRows[sourceRows.length - 1].holding_end_date
    && context.total_return_window.end_account === sourceRows[sourceRows.length - 1].account);
  return context;
}
