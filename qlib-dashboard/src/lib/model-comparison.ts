/**
 * Strategy-chart model comparison. One market only: the page's own formal
 * model is the base and a viewer may add up to three same-market formal models.
 * Every displayed series is indexed to 100 at one global exact common start,
 * the intersection of the base, every accepted overlay, and the active
 * benchmark/baseline. Nothing is interpolated, forward filled or snapped, and
 * no series is rebased on its own window.
 */
import { MODEL_SERIES_TOKENS } from './chart-theme';
import { commonExactDates, rebaseEntityWindow, type EntitySeriesInput } from './entity-overlays';
import type { GovernedRunSummary } from './governed-run';
import type { NavPoint } from './nav-series';
import type { OverlayColorRole } from './security-chart-extensions';
import { navBetween } from './strategy-chart';

/** Hard cap for model overlays beside the page's own base model. */
export const MAX_MODEL_OVERLAYS = 3;

export type ModelCompareMarket = 'us' | 'cn';

export interface ModelCompareOption {
  id: string;
  market: ModelCompareMarket;
  modelVersionId: string;
  label: string;
  detail: string;
  href: string;
  available: boolean;
  reason?: string;
}

/** Stable comparison identity for one formal model in one market. */
export function modelCompareId(market: ModelCompareMarket, modelVersionId: string): string {
  return `model:${market}:${modelVersionId}`;
}

export function modelCompareHref(modelVersionId: string): string {
  return `/strategies/${encodeURIComponent(modelVersionId)}`;
}

function normalizedIdentity(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '');
}

/**
 * Formal models in the chart's own market, deduplicated by model version and
 * with the base model removed. The result is sorted by immutable model version
 * so filtering or selecting does not change identity order.
 */
export function sameMarketModels(
  runs: readonly GovernedRunSummary[],
  market: ModelCompareMarket,
  baseModelVersionId: string,
): GovernedRunSummary[] {
  const seen = new Set<string>([baseModelVersionId]);
  const models: GovernedRunSummary[] = [];
  for (const run of runs) {
    if (run.channel !== 'formal' || run.market !== market) continue;
    if (seen.has(run.modelVersionId)) continue;
    seen.add(run.modelVersionId);
    models.push(run);
  }
  return models.sort((left, right) => left.modelVersionId.localeCompare(right.modelVersionId));
}

/** Every same-market formal model identity, base included, in fixed order. */
export function marketModelIds(
  runs: readonly GovernedRunSummary[],
  market: ModelCompareMarket,
): string[] {
  const ids = new Set<string>();
  for (const run of runs) {
    if (run.channel === 'formal' && run.market === market) ids.add(run.modelVersionId);
  }
  return [...ids].sort();
}

export interface ModelCompareOptionContext {
  runs: readonly GovernedRunSummary[];
  market: ModelCompareMarket;
  baseModelVersionId: string;
  /**
   * Active baseline identity (declared benchmark or governed market index).
   * A model already displayed as that baseline is never offered as an overlay.
   */
  baselineIdentity?: string | null;
  /** Runtime reasons keyed by model version, for example a failed NAV read. */
  unavailable?: ReadonlyMap<string, string>;
}

/**
 * Same-market model options for the picker. The base model is excluded, a
 * model matching the active baseline stays visible but unavailable, and any
 * runtime failure keeps its exact reason. No cross-market model is ever built.
 */
export function modelCompareOptions(context: ModelCompareOptionContext): ModelCompareOption[] {
  const baseline = normalizedIdentity(context.baselineIdentity ?? '');
  return sameMarketModels(context.runs, context.market, context.baseModelVersionId).map((run) => {
    const runtimeReason = context.unavailable?.get(run.modelVersionId);
    const matchesBaseline = baseline !== ''
      && (normalizedIdentity(run.modelVersionId) === baseline
        || normalizedIdentity(run.title) === baseline);
    const reason = runtimeReason
      ?? (matchesBaseline ? 'Already displayed as the active baseline.' : undefined);
    return {
      id: modelCompareId(context.market, run.modelVersionId),
      market: context.market,
      modelVersionId: run.modelVersionId,
      label: run.title,
      detail: `${run.modelVersionId} · ${context.market.toUpperCase()} · formal NAV`,
      href: modelCompareHref(run.modelVersionId),
      available: reason === undefined,
      ...(reason === undefined ? {} : { reason }),
    };
  });
}

export interface ModelIdentityColor {
  /** Chart foundation token passed to the NAV renderer. */
  token: string;
  /** Comparison legend role. */
  role: OverlayColorRole;
  color: string;
}

/**
 * Fixed categorical color per model identity. Order is the lexicographic model
 * version order across the market catalog, so hiding, filtering or selecting a
 * model never repaints the survivors. Past the validated five-slot order a
 * model keeps a neutral overflow color instead of cycling a new identity into
 * slot one. The base model keeps its own slot too; the chart only renders it
 * with the primary token, so an overlay can never borrow another identity.
 */
export function modelIdentityColors(
  modelVersionIds: readonly string[],
): Map<string, ModelIdentityColor> {
  const ids = [...new Set(modelVersionIds.filter(id => typeof id === 'string' && id !== ''))].sort();
  const colors = new Map<string, ModelIdentityColor>();
  ids.forEach((id, index) => {
    const token = MODEL_SERIES_TOKENS[index];
    if (token === undefined) {
      colors.set(id, {
        token: 'muted-foreground',
        role: 'muted',
        color: 'hsl(var(--muted-foreground))',
      });
      return;
    }
    colors.set(id, {
      token,
      role: `model-${index + 1}` as OverlayColorRole,
      color: `hsl(var(--${token}))`,
    });
  });
  return colors;
}

export interface ModelWindowInput {
  id: string;
  label: string;
  modelVersionId?: string;
  points: readonly NavPoint[];
}

export type ModelWindowRole = 'base' | 'overlay' | 'baseline';

export interface ModelWindowSeries {
  id: string;
  label: string;
  role: ModelWindowRole;
  modelVersionId?: string;
  /** Exact common observations, indexed to 100 at the global start. */
  points: NavPoint[];
}

export interface ModelWindow {
  /** First exact observation shared by every plotted series. */
  startDate: string;
  endDate: string;
  observations: number;
  series: ModelWindowSeries[];
  /**
   * Original (unindexed) observations clipped to the period bounds. Return
   * math reads these so an indexed line is never used as a price level.
   */
  raw: ReadonlyMap<string, NavPoint[]>;
  /** Overlays that could not join the window, with the reason shown instead. */
  rejected: ReadonlyMap<string, string>;
  /** False when the selected baseline had fewer than two exact common dates. */
  baselineIncluded: boolean;
}

export const MODEL_WINDOW_REJECTION =
  'Fewer than two exact common dates with the base model and active baseline in this window.';

export interface GlobalModelWindowInput {
  base: ModelWindowInput;
  overlays: readonly ModelWindowInput[];
  baseline?: ModelWindowInput | null;
  /** Inclusive period bounds; observations outside them are never used. */
  start: string | null;
  end: string | null;
}

/**
 * Build the one global window for a multi-model chart.
 *
 * The base and the active baseline define the initial intersection. Each
 * overlay joins only when it contributes at least two exact common dates to
 * the already accepted set; otherwise it is reported in `rejected` and never
 * drawn partially. Every accepted series is rebased to 100 at the single
 * global start, and the raw points are retained for period-return math.
 */
export function globalModelWindow(input: GlobalModelWindowInput): ModelWindow | null {
  const { base, overlays, baseline, start, end } = input;
  if (!start || !end) return null;

  const clip = (points: readonly NavPoint[]): NavPoint[] => navBetween([...points], start, end);
  const meta = new Map<string, { role: ModelWindowRole; modelVersionId?: string }>();
  const raw = new Map<string, NavPoint[]>();
  const rejected = new Map<string, string>();

  const basePoints = clip(base.points);
  const inputs: EntitySeriesInput[] = [{ id: base.id, label: base.label, points: basePoints }];
  raw.set(base.id, basePoints);
  meta.set(base.id, {
    role: 'base',
    ...(base.modelVersionId === undefined ? {} : { modelVersionId: base.modelVersionId }),
  });

  let baselineIncluded = false;
  if (baseline) {
    const points = clip(baseline.points);
    const candidate: EntitySeriesInput = { id: baseline.id, label: baseline.label, points };
    if (commonExactDates([inputs[0], candidate]).length >= 2) {
      inputs.push(candidate);
      raw.set(baseline.id, points);
      meta.set(baseline.id, {
        role: 'baseline',
        ...(baseline.modelVersionId === undefined ? {} : { modelVersionId: baseline.modelVersionId }),
      });
      baselineIncluded = true;
    }
  }

  for (const overlay of overlays) {
    const points = clip(overlay.points);
    const candidate: EntitySeriesInput = { id: overlay.id, label: overlay.label, points };
    if (commonExactDates([...inputs, candidate]).length >= 2) {
      inputs.push(candidate);
      raw.set(overlay.id, points);
      meta.set(overlay.id, {
        role: 'overlay',
        ...(overlay.modelVersionId === undefined ? {} : { modelVersionId: overlay.modelVersionId }),
      });
    } else {
      rejected.set(overlay.id, MODEL_WINDOW_REJECTION);
    }
  }

  const window = rebaseEntityWindow(inputs);
  if (!window) return null;

  // Keep only the exact common observations in the raw series too. Return math
  // must describe the same global window as the indexed lines, never an earlier
  // date that the base and baseline happen to share before an overlay starts.
  for (const [id, points] of raw) {
    raw.set(id, points.filter(point => point.date >= window.startDate && point.date <= window.endDate));
  }

  const series = window.series.map((value): ModelWindowSeries => {
    const identity = meta.get(value.id);
    return {
      id: value.id,
      label: value.label,
      role: identity?.role ?? 'overlay',
      ...(identity?.modelVersionId === undefined ? {} : { modelVersionId: identity.modelVersionId }),
      points: value.points,
    };
  });

  return {
    startDate: window.startDate,
    endDate: window.endDate,
    observations: window.observations,
    series,
    raw,
    rejected,
    baselineIncluded,
  };
}
