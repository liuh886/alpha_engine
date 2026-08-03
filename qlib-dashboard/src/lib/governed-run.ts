import type { ModelData } from './data-parser';
import type { FormalBacktestPackage } from './formal-backtest';
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
  channel: 'preview';
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

function modelRunAssetRoot(): string {
  const base = import.meta.env.BASE_URL.endsWith('/') ? import.meta.env.BASE_URL : `${import.meta.env.BASE_URL}/`;
  return `${base}data/model-runs/`;
}

async function fetchText(path: string): Promise<string> {
  const response = await fetch(`${modelRunAssetRoot()}${path}`, { cache: 'no-cache' });
  if (!response.ok) throw new Error(`Model-run asset request failed (${response.status}): ${path}`);
  return response.text();
}

function parseCatalog(value: unknown): ModelRunCatalog {
  if (!isRecord(value) || value.schema_version !== '2.0.0' || value.channel !== 'preview') {
    throw new Error('Preview model-run catalog contract is invalid.');
  }
  if (value.research_only !== true || value.trade_ready !== false || !Array.isArray(value.records)) {
    throw new Error('Preview model-run catalog research boundary is invalid.');
  }
  const identities = new Set<string>();
  const records = value.records.map((raw, index): ModelRunCatalogRecord => {
    if (!isRecord(raw)) throw new Error(`Preview catalog record ${index} is invalid.`);
    const identity = `${String(raw.model_family_id)}:${String(raw.model_version_id)}:${String(raw.run_id)}`;
    if (identities.has(identity)) throw new Error(`Duplicate preview run identity: ${identity}`);
    identities.add(identity);
    const manifestSha = String(raw.manifest_sha256 ?? '');
    const bundleId = String(raw.bundle_id ?? '');
    if (!SHA256.test(manifestSha) || !SHA256.test(bundleId)) throw new Error(`Preview digest is invalid: ${identity}`);
    return {
      model_family_id: String(raw.model_family_id ?? ''),
      model_version_id: String(raw.model_version_id ?? ''),
      run_id: String(raw.run_id ?? ''),
      bundle_id: bundleId,
      model_kind: String(raw.model_kind) as ModelRunKind,
      publication_status: String(raw.publication_status) as ModelRunStatus,
      manifest_path: safeRelativeJsonPath(raw.manifest_path, 'preview manifest path'),
      manifest_sha256: manifestSha,
      evidence_cutoff: String(raw.evidence_cutoff ?? ''),
    };
  });
  return {
    schema_version: '2.0.0',
    channel: 'preview',
    generated_at: String(value.generated_at ?? ''),
    records,
    research_only: true,
    trade_ready: false,
  };
}

function runKey(channel: ModelRunChannel, family: string, version: string, run: string): string {
  return `${channel}:${family}:${version}:${run}`;
}

function formalKind(modelId: string): ModelRunKind {
  return modelId === 'qqqi_qqq_tqqq_v4_2' ? 'rules_based_allocation' : 'cross_sectional_ranker';
}

export function adaptFormalRuns(packages: FormalBacktestPackage[], models: ModelData[]): GovernedRunSummary[] {
  const byId = new Map(models.map((model) => [model.id, model]));
  return packages.map((formal) => {
    const family = formal.model_id;
    const version = formal.model_id;
    const evidenceStatus: RunEvidenceStatus = formal.evidence_completeness.status === 'complete' ? 'complete' : 'partial';
    return {
      key: runKey('formal', family, version, formal.backtest_id),
      modelFamilyId: family,
      modelVersionId: version,
      runId: formal.backtest_id,
      bundleId: null,
      title: formal.display_name,
      modelKind: formalKind(formal.model_id),
      channel: 'formal',
      publicationStatus: 'accepted_formal_baseline',
      market: formal.market,
      benchmark: formal.benchmark,
      generatedAt: formal.generated_at,
      evidenceCutoff: formal.evidence_cutoff,
      evidenceStatus,
      decisionStatus: 'absent',
      manifestPath: null,
      manifestSha256: null,
      summary: {
        metrics: formal.metrics,
        evidence_completeness: formal.evidence_completeness,
        interpretation_notes: formal.interpretation_notes,
      },
      manifest: null,
      modelData: byId.get(formal.model_id) ?? null,
      formalPackage: formal,
      loadWarnings: ['Temporary v1 formal adapter; migration is completed in PR 7.'],
    };
  });
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
      title: model.name || model.tag || model.id,
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
  return typeof value === 'string' && value.trim() ? value : record.model_version_id;
}

function summaryText(summary: Record<string, unknown>, key: string, fallback: string): string {
  const value = summary[key];
  return typeof value === 'string' && value.trim() ? value : fallback;
}

async function loadPreviewRecord(record: ModelRunCatalogRecord): Promise<GovernedRunSummary> {
  const manifestText = await fetchText(record.manifest_path);
  if ((await sha256Text(manifestText)) !== record.manifest_sha256) {
    throw new Error(`Preview manifest SHA-256 mismatch: ${record.model_family_id}/${record.run_id}`);
  }
  const manifest = parseModelRunBundleV2Manifest(JSON.parse(manifestText) as unknown);
  if (!(await verifyModelRunBundleId(manifest)) || manifest.bundle_id !== record.bundle_id) {
    throw new Error(`Preview bundle identity mismatch: ${record.model_family_id}/${record.run_id}`);
  }
  if (manifest.publication_channel !== 'preview' || manifest.publication_status !== record.publication_status) {
    throw new Error(`Preview channel/status mismatch: ${record.model_family_id}/${record.run_id}`);
  }
  const summarySection = manifest.sections.find((section) => section.section_id === 'summary');
  if (!summarySection || summarySection.availability_status !== 'available' || !summarySection.path || !summarySection.sha256) {
    throw new Error(`Required preview summary is unavailable: ${record.model_family_id}/${record.run_id}`);
  }
  const base = record.manifest_path.includes('/')
    ? record.manifest_path.slice(0, record.manifest_path.lastIndexOf('/') + 1)
    : '';
  const summaryPath = safeRelativeJsonPath(`${base}${summarySection.path}`, 'preview summary path');
  const summaryTextValue = await fetchText(summaryPath);
  if ((await sha256Text(summaryTextValue)) !== summarySection.sha256 || new TextEncoder().encode(summaryTextValue).byteLength !== summarySection.byte_size) {
    throw new Error(`Required preview summary integrity mismatch: ${record.model_family_id}/${record.run_id}`);
  }
  const parsed = JSON.parse(summaryTextValue) as unknown;
  if (!isRecord(parsed)) throw new Error(`Preview summary must be an object: ${record.model_family_id}/${record.run_id}`);
  const optionalWarnings = manifest.sections
    .filter((section) => !section.required_for_model_kind && section.availability_status !== 'available')
    .map((section) => `${section.section_id}: ${section.reason ?? section.availability_status}`);
  const requiredBlocked = manifest.sections.some(
    (section) => section.required_for_model_kind && section.availability_status !== 'available',
  );
  return {
    key: runKey('preview', manifest.model_family_id, manifest.model_version_id, manifest.run_id),
    modelFamilyId: manifest.model_family_id,
    modelVersionId: manifest.model_version_id,
    runId: manifest.run_id,
    bundleId: manifest.bundle_id,
    title: summaryTitle(parsed, record),
    modelKind: manifest.model_kind,
    channel: 'preview',
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

export async function loadPreviewRuns(): Promise<GovernedRunLoadResult> {
  let catalogText: string;
  try {
    catalogText = await fetchText('catalog.json');
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (message.includes('(404)')) return { runs: [], errors: [] };
    return { runs: [], errors: [message] };
  }
  try {
    const catalog = parseCatalog(JSON.parse(catalogText) as unknown);
    const settled = await Promise.allSettled(catalog.records.map(loadPreviewRecord));
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

export async function loadRunSection(run: GovernedRunSummary, sectionId: string): Promise<unknown> {
  if (!run.manifest || !run.manifestPath) throw new Error(`Run section is not v2-backed: ${run.key}`);
  const section = run.manifest.sections.find((candidate) => candidate.section_id === sectionId);
  if (!section) throw new Error(`Section is undeclared: ${sectionId}`);
  if (section.availability_status !== 'available' || !section.path || !section.sha256 || section.byte_size === null) {
    throw new Error(section.reason || `${sectionId} is ${section.availability_status}`);
  }
  const base = run.manifestPath.includes('/') ? run.manifestPath.slice(0, run.manifestPath.lastIndexOf('/') + 1) : '';
  const path = safeRelativeJsonPath(`${base}${section.path}`, `${sectionId} path`);
  const text = await fetchText(path);
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
