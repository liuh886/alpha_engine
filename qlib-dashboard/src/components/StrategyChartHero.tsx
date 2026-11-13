import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { BaselineControl } from '@/components/charts/BaselineControl';
import { NavChart, type NavChartSeries } from '@/components/charts/NavChart';
import { useBaselinePreference } from '@/hooks/useBaselinePreference';
import {
  marketNavFromBars,
  navFromBenchmarkField,
  type BaselineKind,
  type BaselineMarket,
  type BaselineOption,
} from '@/lib/baseline';
import { loadFormalNav } from '@/lib/formal-nav';
import { loadRunSection, type GovernedRunSummary } from '@/lib/governed-run';
import { readMarketEvidence } from '@/lib/market-evidence-cache';
import { alignNavSeries, joinNavMarkers, navFromReport, type NavMarker, type NavPoint } from '@/lib/nav-series';
import { navHorizonCoverage, navSeriesForPeriod } from '@/lib/nav-returns';
import type { ReportRow } from '@/lib/types';
import {
  CHART_HORIZONS,
  DEFAULT_CHART_HORIZON,
  coverageReasonText,
  defaultBaselineKind,
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
  strategyBaselineOptions,
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

function markerSideLabel(side: NavMarker['side']): string {
  if (side === 'buy') return 'Buy / increase';
  if (side === 'sell') return 'Sell / decrease';
  return 'Buy and sell';
}

function markerModeLabel(mode: NavMarkerMode): string {
  return mode === 'holding-end' ? 'holding-end settlement dates' : 'trade dates';
}

function baselineLabel(option: BaselineOption | null): string {
  return option?.label ?? 'baseline';
}

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
      <p data-testid={testId} className={cn('mt-1 break-words font-mono text-lg tabular-nums', valueClassName)}>
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
 */
export function StrategyChartHero({ run }: { run: GovernedRunSummary }) {
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
  const [selectedMarker, setSelectedMarker] = useState<NavMarker | null>(null);
  const previousKind = useRef<BaselineKind | null>(null);
  const { preference, setPreference } = useBaselinePreference();
  const chartHeight = useChartHeight();

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

  const nav = useMemo(() => navFromReport(rows), [rows]);
  const windowPoints = useMemo(() => navSeriesForPeriod(nav, period), [nav, period]);
  const coverage = useMemo(() => navHorizonCoverage(nav, period), [nav, period]);
  const options = useMemo(
    () => (market ? strategyBaselineOptions({ benchmark: run.benchmark, market }, rows) : []),
    [market, rows, run.benchmark],
  );
  const activeKind: BaselineKind = kind ?? (market ? defaultBaselineKind(options, preference[market]) : 'none');
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

  const baselineFull = useMemo(() => {
    if (activeKind === 'declared' && activeOption?.field) return navFromBenchmarkField(rows, activeOption.field);
    if (activeKind === 'market' && market && marketSeries?.key === marketBaselineKey(market)) {
      return marketSeries.points;
    }
    return [];
  }, [activeKind, activeOption, market, marketSeries, rows]);

  const windowStart = windowPoints[0]?.date ?? null;
  const windowEnd = windowPoints[windowPoints.length - 1]?.date ?? null;
  const baselineWindow = useMemo(
    () => navBetween(baselineFull, windowStart, windowEnd),
    [baselineFull, windowStart, windowEnd],
  );
  const returns = useMemo(() => windowReturns(windowPoints, baselineWindow), [windowPoints, baselineWindow]);

  /**
   * A loaded market series must have two exact common dates in the current
   * window. Otherwise the comparison is invalid for this horizon, so the
   * failure is scoped to the baseline and the previous selection is restored.
   */
  useEffect(() => {
    if (!market || activeKind !== 'market' || marketLoading) return;
    if (!marketSeries || marketSeries.key !== marketBaselineKey(market)) return;
    if (windowPoints.length < 2) return;
    const overlap = alignNavSeries(windowPoints, navBetween(marketSeries.points, windowStart, windowEnd));
    if (overlap.length >= 2) return;
    const fallback = fallbackKind();
    setBaselineError(
      `${baselineLabel(options.find(option => option.kind === 'market') ?? null)} has fewer than two exact-date observations in this window. Reverted to ${fallback === 'declared' ? 'the declared baseline' : 'no baseline'}; the strategy curve is unchanged.`,
    );
    setKind(fallback);
    setPreference(market, fallback);
  }, [activeKind, market, marketLoading, marketSeries, options, setPreference, windowEnd, windowPoints, windowStart]);

  const markerMode = useMemo(() => navMarkerMode(rows), [rows]);
  const markers = useMemo(() => joinNavMarkers(nav, trades, markerMode), [nav, trades, markerMode]);
  useEffect(() => {
    if (selectedMarker && !markers.some(marker => marker.date === selectedMarker.date)) setSelectedMarker(null);
  }, [markers, selectedMarker]);

  const periodDisplay = metricDisplay(coverage, returns.strategy);
  const drawdownDisplay = metricDisplay(coverage, maximumDrawdown(windowPoints));
  const provisional = provisionalObservationCount(rows, returns.startDate, returns.endDate);
  const stale = isStale(run.evidenceCutoff, coverage.asOf);
  const staleBy = staleDays(run.evidenceCutoff, coverage.asOf);
  const horizonLabel = CHART_HORIZONS.find(horizon => horizon.period === period)?.label ?? period.toUpperCase();
  const baselineSelected = activeKind !== 'none' && activeOption !== null;
  const baselineName = baselineLabel(activeOption);
  const baselineReturnDisplay = baselineSelected && returns.baseline !== null
    ? { text: formatReturn(returns.baseline), tone: returnTone(returns.baseline) }
    : null;
  const excessText = returns.excess !== null ? formatReturn(returns.excess) : '—';
  const windowRange = windowStart && windowEnd ? `${windowStart} – ${windowEnd}` : '—';
  const alignedObservations = returns.alignedObservations;
  const summaryLabel = windowPoints.length > 0
    ? [
      `${horizonLabel} window ${windowRange}`,
      `Strategy ${periodDisplay.visible ? formatReturn(returns.strategy) : 'unavailable'}`,
      baselineSelected
        ? `${baselineName} ${returns.baseline !== null ? formatReturn(returns.baseline) : 'unavailable'}`
        : 'No baseline',
      ...(baselineSelected && alignedObservations > 0 ? [`${alignedObservations} aligned observations`] : []),
    ].join(' · ')
    : undefined;

  const chartSeries = useMemo<NavChartSeries[]>(() => {
    const series: NavChartSeries[] = [];
    if (windowPoints.length > 0) {
      series.push({ key: 'strategy', label: 'Strategy', nav: windowPoints, emphasis: 'primary' });
    }
    if (baselineSelected && baselineWindow.length >= 2) {
      series.push({
        key: 'baseline',
        label: baselineName,
        nav: baselineWindow,
        emphasis: 'baseline',
        colorToken: 'chart-2',
      });
    }
    return series;
  }, [baselineName, baselineSelected, baselineWindow, windowPoints]);

  const baselineNote = (() => {
    if (!baselineSelected) return 'Select a baseline to compare on exact common dates.';
    if (marketLoading && activeKind === 'market') return 'Loading the governed market series…';
    if (periodDisplay.reason) return periodDisplay.reason;
    if (returns.baseline === null) return 'No exact-date overlap with the primary window.';
    return `Excess vs ${baselineName} ${excessText} · browser-derived, not a sealed metric`;
  })();

  const periodNote = periodDisplay.reason
    ?? (coverage.state === 'partial'
      ? `Partial ${horizonLabel} window · first observation ${coverage.firstObservation ?? 'unavailable'}`
      : `${horizonLabel} window · ${coverage.observations} observations`);

  const emptyReason = navError
    ? 'The verified NAV projection is unavailable; the formal evidence review below remains readable.'
    : coverage.state === 'none'
      ? coverageReasonText(coverage)
      : 'Not enough exact-date observations to plot this window.';

  const changeBaseline = (next: BaselineKind) => {
    setKind(next);
    setBaselineError(null);
    if (market) setPreference(market, next);
  };

  return (
    <section
      data-testid="strategy-chart-hero"
      aria-labelledby="strategy-chart-hero-heading"
      className="overflow-hidden rounded-xl border bg-card shadow-card"
    >
      <header className="flex flex-col gap-3 border-b p-4 sm:p-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <h2 id="strategy-chart-hero-heading" className="text-lg font-semibold">Performance path</h2>
          <p className="mt-1 max-w-2xl text-xs leading-5 text-muted-foreground">
            Governed NAV indexed to 100 at the first exact-date observation. No interpolation, forward fill or
            cross-market baseline. All values remain research evidence, not live trading results.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
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
          {market && (
            <BaselineControl
              options={options}
              value={activeKind}
              onChange={changeBaseline}
              marketLabel={market === 'us' ? 'US' : 'CN'}
            />
          )}
        </div>
      </header>

      {!navLoaded ? (
        <p role="status" className="p-6 text-sm text-muted-foreground">Loading verified NAV projection…</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-px border-b bg-border lg:grid-cols-4">
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
              valueClassName={drawdownDisplay.visible ? returnTone(maximumDrawdown(windowPoints)) : 'text-muted-foreground'}
            >
              <p data-testid="hero-drawdown-note" className="mt-1 text-[10px] leading-4 text-muted-foreground">
                {drawdownDisplay.reason ?? 'Chart-derived from retained wealth marks in this window.'}
              </p>
            </HeroTile>

            <HeroTile label="Window" testId="hero-window" value={windowRange} valueClassName="text-sm">
              <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] leading-4 text-muted-foreground">
                <span>{coverage.observations} observation{coverage.observations === 1 ? '' : 's'} · As of {coverage.asOf ?? 'unavailable'}</span>
                {stale && (
                  <span
                    data-testid="hero-window-stale"
                    className="rounded bg-warning/10 px-1.5 py-0.5 font-semibold text-warning"
                  >
                    Stale by {staleBy} day{staleBy === 1 ? '' : 's'}
                  </span>
                )}
              </p>
              {coverage.state === 'partial' && coverage.firstObservation && (
                <p className="mt-0.5 text-[10px] leading-4 text-warning">
                  First observation {coverage.firstObservation}
                </p>
              )}
            </HeroTile>
          </div>

          <div data-testid="strategy-nav-chart" className="p-4 sm:p-5">
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
              coverage={coverage}
              emptyReason={emptyReason}
              onMarkerSelect={setSelectedMarker}
              selectedMarkerDate={selectedMarker?.date ?? null}
              summaryLabel={summaryLabel}
            />

            {selectedMarker && (
              <div
                data-testid="strategy-selected-marker"
                role="status"
                aria-label="Selected rotation marker"
                className="mt-3 rounded-lg border bg-muted/20 p-3 text-xs"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-semibold">
                    {selectedMarker.date} · {markerSideLabel(selectedMarker.side)} · {selectedMarker.count}{' '}
                    {selectedMarker.count === 1 ? 'trade' : 'trades'}
                  </p>
                  <button
                    type="button"
                    className="min-h-8 rounded border bg-card px-2 text-[11px] text-muted-foreground hover:text-foreground"
                    onClick={() => setSelectedMarker(null)}
                  >
                    Clear marker
                  </button>
                </div>
                <dl className="mt-2 divide-y rounded-md border bg-card">
                  <div className="grid grid-cols-[110px_minmax(0,1fr)] gap-2 px-2 py-1.5">
                    <dt className="text-muted-foreground">Instruments</dt>
                    <dd className="break-words font-mono">
                      {selectedMarker.instruments.length > 0 ? selectedMarker.instruments.join(', ') : 'Not retained'}
                    </dd>
                  </div>
                  <div className="grid grid-cols-[110px_minmax(0,1fr)] gap-2 px-2 py-1.5">
                    <dt className="text-muted-foreground">Net weight change</dt>
                    <dd className="font-mono">
                      {selectedMarker.netWeightDelta === null ? 'Not retained' : formatReturn(selectedMarker.netWeightDelta)}
                    </dd>
                  </div>
                  <div className="grid grid-cols-[110px_minmax(0,1fr)] gap-2 px-2 py-1.5">
                    <dt className="text-muted-foreground">Reasons</dt>
                    <dd className="break-words">
                      {selectedMarker.reasons.length > 0 ? selectedMarker.reasons.join('; ') : 'No reason retained'}
                    </dd>
                  </div>
                </dl>
                <p className="mt-2 text-[10px] leading-4 text-muted-foreground">
                  Retained research trade marker. It does not establish an execution price, live fill or order
                  instruction.
                </p>
              </div>
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
                  {baselineName} uses governed open-to-open price bars; it is a price comparison, not a total-return
                  index.
                </p>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
