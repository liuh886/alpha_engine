import { Link } from 'react-router-dom';
import { Sparkline } from '@/components/charts/Sparkline';
import type { ModelRankingIssue } from '@/hooks/useModelRanking';
import {
  RANKING_INDEXES,
  RANKING_MARKET_LABELS,
  formatDate,
  formatPrice,
  formatPriceChange,
  formatReturn,
  type IndexRankingRow,
  type ModelRankingRow,
  type RankingIndexIdentity,
} from '@/lib/model-ranking';
import { lastSessions } from '@/lib/nav-series';
import { cn } from '@/lib/utils';

interface BenchmarkMarketCardsProps {
  rows: ModelRankingRow[];
  loading?: boolean;
  issues?: ModelRankingIssue[];
}

interface CardKeys {
  testId: string;
  suffix: string;
}

/**
 * Stable card hooks. The QQQ and CSI 300 cards keep their original
 * market-keyed testids; the S&P 500 card keeps the `sp500` hook it had before
 * it became a governed identity.
 */
const INDEX_CARD_KEYS: Readonly<Record<string, CardKeys>> = {
  'us:QQQ': { testId: 'benchmark-card-us', suffix: 'us' },
  'us:SPX': { testId: 'benchmark-card-sp500', suffix: 'sp500' },
  'cn:000300': { testId: 'benchmark-card-cn', suffix: 'cn' },
};

function cardKeys(index: RankingIndexIdentity): CardKeys {
  return INDEX_CARD_KEYS[`${index.market}:${index.symbol}`] ?? {
    testId: `benchmark-card-${index.market}-${index.symbol}`,
    suffix: `${index.market}-${index.symbol}`,
  };
}

function signedTone(value: number | null): string {
  if (value === null || !Number.isFinite(value) || value === 0) return 'text-muted-foreground';
  return value > 0 ? 'text-positive' : 'text-negative';
}

function IndexCard({
  index,
  row,
  issue,
  loading,
}: {
  index: RankingIndexIdentity;
  row: IndexRankingRow | null;
  issue?: ModelRankingIssue;
  loading: boolean;
}) {
  const { market, symbol, title } = index;
  const { testId, suffix } = cardKeys(index);
  const last = row?.nav[row.nav.length - 1];
  const cell = row?.cells['1w'];
  const first = row && cell?.display && cell.coverage.firstObservation
    ? row.nav.find((point) => point.date === cell.coverage.firstObservation)
    : undefined;
  const weekChange = first && last && cell?.display ? last.value - first.value : null;
  const weekPct = cell?.display ? cell.value : null;
  const weekTone = weekPct === null || weekPct === 0 ? 'neutral' : weekPct > 0 ? 'positive' : 'negative';
  // A missing row is either an unpublished governed series (the expected state
  // until the governed refresh lands) or a genuine read/parse failure. Keep the
  // two distinguishable in visible and assistive text; never fill in a number.
  const awaiting = issue?.state === 'awaiting_publication' || (!issue && !loading);
  const status = loading && !issue
    ? 'Reading governed market evidence…'
    : awaiting
      ? 'Awaiting governed series'
      : issue?.message ?? 'Awaiting governed series';
  const accessibleName = row
    ? row.stale
      ? `${title} governed market evidence, stale ${row.staleDays} days behind cutoff`
      : `${title} governed market evidence`
    : `${title} governed market evidence unavailable`;

  return (
    <Link
      to={`/securities/${market}/${encodeURIComponent(symbol)}`}
      aria-label={accessibleName}
      title={issue?.message ?? 'Close-to-close price return, not total return.'}
      data-testid={testId}
      data-instrument={`${market}:${symbol}`}
      className="group flex min-h-[104px] flex-col justify-between rounded-lg border bg-card px-4 py-3 shadow-card transition-colors hover:bg-muted/30 focus-visible:ring-2 focus-visible:ring-ring"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-semibold">{title}</span>
        <span className="text-[10px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
          {RANKING_MARKET_LABELS[market]}
        </span>
      </div>
      {row ? (
        <>
          <div className="flex items-end justify-between gap-3">
            <div className="min-w-0">
              <span className="block text-[22px] font-semibold leading-none tabular-nums">
                {formatPrice(last?.value)}
              </span>
              <span className="mt-1 block text-[11px] tabular-nums">
                <span className="font-medium text-muted-foreground">1W </span>
                <span className={cn('font-medium', signedTone(weekPct))}>{formatPriceChange(weekChange)}</span>
                <span className="text-muted-foreground"> · </span>
                <span className={cn('font-medium', signedTone(weekPct))}>{formatReturn(weekPct)}</span>
              </span>
              {/* A displayed 1W return can still carry a coverage basis. Render it
                  in the card instead of a hover-only title so touch and keyboard
                  readers reach the same reason. */}
              {cell?.reason && (
                <span
                  data-testid={`benchmark-reason-${suffix}`}
                  className="mt-0.5 block max-w-full break-words text-[10px] leading-4 text-muted-foreground"
                >
                  {cell.reason}
                </span>
              )}
            </div>
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
          </div>
          <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1 text-[10px] text-muted-foreground">
            <span>As of {formatDate(row.asOf)}</span>
            {row.stale && (
              <span
                data-testid={`benchmark-stale-${suffix}`}
                title={`Evidence cutoff ${row.evidenceCutoff} is ${row.staleDays} calendar days after the last observation ${formatDate(row.asOf)}.`}
                className="inline-flex items-center gap-1 whitespace-nowrap rounded border border-warning/30 bg-warning/10 px-1.5 py-0.5 font-medium text-warning"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-warning" aria-hidden="true" />
                Stale · {row.staleDays}d behind cutoff
              </span>
            )}
            <span>Cutoff {formatDate(row.evidenceCutoff)}</span>
          </div>
        </>
      ) : (
        <div className="min-w-0">
          <span className="block text-[22px] font-semibold leading-none tabular-nums">
            {formatPrice(undefined)}
          </span>
          <span
            data-testid={`benchmark-status-${suffix}`}
            role="status"
            title={issue?.message}
            className={cn(
              'mt-1 block max-w-full break-words text-[11px] leading-snug',
              awaiting ? 'text-muted-foreground' : 'text-warning',
            )}
          >
            {status}
            {awaiting && issue && <span className="sr-only"> {issue.message}</span>}
          </span>
        </div>
      )}
    </Link>
  );
}

/**
 * Governed reference-index strip. QQQ, S&P 500 and CSI 300 each read their own
 * close-to-close market evidence. A missing series stays visibly awaiting its
 * governed publication; no index, ETF or synthetic series is substituted.
 */
export function BenchmarkMarketCards({ rows, loading = false, issues = [] }: BenchmarkMarketCardsProps) {
  return (
    <section aria-label="Benchmark markets" aria-busy={loading} className="space-y-2">
      <div className="grid gap-3 sm:grid-cols-3">
        {RANKING_INDEXES.map((index) => (
          <IndexCard
            key={`${index.market}:${index.symbol}`}
            index={index}
            loading={loading}
            row={rows.find((row): row is IndexRankingRow => row.kind === 'index'
              && row.market === index.market && row.symbol === index.symbol) ?? null}
            issue={issues.find((issue) => issue.id === `index:${index.market}:${index.symbol}`)}
          />
        ))}
      </div>
      <p className="text-[11px] leading-relaxed text-muted-foreground">
        Index cards use governed close-to-close price returns, not total return, and are research evidence
        only — not trade-ready. QQQ is the US strategy benchmark and CSI 300 the China strategy benchmark;
        S&amp;P 500 is a broad US market index reference, not a strategy benchmark. No index is used as a
        cross-market substitute.
      </p>
    </section>
  );
}
