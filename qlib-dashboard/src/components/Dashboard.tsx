import { Calendar, Database, Info, Tag } from 'lucide-react';
import type { BacktestData } from '@/lib/data-parser';
import type { FormalBacktestPackage } from '@/lib/formal-backtest';
import type { ModelParams } from '@/lib/types';
import { projectFormalPackage } from '@/lib/formal-evidence';
import { AttributionEvidence } from './AttributionEvidence';
import { AttributionInterpretation } from './AttributionInterpretation';
import { FormalBacktestEvidence, FormalBacktestTrades } from './FormalBacktestEvidence';
import { HoldingsSummary } from './HoldingsSummary';
import { MetricsExpanded } from './MetricsExpanded';
import { ModelExplainability } from './ModelExplainability';
import { ModelSpec } from './ModelSpec';
import { OverviewCards } from './OverviewCards';
import { PerformanceCharts } from './PerformanceCharts';
import { PositionsTable } from './PositionsTable';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

export function Dashboard({ data, params }: { data: BacktestData; params?: ModelParams }) {
  const meta = data.meta;
  const snapshotId = (params as ModelParams & { data_snapshot_id?: string })?.data_snapshot_id ?? '';
  const hasReport = Array.isArray(data.report) && data.report.length > 0;
  const formal = (data as BacktestData & { formalBacktest?: FormalBacktestPackage }).formalBacktest ?? null;
  const projection = projectFormalPackage(formal, {
    id: String(params?.id ?? formal?.model_id ?? ''),
    model_type: typeof params?.model_type === 'string' ? params.model_type : '',
  });
  const completeness = formal?.evidence_completeness.status;
  const metricAvailabilityLabel = formal?.evidence_completeness.status === 'partial'
    ? 'Blocked by source'
    : formal
      ? 'Not retained'
      : 'Contract violation';
  const metricUnavailableReason = formal?.evidence_completeness.status === 'partial'
    ? 'The retained formal source evidence does not provide this metric.'
    : formal
      ? 'The accepted formal package does not retain this metric.'
      : 'The formal evidence contract is missing from this record.';

  return (
    <div className="mx-auto max-w-[1400px] space-y-5 pb-16">
      <section className="flex flex-wrap items-end justify-between gap-4 border-b pb-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-primary">Formal model evidence</p>
          <h2 className="mt-2 text-2xl font-black tracking-tight">Complete backtest review</h2>
          <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            <span className="flex items-center gap-1 font-mono"><Calendar className="h-3 w-3" /> {meta.start} → {meta.end}</span>
            <span className="flex items-center gap-1"><Tag className="h-3 w-3" /> {meta.benchmark}</span>
            {params?.id != null && <Badge variant="outline" className="font-mono text-[10px]">{String(params.id)}</Badge>}
            {snapshotId && <Badge variant="secondary" className="gap-1 font-mono text-[10px]"><Database className="h-3 w-3" /> {snapshotId.slice(0, 18)}</Badge>}
            {formal && <Badge variant="outline" className="font-mono text-[10px]">{formal.trace_frequency.split('_').join(' ')}</Badge>}
            <Badge variant="outline" className={completeness === 'complete' ? 'text-[10px] text-emerald-700 dark:text-emerald-300' : 'text-[10px] text-amber-700 dark:text-amber-300'}>
              {completeness === 'complete' ? 'Complete retained evidence' : 'Partial retained evidence'}
            </Badge>
            <Badge variant="outline" className="text-[10px] text-amber-700 dark:text-amber-300">Historical · read only</Badge>
          </div>
        </div>
      </section>

      <OverviewCards
        metrics={data.metrics}
        availabilityLabel={metricAvailabilityLabel}
        unavailableReason={metricUnavailableReason}
      />

      {!hasReport ? (
        <div className="rounded-xl border-2 border-dashed bg-muted/20 px-6 py-14 text-center">
          <Info className="mx-auto h-8 w-8 text-muted-foreground/30" />
          <p className="mt-3 text-sm font-medium">Formal performance contract violation</p>
          <p className="mx-auto mt-1 max-w-xl text-xs leading-relaxed text-muted-foreground">
            A formal baseline must retain a performance path. The frontend will not reconstruct one from headline metrics.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
          <div className="min-w-0 space-y-5 xl:col-span-2">
            <Tabs defaultValue="performance" className="w-full">
              <TabsList className="mb-4 flex h-auto w-full max-w-full justify-start gap-1 overflow-x-auto p-1">
                <TabsTrigger className="shrink-0" value="performance">Performance</TabsTrigger>
                <TabsTrigger className="shrink-0" value="positions">Holdings</TabsTrigger>
                {formal && <TabsTrigger className="shrink-0" value="trades">Trades</TabsTrigger>}
                <TabsTrigger className="shrink-0" value="attribution">Attribution</TabsTrigger>
                {formal && <TabsTrigger className="shrink-0" value="evidence">Evidence</TabsTrigger>}
              </TabsList>

              <TabsContent value="performance" className="mt-0"><section data-testid="backtest-performance-section"><PerformanceCharts report={data.report} /></section></TabsContent>
              <TabsContent value="positions" className="mt-0"><section data-testid="position-history-section"><PositionsTable positions={data.positions} report={data.report} /></section></TabsContent>
              {formal && <TabsContent value="trades" className="mt-0"><section data-testid="trade-ledger-section"><FormalBacktestTrades formal={formal} /></section></TabsContent>}
              <TabsContent value="attribution" className="mt-0"><section data-testid="attribution-section"><AttributionEvidence rows={projection.attribution} /></section></TabsContent>
              {formal && <TabsContent value="evidence" className="mt-0"><section data-testid="formal-evidence-section"><FormalBacktestEvidence formal={formal} /></section></TabsContent>}
            </Tabs>
          </div>

          <div className="min-w-0 space-y-5">
            <section data-testid="current-holdings-section"><HoldingsSummary positions={data.positions} /></section>
            <AttributionInterpretation
              rows={projection.attribution}
              modelKind={projection.modelKind}
              availabilityReason={projection.attributionAvailability}
            />
            <ModelExplainability featureImportance={data.featureImportance} />
            <MetricsExpanded metrics={data.metrics} indicators={data.indicators} />
            {params && <ModelSpec params={params} />}
          </div>
        </div>
      )}
    </div>
  );
}
