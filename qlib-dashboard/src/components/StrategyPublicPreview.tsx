import { ArrowLeft, BarChart3, Crown, LockKeyhole, ShieldCheck, TrendingUp } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { GovernedRunSummary } from '@/lib/governed-run';
import type { CanonicalMetricV2 } from '@/lib/model-run-bundle-v2';

function metric(run: GovernedRunSummary, id: string): CanonicalMetricV2 | null {
  const metrics = Array.isArray(run.summary.metrics) ? run.summary.metrics : [];
  return (metrics as CanonicalMetricV2[]).find((item) => item.metric_id === id) ?? null;
}

function metricNumber(run: GovernedRunSummary, id: string): number | null {
  const item = metric(run, id);
  return item?.availability_status === 'available' && typeof item.value === 'number' ? item.value : null;
}

function percent(value: number | null, digits = 1): string {
  return value === null ? '—' : `${value >= 0 ? '+' : ''}${(value * 100).toFixed(digits)}%`;
}

function decimal(value: number | null): string {
  return value === null ? '—' : value.toFixed(2);
}

export function StrategyPublicPreview({ run, openAccount }: { run: GovernedRunSummary; openAccount: () => void }) {
  const totalReturn = metricNumber(run, 'total_return');
  const annualizedReturn = metricNumber(run, 'annualized_return');
  const benchmarkReturn = metricNumber(run, 'benchmark_return');
  const sharpe = metricNumber(run, 'sharpe_ratio');
  const maxDrawdown = metricNumber(run, 'max_drawdown');
  const volatility = metricNumber(run, 'annualized_volatility');
  const relativeReturn = totalReturn !== null && benchmarkReturn !== null ? totalReturn - benchmarkReturn : null;

  return (
    <div className="mx-auto max-w-[1320px] space-y-7 pb-16">
      <section className="border-b pb-7">
        <Button asChild variant="ghost" size="sm" className="mb-4 -ml-2 gap-2"><Link to="/strategies"><ArrowLeft className="h-4 w-4" />Strategies</Link></Button>
        <div className="flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
          <div className="max-w-4xl">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{run.market.toUpperCase()}</Badge>
              <Badge variant="outline">Benchmark {run.benchmark}</Badge>
              <Badge variant="secondary">Formal baseline</Badge>
            </div>
            <h1 className="mt-3 text-3xl font-black tracking-tight md:text-5xl">{run.title}</h1>
            <p className="mt-3 max-w-3xl text-sm leading-relaxed text-muted-foreground">
              Formal performance and risk evidence are public. Live holdings, target allocations and current signal drivers remain an AlphaEngine Pro execution surface.
            </p>
          </div>
          <div className="flex items-center gap-2 rounded-xl border bg-card px-4 py-3 text-sm shadow-sm">
            <ShieldCheck className="h-4 w-4 text-emerald-600" />
            <div><p className="font-semibold">Public formal evidence</p><p className="text-xs text-muted-foreground">Cutoff {run.evidenceCutoff}</p></div>
          </div>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(340px,0.7fr)]">
        <div className="overflow-hidden rounded-2xl border bg-card shadow-sm">
          <div className="border-b px-5 py-4">
            <div className="flex items-center gap-2"><TrendingUp className="h-4 w-4 text-primary" /><h2 className="text-sm font-semibold">Formal performance</h2></div>
            <p className="mt-1 text-xs text-muted-foreground">Retained accepted-baseline metrics; no live allocation is exposed here.</p>
          </div>
          <div className="grid gap-px bg-border sm:grid-cols-2 lg:grid-cols-4">
            <Metric label="Total return" value={percent(totalReturn)} emphasis />
            <Metric label="Annualized return" value={percent(annualizedReturn)} />
            <Metric label="Sharpe ratio" value={decimal(sharpe)} />
            <Metric label="Max drawdown" value={percent(maxDrawdown)} />
          </div>
          <div className="grid gap-4 border-t p-5 md:grid-cols-3">
            <Comparison label="Benchmark return" value={percent(benchmarkReturn)} detail={run.benchmark} />
            <Comparison label="Return vs benchmark" value={percent(relativeReturn)} detail="Observed-window difference" />
            <Comparison label="Annualized volatility" value={percent(volatility)} detail="Retained formal metric" />
          </div>
        </div>

        <div className="rounded-2xl border border-primary/20 bg-primary/[0.035] p-5 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2"><Crown className="h-4 w-4 text-primary" /><h2 className="text-sm font-semibold">Pro execution layer</h2></div>
            <LockKeyhole className="h-4 w-4 text-primary" />
          </div>
          <p className="mt-3 text-sm leading-relaxed text-muted-foreground">Unlock the information that turns the research model into an operating decision view.</p>
          <div className="mt-5 divide-y rounded-xl border bg-background/80 px-4">
            <LockedRow label="Current holdings" />
            <LockedRow label="Target allocation & change" />
            <LockedRow label="Current signal drivers" />
            <LockedRow label="Next decision state" />
          </div>
          <Button className="mt-5 w-full" onClick={openAccount}>View AlphaEngine Pro access</Button>
        </div>
      </section>

      <section className="flex flex-col gap-3 rounded-xl border bg-muted/20 p-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <BarChart3 className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
          <div><h2 className="text-sm font-semibold">Performance is the public proof layer</h2><p className="mt-1 text-xs leading-relaxed text-muted-foreground">The model's formal return and risk record remains visible before purchase; AlphaEngine Pro gates the live execution intelligence rather than the headline backtest.</p></div>
        </div>
      </section>
    </div>
  );
}

function Metric({ label, value, emphasis = false }: { label: string; value: string; emphasis?: boolean }) {
  return (
    <div className="bg-card p-5">
      <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-muted-foreground">{label}</p>
      <p className={emphasis ? 'mt-2 text-3xl font-black tabular-nums text-primary' : 'mt-2 text-2xl font-bold tabular-nums'}>{value}</p>
    </div>
  );
}

function Comparison({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 text-lg font-semibold tabular-nums">{value}</p><p className="mt-1 text-[10px] text-muted-foreground">{detail}</p></div>;
}

function LockedRow({ label }: { label: string }) {
  return <div className="flex items-center justify-between py-3 text-xs"><span>{label}</span><LockKeyhole className="h-3.5 w-3.5 text-muted-foreground" /></div>;
}
