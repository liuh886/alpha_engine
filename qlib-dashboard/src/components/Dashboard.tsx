import { BacktestData } from "@/lib/data-parser";
import { OverviewCards } from "./OverviewCards";
import { PerformanceCharts } from "./PerformanceCharts";
import { PositionsTable } from "./PositionsTable";
import { Attribution } from "./Attribution";
import { AttributionInterpretation } from "./AttributionInterpretation";
import { ModelExplainability } from "./ModelExplainability";
import { TradeLedger } from "./TradeLedger";
import { AlphaDecomposition } from "./AlphaDecomposition";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ModelSpec } from "./ModelSpec";
import { MetricsExpanded } from "./MetricsExpanded";
import { HoldingsSummary } from "./HoldingsSummary";
import { Calendar, Tag, Info } from "lucide-react";
import { Badge } from "@/components/ui/badge";

export function Dashboard({ data, params }: { data: BacktestData; params?: Record<string, any> }) {
  const meta = data.meta;
  const runId = params?.id || "";

  return (
    <div className="space-y-5 max-w-[1400px] mx-auto pb-16">
      <div className="border-b pb-4 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
          <div className="flex flex-wrap items-center gap-3 mt-2 text-xs text-muted-foreground">
            <span className="flex items-center gap-1 font-mono"><Calendar className="h-3 w-3" /> {meta.start} → {meta.end}</span>
            <span className="flex items-center gap-1"><Tag className="h-3 w-3" /> {meta.benchmark}</span>
            {params?.id && <Badge variant="outline" className="font-mono text-[10px] py-0">{params.id}</Badge>}
          </div>
        </div>
      </div>

      <OverviewCards metrics={data.metrics} />

      {!data.report || data.report.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 border-2 border-dashed rounded-lg bg-muted/30">
          <Info className="h-8 w-8 text-muted-foreground/30 mb-2" />
          <p className="text-muted-foreground text-sm mb-3">No backtest data available for this model.</p>
          <button className="px-3 py-1.5 bg-primary text-primary-foreground rounded text-xs hover:opacity-90" onClick={() => window.location.hash = '#/models'}>
            Go to Model Registry
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
          <div className="xl:col-span-2 space-y-5">
            <Tabs defaultValue="performance" className="w-full">
              <div className="flex items-center justify-between mb-3 border-b pb-1">
                <TabsList className="bg-transparent h-auto p-0 gap-4 border-none">
                  <TabsTrigger value="performance" className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-0 pb-2 text-sm">Performance</TabsTrigger>
                  <TabsTrigger value="positions" className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-0 pb-2 text-sm">Holdings</TabsTrigger>
                  <TabsTrigger value="attribution" className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-0 pb-2 text-sm">Attribution</TabsTrigger>
                  <TabsTrigger value="trades" className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-0 pb-2 text-sm">Trades</TabsTrigger>
                  <TabsTrigger value="alpha" className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-0 pb-2 text-sm">Alpha</TabsTrigger>
                </TabsList>
              </div>

              <TabsContent value="performance" className="mt-0 focus-visible:ring-0">
                <PerformanceCharts report={data.report} />
              </TabsContent>

              <TabsContent value="positions" className="mt-0 focus-visible:ring-0">
                <PositionsTable positions={data.positions} report={data.report} />
              </TabsContent>

              <TabsContent value="attribution" className="mt-0 focus-visible:ring-0">
                <Attribution positions={data.positions} report={data.report} />
              </TabsContent>

              <TabsContent value="trades" className="mt-0 focus-visible:ring-0">
                {runId ? <TradeLedger runId={runId} /> : <p className="text-sm text-muted-foreground py-8 text-center">No run ID available</p>}
              </TabsContent>

              <TabsContent value="alpha" className="mt-0 focus-visible:ring-0">
                {runId ? <AlphaDecomposition runId={runId} /> : <p className="text-sm text-muted-foreground py-8 text-center">No run ID available</p>}
              </TabsContent>
            </Tabs>
          </div>

          <div className="space-y-5">
            <HoldingsSummary positions={data.positions} />
            <AttributionInterpretation positions={data.positions} report={data.report} />
            <ModelExplainability featureImportance={data.featureImportance} />
            <MetricsExpanded metrics={data.metrics} indicators={data.indicators} />
            {params && <ModelSpec params={params} />}
          </div>
        </div>
      )}
    </div>
  );
}
