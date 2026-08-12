import { mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const dashboardRoot = resolve(scriptDir, '..');
const repoRoot = resolve(dashboardRoot, '..');
const catalogPath = resolve(repoRoot, 'data/research/formal_model_runs/catalog.json');
const snapshotsPath = resolve(repoRoot, 'data/research/strategy_operations/snapshots.json');
const outputDir = resolve(dashboardRoot, 'public/data/strategy-operations');
const outputPath = resolve(outputDir, 'snapshots.json');
const allowedStatuses = new Set(['pipeline_unavailable', 'awaiting_observation', 'current_no_change', 'target_pending_execution', 'execution_observed', 'stale', 'blocked', 'delivery_failed']);
const allowedFreshness = new Set(['current', 'stale', 'blocked', 'unknown']);
const allowedEffects = new Set(['support', 'veto', 'neutral']);
const allowedAccess = new Set(['public', 'authenticated', 'pro', 'owner']);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function redactProtectedRecord(record) {
  if (record.current_operations_access === 'public') return record;
  return {
    strategy_id: record.strategy_id,
    model_version_id: record.model_version_id,
    current_operations_access: record.current_operations_access,
    status: 'blocked',
    as_of: null,
    latest_completed_session: null,
    decision_cadence: record.decision_cadence,
    next_decision_policy: record.next_decision_policy,
    state_label: 'Protected current operations',
    decision_reason: 'Current holdings and signals require authenticated entitlement delivery.',
    allocations: [],
    turnover: null,
    estimated_cost: null,
    data_freshness: 'unknown',
    factor_freshness: 'blocked',
    delivery_status: 'not available',
    source_label: 'Protected current operations',
    source_href: null,
    note: 'Current holdings, targets, drivers and decision-ledger provenance are not included in the public bundle.',
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

const catalog = JSON.parse(await readFile(catalogPath, 'utf8'));
const snapshots = JSON.parse(await readFile(snapshotsPath, 'utf8'));
assert(snapshots.schema_version === '2.1.0', 'Unsupported strategy operations schema');
assert(snapshots.research_only === true && snapshots.trade_ready === false, 'Invalid strategy operations boundary');
assert(Array.isArray(snapshots.records), 'Strategy operations records are missing');
assert(Array.isArray(catalog.records), 'Formal Model Run Bundle v2 catalog records are missing');

const formalIds = catalog.records.map((record) => String(record.model_version_id)).sort();
const operationIds = snapshots.records.map((record) => String(record.model_version_id)).sort();
const strategyIds = snapshots.records.map((record) => String(record.strategy_id));
assert(new Set(operationIds).size === operationIds.length, 'Duplicate strategy operations model identity');
assert(new Set(strategyIds).size === strategyIds.length, 'Duplicate stable strategy identity');
assert(JSON.stringify(formalIds) === JSON.stringify(operationIds), 'Strategy operations set must exactly match the accepted formal catalog');
const formalById = new Map(catalog.records.map((record) => [String(record.model_version_id), record]));

for (const record of snapshots.records) {
  const id = record.model_version_id;
  const formal = formalById.get(String(id));
  assert(formal, `Missing formal record for ${id}`);
  assert(typeof record.strategy_id === 'string' && record.strategy_id.length > 0, `Missing stable strategy id for ${id}`);
  assert(allowedAccess.has(record.current_operations_access), `Unsupported operations access for ${id}`);
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

const publicProjection = {
  ...snapshots,
  records: snapshots.records.map(redactProtectedRecord),
};

for (const record of publicProjection.records) {
  if (record.current_operations_access === 'public') continue;
  assert(record.allocations.length === 0, `Protected allocations leaked for ${record.model_version_id}`);
  assert(record.factor_evidence.length === 0, `Protected factor evidence leaked for ${record.model_version_id}`);
  assert(record.source_identity.ledger_fingerprint === null, `Protected ledger fingerprint leaked for ${record.model_version_id}`);
  assert(record.source_identity.signal_sha256 === null, `Protected signal hash leaked for ${record.model_version_id}`);
  assert(record.source_identity.workflow_run_id === null, `Protected workflow provenance leaked for ${record.model_version_id}`);
}

await rm(outputDir, { recursive: true, force: true });
await mkdir(outputDir, { recursive: true });
await writeFile(outputPath, `${JSON.stringify(publicProjection)}\n`, 'utf8');
console.log(`Published governed strategy operations snapshots for ${operationIds.length} formal models; protected current operations were redacted.`);
