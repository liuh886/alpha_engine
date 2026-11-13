import { useMemo, useState } from 'react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { alignNavSeries, type NavMarker, type NavPoint } from '@/lib/nav-series';
import {
  isPerformanceDate,
  type HorizonCoverage,
  type HorizonCoverageReason,
} from '@/lib/performancePeriods';
import { cn } from '@/lib/utils';

export interface NavChartSeries {
  key: string;
  label: string;
  nav: NavPoint[];
  emphasis?: 'primary' | 'baseline';
  /** Allowed foundation token, for example `chart-2` or `positive`. */
  colorToken?: string;
}

export interface NavChartRow {
  date: string;
  [key: string]: string | number;
}

export interface NavChartModel {
  rows: NavChartRow[];
  startDate: string | null;
  endDate: string | null;
}

export interface NavChartProps {
  series: NavChartSeries[];
  markers?: NavMarker[];
  height?: number;
  periodLabel: string;
  coverage?: HorizonCoverage;
  emptyReason?: string;
  onMarkerSelect?: (marker: NavMarker) => void;
  /** Date of the marker currently announced by the surrounding panel. */
  selectedMarkerDate?: string | null;
  /** Optional spoken summary of window and headline returns for the figure. */
  summaryLabel?: string;
}

const INDEX_FORMAT = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const AXIS_INDEX_FORMAT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const PERCENT_FORMAT = new Intl.NumberFormat('en-US', {
  style: 'percent',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: 'exceptZero',
});
const DATE_FORMAT = new Intl.DateTimeFormat('en-US', {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  timeZone: 'UTC',
});
const AXIS_DATE_FORMAT = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  timeZone: 'UTC',
});

const BASELINE_TOKENS = ['chart-2', 'chart-3', 'chart-4', 'chart-5', 'chart-6'] as const;
const ALLOWED_TOKENS: ReadonlySet<string> = new Set<string>([
  'chart-1', 'chart-2', 'chart-3', 'chart-4', 'chart-5', 'chart-6',
  'primary', 'positive', 'negative', 'warning',
]);

const COVERAGE_REASON_TEXT: Record<HorizonCoverageReason, string> = {
  covered: 'The requested window is fully covered.',
  short_history: 'History starts after the requested window.',
  truncated_window: 'Retained history does not reach the requested start.',
  coarse_cadence: 'Observations are less frequent than the weekly horizon requires.',
  insufficient_observations: 'Too few observations fall inside this window.',
  invalid_dates: 'No valid observation dates are retained.',
};

function valuesByDate(nav: NavPoint[]): Map<string, number> {
  const values = new Map<string, number>();
  if (!Array.isArray(nav)) return values;
  for (const point of nav) {
    if (!point || !isPerformanceDate(point.date) || !Number.isFinite(point.value) || point.value <= 0) continue;
    values.set(point.date, point.value);
  }
  return values;
}

/**
 * Exact-date aligned chart rows, rebased to 100 at the first common
 * observation. No interpolation, snapping or synthetic dates are introduced.
 */
export function buildNavChartModel(series: NavChartSeries[]): NavChartModel {
  const active = Array.isArray(series)
    ? series.filter(candidate => candidate && typeof candidate.key === 'string' && candidate.key !== '')
    : [];
  if (active.length === 0) return { rows: [], startDate: null, endDate: null };

  const maps = active.map(candidate => valuesByDate(candidate.nav));
  let dates: string[];
  if (maps.length === 1) {
    dates = [...maps[0].keys()].sort();
  } else if (maps.length === 2) {
    dates = alignNavSeries(active[0].nav, active[1].nav).map(point => point.date);
  } else {
    dates = [...maps[0].keys()]
      .filter(date => maps.every(map => map.has(date)))
      .sort();
  }
  if (dates.length === 0) return { rows: [], startDate: null, endDate: null };

  const bases = maps.map(map => map.get(dates[0]) as number);
  const rows = dates.map(date => {
    const row: NavChartRow = { date };
    active.forEach((candidate, index) => {
      row[candidate.key] = ((maps[index].get(date) as number) / bases[index]) * 100;
    });
    return row;
  });

  return { rows, startDate: dates[0], endDate: dates[dates.length - 1] };
}

function colorFor(series: NavChartSeries, index: number, primaryIndex: number): string {
  if (series.colorToken && ALLOWED_TOKENS.has(series.colorToken)) return `hsl(var(--${series.colorToken}))`;
  if (index === primaryIndex) return 'hsl(var(--chart-1))';
  let rank = 0;
  for (let candidate = 0; candidate < index; candidate += 1) {
    if (candidate !== primaryIndex) rank += 1;
  }
  return `hsl(var(--${BASELINE_TOKENS[rank % BASELINE_TOKENS.length]}))`;
}

function formatChartDate(date: string): string {
  if (!isPerformanceDate(date)) return date;
  return DATE_FORMAT.format(new Date(`${date}T00:00:00Z`));
}

function formatAxisDate(date: string): string {
  if (!isPerformanceDate(date)) return date;
  return AXIS_DATE_FORMAT.format(new Date(`${date}T00:00:00Z`));
}

function markerSideLabel(side: NavMarker['side']): string {
  if (side === 'buy') return 'Buy';
  if (side === 'sell') return 'Sell';
  return 'Mixed';
}

function markerSummary(marker: NavMarker): string {
  const tradeLabel = marker.count === 1 ? 'trade' : 'trades';
  const parts = [`${markerSideLabel(marker.side)}, ${marker.count} ${tradeLabel}`, `date ${marker.date}`];
  if (marker.instruments.length > 0) parts.push(`instruments ${marker.instruments.join(', ')}`);
  if (marker.reasons.length > 0) parts.push(`reasons ${marker.reasons.join('; ')}`);
  if (marker.netWeightDelta !== null) parts.push(`net weight change ${PERCENT_FORMAT.format(marker.netWeightDelta)}`);
  return parts.join('; ');
}

const MARKER_KEY: ReadonlyArray<{ side: NavMarker['side']; label: string }> = [
  { side: 'buy', label: 'Buy / increase' },
  { side: 'sell', label: 'Sell / decrease' },
  { side: 'mixed', label: 'Buy and sell' },
];

function markerColor(side: NavMarker['side']): string {
  if (side === 'buy') return 'hsl(var(--positive))';
  if (side === 'sell') return 'hsl(var(--negative))';
  return 'hsl(var(--warning))';
}

/** Small static glyph for the legend; the chart uses the same geometry. */
export function MarkerGlyph({ side }: { side: NavMarker['side'] }) {
  const points = side === 'buy'
    ? '5,1 10,10 0,10'
    : side === 'sell'
      ? '0,0 10,0 5,9'
      : '5,0 10,5 5,10 0,5';
  return (
    <svg aria-hidden="true" viewBox="0 0 10 10" className="h-2.5 w-2.5" fill={markerColor(side)}>
      <polygon points={points} />
    </svg>
  );
}

interface ActivityMarkerShapeProps {
  cx?: number;
  cy?: number;
  side?: NavMarker['side'];
  onClick?: () => void;
}

/**
 * Side-coded activity marker anchored to the primary line: buys point up below
 * the line, sells point down above it, and a mixed date is a split diamond.
 * Shape and position carry identity, so color is never the only encoding.
 */
export function ActivityMarkerShape({ cx, cy, side = 'buy', onClick }: ActivityMarkerShapeProps) {
  if (typeof cx !== 'number' || typeof cy !== 'number' || !Number.isFinite(cx) || !Number.isFinite(cy)) return null;
  const color = markerColor(side);
  const stroke = 'hsl(var(--card))';
  return (
    <g
      data-testid="activity-marker-shape"
      data-side={side}
      onClick={onClick}
      style={onClick ? { cursor: 'pointer' } : undefined}
    >
      {side === 'mixed' ? (
        <>
          <path
            d={`M ${cx},${cy - 6} L ${cx + 6},${cy} L ${cx},${cy + 6} L ${cx - 6},${cy} Z`}
            fill={color}
            stroke={stroke}
            strokeWidth={1}
          />
          <path d={`M ${cx},${cy - 6} L ${cx},${cy + 6}`} stroke={stroke} strokeWidth={1.4} fill="none" />
        </>
      ) : side === 'buy' ? (
        <polygon
          points={`${cx},${cy + 3} ${cx - 5},${cy + 9} ${cx + 5},${cy + 9}`}
          fill={color}
          stroke={stroke}
          strokeWidth={1}
        />
      ) : (
        <polygon
          points={`${cx - 5},${cy - 9} ${cx + 5},${cy - 9} ${cx},${cy - 3}`}
          fill={color}
          stroke={stroke}
          strokeWidth={1}
        />
      )}
    </g>
  );
}

function coverageDisclosure(coverage: HorizonCoverage): string {
  const first = coverage.firstObservation ?? 'unavailable';
  const prefix = coverage.state === 'partial' ? 'Partial coverage' : 'Coverage unavailable';
  return `${prefix}: first observation ${first}. ${COVERAGE_REASON_TEXT[coverage.reason]}`;
}

export interface NavChartTooltipValue {
  dataKey?: string | number;
  name?: string | number;
  value?: number | string | null;
}

export interface NavChartTooltipProps {
  active?: boolean;
  payload?: NavChartTooltipValue[];
  label?: string | number;
  labels?: Record<string, string>;
  markers?: NavMarker[];
}

/** Chart tooltip with fixed en-US formatting and no rounding of retained data. */
export function NavChartTooltip({ active, payload, label, labels, markers }: NavChartTooltipProps) {
  if (!active || !payload || payload.length === 0 || label === undefined || label === null) return null;
  const date = String(label);
  const marker = markers?.find(candidate => candidate.date === date) ?? null;

  return (
    <div
      data-testid="nav-chart-tooltip"
      className="min-w-[190px] rounded-md border bg-popover p-2.5 text-[11px] text-popover-foreground shadow-card"
    >
      <p className="mb-1.5 flex flex-wrap items-center gap-1.5 border-b pb-1.5">
        <span data-testid="nav-chart-tooltip-date" className="rounded bg-primary/10 px-1.5 py-0.5 font-semibold tabular-nums text-primary">
          {formatChartDate(date)}
        </span>
        <span className="text-[9px] font-medium uppercase tracking-[0.08em] text-muted-foreground">Observation date</span>
      </p>
      <ul className="space-y-0.5">
        {payload.map(item => {
          const key = String(item.dataKey ?? item.name ?? '');
          const numeric = typeof item.value === 'number'
            ? item.value
            : item.value === null || item.value === undefined
              ? Number.NaN
              : Number(item.value);
          const value = Number.isFinite(numeric) ? numeric : null;
          return (
            <li key={key} className="flex items-baseline justify-between gap-3">
              <span className="min-w-0 truncate text-muted-foreground">{labels?.[key] ?? String(item.name ?? key)}</span>
              <span className="shrink-0 font-mono tabular-nums">
                {value === null ? '—' : `${INDEX_FORMAT.format(value)} · ${PERCENT_FORMAT.format(value / 100 - 1)}`}
              </span>
            </li>
          );
        })}
      </ul>
      {marker && (
        <div data-testid="nav-chart-tooltip-marker" className="mt-1.5 border-t pt-1.5">
          <p className="font-semibold">
            {markerSideLabel(marker.side)} · {marker.count} {marker.count === 1 ? 'trade' : 'trades'}
          </p>
          {marker.instruments.length > 0 && (
            <p className="text-muted-foreground">Instruments: {marker.instruments.join(', ')}</p>
          )}
          {marker.reasons.length > 0 && (
            <p className="text-muted-foreground">Reasons: {marker.reasons.join('; ')}</p>
          )}
          {marker.netWeightDelta !== null && (
            <p className="text-muted-foreground">Net weight change: {PERCENT_FORMAT.format(marker.netWeightDelta)}</p>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Same-market NAV comparison indexed to 100 at the first exact-date common
 * observation. Partial coverage and hidden markers are disclosed rather than
 * silently dropped.
 */
export function NavChart({
  series,
  markers = [],
  height = 320,
  periodLabel,
  coverage,
  emptyReason,
  onMarkerSelect,
  selectedMarkerDate = null,
  summaryLabel,
}: NavChartProps) {
  const model = useMemo(() => buildNavChartModel(series), [series]);
  const activeSeries = Array.isArray(series) ? series : [];
  const explicitPrimary = activeSeries.findIndex(candidate => candidate.emphasis === 'primary');
  const primaryIndex = explicitPrimary >= 0 ? explicitPrimary : 0;
  const primarySeries = activeSeries[primaryIndex] ?? null;
  const primaryKey = primarySeries?.key ?? null;
  const colors = activeSeries.map((candidate, index) => colorFor(candidate, index, primaryIndex));
  const labels = useMemo(
    () => Object.fromEntries(activeSeries.map(candidate => [candidate.key, candidate.label])) as Record<string, string>,
    [activeSeries],
  );
  const rowByDate = useMemo(() => new Map(model.rows.map(row => [row.date, row])), [model.rows]);
  const chartDates = useMemo(() => new Set(model.rows.map(row => row.date)), [model.rows]);
  const visibleMarkers = useMemo(
    () => (Array.isArray(markers) ? markers : []).filter(marker => chartDates.has(marker.date)),
    [chartDates, markers],
  );
  const hiddenMarkerCount = Math.max(0, (Array.isArray(markers) ? markers : []).length - visibleMarkers.length);
  const markerByDate = useMemo(
    () => new Map(visibleMarkers.map(marker => [marker.date, marker])),
    [visibleMarkers],
  );
  const [hoverValue, setHoverValue] = useState<number | null>(null);
  const hasData = model.rows.length >= 2 && primarySeries !== null;
  const resolvedHeight = Number.isFinite(height) && height > 0 ? height : 320;
  // Padded data-driven domain: a zero-based axis would spend most of the plot
  // on empty space when a retained series lives, for example, between 68 and
  // 120. The 100 reference line stays inside the domain.
  const yDomain = useMemo((): [number, number] => {
    let low = Infinity;
    let high = -Infinity;
    for (const row of model.rows) {
      for (const candidate of activeSeries) {
        const value = row[candidate.key];
        if (typeof value === 'number' && Number.isFinite(value)) {
          low = Math.min(low, value);
          high = Math.max(high, value);
        }
      }
    }
    if (!Number.isFinite(low) || !Number.isFinite(high)) return [0, 100];
    low = Math.min(low, 100);
    high = Math.max(high, 100);
    const pad = Math.max((high - low) * 0.08, 1.5);
    return [Math.floor(low - pad), Math.ceil(high + pad)];
  }, [activeSeries, model.rows]);
  const hiddenMarkerText = hiddenMarkerCount === 1
    ? '1 activity marker falls outside the aligned window or does not match a retained observation date and is not drawn.'
    : `${hiddenMarkerCount} activity markers fall outside the aligned window or do not match retained observation dates and are not drawn.`;

  return (
    <figure
      className="min-w-0"
      aria-label={`${periodLabel} NAV chart indexed to 100${summaryLabel ? ` · ${summaryLabel}` : ''}`}
    >
      {hasData ? (
        <div data-testid="nav-chart" className="w-full" style={{ height: resolvedHeight }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={model.rows}
              margin={{ top: 8, right: 16, bottom: 4, left: 8 }}
              onMouseMove={(state) => {
                const label = state?.activeLabel;
                const row = typeof label === 'string' ? rowByDate.get(label) : undefined;
                const value = row && primaryKey !== null ? row[primaryKey] : undefined;
                setHoverValue(typeof value === 'number' && Number.isFinite(value) ? value : null);
              }}
              onMouseLeave={() => setHoverValue(null)}
            >
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--chart-grid))" />
              <XAxis
                dataKey="date"
                tickFormatter={formatAxisDate}
                minTickGap={32}
                tick={{ fontSize: 10, fill: 'hsl(var(--chart-axis))' }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                domain={yDomain}
                tickFormatter={value => AXIS_INDEX_FORMAT.format(Number(value))}
                tick={{ fontSize: 10, fill: 'hsl(var(--chart-axis))' }}
                axisLine={false}
                tickLine={false}
                width={52}
                label={{
                  value: 'Indexed to 100',
                  angle: -90,
                  position: 'insideLeft',
                  style: { fontSize: 10, fill: 'hsl(var(--chart-axis))' },
                }}
              />
              <Tooltip
                cursor={{ stroke: 'hsl(var(--chart-axis))', strokeWidth: 1, strokeDasharray: '3 3' }}
                content={<NavChartTooltip labels={labels} markers={markers} />}
              />
              <ReferenceLine y={100} stroke="hsl(var(--chart-grid))" strokeDasharray="3 3" />
              {hoverValue !== null && (
                <ReferenceLine
                  y={hoverValue}
                  className="nav-chart-hover-line"
                  stroke="hsl(var(--chart-axis))"
                  strokeDasharray="3 3"
                  strokeOpacity={0.75}
                />
              )}
              {activeSeries.map((candidate, index) => (
                <Line
                  key={candidate.key}
                  type="linear"
                  dataKey={candidate.key}
                  name={candidate.label}
                  stroke={colors[index]}
                  strokeWidth={index === primaryIndex ? 2.2 : candidate.emphasis === 'baseline' ? 1.5 : 1.8}
                  strokeDasharray={index === primaryIndex ? undefined : '5 4'}
                  dot={false}
                  activeDot={false}
                  isAnimationActive={false}
                  connectNulls={false}
                />
              ))}
              {visibleMarkers.map(marker => (
                <ReferenceLine
                  key={`marker-line-${marker.date}`}
                  x={marker.date}
                  stroke="hsl(var(--chart-axis))"
                  strokeDasharray="2 4"
                  strokeOpacity={0.55}
                />
              ))}
              {visibleMarkers.map(marker => {
                const row = rowByDate.get(marker.date);
                const value = row && primaryKey !== null ? Number(row[primaryKey]) : Number.NaN;
                if (!Number.isFinite(value)) return null;
                return (
                  <ReferenceDot
                    key={`marker-dot-${marker.date}`}
                    x={marker.date}
                    y={value}
                    r={6}
                    fill={markerColor(marker.side)}
                    stroke="hsl(var(--card))"
                    strokeWidth={1}
                    onClick={onMarkerSelect ? () => onMarkerSelect(marker) : undefined}
                    style={onMarkerSelect ? { cursor: 'pointer' } : undefined}
                    shape={<ActivityMarkerShape side={marker.side} />}
                  />
                );
              })}
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div
          data-testid="nav-chart-empty"
          role="status"
          className={cn('ae-empty')}
          style={{ minHeight: resolvedHeight }}
        >
          {emptyReason ?? 'Not enough exact-date observations to plot this comparison.'}
        </div>
      )}

      {activeSeries.length > 0 && (
        <ul aria-label="Chart series" className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
          {activeSeries.map((candidate, index) => (
            <li key={candidate.key} className="inline-flex items-center gap-1.5">
              <span aria-hidden="true" className="inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: colors[index] }} />
              <span>{candidate.label}</span>
              <span className="text-[10px] uppercase tracking-[0.08em]">
                {index === primaryIndex ? 'Primary' : 'Baseline'}
              </span>
            </li>
          ))}
        </ul>
      )}

      <figcaption className="mt-2 space-y-1 text-[11px] leading-4 text-muted-foreground">
        <p data-testid="nav-chart-window">
          {periodLabel}
          {hasData
            ? ` · ${model.startDate} – ${model.endDate} · Indexed to 100 at ${model.startDate}`
            : ' · No aligned observations'}
        </p>
        {hasData && (
          <p>
            Exact-date observations only, rebased to the first common date. Compare within one market;
            baselines are not cross-market substitutes.
          </p>
        )}
        {coverage && coverage.state !== 'full' && (
          <p
            role="note"
            data-testid="nav-chart-coverage"
            data-coverage-state={coverage.state}
            className="font-medium text-warning"
          >
            {coverageDisclosure(coverage)}
          </p>
        )}
        {hiddenMarkerCount > 0 && (
          <p role="note" data-testid="nav-chart-hidden-markers">{hiddenMarkerText}</p>
        )}
      </figcaption>

      {visibleMarkers.length > 0 && (
        <ul aria-label="Activity marker key" className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-muted-foreground">
          {MARKER_KEY.map(item => (
            <li key={item.side} className="inline-flex items-center gap-1.5">
              <MarkerGlyph side={item.side} />
              {item.label}
            </li>
          ))}
          <li>Markers appear only on retained observation dates.</li>
        </ul>
      )}

      {visibleMarkers.length > 0 && (
        <div className="mt-2 rounded-lg border bg-card/60">
          <p className="border-b px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Activity markers in this window
          </p>
          <ul aria-label="Activity marker details" className="flex max-h-48 flex-wrap gap-1.5 overflow-y-auto p-2">
            {visibleMarkers.map(marker => {
              const selected = selectedMarkerDate === marker.date;
              return (
                <li key={`marker-detail-${marker.date}`}>
                  {onMarkerSelect ? (
                    <button
                      type="button"
                      data-testid="nav-marker-button"
                      aria-pressed={selected}
                      onClick={() => onMarkerSelect(marker)}
                      className={cn(
                        'research-touch min-h-8 rounded border px-2 py-1 text-left text-[11px] tabular-nums transition-colors',
                        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
                        selected
                          ? 'border-primary bg-primary/10 text-foreground'
                          : 'bg-card text-muted-foreground hover:text-foreground',
                      )}
                    >{markerSummary(marker)}</button>
                  ) : (
                    <span className="text-[11px] text-muted-foreground">{markerSummary(marker)}</span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {hasData && (
        <details data-testid="nav-chart-data" className="mt-2 rounded-lg border bg-card/60">
          <summary className="research-touch min-h-8 cursor-pointer px-3 py-2 text-[11px] font-medium text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1">
            View chart data table
          </summary>
          <div className="max-h-72 overflow-auto border-t">
            <table className="w-full border-collapse text-[11px]">
              <caption className="sr-only">
                {periodLabel} plot data indexed to 100 at {model.startDate}; exact observed dates only.
              </caption>
              <thead className="sticky top-0 bg-card">
                <tr className="border-b">
                  <th scope="col" className="px-2 py-1 text-left font-semibold text-muted-foreground">Date</th>
                  {activeSeries.map(candidate => (
                    <th key={candidate.key} scope="col" className="px-2 py-1 text-right font-semibold text-muted-foreground">
                      {candidate.label}
                    </th>
                  ))}
                  <th scope="col" className="px-2 py-1 text-left font-semibold text-muted-foreground">Marker</th>
                </tr>
              </thead>
              <tbody>
                {model.rows.map(row => {
                  const marker = markerByDate.get(row.date);
                  return (
                    <tr key={`chart-row-${row.date}`} className="border-b last:border-b-0">
                      <th scope="row" className="px-2 py-1 text-left font-normal tabular-nums">{row.date}</th>
                      {activeSeries.map(candidate => (
                        <td key={candidate.key} className="px-2 py-1 text-right font-mono tabular-nums">
                          {INDEX_FORMAT.format(Number(row[candidate.key]))}
                        </td>
                      ))}
                      <td className="px-2 py-1 text-left">
                        {marker ? `${markerSideLabel(marker.side)} · ${marker.count}` : '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </figure>
  );
}
