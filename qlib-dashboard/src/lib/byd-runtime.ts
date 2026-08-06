const REPOSITORY = 'liuh886/alpha_engine';
const API_ROOT = `https://api.github.com/repos/${REPOSITORY}`;
const FORMAL_BYD_MODEL_ID = 'byd_v1_2_convex_momentum_budget_v1' as const;

export type BydAsset = 'BYD' | '515180' | 'CASH';
export type BydWeights = Record<BydAsset, number>;

export interface GitHubIssueRecord {
  number: number;
  title: string;
  body: string | null;
  state: 'open' | 'closed';
  html_url: string;
  updated_at: string;
  pull_request?: unknown;
}

export interface BydSignalRecord {
  schema_version: 'byd_v1_2_signal_v2';
  model_id: typeof FORMAL_BYD_MODEL_ID;
  experiment_id: string;
  research_only: true;
  trade_ready: false;
  should_alert: boolean;
  fingerprint: string;
  signal_date: string;
  latest_data_date: string;
  data_freshness_ok: boolean;
  open_research_eligible: boolean;
  execution_time: string;
  transition_type: 'initialize' | 'rebalance' | 'no_change';
  transition_label: string;
  previous_mode: string | null;
  target_mode: 'defense' | 'offense' | 'convex_expansion';
  target_mode_label: string;
  base_target: number;
  expansion_active: boolean;
  momentum_scale: number;
  financed_increment: number;
  current_weights: BydWeights;
  target_weights: BydWeights;
  orders: Array<{
    asset: string;
    side: string;
    weight_change: number;
    from_weight: number;
    to_weight: number;
  }>;
  turnover_units: number;
  estimated_transaction_cost: number;
  price_context: {
    byd_close: number;
    byd_open: number;
  };
  factor_context: {
    market_state: string;
    vol_state: string;
    drawdown_252: number;
    mom_20: number;
    mom_60: number;
    momentum_scale: number;
    financed_increment: number;
  };
  data_provenance?: {
    shadow_manifest_sha256?: string;
    paired_manifest_sha256?: string;
    expansion_manifest_sha256?: string;
  };
}

export interface BydRuntimeEvent {
  issue: GitHubIssueRecord;
  record: BydSignalRecord;
}

export interface BydRuntimeIndex {
  latestSignal: BydRuntimeEvent | null;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isSignalRecord(value: unknown): value is BydSignalRecord {
  if (!isObject(value)) return false;
  return Boolean(
    value.schema_version === 'byd_v1_2_signal_v2'
    && value.model_id === FORMAL_BYD_MODEL_ID
    && value.research_only === true
    && value.trade_ready === false
    && typeof value.signal_date === 'string'
    && isObject(value.target_weights),
  );
}

export function extractFingerprint(body: string | null): string | null {
  if (!body) return null;
  const match = body.match(/<!--\s*signal-fingerprint:([a-f0-9]{20})\s*-->/);
  return match ? match[1] : null;
}

export function buildRuntimeIndex(issues: GitHubIssueRecord[]): BydRuntimeIndex {
  const events: BydRuntimeEvent[] = [];
  for (const issue of issues) {
    if (issue.pull_request) continue;
    const fingerprint = extractFingerprint(issue.body);
    if (!fingerprint) continue;
    const jsonMatch = issue.body?.match(/```json\n([\s\S]*?)\n```/);
    if (!jsonMatch) continue;
    try {
      const record: unknown = JSON.parse(jsonMatch[1]);
      if (isSignalRecord(record) && record.fingerprint === fingerprint) {
        events.push({ issue, record });
      }
    } catch {
      continue;
    }
  }
  events.sort((left, right) =>
    right.record.signal_date.localeCompare(left.record.signal_date)
  );
  return { latestSignal: events[0] ?? null };
}

async function fetchAllPages<T>(baseUrl: string): Promise<T[]> {
  const results: T[] = [];
  let url: string | null = `${baseUrl}&per_page=100`;
  while (url) {
    const response = await fetch(url, {
      headers: {
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
      },
    });
    if (!response.ok) {
      throw new Error(`GitHub BYD signal ledger failed (${response.status})`);
    }
    const page = await response.json() as T[];
    results.push(...page);
    const link = response.headers.get('link');
    const nextMatch = link?.match(/<([^>]+)>;\s*rel="next"/);
    url = nextMatch?.[1] ?? null;
  }
  return results;
}

export async function fetchBydRuntimeSnapshot(): Promise<BydRuntimeIndex> {
  const issues = await fetchAllPages<GitHubIssueRecord>(
    `${API_ROOT}/issues?state=all&sort=updated&direction=desc`,
  );
  return buildRuntimeIndex(issues);
}
