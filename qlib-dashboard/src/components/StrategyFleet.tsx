import { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRight,
  ChevronDown,
  CircleSlash2,
  Crown,
  LockKeyhole,
  ShieldAlert,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import { useAccessControl } from '@/hooks/useAccessControl';
import type { GovernedRunSummary } from '@/lib/governed-run';
import type { CanonicalMetricV2 } from '@/lib/model-run-bundle-v2';
import {
  summarizeStrategySignal,
  type StrategyOperationsSnapshot,
} from '@/lib/strategy-operations';
import { StrategySignalDrawer } from '@/components/StrategySignalDrawer';
import { cn } from '@/lib/utils';

type MarketFilter = 'all' | 'us' | 'cn';
type SignalFilter = 'all' | 'new' | 'attention';
type PeriodKey = '1m' | '3m' | 'ytd' | 'all';

const PERIOD_OPTIONS: Array<{ key: PeriodKey; label: string }> = [
  { key: '1m', label: '1 month' },
  { key: '3m', label: '3 months' },
  { key: 'ytd', label: 'YTD' },
  { key: 'all', label: 'All' },
];

function metric(run: GovernedRunSummary, id: string): CanonicalMetricV2 | null {
  const metrics = Array.isArray(run.summary.metrics) ? run.summary.metrics : [];
  return (metrics as CanonicalMetricV2[]).find((item) => item.metric_id === id) ?? null;
}

function metricPercent(run: GovernedRunSummary, id: string): string {
  const item = metric(run, id);
  return item?.availability_status === 'available' && typeof item.value === 'number'
    ? `${item.value >= 0 ? '+' : ''}${(item.value * 100).toFixed(1)}%`
    : '—';
}

function metricDecimal(run: GovernedRunSummary, id: string): string {
  const item = metric(run, id);
  return item?.availability_status === 'available' && typeof item.value === 'number'
    ? item.value.toFixed(2)
    : '—';
}

function allocationSummary(snapshot: StrategyOperationsSnapshot | undefined, side: 'current' | 'target'): string {
  if (!snapshot || snapshot.allocations.length === 0) return 'Not published';
  return (
    snapshot.allocations
      .filter((leg) => Math.abs(leg[side]) > 1e-9)
      .map((leg) => `${leg.asset} ${(leg[side] * 100).toFixed(0)}%`)
      .join(' · ') || 'Cash / flat'
  );
}

function SignalStatusIcon({ direction }: { direction: string }) {
  switch (direction) {
    case 'increase':
      return <TrendingUp className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />;
    case 'reduce':
      return <TrendingDown className="h-3.5 w-3.5 text-amber-600 dark:text-amber-400" />;
    case 'hold':
      return <ShieldCheck className="h-3.5 w-3.5 text-blue-600 dark:text-blue-400" />;
    case 'attention':
      return <ShieldAlert className="h-3.5 w-3.5 text-rose-600 dark:text-rose-400" />;
    default:
      return <CircleSlash2 className="h-3.5 w-3.5 text-muted-foreground" />;
  }
}

function signalBadgeTone(direction: string): string {
  switch (direction) {
    case 'increase':
      return 'border-emerald-500/25 bg-emerald-500/10 text-emerald-700 hover:bg-emerald-500/15 dark:text-emerald-300';
    case 'reduce':
      return 'border-amber-500/25 bg-amber-500/10 text-amber-800 hover:bg-amber-500/15 dark:text-amber-200';
    case 'hold':
      return 'border-blue-500/25 bg-blue-500/10 text-blue-700 hover:bg-blue-500/15 dark:text-blue-300';
    case 'attention':
      return 'border-rose-500/25 bg-rose-500/10 text-rose-700 hover:bg-rose-500/15 dark:text-rose-300';
    default:
      return 'border-muted-foreground/25 bg-muted/30 text-muted-foreground hover:bg-muted/40';
  }
}

export function StrategyFleet({
  runs,
  snapshots,
  loading = false,
}: {
  runs: GovernedRunSummary[];
  snapshots: Map<string, StrategyOperationsSnapshot>;
  loading?: boolean;
}) {
  const navigate = useNavigate();
  const access = useAccessControl();
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  // Observer Controls State
  const [marketFilter, setMarketFilter] = useState<MarketFilter>('all');
  const [signalFilter, setSignalFilter] = useState<SignalFilter>('all');
  const [period, setPeriod] = useState<PeriodKey>('all');

  // Signal Drawer State
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const selectedRun = useMemo(
    () => runs.find((r) => r.modelVersionId === selectedRunId) ?? null,
    [runs, selectedRunId],
  );
  const selectedSnapshot = useMemo(
    () => (selectedRun ? snapshots.get(selectedRun.modelVersionId) ?? null : null),
    [selectedRun, snapshots],
  );

  const handleOpenSignal = (run: GovernedRunSummary) => {
    setSelectedRunId(run.modelVersionId);
    setDrawerOpen(true);
  };

  // Filtered Strategy List
  const filteredRuns = useMemo(() => {
    return runs.filter((run) => {
      // Market filter
      if (marketFilter !== 'all' && run.market.toLowerCase() !== marketFilter) {
        return false;
      }

      // Signal filter
      if (signalFilter !== 'all') {
        const snapshot = snapshots.get(run.modelVersionId);
        const summary = summarizeStrategySignal(snapshot);
        if (signalFilter === 'new' && !summary.isNew) {
          return false;
        }
        if (signalFilter === 'attention' && !summary.isAttention) {
          return false;
        }
      }

      return true;
    });
  }, [runs, marketFilter, signalFilter, snapshots]);

  return (
    <section className="space-y-4" aria-label="Formal strategy fleet">
      {/* Observer Controls Toolbar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <select
            id="market"
            aria-label="Market"
            value={marketFilter}
            onChange={(e) => setMarketFilter(e.target.value as MarketFilter)}
            className="rounded-lg border bg-card px-3 py-1.5 text-xs font-medium text-foreground shadow-sm focus:outline-none focus:ring-2 focus:ring-primary"
          >
            <option value="all">All markets</option>
            <option value="us">US</option>
            <option value="cn">CN</option>
          </select>

          <select
            id="filter"
            aria-label="Signal filter"
            value={signalFilter}
            onChange={(e) => setSignalFilter(e.target.value as SignalFilter)}
            className="rounded-lg border bg-card px-3 py-1.5 text-xs font-medium text-foreground shadow-sm focus:outline-none focus:ring-2 focus:ring-primary"
          >
            <option value="all">All signals</option>
            <option value="new">New signals</option>
            <option value="attention">Needs attention</option>
          </select>
        </div>

        <div className="flex items-center gap-1 rounded-lg border bg-muted/20 p-1" aria-label="Performance period">
          {PERIOD_OPTIONS.map((opt) => (
            <button
              key={opt.key}
              type="button"
              data-period={opt.key}
              aria-pressed={period === opt.key}
              onClick={() => setPeriod(opt.key)}
              className={cn(
                'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                period === opt.key
                  ? 'bg-card font-semibold text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Main Table / Fleet Container */}
      <div className="overflow-hidden rounded-2xl border bg-card shadow-sm">
        <div className="hidden grid-cols-[minmax(220px,1.4fr)_100px_130px_100px_minmax(200px,1.2fr)_110px_36px] gap-4 border-b bg-muted/25 px-5 py-3 text-[10px] font-bold uppercase tracking-[0.15em] text-muted-foreground lg:grid">
          <span>Strategy</span>
          <span>Return</span>
          <span>Excess / benchmark</span>
          <span>Drawdown</span>
          <span>Latest signal</span>
          <span>Applicable</span>
          <span />
        </div>

        <div className="divide-y">
          {filteredRuns.map((run) => {
            const snapshot = snapshots.get(run.modelVersionId);
            const requiredTier = snapshot ? access.requiredTier('strategy', snapshot.strategyId) : 'owner';
            const liveLocked = !access.canAccess(requiredTier);
            const summary = summarizeStrategySignal(snapshot);
            const expanded = expandedKey === run.key;

            const totalReturn = metricPercent(run, 'total_return');
            const excessReturn = metricPercent(run, 'excess_return');
            const maxDd = metricPercent(run, 'max_drawdown');
            const sharpe = metricDecimal(run, 'sharpe_ratio');

            const applicableDate = snapshot?.asOf
              ? `${snapshot.asOf}`
              : snapshot?.latestCompletedSession ?? run.evidenceCutoff;

            return (
              <article
                key={run.key}
                className="group px-5 py-4 transition-colors hover:bg-muted/20 lg:grid lg:grid-cols-[minmax(220px,1.4fr)_100px_130px_100px_minmax(200px,1.2fr)_110px_36px] lg:items-center lg:gap-4 lg:py-5"
              >
                {/* 1. Strategy Title and Details */}
                <div className="block w-full text-left lg:contents">
                  <button
                    type="button"
                    onClick={() => navigate(`/strategies/${encodeURIComponent(run.modelVersionId)}`)}
                    className="block w-full text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded-md"
                    aria-label={liveLocked ? `${run.title}, historical evidence public, live operations require ${requiredTier}` : run.title}
                  >
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-base font-semibold hover:text-primary transition-colors">
                        {run.title}
                      </span>
                      {requiredTier !== 'public' && (
                        <span className="inline-flex items-center gap-1 rounded-full border border-primary/25 bg-primary/10 px-2 py-0.5 text-[10px] font-black uppercase tracking-[0.12em] text-primary">
                          <Crown className="h-3 w-3" /> {requiredTier === 'pro' ? 'Pro live' : requiredTier}
                        </span>
                      )}
                    </span>
                    <span className="mt-1 block text-xs text-muted-foreground">
                      {run.market.toUpperCase()} · {run.modelVersionId}
                    </span>
                  </button>

                  {/* Mobile-only metrics preview row */}
                  <div className="mt-2 flex items-center justify-between font-mono text-sm font-semibold tabular-nums lg:hidden">
                    <div className="flex items-center gap-3">
                      <span className={cn(totalReturn.startsWith('+') && 'text-emerald-600 dark:text-emerald-400')}>
                        {totalReturn}
                      </span>
                      <span className="text-xs text-muted-foreground">Ex {excessReturn}</span>
                      <span className="text-xs text-muted-foreground">DD {maxDd}</span>
                    </div>

                    <button
                      type="button"
                      onClick={() => handleOpenSignal(run)}
                      className={cn(
                        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold transition-colors',
                        signalBadgeTone(summary.direction),
                      )}
                    >
                      <SignalStatusIcon direction={summary.direction} />
                      {summary.badgeLabel}
                    </button>
                  </div>

                  {/* Desktop Return */}
                  <div className="hidden lg:block">
                    <span className={cn('font-mono text-sm font-semibold tabular-nums', totalReturn.startsWith('+') && 'text-emerald-600 dark:text-emerald-400')}>
                      {totalReturn}
                    </span>
                    <span className="block text-[11px] text-muted-foreground">
                      {loading ? 'Updating' : 'Formal evidence'}
                    </span>
                  </div>

                  {/* Desktop Excess / benchmark */}
                  <div className="hidden lg:block">
                    <span className="font-mono text-sm font-medium tabular-nums">
                      {excessReturn}
                    </span>
                    <span className="block truncate text-[11px] text-muted-foreground">
                      vs {run.benchmark}
                    </span>
                  </div>

                  {/* Desktop Drawdown */}
                  <div className="hidden lg:block">
                    <span className="font-mono text-sm font-medium tabular-nums text-muted-foreground">
                      {maxDd}
                    </span>
                    <span className="block text-[11px] text-muted-foreground">
                      Max DD
                    </span>
                  </div>
                </div>

                {/* 2. Latest Signal column */}
                <div className="mt-3 lg:mt-0 lg:block hidden">
                  {liveLocked ? (
                    <div className="rounded-lg border border-primary/15 bg-primary/[0.035] p-2">
                      <p className="flex items-center gap-1.5 text-xs font-semibold text-primary">
                        <LockKeyhole className="h-3.5 w-3.5" />
                        Live holdings & signals
                      </p>
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        AlphaEngine {requiredTier === 'pro' ? 'Pro' : requiredTier} unlocks the current-operations layer.
                      </p>
                    </div>
                  ) : (
                    <div>
                      <button
                        type="button"
                        onClick={() => handleOpenSignal(run)}
                        className={cn(
                          'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-primary',
                          signalBadgeTone(summary.direction),
                        )}
                        aria-label={`Inspect signal for ${run.title}: ${summary.badgeLabel}`}
                      >
                        <SignalStatusIcon direction={summary.direction} />
                        {summary.badgeLabel}
                      </button>
                      <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">
                        {summary.summaryNote}
                      </p>
                    </div>
                  )}
                </div>

                {/* 3. Applicable / Freshness Date */}
                <div className="hidden text-xs text-muted-foreground lg:block">
                  <p className="font-medium text-foreground">
                    {summary.isAttention ? (
                      <span className="text-rose-600 dark:text-rose-400">Expired / Stale</span>
                    ) : (
                      applicableDate
                    )}
                  </p>
                  <p className="text-[11px]">
                    {summary.isAttention ? 'Last known cutoff' : 'Model session'}
                  </p>
                </div>

                {/* 4. Action arrow for Desktop */}
                <button
                  type="button"
                  onClick={() => navigate(`/strategies/${encodeURIComponent(run.modelVersionId)}`)}
                  className="hidden h-8 w-8 items-center justify-center rounded-lg text-muted-foreground transition-transform hover:text-primary group-hover:translate-x-0.5 lg:flex"
                  aria-label={`Open ${run.title} strategy detail`}
                >
                  <ArrowRight className="h-4 w-4" />
                </button>

                {/* Mobile accordion toggle & quick links */}
                <div className="mt-3 flex items-center justify-between lg:hidden border-t pt-2">
                  <button
                    type="button"
                    onClick={() => setExpandedKey(expanded ? null : run.key)}
                    aria-expanded={expanded}
                    className="inline-flex min-h-[44px] items-center gap-1.5 text-xs font-semibold text-primary"
                  >
                    {expanded ? 'Hide details' : 'Strategy details'}
                    <ChevronDown className={cn('h-4 w-4 transition-transform', expanded && 'rotate-180')} />
                  </button>

                  <button
                    type="button"
                    onClick={() => navigate(`/strategies/${encodeURIComponent(run.modelVersionId)}`)}
                    className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg text-muted-foreground hover:text-primary"
                    aria-label={`Open ${run.title} strategy detail`}
                  >
                    <ArrowRight className="h-4 w-4" />
                  </button>
                </div>

                {/* Mobile Expanded Drawer Info */}
                {expanded && (
                  <div className="mt-2 space-y-2 rounded-lg border bg-muted/30 p-3 text-xs lg:hidden">
                    <p><span className="font-semibold">Sharpe Ratio:</span> <span className="font-mono tabular-nums">{sharpe}</span></p>
                    <p><span className="font-semibold">Benchmark:</span> {run.benchmark}</p>
                    <p><span className="font-semibold">Allocations:</span> {allocationSummary(snapshot, 'current')} → {allocationSummary(snapshot, 'target')}</p>
                    <p className="text-muted-foreground">Cutoff session: {run.evidenceCutoff}</p>
                    <div className="pt-2">
                      <button
                        type="button"
                        onClick={() => handleOpenSignal(run)}
                        className="inline-flex min-h-[44px] w-full items-center justify-center rounded-lg bg-primary/10 text-xs font-bold text-primary"
                      >
                        Inspect Full Signal & Targets
                      </button>
                    </div>
                  </div>
                )}
              </article>
            );
          })}
        </div>

        {/* Empty state when no strategies match filter */}
        {filteredRuns.length === 0 && (
          <div id="empty" className="p-12 text-center text-sm text-muted-foreground">
            No strategies match these filters.
          </div>
        )}
      </div>

      {/* Footnote matching Observer prototype */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between text-xs text-muted-foreground px-1">
        <span id="count">{filteredRuns.length} strategies · Stable watchlist order</span>
        <span>Model portfolio simulation · Returns are not an investment recommendation</span>
      </div>

      {/* Signal Drawer Modal */}
      <StrategySignalDrawer
        run={selectedRun}
        snapshot={selectedSnapshot}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
      />
    </section>
  );
}
