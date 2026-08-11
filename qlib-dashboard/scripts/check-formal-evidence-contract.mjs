import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '../public/data/formal-model-runs');
const REQUIRED_METRICS = [
  'total_return',
  'annualized_return',
  'benchmark_return',
  'excess_return',
  'annualized_volatility',
  'sharpe_ratio',
  'information_ratio',
  'max_drawdown',
  'turnover',
  'transaction_cost',
  'ic',
  'rank_ic',
  'icir',
];
const AVAILABILITY = new Set([
  'available',
  'not_applicable',
  'not_computed',
  'not_retained',
  'blocked_by_source',
]);
const FORMAL_CONTRACT = 'native_formal_bundle_v2';
const PERFORMANCE_SCHEMA = 'formal_performance_semantics_v1';

function readJson(path) {
  return JSON.parse(readFileSync(path, 'utf8'));
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function declared(value) {
  return value !== null && value !== undefined && value !== '' && value !== 'not_declared' && value !== 'not declared';
}

function runRoot(record) {
  return dirname(join(root, record.manifest_path));
}

function validateMetric(metric, modelId) {
  assert(metric && typeof metric === 'object', `${modelId}: canonical metric is missing`);
  assert(AVAILABILITY.has(metric.availability_status), `${modelId}/${metric.metric_id}: invalid availability`);
  if (metric.availability_status === 'available') {
    assert(typeof metric.value === 'number' && Number.isFinite(metric.value), `${modelId}/${metric.metric_id}: available metric has no finite value`);
    assert(metric.unavailable_reason === null, `${modelId}/${metric.metric_id}: available metric has an unavailable reason`);
  } else {
    assert(metric.value === null, `${modelId}/${metric.metric_id}: unavailable metric must have null value`);
    assert(typeof metric.unavailable_reason === 'string' && metric.unavailable_reason.trim(), `${modelId}/${metric.metric_id}: unavailable metric needs an explicit reason`);
  }
}

function validateFormal(record, summary) {
  const modelId = record.model_version_id;
  const base = runRoot(record);
  const manifest = readJson(join(root, record.manifest_path));
  const diagnostics = readJson(join(base, 'diagnostics.json'));

  assert(summary.evidence_contract === FORMAL_CONTRACT, `${modelId}: formal evidence contract is missing`);
  assert(manifest.publication_channel === 'formal', `${modelId}: publication channel is not formal`);
  assert(manifest.publication_status === 'accepted_formal_baseline', `${modelId}: publication status is not accepted formal`);
  assert(manifest.research_only === true && manifest.trade_ready === false, `${modelId}: research boundary changed`);

  const metrics = Array.isArray(summary.metrics) ? summary.metrics : [];
  for (const metricId of REQUIRED_METRICS) {
    const metric = metrics.find((candidate) => candidate?.metric_id === metricId);
    assert(metric, `${modelId}: missing canonical metric declaration ${metricId}`);
    validateMetric(metric, modelId);
  }

  const semantics = summary.performance_semantics;
  assert(semantics && typeof semantics === 'object', `${modelId}: production performance semantics missing`);
  assert(semantics.schema_version === PERFORMANCE_SCHEMA, `${modelId}: invalid production performance schema`);
  for (const key of ['signal_time', 'execution_time', 'return_measurement', 'price_basis', 'holding_end_offset_sessions']) {
    assert(declared(semantics[key]), `${modelId}: methodology field ${key} is undeclared`);
  }
  const cost = semantics.cost;
  assert(cost && typeof cost === 'object', `${modelId}: cost semantics missing`);
  for (const key of ['rate_bps', 'turnover_formula', 'net_return_formula']) {
    assert(declared(cost[key]), `${modelId}: cost methodology field ${key} is undeclared`);
  }

  const portfolio = summary.portfolio_contract;
  assert(portfolio && typeof portfolio === 'object', `${modelId}: production portfolio contract missing`);
  for (const key of ['signal_time', 'execution_time', 'price_basis', 'turnover_formula']) {
    assert(declared(portfolio[key]), `${modelId}: portfolio methodology field ${key} is undeclared`);
  }

  const completeness = summary.evidence_completeness;
  assert(completeness && completeness.status === 'complete', `${modelId}: formal evidence is not complete`);
  assert(Array.isArray(completeness.missing) && completeness.missing.length === 0, `${modelId}: formal evidence contains unresolved missing fields`);
  assert(diagnostics.evidence_completeness?.status === 'complete', `${modelId}: diagnostics do not confirm complete evidence`);
}

const catalog = readJson(join(root, 'catalog.json'));
assert(Array.isArray(catalog.records) && catalog.records.length > 0, 'Formal catalog is empty');
for (const record of catalog.records) {
  const summary = readJson(join(runRoot(record), 'summary.json'));
  validateFormal(record, summary);
}

console.log(`Formal evidence contract passed for ${catalog.records.length} active formal model(s): ${catalog.records.map((record) => record.model_version_id).join(', ')}`);
