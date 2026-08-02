import type { ModelData } from './data-parser';
import type { BundleArtifact, OpenedResearchBundle } from './research-bundle';

export interface EvidenceArtifactGroup {
  kind: string;
  count: number;
  bytes: number;
  required: number;
}

export function groupArtifacts(artifacts: BundleArtifact[]): EvidenceArtifactGroup[] {
  const groups = new Map<string, EvidenceArtifactGroup>();
  for (const artifact of artifacts) {
    const current = groups.get(artifact.kind) ?? { kind: artifact.kind, count: 0, bytes: 0, required: 0 };
    current.count += 1;
    current.bytes += artifact.byte_size;
    if (artifact.required) current.required += 1;
    groups.set(artifact.kind, current);
  }
  return Array.from(groups.values()).sort((a, b) => b.bytes - a.bytes || a.kind.localeCompare(b.kind));
}

export function findArtifact(bundle: OpenedResearchBundle | null, predicate: (artifact: BundleArtifact) => boolean): BundleArtifact | null {
  return bundle?.manifest.artifacts.find(predicate) ?? null;
}

async function digestBlob(blob: Blob): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

export async function readArtifactText(bundle: OpenedResearchBundle, artifact: BundleArtifact): Promise<string> {
  const blob = await bundle.source.read(artifact.path);
  if (blob.size !== artifact.byte_size) throw new Error(`Artifact size mismatch: ${artifact.path}`);
  if ((await digestBlob(blob)) !== artifact.sha256) throw new Error(`Artifact digest mismatch: ${artifact.path}`);
  return blob.text();
}

export async function readArtifactJson<T>(bundle: OpenedResearchBundle, artifact: BundleArtifact): Promise<T> {
  return JSON.parse(await readArtifactText(bundle, artifact)) as T;
}

export type DataComponentStatus = 'ready' | 'partial' | 'blocked' | 'not_provided' | 'not_applicable';

export interface ModelDataReadinessIndex {
  schema_version: string;
  bundle_id: string;
  built_at: string;
  evidence_cutoff: string;
  research_only: true;
  trade_ready: false;
  summary: {
    component_count: number;
    ready_component_count: number;
    partial_component_count: number;
    blocked_component_count: number;
    ready_training_profiles: string[];
    blocked_training_profiles: string[];
  };
}

export interface DataComponentRecord {
  component_id: string;
  component_kind: string;
  status: DataComponentStatus;
  market: string;
  pool_id: string;
  evidence_cutoff: string | null;
  first_date: string | null;
  last_date: string | null;
  expected_symbol_count: number;
  ready_symbol_count: number;
  coverage_ratio: number;
  missing_symbols: string[];
  invalid_symbols: string[];
  quarantined_symbols: string[];
  providers: string[];
  professional_source_ready: boolean | null;
  research_only: true;
  trade_ready: false;
}

export interface TrainingProfileRecord {
  profile_id: string;
  market: string;
  candidate_pool_id: string;
  candidate_count: number;
  references: string[];
  status: 'ready' | 'blocked';
  failed_gates: string[];
  research_only: true;
  trade_ready: false;
}

export interface DataReadinessEvidence {
  readiness: ModelDataReadinessIndex;
  components: DataComponentRecord[];
  profiles: TrainingProfileRecord[];
}

const COMPONENT_STATUSES = new Set<DataComponentStatus>(['ready', 'partial', 'blocked', 'not_provided', 'not_applicable']);

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

function finiteNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

export function parseDataReadinessEvidence(
  readinessValue: unknown,
  componentsValue: unknown,
  profilesValue: unknown,
): DataReadinessEvidence {
  if (!isRecord(readinessValue)) throw new Error('Model data readiness index is invalid.');
  if (readinessValue.research_only !== true || readinessValue.trade_ready !== false) throw new Error('Model data readiness boundary is invalid.');
  if (!isRecord(readinessValue.summary)) throw new Error('Model data readiness summary is missing.');
  if (!Array.isArray(componentsValue) || !Array.isArray(profilesValue)) throw new Error('Model data component or profile index is invalid.');

  const components: DataComponentRecord[] = componentsValue.map((value) => {
    if (!isRecord(value)) throw new Error('Data component record is invalid.');
    const status = String(value.status) as DataComponentStatus;
    if (!COMPONENT_STATUSES.has(status)) throw new Error(`Unsupported data component status: ${status}`);
    const expected = finiteNumber(value.expected_symbol_count);
    const ready = finiteNumber(value.ready_symbol_count);
    const coverage = finiteNumber(value.coverage_ratio);
    if (expected < 0 || ready < 0 || ready > expected || coverage < 0 || coverage > 1) throw new Error(`Invalid data component coverage: ${String(value.component_id)}`);
    if (value.research_only !== true || value.trade_ready !== false) throw new Error(`Invalid data component boundary: ${String(value.component_id)}`);
    return {
      component_id: String(value.component_id ?? ''),
      component_kind: String(value.component_kind ?? ''),
      status,
      market: String(value.market ?? 'global'),
      pool_id: String(value.pool_id ?? ''),
      evidence_cutoff: value.evidence_cutoff ? String(value.evidence_cutoff) : null,
      first_date: value.first_date ? String(value.first_date) : null,
      last_date: value.last_date ? String(value.last_date) : null,
      expected_symbol_count: expected,
      ready_symbol_count: ready,
      coverage_ratio: coverage,
      missing_symbols: stringArray(value.missing_symbols),
      invalid_symbols: stringArray(value.invalid_symbols),
      quarantined_symbols: stringArray(value.quarantined_symbols),
      providers: stringArray(value.providers),
      professional_source_ready: typeof value.professional_source_ready === 'boolean' ? value.professional_source_ready : null,
      research_only: true,
      trade_ready: false,
    };
  });

  const profiles: TrainingProfileRecord[] = profilesValue.map((value) => {
    if (!isRecord(value)) throw new Error('Training profile record is invalid.');
    const status = String(value.status);
    if (status !== 'ready' && status !== 'blocked') throw new Error(`Unsupported training profile status: ${status}`);
    if (value.research_only !== true || value.trade_ready !== false) throw new Error(`Invalid training profile boundary: ${String(value.profile_id)}`);
    return {
      profile_id: String(value.profile_id ?? ''),
      market: String(value.market ?? ''),
      candidate_pool_id: String(value.candidate_pool_id ?? ''),
      candidate_count: finiteNumber(value.candidate_count),
      references: stringArray(value.references),
      status,
      failed_gates: stringArray(value.failed_gates),
      research_only: true,
      trade_ready: false,
    };
  });

  const summary = readinessValue.summary;
  return {
    readiness: {
      schema_version: String(readinessValue.schema_version ?? ''),
      bundle_id: String(readinessValue.bundle_id ?? ''),
      built_at: String(readinessValue.built_at ?? ''),
      evidence_cutoff: String(readinessValue.evidence_cutoff ?? ''),
      research_only: true,
      trade_ready: false,
      summary: {
        component_count: finiteNumber(summary.component_count),
        ready_component_count: finiteNumber(summary.ready_component_count),
        partial_component_count: finiteNumber(summary.partial_component_count),
        blocked_component_count: finiteNumber(summary.blocked_component_count),
        ready_training_profiles: stringArray(summary.ready_training_profiles),
        blocked_training_profiles: stringArray(summary.blocked_training_profiles),
      },
    },
    components,
    profiles,
  };
}

export async function loadDataReadinessEvidence(bundle: OpenedResearchBundle): Promise<DataReadinessEvidence | null> {
  const readinessArtifact = findArtifact(bundle, (artifact) => artifact.kind === 'data_readiness_index');
  const componentsArtifact = findArtifact(bundle, (artifact) => artifact.kind === 'data_component_index');
  const profilesArtifact = findArtifact(bundle, (artifact) => artifact.kind === 'training_readiness_index');
  if (!readinessArtifact && !componentsArtifact && !profilesArtifact) return null;
  if (!readinessArtifact || !componentsArtifact || !profilesArtifact) throw new Error('Model data readiness indexes are incomplete.');
  const [readiness, components, profiles] = await Promise.all([
    readArtifactJson<unknown>(bundle, readinessArtifact),
    readArtifactJson<unknown>(bundle, componentsArtifact),
    readArtifactJson<unknown>(bundle, profilesArtifact),
  ]);
  return parseDataReadinessEvidence(readiness, components, profiles);
}

export function numericMetric(model: ModelData, aliases: string[]): number | null {
  for (const key of aliases) {
    const value = model.metrics?.[key] ?? model.backtest?.metrics?.[key];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return null;
}

export interface SignalExecutionRow {
  symbol: string;
  signalDate: string;
  executionDate: string;
  action: string;
  weight?: number;
}

function normalizeLedgerRow(row: Record<string, unknown>): SignalExecutionRow | null {
  const signalDate = String(row.signal_date ?? row.signalDate ?? row.decision_date ?? '');
  const executionDate = String(row.execution_date ?? row.executionDate ?? row.trade_date ?? '');
  if (!signalDate || !executionDate) return null;
  return {
    symbol: String(row.symbol ?? row.instrument ?? row.code ?? 'Portfolio'),
    signalDate,
    executionDate,
    action: String(row.action ?? row.side ?? row.event ?? 'rebalance'),
    weight: typeof row.weight === 'number' ? row.weight : typeof row.target_weight === 'number' ? row.target_weight : undefined,
  };
}

export function extractSignalExecutionRows(model: ModelData): SignalExecutionRow[] {
  const candidates: unknown[] = [];
  const params = model.params as Record<string, unknown> | undefined;
  const backtest = model.backtest as unknown as Record<string, unknown> | undefined;
  for (const value of [
    params?.signal_execution_ledger,
    params?.trade_ledger,
    backtest?.signal_execution_ledger,
    backtest?.trade_ledger,
    backtest?.positions,
  ]) {
    if (Array.isArray(value)) candidates.push(...value);
  }
  return candidates
    .filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === 'object')
    .map(normalizeLedgerRow)
    .filter((row): row is SignalExecutionRow => row !== null)
    .sort((a, b) => a.executionDate.localeCompare(b.executionDate));
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}
