export type MarketEvidenceMarket = 'us' | 'cn';

export interface MarketEvidenceCatalogSymbol {
  instrument_id: string;
  provider_symbol: string;
  symbol: string;
  source_instruments: string[];
  roles: string[];
  name: string;
  path: string;
  sha256: string;
  start: string;
  cutoff: string;
  formal_event_count: number;
  factor_series_available: boolean;
}

export interface MarketEvidenceCatalog {
  schema_version: '1.1';
  evidence_type: 'market_evidence_catalog';
  market: MarketEvidenceMarket;
  pool_id: string;
  candidate_count: number;
  benchmark: string;
  auxiliary_symbols: string[];
  start: string;
  cutoff: string;
  provider_identity_sha256: string;
  provider_manifest_sha256: string;
  factor_diagnostics_path: string;
  factor_diagnostics_sha256: string;
  factor_library_sha256: string;
  series_factor_group: string;
  symbol_count: number;
  symbols: MarketEvidenceCatalogSymbol[];
  research_only: true;
  trade_ready: false;
}

export interface MarketBar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface BollingerPoint {
  time: string;
  middle: number;
  upper: number;
  lower: number;
}

export interface MacdPoint {
  time: string;
  macd: number;
  signal: number;
  histogram: number;
}

export interface IndicatorPoint {
  time: string;
  value: number;
}

export interface FormalModelEvent {
  time: string;
  instrument_id: string;
  source_instrument: string;
  model_id: string;
  model_name: string;
  run_id: string;
  action: 'BUY' | 'SELL' | 'INCREASE' | 'DECREASE';
  previous_weight: number | null;
  target_weight: number | null;
  weight_delta: number | null;
  reason: string;
  research_only: true;
  trade_ready: false;
}

export interface SecurityMarketEvidence {
  schema_version: '1.1';
  evidence_type: 'security_market_evidence';
  market: MarketEvidenceMarket;
  instrument_id: string;
  provider_symbol: string;
  symbol: string;
  source_instruments: string[];
  roles: string[];
  name: string;
  start: string;
  cutoff: string;
  source_csv_sha256: string;
  provider_manifest_sha256: string;
  bars: MarketBar[];
  chart_studies: {
    boll20: BollingerPoint[];
    macd_12_26_9: MacdPoint[];
    rsi14: IndicatorPoint[];
  };
  formal_model_events: FormalModelEvent[];
  factor_series: Record<string, IndicatorPoint[]>;
  factor_series_scope: {
    group: string;
    factor_ids: string[];
    materialization_rule: string;
  };
  research_only: true;
  trade_ready: false;
}

export interface FactorDistributionRow {
  factor_id: string;
  display_name: string;
  information_family: string;
  implementation_hash: string;
  market?: MarketEvidenceMarket;
  pool_id?: string;
  start?: string;
  cutoff?: string;
  sample_count: number;
  missing_count: number;
  mean?: number;
  std?: number;
  min?: number;
  q01?: number;
  q05?: number;
  q25?: number;
  median?: number;
  q75?: number;
  q95?: number;
  q99?: number;
  max?: number;
  histogram_display_clip?: [number, number];
  below_histogram_clip?: number;
  above_histogram_clip?: number;
  histogram?: Array<{ lower: number; upper: number; count: number }>;
  status: 'ready' | 'unavailable';
}

export interface FactorDiagnosticsEvidence {
  schema_version: '1.1';
  evidence_type: 'factor_distribution_evidence';
  market: MarketEvidenceMarket;
  pool_id: string;
  start: string;
  cutoff: string;
  provider_manifest_sha256: string;
  factor_library_sha256: string;
  catalog_implementation_hash: string;
  distribution_universe: 'selected_pool_candidates_only';
  candidate_count: number;
  factors: FactorDistributionRow[];
  research_only: true;
  trade_ready: false;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== 'string' || value.trim().length === 0) throw new Error(`${label} is missing.`);
  return value;
}

function stringArray(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || value.some((entry) => typeof entry !== 'string')) throw new Error(`${label} must be a string array.`);
  return value.map(String);
}

function requiredFinite(value: unknown, label: string): number {
  const number = Number(value);
  if (!Number.isFinite(number)) throw new Error(`${label} must be finite.`);
  return number;
}

function assertBoundary(value: Record<string, unknown>, label: string): void {
  if (value.research_only !== true || value.trade_ready !== false) throw new Error(`${label} research boundary is invalid.`);
}

function assertDigest(value: string, label: string): void {
  if (!/^[a-f0-9]{64}$/.test(value)) throw new Error(`${label} SHA-256 is invalid.`);
}

function assertInstrumentIdentity(market: MarketEvidenceMarket, instrumentId: string, providerSymbol: string, label: string): void {
  if (instrumentId !== `${market}:${providerSymbol}`) throw new Error(`${label} canonical instrument identity mismatch.`);
}

export function parseMarketEvidenceCatalog(value: unknown, expectedMarket?: MarketEvidenceMarket): MarketEvidenceCatalog {
  if (!isRecord(value) || value.schema_version !== '1.1' || value.evidence_type !== 'market_evidence_catalog') {
    throw new Error('Unsupported market evidence catalog.');
  }
  assertBoundary(value, 'Market evidence catalog');
  const market = requiredString(value.market, 'Market evidence market') as MarketEvidenceMarket;
  if (!['us', 'cn'].includes(market) || (expectedMarket && market !== expectedMarket)) throw new Error('Market evidence market mismatch.');
  const providerManifest = requiredString(value.provider_manifest_sha256, 'Market evidence provider manifest');
  const factorDiagnosticsSha = requiredString(value.factor_diagnostics_sha256, 'Factor diagnostics');
  const factorLibrarySha = requiredString(value.factor_library_sha256, 'Factor library sha256');
  assertDigest(providerManifest, 'Market evidence provider manifest');
  assertDigest(factorDiagnosticsSha, 'Factor diagnostics');
  assertDigest(factorLibrarySha, 'Factor library');
  if (!Array.isArray(value.symbols)) throw new Error('Market evidence symbol catalog is missing.');
  const symbols = value.symbols.map((raw, index): MarketEvidenceCatalogSymbol => {
    if (!isRecord(raw)) throw new Error(`Market evidence symbol ${index} is invalid.`);
    const path = requiredString(raw.path, `Market evidence symbol ${index} path`);
    if (!/^symbols\/[A-Za-z0-9._-]+\.json$/.test(path)) throw new Error(`Unsafe market evidence path: ${path}`);
    const sha256 = requiredString(raw.sha256, `Market evidence symbol ${index} sha256`);
    assertDigest(sha256, `Market evidence symbol ${index}`);
    const providerSymbol = requiredString(raw.provider_symbol, `Market evidence provider symbol ${index}`);
    const symbol = requiredString(raw.symbol, `Market evidence symbol ${index}`);
    const instrumentId = requiredString(raw.instrument_id, `Market evidence instrument id ${index}`);
    if (symbol !== providerSymbol) throw new Error(`Market evidence display/provider symbol mismatch: ${instrumentId}`);
    assertInstrumentIdentity(market, instrumentId, providerSymbol, `Market evidence symbol ${index}`);
    return {
      instrument_id: instrumentId,
      provider_symbol: providerSymbol,
      symbol,
      source_instruments: stringArray(raw.source_instruments, `Market evidence source instruments ${index}`),
      roles: stringArray(raw.roles, `Market evidence roles ${index}`),
      name: requiredString(raw.name, `Market evidence name ${index}`),
      path,
      sha256,
      start: requiredString(raw.start, `Market evidence start ${index}`),
      cutoff: requiredString(raw.cutoff, `Market evidence cutoff ${index}`),
      formal_event_count: requiredFinite(raw.formal_event_count, `Market evidence event count ${index}`),
      factor_series_available: raw.factor_series_available === true,
    };
  });
  if (symbols.length !== requiredFinite(value.symbol_count, 'Market evidence symbol_count')) throw new Error('Market evidence symbol count mismatch.');
  if (new Set(symbols.map((row) => row.instrument_id)).size !== symbols.length) throw new Error('Market evidence instrument ids are not unique.');
  return {
    schema_version: '1.1',
    evidence_type: 'market_evidence_catalog',
    market,
    pool_id: requiredString(value.pool_id, 'Market evidence pool_id'),
    candidate_count: requiredFinite(value.candidate_count, 'Market evidence candidate_count'),
    benchmark: requiredString(value.benchmark, 'Market evidence benchmark'),
    auxiliary_symbols: stringArray(value.auxiliary_symbols, 'Market evidence auxiliary symbols'),
    start: requiredString(value.start, 'Market evidence start'),
    cutoff: requiredString(value.cutoff, 'Market evidence cutoff'),
    provider_identity_sha256: requiredString(value.provider_identity_sha256, 'Market evidence provider identity'),
    provider_manifest_sha256: providerManifest,
    factor_diagnostics_path: requiredString(value.factor_diagnostics_path, 'Factor diagnostics path'),
    factor_diagnostics_sha256: factorDiagnosticsSha,
    factor_library_sha256: factorLibrarySha,
    series_factor_group: requiredString(value.series_factor_group, 'Factor series group'),
    symbol_count: symbols.length,
    symbols,
    research_only: true,
    trade_ready: false,
  };
}

function parseBars(value: unknown): MarketBar[] {
  if (!Array.isArray(value) || value.length === 0) throw new Error('Security OHLCV bars are missing.');
  return value.map((raw, index) => {
    if (!isRecord(raw)) throw new Error(`Security bar ${index} is invalid.`);
    const open = requiredFinite(raw.open, `Security bar ${index} open`);
    const high = requiredFinite(raw.high, `Security bar ${index} high`);
    const low = requiredFinite(raw.low, `Security bar ${index} low`);
    const close = requiredFinite(raw.close, `Security bar ${index} close`);
    if (Math.min(open, high, low, close) <= 0 || high < low) throw new Error(`Security bar ${index} OHLC is invalid.`);
    return {
      time: requiredString(raw.time, `Security bar ${index} time`),
      open,
      high,
      low,
      close,
      volume: requiredFinite(raw.volume, `Security bar ${index} volume`),
    };
  });
}

function parseIndicatorPoints(value: unknown): IndicatorPoint[] {
  if (!Array.isArray(value)) return [];
  return value.map((raw, index) => {
    if (!isRecord(raw)) throw new Error(`Indicator point ${index} is invalid.`);
    return { time: requiredString(raw.time, `Indicator point ${index} time`), value: requiredFinite(raw.value, `Indicator point ${index} value`) };
  });
}

export function parseSecurityMarketEvidence(value: unknown, expectedMarket?: MarketEvidenceMarket, expectedSymbol?: string): SecurityMarketEvidence {
  if (!isRecord(value) || value.schema_version !== '1.1' || value.evidence_type !== 'security_market_evidence') throw new Error('Unsupported security market evidence.');
  assertBoundary(value, 'Security market evidence');
  const market = requiredString(value.market, 'Security market') as MarketEvidenceMarket;
  const providerSymbol = requiredString(value.provider_symbol, 'Security provider symbol');
  const symbol = requiredString(value.symbol, 'Security symbol');
  const instrumentId = requiredString(value.instrument_id, 'Security instrument id');
  if (expectedMarket && market !== expectedMarket) throw new Error('Security market evidence market mismatch.');
  if (expectedSymbol && symbol !== expectedSymbol) throw new Error('Security market evidence symbol mismatch.');
  if (symbol !== providerSymbol) throw new Error('Security display/provider symbol mismatch.');
  assertInstrumentIdentity(market, instrumentId, providerSymbol, 'Security market evidence');
  const studies = isRecord(value.chart_studies) ? value.chart_studies : {};
  const bollRaw = Array.isArray(studies.boll20) ? studies.boll20 : [];
  const macdRaw = Array.isArray(studies.macd_12_26_9) ? studies.macd_12_26_9 : [];
  const factorRaw = isRecord(value.factor_series) ? value.factor_series : {};
  const factorSeries = Object.fromEntries(Object.entries(factorRaw).map(([factorId, rows]) => [factorId, parseIndicatorPoints(rows)]));
  const eventsRaw = Array.isArray(value.formal_model_events) ? value.formal_model_events : [];
  const formalModelEvents = eventsRaw.map((raw, index): FormalModelEvent => {
    if (!isRecord(raw)) throw new Error(`Formal model event ${index} is invalid.`);
    assertBoundary(raw, `Formal model event ${index}`);
    const action = requiredString(raw.action, `Formal model event ${index} action`) as FormalModelEvent['action'];
    if (!['BUY', 'SELL', 'INCREASE', 'DECREASE'].includes(action)) throw new Error(`Formal model event ${index} action is unsupported.`);
    const eventInstrumentId = requiredString(raw.instrument_id, `Formal model event ${index} instrument_id`);
    if (eventInstrumentId !== instrumentId) throw new Error(`Formal model event ${index} instrument identity mismatch.`);
    const optional = (entry: unknown) => entry === null || entry === undefined ? null : requiredFinite(entry, `Formal model event ${index} weight`);
    return {
      time: requiredString(raw.time, `Formal model event ${index} time`),
      instrument_id: eventInstrumentId,
      source_instrument: requiredString(raw.source_instrument, `Formal model event ${index} source_instrument`),
      model_id: requiredString(raw.model_id, `Formal model event ${index} model_id`),
      model_name: requiredString(raw.model_name, `Formal model event ${index} model_name`),
      run_id: String(raw.run_id ?? ''),
      action,
      previous_weight: optional(raw.previous_weight),
      target_weight: optional(raw.target_weight),
      weight_delta: optional(raw.weight_delta),
      reason: String(raw.reason ?? ''),
      research_only: true,
      trade_ready: false,
    };
  });
  const boll20 = bollRaw.map((raw, index) => {
    if (!isRecord(raw)) throw new Error(`BOLL point ${index} is invalid.`);
    return {
      time: requiredString(raw.time, `BOLL point ${index} time`),
      middle: requiredFinite(raw.middle, `BOLL point ${index} middle`),
      upper: requiredFinite(raw.upper, `BOLL point ${index} upper`),
      lower: requiredFinite(raw.lower, `BOLL point ${index} lower`),
    };
  });
  const macd = macdRaw.map((raw, index) => {
    if (!isRecord(raw)) throw new Error(`MACD point ${index} is invalid.`);
    return {
      time: requiredString(raw.time, `MACD point ${index} time`),
      macd: requiredFinite(raw.macd, `MACD point ${index} macd`),
      signal: requiredFinite(raw.signal, `MACD point ${index} signal`),
      histogram: requiredFinite(raw.histogram, `MACD point ${index} histogram`),
    };
  });
  const scope = isRecord(value.factor_series_scope) ? value.factor_series_scope : {};
  return {
    schema_version: '1.1',
    evidence_type: 'security_market_evidence',
    market,
    instrument_id: instrumentId,
    provider_symbol: providerSymbol,
    symbol,
    source_instruments: stringArray(value.source_instruments, 'Security source instruments'),
    roles: stringArray(value.roles, 'Security roles'),
    name: requiredString(value.name, 'Security name'),
    start: requiredString(value.start, 'Security start'),
    cutoff: requiredString(value.cutoff, 'Security cutoff'),
    source_csv_sha256: requiredString(value.source_csv_sha256, 'Security source sha256'),
    provider_manifest_sha256: requiredString(value.provider_manifest_sha256, 'Security provider manifest sha256'),
    bars: parseBars(value.bars),
    chart_studies: { boll20, macd_12_26_9: macd, rsi14: parseIndicatorPoints(studies.rsi14) },
    formal_model_events: formalModelEvents,
    factor_series: factorSeries,
    factor_series_scope: {
      group: requiredString(scope.group, 'Security factor group'),
      factor_ids: stringArray(scope.factor_ids, 'Security factor ids'),
      materialization_rule: requiredString(scope.materialization_rule, 'Security factor materialization rule'),
    },
    research_only: true,
    trade_ready: false,
  };
}

export function parseFactorDiagnosticsEvidence(value: unknown, expectedMarket?: MarketEvidenceMarket): FactorDiagnosticsEvidence {
  if (!isRecord(value) || value.schema_version !== '1.1' || value.evidence_type !== 'factor_distribution_evidence') throw new Error('Unsupported factor diagnostics evidence.');
  assertBoundary(value, 'Factor diagnostics');
  const market = requiredString(value.market, 'Factor diagnostics market') as MarketEvidenceMarket;
  if (expectedMarket && market !== expectedMarket) throw new Error('Factor diagnostics market mismatch.');
  if (value.distribution_universe !== 'selected_pool_candidates_only') throw new Error('Factor diagnostics distribution universe is invalid.');
  if (!Array.isArray(value.factors)) throw new Error('Factor diagnostics rows are missing.');
  const factors = value.factors.map((raw, index): FactorDistributionRow => {
    if (!isRecord(raw)) throw new Error(`Factor diagnostics row ${index} is invalid.`);
    const status = raw.status === 'ready' ? 'ready' : 'unavailable';
    return {
      ...raw,
      factor_id: requiredString(raw.factor_id, `Factor diagnostics ${index} factor_id`),
      display_name: requiredString(raw.display_name, `Factor diagnostics ${index} display_name`),
      information_family: requiredString(raw.information_family, `Factor diagnostics ${index} information_family`),
      implementation_hash: requiredString(raw.implementation_hash, `Factor diagnostics ${index} implementation_hash`),
      sample_count: requiredFinite(raw.sample_count, `Factor diagnostics ${index} sample_count`),
      missing_count: requiredFinite(raw.missing_count, `Factor diagnostics ${index} missing_count`),
      status,
    } as FactorDistributionRow;
  });
  return {
    schema_version: '1.1',
    evidence_type: 'factor_distribution_evidence',
    market,
    pool_id: requiredString(value.pool_id, 'Factor diagnostics pool_id'),
    start: requiredString(value.start, 'Factor diagnostics start'),
    cutoff: requiredString(value.cutoff, 'Factor diagnostics cutoff'),
    provider_manifest_sha256: requiredString(value.provider_manifest_sha256, 'Factor diagnostics provider manifest'),
    factor_library_sha256: requiredString(value.factor_library_sha256, 'Factor diagnostics factor library'),
    catalog_implementation_hash: requiredString(value.catalog_implementation_hash, 'Factor diagnostics catalog implementation'),
    distribution_universe: 'selected_pool_candidates_only',
    candidate_count: requiredFinite(value.candidate_count, 'Factor diagnostics candidate_count'),
    factors,
    research_only: true,
    trade_ready: false,
  };
}

function assetRoot(market: MarketEvidenceMarket): string {
  const base = import.meta.env.BASE_URL.endsWith('/') ? import.meta.env.BASE_URL : `${import.meta.env.BASE_URL}/`;
  return `${base}data/market-evidence/${market}/`;
}

async function sha256Text(text: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function fetchText(url: string): Promise<string> {
  const response = await fetch(url, { cache: 'no-cache' });
  if (!response.ok) throw new Error(`Market evidence request failed (${response.status}).`);
  return response.text();
}

export async function loadMarketEvidenceCatalog(market: MarketEvidenceMarket): Promise<MarketEvidenceCatalog> {
  const text = await fetchText(`${assetRoot(market)}catalog.json`);
  return parseMarketEvidenceCatalog(JSON.parse(text) as unknown, market);
}

export async function loadSecurityMarketEvidence(catalog: MarketEvidenceCatalog, symbol: string): Promise<SecurityMarketEvidence> {
  const entry = catalog.symbols.find((row) => row.symbol === symbol);
  if (!entry) throw new Error(`Security is not present in governed ${catalog.market.toUpperCase()} Market Evidence: ${symbol}`);
  const text = await fetchText(`${assetRoot(catalog.market)}${entry.path}`);
  if ((await sha256Text(text)) !== entry.sha256) throw new Error(`Security market evidence SHA-256 mismatch: ${symbol}`);
  return parseSecurityMarketEvidence(JSON.parse(text) as unknown, catalog.market, symbol);
}

export async function loadFactorDiagnostics(catalog: MarketEvidenceCatalog): Promise<FactorDiagnosticsEvidence> {
  const text = await fetchText(`${assetRoot(catalog.market)}${catalog.factor_diagnostics_path}`);
  if ((await sha256Text(text)) !== catalog.factor_diagnostics_sha256) throw new Error(`Factor diagnostics SHA-256 mismatch: ${catalog.market}`);
  return parseFactorDiagnosticsEvidence(JSON.parse(text) as unknown, catalog.market);
}
