import type { ModelData } from './data-parser';
import type { FormalBacktestPackage } from './formal-backtest';
import { publicModelDisplayName } from './model-presentation';
import {
  parseModelRunBundleV2Manifest,
  sha256Text,
  verifyModelRunBundleId,
  type ModelRunBundleV2Manifest,
  type ModelRunChannel,
  type ModelRunKind,
  type ModelRunStatus,
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
  channel: ModelRunChannel;
  publicationStatus: ModelRunStatus;
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
  modelData: ModelData | null;
  /** Transitional type-only field; the production loader never populates v1 formal packages. */
  formalPackage: FormalBacktestPackage | null;
  loadWarnings: string[];
}

interface ModelRunCatalogRecord {
  model_family_id: string;
  model_version_id: string;
  run_id: string;
  bundle_id: string;
  model_kind: ModelRunKind;
  publication_status: ModelRunStatus;
  manifest_path: string;
  manifest_sha256: string;
  evidence_cutoff: string;
}

interface ModelRunCatalog {
  schema_version: '2.0.0';
  channel: 'preview' | 'formal';
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

function assetRoot(channel: 'formal' | 'preview'): string {
  const base = import.meta.env.BASE_URL.endsWith('/') ? import.meta.env.BASE_URL : `${import.meta.env.BASE_URL}/`;
  return channel === 'formal'
    ? `${base}data/formal-model-runs/`
    : `${base}data/model-runs/`;
}

async function fetchText(channel: 'formal' | 'preview', path: string): Promise<string> {
  const response = await fetch(`${assetRoot(channel)}${path}`, { cache: 'no-cache' });
  if (!response.ok) throw new Error(`${channel} model-run asset request failed (${response.status}): ${path}`);
  return response.text();
}

function parseCatalog(value: unknown, expectedChannel: 'formal' | 'preview'): ModelRunCatalog {
  if (!isRecord(value) || value.schema_version !== '2.0.0' || value.channel !== expectedChannel) {
    throw new Error(`${expectedChannel} model-run catalog contract is invalid.`);
  }
  if (value.research_only !== true || value.trade_ready !== false || !Array.isArray(value.records)) {
    throw new Error(`${expectedChannel} model-run catalog research boundary is invalid.`);
  }
  const identities = new Set<string>();
  const records = value.records.map((raw, index): ModelRunCatalogRecord => {
    if (!isRecord(raw)) throw new Error(`${expectedChannel} catalog record ${index} is invalid.`);
    const identity = `${String(raw.model_family_id)}:${String(raw.model_version_id)}:${String(raw.run_id)}`;
    if (identities.has(identity)) throw new Error(`Duplicate ${expectedChannel} run identity: ${identity}`);
    identities.add(identity);
    const manifestSha = String(raw.manifest_sha256 ?? '');
    const bundleId = String(raw.bundle_id ?? '');
    if (!SHA256.test(manifestSha) || !SHA256.test(bundleId)) throw new Error(`${expectedChannel} digest is invalid: ${identity}`);
    const publicationStatus = String(raw.publication_status) as ModelRunStatus;
    if (expectedChannel === 'formal' && publicationStatus !== 'accepted_formal_baseline') {
      throw new Error(`Non-formal record entered formal catalog: ${identity}`);
    }
    return {
      model_family_id: String(raw.model_family_id ?? ''),
      model_version_id: String(raw.model_version_id ?? ''),
      run_id: String(raw.run_id ?? ''),
      bundle_id: bundleId,
      model_kind: String(raw.model_kind) as ModelRunKind,
      publication_status: publicationStatus,
      manifest_path: safeRelativeJsonPath(raw.manifest_path, `${expectedChannel} manifest path`),
      manifest_sha256: manifestSha,
      evidence_cutoff: String(raw.evidence_cutoff ?? ''),
    };
  });
  return {
    schema_version: '2.0.0',
    channel: expectedChannel,
    generated_at: String(value.generated_at ?? ''),
    records,
    research_only: true,
    trade_ready: false,
  };
}

function runKey(channel: ModelRunChannel, family: string, version: string, run: string): string {
  return `${channel}:${family}:${version}:${run}`;
}

export function adaptLocalRuns(models: ModelData[]): GovernedRunSummary[] {
  return models.map((model) => {
    const family = model.id || 'local-model';
    const version = String(model.run_id || model.id || 'local-version');
    const run = String(model.run_id || model.created_at || model.id || 'local-run');
    const market = String(model.market || 'unknown');
    const meta = model.backtest?.meta ?? {};
    return {
      key: runKey('local', family, version, run),
      modelFamilyId: family,
      modelVersionId: version,
      runId: run,
      bundleId: null,
      title: publicModelDisplayName(model.name || model.tag || model.id, { modelId: model.id }),
      modelKind: model.model_type === 'rules_based_rotation' ? 'rules_based_allocation' : 'cross_sectional_ranker',
      channel: 'local',
      publicationStatus: 'local_only',
      market,
      benchmark: String(meta.benchmark || 'not-declared'),
      generatedAt: String(model.created_at || meta.generated_at || ''),
      evidenceCutoff: String(meta.end || ''),
      evidenceStatus: 'partial',
      decisionStatus: 'absent',
      manifestPath: null,
      manifestSha256: null,
      summary: { metrics: model.metrics ?? {}, source: 'local_research_bundle' },
      manifest: null,
      modelData: model,
      formalPackage: null,
      loadWarnings: ['Local adapter does not imply repository acceptance or formal publication.'],
    };
  });
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

async function loadCatalogRecord(
  channel: 'formal' | 'preview',
  record: ModelRunCatalogRecord,
): Promise<GovernedRunSummary> {
  const manifestText = await fetchText(channel, record.manifest_path);
  if ((await sha256Text(manifestText)) !== record.manifest_sha256) {
    throw new Error(`${channel} manifest SHA-256 mismatch: ${record.model_family_id}/${record.run_id}`);
  }
  const manifest = parseModelRunBundleV2Manifest(JSON.parse(manifestText) as unknown);
  if (!(await verifyModelRunBundleId(manifest)) || manifest.bundle_id !== record.bundle_id) {
    throw new Error(`${channel} bundle identity mismatch: ${record.model_family_id}/${record.run_id}`);
  }
  if (manifest.publication_channel !== channel || manifest.publication_status !== record.publication_status) {
    throw new Error(`${channel} channel/status mismatch: ${record.model_family_id}/${record.run_id}`);
  }
  const summarySection = manifest.sections.find((section) => section.section_id === 'summary');
  if (!summarySection || summarySection.availability_status !== 'available' || !summarySection.path || !summarySection.sha256) {
    throw new Error(`Required ${channel} summary is unavailable: ${record.model_family_id}/${record.run_id}`);
  }
  const base = record.manifest_path.includes('/')
    ? record.manifest_path.slice(0, record.manifest_path.lastIndexOf('/') + 1)
    : '';
  const summaryPath = safeRelativeJsonPath(`${base}${summarySection.path}`, `${channel} summary path`);
  const summaryTextValue = await fetchText(channel, summaryPath);
  if ((await sha256Text(summaryTextValue)) !== summarySection.sha256 || new TextEncoder().encode(summaryTextValue).byteLength !== summarySection.byte_size) {
    throw new Error(`Required ${channel} summary integrity mismatch: ${record.model_family_id}/${record.run_id}`);
  }
  const parsed = JSON.parse(summaryTextValue) as unknown;
  if (!isRecord(parsed)) throw new Error(`${channel} summary must be an object: ${record.model_family_id}/${record.run_id}`);
  const optionalWarnings = manifest.sections
    .filter((section) => section.section_id !== 'decision' && !section.required_for_model_kind && section.availability_status !== 'available')
    .map((section) => `${section.section_id}: ${section.reason ?? section.availability_status}`);
  const requiredBlocked = manifest.sections.some(
    (section) => section.required_for_model_kind && section.availability_status !== 'available',
  );
  return {
    key: runKey(channel, manifest.model_family_id, manifest.model_version_id, manifest.run_id),
    modelFamilyId: manifest.model_family_id,
    modelVersionId: manifest.model_version_id,
    runId: manifest.run_id,
    bundleId: manifest.bundle_id,
    title: summaryTitle(parsed, record),
    modelKind: manifest.model_kind,
    channel,
    publicationStatus: manifest.publication_status,
    market: manifest.comparability_key.market,
    benchmark: manifest.comparability_key.benchmark_id,
    generatedAt: manifest.generated_at,
    evidenceCutoff: manifest.evidence_cutoff,
    evidenceStatus: requiredBlocked || manifest.publication_status === 'blocked' ? 'blocked' : optionalWarnings.length ? 'partial' : 'complete',
    decisionStatus: summaryText(parsed, 'decision_status', 'absent') as RunDecisionStatus,
    manifestPath: record.manifest_path,
    manifestSha256: record.manifest_sha256,
    summary: parsed,
    manifest,
    modelData: null,
    formalPackage: null,
    loadWarnings: optionalWarnings,
  };
}

async function loadCatalogRuns(channel: 'formal' | 'preview'): Promise<GovernedRunLoadResult> {
  let catalogText: string;
  try {
    catalogText = await fetchText(channel, 'catalog.json');
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (channel === 'preview' && message.includes('(404)')) return { runs: [], errors: [] };
    return { runs: [], errors: [message] };
  }
  try {
    const catalog = parseCatalog(JSON.parse(catalogText) as unknown, channel);
    const settled = await Promise.allSettled(
      catalog.records.map((record) => loadCatalogRecord(channel, record)),
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

export function loadFormalRuns(): Promise<GovernedRunLoadResult> {
  return loadCatalogRuns('formal');
}

export function loadPreviewRuns(): Promise<GovernedRunLoadResult> {
  return loadCatalogRuns('preview');
}

export async function loadRunSection(run: GovernedRunSummary, sectionId: string): Promise<unknown> {
  if (!run.manifest || !run.manifestPath || run.channel === 'local') {
    throw new Error(`Run section is not Bundle v2-backed: ${run.key}`);
  }
  const channel = run.channel;
  const section = run.manifest.sections.find((candidate) => candidate.section_id === sectionId);
  if (!section) throw new Error(`Section is undeclared: ${sectionId}`);
  if (section.availability_status !== 'available' || !section.path || !section.sha256 || section.byte_size === null) {
    throw new Error(section.reason || `${sectionId} is ${section.availability_status}`);
  }
  const base = run.manifestPath.includes('/') ? run.manifestPath.slice(0, run.manifestPath.lastIndexOf('/') + 1) : '';
  const path = safeRelativeJsonPath(`${base}${section.path}`, `${sectionId} path`);
  const text = await fetchText(channel, path);
  if ((await sha256Text(text)) !== section.sha256 || new TextEncoder().encode(text).byteLength !== section.byte_size) {
    throw new Error(`Section integrity mismatch: ${run.key}/${sectionId}`);
  }
  return JSON.parse(text) as unknown;
}

export function governedRunQuery(run: GovernedRunSummary): string {
  const params = new URLSearchParams({
    channel: run.channel,
    family: run.modelFamilyId,
    version: run.modelVersionId,
    run: run.runId,
  });
  return params.toString();
}

export function selectRunFromQuery(runs: GovernedRunSummary[], search: string): GovernedRunSummary | null {
  const params = new URLSearchParams(search);
  const channel = params.get('channel');
  const family = params.get('family');
  const version = params.get('version');
  const run = params.get('run');
  if (!channel || !family || !version || !run) return null;
  return runs.find((candidate) => (
    candidate.channel === channel
    && candidate.modelFamilyId === family
    && candidate.modelVersionId === version
    && candidate.runId === run
  )) ?? null;
}
