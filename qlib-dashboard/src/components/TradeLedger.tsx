import { useEffect, useState, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Trade {
  date: string;
  symbol: string;
  type: "BUY" | "SELL";
  quantity: number;
  price: number;
  pnl?: number;
  status?: string;
}

interface PnLSymbol {
  symbol: string;
  pnl: number;
}

interface LedgerData {
  holdings: any[];
  trades: Trade[];
  pnl_by_symbol: PnLSymbol[];
}

export function TradeLedger({ runId }: { runId: string }) {
  const [data, setData] = useState<LedgerData | null>(null);
  const [loading, setLoading] = useState(false);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    if (!runId) return;
    setLoading(true);
    fetch(`/api/backtest/${encodeURIComponent(runId)}/ledger`)
      .then(r => r.json())
      .then(json => {
        if (json.ok) setData(json);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [runId]);

  const topWinners = useMemo(() => {
    if (!data?.pnl_by_symbol) return [];
    return data.pnl_by_symbol.filter(p => p.pnl > 0).slice(0, 10);
  }, [data]);

  const topLosers = useMemo(() => {
    if (!data?.pnl_by_symbol) return [];
    return data.pnl_by_symbol.filter(p => p.pnl < 0).slice(-10).reverse();
  }, [data]);

  const displayTrades = useMemo(() => {
    if (!data?.trades) return [];
    return showAll ? data.trades : data.trades.slice(0, 50);
  }, [data, showAll]);

  if (loading) return <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">Loading trades...</CardContent></Card>;
  if (!data) return null;

  return (
    <div className="space-y-5">
      {/* Top PnL Contributors */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardHeader className="pb-3 border-b">
            <CardTitle className="text-sm font-semibold text-green-500">Top 10 Profitable</CardTitle>
          </CardHeader>
          <CardContent className="pt-3">
            {topWinners.length === 0 ? (
              <p className="text-xs text-muted-foreground">No profitable trades</p>
            ) : (
              <div className="space-y-1.5">
                {topWinners.map((p, i) => (
                  <div key={i} className="flex justify-between items-center text-xs">
                    <span className="font-mono">{p.symbol}</span>
                    <span className="font-mono text-green-500">+${p.pnl.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3 border-b">
            <CardTitle className="text-sm font-semibold text-red-500">Top 10 Losing</CardTitle>
          </CardHeader>
          <CardContent className="pt-3">
            {topLosers.length === 0 ? (
              <p className="text-xs text-muted-foreground">No losing trades</p>
            ) : (
              <div className="space-y-1.5">
                {topLosers.map((p, i) => (
                  <div key={i} className="flex justify-between items-center text-xs">
                    <span className="font-mono">{p.symbol}</span>
                    <span className="font-mono text-red-500">${p.pnl.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Trade Log */}
      <Card>
        <CardHeader className="pb-3 border-b">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-semibold">Trade Ledger ({data.trades.length} trades)</CardTitle>
            {!showAll && data.trades.length > 50 && (
              <Button variant="ghost" size="sm" onClick={() => setShowAll(true)} className="text-xs h-6">
                Show all
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b">
                  <th className="text-left py-2 px-3 font-medium text-muted-foreground">Date</th>
                  <th className="text-left py-2 px-3 font-medium text-muted-foreground">Symbol</th>
                  <th className="text-center py-2 px-3 font-medium text-muted-foreground">Side</th>
                  <th className="text-right py-2 px-3 font-medium text-muted-foreground">Qty</th>
                  <th className="text-right py-2 px-3 font-medium text-muted-foreground">Price</th>
                  <th className="text-right py-2 px-3 font-medium text-muted-foreground">PnL</th>
                </tr>
              </thead>
              <tbody>
                {displayTrades.map((t, i) => (
                  <tr key={i} className="border-b last:border-0 hover:bg-muted/30">
                    <td className="py-1.5 px-3 font-mono">{t.date}</td>
                    <td className="py-1.5 px-3 font-mono">{t.symbol}</td>
                    <td className="py-1.5 px-3 text-center">
                      <Badge variant={t.type === "BUY" ? "default" : "destructive"} className="text-[10px] px-1.5">
                        {t.type}
                      </Badge>
                    </td>
                    <td className="py-1.5 px-3 text-right font-mono">{t.quantity.toFixed(0)}</td>
                    <td className="py-1.5 px-3 text-right font-mono">${t.price.toFixed(2)}</td>
                    <td className={cn("py-1.5 px-3 text-right font-mono", t.type === "SELL" ? (t.pnl && t.pnl >= 0 ? "text-green-500" : "text-red-500") : "text-muted-foreground")}>
                      {t.type === "SELL" && t.pnl !== undefined ? `$${t.pnl.toFixed(2)}` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
