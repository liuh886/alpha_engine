import { lookupMetricValueByKey } from "@/types/metrics";
import { PerformanceCharts } from '@/components/PerformanceCharts';
import { PositionsTable } from '@/components/PositionsTable';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Placeholder } from '@/components/Placeholder';
import { Badge } from '@/components/ui/badge';
import { Cpu, FlaskConical, ShieldAlert } from 'lucide-react';

export function TrueDashboard({ model, report, positions }: { model: any, report: any[], positions: any[] }) {
  const bestModel = model;

  return (
    <div className="space-y-6 max-w-[1400px] mx-auto pb-16">
      <div className="border-b pb-4">
        <h1 className="text-4xl font-black tracking-tight text-foreground">Model Dashboard</h1>
        <p className="text-muted-foreground mt-2 font-medium">Detailed performance metrics for {bestModel?.name || 'Selected Model'}.</p>
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
                    <span className="font-mono text-lg font-black text-green-500">
                      {((lookupMetricValueByKey(bestModel.backtest.metrics, "Annualized Return") ?? 0) * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div>
                    <span className="text-muted-foreground text-[10px] font-bold uppercase tracking-wider block">Sharpe</span>
                    <span className="font-mono text-lg font-black">
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
                  <span className="font-mono text-lg font-black text-red-500">
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
        <>
          <h2 className="text-lg font-bold uppercase tracking-widest text-muted-foreground mt-8 mb-4">Backtest Performance</h2>
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
            <div className="xl:col-span-2">
              <PerformanceCharts report={report} />
            </div>
            <div>
              {positions && positions.length > 0 ? (
                <PositionsTable positions={positions} report={report} />
              ) : (
                <Card className="h-full flex items-center justify-center border-dashed">
                  <span className="text-muted-foreground text-sm">No position data</span>
                </Card>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
