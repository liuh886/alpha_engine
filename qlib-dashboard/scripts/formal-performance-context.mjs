// Disposable presentation metadata; canonical evidence and economics are untouched.
const positive = value => typeof value === 'number' && Number.isFinite(value) && value > 0;
const finite = value => typeof value === 'number' && Number.isFinite(value);
const close = (a, b) => Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a), Math.abs(b));
const validDate = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)
  && Number.isFinite(Date.parse(value)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
const provisional = row => row.provisional_mtm === true || row.settlement_status === 'provisional_mtm';
function requireEvidence(condition) {
  if (!condition) throw new Error('Formal source wealth/return context is inconsistent; publication blocked.');
}

export function projectPerformanceContext(performance, summary, source) {
  // Only this declared return/settlement contract supports the retained chain.
  // Daily and other horizons stay byte-identical; no model-id defaults.
  if (performance.trace_frequency !== 'non_overlapping_10_session'
      || performance.benchmark !== 'QQQ'
      || performance.performance_semantics?.performance_date_field !== 'holding_end_date') return null;
  const rows = performance.report;
  requireEvidence(Array.isArray(rows) && rows.length > 0 && !('public_evidence_context' in performance));
  const first = rows[0];
  requireEvidence(positive(first.account) && finite(first.period_return) && first.period_return > -1
    && positive(first.bench_qqq) && finite(first.benchmark_return) && first.benchmark_return > -1);
  const opening = first.account / (1 + first.period_return);
  const benchmarkOpening = first.bench_qqq / (1 + first.benchmark_return);
  requireEvidence(positive(opening) && positive(benchmarkOpening) && validDate(first.date)
    && validDate(first.holding_end_date) && first.date < first.holding_end_date);
  let account = opening;
  let benchmark = benchmarkOpening;
  let previousDate = first.date;
  let unsettledSeen = false;
  for (const row of rows) {
    requireEvidence(positive(row.account) && finite(row.period_return) && row.period_return > -1
      && positive(row.bench_qqq) && finite(row.benchmark_return) && row.benchmark_return > -1
      && validDate(row.date) && validDate(row.holding_end_date) && row.date <= row.holding_end_date
      && row.date >= previousDate && row.holding_end_date > previousDate && row.holding_end_date <= source.evidence_cutoff
      && (!unsettledSeen || provisional(row)));
    if (row.account_before !== undefined) requireEvidence(positive(row.account_before) && close(row.account_before, account));
    if (row.bench_qqq_before !== undefined) requireEvidence(positive(row.bench_qqq_before) && close(row.bench_qqq_before, benchmark));
    requireEvidence(close(account * (1 + row.period_return), row.account)
      && close(benchmark * (1 + row.benchmark_return), row.bench_qqq));
    account = row.account;
    benchmark = row.bench_qqq;
    previousDate = row.holding_end_date;
    unsettledSeen ||= provisional(row);
  }
  const settled = rows.filter(row => !provisional(row));
  const metric = summary.metrics?.find(row => row.metric_id === 'total_return');
  requireEvidence(metric?.availability_status === 'available' && finite(metric.value)
    && Number.isInteger(metric.sample_count) && metric.sample_count > 0 && typeof metric.scope === 'string');
  const metricRows = metric.sample_count === rows.length ? rows
    : metric.sample_count === settled.length ? settled : null;
  requireEvidence(metricRows && close(metricRows.at(-1).account / opening - 1, metric.value));
  const payload = structuredClone(performance);
  // Existing consumers share these source-validated fields. Never recalculate costs in the browser.
  payload.report[0].account_before = opening;
  payload.report[0].bench_qqq_before = benchmarkOpening;
  payload.public_evidence_context = {
    schema_version: 'formal_performance_source_context_v1',
    canonical_bundle_id: source.canonical_bundle_id,
    canonical_manifest_sha256: source.canonical_manifest_sha256,
    source_performance_sha256: source.performance_sha256,
    source_summary_sha256: source.summary_sha256,
    evidence_cutoff: source.evidence_cutoff,
    opening_date: first.date, opening_account: opening,
    opening_benchmark_field: 'bench_qqq', opening_benchmark: benchmarkOpening,
    opening_basis: 'validated_retained_net_wealth_compounding',
    first_observation_date: first.holding_end_date,
    last_observation_date: rows.at(-1).holding_end_date,
    wealth_observation_count: rows.length,
    non_provisional_count: settled.length,
    provisional_count: rows.length - settled.length,
    total_return_window: { start: first.date, end: metricRows.at(-1).holding_end_date,
      sample_count: metric.sample_count, scope: metric.scope, end_account: metricRows.at(-1).account,
      includes_provisional: metricRows.some(provisional) },
    research_only: true, trade_ready: false,
  };
  return payload;
}
