import { publicModelDisplayName } from './model-presentation';
import {
  parseModelRunBundleV2Manifest,
  sha256Text,
  verifyModelRunBundleId,
  type ModelRunBundleV2Manifest,
  type ModelRunKind,
} from './model-run-bundle-v2';

export type RunEvidenceStatus = 'complete' | 'partial' | 'blocked';
export type RunDecisionStatus = 'absent' | 'pending' | 'supported' | 'not_supported' | 'blocked';

export interface GovernedRunSummary {
  key: string;
  modelFamilyId: string;
  modelVersionId: string;
  runId: string;
  bundleId: string | null;
  title: string;
  modelKind: ModelRunKind;
  channel: 'formal';
  publicationStatus: 'accepted_formal_baseline';
  market: string;
  benchmark: string;
  generatedAt: string;
  evidenceCutoff: string;
  evidenceStatus: RunEvidenceStatus;
  decisionStatus: RunDecisionStatus;
  manifestPath: string | null;
  manifestSha256: string | null;
  summary: Record<string, unknown>;
  manifest: ModelRunBundleV2Manifest | null;
  loadWarnings: string[];
}

interface ModelRunCatalogRecord {
  model_family_id: string;
  model_version_id: string;
  run_id: string;
  bundle_id: string;
  model_kind: ModelRunKind;
  publication_status: 'accepted_formal_baseline';
  manifest_path: string;
  manifest_sha256: string;
  evidence_cutoff: string;
}

interface ModelRunCatalog {
  schema_version: '2.0.0';
  channel: 'formal';
  generated_at: string;
  records: ModelRunCatalogRecord[];
  research_only: true;
  trade_ready: false;
}

export interface GovernedRunLoadResult {
  runs: GovernedRunSummary[];
  errors: string[];
}

const SHA256 = /^[a-f0-9]{64}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function safeRelativeJsonPath(value: unknown, label: string): string {
  const path = String(value ?? '');
  if (!path.endsWith('.json') || path.startsWith('/') || path.includes('..') || path.includes('\\')) {
    throw new Error(`Unsafe ${label}: ${path}`);
  }
  return path;
}

function assetRoot(): string {
  const base = import.meta.env.BASE_URL.endsWith('/') ? import.meta.env.BASE_URL : `${import.meta.env.BASE_URL}/`;
  return `${base}data/formal-model-runs/`;
}

async function fetchText(path: string): Promise<string> {
  const response = await fetch(`${assetRoot()}${path}`, { cache: 'no-cache' });
  if (!response.ok) throw new Error(`formal model-run asset request failed (${response.status}): ${path}`);
  return response.text();
}

function parseCatalog(value: unknown): ModelRunCatalog {
  if (!isRecord(value) || value.schema_version !== '2.0.0' || value.channel !== 'formal') {
    throw new Error('formal model-run catalog contract is invalid.');
  }
  if (value.research_only !== true || value.trade_ready !== false || !Array.isArray(value.records)) {
    throw new Error('formal model-run catalog research boundary is invalid.');
  }
  const identities = new Set<string>();
  const records = value.records.map((raw, index): ModelRunCatalogRecord => {
    if (!isRecord(raw)) throw new Error(`formal catalog record ${index} is invalid.`);
    const identity = `${String(raw.model_family_id)}:${String(raw.model_version_id)}:${String(raw.run_id)}`;
    if (identities.has(identity)) throw new Error(`Duplicate formal run identity: ${identity}`);
    identities.add(identity);
    const manifestSha = String(raw.manifest_sha256 ?? '');
    const bundleId = String(raw.bundle_id ?? '');
    if (!SHA256.test(manifestSha) || !SHA256.test(bundleId)) throw new Error(`formal digest is invalid: ${identity}`);
    const publicationStatus = String(raw.publication_status);
    if (publicationStatus !== 'accepted_formal_baseline') {
      throw new Error(`Non-formal record entered formal catalog: ${identity}`);
    }
    return {
      model_family_id: String(raw.model_family_id ?? ''),
      model_version_id: String(raw.model_version_id ?? ''),
      run_id: String(raw.run_id ?? ''),
      bundle_id: bundleId,
      model_kind: String(raw.model_kind) as ModelRunKind,
      publication_status: publicationStatus,
      manifest_path: safeRelativeJsonPath(raw.manifest_path, 'formal manifest path'),
      manifest_sha256: manifestSha,
      evidence_cutoff: String(raw.evidence_cutoff ?? ''),
    };
  });
  return {
    schema_version: '2.0.0',
    channel: 'formal',
    generated_at: String(value.generated_at ?? ''),
    records,
    research_only: true,
    trade_ready: false,
  };
}

function summaryTitle(summary: Record<string, unknown>, record: ModelRunCatalogRecord): string {
  const value = summary.title ?? summary.display_name ?? summary.name;
  const fallback = typeof value === 'string' && value.trim() ? value : record.model_version_id;
  return publicModelDisplayName(fallback, {
    modelFamilyId: record.model_family_id,
    modelVersionId: record.model_version_id,
  });
}

function summaryText(summary: Record<string, unknown>, key: string, fallback: string): string {
  const value = summary[key];
  return typeof value === 'string' && value.trim() ? value : fallback;
}

async function loadCatalogRecord(record: ModelRunCatalogRecord): Promise<GovernedRunSummary> {
  const manifestText = await fetchText(record.manifest_path);
  if ((await sha256Text(manifestText)) !== record.manifest_sha256) {
    throw new Error(`formal manifest SHA-256 mismatch: ${record.model_family_id}/${record.run_id}`);
  }
  const manifest = parseModelRunBundleV2Manifest(JSON.parse(manifestText) as unknown);
  if (!(await verifyModelRunBundleId(manifest)) || manifest.bundle_id !== record.bundle_id) {
    throw new Error(`formal bundle identity mismatch: ${record.model_family_id}/${record.run_id}`);
  }
  if (manifest.publication_channel !== 'formal' || manifest.publication_status !== record.publication_status) {
    throw new Error(`formal channel/status mismatch: ${record.model_family_id}/${record.run_id}`);
  }
  const summarySection = manifest.sections.find((section) => section.section_id === 'summary');
  if (!summarySection || summarySection.availability_status !== 'available' || !summarySection.path || !summarySection.sha256) {
    throw new Error(`Required formal summary is unavailable: ${record.model_family_id}/${record.run_id}`);
  }
  const base = record.manifest_path.includes('/')
    ? record.manifest_path.slice(0, record.manifest_path.lastIndexOf('/') + 1)
    : '';
  const summaryPath = safeRelativeJsonPath(`${base}${summarySection.path}`, 'formal summary path');
  const summaryTextValue = await fetchText(summaryPath);
  if ((await sha256Text(summaryTextValue)) !== summarySection.sha256 || new TextEncoder().encode(summaryTextValue).byteLength !== summarySection.byte_size) {
    throw new Error(`Required formal summary integrity mismatch: ${record.model_family_id}/${record.run_id}`);
  }
  const parsed = JSON.parse(summaryTextValue) as unknown;
  if (!isRecord(parsed)) throw new Error(`formal summary must be an object: ${record.model_family_id}/${record.run_id}`);
  const optionalWarnings = manifest.sections
    .filter((section) => section.section_id !== 'decision' && !section.required_for_model_kind && section.availability_status !== 'available')
    .map((section) => `${section.section_id}: ${section.reason ?? section.availability_status}`);
  const requiredBlocked = manifest.sections.some(
    (section) => section.required_for_model_kind && section.availability_status !== 'available',
  );
  return {
    key: `formal:${manifest.model_family_id}:${manifest.model_version_id}:${manifest.run_id}`,
    modelFamilyId: manifest.model_family_id,
    modelVersionId: manifest.model_version_id,
    runId: manifest.run_id,
    bundleId: manifest.bundle_id,
    title: summaryTitle(parsed, record),
    modelKind: manifest.model_kind,
    channel: 'formal',
    publicationStatus: 'accepted_formal_baseline',
    market: manifest.comparability_key.market,
    benchmark: manifest.comparability_key.benchmark_id,
    generatedAt: manifest.generated_at,
    evidenceCutoff: manifest.evidence_cutoff,
    evidenceStatus: requiredBlocked ? 'blocked' : optionalWarnings.length ? 'partial' : 'complete',
    decisionStatus: summaryText(parsed, 'decision_status', 'absent') as RunDecisionStatus,
    manifestPath: record.manifest_path,
    manifestSha256: record.manifest_sha256,
    summary: parsed,
    manifest,
    loadWarnings: optionalWarnings,
  };
}

export async function loadFormalRuns(): Promise<GovernedRunLoadResult> {
  let catalogText: string;
  try {
    catalogText = await fetchText('catalog.json');
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { runs: [], errors: [message] };
  }
  try {
    const catalog = parseCatalog(JSON.parse(catalogText) as unknown);
    const settled = await Promise.allSettled(
      catalog.records.map((record) => loadCatalogRecord(record)),
    );
    const runs: GovernedRunSummary[] = [];
    const errors: string[] = [];
    settled.forEach((result) => {
      if (result.status === 'fulfilled') runs.push(result.value);
      else errors.push(result.reason instanceof Error ? result.reason.message : String(result.reason));
    });
    return { runs, errors };
  } catch (error) {
    return { runs: [], errors: [error instanceof Error ? error.message : String(error)] };
  }
}

// Keep verified public bytes only for the lifetime of the current workspace run.
// Parse a separate value for each consumer so its mutations cannot alter evidence.
const sectionReads = new WeakMap<GovernedRunSummary, Map<string, { identity: string; text: Promise<string> }>>();

export async function loadRunSection(run: GovernedRunSummary, sectionId: string): Promise<unknown> {
  if (!run.manifest || !run.manifestPath || run.channel !== 'formal') {
    throw new Error(`Run section is not Bundle v2-backed: ${run.key}`);
  }
  const section = run.manifest.sections.find((candidate) => candidate.section_id === sectionId);
  if (!section) throw new Error(`Section is undeclared: ${sectionId}`);
  if (section.availability_status !== 'available' || !section.path || !section.sha256 || section.byte_size === null) {
    throw new Error(section.reason || `${sectionId} is ${section.availability_status}`);
  }
  const base = run.manifestPath.includes('/') ? run.manifestPath.slice(0, run.manifestPath.lastIndexOf('/') + 1) : '';
  const path = safeRelativeJsonPath(`${base}${section.path}`, `${sectionId} path`);
  const identity = JSON.stringify([
    run.key, run.bundleId, run.manifestSha256, run.manifestPath, run.evidenceCutoff,
    path, section.sha256, section.byte_size,
  ]);
  let reads = sectionReads.get(run);
  if (!reads) {
    reads = new Map();
    sectionReads.set(run, reads);
  }
  let read = reads.get(sectionId);
  if (read?.identity !== identity) {
    const { sha256, byte_size } = section;
    read = {
      identity,
      text: (async () => {
        const text = await fetchText(path);
        if ((await sha256Text(text)) !== sha256 || new TextEncoder().encode(text).byteLength !== byte_size) {
          throw new Error(`Section integrity mismatch: ${run.key}/${sectionId}`);
        }
        return text;
      })(),
    };
    reads.set(sectionId, read);
  }
  try {
    return JSON.parse(await read.text) as unknown;
  } catch (error) {
    if (reads.get(sectionId) === read) reads.delete(sectionId);
    throw error;
  }
}
