import { Card, CardContent } from "@/components/ui/card";
import { Layers, CheckCircle2, Clock, Activity } from "lucide-react";
import type { RegistryStats, ScanStats } from "./types";

interface RegistrySummaryCardsProps {
  stats: RegistryStats | null;
  scanStats: ScanStats | null;
  factorCount: number;
}

export function RegistrySummaryCards({ stats, scanStats, factorCount }: RegistrySummaryCardsProps) {
  const totalFactors = stats?.total_factors ?? factorCount;
  const activeFactors = stats?.by_stage?.["Active"] ?? 0;
  const candidates = (stats?.by_stage?.["Candidate"] ?? 0) + (stats?.by_stage?.["Validated"] ?? 0);

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-primary/10"><Layers className="h-4 w-4 text-primary" /></div>
            <div>
              <p className="text-xs text-muted-foreground">Total Factors</p>
              <p className="text-2xl font-bold">{totalFactors}</p>
            </div>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-green-500/10"><CheckCircle2 className="h-4 w-4 text-green-500" /></div>
            <div>
              <p className="text-xs text-muted-foreground">Active Factors</p>
              <p className="text-2xl font-bold text-green-500">{activeFactors}</p>
            </div>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-yellow-500/10"><Clock className="h-4 w-4 text-yellow-500" /></div>
            <div>
              <p className="text-xs text-muted-foreground">Candidates</p>
              <p className="text-2xl font-bold text-yellow-500">{candidates}</p>
            </div>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-blue-500/10"><Activity className="h-4 w-4 text-blue-500" /></div>
            <div>
              <p className="text-xs text-muted-foreground">This Scan</p>
              <p className="text-2xl font-bold">
                {scanStats ? `${scanStats.passed}/${scanStats.total_scanned}` : "N/A"}
              </p>
              {scanStats && (
                <p className="text-[10px] text-muted-foreground">passed on {scanStats.scan_date}</p>
              )}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
