import { assetUrl } from './runtime-capabilities';

export type StrategyOperationsSource = 'github_issue_v42' | 'github_issue_byd' | 'unavailable';
export type StrategyPipelineStatus = 'available' | 'unavailable';

export interface StrategyCapability {
  modelVersionId: string;
  sourceType: StrategyOperationsSource;
  pipelineStatus: StrategyPipelineStatus;
  decisionCadence: string;
  nextDecisionPolicy: string;
  factorEvidenceStatus: string;
  note: string;
}

interface StrategyCapabilityDocument {
  schema_version: '1.0.0';
  generated_at: string;
  research_only: true;
  trade_ready: false;
  records: Array<{
    model_version_id: string;
    source_type: StrategyOperationsSource;
    pipeline_status: StrategyPipelineStatus;
    decision_cadence: string;
    next_decision_policy: string;
    factor_evidence_status: string;
    note: string;
  }>;
}

const SOURCES = new Set<StrategyOperationsSource>(['github_issue_v42', 'github_issue_byd', 'unavailable']);
const PIPELINE_STATUS = new Set<StrategyPipelineStatus>(['available', 'unavailable']);

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function parseDocument(value: unknown): StrategyCapability[] {
  assert(Boolean(value) && typeof value === 'object' && !Array.isArray(value), 'Strategy capability document is invalid');
  const document = value as Partial<StrategyCapabilityDocument>;
  assert(document.schema_version === '1.0.0', 'Unsupported strategy capability schema');
  assert(document.research_only === true && document.trade_ready === false, 'Invalid strategy capability boundary');
  assert(Array.isArray(document.records), 'Strategy capability records are missing');

  const capabilities = document.records.map((record) => {
    assert(Boolean(record) && typeof record === 'object', 'Invalid strategy capability record');
    assert(typeof record.model_version_id === 'string' && record.model_version_id.length > 0, 'Strategy capability model identity is missing');
    assert(SOURCES.has(record.source_type), `Unsupported strategy operations source for ${record.model_version_id}`);
    assert(PIPELINE_STATUS.has(record.pipeline_status), `Unsupported strategy pipeline status for ${record.model_version_id}`);
    assert(typeof record.decision_cadence === 'string' && record.decision_cadence.length > 0, `Missing decision cadence for ${record.model_version_id}`);
    assert(typeof record.next_decision_policy === 'string' && record.next_decision_policy.length > 0, `Missing next decision policy for ${record.model_version_id}`);
    assert(typeof record.factor_evidence_status === 'string' && record.factor_evidence_status.length > 0, `Missing factor evidence status for ${record.model_version_id}`);
    assert(typeof record.note === 'string' && record.note.length > 0, `Missing capability note for ${record.model_version_id}`);
    if (record.source_type === 'unavailable') assert(record.pipeline_status === 'unavailable', `Unavailable source must fail closed for ${record.model_version_id}`);
    else assert(record.pipeline_status === 'available', `Operational source must declare an available pipeline for ${record.model_version_id}`);
    return {
      modelVersionId: record.model_version_id,
      sourceType: record.source_type,
      pipelineStatus: record.pipeline_status,
      decisionCadence: record.decision_cadence,
      nextDecisionPolicy: record.next_decision_policy,
      factorEvidenceStatus: record.factor_evidence_status,
      note: record.note,
    } satisfies StrategyCapability;
  });

  assert(new Set(capabilities.map((record) => record.modelVersionId)).size === capabilities.length, 'Duplicate strategy capability model identity');
  return capabilities;
}

export async function fetchStrategyCapabilities(): Promise<Map<string, StrategyCapability>> {
  const response = await fetch(assetUrl('data/strategy-operations/capabilities.json'), { cache: 'no-store' });
  if (!response.ok) throw new Error(`Strategy capability document unavailable (${response.status})`);
  const capabilities = parseDocument(await response.json());
  return new Map(capabilities.map((capability) => [capability.modelVersionId, capability]));
}
