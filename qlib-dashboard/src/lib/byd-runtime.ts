const REPOSITORY = 'liuh886/alpha_engine';
const API_ROOT = `https://api.github.com/repos/${REPOSITORY}`;
const SIGNAL_MARKER = 'signal-fingerprint';

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
  schema_version: string;
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
  transition_type: string;
  transition_label: string;
  target_state: number;
  target_state_label: string;
  base_target: number;
  expansion_active: boolean;
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
    momentum_accel_20_60: number;
    open_return_autocorr_20: number;
    distance_from_low_20: number;
  };
  data_identity?: {
    data_version?: string;
    shadow_sha256?: string;
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

function isSignalRecord(value: BydSignalRecord | null): value is BydSignalRecord {
  return Boolean(
    value
    && value.schema_version
    && value.experiment_id
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

    // Try to parse the full signal JSON embedded in the body
    // The signal data is in a JSON code block or inline
    const jsonMatch = issue.body?.match(/```json\n([\s\S]*?)\n```/);
    if (!jsonMatch) continue;

    try {
      const record: unknown = JSON.parse(jsonMatch[1]);
      if (isSignalRecord(record as BydSignalRecord)) {
        events.push({ issue, record: record as BydSignalRecord });
      }
    } catch {
      continue;
    }
  }

  events.sort((left, right) =>
    right.record.signal_date.localeCompare(left.record.signal_date)
  );

  return {
    latestSignal: events[0] ?? null,
  };
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url, {
    headers: {
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
  });

  if (!response.ok) {
    const rateRemaining = response.headers.get('x-ratelimit-remaining');
    const suffix = rateRemaining === '0' ? ' Public API rate limit exhausted.' : '';
    throw new Error(`GitHub BYD request failed (${response.status}).${suffix}`);
  }

  return response.json() as Promise<T>;
}

export async function fetchBydRuntimeSnapshot(): Promise<BydRuntimeIndex> {
  const issues = await fetchJson<GitHubIssueRecord[]>(
    `${API_ROOT}/issues?state=all&per_page=100&sort=updated&direction=desc`,
  );
  return buildRuntimeIndex(issues);
}
