/**
 * Governed chart indicators.
 *
 * Every definition comes from configs/indicators/indicator_registry_v1.yaml via
 * the generated, hash-bound snapshot. This module owns the single deterministic
 * formula implementation used by the chart layer; page components must not
 * re-implement indicator math.
 *
 * Truth rules:
 * - values use exact observed points only (no forward fill or interpolation);
 * - insufficient or invalid inputs return an explicit unavailable result;
 * - instrument indicators read only the instrument's own bars;
 * - market indicators read one declared governed series in their own market;
 * - non-governed and reserved registry entries never emit values.
 */

import {
  INDICATOR_FORMULA_CATALOG,
  INDICATOR_REGISTRY,
  INDICATOR_REGISTRY_SCHEMA_VERSION,
  INDICATOR_REGISTRY_SOURCE,
  INDICATOR_REGISTRY_SOURCE_SHA256,
} from './indicator-registry.generated';

export {
  INDICATOR_FORMULA_CATALOG,
  INDICATOR_REGISTRY,
  INDICATOR_REGISTRY_SCHEMA_VERSION,
  INDICATOR_REGISTRY_SOURCE,
  INDICATOR_REGISTRY_SOURCE_SHA256,
};

export type IndicatorScope = 'market' | 'instrument';
export type IndicatorStatus = 'governed' | 'research_only' | 'blocked';
export type IndicatorKind = 'derived' | 'series' | 'reserved';
export type IndicatorFormulaId =
  | 'sma'
  | 'ema'
  | 'rsi'
  | 'macd'
  | 'bollinger'
  | 'volume_sma';
export type IndicatorField = 'close' | 'volume';

export interface FormulaCatalogEntry {
  version: string;
  params: readonly string[];
  outputs: readonly string[];
}

export interface IndicatorInputs {
  source: 'instrument_bars' | 'market_series';
  field?: IndicatorField;
  series_id?: string;
}

export interface IndicatorProvenance {
  authorized_by: string;
  authorized_on: string;
  rationale: string;
  source: string;
}

export interface IndicatorEntry {
  indicator_id: string;
  scope: IndicatorScope;
  kind: IndicatorKind;
  market?: 'us' | 'cn';
  formula: IndicatorFormulaId | null;
  formula_version: string | null;
  inputs: IndicatorInputs;
  params: Readonly<Record<string, number>>;
  version: string;
  status: IndicatorStatus;
  description: string;
  provenance: IndicatorProvenance;
}

/** A single observed observation. Times are ISO dates and strictly increasing. */
export interface IndicatorPoint {
  time: string;
  value: number;
}

export type FormulaOutput = Record<string, IndicatorPoint[]>;

/** The observed OHLCV fields an instrument indicator may read. */
export interface IndicatorBar {
  time: string;
  close: number;
  volume: number;
}

export interface InstrumentIndicatorInput {
  scope: 'instrument';
  market: 'us' | 'cn';
  bars: readonly IndicatorBar[];
}

export interface MarketIndicatorInput {
  scope: 'market';
  market: 'us' | 'cn';
  series_id: string;
  series?: readonly IndicatorPoint[];
}

export type IndicatorInput = InstrumentIndicatorInput | MarketIndicatorInput;

export type IndicatorUnavailableReason =
  | 'not_computable_status'
  | 'scope_mismatch'
  | 'cross_market_mismatch'
  | 'series_identity_mismatch'
  | 'market_series_unavailable'
  | 'unsupported_formula'
  | 'unsupported_formula_version'
  | 'invalid_params'
  | 'unsupported_input_field'
  | 'invalid_observations'
  | 'insufficient_observations';

export interface IndicatorAvailable {
  available: true;
  indicator_id: string;
  version: string;
  scope: IndicatorScope;
  market: 'us' | 'cn';
  series: FormulaOutput;
}

export interface IndicatorUnavailable {
  available: false;
  indicator_id: string;
  version: string;
  scope: IndicatorScope;
  reason: IndicatorUnavailableReason;
  detail: string;
  observations?: number;
  required?: number;
}

export type IndicatorResult = IndicatorAvailable | IndicatorUnavailable;

interface IndicatorBase {
  indicator_id: string;
  version: string;
  scope: IndicatorScope;
}

const FORMULA_PARAMS: Readonly<Record<IndicatorFormulaId, readonly string[]>> = {
  sma: ['period'],
  ema: ['period'],
  rsi: ['period'],
  macd: ['fast', 'slow', 'signal'],
  bollinger: ['period', 'std_dev'],
  volume_sma: ['period'],
};

const FORMULA_OUTPUTS: Readonly<Record<IndicatorFormulaId, readonly string[]>> = {
  sma: ['value'],
  ema: ['value'],
  rsi: ['value'],
  macd: ['macd', 'signal', 'histogram'],
  bollinger: ['middle', 'upper', 'lower'],
  volume_sma: ['value'],
};

const FORMULA_IMPLEMENTATION_VERSION = '1';
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

function isIsoDate(value: string): boolean {
  if (!DATE_PATTERN.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

/** Return canonical points or null when any observation is unusable. */
function orderedPoints(points: readonly IndicatorPoint[]): IndicatorPoint[] | null {
  if (!Array.isArray(points)) return null;
  const ordered: IndicatorPoint[] = [];
  let previous = '';
  for (const point of points) {
    if (!point || typeof point.time !== 'string' || !isIsoDate(point.time)
      || typeof point.value !== 'number' || !Number.isFinite(point.value)) return null;
    if (point.time <= previous) return null;
    previous = point.time;
    ordered.push({ time: point.time, value: point.value });
  }
  return ordered;
}

function extractBars(
  bars: readonly IndicatorBar[],
  field: IndicatorField,
): IndicatorPoint[] | null {
  if (!Array.isArray(bars)) return null;
  const points: IndicatorPoint[] = [];
  for (const bar of bars) {
    if (!bar || typeof bar.time !== 'string'
      || !Number.isFinite(bar.close) || !Number.isFinite(bar.volume)) return null;
    points.push({ time: bar.time, value: field === 'close' ? bar.close : bar.volume });
  }
  const ordered = orderedPoints(points);
  if (ordered === null) return null;
  for (const point of ordered) {
    const invalid = field === 'close' ? point.value <= 0 : point.value < 0;
    if (invalid) return null;
  }
  return ordered;
}

function toPoints(
  points: readonly IndicatorPoint[],
  values: readonly number[],
  offset: number,
): IndicatorPoint[] {
  return values.map((value, index) => ({ time: points[offset + index].time, value }));
}

function mean(values: readonly number[]): number {
  let sum = 0;
  for (const value of values) sum += value;
  return sum / values.length;
}

function smaValues(values: readonly number[], period: number): number[] {
  let sum = 0;
  for (let index = 0; index < period; index += 1) sum += values[index];
  const output = [sum / period];
  for (let index = period; index < values.length; index += 1) {
    sum += values[index] - values[index - period];
    output.push(sum / period);
  }
  return output;
}

function emaValues(values: readonly number[], period: number): number[] {
  const alpha = 2 / (period + 1);
  const output = [mean(values.slice(0, period))];
  for (let index = period; index < values.length; index += 1) {
    output.push(alpha * values[index] + (1 - alpha) * output[output.length - 1]);
  }
  return output;
}

function rsiValue(averageGain: number, averageLoss: number): number {
  if (averageLoss === 0) return averageGain > 0 ? 100 : 50;
  return 100 - 100 / (1 + averageGain / averageLoss);
}

function rsiValues(values: readonly number[], period: number): number[] {
  let averageGain = 0;
  let averageLoss = 0;
  for (let index = 1; index <= period; index += 1) {
    const change = values[index] - values[index - 1];
    if (change > 0) averageGain += change;
    else averageLoss -= change;
  }
  averageGain /= period;
  averageLoss /= period;
  const output = [rsiValue(averageGain, averageLoss)];
  for (let index = period + 1; index < values.length; index += 1) {
    const change = values[index] - values[index - 1];
    averageGain = (averageGain * (period - 1) + (change > 0 ? change : 0)) / period;
    averageLoss = (averageLoss * (period - 1) + (change < 0 ? -change : 0)) / period;
    output.push(rsiValue(averageGain, averageLoss));
  }
  return output;
}

/** 20-session SMA, or null when fewer than `period` ordered points exist. */
export function sma(
  points: readonly IndicatorPoint[],
  period: number,
): IndicatorPoint[] | null {
  if (!Number.isSafeInteger(period) || period <= 0 || points.length < period) return null;
  return toPoints(points, smaValues(points.map(point => point.value), period), period - 1);
}

/** SMA-seeded exponential moving average with alpha = 2 / (period + 1). */
export function ema(
  points: readonly IndicatorPoint[],
  period: number,
): IndicatorPoint[] | null {
  if (!Number.isSafeInteger(period) || period <= 0 || points.length < period) return null;
  return toPoints(points, emaValues(points.map(point => point.value), period), period - 1);
}

/** Wilder RSI; returns null until `period + 1` observations exist. */
export function rsi(
  points: readonly IndicatorPoint[],
  period: number,
): IndicatorPoint[] | null {
  if (!Number.isSafeInteger(period) || period <= 0 || points.length < period + 1) return null;
  return toPoints(points, rsiValues(points.map(point => point.value), period), period);
}

/** MACD line, signal and histogram. Each key starts at its own first valid date. */
export function macd(
  points: readonly IndicatorPoint[],
  fast: number,
  slow: number,
  signal: number,
): FormulaOutput | null {
  if (![fast, slow, signal].every(value => Number.isSafeInteger(value) && value > 0)
    || fast >= slow || points.length < slow + signal - 1) return null;
  const values = points.map(point => point.value);
  const fastEma = emaValues(values, fast);
  const slowEma = emaValues(values, slow);
  const line: number[] = [];
  for (let index = slow - 1; index < values.length; index += 1) {
    line.push(fastEma[index - (fast - 1)] - slowEma[index - (slow - 1)]);
  }
  const signalValues = emaValues(line, signal);
  const histogram = signalValues.map(
    (value, index) => line[signal - 1 + index] - value,
  );
  const signalOffset = slow - 1 + signal - 1;
  return {
    macd: toPoints(points, line, slow - 1),
    signal: toPoints(points, signalValues, signalOffset),
    histogram: toPoints(points, histogram, signalOffset),
  };
}

/** Bollinger bands using population standard deviation (divide by period). */
export function bollinger(
  points: readonly IndicatorPoint[],
  period: number,
  stdDev: number,
): FormulaOutput | null {
  if (!Number.isSafeInteger(period) || period <= 0
    || !Number.isFinite(stdDev) || stdDev <= 0 || points.length < period) return null;
  const values = points.map(point => point.value);
  const middle: number[] = [];
  const upper: number[] = [];
  const lower: number[] = [];
  for (let index = period - 1; index < values.length; index += 1) {
    const window = values.slice(index - period + 1, index + 1);
    const average = mean(window);
    const variance = window.reduce(
      (total, value) => total + (value - average) ** 2,
      0,
    ) / period;
    const deviation = Math.sqrt(variance);
    middle.push(average);
    upper.push(average + stdDev * deviation);
    lower.push(average - stdDev * deviation);
  }
  const offset = period - 1;
  return {
    middle: toPoints(points, middle, offset),
    upper: toPoints(points, upper, offset),
    lower: toPoints(points, lower, offset),
  };
}

/** Volume SMA shares the close-SMA implementation but reads observed volume. */
export function volumeSma(
  points: readonly IndicatorPoint[],
  period: number,
): IndicatorPoint[] | null {
  return sma(points, period);
}

/**
 * Reject any parameter map that does not exactly match the formula contract.
 * Returns an explanation or null when valid.
 */
export function validateFormulaParams(
  formula: string,
  params: Readonly<Record<string, number>>,
): string | null {
  const expected = FORMULA_PARAMS[formula as IndicatorFormulaId];
  if (!expected) return `Unknown formula ${formula}.`;
  const actual = Object.keys(params).sort();
  const required = [...expected].sort();
  if (actual.join(',') !== required.join(',')) {
    return `Formula ${formula} requires exactly ${required.join(', ')}.`;
  }
  for (const name of expected) {
    const value = params[name];
    if (name === 'std_dev') {
      if (!Number.isFinite(value) || value <= 0) return 'std_dev must be a positive number.';
    } else if (!Number.isSafeInteger(value) || value <= 0) {
      return `${name} must be a positive integer.`;
    }
  }
  if (formula === 'macd' && params.fast >= params.slow) {
    return 'macd fast must be less than slow.';
  }
  return null;
}

export interface FormulaImplementation {
  id: IndicatorFormulaId;
  version: string;
  params: readonly string[];
  outputs: readonly string[];
  minObservations(params: Readonly<Record<string, number>>): number;
  compute(
    points: readonly IndicatorPoint[],
    params: Readonly<Record<string, number>>,
  ): FormulaOutput | null;
}

export const FORMULAS: Readonly<Record<IndicatorFormulaId, FormulaImplementation>> = {
  sma: {
    id: 'sma',
    version: FORMULA_IMPLEMENTATION_VERSION,
    params: FORMULA_PARAMS.sma,
    outputs: FORMULA_OUTPUTS.sma,
    minObservations: params => params.period,
    compute: (points, params) => {
      const values = sma(points, params.period);
      return values === null ? null : { value: values };
    },
  },
  ema: {
    id: 'ema',
    version: FORMULA_IMPLEMENTATION_VERSION,
    params: FORMULA_PARAMS.ema,
    outputs: FORMULA_OUTPUTS.ema,
    minObservations: params => params.period,
    compute: (points, params) => {
      const values = ema(points, params.period);
      return values === null ? null : { value: values };
    },
  },
  rsi: {
    id: 'rsi',
    version: FORMULA_IMPLEMENTATION_VERSION,
    params: FORMULA_PARAMS.rsi,
    outputs: FORMULA_OUTPUTS.rsi,
    minObservations: params => params.period + 1,
    compute: (points, params) => {
      const values = rsi(points, params.period);
      return values === null ? null : { value: values };
    },
  },
  macd: {
    id: 'macd',
    version: FORMULA_IMPLEMENTATION_VERSION,
    params: FORMULA_PARAMS.macd,
    outputs: FORMULA_OUTPUTS.macd,
    minObservations: params => params.slow + params.signal - 1,
    compute: (points, params) => macd(points, params.fast, params.slow, params.signal),
  },
  bollinger: {
    id: 'bollinger',
    version: FORMULA_IMPLEMENTATION_VERSION,
    params: FORMULA_PARAMS.bollinger,
    outputs: FORMULA_OUTPUTS.bollinger,
    minObservations: params => params.period,
    compute: (points, params) => bollinger(points, params.period, params.std_dev),
  },
  volume_sma: {
    id: 'volume_sma',
    version: FORMULA_IMPLEMENTATION_VERSION,
    params: FORMULA_PARAMS.volume_sma,
    outputs: FORMULA_OUTPUTS.volume_sma,
    minObservations: params => params.period,
    compute: (points, params) => {
      const values = volumeSma(points, params.period);
      return values === null ? null : { value: values };
    },
  },
};

function unavailable(
  base: IndicatorBase,
  reason: IndicatorUnavailableReason,
  detail: string,
  extra?: { observations?: number; required?: number },
): IndicatorUnavailable {
  return {
    available: false,
    indicator_id: base.indicator_id,
    version: base.version,
    scope: base.scope,
    reason,
    detail,
    ...extra,
  };
}

function available(
  base: IndicatorBase,
  market: 'us' | 'cn',
  series: FormulaOutput,
): IndicatorAvailable {
  return {
    available: true,
    indicator_id: base.indicator_id,
    version: base.version,
    scope: base.scope,
    market,
    series,
  };
}

function computeDerived(
  entry: IndicatorEntry,
  points: readonly IndicatorPoint[],
  market: 'us' | 'cn',
  base: IndicatorBase,
): IndicatorResult {
  if (entry.formula === null) {
    return unavailable(base, 'unsupported_formula', 'Registry entry declares no formula.');
  }
  const implementation = FORMULAS[entry.formula];
  if (!implementation) {
    return unavailable(base, 'unsupported_formula', `Unknown formula ${entry.formula}.`);
  }
  if (entry.formula_version !== implementation.version) {
    return unavailable(
      base,
      'unsupported_formula_version',
      `Registry formula version ${String(entry.formula_version)} does not match implementation ${implementation.version}.`,
    );
  }
  const paramError = validateFormulaParams(entry.formula, entry.params);
  if (paramError !== null) return unavailable(base, 'invalid_params', paramError);
  const required = implementation.minObservations(entry.params);
  if (points.length < required) {
    return unavailable(
      base,
      'insufficient_observations',
      `Indicator needs ${required} observations but received ${points.length}.`,
      { observations: points.length, required },
    );
  }
  const series = implementation.compute(points, entry.params);
  if (series === null) {
    return unavailable(
      base,
      'insufficient_observations',
      `Indicator needs ${required} observations but received ${points.length}.`,
      { observations: points.length, required },
    );
  }
  return available(base, market, series);
}

function computeInstrument(
  entry: IndicatorEntry,
  input: InstrumentIndicatorInput,
  base: IndicatorBase,
): IndicatorResult {
  const field = entry.inputs.field;
  if (entry.inputs.source !== 'instrument_bars'
    || (field !== 'close' && field !== 'volume')) {
    return unavailable(
      base,
      'unsupported_input_field',
      'Instrument indicator requires an instrument_bars close or volume input.',
    );
  }
  const points = extractBars(input.bars, field);
  if (points === null) {
    return unavailable(base, 'invalid_observations', 'Instrument bars are not valid ordered observations.');
  }
  if (entry.kind === 'series') return available(base, input.market, { value: points });
  return computeDerived(entry, points, input.market, base);
}

function computeMarket(
  entry: IndicatorEntry,
  input: MarketIndicatorInput,
  base: IndicatorBase,
): IndicatorResult {
  if (entry.market !== input.market) {
    return unavailable(
      base,
      'cross_market_mismatch',
      `Market indicator is bound to ${entry.market ?? 'no market'} and cannot run for ${input.market}.`,
    );
  }
  const declared = entry.inputs.series_id;
  if (!declared || declared.split(':')[0] !== entry.market) {
    return unavailable(
      base,
      'cross_market_mismatch',
      'Registry market series is not bound to its declared market.',
    );
  }
  if (input.series_id !== declared) {
    return unavailable(
      base,
      'series_identity_mismatch',
      `Expected governed series ${declared} but received ${input.series_id}.`,
    );
  }
  if (!input.series) {
    return unavailable(
      base,
      'market_series_unavailable',
      `Governed series ${declared} has not been published.`,
    );
  }
  const points = orderedPoints(input.series);
  if (points === null) {
    return unavailable(base, 'invalid_observations', 'Market series is not valid ordered observations.');
  }
  if (entry.kind === 'series') return available(base, input.market, { value: points });
  return computeDerived(entry, points, input.market, base);
}

/**
 * Compute one governed indicator from the declared input.
 *
 * The result is always explicit: an unavailable state carries a reason rather
 * than a partial or invented value.
 */
export function computeIndicator(
  entry: IndicatorEntry,
  input: IndicatorInput,
): IndicatorResult {
  const base: IndicatorBase = {
    indicator_id: entry.indicator_id,
    version: entry.version,
    scope: entry.scope,
  };
  if (entry.status !== 'governed') {
    return unavailable(
      base,
      'not_computable_status',
      `Indicator status ${entry.status} does not admit values.`,
    );
  }
  if (entry.kind === 'reserved') {
    return unavailable(
      base,
      'not_computable_status',
      'Reserved indicator families never compute values.',
    );
  }
  if (entry.scope !== input.scope) {
    return unavailable(
      base,
      'scope_mismatch',
      `Indicator scope ${entry.scope} cannot consume ${input.scope} input.`,
    );
  }
  if (input.scope === 'instrument') return computeInstrument(entry, input, base);
  return computeMarket(entry, input, base);
}

/**
 * Validate a registry snapshot against the formula contract. Returns every
 * problem found; the generated snapshot must yield an empty list.
 */
export function validateIndicatorRegistry(
  entries: readonly IndicatorEntry[] = INDICATOR_REGISTRY,
  catalog: Readonly<Record<string, FormulaCatalogEntry>> = INDICATOR_FORMULA_CATALOG,
): string[] {
  const errors: string[] = [];
  const seen = new Set<string>();
  for (const entry of entries) {
    const id = entry.indicator_id || '(missing id)';
    if (!entry.indicator_id || !/^[a-z][a-z0-9_]*$/.test(entry.indicator_id)) {
      errors.push(`${id}: indicator_id is not snake_case.`);
    }
    if (seen.has(entry.indicator_id)) errors.push(`${id}: duplicate indicator_id.`);
    seen.add(entry.indicator_id);
    if (!['instrument', 'market'].includes(entry.scope)) errors.push(`${id}: unknown scope ${String(entry.scope)}.`);
    if (!['derived', 'series', 'reserved'].includes(entry.kind)) errors.push(`${id}: unknown kind ${String(entry.kind)}.`);
    if (!['governed', 'research_only', 'blocked'].includes(entry.status)) errors.push(`${id}: unknown status ${String(entry.status)}.`);
    if (!entry.version) errors.push(`${id}: missing version.`);
    if (!entry.description) errors.push(`${id}: missing description.`);
    if (!entry.provenance?.authorized_by || !entry.provenance?.authorized_on
      || !entry.provenance?.rationale || !entry.provenance?.source) {
      errors.push(`${id}: incomplete provenance.`);
    }

    if (entry.scope === 'instrument') {
      if ('market' in entry) errors.push(`${id}: instrument scope must not declare a market.`);
      if (entry.inputs.source !== 'instrument_bars'
        || (entry.inputs.field !== 'close' && entry.inputs.field !== 'volume')) {
        errors.push(`${id}: instrument input must be instrument_bars close or volume.`);
      }
    } else {
      if (entry.market !== 'us' && entry.market !== 'cn') {
        errors.push(`${id}: market scope requires market us or cn.`);
      }
      if (entry.inputs.source !== 'market_series' || !entry.inputs.series_id) {
        errors.push(`${id}: market input must declare a market_series id.`);
      } else if (entry.market && entry.inputs.series_id.split(':')[0] !== entry.market) {
        errors.push(`${id}: market series ${entry.inputs.series_id} is outside ${entry.market}.`);
      }
    }

    if (entry.kind === 'derived') {
      const formula = entry.formula as string | null;
      if (!formula || !(formula in FORMULAS)) {
        errors.push(`${id}: unknown formula ${String(entry.formula)}.`);
      } else {
        const implementation = FORMULAS[formula as IndicatorFormulaId];
        const catalogEntry = catalog[formula];
        if (!catalogEntry) errors.push(`${id}: formula ${formula} is absent from the registry catalog.`);
        if (entry.formula_version !== implementation.version) {
          errors.push(`${id}: formula_version ${String(entry.formula_version)} does not match ${implementation.version}.`);
        }
        const paramError = validateFormulaParams(formula, entry.params);
        if (paramError !== null) errors.push(`${id}: ${paramError}`);
        if (entry.scope === 'market' && formula === 'volume_sma') {
          errors.push(`${id}: volume_sma is instrument-only.`);
        }
        if (entry.scope === 'instrument') {
          const expectedField = formula === 'volume_sma' ? 'volume' : 'close';
          if (entry.inputs.field !== expectedField) {
            errors.push(`${id}: formula ${formula} requires field ${expectedField}.`);
          }
        }
      }
      if (entry.formula === null) errors.push(`${id}: derived kind requires a formula.`);
    } else {
      if (entry.formula !== null || entry.formula_version !== null
        || Object.keys(entry.params).length > 0) {
        errors.push(`${id}: ${entry.kind} kind must not declare a formula or params.`);
      }
      if (entry.kind === 'reserved' && entry.status === 'governed') {
        errors.push(`${id}: reserved entries cannot be governed.`);
      }
    }
  }

  const catalogIds = Object.keys(catalog).sort();
  const implementationIds = Object.keys(FORMULAS).sort();
  if (catalogIds.join(',') !== implementationIds.join(',')) {
    errors.push('Formula catalog does not match the implemented formula set.');
  }
  for (const formula of implementationIds as IndicatorFormulaId[]) {
    const catalogEntry = catalog[formula];
    const implementation = FORMULAS[formula];
    if (!catalogEntry) continue;
    if (catalogEntry.version !== implementation.version) {
      errors.push(`${formula}: catalog version does not match implementation.`);
    }
    if ([...catalogEntry.params].sort().join(',') !== [...implementation.params].sort().join(',')) {
      errors.push(`${formula}: catalog params do not match implementation.`);
    }
    if ([...catalogEntry.outputs].join(',') !== [...implementation.outputs].join(',')) {
      errors.push(`${formula}: catalog outputs do not match implementation.`);
    }
  }
  return errors;
}
