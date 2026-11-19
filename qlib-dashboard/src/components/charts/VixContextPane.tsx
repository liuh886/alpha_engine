import { useMemo, useState } from 'react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { SecurityBar } from '@/lib/security-evidence';
import {
  VIX_DISCLOSURE,
  VIX_PANE_LABEL,
  VIX_SMA_LABEL,
  vixPoints,
  vixSmaPoints,
} from '@/lib/vix-context';
import { cn } from '@/lib/utils';

export type VixPaneState =
  | { status: 'loading' }
  | { status: 'unavailable'; reason: string }
  | { status: 'ready'; bars: readonly SecurityBar[] };

const RAW_COLOR = 'hsl(var(--indicator-3))';
const SMA_COLOR = 'hsl(var(--indicator-2))';
const TABLE_ROWS = 120;
const VIX_FORMAT = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const AXIS_DATE_FORMAT = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  timeZone: 'UTC',
});
const READABLE_DATE_FORMAT = new Intl.DateTimeFormat('en-US', {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  timeZone: 'UTC',
});

interface VixRow {
  date: string;
  vix: number;
  sma?: number;
}

interface VixTooltipPayload {
  dataKey?: string | number;
  value?: number | string | null;
}

function formatAxisDate(date: string): string {
  const parsed = new Date(`${date}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) ? AXIS_DATE_FORMAT.format(parsed) : date;
}

function formatReadableDate(date: string): string {
  const parsed = new Date(`${date}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) ? READABLE_DATE_FORMAT.format(parsed) : date;
}

/** Compact tooltip for the separate VIX pane; text stays in ink tokens. */
export function VixContextTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: VixTooltipPayload[];
  label?: string | number;
}) {
  if (!active || !payload || payload.length === 0 || label === undefined || label === null) return null;
  return (
    <div
      data-testid="vix-context-tooltip"
      className="min-w-[150px] rounded-md border bg-popover p-2 text-[11px] text-popover-foreground shadow-card"
    >
      <p className="mb-1 border-b pb-1 font-semibold tabular-nums text-foreground">
        {formatReadableDate(String(label))}
      </p>
      <ul className="space-y-0.5">
        {payload.map(item => {
          const key = String(item.dataKey ?? '');
          const value = typeof item.value === 'number' ? item.value : Number(item.value);
          const name = key === 'sma' ? VIX_SMA_LABEL : 'VIX';
          return (
            <li key={key} className="flex items-baseline justify-between gap-3">
              <span className="text-muted-foreground">{name}</span>
              <span className="font-mono tabular-nums">
                {Number.isFinite(value) ? VIX_FORMAT.format(value) : '—'}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function VixLegend({ smaVisible }: { smaVisible: boolean }) {
  return (
    <ul aria-label="VIX series" className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
      <li className="inline-flex items-center gap-1.5">
        <span aria-hidden="true" className="inline-block w-4 border-t-2" style={{ borderColor: RAW_COLOR }} />
        <span>VIX</span>
      </li>
      {smaVisible && (
        <li className="inline-flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block w-4 border-t-2 border-dashed"
            style={{ borderColor: SMA_COLOR }}
          />
          <span>{VIX_SMA_LABEL}</span>
        </li>
      )}
    </ul>
  );
}

/**
 * A separate US-only VIX context pane below the NAV chart. It never shares the
 * NAV price axis: this figure owns one VIX axis. Raw closes are exact observed
 * dates; the optional average is the governed registry formula.
 */
export function VixContextPane({
  state,
  start,
  end,
}: {
  state: VixPaneState;
  start: string | null;
  end: string | null;
}) {
  const [smaEnabled, setSmaEnabled] = useState(false);

  const raw = useMemo(
    () => (state.status === 'ready' ? vixPoints(state.bars, start, end) : []),
    [end, start, state],
  );
  const sma = useMemo(
    () => (state.status === 'ready' ? vixSmaPoints(state.bars, start, end) : { points: [], available: false }),
    [end, start, state],
  );

  const rows = useMemo<VixRow[]>(() => {
    if (!smaEnabled || !sma.available) return raw.map(point => ({ date: point.time, vix: point.value }));
    const smaByDate = new Map(sma.points.map(point => [point.time, point.value]));
    return raw.map(point => ({
      date: point.time,
      vix: point.value,
      ...(smaByDate.has(point.time) ? { sma: smaByDate.get(point.time) } : {}),
    }));
  }, [raw, sma.available, sma.points, smaEnabled]);

  const smaVisible = smaEnabled && sma.available;
  const first = raw[0]?.time ?? null;
  const last = raw[raw.length - 1]?.time ?? null;
  const shownRows = rows.slice(-TABLE_ROWS);
  const bounded = shownRows.length < rows.length;

  return (
    <figure
      data-testid="strategy-vix-pane"
      aria-label={`${VIX_PANE_LABEL} · separate pane, exact observed VIX dates`}
      className="mt-5 min-w-0 border-t pt-3"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-xs font-semibold text-foreground">{VIX_PANE_LABEL}</h3>
          <p className="mt-0.5 text-[10px] leading-4 text-muted-foreground">
            Separate pane · one VIX axis · never a dual axis with NAV
          </p>
        </div>
        <button
          type="button"
          data-testid="strategy-vix-sma-toggle"
          aria-pressed={smaVisible}
          disabled={state.status !== 'ready' || !sma.available}
          onClick={() => setSmaEnabled(value => !value)}
          className={cn(
            'research-touch inline-flex min-h-8 items-center rounded border px-2.5 text-[11px] font-medium transition-colors',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
            smaVisible
              ? 'border-primary bg-primary/10 text-foreground'
              : 'bg-background text-muted-foreground hover:bg-muted hover:text-foreground',
            (state.status !== 'ready' || !sma.available) && 'cursor-not-allowed opacity-70',
          )}
        >
          {VIX_SMA_LABEL}
        </button>
      </div>

      {state.status === 'loading' && (
        <p role="status" data-testid="strategy-vix-loading" className="mt-2 text-[11px] text-muted-foreground">
          Loading governed US VIX context…
        </p>
      )}

      {state.status === 'unavailable' && (
        <p role="note" data-testid="strategy-vix-unavailable" className="mt-2 text-[11px] leading-4 text-warning">
          {state.reason}
        </p>
      )}

      {state.status === 'ready' && raw.length < 2 && (
        <p role="note" data-testid="strategy-vix-empty" className="mt-2 text-[11px] leading-4 text-muted-foreground">
          No governed VIX observations fall inside this chart window, so no context pane is drawn.
        </p>
      )}

      {state.status === 'ready' && !sma.available && sma.reason && (
        <p data-testid="strategy-vix-sma-unavailable" className="mt-1 text-[10px] leading-4 text-muted-foreground">
          {VIX_SMA_LABEL} unavailable: {sma.reason}
        </p>
      )}

      {state.status === 'ready' && raw.length >= 2 && (
        <>
          <div data-testid="strategy-vix-chart" className="mt-2 h-[132px] w-full sm:h-[148px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rows} margin={{ top: 4, right: 16, bottom: 2, left: 4 }}>
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
                  domain={['auto', 'auto']}
                  tickFormatter={value => VIX_FORMAT.format(Number(value))}
                  tick={{ fontSize: 10, fill: 'hsl(var(--chart-axis))' }}
                  axisLine={false}
                  tickLine={false}
                  width={46}
                  label={{
                    value: 'VIX',
                    angle: -90,
                    position: 'insideLeft',
                    style: { fontSize: 10, fill: 'hsl(var(--chart-axis))' },
                  }}
                />
                <Tooltip
                  cursor={{ stroke: 'hsl(var(--chart-axis))', strokeWidth: 1, strokeDasharray: '3 3' }}
                  content={<VixContextTooltip />}
                />
                <Line
                  type="linear"
                  dataKey="vix"
                  name="VIX"
                  stroke={RAW_COLOR}
                  strokeWidth={1.8}
                  dot={false}
                  activeDot={false}
                  isAnimationActive={false}
                  connectNulls={false}
                />
                {smaVisible && (
                  <Line
                    type="linear"
                    dataKey="sma"
                    name={VIX_SMA_LABEL}
                    stroke={SMA_COLOR}
                    strokeWidth={1.5}
                    strokeDasharray="5 4"
                    dot={false}
                    activeDot={false}
                    isAnimationActive={false}
                    connectNulls={false}
                  />
                )}
              </LineChart>
            </ResponsiveContainer>
          </div>

          <VixLegend smaVisible={smaVisible} />

          <figcaption className="mt-1 space-y-0.5 text-[10px] leading-4 text-muted-foreground">
            <p data-testid="strategy-vix-window">
              {first} – {last} · {raw.length} exact VIX observation{raw.length === 1 ? '' : 's'} · window{' '}
              {start ?? '—'} – {end ?? '—'}
            </p>
            <p>{VIX_DISCLOSURE}</p>
          </figcaption>

          <details data-testid="strategy-vix-data" className="mt-2 rounded-lg border bg-card/60">
            <summary className="research-touch min-h-8 cursor-pointer px-3 py-2 text-[11px] font-medium text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1">
              View VIX data table
            </summary>
            <div className="max-h-56 overflow-auto border-t">
              <table className="w-full border-collapse text-[11px]">
                <caption className="sr-only">
                  Exact observed VIX closes; {bounded
                    ? `the most recent ${shownRows.length} of ${rows.length} observations are shown.`
                    : `${shownRows.length} observation${shownRows.length === 1 ? '' : 's'} are shown.`}
                </caption>
                <thead className="sticky top-0 bg-card">
                  <tr className="border-b">
                    <th scope="col" className="px-2 py-1 text-left font-semibold text-muted-foreground">Date</th>
                    <th scope="col" className="px-2 py-1 text-right font-semibold text-muted-foreground">VIX</th>
                    {smaVisible && (
                      <th scope="col" className="px-2 py-1 text-right font-semibold text-muted-foreground">
                        {VIX_SMA_LABEL}
                      </th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {shownRows.map(row => (
                    <tr key={row.date} className="border-b last:border-b-0">
                      <th scope="row" className="px-2 py-1 text-left font-normal tabular-nums">{row.date}</th>
                      <td className="px-2 py-1 text-right font-mono tabular-nums">{VIX_FORMAT.format(row.vix)}</td>
                      {smaVisible && (
                        <td className="px-2 py-1 text-right font-mono tabular-nums">
                          {row.sma === undefined ? '—' : VIX_FORMAT.format(row.sma)}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="border-t px-3 py-2 text-[10px] leading-4 text-muted-foreground">
              {bounded
                ? `Showing the most recent ${shownRows.length} of ${rows.length} exact observations; older observations remain in the published series.`
                : `Showing all ${shownRows.length} exact observation${shownRows.length === 1 ? '' : 's'}.`}{' '}
              Not a signal or forecast.
            </p>
          </details>
        </>
      )}
    </figure>
  );
}
