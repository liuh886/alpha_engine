const REPOSITORY = 'liuh886/alpha_engine';
const API_ROOT = `https://api.github.com/repos/${REPOSITORY}`;
const EVENT_MARKER = 'prospective-evidence-record';
const UPDATE_MARKER = 'prospective-evidence-update';
const MONTH_MARKER = 'prospective-evidence-month';

export type V42Asset = 'QQQI' | 'QQQ' | 'TQQQ';
export type V42Weights = Record<V42Asset, number>;

export interface GitHubIssueRecord {
  number: number;
  title: string;
  body: string | null;
  state: 'open' | 'closed';
  html_url: string;
  updated_at: string;
  pull_request?: unknown;
}

interface GitHubCommentRecord {
  body: string | null;
  html_url: string;
  updated_at: string;
}

export interface V42EventRecord {
  schema_version: string;
  event_id: string;
  event_type: 'state_change' | 'recovery_precursor';
  research_only: true;
  trade_ready: false;
  actionable: boolean;
  status: string;
  signal_date: string;
  latest_data_date_at_creation: string;
  data_freshness_ok: boolean;
  execution_time: string;
  fingerprint: string;
  transition_type: string;
  decision_reason: string;
  current_state: number;
  target_state: number;
  current_weights: V42Weights;
  target_weights: V42Weights;
  turnover_units: number;
  estimated_transaction_cost: number;
  signal_close_features: Record<string, unknown>;
  recovery_precursor_boolean: boolean;
  data_identity?: {
    mode?: string | null;
    bundle_id?: string | null;
    selected_providers?: Record<string, string> | null;
  };
  delivery?: Record<string, string>;
  outcome_horizons_sessions: number[];
}

export interface V42HorizonOutcome {
  qqq_return?: number | null;
  tqqq_return?: number | null;
  raw_50_vs_25_component?: number | null;
  directional_leverage_component?: number | null;
  tracking_compounding_component?: number | null;
  qqq_mfe?: number | null;
  qqq_mae?: number | null;
  qqq_realized_volatility_annualized?: number | null;
  qqq_sign_reversals?: number | null;
  qqq_intraday_log_return?: number | null;
  qqq_overnight_log_return?: number | null;
  [key: string]: unknown;
}

export interface V42ObservationRecord {
  schema_version: string;
  event_id: string;
  as_of_data_date: string;
  status: string;
  previous_status?: string | null;
  status_changed?: boolean;
  available_sessions: number;
  completed_horizons: number[];
  new_horizons: number[];
  execution?: {
    execution_date?: string | null;
    theoretical_next_open_prices?: Partial<Record<V42Asset, number | null>>;
    qqq_opening_gap?: number | null;
  } | null;
  outcomes: Record<string, V42HorizonOutcome>;
  time_to_formal_state_2_sessions?: number | null;
  time_to_state_0_sessions?: number | null;
}

export interface V42MonthlySummary {
  schema_version: string;
  month: string;
  research_only: true;
  trade_ready: false;
  event_count: number;
  state_change_event_count: number;
  recovery_precursor_event_count: number;
  unresolved_40_session_count: number;
  completed_horizon_counts: Record<string, number>;
  model_change_authorized: false;
  interpretation?: string;
}

export interface V42RuntimeEvent {
  issue: GitHubIssueRecord;
  record: V42EventRecord;
}

export interface V42RuntimeIndex {
  latestStateChange: V42RuntimeEvent | null;
  latestPrecursor: V42RuntimeEvent | null;
  latestMonthlySummary: {
    issue: GitHubIssueRecord;
    summary: V42MonthlySummary;
  } | null;
}

export interface V42RuntimeSnapshot extends V42RuntimeIndex {
  observation: V42ObservationRecord | null;
  fetchedAt: string;
  source: 'public_github_issue_ledger';
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function decodeBase64Url(value: string): string {
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/');
  const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=');
  const binary = atob(padded);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

export function decodeMachineMarker<T extends object>(
  text: string | null | undefined,
  prefix: string,
): T | null {
  if (!text) return null;
  const escaped = prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = text.match(new RegExp(`<!--\\s*${escaped}:([A-Za-z0-9_-]+)\\s*-->`));
  if (!match) return null;

  try {
    const parsed: unknown = JSON.parse(decodeBase64Url(match[1]));
    return isObject(parsed) ? parsed as T : null;
  } catch {
    return null;
  }
}

function isEventRecord(value: V42EventRecord | null): value is V42EventRecord {
  return Boolean(
    value
    && value.schema_version
    && value.event_id
    && (value.event_type === 'state_change' || value.event_type === 'recovery_precursor')
    && value.research_only === true
    && value.trade_ready === false
    && typeof value.signal_date === 'string'
    && isObject(value.current_weights)
    && isObject(value.target_weights),
  );
}

function isMonthlySummary(value: V42MonthlySummary | null): value is V42MonthlySummary {
  return Boolean(
    value
    && value.research_only === true
    && value.trade_ready === false
    && typeof value.month === 'string',
  );
}

function eventSortKey(event: V42RuntimeEvent): string {
  return `${event.record.signal_date}:${String(event.issue.number).padStart(10, '0')}`;
}

export function buildRuntimeIndex(issues: GitHubIssueRecord[]): V42RuntimeIndex {
  const events: V42RuntimeEvent[] = [];
  const monthlySummaries: Array<{ issue: GitHubIssueRecord; summary: V42MonthlySummary }> = [];

  for (const issue of issues) {
    if (issue.pull_request) continue;

    const record = decodeMachineMarker<V42EventRecord>(issue.body, EVENT_MARKER);
    if (isEventRecord(record)) events.push({ issue, record });

    const summary = decodeMachineMarker<V42MonthlySummary>(issue.body, MONTH_MARKER);
    if (isMonthlySummary(summary)) monthlySummaries.push({ issue, summary });
  }

  const latest = (eventType: V42EventRecord['event_type']) => events
    .filter((event) => event.record.event_type === eventType)
    .sort((left, right) => eventSortKey(right).localeCompare(eventSortKey(left)))[0] ?? null;

  monthlySummaries.sort((left, right) => {
    const monthOrder = right.summary.month.localeCompare(left.summary.month);
    return monthOrder || right.issue.number - left.issue.number;
  });

  return {
    latestStateChange: latest('state_change'),
    latestPrecursor: latest('recovery_precursor'),
    latestMonthlySummary: monthlySummaries[0] ?? null,
  };
}

function latestObservation(
  comments: GitHubCommentRecord[],
  eventId: string,
): V42ObservationRecord | null {
  const observations = comments
    .map((comment) => decodeMachineMarker<V42ObservationRecord>(comment.body, UPDATE_MARKER))
    .filter((record): record is V42ObservationRecord => Boolean(
      record
      && record.event_id === eventId
      && typeof record.as_of_data_date === 'string',
    ));

  observations.sort((left, right) => right.as_of_data_date.localeCompare(left.as_of_data_date));
  return observations[0] ?? null;
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
    const suffix = rateRemaining === '0' ? ' The public GitHub API rate limit is exhausted.' : '';
    throw new Error(`GitHub ledger request failed (${response.status}).${suffix}`);
  }

  return response.json() as Promise<T>;
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
      const rateRemaining = response.headers.get('x-ratelimit-remaining');
      if (rateRemaining === '0') {
        console.warn(`GitHub API rate limit exhausted after ${results.length} issues`);
        break;
      }
      throw new Error(`GitHub ledger pagination failed (${response.status})`);
    }

    const page = await response.json() as T[];
    results.push(...page);

    // Parse Link header for next page
    const link = response.headers.get('link');
    url = null;
    if (link) {
      const nextMatch = link.match(/<([^>]+)>;\s*rel="next"/);
      if (nextMatch) url = nextMatch[1];
    }
  }

  return results;
}

async function fetchIssueLedger(): Promise<GitHubIssueRecord[]> {
  const labelled = await fetchAllPages<GitHubIssueRecord>(
    `${API_ROOT}/issues?state=all&labels=prospective-evidence&sort=updated&direction=desc`,
  );
  if (buildRuntimeIndex(labelled).latestStateChange) return labelled;

  return fetchAllPages<GitHubIssueRecord>(
    `${API_ROOT}/issues?state=all&sort=updated&direction=desc`,
  );
}

export async function fetchV42RuntimeSnapshot(): Promise<V42RuntimeSnapshot> {
  const issues = await fetchIssueLedger();
  const index = buildRuntimeIndex(issues);
  const latestEvent = index.latestStateChange;
  if (!latestEvent) {
    throw new Error('No valid v4.2 state-change record exists in the public GitHub ledger.');
  }

  const comments = await fetchJson<GitHubCommentRecord[]>(
    `${API_ROOT}/issues/${latestEvent.issue.number}/comments?per_page=100`,
  );

  return {
    ...index,
    observation: latestObservation(comments, latestEvent.record.event_id),
    fetchedAt: new Date().toISOString(),
    source: 'public_github_issue_ledger',
  };
}
