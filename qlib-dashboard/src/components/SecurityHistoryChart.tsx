import { useId } from 'react';
import { Bar, CartesianGrid, ComposedChart, ReferenceDot, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { SecurityBar, SecurityEvent } from '@/lib/security-evidence';

export interface SecurityMarker { time: string; positive: boolean; events: SecurityEvent[] }
export function securityMarkers(bars: SecurityBar[], events: SecurityEvent[]): SecurityMarker[] {
  const dates = new Set(bars.map(bar => bar.time));
  const groups = new Map<string, SecurityMarker>();
  for (const event of events) {
    if (!dates.has(event.time)) continue;
    const positive = event.action === 'BUY' || event.action === 'INCREASE';
    const key = `${event.time}:${positive}`;
    const group = groups.get(key) ?? { time: event.time, positive, events: [] };
    group.events.push(event);
    groups.set(key, group);
  }
  return [...groups.values()];
}

function Candle({ x = 0, y = 0, width = 0, height = 0, payload }: {
  x?: number; y?: number; width?: number; height?: number; payload?: SecurityBar;
}) {
  if (!payload) return <g />;
  const scale = payload.high === payload.low ? 0 : height / (payload.high - payload.low);
  const bodyY = y + (payload.high - Math.max(payload.open, payload.close)) * scale;
  const bodyHeight = Math.max(1, Math.abs(payload.close - payload.open) * scale);
  const color = payload.close >= payload.open ? '#059669' : '#e11d48';
  return <g data-testid="security-candle">
    <line x1={x + width / 2} x2={x + width / 2} y1={y} y2={y + height} stroke={color} />
    <rect x={x} y={bodyY} width={Math.max(1, width)} height={bodyHeight} fill={color} />
  </g>;
}

export function SecurityHistoryChart({ bars, events, modelName, onSelect }: {
  bars: SecurityBar[]; events: SecurityEvent[]; modelName: (id: string) => string;
  onSelect: (events: SecurityEvent[]) => void;
}) {
  const syncId = useId();
  const data = bars.map(bar => ({ ...bar, priceRange: [bar.low, bar.high] }));
  const byDate = new Map(bars.map(bar => [bar.time, bar]));
  const markers = securityMarkers(bars, events);
  const short = bars.length && Date.parse(bars[bars.length - 1].time) - Date.parse(bars[0].time) < 100 * 86400000;
  const tick = (date: string) => short ? date.slice(5) : date.slice(0, 7);
  return <div data-testid="security-history-chart" data-marker-count={markers.length}>
    <div className="h-[360px] sm:h-[440px]">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} syncId={syncId} margin={{ top: 24, right: 15, left: 5, bottom: 8 }}>
          <CartesianGrid vertical={false} strokeOpacity={0.15} />
          <XAxis dataKey="time" tickFormatter={tick} minTickGap={48} tick={{ fontSize: 11 }} />
          <YAxis domain={[(min: number) => min * 0.96, (max: number) => max * 1.04]} tick={{ fontSize: 11 }} width={62}
            tickFormatter={(value: number) => value.toFixed(2)} />
          <Tooltip content={({ active, payload }) => {
            const bar = payload?.[0]?.payload as SecurityBar | undefined;
            return active && bar ? <div className="rounded-lg border bg-background p-3 text-xs shadow">
              <strong>{bar.time}</strong><p className="mt-1 font-mono">O {bar.open.toFixed(2)} · H {bar.high.toFixed(2)}</p>
              <p className="font-mono">L {bar.low.toFixed(2)} · C {bar.close.toFixed(2)}</p>
              <p className="mt-1">Volume {bar.volume.toLocaleString()}</p>
            </div> : null;
          }} />
          <Bar dataKey="priceRange" shape={<Candle />} isAnimationActive={false} maxBarSize={12} />
          {markers.map(marker => {
            const bar = byDate.get(marker.time)!;
            const label = `${marker.time}: ${marker.events.map(event => `${modelName(event.model_id)} ${event.action}`).join(', ')}`;
            return <ReferenceDot key={`${marker.time}:${marker.positive}`} x={marker.time} y={marker.positive ? bar.low : bar.high}
              shape={({ cx = 0, cy = 0 }) => {
                const center = cy + (marker.positive ? 12 : -12);
                return <g role="button" tabIndex={0} aria-label={label} data-testid="security-trade-marker" className="cursor-pointer"
                  onClick={() => onSelect(marker.events)} onKeyDown={event => {
                    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(marker.events); }
                  }}>
                  <title>{label}</title>
                  <circle cx={cx} cy={center} r={10} fill="hsl(var(--background))" stroke={marker.positive ? '#059669' : '#e11d48'} />
                  <text x={cx} y={center + 3} textAnchor="middle" fontSize={10} fontWeight={700}
                    fill={marker.positive ? '#059669' : '#e11d48'}>{marker.positive ? 'B' : 'S'}</text>
                </g>;
              }} />;
          })}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
    <div className="h-[105px]" aria-label="Observed volume">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} syncId={syncId} margin={{ right: 15, left: 5 }}>
          <XAxis dataKey="time" tickFormatter={tick} minTickGap={48} tick={{ fontSize: 10 }} />
          <YAxis width={62} tick={{ fontSize: 10 }} tickFormatter={(value: number) => value >= 1e6 ? `${(value / 1e6).toFixed(0)}M` : `${(value / 1e3).toFixed(0)}K`} />
          <Tooltip formatter={(value) => [Number(value).toLocaleString(), 'Volume']} />
          <Bar dataKey="volume" fill="hsl(var(--muted-foreground))" opacity={0.4} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  </div>;
}
