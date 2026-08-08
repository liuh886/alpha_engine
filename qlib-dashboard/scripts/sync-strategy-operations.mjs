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

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const catalog = JSON.parse(await readFile(catalogPath, 'utf8'));
const snapshots = JSON.parse(await readFile(snapshotsPath, 'utf8'));
assert(snapshots.schema_version === '2.0.0', 'Unsupported strategy operations schema');
assert(snapshots.research_only === true && snapshots.trade_ready === false, 'Invalid strategy operations boundary');
assert(Array.isArray(snapshots.records), 'Strategy operations records are missing');
assert(Array.isArray(catalog.records), 'Formal Model Run Bundle v2 catalog records are missing');

const formalIds = catalog.records.map((record) => String(record.model_version_id)).sort();
const operationIds = snapshots.records.map((record) => String(record.model_version_id)).sort();
assert(new Set(operationIds).size === operationIds.length, 'Duplicate strategy operations model identity');
assert(JSON.stringify(formalIds) === JSON.stringify(operationIds), 'Strategy operations set must exactly match the accepted formal catalog');
const formalById = new Map(catalog.records.map((record) => [String(record.model_version_id), record]));

for (const record of snapshots.records) {
  const id = record.model_version_id;
  const formal = formalById.get(String(id));
  assert(formal, `Missing formal record for ${id}`);
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

await rm(outputDir, { recursive: true, force: true });
await mkdir(outputDir, { recursive: true });
await writeFile(outputPath, `${JSON.stringify(snapshots)}\n`, 'utf8');
console.log(`Published governed strategy operations snapshots for ${operationIds.length} formal models.`);
