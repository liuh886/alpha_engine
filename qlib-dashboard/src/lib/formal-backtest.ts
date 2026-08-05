import type { ModelData } from './data-parser';
import type { Position, ReportRow } from './types';

export type FormalBacktestCompletenessStatus = 'complete' | 'partial';

export interface FormalBacktestCatalogEntry {
  model_id: string;
  display_name: string;
  display_order: number;
  path: string;
  sha256: string;
  publication_status: 'accepted_formal_baseline';
}

export interface FormalBacktestCatalog {
  schema_version: '1.0.0';
  published_at: string;
  publication_policy: 'formal_named_baselines_only';
  excluded_record_classes: string[];
  records: FormalBacktestCatalogEntry[];
  research_only: true;
  trade_ready: false;
}

export interface FormalBacktestTrade {
  date: string;
  instrument: string;
  action: string;
  previous_weight?: number;
  target_weight?: number;
  weight_delta?: number;
  transaction_cost?: number;
  holding_end_date?: string;
  reason?: string;
  window?: string;
  [key: string]: unknown;
}

export interface FormalBacktestCompleteness {
  status: FormalBacktestCompletenessStatus;
  performance_trace?: string;
  holdings?: string;
  trades?: string;
  attribution?: string;
  missing: string[];
  [key: string]: unknown;
}

export interface FormalBacktestPackage {
  schema_version: '1.0.0';
  record_type: 'formal_model_backtest';
  backtest_id: string;
  model_id: string;
  display_name: string;
  market: string;
  benchmark: string;
  publication_status: 'accepted_formal_baseline';
  generated_at: string;
  evidence_cutoff: string;
  trace_frequency: string;
  date_range: { start: string; end: string };
  metrics: Record<string, number>;
  portfolio_contract: Record<string, unknown>;
  report: ReportRow[];
  positions: Position[];
  trades: FormalBacktestTrade[];
  attribution: Array<{ instrument?: string; name?: string; value?: number; [key: string]: unknown }>;
  window_summary: Array<Record<string, unknown>>;
  evidence: Record<string, unknown>;
  evidence_completeness: FormalBacktestCompleteness;
  interpretation_notes: string[];
  research_only: true;
  trade_ready: false;
  [key: string]: unknown;
}

const PUBLIC_DISPLAY_NAME_BY_MODEL_ID: Record<string, string> = {
  byd_dividend_sleeve_v1_0: 'BYD v1.1',
};

function publicDisplayName(formal: FormalBacktestPackage): string {
  return PUBLIC_DISPLAY_NAME_BY_MODEL_ID[formal.model_id] ?? formal.display_name;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== 'string' || value.trim().length === 0) throw new Error(`${label} is missing.`);
  return value;
}

function stringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map(String);
}

function numericRecord(value: unknown, label: string): Record<string, number> {
  if (!isRecord(value)) throw new Error(`${label} must be an object.`);
  const output: Record<string, number> = {};
  for (const [key, raw] of Object.entries(value)) {
    if (typeof raw !== 'number' || !Number.isFinite(raw)) throw new Error(`${label}.${key} must be finite.`);
    output[key] = raw;
  }
  return output;
}

export function parseFormalBacktestCatalog(value: unknown): FormalBacktestCatalog {
  if (!isRecord(value)) throw new Error('Formal backtest catalog is invalid.');
  if (value.schema_version !== '1.0.0') throw new Error('Unsupported formal backtest catalog schema.');
  if (value.publication_policy !== 'formal_named_baselines_only') throw new Error('Formal backtest publication policy is invalid.');
  if (value.research_only !== true || value.trade_ready !== false) throw new Error('Formal backtest catalog boundary is invalid.');
  if (!Array.isArray(value.records) || value.records.length === 0) throw new Error('Formal backtest catalog is empty.');

  const modelIds = new Set<string>();
  const records = value.records.map((raw, index): FormalBacktestCatalogEntry => {
    if (!isRecord(raw)) throw new Error(`Formal catalog entry ${index} is invalid.`);
    const modelId = requiredString(raw.model_id, `Formal catalog entry ${index} model_id`);
    if (modelIds.has(modelId)) throw new Error(`Duplicate formal model ID: ${modelId}`);
    modelIds.add(modelId);
    const path = requiredString(raw.path, `Formal catalog entry ${modelId} path`);
    if (path.includes('/') || path.includes('\\') || !path.endsWith('.json')) throw new Error(`Unsafe formal backtest path: ${path}`);
    const digest = requiredString(raw.sha256, `Formal catalog entry ${modelId} sha256`);
    if (!/^[a-f0-9]{64}$/.test(digest)) throw new Error(`Invalid formal backtest digest: ${modelId}`);
    if (raw.publication_status !== 'accepted_formal_baseline') throw new Error(`Non-formal record is not publishable: ${modelId}`);
    const displayOrder = Number(raw.display_order);
    if (!Number.isFinite(displayOrder)) throw new Error(`Formal catalog display_order is invalid: ${modelId}`);
    return {
      model_id: modelId,
      display_name: requiredString(raw.display_name, `Formal catalog entry ${modelId} display_name`),
      display_order: displayOrder,
      path,
      sha256: digest,
      publication_status: 'accepted_formal_baseline',
    };
  }).sort((a, b) => a.display_order - b.display_order || a.model_id.localeCompare(b.model_id));

  return {
    schema_version: '1.0.0',
    published_at: requiredString(value.published_at, 'Formal backtest catalog published_at'),
    publication_policy: 'formal_named_baselines_only',
    excluded_record_classes: stringArray(value.excluded_record_classes),
    records,
    research_only: true,
    trade_ready: false,
  };
}

export function parseFormalBacktestPackage(value: unknown, expectedModelId?: string): FormalBacktestPackage {
  if (!isRecord(value)) throw new Error('Formal backtest package is invalid.');
  if (value.schema_version !== '1.0.0' || value.record_type !== 'formal_model_backtest') throw new Error('Unsupported formal backtest package schema.');
  if (value.publication_status !== 'accepted_formal_baseline') throw new Error('Exploratory or unaccepted records are not publishable.');
  if (value.research_only !== true || value.trade_ready !== false) throw new Error('Formal backtest research boundary is invalid.');
  const modelId = requiredString(value.model_id, 'Formal backtest model_id');
  if (expectedModelId && modelId !== expectedModelId) throw new Error(`Formal backtest model mismatch: ${modelId} != ${expectedModelId}`);
  const dateRange = value.date_range;
  if (!isRecord(dateRange)) throw new Error(`Formal backtest date range is invalid: ${modelId}`);
  if (!Array.isArray(value.report) || value.report.length === 0) throw new Error(`Formal backtest performance trace is missing: ${modelId}`);
  if (!Array.isArray(value.positions) || !Array.isArray(value.trades) || !Array.isArray(value.attribution) || !Array.isArray(value.window_summary)) {
    throw new Error(`Formal backtest evidence arrays are incomplete: ${modelId}`);
  }
  if (!isRecord(value.evidence) || !isRecord(value.evidence_completeness)) throw new Error(`Formal backtest evidence identity is missing: ${modelId}`);
  const completenessStatus = String(value.evidence_completeness.status);
  if (completenessStatus !== 'complete' && completenessStatus !== 'partial') throw new Error(`Unsupported evidence completeness: ${modelId}`);

  const report = value.report.map((raw, index): ReportRow => {
    if (!isRecord(raw)) throw new Error(`Formal backtest report row is invalid: ${modelId}/${index}`);
    const account = Number(raw.account);
    if (!Number.isFinite(account) || account <= 0) throw new Error(`Formal backtest account value is invalid: ${modelId}/${index}`);
    return { ...raw, date: requiredString(raw.date, `Formal backtest report date ${modelId}/${index}`), account } as ReportRow;
  });
  const positions = value.positions.map((raw, index): Position => {
    if (!isRecord(raw)) throw new Error(`Formal backtest position is invalid: ${modelId}/${index}`);
    const weight = Number(raw.weight);
    if (!Number.isFinite(weight) || weight < 0 || weight > 1.0000001) throw new Error(`Formal backtest position weight is invalid: ${modelId}/${index}`);
    return {
      ...raw,
      date: requiredString(raw.date, `Formal backtest position date ${modelId}/${index}`),
      instrument: requiredString(raw.instrument, `Formal backtest position instrument ${modelId}/${index}`),
      weight,
    } as Position;
  });
  const trades = value.trades.map((raw, index): FormalBacktestTrade => {
    if (!isRecord(raw)) throw new Error(`Formal backtest trade is invalid: ${modelId}/${index}`);
    return {
      ...raw,
      date: requiredString(raw.date, `Formal backtest trade date ${modelId}/${index}`),
      instrument: requiredString(raw.instrument, `Formal backtest trade instrument ${modelId}/${index}`),
      action: requiredString(raw.action, `Formal backtest trade action ${modelId}/${index}`),
    } as FormalBacktestTrade;
  });
  const attribution = value.attribution.map((raw, index) => {
    if (!isRecord(raw)) throw new Error(`Formal backtest attribution row is invalid: ${modelId}/${index}`);
    const output = { ...raw } as { instrument?: string; name?: string; value?: number; [key: string]: unknown };
    if (raw.value !== undefined) {
      const numeric = Number(raw.value);
      if (!Number.isFinite(numeric)) throw new Error(`Formal backtest attribution value is invalid: ${modelId}/${index}`);
      output.value = numeric;
    }
    return output;
  });

  const completeness = value.evidence_completeness;
  return {
    ...value,
    schema_version: '1.0.0',
    record_type: 'formal_model_backtest',
    backtest_id: requiredString(value.backtest_id, 'Formal backtest backtest_id'),
    model_id: modelId,
    display_name: requiredString(value.display_name, 'Formal backtest display_name'),
    market: requiredString(value.market, 'Formal backtest market'),
    benchmark: requiredString(value.benchmark, 'Formal backtest benchmark'),
    publication_status: 'accepted_formal_baseline',
    generated_at: requiredString(value.generated_at, 'Formal backtest generated_at'),
    evidence_cutoff: requiredString(value.evidence_cutoff, 'Formal backtest evidence_cutoff'),
    trace_frequency: requiredString(value.trace_frequency, 'Formal backtest trace_frequency'),
    date_range: {
      start: requiredString(dateRange.start, 'Formal backtest date_range.start'),
      end: requiredString(dateRange.end, 'Formal backtest date_range.end'),
    },
    metrics: numericRecord(value.metrics, `Formal backtest metrics ${modelId}`),
    portfolio_contract: isRecord(value.portfolio_contract) ? value.portfolio_contract : {},
    report,
    positions,
    trades,
    attribution,
    window_summary: value.window_summary.filter(isRecord),
    evidence: value.evidence,
    evidence_completeness: {
      ...completeness,
      status: completenessStatus,
      missing: stringArray(completeness.missing),
    } as FormalBacktestCompleteness,
    interpretation_notes: stringArray(value.interpretation_notes),
    research_only: true,
    trade_ready: false,
  } as FormalBacktestPackage;
}

async function sha256Text(text: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

function formalAssetRoot(): string {
  const base = import.meta.env.BASE_URL.endsWith('/') ? import.meta.env.BASE_URL : `${import.meta.env.BASE_URL}/`;
  return `${base}data/formal-backtests/`;
}

async function fetchJsonText(path: string): Promise<{ text: string; value: unknown }> {
  const response = await fetch(`${formalAssetRoot()}${path}`, { cache: 'no-cache' });
  if (!response.ok) throw new Error(`Formal backtest asset request failed (${response.status}): ${path}`);
  const text = await response.text();
  try {
    return { text, value: JSON.parse(text) as unknown };
  } catch (error) {
    throw new Error(`Formal backtest asset contains invalid JSON (${path}): ${error instanceof Error ? error.message : String(error)}`);
  }
}

export async function loadFormalBacktestPackages(): Promise<FormalBacktestPackage[]> {
  const catalogResult = await fetchJsonText('catalog.json');
  const catalog = parseFormalBacktestCatalog(catalogResult.value);
  const packages: FormalBacktestPackage[] = [];
  for (const entry of catalog.records) {
    const result = await fetchJsonText(entry.path);
    if ((await sha256Text(result.text)) !== entry.sha256) throw new Error(`Formal backtest SHA-256 mismatch: ${entry.model_id}`);
    packages.push(parseFormalBacktestPackage(result.value, entry.model_id));
  }
  return packages;
}

export function attachFormalBacktests(existingModels: ModelData[], packages: FormalBacktestPackage[]): ModelData[] {
  const existing = new Map(existingModels.map((model) => [model.id, model]));
  return packages.map((formal) => {
    const source = existing.get(formal.model_id);
    const sourceBacktest = source?.backtest ?? {};
    const providerIdentity = typeof formal.evidence.provider_identity === 'string' ? formal.evidence.provider_identity : '';
    const displayName = publicDisplayName(formal);
    const publicFormal = displayName === formal.display_name ? formal : { ...formal, display_name: displayName };
    return {
      ...source,
      id: formal.model_id,
      tag: displayName,
      name: displayName,
      market: formal.market,
      model_type: source?.model_type || (formal.model_id.includes('v4_2') ? 'rules_based_rotation' : 'xgb'),
      path: source?.path || String(formal.evidence.contract_path ?? ''),
      run_id: formal.backtest_id,
      snapshot_id: providerIdentity || source?.snapshot_id || '',
      created_at: formal.generated_at,
      stage: 'FORMAL_BASELINE',
      description: source?.description || `Accepted formal ${formal.market.toUpperCase()} baseline backtest.`,
      metrics: formal.metrics,
      params: {
        ...(source?.params ?? {}),
        formal_backtest: {
          backtest_id: formal.backtest_id,
          trace_frequency: formal.trace_frequency,
          evidence_cutoff: formal.evidence_cutoff,
          evidence_completeness: formal.evidence_completeness,
          portfolio_contract: formal.portfolio_contract,
          research_only: true,
          trade_ready: false,
        },
      },
      backtest: {
        ...sourceBacktest,
        meta: {
          start: formal.date_range.start,
          end: formal.date_range.end,
          benchmark: formal.benchmark,
          market: formal.market,
          generated_at: formal.generated_at,
        },
        metrics: formal.metrics,
        report: formal.report,
        positions: formal.positions,
        attribution: formal.attribution,
        featureImportance: sourceBacktest.featureImportance ?? {},
        indicators: {
          ...(sourceBacktest.indicators ?? {}),
          formal_backtest: true,
          trace_frequency: formal.trace_frequency,
          evidence_cutoff: formal.evidence_cutoff,
          evidence_completeness: formal.evidence_completeness.status,
        },
        formalBacktest: publicFormal,
      },
    } as ModelData;
  });
}
