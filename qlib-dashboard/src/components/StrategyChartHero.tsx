import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { EntityChartPanel } from '@/components/workspace/EntityWorkspace';
import { BaselineControl } from '@/components/charts/BaselineControl';
import { CompareControl } from '@/components/charts/CompareControl';
import { CompareLegend, type CompareLegendItem } from '@/components/charts/CompareLegend';
import { MarkerDetailPanel } from '@/components/charts/MarkerDetailPanel';
import { NavChart, type NavChartSeries } from '@/components/charts/NavChart';
import { VixContextPane, type VixPaneState } from '@/components/charts/VixContextPane';
import { useBaselinePreference } from '@/hooks/useBaselinePreference';
import {
  BASELINE_EXACT_DATE_DISCLOSURE,
  DECLARED_BENCHMARK_DISCLOSURE,
  MARKET_BASELINES,
  MARKET_BASELINE_RETURN_DISCLOSURE,
  marketNavFromBars,
  navFromBenchmarkField,
  type BaselineKind,
  type BaselineMarket,
  type BaselineOption,
} from '@/lib/baseline';
import { baselineOptionsFor, defaultBaselineKindFor, type BaselineOptionSource } from '@/lib/baseline-options';
import { navMarkerDetail } from '@/lib/chart-markers';
import type { CompareEntityOption, CompareEntitySelection } from '@/lib/entity-overlays';
import { loadFormalNav } from '@/lib/formal-nav';
import { loadRunSection, type GovernedRunSummary } from '@/lib/governed-run';
import { readMarketEvidence } from '@/lib/market-evidence-cache';
import {
  MAX_MODEL_OVERLAYS,
  globalModelWindow,
  marketModelIds,
  modelCompareId,
  modelCompareOptions,
  modelIdentityColors,
  type ModelWindowInput,
} from '@/lib/model-comparison';
import { alignNavSeries, joinNavMarkers, navFromReport, type NavMarker, type NavPoint } from '@/lib/nav-series';
import { navHorizonCoverage, navSeriesForPeriod } from '@/lib/nav-returns';
import type { ReportRow } from '@/lib/types';
import { vixUnavailableReason } from '@/lib/vix-context';
import {
  CHART_HORIZONS,
  DEFAULT_CHART_HORIZON,
  coverageReasonText,
  formatReturn,
  isStale,
  marketBaselineKey,
  maximumDrawdown,
  metricDisplay,
  navBetween,
  navMarkerMode,
  parseNavTrades,
  provisionalObservationCount,
  returnTone,
  staleDays,
  windowReturns,
  type NavMarkerMode,
} from '@/lib/strategy-chart';
import { cn } from '@/lib/utils';

function useChartHeight(): number {
  const [height, setHeight] = useState(380);
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const query = window.matchMedia('(min-width: 640px)');
    const update = () => setHeight(query.matches ? 380 : 300);
    update();
    query.addEventListener?.('change', update);
    return () => query.removeEventListener?.('change', update);
  }, []);
  return height;
}

/**
 * The comparison picker joins the control row on larger screens. On a handset
 * it moves below the plot so its control row cannot push the chart-first hero
 * below the fold; the picker remains the same controlled component.
 */
function useHandsetLayout(): boolean {
  const [handset, setHandset] = useState(() => (
    typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(max-width: 639px)').matches
  ));
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const query = window.matchMedia('(max-width: 639px)');
    const update = () => setHandset(query.matches);
    update();
    query.addEventListener?.('change', update);
    return () => query.removeEventListener?.('change', update);
  }, []);
  return handset;
}

function markerModeLabel(mode: NavMarkerMode): string {
  return mode === 'holding-end' ? 'holding-end settlement dates' : 'trade dates';
}

function baselineLabel(option: BaselineOption | null): string {
  return option?.label ?? 'baseline';
}

interface SelectedModelOverlay {
  id: string;
  modelVersionId: string;
  label: string;
  run: GovernedRunSummary;
}

type OverlaySeriesState =
  | { status: 'loading' }
  | { status: 'ready'; points: NavPoint[] }
  | { status: 'unavailable'; reason: string };

const EMPTY_DISPLAYED = new Map<string, string>();

interface HeroTileProps {
  label: string;
  testId: string;
  value: string;
  valueClassName?: string;
  children?: ReactNode;
}

function HeroTile({ label, testId, value, valueClassName, children }: HeroTileProps) {
  return (
    <div className="min-w-0 bg-card px-3 py-3 sm:px-4">
      <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{label}</p>
      <p data-testid={testId} className={cn('ae-hero-value mt-1 break-words font-mono', valueClassName)}>
        {value}
      </p>
      {children}
    </div>
  );
}

/**
 * Chart-first formal strategy summary. Reads only the compact `nav.json` plus the
 * already section-cached trades ledger; the full performance section remains the
 * review below, and market bars are requested only after a market selection.
 *
 * Same-market formal models may be added as NAV overlays. The base model is
 * always the page's own run; a single global exact common window keeps every
 * series on one indexed axis.
 */
export function StrategyChartHero({
  run,
  runs = [],
}: {
  run: GovernedRunSummary;
  /** The accepted formal catalog; used only to offer same-market model overlays. */
  runs?: GovernedRunSummary[];
}) {
  const market: BaselineMarket | null = run.market === 'us' || run.market === 'cn' ? run.market : null;
  const [period, setPeriod] = useState(DEFAULT_CHART_HORIZON);
  const [rows, setRows] = useState<ReportRow[]>([]);
  const [navLoaded, setNavLoaded] = useState(false);
  const [navError, setNavError] = useState<string | null>(null);
  const [trades, setTrades] = useState<ReturnType<typeof parseNavTrades>>([]);
  const [tradesLoading, setTradesLoading] = useState(true);
  const [tradesError, setTradesError] = useState<string | null>(null);
  const [kind, setKind] = useState<BaselineKind | null>(null);
  const [marketSeries, setMarketSeries] = useState<{ key: string; points: NavPoint[] } | null>(null);
  const [marketLoading, setMarketLoading] = useState(false);
  const [baselineError, setBaselineError] = useState<string | null>(null);
  const [vixState, setVixState] = useState<VixPaneState>({ status: 'loading' });
  const [selectedMarker, setSelectedMarker] = useState<NavMarker | null>(null);
  const [selectedModels, setSelectedModels] = useState<SelectedModelOverlay[]>([]);
  const [overlaySeries, setOverlaySeries] = useState<Record<string, OverlaySeriesState>>({});
  const previousKind = useRef<BaselineKind | null>(null);
  const overlayRequests = useRef(new Map<string, Promise<void>>());
  const overlayStateRef = useRef(overlaySeries);
  const selectedIdsRef = useRef<string[]>([]);
  const mountedRef = useRef(true);
  overlayStateRef.current = overlaySeries;
  selectedIdsRef.current = selectedModels.map(item => item.id);
  const { preference, setPreference } = useBaselinePreference();
  const chartHeight = useChartHeight();
  const handset = useHandsetLayout();

  const catalogRuns = useMemo(() => {
    const list = runs.length > 0 ? runs : [run];
    return list.some(candidate => candidate.key === run.key) ? list : [run, ...list];
  }, [run, runs]);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    setSelectedModels([]);
    setOverlaySeries({});
  }, [run.key]);

  useEffect(() => {
    let active = true;
    setNavLoaded(false);
    setNavError(null);
    setRows([]);
    void loadFormalNav(run)
      .then(series => {
        if (!active) return;
        setRows(series.rows);
        setNavLoaded(true);
      })
      .catch(error => {
        if (!active) return;
        setRows([]);
        setNavError(error instanceof Error ? error.message : String(error));
        setNavLoaded(true);
      });
    return () => { active = false; };
  }, [run]);

  useEffect(() => {
    let active = true;
    setTradesLoading(true);
    setTradesError(null);
    setTrades([]);
    void loadRunSection(run, 'trades')
      .then(payload => {
        if (!active) return;
        setTrades(parseNavTrades(payload));
        setTradesLoading(false);
      })
      .catch(error => {
        if (!active) return;
        setTradesError(error instanceof Error ? error.message : String(error));
        setTradesLoading(false);
      });
    return () => { active = false; };
  }, [run]);

  /**
   * Load each selected overlay's own verified NAV projection. The base page
   * never prefetches another model: a read starts only after the viewer adds
   * the model, and a failure is scoped to that one overlay.
   */
  useEffect(() => {
    setOverlaySeries(previous => {
      const next: Record<string, OverlaySeriesState> = {};
      for (const item of selectedModels) next[item.id] = previous[item.id] ?? { status: 'loading' };
      return next;
    });
    for (const item of selectedModels) {
      if (overlayStateRef.current[item.id] || overlayRequests.current.has(item.id)) continue;
      const request = loadFormalNav(item.run)
        .then(series => {
          if (!mountedRef.current || !selectedIdsRef.current.includes(item.id)) return;
          setOverlaySeries(previous => ({
            ...previous,
            [item.id]: { status: 'ready', points: navFromReport(series.rows) },
          }));
        })
        .catch(error => {
          if (!mountedRef.current || !selectedIdsRef.current.includes(item.id)) return;
          setOverlaySeries(previous => ({
            ...previous,
            [item.id]: {
              status: 'unavailable',
              reason: `Verified NAV projection unavailable: ${error instanceof Error ? error.message : String(error)}`,
            },
          }));
        })
        .finally(() => { overlayRequests.current.delete(item.id); });
      overlayRequests.current.set(item.id, request);
    }
  }, [selectedModels]);

  const toggleModel = (id: string) => {
    setSelectedModels(current => {
      if (current.some(item => item.id === id)) return current.filter(item => item.id !== id);
      if (!market || current.length >= MAX_MODEL_OVERLAYS) return current;
      const candidate = catalogRuns.find(value => (
        value.channel === 'formal'
        && value.market === market
        && value.modelVersionId !== run.modelVersionId
        && modelCompareId(market, value.modelVersionId) === id
      ));
      if (!candidate) return current;
      return [...current, {
        id,
        modelVersionId: candidate.modelVersionId,
        label: candidate.title,
        run: candidate,
      }];
    });
  };
  const nav = useMemo(() => navFromReport(rows), [rows]);
  const windowPoints = useMemo(() => navSeriesForPeriod(nav, period), [nav, period]);
  const coverage = useMemo(() => navHorizonCoverage(nav, period), [nav, period]);
  const baselineSource = useMemo<BaselineOptionSource | null>(
    () => (market ? { view: 'strategy', run: { benchmark: run.benchmark, market }, rows } : null),
    [market, rows, run.benchmark],
  );
  const options = useMemo(
    () => (baselineSource ? baselineOptionsFor(baselineSource) : []),
    [baselineSource],
  );
  const activeKind: BaselineKind = kind
    ?? (market && baselineSource ? defaultBaselineKindFor(baselineSource, options, preference[market]) : 'none');
  const activeOption = options.find(option => option.kind === activeKind) ?? null;
  const fallbackKind = (): BaselineKind => {
    const previous = previousKind.current;
    if (previous && previous !== 'market' && options.some(option => option.kind === previous && option.available)) {
      return previous;
    }
    return options.some(option => option.kind === 'declared' && option.available) ? 'declared' : 'none';
  };

  useEffect(() => {
    if (activeKind !== 'market') previousKind.current = activeKind;
  }, [activeKind]);

  useEffect(() => {
    if (!market || activeKind !== 'market') {
      setMarketLoading(false);
      return;
    }
    const key = marketBaselineKey(market);
    if (marketSeries?.key === key) return;
    let active = true;
    setMarketLoading(true);
    setBaselineError(null);
    void readMarketEvidence(market)
      .then(evidence => marketNavFromBars(evidence.bars))
      .then(points => {
        if (!active) return;
        setMarketSeries({ key, points });
        setMarketLoading(false);
        setPreference(market, 'market');
      })
      .catch(error => {
        if (!active) return;
        setMarketLoading(false);
        const fallback = fallbackKind();
        setBaselineError(
          `Market baseline unavailable: ${error instanceof Error ? error.message : String(error)}. Reverted to ${fallback === 'declared' ? `the declared baseline (${run.benchmark})` : 'no baseline'}.`,
        );
        setKind(fallback);
        setPreference(market, fallback);
      });
    return () => { active = false; };
    // fallbackKind reads the latest options/refs and is intentionally not a dependency.
  }, [activeKind, market, marketSeries, run.benchmark, setPreference]);

  /**
   * US-only governed VIX context. It reads the published `us:VIX` market
   * evidence through the shared cache; CN charts never request or render it.
   * An absent series keeps an explicit reason and no substitute is drawn.
   */
  useEffect(() => {
    if (market !== 'us') return;
    let active = true;
    setVixState({ status: 'loading' });
    void readMarketEvidence('us', 'VIX')
      .then(evidence => {
        if (!active) return;
        if (!evidence || !Array.isArray(evidence.bars) || evidence.bars.length === 0) {
          setVixState({
            status: 'unavailable',
            reason: 'Governed US VIX series unavailable: the published series has no observations. No substitute series is shown.',
          });
          return;
        }
        setVixState({ status: 'ready', bars: evidence.bars });
      })
      .catch(error => {
        if (!active) return;
        setVixState({ status: 'unavailable', reason: vixUnavailableReason(error) });
      });
    return () => { active = false; };
  }, [market]);

  const baselineFull = useMemo(() => {
    if (activeKind === 'declared' && activeOption?.field) return navFromBenchmarkField(rows, activeOption.field);
    if (activeKind === 'market' && market && marketSeries?.key === marketBaselineKey(market)) {
      return marketSeries.points;
    }
    return [];
  }, [activeKind, activeOption, market, marketSeries, rows]);

  const windowStart = windowPoints[0]?.date ?? null;
  const windowEnd = windowPoints[windowPoints.length - 1]?.date ?? null;
  const baselineSelected = activeKind !== 'none' && activeOption !== null;
  const baselineName = baselineLabel(activeOption);
  const multiModel = selectedModels.length > 0;

  const overlayInputs = useMemo<ModelWindowInput[]>(
    () => selectedModels.flatMap(item => {
      const state = overlaySeries[item.id];
      if (!state || state.status !== 'ready') return [];
      return [{
        id: item.id,
        label: item.label,
        modelVersionId: item.modelVersionId,
        points: state.points,
      }];
    }),
    [overlaySeries, selectedModels],
  );

  const baselineInput = useMemo<ModelWindowInput | null>(
    () => (baselineSelected && baselineFull.length >= 2
      ? { id: 'baseline', label: baselineName, points: baselineFull }
      : null),
    [baselineFull, baselineName, baselineSelected],
  );

  /**
   * The single global window for every plotted series. Period bounds come from
   * the base model's own horizon; the window itself is the exact-date
   * intersection across the base, each accepted overlay and the active
   * baseline. Adding or removing an overlay, or changing the period, rebuilds
   * it; no series is ever rebased on its own window.
   */
  const globalModel = useMemo(
    () => (multiModel && market
      ? globalModelWindow({
        base: {
          id: 'base',
          label: run.title,
          modelVersionId: run.modelVersionId,
          points: nav,
        },
        overlays: overlayInputs,
        baseline: baselineInput,
        start: windowStart,
        end: windowEnd,
      })
      : null),
    [baselineInput, market, multiModel, nav, overlayInputs, run.modelVersionId, run.title, windowEnd, windowStart],
  );

  const effectivePoints = multiModel ? globalModel?.raw.get('base') ?? [] : windowPoints;
  const effectiveCoverage = useMemo(
    () => (multiModel ? navHorizonCoverage(effectivePoints, period) : coverage),
    [coverage, effectivePoints, multiModel, period],
  );
  const effectiveBaselinePoints = useMemo(
    () => (multiModel
      ? (globalModel?.baselineIncluded ? globalModel.raw.get('baseline') ?? [] : [])
      : navBetween(baselineFull, windowStart, windowEnd)),
    [baselineFull, globalModel, multiModel, windowEnd, windowStart],
  );
  const returns = useMemo(
    () => windowReturns(effectivePoints, effectiveBaselinePoints),
    [effectiveBaselinePoints, effectivePoints],
  );
  const effectiveWindowStart = multiModel ? globalModel?.startDate ?? null : windowStart;
  const effectiveWindowEnd = multiModel ? globalModel?.endDate ?? null : windowEnd;

  /**
   * A loaded market series must have two exact common dates in the current
   * window. Otherwise the comparison is invalid for this horizon, so the
   * failure is scoped to the baseline and the previous selection is restored.
   */
  useEffect(() => {
    if (!market || activeKind !== 'market' || marketLoading) return;
    if (!marketSeries || marketSeries.key !== marketBaselineKey(market)) return;
    if (effectivePoints.length < 2) return;
    const overlap = alignNavSeries(
      effectivePoints,
      navBetween(marketSeries.points, effectiveWindowStart, effectiveWindowEnd),
    );
    if (overlap.length >= 2) return;
    const fallback = fallbackKind();
    setBaselineError(
      `${baselineLabel(options.find(option => option.kind === 'market') ?? null)} has fewer than two exact-date observations in this window. Reverted to ${fallback === 'declared' ? 'the declared baseline' : 'no baseline'}; the strategy curve is unchanged.`,
    );
    setKind(fallback);
    setPreference(market, fallback);
  }, [
    activeKind, effectivePoints, effectiveWindowEnd, effectiveWindowStart, market,
    marketLoading, marketSeries, options, setPreference,
  ]);

  const markerMode = useMemo(() => navMarkerMode(rows), [rows]);
  const markers = useMemo(() => joinNavMarkers(nav, trades, markerMode), [nav, trades, markerMode]);
  const selectedMarkerDetail = useMemo(
    () => (selectedMarker ? navMarkerDetail(selectedMarker, { modelId: run.modelVersionId, label: run.title }) : null),
    [selectedMarker, run.modelVersionId, run.title],
  );
  useEffect(() => {
    if (selectedMarker && !markers.some(marker => marker.date === selectedMarker.date)) setSelectedMarker(null);
  }, [markers, selectedMarker]);

  // The value is measured on the exact common window when overlays are present,
  // but display gating still follows the base model's own horizon coverage so a
  // comparison never hides a readable base return or exposes an unreadable one.
  const periodDisplay = metricDisplay(coverage, returns.strategy);
  const drawdownDisplay = metricDisplay(coverage, maximumDrawdown(effectivePoints));
  const provisional = provisionalObservationCount(rows, returns.startDate, returns.endDate);
  const stale = isStale(run.evidenceCutoff, effectiveCoverage.asOf);
  const staleBy = staleDays(run.evidenceCutoff, effectiveCoverage.asOf);
  const horizonLabel = CHART_HORIZONS.find(horizon => horizon.period === period)?.label ?? period.toUpperCase();
  const baselineReturnDisplay = baselineSelected && returns.baseline !== null
    ? { text: formatReturn(returns.baseline), tone: returnTone(returns.baseline) }
    : null;
  const excessText = returns.excess !== null ? formatReturn(returns.excess) : '—';
  const windowRange = effectiveWindowStart && effectiveWindowEnd
    ? `${effectiveWindowStart} – ${effectiveWindowEnd}`
    : '—';
  const windowLabel = multiModel ? 'exact common window' : 'window';
  const strategySummaryName = multiModel ? `Base ${run.title}` : 'Strategy';
  const alignedObservations = returns.alignedObservations;
  const summaryLabel = effectivePoints.length > 0
    ? [
      `${horizonLabel} ${windowLabel} ${windowRange}`,
      `${strategySummaryName} ${periodDisplay.visible ? formatReturn(returns.strategy) : 'unavailable'}`,
      baselineSelected
        ? `${baselineName} ${returns.baseline !== null ? formatReturn(returns.baseline) : 'unavailable'}`
        : 'No baseline',
      ...(baselineSelected && alignedObservations > 0 ? [`${alignedObservations} aligned observations`] : []),
    ].join(' · ')
    : undefined;

  const modelColors = useMemo(
    () => modelIdentityColors(market ? marketModelIds(catalogRuns, market) : []),
    [catalogRuns, market],
  );

  const rejectedReasons = useMemo(() => {
    const reasons = new Map<string, string>(globalModel?.rejected ?? []);
    for (const item of selectedModels) {
      const state = overlaySeries[item.id];
      if (state?.status === 'unavailable') reasons.set(item.id, state.reason);
    }
    return reasons;
  }, [globalModel, overlaySeries, selectedModels]);

  const overlayUnavailable = useMemo(() => {
    const reasons = new Map<string, string>();
    for (const item of selectedModels) {
      const reason = rejectedReasons.get(item.id);
      if (reason) reasons.set(item.modelVersionId, reason);
    }
    return reasons;
  }, [rejectedReasons, selectedModels]);

  const compareOptions = useMemo<CompareEntityOption[]>(() => {
    if (!market) return [];
    return modelCompareOptions({
      runs: catalogRuns,
      market,
      baseModelVersionId: run.modelVersionId,
      baselineIdentity: baselineSelected
        ? (activeKind === 'declared' ? run.benchmark : MARKET_BASELINES[market].label)
        : null,
      unavailable: overlayUnavailable,
    }).map(option => ({
      id: option.id,
      kind: 'model' as const,
      label: option.label,
      detail: option.detail,
      available: option.available,
      ...(option.reason === undefined ? {} : { reason: option.reason }),
    }));
  }, [
    activeKind, baselineSelected, catalogRuns, market, overlayUnavailable,
    run.benchmark, run.modelVersionId,
  ]);

  const selectedCompare = useMemo<CompareEntitySelection[]>(
    () => selectedModels.map(item => ({ id: item.id, kind: 'model' as const, label: item.label })),
    [selectedModels],
  );

  const compareControl = market && compareOptions.length > 0 ? (
    <CompareControl
      options={compareOptions}
      selected={selectedCompare}
      onToggle={toggleModel}
      marketLabel={market === 'us' ? 'US' : 'CN'}
      displayed={EMPTY_DISPLAYED}
      max={MAX_MODEL_OVERLAYS}
    />
  ) : null;

  const legendItems = useMemo<CompareLegendItem[]>(() => {
    if (!multiModel) return [];
    const items: CompareLegendItem[] = [{
      id: 'base',
      label: run.title,
      detail: 'base · indexed NAV',
      colorRole: modelColors.get(run.modelVersionId)?.role ?? 'primary',
      dashed: false,
      kind: 'model',
    }];
    if (baselineSelected) {
      items.push({
        id: 'baseline',
        label: baselineName,
        detail: 'baseline · indexed',
        colorRole: 'baseline',
        dashed: true,
        kind: 'baseline',
        ...(globalModel && !globalModel.baselineIncluded
          ? { unavailableReason: 'No exact common dates with the compared models in this window.' }
          : {}),
      });
    }
    for (const item of selectedModels) {
      const state = overlaySeries[item.id];
      const color = modelColors.get(item.modelVersionId);
      const reason = rejectedReasons.get(item.id);
      items.push({
        id: item.id,
        label: item.label,
        detail: 'model NAV',
        colorRole: color?.role ?? 'muted',
        dashed: false,
        kind: 'model',
        href: `/strategies/${encodeURIComponent(item.modelVersionId)}`,
        onRemove: () => setSelectedModels(current => current.filter(candidate => candidate.id !== item.id)),
        loading: !state || state.status === 'loading',
        ...(reason === undefined ? {} : { unavailableReason: reason }),
      });
    }
    return items;
  }, [
    baselineName, baselineSelected, globalModel, modelColors, multiModel,
    overlaySeries, rejectedReasons, run.title, selectedModels,
  ]);

  const chartSeries = useMemo<NavChartSeries[]>(() => {
    if (multiModel) {
      if (!globalModel) return [];
      return globalModel.series.map(series => {
        if (series.role === 'base') {
          return {
            key: series.id,
            label: run.title,
            nav: series.points,
            emphasis: 'primary' as const,
            colorToken: modelColors.get(run.modelVersionId)?.token ?? 'chart-1',
          };
        }
        if (series.role === 'baseline') {
          return {
            key: series.id,
            label: baselineName,
            nav: series.points,
            emphasis: 'baseline' as const,
            colorToken: 'chart-2',
          };
        }
        return {
          key: series.id,
          label: series.label,
          nav: series.points,
          emphasis: 'model' as const,
          dashed: false,
          colorToken: modelColors.get(series.modelVersionId ?? '')?.token ?? 'muted-foreground',
        };
      });
    }
    const series: NavChartSeries[] = [];
    if (windowPoints.length > 0) {
      series.push({ key: 'strategy', label: run.title, nav: windowPoints, emphasis: 'primary' });
    }
    if (baselineSelected && effectiveBaselinePoints.length >= 2) {
      series.push({
        key: 'baseline',
        label: baselineName,
        nav: effectiveBaselinePoints,
        emphasis: 'baseline',
        colorToken: 'chart-2',
      });
    }
    return series;
  }, [
    baselineName, baselineSelected, effectiveBaselinePoints, globalModel,
    modelColors, multiModel, run.title, windowPoints,
  ]);

  const baselineNote = (() => {
    if (!baselineSelected) return 'Select a baseline to compare on exact common dates.';
    if (marketLoading && activeKind === 'market') return 'Loading the governed market series…';
    if (periodDisplay.reason) return periodDisplay.reason;
    if (returns.baseline === null) {
      return multiModel
        ? 'No exact common dates with the compared models in this window.'
        : 'No exact-date overlap with the primary window.';
    }
    return `Excess vs ${baselineName} ${excessText} · browser-derived, not a sealed metric`;
  })();

  const periodNote = periodDisplay.reason
    ?? (effectiveCoverage.state === 'partial'
      ? `Partial ${horizonLabel} ${windowLabel} · first observation ${effectiveCoverage.firstObservation ?? 'unavailable'}`
      : `${horizonLabel} ${windowLabel} · ${effectiveCoverage.observations} observations`);

  const emptyReason = navError
    ? 'The verified NAV projection is unavailable; the formal evidence review below remains readable.'
    : multiModel && selectedModels.some(item => {
      const state = overlaySeries[item.id];
      return !state || state.status === 'loading';
    })
      ? 'Loading the selected model NAV series…'
      : multiModel && !globalModel
        ? 'No exact common window across the base model, selected models and baseline in this period.'
        : effectiveCoverage.state === 'none'
          ? coverageReasonText(effectiveCoverage)
          : 'Not enough exact-date observations to plot this window.';

  const changeBaseline = (next: BaselineKind) => {
    setKind(next);
    setBaselineError(null);
    if (market) setPreference(market, next);
  };

  const horizonControl = (
    <div role="group" aria-label="Chart horizon" className="flex flex-wrap items-center gap-0.5 rounded-md border bg-muted/30 p-0.5">
      {CHART_HORIZONS.map(horizon => (
        <button
          key={horizon.period}
          type="button"
          aria-pressed={period === horizon.period}
          onClick={() => setPeriod(horizon.period)}
          className={cn(
            'research-touch min-h-8 rounded px-2.5 text-[11px] font-semibold tabular-nums transition-colors',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
            period === horizon.period
              ? 'bg-primary text-primary-foreground shadow-sm'
              : 'text-muted-foreground hover:bg-muted hover:text-foreground',
          )}
        >
          {horizon.label}
        </button>
      ))}
    </div>
  );

  const baselineControl = market ? (
    <BaselineControl
      options={options}
      value={activeKind}
      onChange={changeBaseline}
      marketLabel={market === 'us' ? 'US' : 'CN'}
    />
  ) : null;

  const headerControls = handset ? undefined : (
    <>
      {horizonControl}
      {compareControl}
      {baselineControl}
    </>
  );

  return (
    <EntityChartPanel
      testId="strategy-chart-hero"
      title="Performance path"
      description={handset ? undefined : (
        <p className="mt-1 max-w-2xl text-xs leading-5 text-muted-foreground">
          {multiModel
            ? 'Governed NAV for same-market formal models indexed to 100 at one exact common start. One axis; no interpolation, forward fill or cross-market comparison.'
            : 'Governed NAV indexed to 100 at the first exact-date observation. No interpolation, forward fill or cross-market baseline.'}
        </p>
      )}
      controls={headerControls}
    >
      {!navLoaded ? (
        <p role="status" className="p-6 text-sm text-muted-foreground">Loading verified NAV projection…</p>
      ) : (
        <>
          <div className="order-3 grid grid-cols-2 gap-px border-y bg-border lg:order-2 lg:grid-cols-4">
            <HeroTile
              label="Period return"
              testId="hero-period-return"
              value={periodDisplay.text}
              valueClassName={periodDisplay.visible ? returnTone(returns.strategy) : 'text-muted-foreground'}
            >
              <p data-testid="hero-period-note" className="mt-1 text-[10px] leading-4 text-muted-foreground">
                {navError ? 'Formal NAV projection unavailable.' : periodNote}
              </p>
            </HeroTile>

            <HeroTile
              label="Baseline return"
              testId="hero-baseline-return"
              value={baselineReturnDisplay?.text ?? (baselineSelected ? '—' : 'No baseline')}
              valueClassName={baselineReturnDisplay ? baselineReturnDisplay.tone : 'text-sm text-muted-foreground'}
            >
              <p data-testid="hero-excess-return" className="mt-1 text-[10px] leading-4 text-muted-foreground">
                {baselineNote}
              </p>
              {baselineSelected && alignedObservations > 0 && (
                <p className="mt-0.5 text-[10px] text-muted-foreground">
                  {alignedObservations} aligned observation{alignedObservations === 1 ? '' : 's'}
                </p>
              )}
            </HeroTile>

            <HeroTile
              label="Max drawdown"
              testId="hero-max-drawdown"
              value={drawdownDisplay.text}
              valueClassName={drawdownDisplay.visible ? returnTone(maximumDrawdown(effectivePoints)) : 'text-muted-foreground'}
            >
              <p data-testid="hero-drawdown-note" className="mt-1 text-[10px] leading-4 text-muted-foreground">
                {drawdownDisplay.reason ?? 'Chart-derived from retained wealth marks in this window.'}
              </p>
            </HeroTile>

            <HeroTile label="Window" testId="hero-window" value={windowRange} valueClassName="text-sm">
              <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] leading-4 text-muted-foreground">
                <span>{effectiveCoverage.observations} observation{effectiveCoverage.observations === 1 ? '' : 's'} · As of {effectiveCoverage.asOf ?? 'unavailable'}</span>
                {stale && (
                  <span
                    data-testid="hero-window-stale"
                    className="rounded bg-warning/10 px-1.5 py-0.5 font-semibold text-warning"
                  >
                    Stale by {staleBy} day{staleBy === 1 ? '' : 's'}
                  </span>
                )}
              </p>
              {effectiveCoverage.state === 'partial' && effectiveCoverage.firstObservation && (
                <p className="mt-0.5 text-[10px] leading-4 text-warning">
                  First observation {effectiveCoverage.firstObservation}
                </p>
              )}
            </HeroTile>
          </div>

          <div data-testid="strategy-nav-chart" className="order-2 p-4 sm:p-5 lg:order-3">
            {navError && (
              <p role="alert" className="mb-3 rounded-lg border border-warning/30 p-3 text-xs text-muted-foreground">
                {navError}
              </p>
            )}
            {baselineError && (
              <p
                role="note"
                data-testid="strategy-baseline-error"
                className="mb-3 rounded-lg border border-warning/30 p-3 text-xs text-muted-foreground"
              >
                {baselineError}
              </p>
            )}
            <NavChart
              series={chartSeries}
              markers={markers}
              height={chartHeight}
              periodLabel={horizonLabel}
              coverage={effectiveCoverage}
              emptyReason={emptyReason}
              onMarkerSelect={setSelectedMarker}
              selectedMarkerDate={selectedMarker?.date ?? null}
              summaryLabel={summaryLabel}
              seriesLegend={!multiModel}
              markerScope={multiModel ? `base model (${run.title})` : undefined}
            />

            {handset && (
              <div
                data-testid="strategy-model-mobile-controls"
                className="mt-3 flex flex-col gap-2"
              >
                {horizonControl}
                <div className="flex flex-wrap items-center gap-2">
                  {compareControl && (
                    <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                      Compare models
                    </span>
                  )}
                  {compareControl}
                  {baselineControl}
                </div>
              </div>
            )}

            {market === 'us' && (
              <VixContextPane
                state={vixState}
                start={effectiveWindowStart}
                end={effectiveWindowEnd}
              />
            )}

            {multiModel && <CompareLegend items={legendItems} />}

            {multiModel && (
              <p
                data-testid="strategy-model-comparison-disclosure"
                className="mt-2 text-[11px] leading-4 text-muted-foreground"
              >
                Comparing {selectedModels.length + 1} same-market formal models on one indexed axis ·{' '}
                {windowLabel} {windowRange} · historical research evidence, not a signal or forecast. Activity
                markers show the base model ({run.title}) only and are never derived from comparison NAV.
              </p>
            )}

            {selectedMarkerDetail && (
              <MarkerDetailPanel
                detail={selectedMarkerDetail}
                testId="strategy-selected-marker"
                ariaLabel="Selected rotation marker"
                market={run.market}
                model={run.modelVersionId}
                onClear={() => setSelectedMarker(null)}
              />
            )}

            <div className="mt-3 space-y-1 text-[11px] leading-4 text-muted-foreground">
              {tradesLoading && <p role="status">Loading retained rotation trades…</p>}
              {tradesError && (
                <p role="note">
                  Retained trades could not be verified, so rotation markers are unavailable. The strategy curve
                  remains readable.
                </p>
              )}
              {!tradesLoading && !tradesError && (
                <p>
                  Rotation markers use retained {markerModeLabel(markerMode)} joined to observed NAV dates. Markers
                  that fall outside this window or between observations are disclosed, never snapped. Research
                  trades only; not live fills or orders.
                </p>
              )}
              {provisional > 0 && (
                <p>
                  Includes {provisional} provisional observation{provisional === 1 ? '' : 's'} in this window;
                  unsettled marks remain research evidence.
                </p>
              )}
              {activeKind === 'market' && (
                <p>
                  {baselineName} · governed market bars · {MARKET_BASELINE_RETURN_DISCLOSURE}{' '}
                  {BASELINE_EXACT_DATE_DISCLOSURE}
                </p>
              )}
              {activeKind === 'declared' && (
                <p>
                  {baselineName} · {DECLARED_BENCHMARK_DISCLOSURE}
                </p>
              )}
            </div>
          </div>
        </>
      )}
    </EntityChartPanel>
  );
}
