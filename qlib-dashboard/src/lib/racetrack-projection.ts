import { sha256Text } from './model-run-bundle-v2';

export type RaceMarket = 'us' | 'cn';
export type RaceWindow = 1 | 3 | 6 | 12;
export interface ArtifactRef { path: string; sha256: string; size_bytes: number }
export interface RaceManifest {
  schema_version: '1.0' | '2.0'; pipeline_version: '1.1.0' | '2.0.0'; release_id: string;
  market: RaceMarket; pool_id: string; benchmark_symbol: string;
  as_of_session: string; as_of_cutoff: string; season_id: string;
  generated_at_utc: string; data_qualification: string; runner_count: number;
  engine_config: { friction_rate: number };
  artifacts: Record<string, ArtifactRef>; runner_details?: Record<string, string>;
  local_evidence?: Record<string, ArtifactRef & { event_count: number; tip_hash: string }>;
}
export interface MonthlyRank {
  month: string; rank: number; total_runners: number; points_earned: number;
  monthly_net_return: number;
}
export interface RaceEntry {
  runner_id: string; runner_version: string; thesis_summary: string;
  current_rank: number; season_points: number; cumulative_points: number;
  return_1m: number | null; return_3m: number | null; return_6m: number | null; return_1y: number | null;
  excess_vs_qqq: number | null; excess_vs_pool: number | null;
  max_drawdown: number; sharpe_ratio: number; persistence_ratio: number;
  monthly_ranks: MonthlyRank[];
}
export interface RaceScoreboard {
  schema_version: '1.0' | '2.0'; pool_id: string; benchmark_symbol: string;
  as_of_session: string; season_id: string;
  status: 'operational_race' | 'diagnostic_baseline_only';
  period_policy: 'calendar_month_buckets_including_partial' | 'trailing_calendar_duration_previous_session_anchor_v1';
  dates: string[]; benchmarks: { pool_index: (number | null)[]; macro: (number | null)[] };
  entries: RaceEntry[]; top_runners_nav: Record<string, (number | null)[]>;
  first_season?: FirstSeason;
}
export interface FirstSeason {
  contract_version: 'first_season_v2'; points_rule: 'monthly_net_return_percentage_points_v2';
  rank_policy: 'window_net_return_competition_rank_v1'; season_state: 'provisional'; pool_runner_id: string;
  roles: Record<string, 'internal_benchmark_racer' | 'strategy_racer'>;
  windows: Record<string, { anchor_session: string | null; end_session: string; ranks: Record<string, number | null>; top_runner_ids: string[] }>;
  month_windows: { month: string; first_session: string; last_session: string; expected_sessions: number; observed_sessions: number; complete_window: boolean; settlement_status: 'not_reviewed' }[];
  source_gaps: { symbol: string; missing_sessions: number; first_missing_session: string; last_missing_session: string; qualification: string }[];
}
export interface RunnerDetail {
  schema_version: '1.0' | '2.0'; runner_id: string; runner_version: string;
  pool_id: string; market: RaceMarket; as_of_session: string;
  thesis: string; selection_logic: string; rebalance_logic: string;
  model_weights: { symbol: string; weight: number }[]; cash_weight: number;
  monthly_ranks: MonthlyRank[]; limitations: string[];
  runner_role?: 'internal_benchmark_racer' | 'strategy_racer';
}
export interface RaceProjection { manifest: RaceManifest; scoreboard: RaceScoreboard }
export interface DisplaySeries { id: string; label: string; runnerId?: string; values: (number | null)[] }
export interface RaceDisplay { dates: string[]; series: DisplaySeries[]; requestedMonths: number; availableMonths: number; shortHistory?: boolean }

const HASH = /^[a-f0-9]{64}$/;
const POOLS = { us: 'us_selected_equities_v2', cn: 'cn_selected_equities_v3' };
const forbidden = new Set(['shares', 'qty', 'lots', 'total_cost', 'cost_basis', 'cash_balance', 'capital',
  'broker', 'brokerage_account', 'account', 'account_id', 'executed_price', 'execution_fee',
  'commission_paid', 'realized_pnl', 'unrealized_pnl', 'pnl', 'position_size']);
function requireValue(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}
function object(value: unknown): Record<string, any> {
  requireValue(value && typeof value === 'object' && !Array.isArray(value), 'Invalid projection object');
  return value as Record<string, any>;
}
function clean(value: unknown): void {
  if (Array.isArray(value)) value.forEach(clean);
  else if (value && typeof value === 'object') for (const [key, item] of Object.entries(value)) {
    requireValue(!forbidden.has(key.toLowerCase()), 'Personal account fields are not research evidence');
    clean(item);
  }
}
function date(value: unknown): value is string {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)
    && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
}
function text(value: unknown): value is string { return typeof value === 'string' && value.length > 0; }
function metric(value: unknown): boolean { return value === null || typeof value === 'number' && Number.isFinite(value); }
function ranks(value: unknown, v2 = false): asserts value is MonthlyRank[] {
  requireValue(Array.isArray(value) && value.every(item => {
    const row = object(item);
    return /^\d{4}-(0[1-9]|1[0-2])$/.test(row.month) && Number.isInteger(row.rank) && row.rank > 0
      && Number.isInteger(row.total_runners) && row.total_runners >= row.rank
      && (v2 ? Number.isFinite(row.points_earned) : Number.isInteger(row.points_earned) && row.points_earned >= 0) && Number.isFinite(row.monthly_net_return);
  }), 'Invalid monthly rank evidence');
}

export function parseRaceManifest(value: unknown, market: RaceMarket): RaceManifest {
  const m = object(value); clean(m);
  requireValue(m.schema_version === '1.0' && m.pipeline_version === '1.1.0'
    || m.schema_version === '2.0' && m.pipeline_version === '2.0.0', 'Unsupported projection version');
  requireValue(m.market === market && m.pool_id === POOLS[market], 'Projection market/pool mismatch');
  requireValue(m.research_only === true && m.trade_ready === false, 'Invalid research boundary');
  requireValue(HASH.test(m.release_id) && date(m.as_of_session) && date(m.as_of_cutoff)
    && m.as_of_session <= m.as_of_cutoff && text(m.season_id)
    && text(m.generated_at_utc) && Number.isFinite(Date.parse(m.generated_at_utc))
    && text(m.data_qualification) && Number.isInteger(m.runner_count) && m.runner_count >= 0,
  'Missing projection provenance');
  requireValue(m.benchmark_symbol === (market === 'us' ? 'QQQ' : '000300'), 'Benchmark identity mismatch');
  requireValue(m.engine_config && Number.isFinite(m.engine_config.friction_rate)
    && m.engine_config.friction_rate >= 0 && m.engine_config.friction_rate < 1, 'Invalid friction setting');
  const artifacts = object(m.artifacts);
  requireValue(artifacts.scoreboard_latest, 'Scoreboard artifact is missing');
  for (const raw of Object.values(artifacts)) {
    const a = object(raw);
    requireValue(typeof a.path === 'string' && a.path.startsWith(`versions/${m.release_id}/`)
      && /^versions\/[a-f0-9]{64}\/(scoreboard_latest\.json|archive\/scoreboard_\d{4}-\d{2}-\d{2}\.json|runners\/[a-f0-9]{64}\.json)$/.test(a.path)
      && HASH.test(a.sha256) && Number.isSafeInteger(a.size_bytes) && a.size_bytes >= 0
      && a.size_bytes <= 8 * 1024 * 1024, 'Unsafe projection artifact reference');
  }
  if (m.runner_details !== undefined) for (const key of Object.values(object(m.runner_details))) {
    requireValue(typeof key === 'string' && Object.prototype.hasOwnProperty.call(artifacts, key), 'Missing runner detail reference');
  }
  if (m.schema_version === '2.0') {
    requireValue(m.market === 'us' && Object.keys(object(m.local_evidence)).length === m.runner_count, 'Missing first-season local evidence');
    for (const raw of Object.values(m.local_evidence)) {
      const ref = object(raw);
      requireValue(typeof ref.path === 'string' && ref.path.startsWith(`versions/${m.release_id}/evidence/`)
        && /^versions\/[a-f0-9]{64}\/evidence\/[a-f0-9]{64}\.jsonl$/.test(ref.path)
        && HASH.test(ref.sha256) && HASH.test(ref.tip_hash) && Number.isSafeInteger(ref.size_bytes)
        && ref.size_bytes > 0 && ref.size_bytes <= 8 * 1024 * 1024
        && Number.isSafeInteger(ref.event_count) && ref.event_count > 0, 'Invalid retained Q evidence');
    }
  }
  return m as unknown as RaceManifest;
}

export function parseRaceScoreboard(value: unknown, manifest: RaceManifest): RaceScoreboard {
  const s = object(value); clean(s);
  const v2 = manifest.schema_version === '2.0';
  requireValue(s.schema_version === manifest.schema_version && s.pool_id === manifest.pool_id
    && s.benchmark_symbol === manifest.benchmark_symbol && s.as_of_session === manifest.as_of_session
    && s.season_id === manifest.season_id, 'Scoreboard identity mismatch');
  requireValue(s.period_policy === (v2 ? 'trailing_calendar_duration_previous_session_anchor_v1' : 'calendar_month_buckets_including_partial'), 'Unknown period policy');
  requireValue(Array.isArray(s.dates) && s.dates.length > 0 && s.dates.length <= 25000
    && s.dates.every((d: unknown, i: number) => date(d) && (i === 0 || s.dates[i - 1] < d))
    && s.dates[s.dates.length - 1] === manifest.as_of_session, 'Invalid or unordered trading dates');
  const validSeries = (v: unknown) => Array.isArray(v) && v.length === s.dates.length
    && v.every(n => n === null || typeof n === 'number' && Number.isFinite(n) && n >= 0);
  requireValue(s.benchmarks && validSeries(s.benchmarks.pool_index) && validSeries(s.benchmarks.macro), 'Incomplete benchmark series');
  requireValue(Array.isArray(s.entries) && s.entries.length === manifest.runner_count && s.entries.length <= 5000, 'Runner count mismatch');
  const ids = new Set<string>();
  for (const [index, entry] of s.entries.entries()) {
    const e = object(entry);
    requireValue(text(e.runner_id) && !ids.has(e.runner_id) && text(e.runner_version)
      && typeof e.thesis_summary === 'string'
      && e.current_rank === (v2 && index && s.entries[index - 1].season_points === e.season_points ? s.entries[index - 1].current_rank : index + 1)
      && (v2 ? Number.isFinite(e.season_points) && Number.isFinite(e.cumulative_points)
        && (!index || s.entries[index - 1].season_points >= e.season_points)
        : Number.isInteger(e.season_points) && e.season_points >= 0 && Number.isInteger(e.cumulative_points) && e.cumulative_points >= 0), 'Invalid published ranking');
    ids.add(e.runner_id); ranks(e.monthly_ranks, v2);
    requireValue(['return_1m', 'return_3m', 'return_6m', 'return_1y', 'excess_vs_qqq', 'excess_vs_pool'].every(key => metric(e[key]))
      && ['max_drawdown', 'sharpe_ratio', 'persistence_ratio'].every(key => Number.isFinite(e[key])), 'Non-finite research metric');
  }
  const nav = object(s.top_runners_nav);
  requireValue(Object.keys(nav).every(id => ids.has(id) && validSeries(nav[id])), 'Unregistered or invalid NAV series');
  requireValue(s.entries.slice(0, 10).every((e: RaceEntry) => Object.prototype.hasOwnProperty.call(nav, e.runner_id) && validSeries(nav[e.runner_id])), 'Missing Top 10 NAV series');
  requireValue(s.status === (s.entries.length ? 'operational_race' : 'diagnostic_baseline_only'), 'Incorrect race/baseline status');
  if (v2) {
    validateFirstSeason(s, ids);
    requireValue(Object.keys(manifest.local_evidence ?? {}).every(id => ids.has(id)), 'Q evidence runner identity mismatch');
  }
  else requireValue(s.first_season === undefined, 'Version 1 cannot carry version 2 rules');
  return s as unknown as RaceScoreboard;
}

function validateFirstSeason(s: Record<string, any>, ids: Set<string>) {
  const f = object(s.first_season);
  requireValue(f.contract_version === 'first_season_v2' && f.points_rule === 'monthly_net_return_percentage_points_v2'
    && f.rank_policy === 'window_net_return_competition_rank_v1' && f.season_state === 'provisional', 'Unsupported first-season rules or settlement claim');
  const roles = object(f.roles);
  requireValue(ids.has(f.pool_runner_id) && Object.keys(roles).length === ids.size
    && [...ids].every(id => roles[id] === (id === f.pool_runner_id ? 'internal_benchmark_racer' : 'strategy_racer')), 'Invalid runner role identity');
  const windows = object(f.windows);
  requireValue(Object.keys(windows).length === 4, 'Missing first-season windows');
  for (const months of [1, 3, 6, 12] as RaceWindow[]) {
    const w = object(windows[String(months)]);
    const rankMap = object(w.ranks);
    requireValue(w.end_session === s.as_of_session && (w.anchor_session === null || date(w.anchor_session) && s.dates.includes(w.anchor_session))
      && Object.keys(rankMap).length === ids.size && Object.keys(rankMap).every(id => ids.has(id)), 'Window evidence identity mismatch');
    const eligible = s.entries.filter((entry: RaceEntry) => {
      const rank = rankMap[entry.runner_id];
      requireValue(rank === null || Number.isInteger(rank) && rank > 0 && rank <= ids.size, 'Invalid window rank');
      requireValue((windowReturn(entry, months) === null) === (rank === null)
        && (w.anchor_session !== null || rank === null), 'Short history cannot be ranked');
      return rank !== null;
    });
    requireValue(Array.isArray(w.top_runner_ids) && w.top_runner_ids.length === Math.min(10, eligible.length)
      && new Set(w.top_runner_ids).size === w.top_runner_ids.length
      && w.top_runner_ids.every((id: string, index: number) => ids.has(id) && rankMap[id] !== null
        && Object.prototype.hasOwnProperty.call(s.top_runners_nav, id)
        && (!index || rankMap[w.top_runner_ids[index - 1]] <= rankMap[id])), 'Incomplete or unordered window Top 10');
  }
  const monthKeys = new Set(s.dates.map((d: string) => d.slice(0, 7)));
  requireValue(Array.isArray(f.month_windows) && f.month_windows.length === monthKeys.size
    && new Set(f.month_windows.map((m: any) => m.month)).size === monthKeys.size
    && f.month_windows.every((m: any) => monthKeys.has(m.month) && date(m.first_session) && date(m.last_session)
      && m.first_session <= m.last_session && Number.isInteger(m.expected_sessions) && m.expected_sessions > 0
      && Number.isInteger(m.observed_sessions) && m.observed_sessions > 0 && m.observed_sessions <= m.expected_sessions
      && typeof m.complete_window === 'boolean' && (!m.complete_window || m.observed_sessions === m.expected_sessions)
      && m.settlement_status === 'not_reviewed'), 'Invalid month completion or settlement evidence');
  requireValue(Array.isArray(f.source_gaps) && f.source_gaps.every((gap: any) => text(gap.symbol)
    && Number.isInteger(gap.missing_sessions) && gap.missing_sessions > 0 && gap.missing_sessions <= s.dates.length
    && date(gap.first_missing_session) && date(gap.last_missing_session)
    && s.dates[0] <= gap.first_missing_session && gap.first_missing_session <= gap.last_missing_session && gap.last_missing_session <= s.as_of_session
    && ['no_observation_in_replay', 'unresolved_after_first_observation'].includes(gap.qualification)), 'Invalid source-gap qualification');
}

function parseDetail(value: unknown, p: RaceProjection, entry: RaceEntry): RunnerDetail {
  const d = object(value); clean(d);
  requireValue(d.schema_version === p.manifest.schema_version && d.runner_id === entry.runner_id
    && d.runner_version === entry.runner_version && d.pool_id === p.manifest.pool_id
    && d.market === p.manifest.market && d.as_of_session === p.manifest.as_of_session
    && d.research_only === true && d.trade_ready === false, 'Runner detail identity mismatch');
  requireValue(text(d.thesis) && typeof d.selection_logic === 'string' && typeof d.rebalance_logic === 'string'
    && Array.isArray(d.model_weights) && d.model_weights.every((w: any) => text(w.symbol)
      && Number.isFinite(w.weight) && w.weight >= 0 && w.weight <= 1)
    && Number.isFinite(d.cash_weight) && d.cash_weight >= 0 && d.cash_weight <= 1
    && Array.isArray(d.limitations) && d.limitations.every(text), 'Invalid runner detail evidence');
  ranks(d.monthly_ranks, p.manifest.schema_version === '2.0');
  if (p.scoreboard.first_season) requireValue(d.runner_role === p.scoreboard.first_season.roles[entry.runner_id], 'Runner role mismatch');
  return d as unknown as RunnerDetail;
}

export class ProjectionClient {
  private verified = new Map<string, unknown>();
  constructor(private request: typeof fetch = globalThis.fetch.bind(globalThis)) {}
  clear() { this.verified.clear(); }
  private async read(url: string, signal: AbortSignal): Promise<string> {
    const response = await this.request(url, { signal, cache: 'no-store', credentials: 'same-origin' });
    if (response.status === 404) throw new Error('No local projection. Publish it with the existing Racetrack CLI, then retry.');
    if (response.status === 403) throw new Error('This projection is available only to the local operator.');
    if (!response.ok) throw new Error('Projection read or integrity verification failed.');
    const length = Number(response.headers.get('content-length'));
    requireValue(!length || length <= 8 * 1024 * 1024, 'Projection exceeds the read limit');
    const raw = await response.text();
    requireValue(new TextEncoder().encode(raw).byteLength <= 8 * 1024 * 1024, 'Projection exceeds the read limit');
    return raw;
  }
  private async artifact(m: RaceManifest, key: string, signal: AbortSignal): Promise<unknown> {
    const ref = m.artifacts[key]; requireValue(ref, 'Artifact was not published');
    const identity = `${m.market}:${m.release_id}:${ref.path}:${ref.sha256}`;
    if (this.verified.has(identity)) return this.verified.get(identity);
    const raw = await this.read(`/__racetrack/${m.market}/${ref.path}`, signal);
    requireValue(new TextEncoder().encode(raw).byteLength === ref.size_bytes
      && await sha256Text(raw) === ref.sha256, 'Projection artifact hash/size mismatch');
    const value: unknown = JSON.parse(raw);
    if (!signal.aborted) this.verified.set(identity, value);
    return value;
  }
  async load(market: RaceMarket, signal: AbortSignal): Promise<RaceProjection> {
    const m = parseRaceManifest(JSON.parse(await this.read(`/__racetrack/${market}/manifest.json`, signal)), market);
    return { manifest: m, scoreboard: parseRaceScoreboard(await this.artifact(m, 'scoreboard_latest', signal), m) };
  }
  async runner(p: RaceProjection, entry: RaceEntry, signal: AbortSignal): Promise<RunnerDetail> {
    const key = p.manifest.runner_details?.[entry.runner_id];
    requireValue(key, 'Full runner detail was not published in this vintage. Regenerate with the current publisher.');
    return parseDetail(await this.artifact(p.manifest, key, signal), p, entry);
  }
}

// Display transforms only: preserve published rank/returns and retain null gaps.
export function displayWindow(s: RaceScoreboard, window: RaceWindow): RaceDisplay {
  const months = [...new Set(s.dates.map(d => d.slice(0, 7)))];
  const firstMonth = months[Math.max(0, months.length - window)];
  const phase = s.first_season;
  const anchor = phase?.windows[String(window)].anchor_session;
  const start = phase ? (anchor ? s.dates.indexOf(anchor) : 0) : s.dates.findIndex(d => d.slice(0, 7) >= firstMonth);
  const make = (id: string, label: string, raw: (number | null)[]): DisplaySeries => {
    const base = raw[start];
    return { id, label, values: raw.slice(start).map(v => v === null || base === null || base <= 0 ? null : v / base) };
  };
  const visible = phase ? phase.windows[String(window)].top_runner_ids : s.entries.slice(0, 10).map(e => e.runner_id);
  return { dates: s.dates.slice(start), requestedMonths: window, availableMonths: Math.min(months.length, window),
    shortHistory: phase ? !anchor : undefined, series: [
    { ...make('pool', phase ? 'US87 EW · internal benchmark, also racing' : 'Pool index', s.benchmarks.pool_index), runnerId: phase?.pool_runner_id },
    make('macro', phase ? 'QQQ · reference only, not racing' : s.benchmark_symbol === '000300' ? 'CSI 300' : s.benchmark_symbol, s.benchmarks.macro),
    ...visible.filter(id => id !== phase?.pool_runner_id).map(id => ({ ...make(`runner:${id}`, id, s.top_runners_nav[id]), runnerId: id })),
  ] };
}

export function contiguousSegments(dates: string[], values: (number | null)[]) {
  const segments: { time: string; value: number }[][] = [];
  let current: { time: string; value: number }[] = [];
  values.forEach((value, index) => {
    if (value === null) { if (current.length) segments.push(current); current = []; }
    else current.push({ time: dates[index], value });
  });
  if (current.length) segments.push(current);
  return segments;
}

export const windowReturn = (e: RaceEntry, window: RaceWindow) => ({ 1: e.return_1m, 3: e.return_3m, 6: e.return_6m, 12: e.return_1y })[window];

export function leaderboardForWindow(s: RaceScoreboard, window: RaceWindow) {
  if (!s.first_season) return s.entries.slice(0, 10).map(entry => ({ entry, rank: entry.current_rank }));
  const published = s.first_season.windows[String(window)];
  const byId = new Map(s.entries.map(entry => [entry.runner_id, entry]));
  const eligible = published.top_runner_ids.map(id => ({ entry: byId.get(id)!, rank: published.ranks[id] }));
  const short = s.entries.filter(entry => published.ranks[entry.runner_id] === null)
    .slice(0, 10 - eligible.length).map(entry => ({ entry, rank: null }));
  return [...eligible, ...short];
}
