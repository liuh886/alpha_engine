import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useOutletContext, useParams, useSearchParams } from 'react-router-dom';
import { ArrowLeft, Loader2 } from 'lucide-react';
import { SecurityLightweightChart, type SecurityChartMode } from '@/components/SecurityLightweightChart';
import {
  EntityChartPanel,
  EntityDateFacts,
  EntityEvidenceSections,
  EntityWorkspace,
  type EntityBackLink,
} from '@/components/workspace/EntityWorkspace';
import { BaselineControl } from '@/components/charts/BaselineControl';
import { CompareControl } from '@/components/charts/CompareControl';
import { CompareLegend, type CompareLegendItem } from '@/components/charts/CompareLegend';
import { IndicatorControl } from '@/components/charts/IndicatorControl';
import { IndicatorNotes } from '@/components/charts/IndicatorNotes';
import { MarkerDetailPanel } from '@/components/charts/MarkerDetailPanel';
import { MarkerLegend } from '@/components/charts/MarkerLegend';
import { useBaselinePreference } from '@/hooks/useBaselinePreference';
import {
  BASELINE_EXACT_DATE_DISCLOSURE,
  MARKET_BASELINE_RETURN_DISCLOSURE,
  marketNavFromBars,
  type BaselineKind,
} from '@/lib/baseline';
import { baselineOptionsFor, defaultBaselineKindFor, type BaselineOptionSource } from '@/lib/baseline-options';
import {
  MARKER_DETAIL_DISCLOSURE,
  formatMarkerWeight,
  modelColorAssignments,
  modelColorFor,
  modelColorIndexMap,
  securityMarkerDetail,
} from '@/lib/chart-markers';
import {
  DEFAULT_INSTRUMENT_INDICATORS,
  buildInstrumentIndicatorOverlays,
  buildMarketIndicatorOverlays,
  instrumentIndicatorOptions,
  marketIndicatorOptions,
  type MarketSeriesStatus,
} from '@/lib/indicator-overlays';
import type { IndicatorPoint } from '@/lib/indicators';
import { ENTITY_KIND_LABEL, entityKindFromRoles, formatEntityRoles } from '@/lib/entity-kind';
import { staleDays } from '@/lib/metrics';
import { readMarketEvidence } from '@/lib/market-evidence-cache';
import {
  MAX_COMPARE_OVERLAYS,
  commonExactDates,
  firstFreeEntitySlot,
  instrumentEntityId,
  instrumentEntityOptions,
  modelEntityId,
  rebaseEntityWindow,
  type CompareEntityOption,
  type CompareEntitySelection,
  type EntitySeriesInput,
} from '@/lib/entity-overlays';
import {
  boundSecurityEvents,
  loadSecurityCatalog,
  loadSecurityEvidence,
  securityBarsForPeriod,
  type SecurityEvidence,
  type SecurityEvent,
  type SecuritySymbol,
} from '@/lib/security-evidence';
import { securityMarkers, unmatchedMarkerEvents, type SecurityMarker } from '@/lib/security-markers';
import {
  formatEventAction,
  formatIndexedReturn,
  formatSecurityPercent,
  formatSecurityPrice,
  humanizeEventReason,
  visibleCloseSummary,
} from '@/lib/security-format';
import {
  indexedBaselineSeries,
  isMarketBaselineInstrument,
  loadMarketBaseline,
  marketBaseline,
} from '@/lib/security-baseline';
import { loadFormalNav } from '@/lib/formal-nav';
import { navFromReport, type NavPoint } from '@/lib/nav-series';
import type { PerformancePeriod } from '@/lib/performancePeriods';
import type { RunWorkspaceContext } from '@/lib/run-workspace';
import type { GovernedRunSummary } from '@/lib/governed-run';
import type { OverlayColorRole, SecurityChartOverlay } from '@/lib/security-chart-extensions';
import { cn } from '@/lib/utils';

const PERIODS: Array<{ key: PerformancePeriod; label: string }> = [
  { key: '1m', label: '1M' }, { key: '3m', label: '3M' }, { key: '6m', label: '6M' },
  { key: '1y', label: '1Y' }, { key: '3y', label: '3Y' }, { key: 'all', label: 'ALL' },
];

const weight = formatMarkerWeight;

type BaselineState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; evidence: SecurityEvidence }
  | { status: 'error'; error: string };

type CatalogState =
  | { status: 'idle' | 'loading' }
  | { status: 'ready'; symbols: SecuritySymbol[] }
  | { status: 'error'; reason: string };

type EntitySeriesState =
  | { status: 'loading' }
  | { status: 'ready'; points: NavPoint[] }
  | { status: 'unavailable'; reason: string };

interface SelectedCompareEntity extends CompareEntitySelection {
  symbol?: string;
  run?: GovernedRunSummary;
}

const INDEXED_OVERLAY_FORMAT = { type: 'custom' as const, formatter: formatIndexedReturn, minMove: 0.1 };
const BASE_ENTITY_ID = 'base:instrument';
const BASELINE_ENTITY_ID = 'baseline:market';

/**
 * As-of and evidence-cutoff identities are one fact when the dates match and
 * two labelled metrics only when they genuinely differ. Kept as an exported
 * page helper so the shared entity facts own the rendering.
 */
export function SecurityAsOfMetrics({ asOf, cutoff }: { asOf: string | null; cutoff: string }) {
  return <EntityDateFacts asOf={asOf} cutoff={cutoff} testIdPrefix="security" />;
}

/**
 * Index/reference role context. The kind and roles come only from the
 * published market-evidence catalog; no benchmark identity is inferred from a
 * symbol name and no model evidence is attached that the catalog does not bind.
 */
export function EntityRoleContext({ evidence }: { evidence: SecurityEvidence }) {
  const kind = entityKindFromRoles(evidence.roles);
  const first = evidence.bars[0];
  const last = evidence.bars[evidence.bars.length - 1];
  return (
    <section
      className="research-surface p-4 sm:p-5"
      aria-label="Reference role and context"
      data-testid="entity-role-context"
    >
      <h2 className="ae-section-title">Role and context</h2>
      <dl className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <dt className="ae-metric-label">Entity kind</dt>
          <dd data-testid="entity-role-kind" className="mt-1 text-sm font-semibold">{ENTITY_KIND_LABEL[kind]}</dd>
        </div>
        <div>
          <dt className="ae-metric-label">Governed roles</dt>
          <dd className="mt-1 text-sm font-semibold">{formatEntityRoles(evidence.roles)}</dd>
        </div>
        <div>
          <dt className="ae-metric-label">Market benchmark</dt>
          <dd className="mt-1 font-mono text-sm font-semibold">{evidence.benchmark ?? '—'}</dd>
        </div>
        <div>
          <dt className="ae-metric-label">Close history</dt>
          <dd className="mt-1 font-mono text-sm font-semibold">
            {first?.time ?? '—'} – {last?.time ?? '—'} · {evidence.bars.length} sessions
          </dd>
        </div>
      </dl>
      <p className="mt-3 text-[11px] leading-4 text-muted-foreground">
        Index and reference identities are published market context. The catalog classes them; this page does not
        infer a benchmark role from a name and does not attach model evidence the catalog does not bind.
      </p>
    </section>
  );
}

export function SecurityHistory({
  evidence,
  runs,
  back,
}: {
  evidence: SecurityEvidence;
  runs: GovernedRunSummary[];
  back?: EntityBackLink;
}) {
  const [params, setParams] = useSearchParams();
  const range = PERIODS.find(period => period.key === params.get('range'))?.key ?? '1y';
  const [hidden, setHidden] = useState<string[]>([]);
  const [selected, setSelected] = useState<SecurityEvent[]>([]);
  const [completeLedger, setCompleteLedger] = useState(false);
  const [limit, setLimit] = useState(100);
  const [kind, setKind] = useState<BaselineKind | null>(null);
  const [baseline, setBaseline] = useState<BaselineState>({ status: 'idle' });
  const [baselineAttempt, setBaselineAttempt] = useState(0);
  const [indicators, setIndicators] = useState<string[]>([...DEFAULT_INSTRUMENT_INDICATORS]);
  const [vix, setVix] = useState<{
    status: MarketSeriesStatus;
    points?: readonly IndicatorPoint[];
    reason?: string;
  }>({ status: 'idle' });
  const [compare, setCompare] = useState(false);
  const [entities, setEntities] = useState<SelectedCompareEntity[]>([]);
  const [catalog, setCatalog] = useState<CatalogState>({ status: 'idle' });
  const [entitySeries, setEntitySeries] = useState<Record<string, EntitySeriesState>>({});
  const { preference, setPreference } = useBaselinePreference();

  const models = useMemo(
    () => runs
      .filter(run => run.market === evidence.market)
      .slice()
      .sort((left, right) => left.modelVersionId.localeCompare(right.modelVersionId)),
    [runs, evidence.market],
  );
  const names = useMemo(() => new Map(models.map(run => [run.modelVersionId, run.title])), [models]);
  const labelFor = useCallback((id: string) => names.get(id) ?? id, [names]);
  const allEvents = useMemo(() => boundSecurityEvents(evidence, runs), [evidence, runs]);
  const events = useMemo(() => allEvents.filter(event => !hidden.includes(event.model_id)), [allEvents, hidden]);
  const bars = useMemo(() => securityBarsForPeriod(evidence.bars, range), [evidence, range]);
  const markers = useMemo(() => securityMarkers(bars, events), [bars, events]);
  const allMarkers = useMemo(() => securityMarkers(evidence.bars, events), [evidence, events]);
  const visibleEvents = useMemo(() => markers.flatMap(marker => marker.events), [markers]);
  const summary = useMemo(() => visibleCloseSummary(bars), [bars]);
  const first = bars[0];
  const last = bars[bars.length - 1];
  const outsideCoverage = useMemo(() => unmatchedMarkerEvents(evidence.bars, events).length, [evidence, events]);
  const skippedMarkers = allMarkers.length - markers.length;
  const skippedEvents = events.length - visibleEvents.length;
  const rows = [...(completeLedger ? events : visibleEvents)].sort(
    (left, right) => right.time.localeCompare(left.time) || left.model_id.localeCompare(right.model_id),
  );
  const activeSelection = selected.filter(event => visibleEvents.includes(event));
  const excludedModels = models.filter(run => !evidence.bindings.some(binding => binding.model_version_id === run.modelVersionId
    && binding.run_id === run.runId && binding.bundle_id === run.bundleId));

  const baselineIdentity = marketBaseline(evidence.market);
  const baselineIsSelf = isMarketBaselineInstrument(evidence.market, evidence.symbol);
  const baselineSource = useMemo<BaselineOptionSource>(
    () => ({ view: 'security', market: evidence.market, isSelf: baselineIsSelf }),
    [evidence.market, baselineIsSelf],
  );
  const baselineOptions = useMemo(() => baselineOptionsFor(baselineSource), [baselineSource]);
  const activeKind: BaselineKind = kind
    ?? defaultBaselineKindFor(baselineSource, baselineOptions, preference[evidence.market]);
  const changeBaseline = (next: BaselineKind) => {
    setKind(next);
    setPreference(evidence.market, next);
  };

  const modelColorList = useMemo(
    () => modelColorAssignments(models.map(run => run.modelVersionId)),
    [models],
  );
  const modelColorIndex = useMemo(() => modelColorIndexMap(modelColorList), [modelColorList]);
  const colorFor = useCallback(
    (modelId: string) => modelColorFor(modelId, modelColorList),
    [modelColorList],
  );
  const selectedDetail = useMemo(
    () => securityMarkerDetail(activeSelection, { labelFor, colorFor }),
    [activeSelection, labelFor, colorFor],
  );
  const sideKeyVisible = visibleEvents.length > 0;
  const modelLegend = modelColorList.map(assignment => ({
    modelId: assignment.modelId,
    label: names.get(assignment.modelId) ?? assignment.modelId,
    color: assignment.color,
    count: visibleEvents.filter(event => event.model_id === assignment.modelId).length,
    visible: !hidden.includes(assignment.modelId),
    onToggle: () => setHidden(values => values.includes(assignment.modelId)
      ? values.filter(id => id !== assignment.modelId)
      : [...values, assignment.modelId]),
  }));

  const indicatorOptions = useMemo(() => {
    const instrumentOptions = instrumentIndicatorOptions().map(option => ({ ...option, available: true }));
    const marketOptions = marketIndicatorOptions(evidence.market).map(option => ({
      ...option,
      available: vix.status === 'ready',
      ...(vix.status === 'unavailable' && vix.reason ? { reason: vix.reason } : {}),
    }));
    return [...instrumentOptions, ...marketOptions];
  }, [evidence.market, vix]);

  const instrumentOverlays = useMemo(
    () => buildInstrumentIndicatorOverlays({
      market: evidence.market,
      bars: evidence.bars,
      visibleBars: bars,
      enabled: indicators,
    }),
    [evidence.bars, evidence.market, bars, indicators],
  );
  const marketOverlays = useMemo(
    () => buildMarketIndicatorOverlays({
      market: evidence.market,
      status: vix.status,
      series: vix.status === 'ready' ? vix.points : undefined,
      unavailableReason: vix.reason,
      visibleBars: bars,
      enabled: indicators,
    }),
    [evidence.market, vix, bars, indicators],
  );
  const indicatorOverlays = useMemo(
    () => [...instrumentOverlays.overlays, ...marketOverlays.overlays],
    [instrumentOverlays.overlays, marketOverlays.overlays],
  );
  const indicatorLegend = useMemo(
    () => [...instrumentOverlays.legend, ...marketOverlays.legend],
    [instrumentOverlays.legend, marketOverlays.legend],
  );
  const unavailableIndicators = useMemo(
    () => [...instrumentOverlays.unavailable, ...marketOverlays.unavailable],
    [instrumentOverlays.unavailable, marketOverlays.unavailable],
  );
  const marketIndicatorNote = evidence.market === 'us' && vix.status === 'unavailable'
    ? `VIX unavailable. ${vix.reason ?? 'The governed US VIX series has not been published.'} No substitute series is shown.`
    : undefined;
  const toggleIndicator = (id: string) => setIndicators(current => current.includes(id)
    ? current.filter(value => value !== id)
    : [...current, id]);

  useEffect(() => {
    if (activeKind !== 'market' || baselineIsSelf) return;
    let active = true;
    setBaseline(current => current.status === 'ready' ? current : { status: 'loading' });
    void loadMarketBaseline(evidence.market, evidence.cutoff)
      .then(result => { if (active) setBaseline({ status: 'ready', evidence: result }); })
      .catch(error => {
        if (active) setBaseline({ status: 'error', error: error instanceof Error ? error.message : String(error) });
      });
    return () => { active = false; };
  }, [activeKind, baselineIsSelf, evidence.market, evidence.cutoff, baselineAttempt]);

  /**
   * The governed VIX market series belongs to the US market only. The data
   * plane is currently withdrawn, so the read resolves to `unavailable` and the
   * UI states the reason; nothing is substituted, interpolated or fetched from
   * another provider. A CN chart never requests it.
   */
  useEffect(() => {
    if (evidence.market !== 'us') {
      setVix({ status: 'unavailable', reason: 'VIX is a US market indicator; CN charts never offer a cross-market overlay.' });
      return;
    }
    let active = true;
    setVix({ status: 'loading' });
    void readMarketEvidence('us', 'VIX')
      .then(vixEvidence => {
        if (!active) return;
        setVix({
          status: 'ready',
          points: vixEvidence.bars.map(bar => ({ time: bar.time, value: bar.close })),
        });
      })
      .catch(error => {
        if (!active) return;
        setVix({
          status: 'unavailable',
          reason: error instanceof Error ? error.message : String(error),
        });
      });
    return () => { active = false; };
  }, [evidence.market]);

  const baselineSeries = useMemo(() => {
    if (activeKind !== 'market' || baseline.status !== 'ready') return null;
    return indexedBaselineSeries(bars, baseline.evidence.bars);
  }, [activeKind, baseline, bars]);

  /** Same-market catalog for the comparison picker. Never reads another market. */
  useEffect(() => {
    let active = true;
    setCatalog({ status: 'loading' });
    void loadSecurityCatalog(evidence.market)
      .then(result => { if (active) setCatalog({ status: 'ready', symbols: result.symbols }); })
      .catch(error => {
        if (active) {
          setCatalog({ status: 'error', reason: error instanceof Error ? error.message : String(error) });
        }
      });
    return () => { active = false; };
  }, [evidence.market]);

  type CompareOptionRecord = { option: CompareEntityOption; run?: GovernedRunSummary; symbol?: string };
  const compareOptionRecords = useMemo<CompareOptionRecord[]>(() => {
    const modelOptions: CompareOptionRecord[] = models.map(run => ({
      option: {
        id: modelEntityId(evidence.market, run.modelVersionId),
        kind: 'model',
        label: run.title,
        detail: `${run.modelVersionId} · formal NAV`,
        available: true,
      },
      run,
    }));
    if (catalog.status === 'ready') {
      const byId = new Map(catalog.symbols.map(symbol => [instrumentEntityId(evidence.market, symbol.symbol), symbol]));
      return [
        ...modelOptions,
        ...instrumentEntityOptions(evidence.market, catalog.symbols, evidence.symbol).map(option => ({
          option,
          symbol: byId.get(option.id)?.symbol,
        })),
      ];
    }
    if (catalog.status === 'error') {
      modelOptions.push({
        option: {
          id: 'catalog:unavailable',
          kind: 'instrument',
          label: 'Same-market instruments',
          detail: 'Market evidence catalog',
          available: false,
          reason: `Instrument catalog unavailable. ${catalog.reason} No substitute series is offered.`,
        },
      });
    }
    return modelOptions;
  }, [models, evidence.market, evidence.symbol, catalog]);
  const compareOptions = useMemo(
    () => compareOptionRecords.map(record => record.option),
    [compareOptionRecords],
  );

  const toggleCompareEntity = useCallback((id: string) => {
    setEntities(current => {
      if (current.some(entity => entity.id === id)) return current.filter(entity => entity.id !== id);
      if (current.length >= MAX_COMPARE_OVERLAYS) return current;
      const record = compareOptionRecords.find(candidate => candidate.option.id === id);
      if (!record || !record.option.available) return current;
      if (record.option.kind === 'instrument' && !record.symbol) return current;
      const colorSlot = record.option.kind === 'instrument'
        ? firstFreeEntitySlot(current.flatMap(entity => (
          typeof entity.colorSlot === 'number' ? [entity.colorSlot] : []
        ))) ?? undefined
        : undefined;
      return [...current, {
        id,
        kind: record.option.kind,
        label: record.option.label,
        ...(record.symbol ? { symbol: record.symbol } : {}),
        ...(record.run ? { run: record.run } : {}),
        ...(colorSlot !== undefined ? { colorSlot } : {}),
      }];
    });
  }, [compareOptionRecords]);

  /**
   * Load each selected entity's own observed series. Models read the compact
   * verified `nav.json` projection; instruments read the same-market evidence
   * catalog. Nothing is fabricated when a read fails.
   */
  useEffect(() => {
    if (!compare) return;
    const ids = new Set(entities.map(entity => entity.id));
    setEntitySeries(previous => {
      const next: Record<string, EntitySeriesState> = {};
      for (const entity of entities) next[entity.id] = previous[entity.id] ?? { status: 'loading' };
      return next;
    });
    let active = true;
    for (const entity of entities) {
      const settle = (state: EntitySeriesState) => {
        if (!active || !ids.has(entity.id)) return;
        setEntitySeries(previous => ({ ...previous, [entity.id]: state }));
      };
      if (entity.kind === 'model' && entity.run) {
        void loadFormalNav(entity.run)
          .then(series => settle({ status: 'ready', points: navFromReport(series.rows) }))
          .catch(error => settle({
            status: 'unavailable',
            reason: error instanceof Error ? error.message : String(error),
          }));
      } else if (entity.symbol) {
        void readMarketEvidence(evidence.market, entity.symbol)
          .then(series => settle({ status: 'ready', points: marketNavFromBars(series.bars) }))
          .catch(error => settle({
            status: 'unavailable',
            reason: error instanceof Error ? error.message : String(error),
          }));
      }
    }
    return () => { active = false; };
  }, [compare, entities, evidence.market]);

  /** Deduplicate the governed baseline against an identical instrument overlay. */
  useEffect(() => {
    if (!compare || activeKind !== 'market' || baselineIsSelf) return;
    const baselineEntity = instrumentEntityId(evidence.market, baselineIdentity.symbol);
    setEntities(current => current.some(entity => entity.id === baselineEntity)
      ? current.filter(entity => entity.id !== baselineEntity)
      : current);
  }, [compare, activeKind, baselineIsSelf, evidence.market, baselineIdentity.symbol]);

  const displayedIdentities = useMemo(() => {
    const map = new Map<string, string>();
    map.set(
      instrumentEntityId(evidence.market, evidence.symbol),
      'This is the chart’s own instrument and is already indexed.',
    );
    if (activeKind === 'market' && !baselineIsSelf) {
      map.set(
        instrumentEntityId(evidence.market, baselineIdentity.symbol),
        `Already displayed as the ${baselineIdentity.label} baseline.`,
      );
    }
    return map;
  }, [evidence.market, evidence.symbol, activeKind, baselineIsSelf, baselineIdentity.symbol, baselineIdentity.label]);

  /**
   * One global exact common window across the base instrument, the active
   * baseline and every ready overlay. An overlay with fewer than two exact
   * common dates is reported unavailable and excluded, never rebased alone.
   */
  const compareModel = useMemo(() => {
    if (!compare) return null;
    const baseInput: EntitySeriesInput = {
      id: BASE_ENTITY_ID,
      label: evidence.symbol,
      points: marketNavFromBars(bars),
    };
    const baselineInput: EntitySeriesInput | null = activeKind === 'market'
      && baseline.status === 'ready' && !baselineIsSelf
      ? {
        id: BASELINE_ENTITY_ID,
        label: baselineIdentity.label,
        points: marketNavFromBars(baseline.evidence.bars),
      }
      : null;
    const accepted: EntitySeriesInput[] = baselineInput ? [baseInput, baselineInput] : [baseInput];
    const rejected = new Map<string, string>();
    for (const entity of entities) {
      const state = entitySeries[entity.id];
      if (!state || state.status === 'loading') continue;
      if (state.status === 'unavailable') {
        rejected.set(entity.id, state.reason);
        continue;
      }
      const candidate = { id: entity.id, label: entity.label, points: state.points };
      if (commonExactDates([...accepted, candidate]).length >= 2) {
        accepted.push(candidate);
      } else {
        rejected.set(entity.id, 'No exact common dates with the other displayed series in this range.');
      }
    }
    return {
      window: rebaseEntityWindow(accepted),
      baseInput,
      baselineInput,
      rejected,
    };
  }, [
    compare, bars, evidence.symbol, activeKind, baseline, baselineIsSelf,
    baselineIdentity.label, entities, entitySeries,
  ]);

  const compareOverlays = useMemo<SecurityChartOverlay[]>(() => {
    if (!compare || !compareModel?.window) return [];
    return compareModel.window.series.map(series => {
      const entity = entities.find(candidate => candidate.id === series.id);
      let colorRole: OverlayColorRole = 'primary';
      let lineStyle: 'solid' | 'dashed' = 'solid';
      if (series.id === BASELINE_ENTITY_ID) {
        colorRole = 'baseline';
        lineStyle = 'dashed';
      } else if (entity?.kind === 'model') {
        const index = modelColorIndex.get(entity.run?.modelVersionId ?? '') ?? 0;
        colorRole = `model-${Math.min(index, 4) + 1}` as OverlayColorRole;
      } else if (entity?.kind === 'instrument') {
        colorRole = `entity-${(entity.colorSlot ?? 0) + 1}` as OverlayColorRole;
        // Compared instruments stay dashed; model overlays stay solid, so the
        // two families never rely on hue alone.
        lineStyle = 'dashed';
      }
      return {
        id: series.id,
        label: series.label,
        kind: 'line',
        pane: 'price',
        data: series.points.map(point => ({ time: point.date, value: point.value })),
        colorRole,
        lineWidth: 2,
        lineStyle,
        priceFormat: INDEXED_OVERLAY_FORMAT,
      };
    });
  }, [compare, compareModel, entities, modelColorIndex]);

  const compareLegendItems = useMemo<CompareLegendItem[]>(() => {
    if (!compare) return [];
    const items: CompareLegendItem[] = [{
      id: BASE_ENTITY_ID,
      label: `${evidence.symbol} · indexed price`,
      colorRole: 'primary',
      dashed: false,
      kind: 'instrument',
    }];
    if (compareModel?.baselineInput) {
      items.push({
        id: BASELINE_ENTITY_ID,
        label: baselineIdentity.label,
        detail: 'indexed price',
        colorRole: 'baseline',
        dashed: true,
        kind: 'baseline',
      });
    }
    for (const entity of entities) {
      const state = entitySeries[entity.id];
      let colorRole: OverlayColorRole;
      let dashed = entity.kind === 'instrument';
      if (entity.kind === 'model') {
        const index = modelColorIndex.get(entity.run?.modelVersionId ?? '') ?? 0;
        colorRole = `model-${Math.min(index, 4) + 1}` as OverlayColorRole;
        dashed = false;
      } else {
        colorRole = `entity-${(entity.colorSlot ?? 0) + 1}` as OverlayColorRole;
      }
      const reason = state?.status === 'unavailable'
        ? state.reason
        : compareModel?.rejected.get(entity.id);
      items.push({
        id: entity.id,
        label: entity.label,
        detail: entity.kind === 'model' ? 'model NAV' : 'indexed price',
        colorRole,
        dashed,
        kind: entity.kind,
        loading: !state || state.status === 'loading',
        onRemove: () => setEntities(current => current.filter(candidate => candidate.id !== entity.id)),
        ...(reason ? { unavailableReason: reason } : {}),
      });
    }
    return items;
  }, [compare, compareModel, entities, entitySeries, evidence.symbol, baselineIdentity.label, modelColorIndex]);

  const compareBasis = compare
    ? compareModel?.window
      ? `Indexed to 100 at the exact common start ${compareModel.window.startDate} – ${compareModel.window.endDate} · ${compareModel.window.series.length} series · ${compareModel.window.observations} exact observations · not total return`
      : 'Exact common dates only; no overlapping window across the displayed entities in this range.'
    : null;

  const mode: SecurityChartMode = compare ? 'compare' : activeKind === 'market' ? 'baseline' : 'price';
  const chartBaselineSeries = compare ? null : baselineSeries;
  const chartOverlays = compare ? compareOverlays : indicatorOverlays;

  let emptyMessage = 'No observed price sessions fall inside this selected range.';
  if (compare) {
    if (entities.length > 0 && compareLegendItems.some(item => item.loading)) {
      emptyMessage = 'Loading the selected comparison entities…';
    } else if (!compareModel?.window) {
      emptyMessage = 'No exact common dates across the displayed comparison entities in this range.';
    }
  } else if (mode === 'baseline') {
    if (baseline.status === 'loading' || baseline.status === 'idle') {
      emptyMessage = `Loading ${baselineIdentity.label} baseline evidence…`;
    } else if (baseline.status === 'error') {
      emptyMessage = `${baselineIdentity.label} baseline evidence is unavailable in this mode. Price history remains readable in Price mode.`;
    } else if (!baselineSeries) {
      emptyMessage = `No exact-date overlap between ${evidence.symbol} and ${baselineIdentity.label} in this range.`;
    }
  }
  const fitKey = compare
    ? `${range}:compare:${compareModel?.window?.startDate ?? 'pending'}`
    : `${range}:${mode}:${baselineSeries?.startDate ?? 'pending'}`;
  const change = summary.oneWeekChange;
  const markerPressed = (marker: SecurityMarker) => marker.events.every(event => activeSelection.includes(event));
  const entityKind = entityKindFromRoles(evidence.roles);
  const showRoleContext = entityKind === 'index' || entityKind === 'reference';
  const showModelLedger = entityKind === 'instrument' || allEvents.length > 0;

  return (
    <EntityWorkspace
      identity={{
        kind: entityKind,
        name: evidence.name === evidence.symbol ? evidence.name : `${evidence.name} · ${evidence.symbol}`,
        entityId: `${evidence.market}:${evidence.symbol}`,
        market: evidence.market,
        asOf: summary.asOf,
        evidenceCutoff: evidence.cutoff,
        staleDays: staleDays(evidence.cutoff, summary.asOf),
        benchmark: evidence.benchmark ?? baselineIdentity.symbol,
        role: formatEntityRoles(evidence.roles),
      }}
      back={back ?? { to: '/app', label: 'Overview' }}
      description="Exact governed price sessions and historical formal model events."
      metrics={(
        <dl className="grid shrink-0 grid-cols-2 gap-x-5 gap-y-2 sm:grid-cols-4">
          <div>
            <dt className="ae-metric-label">Last close</dt>
            <dd data-testid="security-last-close" className="mt-1 font-mono text-lg font-semibold tabular-nums">
              {formatSecurityPrice(summary.lastClose)}
            </dd>
          </div>
          <div>
            <dt className="ae-metric-label">1W change</dt>
            <dd
              data-testid="security-one-week-change"
              title={summary.oneWeekReason ?? undefined}
              aria-label={summary.oneWeekReason ? `One-week change unavailable: ${summary.oneWeekReason}` : undefined}
              className={cn(
                'mt-1 font-mono text-lg font-semibold tabular-nums',
                change !== null && change > 0 && 'text-positive',
                change !== null && change < 0 && 'text-negative',
              )}
            >
              {formatSecurityPercent(change)}
            </dd>
            {summary.oneWeekReason && (
              <p className="mt-0.5 max-w-[16rem] text-[10px] leading-4 text-muted-foreground">{summary.oneWeekReason}</p>
            )}
          </div>
        </dl>
      )}
    >
      <EntityChartPanel
        testId="security-history-chart"
        title="Price and model events"
        ariaLabel="Price and model events"
        dataMarkerCount={markers.length}
        bodyClassName="p-4 sm:p-5"
        description={(
          <p data-testid="security-visible-dates" className="mt-1 text-[11px] leading-4 text-muted-foreground">
            {first?.time ?? '—'} – {last?.time ?? '—'} · {bars.length} observed sessions · {markers.length} marker clusters
          </p>
        )}
        controls={(
          <>
            <div role="group" aria-label="Security chart range" className="inline-flex rounded-lg border bg-muted/30 p-0.5">
              {PERIODS.map(period => (
                <button
                  key={period.key}
                  type="button"
                  aria-pressed={range === period.key}
                  className={cn(
                    'research-touch min-h-8 rounded-md px-2.5 text-[11px] font-medium transition-colors',
                    range === period.key
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:bg-muted',
                  )}
                  onClick={() => {
                    const next = new URLSearchParams(params);
                    next.set('range', period.key);
                    setParams(next, { replace: true });
                  }}
                >
                  {period.label}
                </button>
              ))}
            </div>
            <button
              type="button"
              data-testid="security-compare-toggle"
              aria-pressed={compare}
              onClick={() => setCompare(value => !value)}
              className={cn(
                'research-touch min-h-8 rounded-md border px-2.5 text-[11px] font-medium transition-colors',
                compare
                  ? 'border-primary bg-primary text-primary-foreground'
                  : 'bg-background text-muted-foreground hover:bg-muted',
              )}
            >
              Compare
            </button>
            {compare && (
              <CompareControl
                options={compareOptions}
                selected={entities}
                onToggle={toggleCompareEntity}
                marketLabel={evidence.market === 'us' ? 'US' : 'CN'}
                displayed={displayedIdentities}
                max={MAX_COMPARE_OVERLAYS}
              />
            )}
            <BaselineControl
              options={baselineOptions}
              value={activeKind}
              onChange={changeBaseline}
              marketLabel={evidence.market === 'us' ? 'US' : 'CN'}
            />
            <IndicatorControl
              options={indicatorOptions}
              selected={indicators}
              onToggle={toggleIndicator}
              marketLabel={evidence.market === 'us' ? 'US' : 'CN'}
            />
          </>
        )}
      >

      {compare && (
        <p role="note" data-testid="compare-scope" className="mt-2 text-[11px] leading-4 text-muted-foreground">
          Same-market comparison only: models use the verified formal NAV projection and instruments use this
          market's evidence catalog. Another market's entity is never offered or read. Up to {MAX_COMPARE_OVERLAYS}
          overlays share one exact common start; price indicators and event markers are hidden while comparing.
        </p>
      )}

      {baselineIsSelf && (
        <p
          role="note"
          data-testid="security-baseline-disabled"
          className="mt-2 rounded-md border border-dashed p-2 text-[11px] leading-5 text-muted-foreground"
        >
          No self-comparison baseline: {evidence.symbol} is the governed {evidence.market.toUpperCase()} market
          baseline ({baselineIdentity.label}). Price history remains readable.
        </p>
      )}

      <p data-testid="security-baseline-scope" className="mt-2 text-[11px] leading-4 text-muted-foreground">
        Only the governed {evidence.market.toUpperCase()} market index is selectable for one instrument. A model's
        declared benchmark is not treated as instrument evidence, so no separate model-benchmark series is fabricated
        as a baseline.
      </p>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-y py-2 text-[11px] leading-4 text-muted-foreground">
        <p data-testid="security-chart-baseline">
          Baseline: <span className="font-medium text-foreground">{baselineIdentity.label}</span> · governed{' '}
          {evidence.market.toUpperCase()} market index
        </p>
        <p data-testid="security-chart-basis">
          {compare
            ? compareBasis
            : mode === 'baseline'
              ? baselineSeries
                ? `Open-to-open price return, indexed to 100 at ${baselineSeries.startDate} – ${baselineSeries.endDate} · not total return`
                : `Open-to-open price return, indexed to 100 at the first exact common date · ${MARKET_BASELINE_RETURN_DISCLOSURE}`
              : 'Raw OHLC price candles · not split or dividend adjusted'}
        </p>
      </div>

      {compare && <CompareLegend items={compareLegendItems} />}

      {!compare && mode === 'baseline' && baselineSeries && (
        <ul aria-label="Chart series" className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
          <li className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="inline-block h-0.5 w-4 rounded-full" style={{ backgroundColor: 'hsl(var(--chart-1))' }} />
            {evidence.symbol} · indexed price
          </li>
          <li className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="inline-block w-4 border-t-2 border-dashed" style={{ borderColor: 'hsl(var(--chart-2))' }} />
            {baselineIdentity.label} · indexed price
          </li>
          <li>{BASELINE_EXACT_DATE_DISCLOSURE} {MARKET_BASELINE_RETURN_DISCLOSURE}</li>
        </ul>
      )}

      {(mode === 'baseline' || (compare && activeKind === 'market')) && baseline.status === 'error' && (
        <div role="alert" className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-warning/40 bg-warning/5 p-3 text-xs">
          <p className="max-w-2xl">
            <strong>{baselineIdentity.label} baseline unavailable.</strong> {baseline.error} Price history remains
            readable in Price mode; the ledger below is unaffected.
          </p>
          <button
            type="button"
            className="research-touch min-h-9 rounded border px-3 text-xs font-medium"
            onClick={() => setBaselineAttempt(value => value + 1)}
          >
            Retry baseline
          </button>
        </div>
      )}

      {!compare && (
        <MarkerLegend
          showSides={sideKeyVisible}
          models={modelLegend}
          sideAriaLabel="Marker direction key"
          modelAriaLabel="Model marker key"
          className="mt-3"
        />
      )}

      <SecurityLightweightChart
        bars={bars}
        markers={markers}
        mode={mode}
        baselineSeries={chartBaselineSeries}
        fitKey={fitKey}
        onSelect={setSelected}
        emptyMessage={emptyMessage}
        loading={compare
          ? entities.length > 0 && compareLegendItems.some(item => item.loading)
          : mode === 'baseline' && (baseline.status === 'loading' || baseline.status === 'idle')}
        modelColorIndex={modelColorIndex}
        overlays={chartOverlays}
      />

      {!compare && (
        <IndicatorNotes
          legend={indicatorLegend}
          unavailable={unavailableIndicators}
          marketNote={marketIndicatorNote}
        />
      )}

      {skippedMarkers > 0 && (
        <p role="note" data-testid="security-skipped-markers" className="mt-2 text-[11px] leading-4 text-muted-foreground">
          {skippedMarkers} marker cluster{skippedMarkers === 1 ? '' : 's'} covering {skippedEvents} model event
          {skippedEvents === 1 ? '' : 's'} fall outside the visible range and are not plotted
          {outsideCoverage > 0 ? `, including ${outsideCoverage} without a matching price session` : ''}. They remain
          in the historical ledger below.
        </p>
      )}
      {outsideCoverage > 0 && (
        <p role="note" data-testid="security-unmatched-events" className="mt-2 text-[11px] leading-4 text-muted-foreground">
          {outsideCoverage} model event{outsideCoverage === 1 ? '' : 's'} fall on a date without a published price
          session and are not plotted. They remain in the historical ledger below.
        </p>
      )}

      <div className="mt-3 overflow-hidden rounded-lg border">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
          <h3 className="text-xs font-semibold">Event markers in range</h3>
          <span className="text-[10px] text-muted-foreground">
            {markers.length} marker clusters · {visibleEvents.length} events
          </span>
        </div>
        {markers.length > 0 ? (
          <ul aria-label="Event markers in range" className="max-h-64 divide-y overflow-y-auto">
            {markers.map(marker => {
              const key = `${marker.time}:${marker.positive ? 'buy' : 'sell'}`;
              return (
                <li key={key}>
                  <button
                    type="button"
                    data-testid="security-trade-marker"
                    aria-pressed={markerPressed(marker)}
                    onClick={() => setSelected(marker.events)}
                    className={cn(
                      'research-touch flex w-full flex-wrap items-baseline gap-x-3 gap-y-0.5 px-3 py-2 text-left text-xs transition-colors hover:bg-muted/50',
                      markerPressed(marker) && 'bg-primary/5',
                    )}
                  >
                    <span className="font-mono text-[11px] tabular-nums">{marker.time}</span>
                    <span className={cn('text-[10px] font-semibold uppercase tracking-[0.08em]', marker.positive ? 'text-positive' : 'text-negative')}>
                      {marker.positive ? 'Buy / increase' : 'Sell / decrease'}
                    </span>
                    <span className="min-w-0 text-muted-foreground">
                      {marker.models.map(model => `${labelFor(model.modelId)} · ${model.events.map(event => formatEventAction(event.action)).join(', ')}`).join('; ')}
                    </span>
                    <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                      {marker.events.length} event{marker.events.length === 1 ? '' : 's'}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="px-3 py-4 text-xs text-muted-foreground">
            No historical model events fall on an observed price session in this range.
          </p>
        )}
      </div>

      {selectedDetail && (
        <MarkerDetailPanel
          detail={selectedDetail}
          testId="security-selected-event"
          ariaLabel="Selected model markers"
          role="status"
          live
          onClear={() => setSelected([])}
        />
      )}

      {excludedModels.length > 0 && (
        <p role="status" className="mt-3 rounded-lg border border-warning/30 p-3 text-sm">
          Model markers unavailable for {excludedModels.map(run => run.title).join(', ')}: price publication does
          not bind the current formal run. Price history remains readable.
        </p>
      )}
      <p className="mt-3 text-[11px] leading-4 text-muted-foreground">
        B = buy / increase · S = sell / decrease. Markers are colored by model identity and shaped by direction.
        {' '}{MARKER_DETAIL_DISCLOSURE}
      </p>
    </EntityChartPanel>

      <EntityEvidenceSections label="Instrument evidence">
        {showRoleContext && <EntityRoleContext evidence={evidence} />}

        {showModelLedger && (
          <section className="research-surface p-4 sm:p-5" aria-label="Historical model event ledger">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <h2 className="ae-section-title">Historical model event ledger</h2>
              <label className="research-touch flex min-h-9 items-center gap-2 text-sm">
                <input
                  type="checkbox" className="h-4 w-4 accent-primary"
                  checked={completeLedger}
                  onChange={event => { setCompleteLedger(event.target.checked); setLimit(100); }}
                />
                Show complete ledger
              </label>
            </div>
            <p className="mb-3 text-[11px] leading-4 text-muted-foreground">
              {completeLedger
                ? 'Full retained ledger, including events outside price coverage.'
                : 'Selected chart interval.'} Weight changes describe historical model targets. The chart price is a
              governed reference, not the event execution price.
            </p>
            <div className="overflow-x-auto">
              <table className="ae-data-table min-w-full text-left">
                <thead>
                  <tr>
                    {['Ledger date', 'Model', 'Action', 'Previous → target', 'Reason / evidence'].map(label => (
                      <th key={label} className="whitespace-nowrap">{label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, limit).map((event, index) => (
                    <tr key={`${event.model_id}:${event.time}:${index}`} className="align-top">
                      <td className="whitespace-nowrap font-mono text-[11px]">{event.time}</td>
                      <td className="whitespace-nowrap">
                        <Link className="text-primary underline" to={`/strategies/${encodeURIComponent(event.model_id)}`}>
                          {labelFor(event.model_id)}
                        </Link>
                      </td>
                      <td className="font-semibold" title={event.action}>{formatEventAction(event.action)}</td>
                      <td className="whitespace-nowrap font-mono text-[11px]">
                        {weight(event.previous_weight)} → {weight(event.target_weight)}
                      </td>
                      <td className="max-w-sm min-w-56 break-words">
                        <span title={event.reason || undefined}>{humanizeEventReason(event.reason)}</span>
                        <span className="mt-1 block text-[10px] text-muted-foreground">{event.run_id}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!rows.length && <p className="py-6 text-sm text-muted-foreground">No retained model events for this instrument and selection.</p>}
            {rows.length > limit && (
              <button
                type="button"
                className="mt-4 min-h-9 rounded border px-4 text-sm"
                onClick={() => setLimit(value => value + 100)}
              >
                Show more events ({limit} of {rows.length})
              </button>
            )}
          </section>
        )}

        <details className="research-surface p-4 text-xs text-muted-foreground">
          <summary className="cursor-pointer font-medium">Price and event provenance</summary>
          <p className="mt-3 break-all">Published price source SHA-256: {evidence.source_sha256}</p>
          <p className="mt-2 break-all">Provider manifest SHA-256: {evidence.provider_manifest_sha256}</p>
          <p className="mt-2">
            OHLCV is retained governed provider evidence. Price mode plots raw OHLC and is not adjusted for splits or
            dividends. vs baseline aligns exact session dates open-to-open and indexes both series to 100 at the first
            common date; that is a price return, not total return. Adjustment and execution semantics remain those of
            the source contracts; price return is not strategy return. Only exact active formal model/run/bundle
            identities qualify for markers.
          </p>
        </details>
      </EntityEvidenceSections>
    </EntityWorkspace>
  );
}

export function SecurityDetailPage() {
  const { market, symbol } = useParams();
  const [params] = useSearchParams();
  const workspace = useOutletContext<RunWorkspaceContext>();
  const key = `${market}:${symbol}`;
  const [state, setState] = useState<{ key: string; evidence?: SecurityEvidence; error?: string } | null>(null);
  const [retry, setRetry] = useState(0);
  const current = state?.key === key ? state : null;
  const parent = workspace.runs.find(run => run.modelVersionId === params.get('model'));
  useEffect(() => {
    let active = true;
    if (market !== 'us' && market !== 'cn' || !symbol) return;
    void loadSecurityEvidence(market, symbol).then(evidence => { if (active) setState({ key, evidence }); })
      .catch(error => { if (active) setState({ key, error: error instanceof Error ? error.message : String(error) }); });
    return () => { active = false; };
  }, [key, market, retry, symbol]);
  const valid = market === 'us' || market === 'cn';
  const back: EntityBackLink = {
    to: parent ? `/strategies/${encodeURIComponent(parent.modelVersionId)}` : '/app',
    label: parent ? parent.title : 'Overview',
  };
  if (current?.evidence) {
    return <SecurityHistory
      key={`${key}:${current.evidence.source_sha256}`}
      evidence={current.evidence}
      runs={workspace.runs}
      back={back}
    />;
  }
  return <div className="research-page space-y-5 pb-16">
    <Link to={back.to} className="inline-flex min-h-10 items-center gap-2 text-sm text-primary">
      <ArrowLeft className="h-4 w-4" />
      {back.label}
    </Link>
    {!valid || current?.error ? (
      <div className="research-surface p-6" role="alert">
        <h1 className="text-lg font-semibold">Security history unavailable</h1>
        <p className="mt-2 text-sm text-muted-foreground">{current?.error || 'Unsupported market.'}</p>
        {valid && (
          <button
            type="button"
            className="mt-4 min-h-10 rounded border px-4"
            onClick={() => { setState(null); setRetry(value => value + 1); }}
          >
            Retry price evidence
          </button>
        )}
      </div>
    ) : (
      <p className="flex items-center gap-2 p-6 text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />Loading verified price history…
      </p>
    )}
  </div>;
}
