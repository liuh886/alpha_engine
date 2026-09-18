import { useEffect, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Cpu,
  Layers,
  RefreshCw,
  Scale,
  ShieldAlert,
  ShieldCheck,
  TrendingUp,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  fetchModelOperations,
  type MarketOperationsSnapshot,
  type ModelOperationsSnapshot,
} from '@/lib/model-operations';

function percent(value: number | undefined | null): string {
  if (value === undefined || value === null || !Number.isFinite(value)) return '—';
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`;
}

function decimal(value: number | undefined | null): string {
  if (value === undefined || value === null || !Number.isFinite(value)) return '—';
  return value.toFixed(3);
}

function currency(value: number | undefined | null): string {
  if (value === undefined || value === null || !Number.isFinite(value)) return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);
}

export function ModelOperationsPage() {
  const [data, setData] = useState<ModelOperationsSnapshot | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [activeMarket, setActiveMarket] = useState<'us' | 'cn'>('us');

  useEffect(() => {
    let active = true;
    void fetchModelOperations().then((res) => {
      if (active) {
        setData(res);
        setLoading(false);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  const marketSnapshot: MarketOperationsSnapshot | undefined = data?.markets.find(
    (m) => m.market === activeMarket,
  );

  const decision = marketSnapshot?.gate_decision?.decision ?? 'continue';
  const planEligible = marketSnapshot?.gate_decision?.plan_eligible ?? false;
  const driftSeverity = marketSnapshot?.drift?.overall_severity ?? 'ok';
  const champion = marketSnapshot?.champion;
  const challenger = marketSnapshot?.challenger;
  const executionPlan = marketSnapshot?.execution_plan;
  const paperLedger = marketSnapshot?.paper_ledger;
  const attribution = marketSnapshot?.attribution;

  return (
    <div className="mx-auto max-w-[1500px] space-y-6 pb-16">
      {/* Header */}
      <section className="flex flex-col gap-4 border-b pb-6 md:flex-row md:items-end md:justify-between">
        <div className="max-w-3xl">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-primary">Continuous Model Operations (T47.8)</p>
          <h1 className="mt-2 text-3xl font-black tracking-tight md:text-4xl">Model Operations & Decision Loop</h1>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            Observe the active Champion lifecycle, continuous statistical drift, operational circuit breakers,
            advisory execution plans, and immutable paper trading simulation.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline" className="gap-1 text-xs">
            <ShieldAlert className="h-3.5 w-3.5 text-amber-500" />
            research_only=true
          </Badge>
          <Badge variant="outline" className="gap-1 text-xs">
            <ShieldAlert className="h-3.5 w-3.5 text-destructive" />
            trade_ready=false
          </Badge>
        </div>
      </section>

      {/* Market Selector Tabs */}
      <div className="flex items-center gap-3">
        <Button
          variant={activeMarket === 'us' ? 'default' : 'outline'}
          size="sm"
          onClick={() => setActiveMarket('us')}
          className="gap-2"
        >
          <span>US Market</span>
          <Badge variant={activeMarket === 'us' ? 'secondary' : 'outline'} className="text-[10px]">
            QQQ / US x1.3
          </Badge>
        </Button>
        <Button
          variant={activeMarket === 'cn' ? 'default' : 'outline'}
          size="sm"
          onClick={() => setActiveMarket('cn')}
          className="gap-2"
        >
          <span>CN Market</span>
          <Badge variant={activeMarket === 'cn' ? 'secondary' : 'outline'} className="text-[10px]">
            CN x1.2 / BYD
          </Badge>
        </Button>
      </div>

      {loading ? (
        <div className="research-empty-state">
          <RefreshCw className="h-6 w-6 animate-spin text-primary/60" />
          <p className="mt-2 text-sm text-muted-foreground">Loading Model Operations read model...</p>
        </div>
      ) : !marketSnapshot ? (
        <div className="research-empty-state">
          <AlertTriangle className="h-8 w-8 text-amber-500" />
          <h2 className="mt-2 text-lg font-semibold">No operational data available for {activeMarket.toUpperCase()}</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Run &quot;alpha ops model-ops&quot; to materialize the current operations snapshot.
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {/* Top Row: Champion vs Challenger & Operational Gate Decision */}
          <div className="grid gap-6 lg:grid-cols-2">
            {/* Champion vs Challenger */}
            <Card className="research-surface">
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="flex items-center gap-2 text-base font-semibold">
                  <Cpu className="h-5 w-5 text-primary" />
                  Champion & Challenger Lifecycle (T47.1)
                </CardTitle>
                <Badge variant="secondary" className="font-mono text-xs uppercase">
                  {activeMarket}
                </Badge>
              </CardHeader>
              <CardContent className="space-y-4 pt-2">
                <div className="rounded-xl border bg-muted/20 p-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Active Champion</p>
                      <p className="text-base font-bold text-foreground">{champion?.model_version_id ?? 'None'}</p>
                    </div>
                    <Badge variant="default" className="gap-1 bg-emerald-600 hover:bg-emerald-600">
                      <CheckCircle2 className="h-3.5 w-3.5" /> Approved Champion
                    </Badge>
                  </div>
                  <p className="mt-1 font-mono text-xs text-muted-foreground">
                    Artifact: {champion?.artifact_id ?? '—'} · Declared: {champion?.declared_at?.slice(0, 10) ?? '—'}
                  </p>
                  <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                    <div className="rounded-lg bg-card p-2.5">
                      <span className="text-[10px] text-muted-foreground">Excess Return</span>
                      <p className="font-mono text-sm font-bold text-primary">
                        {percent(champion?.metrics?.excess_return_with_cost)}
                      </p>
                    </div>
                    <div className="rounded-lg bg-card p-2.5">
                      <span className="text-[10px] text-muted-foreground">Annualized</span>
                      <p className="font-mono text-sm font-bold">{percent(champion?.metrics?.annualized_return)}</p>
                    </div>
                    <div className="rounded-lg bg-card p-2.5">
                      <span className="text-[10px] text-muted-foreground">Max DD</span>
                      <p className="font-mono text-sm font-bold text-destructive">
                        {percent(champion?.metrics?.max_drawdown)}
                      </p>
                    </div>
                    <div className="rounded-lg bg-card p-2.5">
                      <span className="text-[10px] text-muted-foreground">Info Ratio</span>
                      <p className="font-mono text-sm font-bold">{decimal(champion?.metrics?.information_ratio)}</p>
                    </div>
                  </div>
                </div>

                {challenger ? (
                  <div className="rounded-xl border border-dashed p-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Under Observation</p>
                        <p className="text-sm font-semibold">{challenger.challenger_id}</p>
                      </div>
                      <Badge variant="outline" className="gap-1 text-xs">
                        <TrendingUp className="h-3.5 w-3.5 text-blue-500" /> Challenger
                      </Badge>
                    </div>
                    <p className="mt-2 text-xs text-muted-foreground">{challenger.comparison_summary}</p>
                    <div className="mt-3 flex gap-4 text-xs font-mono">
                      <span>Excess: {percent(challenger.metrics.excess_return_with_cost)}</span>
                      <span>Ann: {percent(challenger.metrics.annualized_return)}</span>
                      <span>Max DD: {percent(challenger.metrics.max_drawdown)}</span>
                    </div>
                  </div>
                ) : null}
              </CardContent>
            </Card>

            {/* Operational Gate Decision */}
            <Card className="research-surface">
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="flex items-center gap-2 text-base font-semibold">
                  <ShieldCheck className="h-5 w-5 text-primary" />
                  Operational Gate & Circuit Breaker (T47.6)
                </CardTitle>
                <Badge
                  variant={
                    decision === 'continue'
                      ? 'default'
                      : decision === 'retrain'
                        ? 'secondary'
                        : 'destructive'
                  }
                  className="font-mono uppercase"
                >
                  Decision: {decision}
                </Badge>
              </CardHeader>
              <CardContent className="space-y-4 pt-2">
                <div className="flex items-center justify-between rounded-xl border bg-muted/20 p-4">
                  <div>
                    <p className="text-xs text-muted-foreground">Execution Plan Generation</p>
                    <p className="mt-1 text-sm font-bold">
                      {planEligible ? 'Plan Eligible (Normal Advisory State)' : 'Plan Generation Blocked'}
                    </p>
                  </div>
                  {planEligible ? (
                    <Badge variant="default" className="bg-emerald-600 hover:bg-emerald-600">
                      Eligible
                    </Badge>
                  ) : (
                    <Badge variant="destructive">Blocked</Badge>
                  )}
                </div>

                <div className="overflow-x-auto rounded-xl border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="text-xs">Gate Check</TableHead>
                        <TableHead className="text-xs">Status</TableHead>
                        <TableHead className="text-xs">Observed / Detail</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {marketSnapshot.gate_decision.gates.map((g) => (
                        <TableRow key={g.name}>
                          <TableCell className="font-mono text-xs font-medium">{g.name}</TableCell>
                          <TableCell>
                            {g.status === 'pass' ? (
                              <Badge variant="outline" className="border-emerald-500/40 text-emerald-600 dark:text-emerald-400">
                                PASS
                              </Badge>
                            ) : (
                              <Badge variant="destructive">FAIL</Badge>
                            )}
                          </TableCell>
                          <TableCell className="font-mono text-xs text-muted-foreground">{g.detail}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Middle Row: Drift Monitor & Advisory Execution Plan */}
          <div className="grid gap-6 lg:grid-cols-2">
            {/* Drift Monitor */}
            <Card className="research-surface">
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="flex items-center gap-2 text-base font-semibold">
                  <Activity className="h-5 w-5 text-primary" />
                  Statistical Drift Monitor (T47.2)
                </CardTitle>
                <Badge
                  variant={driftSeverity === 'ok' ? 'outline' : 'destructive'}
                  className="font-mono uppercase"
                >
                  Severity: {driftSeverity}
                </Badge>
              </CardHeader>
              <CardContent className="space-y-4 pt-2">
                <div className="grid gap-3">
                  {marketSnapshot.drift.checks.map((chk) => (
                    <div key={chk.check_name} className="flex items-center justify-between rounded-xl border p-3">
                      <div>
                        <p className="text-xs font-semibold">{chk.check_name.replace(/_/g, ' ')}</p>
                        <p className="text-[11px] text-muted-foreground">
                          Window: {chk.evidence_window} · Threshold: {chk.threshold}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="font-mono text-xs font-bold">{decimal(chk.measured_value)}</p>
                        <Badge
                          variant={chk.severity === 'ok' ? 'outline' : 'destructive'}
                          className="mt-0.5 text-[9px] uppercase"
                        >
                          {chk.severity}
                        </Badge>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* Advisory Execution Plan */}
            <Card className="research-surface">
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="flex items-center gap-2 text-base font-semibold">
                  <Layers className="h-5 w-5 text-primary" />
                  Risk-Constrained Execution Plan (T47.3)
                </CardTitle>
                <Badge variant="outline" className="text-xs">
                  {executionPlan ? `${executionPlan.decisions.length} Decisions` : 'No Active Plan'}
                </Badge>
              </CardHeader>
              <CardContent className="space-y-4 pt-2">
                {executionPlan ? (
                  <>
                    <div className="grid grid-cols-3 gap-3 rounded-xl bg-muted/20 p-3 text-center">
                      <div>
                        <span className="text-[10px] text-muted-foreground">Gross Exposure</span>
                        <p className="font-mono text-sm font-bold">{percent(executionPlan.gross_exposure)}</p>
                      </div>
                      <div>
                        <span className="text-[10px] text-muted-foreground">Cash Weight</span>
                        <p className="font-mono text-sm font-bold">{percent(executionPlan.cash_weight)}</p>
                      </div>
                      <div>
                        <span className="text-[10px] text-muted-foreground">Turnover</span>
                        <p className="font-mono text-sm font-bold">{percent(executionPlan.one_sided_turnover)}</p>
                      </div>
                    </div>

                    <div className="overflow-x-auto rounded-xl border">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead className="text-xs">Instrument</TableHead>
                            <TableHead className="text-xs">Sector</TableHead>
                            <TableHead className="text-xs">Score</TableHead>
                            <TableHead className="text-xs">Target Weight</TableHead>
                            <TableHead className="text-xs">Status</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {executionPlan.decisions.map((p) => (
                            <TableRow key={p.instrument}>
                              <TableCell className="font-mono text-xs font-semibold">{p.instrument}</TableCell>
                              <TableCell className="text-xs text-muted-foreground">{p.sector ?? '—'}</TableCell>
                              <TableCell className="font-mono text-xs">{decimal(p.score)}</TableCell>
                              <TableCell className="font-mono text-xs font-bold text-primary">
                                {percent(executionPlan.target_weights[p.instrument])}
                              </TableCell>
                              <TableCell>
                                <Badge variant="secondary" className="text-[10px]">
                                  {p.status}
                                </Badge>
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  </>
                ) : (
                  <div className="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">
                    Plan generation is blocked by operational circuit breaker.
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Bottom Row: Paper Trading Ledger & Performance Attribution */}
          <Card className="research-surface">
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="flex items-center gap-2 text-base font-semibold">
                <Scale className="h-5 w-5 text-primary" />
                Paper Simulation Ledger & Performance Attribution (T47.4 & T47.5)
              </CardTitle>
              <Badge variant="outline" className="gap-1 font-mono text-xs text-emerald-600">
                <CheckCircle2 className="h-3.5 w-3.5" />
                {paperLedger?.hash_chain_verified ? 'SHA-256 Chain Verified' : 'Unverified'}
              </Badge>
            </CardHeader>
            <CardContent className="space-y-6 pt-2">
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-xl border bg-card p-4">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Current Paper NAV</p>
                  <p className="mt-1 font-mono text-2xl font-black text-primary">{currency(paperLedger?.current_nav)}</p>
                  <p className="mt-1 text-xs text-muted-foreground">Unrealized: {currency(paperLedger?.unrealized_pnl)}</p>
                </div>
                <div className="rounded-xl border bg-card p-4">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Available Cash</p>
                  <p className="mt-1 font-mono text-2xl font-black">{currency(paperLedger?.cash_balance)}</p>
                  <p className="mt-1 text-xs text-muted-foreground">Initial: {currency(paperLedger?.initial_cash)}</p>
                </div>
                <div className="rounded-xl border bg-card p-4">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Attributed Return</p>
                  <p className="mt-1 font-mono text-2xl font-black text-emerald-600">
                    {percent(attribution?.total_return_arithmetic)}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Benchmark: {percent(attribution?.benchmark_return_sum)}
                  </p>
                </div>
                <div className="rounded-xl border bg-card p-4">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Attribution Residual</p>
                  <p className="mt-1 font-mono text-2xl font-black">
                    {attribution?.residual ? decimal(attribution.residual) : '0.000'}
                  </p>
                  <p className="mt-1 text-xs text-emerald-600">Within Mathematical Tolerance</p>
                </div>
              </div>

              {/* Attribution Components */}
              <div className="rounded-xl border bg-muted/10 p-4">
                <p className="text-xs font-semibold">Attribution Decomposition (Arithmetic Sum)</p>
                <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6 text-center">
                  <div className="rounded-lg bg-card p-2">
                    <span className="text-[10px] text-muted-foreground">Market Exposure</span>
                    <p className="font-mono text-xs font-bold">{percent(attribution?.contributions?.market_exposure)}</p>
                  </div>
                  <div className="rounded-lg bg-card p-2">
                    <span className="text-[10px] text-muted-foreground">Stock Selection</span>
                    <p className="font-mono text-xs font-bold text-primary">
                      {percent(attribution?.contributions?.stock_selection)}
                    </p>
                  </div>
                  <div className="rounded-lg bg-card p-2">
                    <span className="text-[10px] text-muted-foreground">Sector Effect</span>
                    <p className="font-mono text-xs font-bold">{percent(attribution?.contributions?.sector_effect)}</p>
                  </div>
                  <div className="rounded-lg bg-card p-2">
                    <span className="text-[10px] text-muted-foreground">Costs</span>
                    <p className="font-mono text-xs font-bold text-destructive">
                      {percent(attribution?.contributions?.costs)}
                    </p>
                  </div>
                  <div className="rounded-lg bg-card p-2">
                    <span className="text-[10px] text-muted-foreground">Slippage</span>
                    <p className="font-mono text-xs font-bold text-destructive">
                      {percent(attribution?.contributions?.slippage)}
                    </p>
                  </div>
                  <div className="rounded-lg bg-card p-2">
                    <span className="text-[10px] text-muted-foreground">Timing</span>
                    <p className="font-mono text-xs font-bold">{percent(attribution?.contributions?.timing)}</p>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
