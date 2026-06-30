import { lazy, Suspense } from "react";
import { BacktestData } from "@/lib/data-parser";
import { OverviewCards } from "./OverviewCards";
import { PerformanceCharts } from "./PerformanceCharts";
import { PositionsTable } from "./PositionsTable";
import { AttributionInterpretation } from "./AttributionInterpretation";
import { ModelExplainability } from "./ModelExplainability";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ModelSpec } from "./ModelSpec";
import { MetricsExpanded } from "./MetricsExpanded";
import { HoldingsSummary } from "./HoldingsSummary";
import { Calendar, Tag, Info, Database, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { ModelParams } from "@/lib/types";
import { useGlobalStore } from "@/store/globalStore";
import { navigateTo } from "@/routes";

// Heavy tab panels — loaded only when the user first opens that tab.
// This avoids bundling Attribution (~22 kB), TradeLedger and AlphaDecomposition
// into the initial chunk, improving first-paint time.
const Attribution = lazy(() =>
  import("./Attribution").then((m) => ({ default: m.Attribution }))
);
const TradeLedger = lazy(() =>
  import("./TradeLedger").then((m) => ({ default: m.TradeLedger }))
);
const AlphaDecomposition = lazy(() =>
  import("./AlphaDecomposition").then((m) => ({ default: m.AlphaDecomposition }))
);

/** Minimal loading indicator shown while a lazy tab chunk is being fetched. */
function TabLoader() {
  return (
    <div className="flex items-center justify-center py-16 text-muted-foreground gap-2 text-sm">
      <Loader2 className="h-4 w-4 animate-spin" />
      Loading…
    </div>
  );
}

export function Dashboard({ data, params }: { data: BacktestData; params?: ModelParams }) {
  const meta = data.meta;
  const runId = String(params?.id ?? "");
  const demoMode = useGlobalStore((s) => s.demoMode);
  // Access typed field; fall back to empty string when not present.
  const snapshotId = (params as ModelParams & { data_snapshot_id?: string })?.data_snapshot_id ?? "";

  return (
    <div className="space-y-5 max-w-[1400px] mx-auto pb-16">
      <div className="border-b pb-4 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
          <div className="flex flex-wrap items-center gap-3 mt-2 text-xs text-muted-foreground">
            <span className="flex items-center gap-1 font-mono">
              <Calendar className="h-3 w-3" /> {meta.start} → {meta.end}
            </span>
            <span className="flex items-center gap-1">
              <Tag className="h-3 w-3" /> {meta.benchmark}
            </span>
            {params?.id != null && (
              <Badge variant="outline" className="font-mono text-[10px] py-0">
                {String(params.id)}
              </Badge>
            )}
            {snapshotId && (
              <Badge variant="secondary" className="font-mono text-[10px] py-0 gap-1">
                <Database className="h-2.5 w-2.5" /> {snapshotId.slice(0, 16)}
              </Badge>
            )}
            <Badge
              variant="secondary"
              className={`font-mono text-[10px] py-0 ${
                demoMode
                  ? "text-blue-500 bg-blue-500/10"
                  : "text-green-500 bg-green-500/10"
              }`}
            >
              {demoMode ? "Demo" : "Live"}
            </Badge>
          </div>
        </div>
      </div>

      <OverviewCards metrics={data.metrics} />

      {!data.report || data.report.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 border-2 border-dashed rounded-lg bg-muted/30">
          <Info className="h-8 w-8 text-muted-foreground/30 mb-2" />
          <p className="text-muted-foreground text-sm mb-1">
            No backtest report data available for this model.
          </p>
          <p className="text-muted-foreground text-xs mb-4">
            Model metrics are shown above. Run a backtest to generate equity curve and position data.
          </p>
          <div className="flex gap-2">
            {/* Use navigateTo() — never write window.location.hash directly */}
            <button
              className="px-3 py-1.5 bg-primary text-primary-foreground rounded text-xs hover:opacity-90"
              onClick={() => navigateTo('backtest')}
            >
              Run Backtest
            </button>
            <button
              className="px-3 py-1.5 border border-border rounded text-xs hover:bg-muted"
              onClick={() => navigateTo('models')}
            >
              Model Registry
            </button>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
          <div className="xl:col-span-2 space-y-5">
            <Tabs defaultValue="performance" className="w-full">
              <div className="flex items-center justify-between mb-3 border-b pb-1">
                <TabsList className="bg-transparent h-auto p-0 gap-4 border-none">
                  <TabsTrigger
                    value="performance"
                    className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-0 pb-2 text-sm"
                  >
                    Performance
                  </TabsTrigger>
                  <TabsTrigger
                    value="positions"
                    className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-0 pb-2 text-sm"
                  >
                    Holdings
                  </TabsTrigger>
                  <TabsTrigger
                    value="attribution"
                    className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-0 pb-2 text-sm"
                  >
                    Attribution
                  </TabsTrigger>
                  <TabsTrigger
                    value="trades"
                    className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-0 pb-2 text-sm"
                  >
                    Trades
                  </TabsTrigger>
                  <TabsTrigger
                    value="alpha"
                    className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-0 pb-2 text-sm"
                  >
                    Alpha
                  </TabsTrigger>
                </TabsList>
              </div>

              <TabsContent value="performance" className="mt-0 focus-visible:ring-0">
                <section data-testid="backtest-performance-section">
                  <PerformanceCharts report={data.report} />
                </section>
              </TabsContent>

              <TabsContent value="positions" className="mt-0 focus-visible:ring-0">
                <section data-testid="position-history-section">
                  <PositionsTable positions={data.positions} report={data.report} />
                </section>
              </TabsContent>

              {/* Attribution, TradeLedger, AlphaDecomposition are lazy-loaded */}
              <TabsContent value="attribution" className="mt-0 focus-visible:ring-0">
                <section data-testid="attribution-section">
                  <Suspense fallback={<TabLoader />}>
                    <Attribution
                      positions={data.positions}
                      report={data.report}
                      attribution={data.attribution}
                    />
                  </Suspense>
                </section>
              </TabsContent>

              <TabsContent value="trades" className="mt-0 focus-visible:ring-0">
                <section data-testid="trades-section">
                  {runId ? (
                    <Suspense fallback={<TabLoader />}>
                      <TradeLedger runId={runId} />
                    </Suspense>
                  ) : (
                    <p className="text-sm text-muted-foreground py-8 text-center">No run ID available</p>
                  )}
                </section>
              </TabsContent>

              <TabsContent value="alpha" className="mt-0 focus-visible:ring-0">
                <section data-testid="alpha-section">
                  {runId ? (
                    <Suspense fallback={<TabLoader />}>
                      <AlphaDecomposition runId={runId} />
                    </Suspense>
                  ) : (
                    <p className="text-sm text-muted-foreground py-8 text-center">No run ID available</p>
                  )}
                </section>
              </TabsContent>
            </Tabs>
          </div>

          <div className="space-y-5">
            <section data-testid="current-holdings-section">
              <HoldingsSummary positions={data.positions} />
            </section>
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
