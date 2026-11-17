import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Info } from 'lucide-react';
import { formatDate, formatReturn } from '@/lib/metrics';
import {
  STOCK_RANKING_LIMIT,
  STOCK_RANKING_MARKET_LABELS,
  STOCK_RANKING_PERIODS,
  formatStockRankingPeriod,
  rankStockRows,
  type RankedStockRow,
  type StockRankingIssue,
  type StockRankingMarket,
  type StockRankingPeriod,
  type StockRankingsProjection,
} from '@/lib/stock-rankings';
import { cn } from '@/lib/utils';

export interface StockRankingsSectionProps {
  projections: Partial<Record<StockRankingMarket, StockRankingsProjection>>;
  loading?: boolean;
  issues?: StockRankingIssue[];
}

const MARKETS: readonly StockRankingMarket[] = ['us', 'cn'];

function signedTone(value: number | null): string {
  if (value === null || !Number.isFinite(value) || value === 0) return 'text-muted-foreground';
  return value > 0 ? 'text-positive' : 'text-negative';
}

function panelTitle(market: StockRankingMarket): string {
  return `${STOCK_RANKING_MARKET_LABELS[market]} stocks · Top ${STOCK_RANKING_LIMIT}`;
}

function StockRow({
  row,
  market,
  period,
}: {
  row: RankedStockRow;
  market: StockRankingMarket;
  period: StockRankingPeriod;
}) {
  const missing = row.selected.value === null;
  return (
    <li>
      <Link
        to={row.href}
        data-testid={`stock-row-${market}-${row.symbol}`}
        data-stale={row.stale ? 'true' : 'false'}
        className={cn(
          'grid min-h-11 grid-cols-[2rem_minmax(0,1fr)_auto] items-start gap-x-2 px-3 py-1.5 transition-colors hover:bg-muted/30 focus-visible:bg-muted/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
          row.stale && 'bg-warning/[0.04]',
        )}
      >
        <span className="pt-0.5 text-[11px] tabular-nums text-muted-foreground">{row.rank}</span>
        <span className="min-w-0">
          <span className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
            <span className="text-sm font-semibold">{row.symbol}</span>
            {row.name && row.name !== row.symbol && (
              <span className="max-w-[150px] truncate text-xs text-muted-foreground" title={row.name}>
                {row.name}
              </span>
            )}
            {row.stale && (
              <span
                data-testid={`stock-stale-${market}-${row.symbol}`}
                title={`Evidence cutoff ${row.cutoff} is ${row.staleDays} calendar days after the last observation ${row.asOf}.`}
                className="inline-flex items-center gap-1 whitespace-nowrap rounded border border-warning/30 bg-warning/10 px-1.5 py-0.5 text-[10px] font-medium text-warning"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-warning" aria-hidden="true" />
                Stale · {row.staleDays}d behind cutoff
              </span>
            )}
          </span>
          <span className="mt-0.5 block text-[10px] text-muted-foreground">As of {formatDate(row.asOf)}</span>
          {row.selected.reason && (
            <span
              data-testid={missing
                ? `stock-missing-${market}-${row.symbol}`
                : `stock-basis-${market}-${row.symbol}`}
              className="mt-0.5 flex items-start gap-1 text-[10px] leading-4 text-muted-foreground"
            >
              {missing && <Info className="mt-0.5 h-3 w-3 shrink-0" aria-hidden="true" />}
              <span>{row.selected.reason}</span>
            </span>
          )}
        </span>
        <span className={cn('pt-0.5 text-right text-sm font-medium tabular-nums', signedTone(row.selected.value))}>
          {formatReturn(row.selected.value)}
          <span className="sr-only"> {formatStockRankingPeriod(period)} price return</span>
        </span>
      </Link>
    </li>
  );
}

function StockRankingPanel({
  market,
  projection,
  loading,
  issue,
  period,
}: {
  market: StockRankingMarket;
  projection?: StockRankingsProjection;
  loading: boolean;
  issue?: StockRankingIssue;
  period: StockRankingPeriod;
}) {
  const label = STOCK_RANKING_MARKET_LABELS[market];
  const titleId = `stock-rankings-${market}-title`;
  const rows = useMemo(
    () => (projection ? rankStockRows(projection, period) : []),
    [projection, period],
  );
  return (
    <section
      aria-labelledby={titleId}
      data-testid={`stock-ranking-${market}`}
      className="overflow-hidden rounded-xl border bg-card shadow-card"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1 border-b bg-muted/20 px-3 py-2">
        <h3 id={titleId} className="text-sm font-semibold">{panelTitle(market)}</h3>
        <span className="text-[10px] text-muted-foreground">
          {projection ? `Cutoff ${formatDate(projection.cutoff)}` : 'Cutoff unavailable'}
        </span>
      </header>
      {loading ? (
        <p role="status" data-testid={`stock-ranking-loading-${market}`} className="px-3 py-4 text-sm text-muted-foreground">
          Reading {label} stock rankings…
        </p>
      ) : !projection ? (
        <p role="status" data-testid={`stock-ranking-unavailable-${market}`} className="px-3 py-4 text-sm text-muted-foreground">
          {issue?.message ?? `${label} stock rankings are unavailable.`}
        </p>
      ) : rows.length === 0 ? (
        <p data-testid={`stock-ranking-empty-${market}`} className="px-3 py-4 text-sm text-muted-foreground">
          No {label} candidates have a projected return.
        </p>
      ) : (
        <ol className="divide-y" aria-label={`${label} candidates ranked by ${formatStockRankingPeriod(period)} price return`}>
          {rows.map((row) => (
            <StockRow key={row.symbol} row={row} market={market} period={period} />
          ))}
        </ol>
      )}
    </section>
  );
}

/**
 * Two independent per-market Top-20 lists sharing one horizon control. A row
 * always links within its own market and always shows its own observed as-of
 * date; missing coverage stays a visible dash plus reason. No model signal and
 * no cross-market comparison enters this section.
 */
export function StockRankingsSection({
  projections,
  loading = false,
  issues = [],
}: StockRankingsSectionProps) {
  const [period, setPeriod] = useState<StockRankingPeriod>('1m');
  return (
    <section
      aria-label="Stock rankings"
      aria-busy={loading}
      data-testid="stock-rankings"
      className="space-y-3"
    >
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="font-semibold">Stock rankings</h2>
          <p data-testid="stock-rankings-caption" className="mt-1 max-w-3xl text-xs leading-relaxed text-muted-foreground">
            Close-to-close price return, not total return. Ranked within each market; not a recommendation.
          </p>
        </div>
        <div role="group" aria-label="Stock ranking horizon" className="flex flex-wrap items-center gap-1.5">
          <span className="px-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Horizon
          </span>
          {STOCK_RANKING_PERIODS.map((candidate) => (
            <button
              key={candidate}
              type="button"
              data-testid={`stock-horizon-${candidate}`}
              aria-pressed={period === candidate}
              onClick={() => setPeriod(candidate)}
              className={cn(
                'min-h-9 min-w-9 rounded-md border px-2.5 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                period === candidate
                  ? 'border-primary/40 bg-primary/10 text-foreground'
                  : 'bg-card text-muted-foreground hover:text-foreground',
              )}
            >
              {formatStockRankingPeriod(candidate)}
            </button>
          ))}
        </div>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        {MARKETS.map((market) => (
          <StockRankingPanel
            key={market}
            market={market}
            projection={projections[market]}
            loading={loading}
            issue={issues.find((issue) => issue.market === market)}
            period={period}
          />
        ))}
      </div>
      <p className="text-[11px] leading-relaxed text-muted-foreground">
        Each panel ranks only its own market's selected-pool candidates. Benchmarks, auxiliary instruments and
        reference indices are excluded. A horizon without full observed coverage shows — with its reason
        rather than an interpolated value.
      </p>
    </section>
  );
}
