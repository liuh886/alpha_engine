import { createHash } from 'node:crypto';
import { copyFile, mkdir, readFile, rm } from 'node:fs/promises';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const dashboardRoot = resolve(scriptDir, '..');
const repositoryRoot = resolve(dashboardRoot, '..');
const sourceRoot = join(repositoryRoot, 'data', 'research', 'formal_backtests');
const targetRoot = join(dashboardRoot, 'public', 'data', 'formal-backtests');

function assertRecord(value, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${label} must be a JSON object.`);
  }
  return value;
}

function safeFilename(value) {
  if (typeof value !== 'string' || value.length === 0 || isAbsolute(value) || value.includes('/') || value.includes('\\')) {
    throw new Error(`Unsafe formal backtest path: ${String(value)}`);
  }
  return value;
}

function sha256(buffer) {
  return createHash('sha256').update(buffer).digest('hex');
}

async function readJson(path, label) {
  const bytes = await readFile(path);
  let parsed;
  try {
    parsed = JSON.parse(bytes.toString('utf8'));
  } catch (error) {
    throw new Error(`${label} contains invalid JSON: ${error instanceof Error ? error.message : String(error)}`);
  }
  return { bytes, value: assertRecord(parsed, label) };
}

const { bytes: catalogBytes, value: catalog } = await readJson(join(sourceRoot, 'catalog.json'), 'Formal backtest catalog');
const { bytes: freshnessBytes, value: freshness } = await readJson(join(sourceRoot, 'freshness.json'), 'Formal backtest freshness policy');
if (catalog.schema_version !== '1.0.0') throw new Error('Unsupported formal backtest catalog schema.');
if (catalog.publication_policy !== 'formal_named_baselines_only') throw new Error('Formal catalog publication policy is invalid.');
if (catalog.research_only !== true || catalog.trade_ready !== false) throw new Error('Formal catalog research boundary is invalid.');
if (!Array.isArray(catalog.records) || catalog.records.length === 0) throw new Error('Formal catalog contains no records.');
if (freshness.schema_version !== '1.0.0' || freshness.cutoff_policy !== 'latest_completed_trading_session') {
  throw new Error('Formal freshness policy is invalid.');
}
if (freshness.research_only !== true || freshness.trade_ready !== false) {
  throw new Error('Formal freshness research boundary is invalid.');
}
const marketCutoffs = assertRecord(freshness.markets, 'Formal freshness market cutoffs');
const nextSessionCloses = assertRecord(freshness.next_session_close_utc, 'Formal freshness next-session closes');
if (JSON.stringify(Object.keys(marketCutoffs).sort()) !== JSON.stringify(Object.keys(nextSessionCloses).sort())) {
  throw new Error('Formal freshness market and next-session-close bindings differ.');
}
if (!Array.isArray(freshness.required_models) || freshness.required_models.length === 0) {
  throw new Error('Formal freshness required model list is missing.');
}

const seen = new Set();
const acceptedFiles = [];
for (const rawEntry of catalog.records) {
  const entry = assertRecord(rawEntry, 'Formal catalog record');
  const modelId = String(entry.model_id ?? '');
  if (!modelId || seen.has(modelId)) throw new Error(`Duplicate or missing formal model ID: ${modelId}`);
  seen.add(modelId);
  if (entry.publication_status !== 'accepted_formal_baseline') throw new Error(`Non-formal record is not publishable: ${modelId}`);
  const filename = safeFilename(entry.path);
  const { bytes, value: payload } = await readJson(join(sourceRoot, filename), `Formal backtest ${modelId}`);
  if (sha256(bytes) !== entry.sha256) throw new Error(`Formal backtest digest mismatch: ${modelId}`);
  if (payload.schema_version !== '1.0.0' || payload.record_type !== 'formal_model_backtest') throw new Error(`Unsupported formal backtest contract: ${modelId}`);
  if (payload.publication_status !== 'accepted_formal_baseline') throw new Error(`Formal backtest is not accepted: ${modelId}`);
  if (payload.model_id !== modelId) throw new Error(`Formal catalog/model mismatch: ${modelId}`);
  if (payload.research_only !== true || payload.trade_ready !== false) throw new Error(`Formal backtest research boundary is invalid: ${modelId}`);
  if (!Array.isArray(payload.report) || payload.report.length === 0) throw new Error(`Formal backtest has no retained performance path: ${modelId}`);
  if (!payload.evidence_completeness || typeof payload.evidence_completeness.status !== 'string') throw new Error(`Formal backtest completeness is missing: ${modelId}`);
  const market = String(payload.market ?? '');
  const requiredCutoff = String(marketCutoffs[market] ?? '');
  if (!requiredCutoff) throw new Error(`Formal freshness cutoff is missing for ${modelId}/${market}.`);
  if (payload.evidence_cutoff !== requiredCutoff) {
    throw new Error(`Formal backtest is stale: ${modelId}; expected ${requiredCutoff}, found ${String(payload.evidence_cutoff)}.`);
  }
  acceptedFiles.push({ filename, bytes });
}

if (seen.size !== freshness.required_models.length || freshness.required_models.some((modelId) => !seen.has(String(modelId)))) {
  throw new Error('Formal catalog does not exactly match freshness required_models.');
}

await rm(targetRoot, { recursive: true, force: true });
await mkdir(targetRoot, { recursive: true });
await copyFile(join(sourceRoot, 'catalog.json'), join(targetRoot, 'catalog.json'));
await copyFile(join(sourceRoot, 'freshness.json'), join(targetRoot, 'freshness.json'));
for (const { filename } of acceptedFiles) {
  await copyFile(join(sourceRoot, filename), join(targetRoot, filename));
}

console.log(
  `Published ${acceptedFiles.length} current formal model backtests from ${sourceRoot}. `
  + `Catalog SHA-256: ${sha256(catalogBytes)}; freshness SHA-256: ${sha256(freshnessBytes)}`,
);
