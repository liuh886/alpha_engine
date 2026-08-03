import { useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AlertCircle, ArrowDownRight, ArrowUpRight, FileCheck2 } from "lucide-react";
import type { FormalBacktestPackage } from '@/lib/formal-backtest';
import type { FormalModelKind } from '@/lib/formal-evidence';

interface AttributionInterpretationProps {
  rows: FormalBacktestPackage['attribution'];
  modelKind: FormalModelKind;
  availabilityReason: string;
}

export function AttributionInterpretation({
  rows,
  modelKind,
  availabilityReason,
}: AttributionInterpretationProps) {
  const retained = useMemo(() => rows
    .filter((row) => typeof row.value === 'number' && Number.isFinite(row.value))
    .map((row) => ({
      instrument: String(row.instrument ?? row.name ?? 'Unknown'),
      name: String(row.name ?? row.instrument ?? 'Unknown'),
      value: Number(row.value),
      semantics: typeof row.semantics === 'string' ? row.semantics : null,
    }))
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value)), [rows]);

  if (retained.length === 0) {
    return (
      <Card className="border-dashed">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-xs font-bold uppercase tracking-widest">
            <FileCheck2 className="h-4 w-4 text-muted-foreground" /> Retained attribution
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm font-medium">Attribution is unavailable</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{availabilityReason}</p>
        </CardContent>
      </Card>
    );
  }

  const positive = retained.filter((row) => row.value >= 0).slice(0, 3);
  const negative = retained.filter((row) => row.value < 0).slice(0, 3);
  const heading = modelKind === 'rules_based_allocation'
    ? 'Retained allocation contributions'
    : 'Retained security contributions';
  const interpretation = modelKind === 'rules_based_allocation'
    ? 'These rows describe contribution by allocated instrument under the retained source method. They do not demonstrate stock-picking skill.'
    : 'These rows are retained source contributions. The browser does not recompute attribution or infer causal model skill.';

  return (
    <Card className="overflow-hidden">
      <CardHeader className="border-b bg-muted/10 pb-3">
        <CardTitle className="flex items-center gap-2 text-xs font-bold uppercase tracking-widest">
          <FileCheck2 className="h-4 w-4 text-primary" /> {heading}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 pt-4">
        {positive.length > 0 && (
          <div>
            <p className="mb-2 flex items-center gap-1.5 text-[10px] font-bold uppercase text-emerald-600 dark:text-emerald-400">
              <ArrowUpRight className="h-3 w-3" /> Positive retained contribution
            </p>
            <div className="space-y-2">
              {positive.map((row) => (
                <div key={`${row.instrument}-positive`} className="flex items-center justify-between gap-3 text-xs">
                  <span className="min-w-0 truncate text-muted-foreground" title={row.name}>{row.name}</span>
                  <span className="shrink-0 font-mono text-emerald-600 dark:text-emerald-400">{(row.value * 100).toFixed(3)}%</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {negative.length > 0 && (
          <div>
            <p className="mb-2 flex items-center gap-1.5 text-[10px] font-bold uppercase text-rose-600 dark:text-rose-400">
              <ArrowDownRight className="h-3 w-3" /> Negative retained contribution
            </p>
            <div className="space-y-2">
              {negative.map((row) => (
                <div key={`${row.instrument}-negative`} className="flex items-center justify-between gap-3 text-xs">
                  <span className="min-w-0 truncate text-muted-foreground" title={row.name}>{row.name}</span>
                  <span className="shrink-0 font-mono text-rose-600 dark:text-rose-400">{(row.value * 100).toFixed(3)}%</span>
                </div>
              ))}
            </div>
          </div>
        )}
        <div className="rounded-lg border bg-muted/25 p-3 text-[10px] leading-relaxed text-muted-foreground">
          <AlertCircle className="mr-1 inline h-3 w-3 -translate-y-px" />
          {interpretation}
          {retained[0]?.semantics ? ` Source semantics: ${retained[0].semantics}.` : ''}
        </div>
      </CardContent>
    </Card>
  );
}
