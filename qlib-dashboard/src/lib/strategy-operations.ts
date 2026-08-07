import type { GovernedRunSummary } from './governed-run';
import { fetchBydRuntimeSnapshot, type BydSignalRecord } from './byd-runtime';
import { fetchQqqV43RuntimeSnapshot, type QqqV43SignalRecord } from './qqq-v4-3-runtime';
import { fetchStrategyCapabilities, type StrategyCapability } from './strategy-capabilities';

export type StrategyOperationalStatus =
  | 'pipeline_unavailable'
  | 'awaiting_observation'
  | 'current_no_change'
  | 'target_pending_execution'
  | 'execution_observed'
  | 'stale'
  | 'blocked'
  | 'delivery_failed';

export type StrategyFreshness = 'current' | 'stale' | 'blocked' | 'unknown';

export interface StrategyAllocationLeg {
  asset: string;
  current: number;
  target: number;
  delta: number;
}

export interface StrategyDriver {
  label: string;
  value: string;
}

export interface StrategyOperationsSnapshot {
  strategyId: string;
  status: StrategyOperationalStatus;
  asOf: string | null;
  latestCompletedSession: string | null;
  decisionCadence: string;
  nextDecision: string;
  stateLabel: string;
  decisionReason: string;
  allocations: StrategyAllocationLeg[];
  turnover: number | null;
  estimatedCost: number | null;
  dataFreshness: StrategyFreshness;
  factorFreshness: StrategyFreshness;
  deliveryStatus: string;
  sourceLabel: string;
  sourceHref: string | null;
  note: string;
  drivers: StrategyDriver[];
}

const STATE_LABELS: Record<number, string> = {
  0: 'Defensive',
  1: 'Transition',
  2: 'Risk-on',
};

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function percent(value: unknown, digits = 1): string {
  return finite(value) ? `${(value * 100).toFixed(digits)}%` : '—';
}

function decimal(value: unknown, digits = 2): string {
  return finite(value) ? value.toFixed(digits) : '—';
}

function factorFreshness(capability: StrategyCapability): StrategyFreshness {
  return capability.factorEvidenceStatus === 'current'
    ? 'current'
    : capability.factorEvidenceStatus === 'stale'
      ? 'stale'
      : capability.factorEvidenceStatus === 'blocked' || capability.factorEvidenceStatus === 'pending_canonical_contract'
        ? 'blocked'
        : 'unknown';
}

function allocationLegs(current: Record<string, number>, target: Record<string, number>): StrategyAllocationLeg[] {
  return Array.from(new Set([...Object.keys(current), ...Object.keys(target)]))
    .sort()
    .map((asset) => {
      const currentWeight = finite(current[asset]) ? current[asset] : 0;
      const targetWeight = finite(target[asset]) ? target[asset] : 0;
      return {
        asset,
        current: currentWeight,
        target: targetWeight,
        delta: targetWeight - currentWeight,
      };
    });
}

function hasAllocationChange(allocations: StrategyAllocationLeg[]): boolean {
  return allocations.some((leg) => Math.abs(leg.delta) > 1e-9);
}

function unavailable(
  run: GovernedRunSummary,
  status: StrategyOperationalStatus,
  note: string,
  capability?: StrategyCapability,
): StrategyOperationsSnapshot {
  return {
    strategyId: run.modelVersionId,
    status,
    asOf: null,
    latestCompletedSession: run.evidenceCutoff || null,
    decisionCadence: capability?.decisionCadence ?? 'Capability not declared',
    nextDecision: capability?.nextDecisionPolicy ?? 'Operating capability unavailable',
    stateLabel: status === 'pipeline_unavailable' ? 'No governed live signal' : 'Operating evidence unavailable',
    decisionReason: note,
    allocations: [],
    turnover: null,
    estimatedCost: null,
    dataFreshness: 'unknown',
    factorFreshness: capability ? factorFreshness(capability) : 'unknown',
    deliveryStatus: 'not available',
    sourceLabel: 'Formal model evidence only',
    sourceHref: null,
    note,
    drivers: [],
  };
}

function qqqV43Snapshot(
  run: GovernedRunSummary,
  capability: StrategyCapability,
  record: QqqV43SignalRecord,
  issueUrl: string,
): StrategyOperationsSnapshot {
  const allocations = allocationLegs(record.current_weights, record.target_weights);
  const changed = hasAllocationChange(allocations);
  const status: StrategyOperationalStatus = !record.data_freshness_ok
    ? 'stale'
    : changed
      ? 'target_pending_execution'
      : 'current_no_change';
  const stateFrom = STATE_LABELS[record.current_formal_state] ?? `State ${record.current_formal_state}`;
  const stateTo = STATE_LABELS[record.target_formal_state] ?? `State ${record.target_formal_state}`;
  const context = record.context;

  return {
    strategyId: run.modelVersionId,
    status,
    asOf: record.signal_date,
    latestCompletedSession: record.latest_data_date,
    decisionCadence: capability.decisionCadence,
    nextDecision: capability.nextDecisionPolicy,
    stateLabel: record.current_formal_state === record.target_formal_state ? stateTo : `${stateFrom} → ${stateTo}`,
    decisionReason: `${record.current_overlay} → ${record.target_overlay}`,
    allocations,
    turnover: finite(record.turnover_units) ? record.turnover_units : null,
    estimatedCost: finite(record.estimated_transaction_cost) ? record.estimated_transaction_cost : null,
    dataFreshness: record.data_freshness_ok ? 'current' : 'stale',
    factorFreshness: factorFreshness(capability),
    deliveryStatus: 'governed signal published',
    sourceLabel: 'Governed QQQ v4.3 signal ledger',
    sourceHref: issueUrl,
    note: changed
      ? 'A v4.3 target-weight change is published for the next market open; brokerage execution remains outside Alpha Engine.'
      : 'Latest governed v4.3 evaluation retained the existing allocation.',
    drivers: [
      { label: 'Risk layer', value: record.target_overlay },
      { label: 'RSI(14)', value: decimal(record.rsi_14) },
      { label: 'Fear & Greed', value: decimal(record.fear_greed_score) },
      { label: 'VIX close', value: decimal(context.vix_close) },
      { label: 'VXN close', value: decimal(context.vxn_close) },
      { label: 'QQQ / MA20', value: `${decimal(context.qqq_close)} / ${decimal(context.ma20)}` },
      { label: 'MA200 falling', value: record.ma200_falling ? 'Yes' : 'No' },
      { label: 'Strong defense', value: record.strong_defense ? 'Yes' : 'No' },
      { label: 'Panic Repair', value: record.panic_repair_active ? 'Yes' : 'No' },
    ],
  };
}

function bydSnapshot(
  run: GovernedRunSummary,
  capability: StrategyCapability,
  record: BydSignalRecord,
  issueUrl: string,
): StrategyOperationsSnapshot {
  const allocations = allocationLegs(record.current_weights, record.target_weights);
  const changed = hasAllocationChange(allocations);
  const status: StrategyOperationalStatus = !record.data_freshness_ok
    ? 'stale'
    : changed
      ? 'target_pending_execution'
      : 'current_no_change';

  return {
    strategyId: run.modelVersionId,
    status,
    asOf: record.signal_date,
    latestCompletedSession: record.latest_data_date,
    decisionCadence: capability.decisionCadence,
    nextDecision: capability.nextDecisionPolicy,
    stateLabel: record.target_mode_label || record.target_mode,
    decisionReason: record.transition_label || record.transition_type,
    allocations,
    turnover: finite(record.turnover_units) ? record.turnover_units : null,
    estimatedCost: finite(record.estimated_transaction_cost) ? record.estimated_transaction_cost : null,
    dataFreshness: record.data_freshness_ok ? 'current' : 'stale',
    factorFreshness: factorFreshness(capability),
    deliveryStatus: record.should_alert ? 'alert required' : 'not required',
    sourceLabel: 'Governed BYD signal ledger',
    sourceHref: issueUrl,
    note: changed
      ? 'Target allocation is published; brokerage execution is outside Alpha Engine.'
      : 'Latest governed evaluation retained the existing allocation.',
    drivers: [
      { label: 'Market state', value: record.factor_context.market_state || '—' },
      { label: 'Volatility state', value: record.factor_context.vol_state || '—' },
      { label: '20D momentum', value: percent(record.factor_context.mom_20, 2) },
      { label: '60D momentum', value: percent(record.factor_context.mom_60, 2) },
      { label: '252D drawdown', value: percent(record.factor_context.drawdown_252, 2) },
      { label: 'Financed increment', value: percent(record.factor_context.financed_increment, 2) },
    ],
  };
}

async function loadOne(run: GovernedRunSummary, capability: StrategyCapability): Promise<StrategyOperationsSnapshot> {
  if (capability.pipelineStatus === 'unavailable' || capability.sourceType === 'unavailable') {
    return unavailable(run, 'pipeline_unavailable', capability.note, capability);
  }

  if (capability.sourceType === 'github_issue_v43') {
    try {
      const snapshot = await fetchQqqV43RuntimeSnapshot();
      return qqqV43Snapshot(run, capability, snapshot.latestSignal.record, snapshot.latestSignal.issue.html_url);
    } catch (error) {
      return unavailable(run, 'blocked', error instanceof Error ? error.message : 'QQQ v4.3 operating evidence is unavailable.', capability);
    }
  }

  if (capability.sourceType === 'github_issue_byd') {
    try {
      const snapshot = await fetchBydRuntimeSnapshot();
      const event = snapshot.latestSignal;
      if (!event) return unavailable(run, 'awaiting_observation', 'BYD signal pipeline is waiting for its first valid production observation.', capability);
      return bydSnapshot(run, capability, event.record, event.issue.html_url);
    } catch (error) {
      return unavailable(run, 'blocked', error instanceof Error ? error.message : 'BYD operating evidence is unavailable.', capability);
    }
  }

  return unavailable(run, 'blocked', `Unsupported governed operations source: ${capability.sourceType}`, capability);
}

export async function loadStrategyOperations(runs: GovernedRunSummary[]): Promise<Map<string, StrategyOperationsSnapshot>> {
  const formalRuns = runs.filter((run) => run.channel === 'formal');
  let capabilities: Map<string, StrategyCapability>;
  try {
    capabilities = await fetchStrategyCapabilities();
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Strategy capability document is unavailable.';
    return new Map(formalRuns.map((run) => [run.modelVersionId, unavailable(run, 'blocked', message)]));
  }

  const snapshots = await Promise.all(formalRuns.map((run) => {
    const capability = capabilities.get(run.modelVersionId);
    return capability
      ? loadOne(run, capability)
      : Promise.resolve(unavailable(run, 'blocked', 'Accepted formal model is missing from the governed strategy capability document.'));
  }));
  return new Map(snapshots.map((snapshot) => [snapshot.strategyId, snapshot]));
}

export const STRATEGY_STATUS_LABEL: Record<StrategyOperationalStatus, string> = {
  pipeline_unavailable: 'Signal unavailable',
  awaiting_observation: 'Awaiting observation',
  current_no_change: 'Current · no change',
  target_pending_execution: 'New target',
  execution_observed: 'Execution observed',
  stale: 'Stale data',
  blocked: 'Operating data blocked',
  delivery_failed: 'Delivery failed',
};
