import { Link } from 'react-router-dom';
import { Sparkline } from '@/components/charts/Sparkline';
import type { ModelRankingIssue } from '@/hooks/useModelRanking';
import {
  RANKING_INDEX_SYMBOLS,
  RANKING_INDEX_TITLES,
  RANKING_MARKET_LABELS,
  formatDate,
  formatPrice,
  formatPriceChange,
  formatReturn,
  type IndexRankingRow,
  type ModelRankingRow,
  type RankingMarket,
} from '@/lib/model-ranking';
import { lastSessions } from '@/lib/nav-series';
import { cn } from '@/lib/utils';

interface BenchmarkMarketCardsProps {
  rows: ModelRankingRow[];
  loading?: boolean;
  issues?: ModelRankingIssue[];
}

const MARKETS: RankingMarket[] = ['us', 'cn'];

function signedTone(value: number | null): string {
  if (value === null || !Number.isFinite(value) || value === 0) return 'text-muted-foreground';
  return value > 0 ? 'text-positive' : 'text-negative';
}

function IndexCard({
  market,
  row,
  issue,
  loading,
}: {
  market: RankingMarket;
  row: IndexRankingRow | null;
  issue?: ModelRankingIssue;
  loading: boolean;
}) {
  const title = RANKING_INDEX_TITLES[market];
  const symbol = RANKING_INDEX_SYMBOLS[market];
  const last = row?.nav[row.nav.length - 1];
  const cell = row?.cells['1w'];
  const first = row && cell?.display && cell.coverage.firstObservation
    ? row.nav.find((point) => point.date === cell.coverage.firstObservation)
    : undefined;
  const weekChange = first && last && cell?.display ? last.value - first.value : null;
  const weekPct = cell?.display ? cell.value : null;
  const weekTone = weekPct === null || weekPct === 0 ? 'neutral' : weekPct > 0 ? 'positive' : 'negative';
  const unavailable = issue?.message ?? (loading && !row ? 'Reading governed market evidence…' : cell?.reason);

  return (
    <Link
      to={`/securities/${market}/${encodeURIComponent(symbol)}`}
      aria-label={row?.stale
        ? `${title} governed market evidence, stale ${row.staleDays} days behind cutoff`
        : `${title} governed market evidence`}
      title="Close-to-close price return, not total return."
      data-testid={`benchmark-card-${market}`}
      className="group flex min-h-[104px] flex-col justify-between rounded-lg border bg-card px-4 py-3 shadow-card transition-colors hover:bg-muted/30 focus-visible:ring-2 focus-visible:ring-ring"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-semibold">{title}</span>
        <span className="text-[10px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
          {RANKING_MARKET_LABELS[market]}
        </span>
      </div>
      <div className="flex items-end justify-between gap-3">
        <div className="min-w-0">
          <span className="block text-[22px] font-semibold leading-none tabular-nums">
            {formatPrice(last?.value)}
          </span>
          <span
            className="mt-1 block text-[11px] tabular-nums"
            title={cell?.reason}
          >
            <span className="font-medium text-muted-foreground">1W </span>
            <span className={cn('font-medium', signedTone(weekPct))}>{formatPriceChange(weekChange)}</span>
            <span className="text-muted-foreground"> · </span>
            <span className={cn('font-medium', signedTone(weekPct))}>{formatReturn(weekPct)}</span>
          </span>
        </div>
        {row && (
          <span className="flex shrink-0 flex-col items-end gap-0.5">
            <Sparkline
              nav={lastSessions(row.nav, 6)}
              width={64}
              height={24}
              showEndpoint
              tone={weekTone}
            />
            <span className="text-[9px] uppercase tracking-[0.08em] text-muted-foreground">6 sessions</span>
          </span>
        )}
      </div>
      <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1 text-[10px] text-muted-foreground">
        <span>As of {formatDate(row?.asOf)}</span>
        {row?.stale && (
          <span
            data-testid={`benchmark-stale-${market}`}
            title={`Evidence cutoff ${row.evidenceCutoff} is ${row.staleDays} calendar days after the last observation ${formatDate(row.asOf)}.`}
            className="inline-flex items-center gap-1 whitespace-nowrap rounded border border-warning/30 bg-warning/10 px-1.5 py-0.5 font-medium text-warning"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-warning" aria-hidden="true" />
            Stale · {row.staleDays}d behind cutoff
          </span>
        )}
        <span>Cutoff {formatDate(row?.evidenceCutoff)}</span>
      </div>
      {unavailable && !row && (
        <span
          data-testid={`benchmark-status-${market}`}
          role="status"
          title={unavailable}
          className={cn(
            'mt-1 block text-[11px] leading-snug',
            issue ? 'text-warning' : 'text-muted-foreground',
          )}
        >
          {issue ? 'Governed market evidence unavailable.' : unavailable}
          {issue && <span className="sr-only"> {unavailable}</span>}
        </span>
      )}
    </Link>
  );
}

function SP500Card() {
  return (
    <div
      data-testid="benchmark-card-sp500"
      role="group"
      aria-label="S&P 500 not governed"
      className="flex min-h-[104px] flex-col justify-between rounded-lg border border-dashed bg-muted/20 px-4 py-3"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-semibold text-muted-foreground">S&amp;P 500</span>
        <span className="text-[10px] font-medium uppercase tracking-[0.12em] text-muted-foreground">US</span>
      </div>
      <div>
        <span className="block text-sm font-semibold">Not governed</span>
        <span className="mt-0.5 block text-[11px] leading-snug text-muted-foreground">
          No governed S&amp;P 500 price series or reference instrument is published.
        </span>
      </div>
      <Link to="/system" className="w-fit text-[11px] text-primary underline">
        Review governance
      </Link>
    </div>
  );
}

/**
 * Governed baseline strip. QQQ and CSI 300 use close-to-close market-evidence
 * closes; SP500 is explicitly unavailable rather than substituted.
 */
export function BenchmarkMarketCards({ rows, loading = false, issues = [] }: BenchmarkMarketCardsProps) {
  return (
    <section aria-label="Benchmark markets" aria-busy={loading} className="space-y-2">
      <div className="grid gap-3 sm:grid-cols-3">
        {MARKETS.map((market) => (
          <IndexCard
            key={market}
            market={market}
            loading={loading}
            row={rows.find((row): row is IndexRankingRow => row.kind === 'index' && row.market === market) ?? null}
            issue={issues.find((issue) => issue.id === `index:${market}:${RANKING_INDEX_SYMBOLS[market]}`)}
          />
        ))}
        <SP500Card />
      </div>
      <p className="text-[11px] leading-relaxed text-muted-foreground">
        Index cards use governed close-to-close price returns, not total return. QQQ is the US baseline and
        CSI 300 is the China baseline; neither is used as a cross-market substitute.
      </p>
    </section>
  );
}
