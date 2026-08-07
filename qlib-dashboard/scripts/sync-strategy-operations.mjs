import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const repoRoot = resolve(process.cwd(), '..');
const catalogPath = resolve(repoRoot, 'data/research/formal_model_runs/catalog.json');
const capabilityPath = resolve(repoRoot, 'data/research/strategy_operations/capabilities.json');
const outputPath = resolve(process.cwd(), 'public/data/strategy-operations/capabilities.json');
const allowedSources = new Set(['github_issue_v42', 'github_issue_byd', 'unavailable']);
const allowedPipelineStatus = new Set(['available', 'unavailable']);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const catalog = JSON.parse(await readFile(catalogPath, 'utf8'));
const capabilities = JSON.parse(await readFile(capabilityPath, 'utf8'));

assert(capabilities.schema_version === '1.0.0', 'Unsupported strategy capability schema');
assert(capabilities.research_only === true && capabilities.trade_ready === false, 'Invalid strategy capability boundary');
assert(Array.isArray(capabilities.records), 'Strategy capability records are missing');
assert(Array.isArray(catalog.records), 'Formal Model Run Bundle v2 catalog records are missing');

const formalIds = catalog.records.map((record) => String(record.model_version_id)).sort();
const capabilityIds = capabilities.records.map((record) => String(record.model_version_id)).sort();
assert(new Set(capabilityIds).size === capabilityIds.length, 'Duplicate strategy capability model identity');
assert(JSON.stringify(formalIds) === JSON.stringify(capabilityIds), 'Strategy capability set must exactly match the accepted formal catalog');

for (const record of capabilities.records) {
  assert(allowedSources.has(record.source_type), `Unsupported operations source_type for ${record.model_version_id}`);
  assert(allowedPipelineStatus.has(record.pipeline_status), `Unsupported pipeline_status for ${record.model_version_id}`);
  assert(typeof record.decision_cadence === 'string' && record.decision_cadence.length > 0, `Missing decision cadence for ${record.model_version_id}`);
  assert(typeof record.next_decision_policy === 'string' && record.next_decision_policy.length > 0, `Missing next decision policy for ${record.model_version_id}`);
  assert(typeof record.note === 'string' && record.note.length > 0, `Missing capability note for ${record.model_version_id}`);
  if (record.source_type === 'unavailable') {
    assert(record.pipeline_status === 'unavailable', `Unavailable source must declare unavailable pipeline for ${record.model_version_id}`);
  } else {
    assert(record.pipeline_status === 'available', `Operational source must declare available pipeline for ${record.model_version_id}`);
  }
}

await mkdir(resolve(process.cwd(), 'public/data/strategy-operations'), { recursive: true });
await writeFile(outputPath, `${JSON.stringify(capabilities)}\n`, 'utf8');
console.log(`Published governed strategy capability status for ${capabilityIds.length} formal models.`);
