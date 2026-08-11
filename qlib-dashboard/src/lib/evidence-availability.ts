import type { CanonicalMetricV2, SectionAvailability } from './model-run-bundle-v2';

const AVAILABILITY_LABELS: Record<SectionAvailability, string> = {
  available: 'Available',
  not_applicable: 'Not applicable',
  not_computed: 'Not computed',
  not_retained: 'Not retained',
  blocked_by_source: 'Blocked by source',
};

const CONTRACT_VIOLATION = 'Contract violation';

export function evidenceAvailabilityLabel(status: SectionAvailability | null | undefined): string {
  return status ? AVAILABILITY_LABELS[status] : CONTRACT_VIOLATION;
}

export function formatDeclaredValue(value: unknown): string {
  return value === null || value === undefined || value === '' ? CONTRACT_VIOLATION : String(value);
}

export function formatCanonicalMetric(metric: CanonicalMetricV2 | null): string {
  if (!metric) return CONTRACT_VIOLATION;
  if (metric.availability_status !== 'available' || metric.value === null) {
    return evidenceAvailabilityLabel(metric.availability_status);
  }
  if (
    [
      'total_return',
      'annualized_return',
      'benchmark_return',
      'excess_return',
      'annualized_volatility',
      'max_drawdown',
      'transaction_cost',
    ].includes(metric.metric_id)
  ) {
    return `${(metric.value * 100).toFixed(2)}%`;
  }
  if (metric.unit === 'bps') return `${metric.value.toFixed(1)} bps`;
  if (metric.unit === 'count') return metric.value.toLocaleString();
  return metric.value.toFixed(3);
}
