import { RefreshCw } from 'lucide-react';
import type { StrategyOperationsReadIssue } from '@/hooks/useStrategyOperations';
import { Button } from '@/components/ui/button';
import type { GovernedRunSummary } from '@/lib/governed-run';
import { RANKING_MARKET_LABELS } from '@/lib/model-ranking';

function checkedLabel(checkedAt: string | null): string | null {
  if (!checkedAt) return null;
  const time = new Date(checkedAt);
  if (!Number.isFinite(time.getTime())) return null;
  return `${time.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' })} UTC`;
}

/**
 * The single operations reader status used by every page. It reports the
 * verified read time and outcome, the markets affected by read issues, and the
 * one refresh affordance for the page that renders it.
 */
export function OperationsReadStatus({ loading, issues, reload, previousRead = false, checkedAt = null, runs = [], showRefresh = true }: {
  loading: boolean;
  previousRead?: boolean;
  issues: StrategyOperationsReadIssue[];
  reload: () => void;
  checkedAt?: string | null;
  runs?: GovernedRunSummary[];
  showRefresh?: boolean;
}) {
  const checked = checkedLabel(checkedAt);
  const failedIds = new Set(issues.map(issue => issue.modelVersionId).filter((id): id is string => Boolean(id)));
  const verified = runs.filter(run => !failedIds.has(run.modelVersionId)).length;
  const marketLabel = (market: string) => market === 'us'
    ? RANKING_MARKET_LABELS.us
    : market === 'cn' ? RANKING_MARKET_LABELS.cn : market.toUpperCase();
  const affectedMarkets = Array.from(new Set(runs.filter(run => failedIds.has(run.modelVersionId))
    .map(run => marketLabel(run.market))));
  const affectsAll = issues.some(issue => !issue.modelVersionId);
  const affected = affectsAll ? 'all markets' : affectedMarkets.join(' / ');
  const outcome = issues.length
    ? `${issues.length} ${issues.length === 1 ? 'record needs' : 'records need'} attention`
    : runs.length ? `${verified} of ${runs.length} observations verified` : 'records verified';
  return (
    <div className="ae-surface flex flex-wrap items-start justify-between gap-3 p-4" role="region" aria-label="Current operations reader">
      <div className="min-w-0 flex-1 text-xs text-muted-foreground" role="status" aria-live="polite">
        {previousRead && <p className="mb-2 font-medium">Showing the previous verified read at its original cutoff. This refresh has not verified newer observations.</p>}
        <p>
          {loading ? 'Reading published operations…' : checked
            ? <>Checked <time dateTime={checkedAt ?? undefined} className="font-medium text-foreground">{checked}</time> · {outcome}{affected && <> · affects {affected}</>}</>
            : <>Published operations checked. Each record retains its own evidence cutoff.</>}
        </p>
        {issues.length > 0 && <ul className="mt-2 space-y-1 text-warning">{issues.map((issue) => <li key={`${issue.modelVersionId}:${issue.message}`}>{issue.message}</li>)}</ul>}
      </div>
      {showRefresh && (
        <Button type="button" variant="outline" size="sm" disabled={loading} onClick={reload} className="min-h-[44px] gap-2">
          <RefreshCw className={loading ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
          {loading ? 'Reading operations' : issues.length ? 'Retry operations' : 'Refresh operations'}
        </Button>
      )}
    </div>
  );
}
