const REPOSITORY = 'liuh886/alpha_engine';
const API_ROOT = `https://api.github.com/repos/${REPOSITORY}`;
const SIGNAL_MARKER = 'qqq-v4-3-signal';

export type QqqV43Asset = 'QQQI' | 'QQQ' | 'TQQQ' | 'SGOV';
export type QqqV43Weights = Record<QqqV43Asset, number>;

export interface GitHubIssueRecord {
  number: number;
  title: string;
  body: string | null;
  state: 'open' | 'closed';
  html_url: string;
  updated_at: string;
  pull_request?: unknown;
}

export interface QqqV43SignalRecord {
  schema_version: '1.0.0';
  model_id: 'qqqi_qqq_tqqq_v4_3';
  research_only: true;
  trade_ready: false;
  signal_date: string;
  latest_data_date: string;
  data_freshness_ok: boolean;
  execution_time: string;
  fingerprint: string;
  current_formal_state: number;
  target_formal_state: number;
  current_overlay: string;
  target_overlay: string;
  current_weights: QqqV43Weights;
  target_weights: QqqV43Weights;
  turnover_units: number;
  estimated_transaction_cost: number;
  panic_repair_active: boolean;
  strong_defense: boolean;
  ma200_falling: boolean;
  fast_price_vol_repair: boolean;
  rsi_14: number;
  fear_greed_score: number | null;
  context: {
    qqq_close?: number | null;
    ma20?: number | null;
    ma50?: number | null;
    ma200?: number | null;
    vix_close?: number | null;
    vxn_close?: number | null;
    vix_regime?: string;
    vxn_regime?: string;
    [key: string]: unknown;
  };
  data_context?: Record<string, unknown>;
}

export interface QqqV43RuntimeSignal {
  issue: GitHubIssueRecord;
  record: QqqV43SignalRecord;
}

export interface QqqV43RuntimeSnapshot {
  latestSignal: QqqV43RuntimeSignal;
  fetchedAt: string;
  source: 'public_github_issue_signal';
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

export function decodeV43SignalMarker(text: string | null | undefined): QqqV43SignalRecord | null {
  if (!text) return null;
  const match = text.match(/<!--\s*qqq-v4-3-signal:([A-Za-z0-9_-]+)\s*-->/);
  if (!match) return null;
  try {
    const parsed: unknown = JSON.parse(decodeBase64Url(match[1]));
    if (!isObject(parsed)) return null;
    const record = parsed as Partial<QqqV43SignalRecord>;
    if (
      record.schema_version !== '1.0.0'
      || record.model_id !== 'qqqi_qqq_tqqq_v4_3'
      || record.research_only !== true
      || record.trade_ready !== false
      || typeof record.signal_date !== 'string'
      || typeof record.latest_data_date !== 'string'
      || !isObject(record.current_weights)
      || !isObject(record.target_weights)
    ) return null;
    return record as QqqV43SignalRecord;
  } catch {
    return null;
  }
}

function signalSortKey(signal: QqqV43RuntimeSignal): string {
  return `${signal.record.signal_date}:${String(signal.issue.number).padStart(10, '0')}`;
}

export function latestV43Signal(issues: GitHubIssueRecord[]): QqqV43RuntimeSignal | null {
  const signals = issues
    .filter((issue) => !issue.pull_request)
    .map((issue) => ({ issue, record: decodeV43SignalMarker(issue.body) }))
    .filter((value): value is QqqV43RuntimeSignal => Boolean(value.record));
  signals.sort((left, right) => signalSortKey(right).localeCompare(signalSortKey(left)));
  return signals[0] ?? null;
}

async function fetchAllIssues(): Promise<GitHubIssueRecord[]> {
  const results: GitHubIssueRecord[] = [];
  let url: string | null = `${API_ROOT}/issues?state=all&sort=updated&direction=desc&per_page=100`;
  while (url) {
    const response = await fetch(url, {
      headers: {
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
      },
    });
    if (!response.ok) {
      const remaining = response.headers.get('x-ratelimit-remaining');
      if (remaining === '0' && results.length > 0) break;
      throw new Error(`GitHub v4.3 signal request failed (${response.status}).`);
    }
    const page = await response.json() as GitHubIssueRecord[];
    results.push(...page);
    const link = response.headers.get('link');
    const next = link?.match(/<([^>]+)>;\s*rel="next"/);
    url = next?.[1] ?? null;
  }
  return results;
}

export async function fetchQqqV43RuntimeSnapshot(): Promise<QqqV43RuntimeSnapshot> {
  const signal = latestV43Signal(await fetchAllIssues());
  if (!signal) throw new Error('No valid QQQ v4.3 signal record exists in the public GitHub ledger.');
  return {
    latestSignal: signal,
    fetchedAt: new Date().toISOString(),
    source: 'public_github_issue_signal',
  };
}
