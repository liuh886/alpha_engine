export type ModelRunChannel = 'local' | 'preview' | 'formal';
export type ModelRunStatus = 'local_only' | 'ci_validated_preview' | 'accepted_formal_baseline' | 'rejected' | 'blocked';
export type ModelRunKind = 'rules_based_allocation' | 'cross_sectional_ranker' | 'forecast_model';
export type SectionAvailability = 'available' | 'not_applicable' | 'not_computed' | 'not_retained' | 'blocked_by_source';

export interface ModelRunSectionDeclaration {
  section_id: string;
  availability_status: SectionAvailability;
  required_for_model_kind: boolean;
  reason: string | null;
  path: string | null;
  sha256: string | null;
  byte_size: number | null;
  media_type: string | null;
}

export interface ModelRunComparabilityKey {
  market: string;
  universe_id: string;
  benchmark_id: string;
  start: string;
  end: string;
  trace_frequency: string;
  horizon: string;
  rebalance_contract_id: string;
  cost_contract_id: string;
}

export interface ModelRunBundleV2Manifest {
  schema_version: '2.0.0';
  model_family_id: string;
  model_version_id: string;
  run_id: string;
  bundle_id: string;
  model_kind: ModelRunKind;
  publication_channel: ModelRunChannel;
  publication_status: ModelRunStatus;
  generated_at: string;
  evidence_cutoff: string;
  research_only: true;
  trade_ready: false;
  comparability_key: ModelRunComparabilityKey;
  sections: ModelRunSectionDeclaration[];
}

export interface CanonicalMetricV2 {
  metric_id: string;
  value: number | null;
  unit: 'ratio' | 'decimal' | 'count' | 'bps';
  direction: 'higher_is_better' | 'lower_is_better' | 'descriptive';
  estimator: string | null;
  annualization: string | null;
  sample_count: number | null;
  scope: string;
  availability_status: SectionAvailability;
  unavailable_reason: string | null;
}

const MODEL_KINDS = new Set<ModelRunKind>(['rules_based_allocation', 'cross_sectional_ranker', 'forecast_model']);
const CHANNELS = new Set<ModelRunChannel>(['local', 'preview', 'formal']);
const STATUSES = new Set<ModelRunStatus>(['local_only', 'ci_validated_preview', 'accepted_formal_baseline', 'rejected', 'blocked']);
const AVAILABILITY = new Set<SectionAvailability>(['available', 'not_applicable', 'not_computed', 'not_retained', 'blocked_by_source']);
const SLUG = /^[a-z0-9][a-z0-9._-]{1,127}$/;
const SHA256 = /^[a-f0-9]{64}$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function requireValue(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function requireSlug(value: unknown, label: string): string {
  const text = String(value ?? '');
  requireValue(SLUG.test(text), `Invalid ${label}`);
  return text;
}

function parseSection(value: unknown): ModelRunSectionDeclaration {
  requireValue(isRecord(value), 'Invalid section declaration');
  const availability = String(value.availability_status) as SectionAvailability;
  requireValue(AVAILABILITY.has(availability), 'Invalid section availability');
  const section: ModelRunSectionDeclaration = {
    section_id: String(value.section_id ?? ''),
    availability_status: availability,
    required_for_model_kind: value.required_for_model_kind === true,
    reason: typeof value.reason === 'string' ? value.reason : null,
    path: typeof value.path === 'string' ? value.path : null,
    sha256: typeof value.sha256 === 'string' ? value.sha256 : null,
    byte_size: typeof value.byte_size === 'number' ? value.byte_size : null,
    media_type: typeof value.media_type === 'string' ? value.media_type : null,
  };
  if (availability === 'available') {
    requireValue(Boolean(section.path?.endsWith('.json')) && !section.path?.includes('..'), `Invalid path for ${section.section_id}`);
    requireValue(Boolean(section.sha256 && SHA256.test(section.sha256)), `Invalid hash for ${section.section_id}`);
    requireValue(Number.isInteger(section.byte_size) && Number(section.byte_size) >= 0, `Invalid size for ${section.section_id}`);
    requireValue(section.media_type === 'application/json', `Invalid media type for ${section.section_id}`);
    requireValue(section.reason === null, `Available ${section.section_id} cannot have a reason`);
  } else {
    requireValue(Boolean(section.reason?.trim()), `Unavailable ${section.section_id} needs a reason`);
    requireValue(section.path === null && section.sha256 === null && section.byte_size === null && section.media_type === null, `Unavailable ${section.section_id} cannot declare a file`);
  }
  return section;
}

export function parseModelRunBundleV2Manifest(value: unknown): ModelRunBundleV2Manifest {
  requireValue(isRecord(value), 'Model Run Bundle v2 manifest is invalid');
  requireValue(value.schema_version === '2.0.0', 'Unsupported Model Run Bundle schema');
  const channel = String(value.publication_channel) as ModelRunChannel;
  const status = String(value.publication_status) as ModelRunStatus;
  const kind = String(value.model_kind) as ModelRunKind;
  requireValue(CHANNELS.has(channel), 'Invalid publication channel');
  requireValue(STATUSES.has(status), 'Invalid publication status');
  requireValue(MODEL_KINDS.has(kind), 'Invalid model kind');
  requireValue(value.research_only === true && value.trade_ready === false, 'Invalid research boundary');
  if (channel === 'formal' || status === 'accepted_formal_baseline') {
    requireValue(channel === 'formal' && status === 'accepted_formal_baseline', 'Formal channel/status mismatch');
  }
  requireValue(typeof value.bundle_id === 'string' && SHA256.test(value.bundle_id), 'Invalid bundle identity');
  requireValue(typeof value.evidence_cutoff === 'string' && DATE.test(value.evidence_cutoff), 'Invalid evidence cutoff');
  requireValue(isRecord(value.comparability_key), 'Comparability key is missing');
  const comparability = value.comparability_key;
  const comparabilityKey: ModelRunComparabilityKey = {
    market: String(comparability.market ?? ''),
    universe_id: requireSlug(comparability.universe_id, 'universe identity'),
    benchmark_id: requireSlug(comparability.benchmark_id, 'benchmark identity'),
    start: String(comparability.start ?? ''),
    end: String(comparability.end ?? ''),
    trace_frequency: String(comparability.trace_frequency ?? ''),
    horizon: String(comparability.horizon ?? ''),
    rebalance_contract_id: requireSlug(comparability.rebalance_contract_id, 'rebalance contract'),
    cost_contract_id: requireSlug(comparability.cost_contract_id, 'cost contract'),
  };
  requireValue(Boolean(comparabilityKey.market && comparabilityKey.trace_frequency && comparabilityKey.horizon), 'Comparability fields are missing');
  requireValue(DATE.test(comparabilityKey.start) && DATE.test(comparabilityKey.end) && comparabilityKey.start <= comparabilityKey.end, 'Invalid comparability interval');
  requireValue(Array.isArray(value.sections), 'Sections are missing');
  const sections = value.sections.map(parseSection);
  requireValue(new Set(sections.map((section) => section.section_id)).size === sections.length, 'Duplicate section declaration');
  requireValue(sections.some((section) => section.section_id === 'summary' && section.availability_status === 'available'), 'Available summary section is required');
  return {
    schema_version: '2.0.0',
    model_family_id: requireSlug(value.model_family_id, 'model family identity'),
    model_version_id: requireSlug(value.model_version_id, 'model version identity'),
    run_id: requireSlug(value.run_id, 'run identity'),
    bundle_id: value.bundle_id,
    model_kind: kind,
    publication_channel: channel,
    publication_status: status,
    generated_at: String(value.generated_at ?? ''),
    evidence_cutoff: value.evidence_cutoff,
    research_only: true,
    trade_ready: false,
    comparability_key: comparabilityKey,
    sections,
  };
}

export function parseCanonicalMetricV2(value: unknown): CanonicalMetricV2 {
  requireValue(isRecord(value), 'Canonical metric is invalid');
  const availability = String(value.availability_status) as SectionAvailability;
  requireValue(AVAILABILITY.has(availability), 'Invalid metric availability');
  const metric: CanonicalMetricV2 = {
    metric_id: String(value.metric_id ?? ''),
    value: typeof value.value === 'number' && Number.isFinite(value.value) ? value.value : null,
    unit: String(value.unit) as CanonicalMetricV2['unit'],
    direction: String(value.direction) as CanonicalMetricV2['direction'],
    estimator: typeof value.estimator === 'string' ? value.estimator : null,
    annualization: typeof value.annualization === 'string' ? value.annualization : null,
    sample_count: typeof value.sample_count === 'number' && Number.isInteger(value.sample_count) ? value.sample_count : null,
    scope: String(value.scope ?? ''),
    availability_status: availability,
    unavailable_reason: typeof value.unavailable_reason === 'string' ? value.unavailable_reason : null,
  };
  if (availability === 'available') {
    requireValue(metric.value !== null && metric.unavailable_reason === null, 'Available metric must contain only a value');
  } else {
    requireValue(metric.value === null && Boolean(metric.unavailable_reason?.trim()), 'Unavailable metric requires a reason');
  }
  return metric;
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (!isRecord(value)) return value;
  return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stableValue(value[key])]));
}

export function canonicalJson(value: unknown): string {
  return `${JSON.stringify(stableValue(value))}\n`;
}

export async function sha256Text(value: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

export async function verifyModelRunBundleId(manifest: ModelRunBundleV2Manifest): Promise<boolean> {
  const { bundle_id: _bundleId, ...identityPayload } = manifest;
  return (await sha256Text(canonicalJson(identityPayload))) === manifest.bundle_id;
}
