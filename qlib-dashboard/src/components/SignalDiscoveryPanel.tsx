import { AlertTriangle, Microscope, Trophy } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { SignalDiscoveryReport } from "@/lib/api-types";

function pct(value: number) {
  return Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : "—";
}

function num(value: number, digits = 3) {
  return Number.isFinite(value) ? value.toFixed(digits) : "—";
}

function label(value: string) {
  return value.replace(/_/g, " ");
}

export function SignalDiscoveryPanel({
  report,
  loading = false,
  error,
}: {
  report?: SignalDiscoveryReport;
  loading?: boolean;
  error?: string | null;
}) {
  if (loading) {
    return <div className="rounded-lg border p-4 text-sm text-muted-foreground">Loading 10D signal discovery evidence…</div>;
  }
  if (!report) {
    return (
      <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-muted-foreground" role="status">
        <AlertTriangle className="mr-2 inline h-4 w-4 text-amber-500" />
        {error || "No 10D signal discovery report is available yet."}
      </div>
    );
  }

  const best = report.summary.best_candidate_summary;
  return (
    <Card className="border-none shadow-xl text-left">
      <CardHeader className="border-b bg-muted/20">
        <CardTitle className="flex items-center gap-2 text-xs font-black uppercase tracking-widest">
          <Microscope className="h-4 w-4" /> 10D Signal Discovery
        </CardTitle>
        <CardDescription>
          Fixed {report.label_horizon}-session holding and {report.rebalance_days}-session rebalance · {report.market.toUpperCase()}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5 p-5">
        <div className="rounded-lg border bg-muted/20 p-4">
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider">
            <Trophy className="h-4 w-4 text-amber-500" /> Best current candidate
          </div>
          <div className="mt-2 font-mono text-sm font-black">{best?.candidate || "No eligible candidate"}</div>
          <div className="mt-1 text-xs text-muted-foreground">
            Direction: {best?.direction ? label(best.direction) : "inconclusive"}
          </div>
          {best?.strength && <p className="mt-2 text-xs">{best.strength}</p>}
          {best?.weakness && <p className="mt-1 text-xs text-amber-700">{best.weakness}</p>}
        </div>

        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Candidate</TableHead>
                <TableHead>Direction</TableHead>
                <TableHead className="text-right">Rank IC</TableHead>
                <TableHead className="text-right">ICIR</TableHead>
                <TableHead className="text-right">Spread</TableHead>
                <TableHead className="text-right">Excess</TableHead>
                <TableHead className="text-right">Sharpe</TableHead>
                <TableHead className="text-right">Max DD</TableHead>
                <TableHead>Top stocks</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {report.candidates.map((candidate) => (
                <TableRow key={`${candidate.candidate_kind}-${candidate.orientation}`}>
                  <TableCell>
                    <div className="font-semibold">{label(candidate.candidate_kind)}</div>
                    <div className="text-[10px] text-muted-foreground">{candidate.orientation} · {label(candidate.status)}</div>
                  </TableCell>
                  <TableCell className="text-xs">{label(candidate.score_direction.recommendation)}</TableCell>
                  <TableCell className="text-right font-mono text-xs">{num(candidate.rank_ic)}</TableCell>
                  <TableCell className="text-right font-mono text-xs">{num(candidate.icir)}</TableCell>
                  <TableCell className="text-right font-mono text-xs">{pct(candidate.score_direction.top_minus_bottom_spread)}</TableCell>
                  <TableCell className="text-right font-mono text-xs">{pct(candidate.excess_return)}</TableCell>
                  <TableCell className="text-right font-mono text-xs">{num(candidate.sharpe, 2)}</TableCell>
                  <TableCell className="text-right font-mono text-xs">{pct(candidate.max_drawdown)}</TableCell>
                  <TableCell className="max-w-[240px] text-xs">{candidate.top_selected_stocks.join(", ") || "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>

        {report.warnings.length > 0 && (
          <div className="text-xs text-amber-700" role="alert">{report.warnings.join(" ")}</div>
        )}
      </CardContent>
    </Card>
  );
}
