import type { ModelData } from './data-parser';
import type {
  FormalBacktestPackage,
  FormalBacktestTrade,
} from './formal-backtest';
import type { SectionAvailability } from './model-run-bundle-v2';

export type FormalModelKind = 'rules_based_allocation' | 'cross_sectional_ranker';

export interface FormalMetricProjection {
  value: number | null;
  availability: SectionAvailability;
  reason: string;
}

export interface FormalEvidenceProjection {
  formal: FormalBacktestPackage | null;
  modelKind: FormalModelKind;
  trades: FormalBacktestTrade[];
  tradeAvailability: string;
  attribution: FormalBacktestPackage['attribution'];
  attributionAvailability: string;
  costBps: number | null;
  costAvailability: string;
}

interface ModelKindIdentity {
  id?: string;
  model_type?: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

export function getFormalBacktest(model: ModelData): FormalBacktestPackage | null {
  const formal = (model.backtest as ModelData['backtest'] & {
    formalBacktest?: FormalBacktestPackage;
  })?.formalBacktest;
  return formal ?? null;
}

export function inferFormalModelKind(
  formal: FormalBacktestPackage | null,
  model?: ModelKindIdentity,
): FormalModelKind {
  const modelId = formal?.model_id ?? model?.id ?? '';
  const modelType = String(model?.model_type ?? '').toLowerCase();
  if (
    modelId.startsWith('qqqi_qqq_tqqq_')
    || modelId.startsWith('byd_v')
    || modelType.includes('rotation')
    || modelType.includes('allocation')
  ) {
    return 'rules_based_allocation';
  }
  return 'cross_sectional_ranker';
}

function evidenceReason(
  formal: FormalBacktestPackage | null,
  component: 'trades' | 'attribution' | 'metrics' | 'costs',
): string {
  if (!formal) return 'No formal package is attached to this record.';
  if (component === 'metrics') return 'This metric is not retained by the formal package.';
  if (component === 'costs') return 'The formal portfolio contract does not declare a cost rate.';
  const declared = formal.evidence_completeness[component];
  if (typeof declared === 'string' && declared.trim()) {
    return declared.split('_').join(' ');
  }
  if (formal.evidence_completeness.missing.includes(component)) {
    return `${component} are blocked or were not retained by the governed source evidence.`;
  }
  return `${component} are not retained by the formal package.`;
}

function isCrossSectionalMetric(aliases: string[]): boolean {
  const normalized = aliases.map((value) => value.toLowerCase().split(' ').join('_'));
  return normalized.some((value) => ['ic', 'rank_ic', 'icir', 'ic_ir'].includes(value));
}

export function projectFormalMetric(
  model: ModelData,
  aliases: string[],
): FormalMetricProjection {
  for (const key of aliases) {
    const value = model.backtest?.metrics?.[key] ?? model.metrics?.[key];
    if (typeof value === 'number' && Number.isFinite(value)) {
      return { value, availability: 'available', reason: '' };
    }
  }
  const formal = getFormalBacktest(model);
  if (inferFormalModelKind(formal, model) === 'rules_based_allocation' && isCrossSectionalMetric(aliases)) {
    return {
      value: null,
      availability: 'not_applicable',
      reason: 'Cross-sectional prediction metrics do not apply to rules-based allocation models.',
    };
  }
  if (formal?.evidence_completeness.status === 'partial') {
    return {
      value: null,
      availability: 'blocked_by_source',
      reason: evidenceReason(formal, 'metrics'),
    };
  }
  if (formal) {
    return {
      value: null,
      availability: 'not_retained',
      reason: evidenceReason(formal, 'metrics'),
    };
  }
  return {
    value: null,
    availability: 'not_computed',
    reason: 'No governed formal metric is attached to this record.',
  };
}

export function projectFormalPackage(
  formal: FormalBacktestPackage | null,
  model?: ModelKindIdentity,
): FormalEvidenceProjection {
  const contract = isRecord(formal?.portfolio_contract)
    ? formal.portfolio_contract
    : {};
  const rawCost = contract.cost_bps ?? contract.transaction_cost_bps;
  const costBps = typeof rawCost === 'number' && Number.isFinite(rawCost)
    ? rawCost
    : null;
  const attribution = formal?.attribution.filter(
    (row) => typeof row.value === 'number' && Number.isFinite(row.value),
  ) ?? [];
  return {
    formal,
    modelKind: inferFormalModelKind(formal, model),
    trades: formal?.trades ?? [],
    tradeAvailability: formal?.trades.length
      ? 'Retained formal transaction ledger.'
      : evidenceReason(formal, 'trades'),
    attribution,
    attributionAvailability: attribution.length
      ? 'Retained formal contribution ledger.'
      : evidenceReason(formal, 'attribution'),
    costBps,
    costAvailability: costBps === null
      ? evidenceReason(formal, 'costs')
      : 'Declared by formal.portfolio_contract.',
  };
}

export function projectFormalEvidence(model: ModelData): FormalEvidenceProjection {
  return projectFormalPackage(getFormalBacktest(model), model);
}

export function modelKindLabel(kind: FormalModelKind): string {
  return kind === 'rules_based_allocation'
    ? 'Rules-based allocation'
    : 'Cross-sectional ranker';
}
