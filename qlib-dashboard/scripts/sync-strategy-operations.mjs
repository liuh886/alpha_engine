import { mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const repoRoot = resolve(process.cwd(), '..');
const catalogPath = resolve(repoRoot, 'data/research/formal_model_runs/catalog.json');
const snapshotsPath = resolve(repoRoot, 'data/research/strategy_operations/snapshots.json');
const outputDir = resolve(process.cwd(), 'public/data/strategy-operations');
const outputPath = resolve(outputDir, 'snapshots.json');
const allowedStatuses = new Set([
  'pipeline_unavailable',
  'awaiting_observation',
  'current_no_change',
  'target_pending_execution',
  'execution_observed',
  'stale',
  'blocked',
  'delivery_failed',
]);
const allowedFreshness = new Set(['current', 'stale', 'blocked', 'unknown']);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const catalog = JSON.parse(await readFile(catalogPath, 'utf8'));
const snapshots = JSON.parse(await readFile(snapshotsPath, 'utf8'));

assert(snapshots.schema_version === '1.0.0', 'Unsupported strategy operations schema');
assert(snapshots.research_only === true && snapshots.trade_ready === false, 'Invalid strategy operations boundary');
assert(Array.isArray(snapshots.records), 'Strategy operations records are missing');
assert(Array.isArray(catalog.records), 'Formal Model Run Bundle v2 catalog records are missing');

const formalIds = catalog.records.map((record) => String(record.model_version_id)).sort();
const operationIds = snapshots.records.map((record) => String(record.model_version_id)).sort();
assert(new Set(operationIds).size === operationIds.length, 'Duplicate strategy operations model identity');
assert(JSON.stringify(formalIds) === JSON.stringify(operationIds), 'Strategy operations set must exactly match the accepted formal catalog');

for (const record of snapshots.records) {
  const id = record.model_version_id;
  assert(allowedStatuses.has(record.status), `Unsupported operations status for ${id}`);
  assert(allowedFreshness.has(record.data_freshness), `Unsupported data freshness for ${id}`);
  assert(allowedFreshness.has(record.factor_freshness), `Unsupported factor freshness for ${id}`);
  assert(typeof record.decision_cadence === 'string' && record.decision_cadence.length > 0, `Missing decision cadence for ${id}`);
  assert(typeof record.next_decision_policy === 'string' && record.next_decision_policy.length > 0, `Missing next decision policy for ${id}`);
  assert(typeof record.state_label === 'string' && record.state_label.length > 0, `Missing state label for ${id}`);
  assert(typeof record.decision_reason === 'string' && record.decision_reason.length > 0, `Missing decision reason for ${id}`);
  assert(Array.isArray(record.allocations), `Missing allocation list for ${id}`);
  assert(Array.isArray(record.drivers), `Missing driver list for ${id}`);
  assert(record.source_identity && typeof record.source_identity === 'object', `Missing source identity for ${id}`);
}

await rm(outputDir, { recursive: true, force: true });
await mkdir(outputDir, { recursive: true });
await writeFile(outputPath, `${JSON.stringify(snapshots)}\n`, 'utf8');
console.log(`Published governed strategy operations snapshots for ${operationIds.length} formal models.`);
