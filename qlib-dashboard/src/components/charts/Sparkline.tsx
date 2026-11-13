import { downsampleLttb, type NavPoint } from '@/lib/nav-series';
import { isPerformanceDate } from '@/lib/performancePeriods';
import { cn } from '@/lib/utils';

export type SparklineTone = 'auto' | 'positive' | 'negative' | 'neutral';

export interface SparklineProps {
  nav: NavPoint[];
  width?: number;
  height?: number;
  className?: string;
  /** Provide a label when the sparkline is the only carrier of the value. */
  label?: string;
  tone?: SparklineTone;
  /** Mark the final observation with an 8px endpoint dot and surface ring. */
  showEndpoint?: boolean;
}

const MAX_POINTS = 60;
const PADDING = 2;

function validSegments(nav: NavPoint[]): NavPoint[][] {
  if (!Array.isArray(nav)) return [];
  const segments: NavPoint[][] = [];
  let current: NavPoint[] = [];
  let lastDate: string | null = null;

  for (const point of nav) {
    const valid = Boolean(point)
      && isPerformanceDate(point.date)
      && Number.isFinite(point.value)
      && point.value > 0;
    if (!valid) {
      if (current.length > 0) segments.push(current);
      current = [];
      lastDate = null;
      continue;
    }
    if (lastDate !== null && point.date <= lastDate) {
      if (current.length > 0) segments.push(current);
      current = [];
    }
    current.push(point);
    lastDate = point.date;
  }

  if (current.length > 0) segments.push(current);
  return segments;
}

function downsampleSegments(segments: NavPoint[][]): NavPoint[][] {
  const total = segments.reduce((sum, segment) => sum + segment.length, 0);
  if (total <= MAX_POINTS) return segments;
  return segments.map(segment => {
    const quota = Math.max(2, Math.round(MAX_POINTS * segment.length / total));
    return downsampleLttb(segment, quota);
  });
}

function coordinate(value: number): string {
  return (Math.round(value * 100) / 100).toFixed(2);
}

function segmentPath(segment: NavPoint[], x: (point: NavPoint) => number, y: (point: NavPoint) => number): string {
  return segment.map((point, index) => `${index === 0 ? 'M' : 'L'}${coordinate(x(point))} ${coordinate(y(point))}`).join(' ');
}

function resolvedTone(points: NavPoint[], tone: SparklineTone): Exclude<SparklineTone, 'auto'> {
  if (tone !== 'auto') return tone;
  if (points.length < 2) return 'neutral';
  const change = points[points.length - 1].value - points[0].value;
  if (change > 0) return 'positive';
  if (change < 0) return 'negative';
  return 'neutral';
}

/**
 * Compact inline-SVG NAV sparkline. The path breaks at invalid observations
 * instead of bridging missing data, uses LTTB downsampling, and derives its
 * color from semantic tokens rather than hard-coded colors.
 */
export function Sparkline({
  nav,
  width = 120,
  height = 32,
  className,
  label,
  tone = 'auto',
  showEndpoint = false,
}: SparklineProps) {
  const resolvedWidth = Number.isFinite(width) && width > 0 ? width : 120;
  const resolvedHeight = Number.isFinite(height) && height > 0 ? height : 32;
  const segments = downsampleSegments(validSegments(nav));
  const points = segments.flat();
  const resolved = resolvedTone(points, tone);
  const toneClass = resolved === 'positive'
    ? 'text-positive'
    : resolved === 'negative'
      ? 'text-negative'
      : 'text-muted-foreground';

  let path = '';
  let endpoint: { x: number; y: number } | null = null;
  if (points.length > 0) {
    const padding = Math.min(PADDING, Math.max(0, Math.min(resolvedWidth, resolvedHeight) / 4));
    const times = points.map(point => Date.parse(`${point.date}T00:00:00Z`));
    const values = points.map(point => point.value);
    const minTime = Math.min(...times);
    const maxTime = Math.max(...times);
    const minValue = Math.min(...values);
    const maxValue = Math.max(...values);
    const innerWidth = Math.max(0, resolvedWidth - padding * 2);
    const innerHeight = Math.max(0, resolvedHeight - padding * 2);

    const x = (point: NavPoint) => {
      if (minTime === maxTime) return padding + innerWidth / 2;
      return padding + ((Date.parse(`${point.date}T00:00:00Z`) - minTime) / (maxTime - minTime)) * innerWidth;
    };
    const y = (point: NavPoint) => {
      if (minValue === maxValue) return padding + innerHeight / 2;
      return padding + innerHeight - ((point.value - minValue) / (maxValue - minValue)) * innerHeight;
    };

    path = segments
      .map(segment => segment.length === 1
        ? `${segmentPath(segment, x, y)} L${coordinate(x(segment[0]) + 0.01)} ${coordinate(y(segment[0]))}`
        : segmentPath(segment, x, y))
      .join(' ');
    endpoint = { x: x(points[points.length - 1]), y: y(points[points.length - 1]) };
  }

  const accessibleLabel = typeof label === 'string' && label.trim() !== '' ? label : undefined;

  return (
    <svg
      data-testid="sparkline"
      data-tone={resolved}
      data-point-count={String(points.length)}
      data-segment-count={String(segments.length)}
      className={cn('block overflow-visible', toneClass, className)}
      width={resolvedWidth}
      height={resolvedHeight}
      viewBox={`0 0 ${resolvedWidth} ${resolvedHeight}`}
      preserveAspectRatio="none"
      role={accessibleLabel ? 'img' : undefined}
      aria-label={accessibleLabel}
      aria-hidden={accessibleLabel ? undefined : true}
      focusable="false"
    >
      {path !== '' && (
        <path
          d={path}
          fill="none"
          stroke="currentColor"
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      )}
      {showEndpoint && endpoint !== null && (
        <circle
          data-testid="sparkline-endpoint"
          cx={coordinate(endpoint.x)}
          cy={coordinate(endpoint.y)}
          r={4}
          fill="currentColor"
          stroke="hsl(var(--card))"
          strokeWidth={2}
        />
      )}
    </svg>
  );
}
