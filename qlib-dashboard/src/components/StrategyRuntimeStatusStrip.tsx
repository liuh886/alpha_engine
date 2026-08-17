import type { SystemHealthState } from '@/lib/system-health';

interface StatusCellProps {
  label: string;
  value: string;
  state?: SystemHealthState | 'unknown';
}

const STATE_LABEL: Record<SystemHealthState | 'unknown', string> = {
  current: 'Current',
  delayed: 'Delayed',
  blocked: 'Blocked',
  inconsistent: 'Inconsistent',
  not_applicable: 'N/A',
  unknown: 'Unknown',
};

function StatusCell({ label, value, state = 'unknown' }: StatusCellProps) {
  return (
    <div className="min-w-0 px-4 py-3 sm:px-5">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-muted-foreground">{label}</p>
        <span className="text-[10px] font-medium text-muted-foreground">{STATE_LABEL[state]}</span>
      </div>
      <p className="mt-1.5 truncate font-mono text-sm font-semibold tabular-nums">{value}</p>
    </div>
  );
}

export function deliveryLabel(status: string | null | undefined): string {
  switch (status) {
    case 'sent': return 'Sent';
    case 'not_required': return 'No change · not required';
    case 'skipped_not_configured': return 'Not configured';
    case 'failed': return 'Failed';
    case 'pending': return 'Pending';
    case 'not available': return 'Unavailable';
    default: return status || 'Unavailable';
  }
}

interface StrategyRuntimeStatusStripProps {
  dataThrough: string | null;
  dataState?: SystemHealthState | 'unknown';
  performanceThrough: string | null;
  performanceState?: SystemHealthState | 'unknown';
  signalThrough: string | null;
  signalState?: SystemHealthState | 'unknown';
  deliveryStatus: string | null | undefined;
  deliveryState?: SystemHealthState | 'unknown';
}

export function StrategyRuntimeStatusStrip({
  dataThrough,
  dataState,
  performanceThrough,
  performanceState,
  signalThrough,
  signalState,
  deliveryStatus,
  deliveryState,
}: StrategyRuntimeStatusStripProps) {
  return (
    <div className="grid overflow-hidden rounded-xl border bg-card shadow-sm sm:grid-cols-2 xl:grid-cols-4 [&>*:not(:last-child)]:border-b sm:[&>*:nth-child(odd)]:border-r sm:[&>*:nth-child(3)]:border-b-0 xl:[&>*]:border-b-0 xl:[&>*:not(:last-child)]:border-r">
      <StatusCell label="Data through" value={dataThrough || '—'} state={dataState} />
      <StatusCell label="Performance through" value={performanceThrough || '—'} state={performanceState} />
      <StatusCell label="Signal evaluated" value={signalThrough || '—'} state={signalState} />
      <StatusCell label="Alert" value={deliveryLabel(deliveryStatus)} state={deliveryState} />
    </div>
  );
}
