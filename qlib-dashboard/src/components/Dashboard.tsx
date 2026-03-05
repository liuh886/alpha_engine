import { BacktestData } from "@/lib/data-parser";
import { OverviewCards } from "./OverviewCards";
import { PerformanceCharts } from "./PerformanceCharts";
import { PositionsTable } from "./PositionsTable";
import { Attribution } from "./Attribution";
import { AttributionInterpretation } from "./AttributionInterpretation";
import { ModelExplainability } from "./ModelExplainability";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ModelSpec } from "./ModelSpec";
import { MetricsExpanded } from "./MetricsExpanded";
import { HoldingsSummary } from "./HoldingsSummary";
import { Calendar, Tag, Compass, Info } from "lucide-react";
import { Badge } from "@/components/ui/badge";

export function Dashboard({ data, params }: { data: BacktestData; params?: Record<string, any> }) {
  const meta = data.meta;

  return (
    <div className="space-y-8 max-w-[1400px] mx-auto pb-20 text-left">
      {/* Page Header Area */}
      <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-4 border-b pb-6">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-primary font-bold text-xs uppercase tracking-widest mb-1">
            <Compass className="h-3 w-3" />
            Strategy Execution Unit
          </div>
          <h1 className="text-4xl font-black tracking-tight">Strategy Alpha Explorer</h1>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 mt-3">
            <div className="flex items-center gap-1.5 text-sm text-muted-foreground bg-muted/50 px-2 py-1 rounded-md border">
              <Calendar className="h-3.5 w-3.5" />
              <span className="font-mono text-xs">{meta.start} → {meta.end}</span>
            </div>
            <div className="flex items-center gap-1.5 text-sm text-muted-foreground bg-muted/50 px-2 py-1 rounded-md border">
              <Tag className="h-3.5 w-3.5" />
              <span className="font-medium text-xs">Benchmark: {meta.benchmark}</span>
            </div>
            <Badge variant="outline" className="font-mono text-[10px] py-0">{params?.id || 'RUN_ID_STUB'}</Badge>
          </div>
        </div>

        <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground animate-pulse">
          <div className="h-2 w-2 rounded-full bg-green-500" />
          Live Session Active
        </div>
      </div>

      <OverviewCards metrics={data.metrics} />

      {!data.report || data.report.length === 0 ? (
        <div className="flex flex-col items-center justify-center p-20 border-2 border-dashed rounded-2xl bg-muted/10 space-y-4">
          <Info className="h-12 w-12 text-muted-foreground opacity-20" />
          <div className="text-center">
            <h3 className="text-lg font-bold">No Backtest Data Available</h3>
            <p className="text-sm text-muted-foreground max-w-md mx-auto mt-1">
              This model version is registered in the registry but its detailed backtest artifacts are not found in the local environment.
              You can trigger a re-backtest to generate this data.
            </p>
          </div>
          <button
            className="px-4 py-2 bg-primary text-primary-foreground rounded-md font-bold text-xs uppercase tracking-widest hover:opacity-90 transition-all"
            onClick={() => window.location.hash = '#/models'}
          >
            Go to Model Registry
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-8">
          <div className="xl:col-span-2 space-y-8">
            <Tabs defaultValue="performance" className="w-full">
              <div className="flex items-center justify-between mb-4 border-b pb-1">
                <TabsList className="bg-transparent h-auto p-0 gap-6 border-none">
                  <TabsTrigger value="performance" className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-0 pb-2 font-bold text-sm">Performance</TabsTrigger>
                  <TabsTrigger value="positions" className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-0 pb-2 font-bold text-sm">Holdings</TabsTrigger>
                  <TabsTrigger value="attribution" className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-0 pb-2 font-bold text-sm">Attribution</TabsTrigger>
                </TabsList>

                <div className="flex items-center gap-2 text-[10px] text-muted-foreground italic">
                  <Info className="h-3 w-3" />
                  Updated based on latest settlement
                </div>
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
            </Tabs>
          </div>

          <div className="space-y-8">
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
