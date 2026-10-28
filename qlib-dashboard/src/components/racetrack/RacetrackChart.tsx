import { useEffect, useRef, useState } from 'react';
import { ColorType, createChart, LineSeries, LineStyle, type IChartApi, type ISeriesApi, type MouseEventParams, type Time } from 'lightweight-charts';
import { contiguousSegments, type RaceDisplay } from '@/lib/racetrack-projection';

const COLORS = ['#64748b', '#a16207', '#6366f1', '#0891b2', '#c2410c', '#059669', '#9333ea', '#db2777', '#2563eb', '#a16207', '#0d9488', '#7c3aed'];
export const seriesColor = (index: number) => COLORS[index % COLORS.length];

export function RacetrackChart({ data, selected, onSelect, onHover }: {
  data: RaceDisplay; selected: string | null; onSelect: (id: string) => void; onHover: (id: string | null) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const lines = useRef(new Map<string, ISeriesApi<'Line'>[]>());
  const callbacks = useRef({ onSelect, onHover }); callbacks.current = { onSelect, onHover };
  const [readout, setReadout] = useState<{ date: string; values: { label: string; value: number | null }[] } | null>(null);
  const [chartError, setChartError] = useState<string | null>(null);
  const readIndex = (index: number) => setReadout({ date: data.dates[index], values: data.series.map(s => ({ label: s.label, value: s.values[index] })) });

  useEffect(() => {
    if (!host.current || !data.dates.length) return;
    const segments = data.series.map(item => contiguousSegments(data.dates, item.values));
    if (segments.reduce((n, items) => n + items.length, 0) > 128) {
      setChartError('Too many disconnected segments to plot safely. Published metrics remain readable.');
      return;
    }
    setChartError(null);
    const chart = createChart(host.current, { autoSize: true, height: 370,
      layout: { attributionLogo: true, background: { type: ColorType.Solid, color: 'transparent' } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: .12, bottom: .12 } },
      timeScale: { borderVisible: false, rightOffset: 2, fixLeftEdge: true },
      grid: { vertLines: { color: 'rgba(128,128,128,.08)' }, horzLines: { color: 'rgba(128,128,128,.12)' } },
      localization: { priceFormatter: (v: number) => v.toFixed(3) },
    });
    chartRef.current = chart;
    const ids = new Map<ISeriesApi<'Line'>, string>();
    for (const [index, item] of data.series.entries()) {
      const parts = segments[index].map(part => {
      const series = chart.addSeries(LineSeries, { color: seriesColor(index), lineWidth: index < 2 ? 2 : 1,
        lineStyle: index < 2 ? LineStyle.Dashed : LineStyle.Solid, title: '',
        lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: true });
      series.setData(part.map(point => ({ ...point, time: point.time as Time })));
      if (item.runnerId) ids.set(series, item.runnerId);
      return series;
      });
      lines.current.set(item.id, parts);
    }
    chart.timeScale().fitContent();
    const theme = () => chart.applyOptions({ layout: { textColor: document.documentElement.classList.contains('dark') ? '#cbd5e1' : '#475569' } });
    theme();
    const observer = new MutationObserver(theme);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    let frame = 0;
    const hover = (event: MouseEventParams) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const index = typeof event.time === 'string' ? data.dates.indexOf(event.time) : -1;
        if (index >= 0) setReadout({ date: data.dates[index], values: data.series.map(s => ({ label: s.label, value: s.values[index] })) });
        const id = event.hoveredSeries ? ids.get(event.hoveredSeries as ISeriesApi<'Line'>) : null;
        callbacks.current.onHover(id ?? null);
      });
    };
    const click = (event: MouseEventParams) => {
      const id = event.hoveredSeries ? ids.get(event.hoveredSeries as ISeriesApi<'Line'>) : null;
      if (id) callbacks.current.onSelect(id);
    };
    chart.subscribeCrosshairMove(hover); chart.subscribeClick(click);
    setReadout(null);
    return () => {
      cancelAnimationFrame(frame); observer.disconnect(); chart.unsubscribeCrosshairMove(hover);
      chart.unsubscribeClick(click); chart.remove(); chartRef.current = null; lines.current.clear();
    };
  }, [data]);

  useEffect(() => {
    for (const [index, item] of data.series.entries()) for (const series of lines.current.get(item.id) ?? []) {
      series.applyOptions({ lineWidth: item.runnerId === selected ? 3 : index < 2 ? 2 : 1 });
    }
  }, [selected, data]);

  return <div className="min-w-0">
    <div className="flex flex-wrap items-center justify-between gap-2 px-1 text-xs text-muted-foreground">
      <span>Display NAV · 1.00 at {data.dates[0]}</span>
      <span>{data.shortHistory === undefined ? `${data.availableMonths} / ${data.requestedMonths} month buckets available` : data.shortHistory ? 'Available replay · insufficient history for the selected window' : `Full ${data.requestedMonths}M window available`}</span>
      <button className="min-h-9 rounded-md border px-3 hover:bg-muted focus-visible:ring-2" onClick={() => chartRef.current?.timeScale().fitContent()}>Reset zoom</button>
    </div>
    <div ref={host} role="img" aria-label="Racetrack normalized NAV comparison" className="h-[370px] w-full" />
    {chartError && <p role="alert" className="text-sm">{chartError}</p>}
    <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs" aria-label="NAV legend">
      {data.series.map((s, index) => <button key={s.id} className="flex min-h-9 items-center gap-2 rounded-md px-1 text-left focus-visible:ring-2"
        disabled={!s.runnerId} aria-pressed={selected === s.runnerId} onClick={() => s.runnerId && onSelect(s.runnerId)}>
        <span aria-hidden="true" className="h-0.5 w-5 shrink-0" style={{ background: seriesColor(index), borderTop: index < 2 ? '1px dashed' : undefined }} />
        <span className={selected === s.runnerId ? 'font-bold text-foreground' : 'text-muted-foreground'}>{s.label}</span>
      </button>)}
    </div>
    <label className="mt-3 flex items-center gap-3 text-xs text-muted-foreground">Keyboard date readout
      <input aria-label="NAV readout date" type="range" className="min-w-0 flex-1" min={0} max={data.dates.length - 1} defaultValue={data.dates.length - 1} key={`${data.dates[0]}:${data.dates.length}`}
        onChange={event => readIndex(Number(event.target.value))} />
    </label>
    <div aria-live="polite" className="mt-2 min-h-7 flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums text-muted-foreground">
      <span>{readout?.date ?? 'Hover a curve or use the date control to read NAV.'}</span>
      {readout?.values.map(row => <span key={row.label}>{row.label}: {row.value === null ? 'Gap' : row.value.toFixed(3)}</span>)}
    </div>
  </div>;
}
