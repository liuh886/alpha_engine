import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { summarizeStrategySignal, type StrategyOperationsSnapshot } from '@/lib/strategy-operations';

export function OperationsReadStatus({ loading, issues, reload, snapshots }: {
  loading: boolean;
  issues: string[];
  reload: () => void;
  snapshots?: Map<string, StrategyOperationsSnapshot>;
}) {
  const records = Array.from(snapshots?.values() ?? []);
  const protectedCount = records.filter(record => record.readState === 'protected').length;
  const retained = records.filter(record => summarizeStrategySignal(record).badgeLabel === 'Not due').length;
  const attention = records.filter(record => summarizeStrategySignal(record).isAttention).length;
  const verified = records.filter(record => !record.readState
    && ['current_no_change', 'target_pending_execution', 'execution_observed'].includes(record.status)
    && !summarizeStrategySignal(record).isAttention).length;
  const awaiting = records.filter(record => !record.readState
    && ['pipeline_unavailable', 'awaiting_observation'].includes(record.status)).length;
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 rounded-xl border bg-card p-4" role="region" aria-label="Current operations reader">
      <div className="min-w-0 flex-1 text-xs text-muted-foreground" role="status" aria-live="polite">
        <p>{loading ? 'Reading published operations…' : issues.length ? 'Some current operations could not be verified.' : protectedCount ? 'Formal evidence checked. Current signals require account or strategy access.' : 'Published operations checked. Each record retains its own evidence cutoff.'}</p>
        {!loading && records.length > 0 && <p className="mt-1">{verified} observations available · {retained} retained within cadence · {attention} need attention · {protectedCount} require access{awaiting > 0 ? ` · ${awaiting} awaiting observation` : ''}</p>}
        {issues.length > 0 && <ul className="mt-2 space-y-1 text-amber-700 dark:text-amber-300">{issues.map((issue) => <li key={issue}>{issue}</li>)}</ul>}
      </div>
      <Button type="button" variant="outline" size="sm" disabled={loading} onClick={reload} className="min-h-[44px] gap-2">
        <RefreshCw className={loading ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
        {loading ? 'Reading operations' : issues.length ? 'Retry operations' : 'Refresh operations'}
      </Button>
    </div>
  );
}
