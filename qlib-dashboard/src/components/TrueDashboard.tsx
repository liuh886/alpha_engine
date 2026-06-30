/**
 * @deprecated TrueDashboard is deprecated and will be removed in a follow-up
 * cleanup PR once all consumers have been updated.
 *
 * This component originally maintained its own layout with duplicate
 * PerformanceCharts / PositionsTable / Attribution rendering.  All of that
 * logic now lives in Dashboard.tsx which is the single source of truth.
 *
 * Migration: replace <TrueDashboard model={m} report={r} positions={p} />
 * with <Dashboard data={backtestData} params={modelParams} />
 * where `backtestData` is the fully-parsed BacktestData object.
 */
import { lookupMetricValueByKey } from "@/types/metrics";
import { PerformanceCharts } from '@/components/PerformanceCharts';
import { PositionsTable } from '@/components/PositionsTable';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Placeholder } from '@/components/Placeholder';
import { Badge } from '@/components/ui/badge';
import { Cpu, FlaskConical, ShieldAlert, AlertTriangle } from 'lucide-react';
import { Attribution } from '@/components/Attribution';
import { HoldingsSummary } from '@/components/HoldingsSummary';

export function TrueDashboard({ model, report, positions }: { model: any, report: any[], positions: any[] }) {
  const bestModel = model;

  return (
    <div className="space-y-6 max-w-[1400px] mx-auto pb-16">
      <div className="border-b pb-4">
        <h1 className="text-4xl font-black tracking-tight text-foreground">Model Dashboard</h1>
        <p className="text-muted-foreground mt-2 font-medium">Detailed performance metrics for {bestModel?.name || 'Selected Model'}.</p>
        <p className="mt-1 text-xs text-yellow-600 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-700 rounded px-2 py-1 inline-block">
          ⚠️ This view is deprecated — use the Model Dashboard instead.
        </p>
      </div>

      {/* MIDDLE LAYER: Model & Risk Snapshot */}
      <h2 className="text-lg font-bold uppercase tracking-widest text-muted-foreground mt-8 mb-4">Model & Risk</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card className="bg-card shadow-md border-border/50 transition-colors hover:border-primary/30">
          <CardHeader className="pb-3 border-b flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-bold flex items-center gap-2 uppercase tracking-wider text-muted-foreground">
              <Cpu className="h-4 w-4" /> Top Model
            </CardTitle>
            <Badge variant="outline" className="font-mono text-[10px] uppercase border-primary text-primary">Champion</Badge>
          </CardHeader>
          <CardContent className="pt-5 space-y-4">
            {bestModel ? (
              <>
                <div>
                  <span className="text-lg font-black truncate block mb-1">{bestModel.name}</span>
                  <span className="text-[10px] text-muted-foreground font-mono uppercase tracking-widest block">{bestModel.id.slice(0,18)}</span>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <span className="text-muted-foreground text-[10px] font-bold uppercase tracking-wider block">Return</span>
                    <span data-testid="metric-return" className="font-mono text-lg font-black text-green-500">
                      {((lookupMetricValueByKey(bestModel.backtest.metrics, "Annualized Return") ?? 0) * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div>
                    <span className="text-muted-foreground text-[10px] font-bold uppercase tracking-wider block">Sharpe</span>
                    <span data-testid="metric-sharpe" className="font-mono text-lg font-black">
                      {(lookupMetricValueByKey(bestModel.backtest.metrics, "Sharpe Ratio") ?? 0).toFixed(2)}
                    </span>
                  </div>
                </div>
              </>
            ) : (
              <Placeholder icon={Cpu} title="No Models" description="No models found in the registry." />
            )}
          </CardContent>
        </Card>

        <Card className="bg-card shadow-md border-border/50 transition-colors hover:border-primary/30">
          <CardHeader className="pb-3 border-b flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-bold flex items-center gap-2 uppercase tracking-wider text-muted-foreground">
              <FlaskConical className="h-4 w-4" /> Latest Backtest
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-5 space-y-4">
            {bestModel ? (
              <>
                <div>
                  <span className="text-xs text-muted-foreground uppercase font-bold tracking-widest block mb-1">Win Rate</span>
                  <span className="font-mono text-lg font-black">
                    {((lookupMetricValueByKey(bestModel.backtest.metrics, "Win Rate") ?? 0) * 100).toFixed(1)}%
                  </span>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground uppercase font-bold tracking-widest block mb-1">Market</span>
                  <Badge variant="secondary" className="font-mono text-[10px]">{bestModel.market}</Badge>
                </div>
              </>
            ) : (
              <Placeholder icon={FlaskConical} title="N/A" description="Awaiting model selection." />
            )}
          </CardContent>
        </Card>

        <Card className="bg-card shadow-md border-border/50 transition-colors hover:border-primary/30">
          <CardHeader className="pb-3 border-b flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-bold flex items-center gap-2 uppercase tracking-wider text-muted-foreground">
              <ShieldAlert className="h-4 w-4" /> Risk Snapshot
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-5 space-y-4">
            {bestModel ? (
              <>
                <div>
                  <span className="text-xs text-muted-foreground uppercase font-bold tracking-widest block mb-1">Max Drawdown</span>
                  <span data-testid="metric-drawdown" className="font-mono text-lg font-black text-red-500">
                    {((lookupMetricValueByKey(bestModel.backtest.metrics, "Max Drawdown") ?? 0) * 100).toFixed(1)}%
                  </span>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground uppercase font-bold tracking-widest block mb-1">Annual Volatility</span>
                  <span className="font-mono text-lg font-black">
                    {((lookupMetricValueByKey(bestModel.backtest.metrics, "Annualized Volatility") ?? 0) * 100).toFixed(1)}%
                  </span>
                </div>
              </>
            ) : (
              <Placeholder icon={ShieldAlert} title="N/A" description="Awaiting model selection." />
            )}
          </CardContent>
        </Card>
      </div>

      {/* BACKTEST PERFORMANCE LAYER */}
      {report && report.length > 0 && (
        <section data-testid="backtest-performance-section">
          <h2 className="text-lg font-bold uppercase tracking-widest text-muted-foreground mt-8 mb-4">Backtest Performance</h2>
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
            <div className="xl:col-span-2">
              <PerformanceCharts report={report} />
            </div>
            <div className="grid grid-cols-1 gap-5">
              <section data-testid="current-holdings-section">
                <h3 className="text-sm font-bold uppercase tracking-widest text-muted-foreground mb-3">Current Holdings</h3>
                {positions && positions.length > 0 ? (
                  <HoldingsSummary positions={positions} title="Current Holdings" />
                ) : (
                  <Card className="flex items-center justify-center border-dashed py-8">
                    <span className="text-muted-foreground text-sm">No position data</span>
                  </Card>
                )}
              </section>
              <section data-testid="position-history-section">
                <h3 className="text-sm font-bold uppercase tracking-widest text-muted-foreground mb-3">Position History</h3>
                {positions && positions.length > 0 ? (
                  <PositionsTable positions={positions} report={report} />
                ) : (
                  <Card className="flex items-center justify-center border-dashed py-8">
                    <span className="text-muted-foreground text-sm">No position data</span>
                  </Card>
                )}
              </section>
            </div>
          </div>
        </section>
      )}

      {/* ATTRIBUTION LAYER */}
      <section data-testid="attribution-section" className="mt-8">
        <h2 className="text-lg font-bold uppercase tracking-widest text-muted-foreground mb-4">Attribution & Decomposition</h2>
        {bestModel?.backtest?.attribution ? (
          <Attribution positions={positions} report={report} attribution={bestModel.backtest.attribution} />
        ) : (
          <Card className="border-dashed bg-muted/20 border-yellow-500/50">
            <CardContent className="flex flex-col items-center justify-center py-10 space-y-3">
              <AlertTriangle className="h-8 w-8 text-yellow-500/70" />
              <p className="text-sm font-bold text-yellow-600/90 text-center">
                Attribution unavailable: missing payload.attribution_normal
              </p>
            </CardContent>
          </Card>
        )}
      </section>
    </div>
  );
}
