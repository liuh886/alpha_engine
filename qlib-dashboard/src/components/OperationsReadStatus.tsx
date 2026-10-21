import { RefreshCw } from 'lucide-react';
import type { StrategyOperationsReadIssue } from '@/hooks/useStrategyOperations';
import { Button } from '@/components/ui/button';

export function OperationsReadStatus({ loading, issues, reload, previousRead = false }: {
  loading: boolean;
  previousRead?: boolean;
  issues: StrategyOperationsReadIssue[];
  reload: () => void;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 rounded-xl border bg-card p-4" role="region" aria-label="Current operations reader">
      <div className="min-w-0 flex-1 text-xs text-muted-foreground" role="status" aria-live="polite">
        {previousRead && <p className="mb-2 font-medium">Showing the previous verified read at its original cutoff. This refresh has not verified newer observations.</p>}
        <p>{loading ? 'Reading published operations…' : issues.length ? 'Some current operations could not be verified.' : 'Published operations checked. Each record retains its own evidence cutoff.'}</p>
        {issues.length > 0 && <ul className="mt-2 space-y-1 text-amber-700 dark:text-amber-300">{issues.map((issue) => <li key={`${issue.modelVersionId}:${issue.message}`}>{issue.message}</li>)}</ul>}
      </div>
      <Button type="button" variant="outline" size="sm" disabled={loading} onClick={reload} className="min-h-[44px] gap-2">
        <RefreshCw className={loading ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
        {loading ? 'Reading operations' : issues.length ? 'Retry operations' : 'Refresh operations'}
      </Button>
    </div>
  );
}
