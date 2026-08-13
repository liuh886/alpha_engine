import { mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const dashboardRoot = resolve(scriptDir, '..');
const repoRoot = resolve(dashboardRoot, '..');
const catalogPath = resolve(repoRoot, 'data/research/formal_model_runs/catalog.json');
const snapshotsPath = resolve(repoRoot, 'data/research/strategy_operations/snapshots.json');
const healthPath = resolve(repoRoot, 'data/research/strategy_operations/system-health.json');
const outputDir = resolve(dashboardRoot, 'public/data/strategy-operations');
const outputPath = resolve(outputDir, 'snapshots.json');
const healthOutputPath = resolve(outputDir, 'system-health.json');
const allowedStatuses = new Set(['pipeline_unavailable', 'awaiting_observation', 'current_no_change', 'target_pending_execution', 'execution_observed', 'stale', 'blocked', 'delivery_failed']);
const allowedFreshness = new Set(['current', 'stale', 'blocked', 'unknown']);
const allowedEffects = new Set(['support', 'veto', 'neutral']);
const allowedHealthStates = new Set(['current', 'delayed', 'blocked', 'inconsistent', 'not_applicable']);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function redactRuntimeRecord(record) {
  return {
    strategy_id: record.strategy_id,
    model_version_id: record.model_version_id,
    status: 'blocked',
    as_of: null,
    latest_completed_session: null,
    decision_cadence: record.decision_cadence,
    next_decision_policy: record.next_decision_policy,
    state_label: 'Runtime current operations',
    decision_reason: 'Current holdings and signals are delivered from the runtime access plane.',
    allocations: [],
    turnover: null,
    estimated_cost: null,
    data_freshness: 'unknown',
    factor_freshness: 'blocked',
    delivery_status: 'not available',
    source_label: 'Runtime current operations',
    source_href: null,
    note: 'Current holdings, targets, drivers and decision-ledger provenance are never included in the public static bundle.',
    factor_evidence: [],
    source_identity: {
      formal_bundle_id: record.source_identity.formal_bundle_id,
      formal_run_id: record.source_identity.formal_run_id,
      formal_evidence_cutoff: record.source_identity.formal_evidence_cutoff,
      ledger_fingerprint: null,
      signal_sha256: null,
      factor_catalog_implementation_hash: null,
      workflow_run_id: null,
      commit_sha: null,
      github_issue_number: null,
    },
  };
}

function redactHealthRecord(record) {
  return {
    strategy_id: record.strategy_id,
    model_version_id: record.model_version_id,
    market: record.market,
    state: record.state,
    market_expected_cutoff: record.market_expected_cutoff,
    provider_cutoff: record.provider_cutoff,
    formal_cutoff: record.formal_cutoff,
    model_data_cutoff: record.model_data_cutoff,
    factor_cutoff: record.factor_cutoff,
    last_signal_evaluation: null,
    last_signal_change: null,
    delivery_state: 'not_applicable',
    delivery_status: null,
    stages: {
      provider: record.stages.provider,
      formal: record.stages.formal,
      model_data: record.stages.model_data,
      factor: record.stages.factor,
      signal: record.stages.signal,
      delivery: 'not_applicable',
    },
    formal_bundle_id: record.formal_bundle_id,
    formal_run_id: record.formal_run_id,
  };
}

const catalog = JSON.parse(await readFile(catalogPath, 'utf8'));
const snapshots = JSON.parse(await readFile(snapshotsPath, 'utf8'));
const health = JSON.parse(await readFile(healthPath, 'utf8'));
assert(snapshots.schema_version === '2.2.0', 'Unsupported strategy operations schema');
assert(snapshots.research_only === true && snapshots.trade_ready === false, 'Invalid strategy operations boundary');
assert(Array.isArray(snapshots.records), 'Strategy operations records are missing');
assert(Array.isArray(catalog.records), 'Formal Model Run Bundle v2 catalog records are missing');
assert(health.schema_version === '1.0.0', 'Unsupported system health schema');
assert(health.research_only === true && health.trade_ready === false, 'Invalid system health boundary');
assert(allowedHealthStates.has(health.state), 'Invalid system health state');
assert(Array.isArray(health.markets) && health.markets.length > 0, 'System health markets are missing');
assert(Array.isArray(health.strategies), 'System health strategies are missing');

const formalIds = catalog.records.map((record) => String(record.model_version_id)).sort();
const operationIds = snapshots.records.map((record) => String(record.model_version_id)).sort();
const strategyIds = snapshots.records.map((record) => String(record.strategy_id));
const healthIds = health.strategies.map((record) => String(record.model_version_id)).sort();
assert(new Set(operationIds).size === operationIds.length, 'Duplicate strategy operations model identity');
assert(new Set(strategyIds).size === strategyIds.length, 'Duplicate stable strategy identity');
assert(JSON.stringify(formalIds) === JSON.stringify(operationIds), 'Strategy operations set must exactly match the accepted formal catalog');
assert(JSON.stringify(formalIds) === JSON.stringify(healthIds), 'System health set must exactly match the accepted formal catalog');
const formalById = new Map(catalog.records.map((record) => [String(record.model_version_id), record]));

for (const record of snapshots.records) {
  const id = record.model_version_id;
  const formal = formalById.get(String(id));
  assert(formal, `Missing formal record for ${id}`);
  assert(typeof record.strategy_id === 'string' && record.strategy_id.length > 0, `Missing stable strategy id for ${id}`);
  assert(!Object.hasOwn(record, 'current_operations_access'), `Runtime access tier leaked into operations evidence for ${id}`);
  assert(allowedStatuses.has(record.status), `Unsupported operations status for ${id}`);
  assert(allowedFreshness.has(record.data_freshness), `Unsupported data freshness for ${id}`);
  assert(allowedFreshness.has(record.factor_freshness), `Unsupported factor freshness for ${id}`);
  assert(typeof record.decision_cadence === 'string' && record.decision_cadence.length > 0, `Missing decision cadence for ${id}`);
  assert(typeof record.next_decision_policy === 'string' && record.next_decision_policy.length > 0, `Missing next decision policy for ${id}`);
  assert(typeof record.state_label === 'string' && record.state_label.length > 0, `Missing state label for ${id}`);
  assert(typeof record.decision_reason === 'string' && record.decision_reason.length > 0, `Missing decision reason for ${id}`);
  assert(Array.isArray(record.allocations), `Missing allocation list for ${id}`);
  assert(Array.isArray(record.factor_evidence), `Missing factor evidence for ${id}`);
  if (record.factor_freshness === 'current') {
    assert(record.factor_evidence.length > 0, `Current factor freshness requires evidence for ${id}`);
  }
  for (const factor of record.factor_evidence) {
    assert(typeof factor.factor_id === 'string' && factor.factor_id.length > 0, `Missing factor id for ${id}`);
    assert(typeof factor.implementation_hash === 'string' && /^[a-f0-9]{64}$/.test(factor.implementation_hash), `Invalid factor implementation hash for ${id}/${factor.factor_id}`);
    assert(typeof factor.observed_at === 'string' && factor.observed_at === record.latest_completed_session, `Factor cutoff drift for ${id}/${factor.factor_id}`);
    assert(allowedEffects.has(factor.effect), `Invalid factor effect for ${id}/${factor.factor_id}`);
  }
  assert(record.source_identity && typeof record.source_identity === 'object', `Missing source identity for ${id}`);
  assert(record.source_identity.formal_bundle_id === formal.bundle_id, `Formal bundle identity drift for ${id}`);
  assert(record.source_identity.formal_run_id === formal.run_id, `Formal run identity drift for ${id}`);
  assert(record.source_identity.formal_evidence_cutoff === formal.evidence_cutoff, `Formal evidence cutoff drift for ${id}`);
}

for (const record of health.strategies) {
  const formal = formalById.get(String(record.model_version_id));
  assert(formal, `Missing formal record for system health ${record.model_version_id}`);
  assert(allowedHealthStates.has(record.state), `Invalid system health strategy state for ${record.model_version_id}`);
  assert(record.stages && typeof record.stages === 'object', `Missing system health stages for ${record.model_version_id}`);
  for (const value of Object.values(record.stages)) {
    assert(allowedHealthStates.has(value), `Invalid system health stage state for ${record.model_version_id}`);
  }
  assert(record.formal_bundle_id === formal.bundle_id, `System health formal bundle drift for ${record.model_version_id}`);
  assert(record.formal_run_id === formal.run_id, `System health formal run drift for ${record.model_version_id}`);
}

const publicProjection = {
  ...snapshots,
  records: snapshots.records.map(redactRuntimeRecord),
};
const publicHealth = {
  ...health,
  strategies: health.strategies.map(redactHealthRecord),
};

for (const record of publicProjection.records) {
  assert(record.allocations.length === 0, `Runtime allocations leaked for ${record.model_version_id}`);
  assert(record.factor_evidence.length === 0, `Runtime factor evidence leaked for ${record.model_version_id}`);
  assert(record.source_identity.ledger_fingerprint === null, `Runtime ledger fingerprint leaked for ${record.model_version_id}`);
  assert(record.source_identity.signal_sha256 === null, `Runtime signal hash leaked for ${record.model_version_id}`);
  assert(record.source_identity.workflow_run_id === null, `Runtime workflow provenance leaked for ${record.model_version_id}`);
}
for (const record of publicHealth.strategies) {
  assert(record.last_signal_evaluation === null, `Signal evaluation leaked for ${record.model_version_id}`);
  assert(record.last_signal_change === null, `Signal change leaked for ${record.model_version_id}`);
  assert(record.delivery_status === null, `Delivery provenance leaked for ${record.model_version_id}`);
}

await rm(outputDir, { recursive: true, force: true });
await mkdir(outputDir, { recursive: true });
await writeFile(outputPath, `${JSON.stringify(publicProjection)}\n`, 'utf8');
await writeFile(healthOutputPath, `${JSON.stringify(publicHealth)}\n`, 'utf8');
console.log(`Published public strategy identity and system-health shells for ${operationIds.length} formal models; protected current operations stay on the runtime access plane.`);
