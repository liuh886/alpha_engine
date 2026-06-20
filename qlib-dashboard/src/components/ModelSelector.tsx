import { ModelData } from "@/lib/data-parser";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Trash2 } from "lucide-react";

export function ModelSelector({
    models,
    selectedModelId,
    onSelect,
    onDelete,
    open,
    onOpenChange
}: {
    models: ModelData[],
    selectedModelId: string,
    onSelect: (id: string) => void,
    onDelete: (id: string) => void | Promise<void>,
    open: boolean,
    onOpenChange: (open: boolean) => void
}) {
    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-4xl max-h-[80vh] overflow-y-auto">
                <DialogHeader>
                    <DialogTitle>Select Backtest Run</DialogTitle>
                </DialogHeader>

                <div className="rounded-md border">
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className="w-[180px]">Date</TableHead>
                                <TableHead>Market</TableHead>
                                <TableHead>Metrics (Ann. Ret / IR / Sharpe)</TableHead>
                                <TableHead>Strategy Params</TableHead>
                                <TableHead>Status</TableHead>
                                <TableHead className="text-right">Action</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {models.map(m => {
                                const isSelected = m.id === selectedModelId;
                                const ret = m.backtest.metrics["Annualized Return"] ?? null;
                                const ir = m.backtest.metrics["Information Ratio"] ?? null;
                                const sharpe = m.backtest.metrics["Sharpe Ratio"] ?? null;
                                const params = m.params || {};
                                const meta = (params["meta"] || {}) as Record<string, unknown>;
                                const strategyProfile = (meta?.strategy_profile || {}) as Record<string, unknown>;
                                const strategy = (strategyProfile?.strategy || {}) as Record<string, unknown>;
                                const universe = (strategyProfile?.universe || {}) as Record<string, unknown>;
                                const universeFilters = (universe?.filters || {}) as Record<string, unknown>;

                                const rebalance = strategy?.rebalance_frequency as string | undefined;
                                const minHoldDays = strategy?.min_hold_days as number | undefined;
                                const positionRule = (strategy?.position_rule || {}) as Record<string, unknown>;
                                const topk = positionRule?.topk as number | undefined;
                                const costsBps = strategy?.costs_bps as number | undefined;
                                const minLiquidity = universeFilters?.min_liquidity as number | undefined;

                                return (
                                    <TableRow
                                        key={m.id}
                                        className={`cursor-pointer ${isSelected ? "bg-muted" : ""}`}
                                        onClick={() => {
                                            onSelect(m.id);
                                            onOpenChange(false);
                                        }}
                                    >
                                        <TableCell className="font-medium">
                                            {m.name && (
                                                <div className="text-xs font-semibold text-primary/80 uppercase tracking-tight" title={m.name}>
                                                    {m.name}
                                                </div>
                                            )}
                                            <div className="text-[10px] font-mono text-muted-foreground uppercase">{m.id}</div>
                                        </TableCell>
                                        <TableCell>
                                            <Badge variant="outline" className="uppercase font-black text-[9px] mb-1 tracking-widest">{m.market}</Badge>
                                            <div className="text-[10px] text-muted-foreground flex flex-col font-medium">
                                                <span>From: {m.backtest.meta.start || "N/A"}</span>
                                                <span>To: {m.backtest.meta.end || "N/A"}</span>
                                            </div>
                                        </TableCell>
                                        <TableCell>
                                            <div className={`text-sm ${ret > 0 ? "text-green-600" : "text-red-600"}`}>
                                                {ret != null ? `${(ret * 100).toFixed(1)}%` : "N/A"}
                                            </div>
                                            <div className="text-xs text-muted-foreground">
                                                IR: {ir != null ? ir.toFixed(2) : "N/A"} | Sharpe:{" "}
                                                {sharpe != null ? sharpe.toFixed(2) : "N/A"}
                                            </div>
                                        </TableCell>
                                        <TableCell>
                                            <div className="text-xs space-y-1">
                                                {rebalance && <div>Rebalance: {String(rebalance)}</div>}
                                                {minHoldDays !== undefined && <div>Min Hold: {String(minHoldDays)}d</div>}
                                                {topk !== undefined && <div>TopK: {String(topk)}</div>}
                                                {costsBps !== undefined && <div>Costs: {String(costsBps)} bps</div>}
                                                {minLiquidity !== undefined && <div>Min Liquidity: {String(minLiquidity)}</div>}
                                            </div>
                                        </TableCell>
                                        <TableCell>
                                            {ret !== null ? (
                                                <Badge variant="default" className="text-[10px]">Has Data</Badge>
                                            ) : (
                                                <Badge variant="outline" className="text-[10px] text-muted-foreground">No Data</Badge>
                                            )}
                                        </TableCell>
                                        <TableCell className="text-right">
                                            <div className="flex justify-end items-center gap-2">
                                                {isSelected && <Badge>Active</Badge>}
                                                <Button
                                                    variant="destructive"
                                                    size="sm"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        onDelete(m.id);
                                                    }}
                                                    title="Delete this run from mlruns/ and remove it from artifacts/dashboard/dashboard_db.json"
                                                >
                                                    <Trash2 className="h-4 w-4" />
                                                </Button>
                                            </div>
                                        </TableCell>
                                    </TableRow>
                                );
                            })}
                        </TableBody>
                    </Table>
                </div>
            </DialogContent>
        </Dialog>
    );
}
