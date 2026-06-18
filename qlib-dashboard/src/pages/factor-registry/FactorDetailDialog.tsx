import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Loader2, ChevronUp, ChevronDown, CheckCircle2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatNum, formatPct } from "@/lib/format";
import type { FactorDetail, FactorStage } from "./types";
import { STAGE_COLORS } from "./types";

interface FactorDetailDialogProps {
  detailFactorId: number | null;
  detail: FactorDetail | null;
  detailLoading: boolean;
  actionId: number | null;
  onClose: () => void;
  onPromote: (factorId: number) => void;
  onDemote: (factorId: number) => void;
}

export function FactorDetailDialog({
  detailFactorId,
  detail,
  detailLoading,
  actionId,
  onClose,
  onPromote,
  onDemote,
}: FactorDetailDialogProps) {
  return (
    <Dialog
      open={detailFactorId !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {detail?.factor?.name || "Factor Details"}
            {detail?.factor?.stage && (
              <Badge
                variant="outline"
                className={cn(
                  "text-[10px]",
                  STAGE_COLORS[detail.factor.stage as FactorStage]
                )}
              >
                {detail.factor.stage}
              </Badge>
            )}
          </DialogTitle>
        </DialogHeader>

        {detailLoading ? (
          <div className="h-48 flex items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-primary opacity-50" />
          </div>
        ) : detail ? (
          <div className="space-y-5">
            {/* Expression */}
            <div>
              <div className="text-xs text-muted-foreground mb-1">
                Expression
              </div>
              <div className="font-mono text-xs break-all bg-muted/50 p-3 rounded">
                {detail.factor.expression}
              </div>
            </div>

            {/* Thesis */}
            {detail.factor.thesis && (
              <div>
                <div className="text-xs text-muted-foreground mb-1">
                  Thesis / Description
                </div>
                <p className="text-sm">{detail.factor.thesis}</p>
              </div>
            )}

            {/* Factor metadata grid */}
            <div className="grid grid-cols-3 gap-3">
              <div className="bg-muted/30 p-2 rounded">
                <div className="text-[10px] text-muted-foreground">
                  Category
                </div>
                <div className="text-sm font-medium">
                  {detail.factor.category}
                </div>
              </div>
              <div className="bg-muted/30 p-2 rounded">
                <div className="text-[10px] text-muted-foreground">
                  Direction
                </div>
                <div
                  className={cn(
                    "text-sm font-medium",
                    detail.factor.direction === "long"
                      ? "text-green-500"
                      : detail.factor.direction === "short"
                        ? "text-red-500"
                        : ""
                  )}
                >
                  {detail.factor.direction}
                </div>
              </div>
              <div className="bg-muted/30 p-2 rounded">
                <div className="text-[10px] text-muted-foreground">
                  Lookback
                </div>
                <div className="text-sm font-medium">
                  {detail.factor.lookback_days} days
                </div>
              </div>
            </div>

            {/* Validation History */}
            <div>
              <div className="text-xs text-muted-foreground mb-2 font-medium">
                Validation History
              </div>
              {detail.validations.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No validations recorded yet.
                </p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="text-xs">Date</TableHead>
                      <TableHead className="text-xs">Market</TableHead>
                      <TableHead className="text-xs text-right">
                        ICIR
                      </TableHead>
                      <TableHead className="text-xs text-right">
                        t-stat
                      </TableHead>
                      <TableHead className="text-xs text-right">
                        Q Spread
                      </TableHead>
                      <TableHead className="text-xs text-center">
                        Passed
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {detail.validations.map((v) => (
                      <TableRow key={v.id}>
                        <TableCell className="text-xs font-mono">
                          {v.validated_at?.slice(0, 10)}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="secondary"
                            className="text-[10px] uppercase"
                          >
                            {v.market}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs">
                          {formatNum(v.icir, 2)}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs">
                          {formatNum(v.t_stat, 2)}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs">
                          {formatPct(v.quintile_spread)}
                        </TableCell>
                        <TableCell className="text-center">
                          {v.passed ? (
                            <CheckCircle2 className="h-4 w-4 text-green-500 mx-auto" />
                          ) : (
                            <X className="h-4 w-4 text-red-500 mx-auto" />
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </div>

            {/* Usage */}
            <div>
              <div className="text-xs text-muted-foreground mb-2 font-medium">
                Strategy Usage
              </div>
              {detail.usage.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  Not used by any strategy yet.
                </p>
              ) : (
                <div className="space-y-1.5">
                  {detail.usage.map((u) => (
                    <div
                      key={u.id}
                      className="flex items-center justify-between bg-muted/30 p-2 rounded text-xs"
                    >
                      <span className="font-mono">
                        {u.strategy_config || "unnamed"}
                      </span>
                      <div className="flex items-center gap-3">
                        <span className="text-muted-foreground">
                          weight: {(u.weight ?? 0).toFixed(2)}
                        </span>
                        <span className="text-muted-foreground">
                          {u.added_at?.slice(0, 10)}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Actions in modal */}
            <div className="flex justify-end gap-2 pt-2 border-t">
              {detail.factor.stage !== "Active" &&
                detail.factor.stage !== "Deprecated" && (
                  <Button
                    size="sm"
                    variant="default"
                    className="h-7 gap-1.5 text-xs"
                    onClick={() => onPromote(detail.factor.id)}
                    disabled={actionId === detail.factor.id}
                  >
                    {actionId === detail.factor.id ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <ChevronUp className="h-3 w-3" />
                    )}
                    Promote
                  </Button>
                )}
              {detail.factor.stage === "Active" && (
                <Button
                  size="sm"
                  variant="destructive"
                  className="h-7 gap-1.5 text-xs"
                  onClick={() => onDemote(detail.factor.id)}
                  disabled={actionId === detail.factor.id}
                >
                  {actionId === detail.factor.id ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <ChevronDown className="h-3 w-3" />
                  )}
                  Demote
                </Button>
              )}
            </div>
          </div>
        ) : (
          <div className="h-32 flex items-center justify-center text-muted-foreground text-sm">
            No data available.
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
