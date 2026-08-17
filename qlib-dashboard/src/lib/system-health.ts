export type SystemHealthState = 'current' | 'delayed' | 'blocked' | 'inconsistent' | 'not_applicable';

export interface SystemHealthMarket {
  market: string;
  state: SystemHealthState;
  market_expected_cutoff: string | null;
  market_expected_cutoff_source: string;
  provider_cutoff: string | null;
  provider_cutoff_source: string;
  provider_lag_sessions: number | null;
  provider_lag_exact: boolean;
  provider_formal_consistency: SystemHealthState;
}

export interface SystemHealthStrategy {
  strategy_id: string;
  model_version_id: string;
  market: string;
  state: SystemHealthState;
  market_expected_cutoff: string | null;
  provider_cutoff: string | null;
  formal_cutoff: string | null;
  model_data_cutoff: string | null;
  factor_cutoff: string | null;
  last_signal_evaluation: string | null;
  last_signal_change: string | null;
  delivery_state: SystemHealthState;
  delivery_status: string | null;
  stages: Record<'provider' | 'formal' | 'model_data' | 'factor' | 'signal' | 'delivery', SystemHealthState>;
  formal_bundle_id: string;
  formal_run_id: string;
}

export interface SystemHealthSnapshot {
  schema_version: '1.0.0';
  generated_at: string;
  state: SystemHealthState;
  markets: SystemHealthMarket[];
  strategies: SystemHealthStrategy[];
  deployment: {
    state: SystemHealthState;
    expected_commit_sha: string | null;
    workflow_run_id: string | null;
    live_acceptance: string;
    receipt: 'deployment.json';
  };
  model_data: {
    state: SystemHealthState;
    evidence_cutoff: string | null;
    bundle_id: string | null;
  };
  research_only: true;
  trade_ready: false;
}

export interface LiveSystemHealth {
  health: SystemHealthSnapshot | null;
  status: SystemHealthState | 'unknown';
  deploymentStatus: SystemHealthState | 'unknown';
  message: string;
}

const STATES = new Set<SystemHealthState>(['current', 'delayed', 'blocked', 'inconsistent', 'not_applicable']);

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function state(value: unknown, label: string): SystemHealthState {
  if (typeof value !== 'string' || !STATES.has(value as SystemHealthState)) {
    throw new Error(`Invalid system-health state: ${label}.`);
  }
  return value as SystemHealthState;
}

function nullableString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

export function parseSystemHealth(value: unknown): SystemHealthSnapshot {
  if (!isObject(value)
    || value.schema_version !== '1.0.0'
    || value.research_only !== true
    || value.trade_ready !== false
    || !Array.isArray(value.markets)
    || !Array.isArray(value.strategies)
    || !isObject(value.deployment)
    || !isObject(value.model_data)) {
    throw new Error('System health contract is invalid.');
  }
  const markets = value.markets.map((item, index) => {
    if (!isObject(item)) throw new Error(`System health market ${index} is invalid.`);
    return {
      market: String(item.market ?? ''),
      state: state(item.state, `market ${index}`),
      market_expected_cutoff: nullableString(item.market_expected_cutoff),
      market_expected_cutoff_source: String(item.market_expected_cutoff_source ?? ''),
      provider_cutoff: nullableString(item.provider_cutoff),
      provider_cutoff_source: String(item.provider_cutoff_source ?? ''),
      provider_lag_sessions: typeof item.provider_lag_sessions === 'number' ? item.provider_lag_sessions : null,
      provider_lag_exact: item.provider_lag_exact === true,
      provider_formal_consistency: state(item.provider_formal_consistency, `market consistency ${index}`),
    };
  });
  const strategies = value.strategies.map((item, index) => {
    if (!isObject(item) || !isObject(item.stages)) throw new Error(`System health strategy ${index} is invalid.`);
    const stages = item.stages;
    return {
      strategy_id: String(item.strategy_id ?? ''),
      model_version_id: String(item.model_version_id ?? ''),
      market: String(item.market ?? ''),
      state: state(item.state, `strategy ${index}`),
      market_expected_cutoff: nullableString(item.market_expected_cutoff),
      provider_cutoff: nullableString(item.provider_cutoff),
      formal_cutoff: nullableString(item.formal_cutoff),
      model_data_cutoff: nullableString(item.model_data_cutoff),
      factor_cutoff: nullableString(item.factor_cutoff),
      last_signal_evaluation: nullableString(item.last_signal_evaluation),
      last_signal_change: nullableString(item.last_signal_change),
      delivery_state: state(item.delivery_state, `delivery ${index}`),
      delivery_status: nullableString(item.delivery_status),
      stages: {
        provider: state(stages.provider, `provider ${index}`),
        formal: state(stages.formal, `formal ${index}`),
        model_data: state(stages.model_data, `model_data ${index}`),
        factor: state(stages.factor, `factor ${index}`),
        signal: state(stages.signal, `signal ${index}`),
        delivery: state(stages.delivery, `delivery ${index}`),
      },
      formal_bundle_id: String(item.formal_bundle_id ?? ''),
      formal_run_id: String(item.formal_run_id ?? ''),
    };
  });
  if (markets.length === 0 || strategies.length === 0) throw new Error('System health records are empty.');
  return {
    schema_version: '1.0.0',
    generated_at: String(value.generated_at ?? ''),
    state: state(value.state, 'root'),
    markets,
    strategies,
    deployment: {
      state: state(value.deployment.state, 'deployment'),
      expected_commit_sha: nullableString(value.deployment.expected_commit_sha),
      workflow_run_id: nullableString(value.deployment.workflow_run_id),
      live_acceptance: String(value.deployment.live_acceptance ?? ''),
      receipt: 'deployment.json',
    },
    model_data: {
      state: state(value.model_data.state, 'model_data'),
      evidence_cutoff: nullableString(value.model_data.evidence_cutoff),
      bundle_id: nullableString(value.model_data.bundle_id),
    },
    research_only: true,
    trade_ready: false,
  };
}

function assetUrl(path: string): string {
  const base = import.meta.env.BASE_URL.endsWith('/') ? import.meta.env.BASE_URL : `${import.meta.env.BASE_URL}/`;
  return `${base}${path}`;
}

async function deploymentState(health: SystemHealthSnapshot): Promise<SystemHealthState | 'unknown'> {
  if (!health.deployment.expected_commit_sha) return 'not_applicable';
  try {
    const response = await fetch(assetUrl('deployment.json'), { cache: 'no-cache' });
    if (!response.ok) return 'unknown';
    const receipt = await response.json() as unknown;
    if (!isObject(receipt) || typeof receipt.commit_sha !== 'string') return 'inconsistent';
    return receipt.commit_sha === health.deployment.expected_commit_sha ? 'current' : 'inconsistent';
  } catch {
    return 'unknown';
  }
}

export async function fetchSystemHealth(): Promise<LiveSystemHealth> {
  try {
    const response = await fetch(assetUrl('data/strategy-operations/system-health.json'), { cache: 'no-cache' });
    if (!response.ok) {
      return { health: null, status: 'unknown', deploymentStatus: 'unknown', message: `System health is unavailable (${response.status}).` };
    }
    const health = parseSystemHealth(await response.json() as unknown);
    const deploymentStatus = await deploymentState(health);
    const status = health.state;
    const delayed = health.markets.filter((row) => row.state === 'delayed').map((row) => row.market.toUpperCase());
    const message = status === 'current'
      ? 'Provider, model-data, factor, formal, signal and delivery stages are current.'
      : status === 'delayed'
        ? `Pipeline is internally consistent but delayed${delayed.length ? ` in ${delayed.join(' / ')}` : ''}.`
        : status === 'blocked'
          ? 'At least one governed pipeline stage is blocked.'
          : status === 'inconsistent'
            ? 'Governed pipeline watermarks disagree; publication should fail closed.'
            : 'No runtime health evaluation applies to this build.';
    return { health, status, deploymentStatus, message };
  } catch (error) {
    return { health: null, status: 'unknown', deploymentStatus: 'unknown', message: error instanceof Error ? error.message : 'System health request failed.' };
  }
}
