import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Clock3,
  RefreshCw,
  ShieldCheck,
  Target,
} from "lucide-react";
import { apiFetch } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface MarketSummary {
  market: string;
  available: boolean;
  ticket_count: number;
  latest: TicketSummary | null;
}

interface TicketSummary {
  as_of_date: string;
  market_regime?: string;
  risk_on?: boolean;
  gross_exposure?: number;
  ticket_turnover?: number;
  turnover_remaining?: number;
  action_counts?: Record<string, number>;
  warning_count?: number;
}

interface BasketRow {
  basket: string;
  selected: boolean;
  composite_percentile?: number | null;
  breadth_above_sma50?: number | null;
  reason_codes?: string[];
}

interface FactorScore {
  stable_factor_key: string;
  information_family: string;
  status: string;
  decision_eligible: boolean;
  percentile?: number | null;
}

interface SecurityRow {
  symbol: string;
  basket: string;
  state: string;
  action: string;
  target_weight: number;
  previous_weight: number;
  weight_change: number;
  eligible_factor_count: number;
  excluded_factor_count: number;
  factor_scores?: FactorScore[];
  reason_codes?: string[];
}

interface DecisionTicket {
  market: string;
  as_of_date: string;
  actionable_from?: string | null;
  mode: string;
  trade_ready: boolean;
  ticket_identity_sha256: string;
  market_context: {
    benchmark?: string;
    risk_on?: boolean;
    market_regime?: string;
    selected_baskets?: string[];
    gross_exposure?: number;
    cash_weight?: number;
  };
  baskets: BasketRow[];
  securities: SecurityRow[];
  turnover_budget: {
    annual_budget?: number;
    ticket_turnover?: number;
    cumulative?: number;
    remaining?: number;
    within_budget?: boolean;
  };
  warnings: string[];
}

const pct = (value?: number | null) =>
  value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;

const actionVariant = (action: string): "default" | "secondary" | "destructive" | "outline" => {
  if (action === "ENTER_CANDIDATE") return "default";
  if (action === "EXIT_RISK") return "destructive";
  if (action === "REDUCE_CANDIDATE") return "secondary";
  return "outline";
};

export function DecisionDeskPage() {
  const [markets, setMarkets] = useState<MarketSummary[]>([]);
  const [market, setMarket] = useState("us");
  const [ticket, setTicket] = useState<DecisionTicket | null>(null);
  const [history, setHistory] = useState<TicketSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadOverview = useCallback(async () => {
    const response = await apiFetch("/api/research/decision-desk", { cache: "no-store" });
    if (!response.ok) throw new Error(`Decision Desk overview failed (${response.status})`);
    const payload = await response.json();
    const rows = (payload.markets || []) as MarketSummary[];
    setMarkets(rows);
    const available = rows.find((row) => row.market === market && row.available)
      || rows.find((row) => row.available);
    if (available) setMarket(available.market);
  }, [market]);

  const loadMarket = useCallback(async (nextMarket: string) => {
    setLoading(true);
    setError(null);
    try {
      const [latestResponse, historyResponse] = await Promise.all([
        apiFetch(`/api/research/decision-desk/${nextMarket}/latest`, { cache: "no-store" }),
        apiFetch(`/api/research/decision-desk/${nextMarket}/history?limit=30`, { cache: "no-store" }),
      ]);
      if (latestResponse.status === 404) {
        setTicket(null);
        setHistory([]);
        return;
      }
      if (!latestResponse.ok || !historyResponse.ok) {
        throw new Error("Decision Desk ticket read failed");
      }
      const latestPayload = await latestResponse.json();
      const historyPayload = await historyResponse.json();
      setTicket(latestPayload.ticket as DecisionTicket);
      setHistory((historyPayload.history || []) as TicketSummary[]);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Decision Desk unavailable");
    } finally {
      setLoading(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await loadOverview();
      await loadMarket(market);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Decision Desk unavailable");
      setLoading(false);
    }
  }, [loadMarket, loadOverview, market]);

  useEffect(() => {
    void loadOverview().catch((exc) => setError(String(exc)));
  }, [loadOverview]);

  useEffect(() => {
    void loadMarket(market);
  }, [loadMarket, market]);

  const actionCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    ticket?.securities.forEach((row) => {
      counts[row.action] = (counts[row.action] || 0) + 1;
    });
    return counts;
  }, [ticket]);

  const selectedBaskets = useMemo(
    () => [...(ticket?.baskets || [])].sort((a, b) => Number(b.selected) - Number(a.selected)),
    [ticket],
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight">Decision Desk</h1>
            <Badge variant="outline">diagnostic only</Badge>
          </div>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Forward, immutable research tickets. Candidate actions require manual review and are not orders.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {markets.map((row) => (
            <Button
              key={row.market}
              variant={market === row.market ? "default" : "outline"}
              size="sm"
              disabled={!row.available}
              onClick={() => setMarket(row.market)}
            >
              {row.market.toUpperCase()} {row.available ? `(${row.ticket_count})` : "blocked"}
            </Button>
          ))}
          <Button variant="outline" size="sm" onClick={() => void refresh()} disabled={loading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </div>

      {error && (
        <Card className="border-destructive/40">
          <CardContent className="flex items-center gap-2 py-4 text-sm text-destructive">
            <AlertTriangle className="h-4 w-4" /> {error}
          </CardContent>
        </Card>
      )}

      {!ticket && !loading ? (
        <Card>
          <CardContent className="py-14 text-center">
            <Clock3 className="mx-auto mb-3 h-9 w-9 text-muted-foreground" />
            <p className="font-semibold">No forward ticket is available for {market.toUpperCase()}.</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Run the governed prospective shadow cycle after end-of-day data are complete.
            </p>
          </CardContent>
        </Card>
      ) : ticket ? (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm">Market regime</CardTitle></CardHeader>
              <CardContent>
                <div className="flex items-center gap-2 text-xl font-bold">
                  {ticket.market_context.risk_on ? <ArrowUpRight className="h-5 w-5" /> : <ArrowDownRight className="h-5 w-5" />}
                  {ticket.market_context.market_regime || "unknown"}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">Benchmark {ticket.market_context.benchmark || "—"}</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm">Gross exposure</CardTitle></CardHeader>
              <CardContent>
                <div className="text-xl font-bold">{pct(ticket.market_context.gross_exposure)}</div>
                <p className="mt-1 text-xs text-muted-foreground">Cash {pct(ticket.market_context.cash_weight)}</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm">Turnover budget</CardTitle></CardHeader>
              <CardContent>
                <div className="text-xl font-bold">{ticket.turnover_budget.remaining?.toFixed(2) ?? "—"}x left</div>
                <p className="mt-1 text-xs text-muted-foreground">Today {ticket.turnover_budget.ticket_turnover?.toFixed(2) ?? "—"}x</p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm">Ticket identity</CardTitle></CardHeader>
              <CardContent>
                <div className="flex items-center gap-2 text-sm font-semibold"><ShieldCheck className="h-4 w-4" /> immutable</div>
                <p className="mt-1 truncate font-mono text-xs text-muted-foreground">{ticket.ticket_identity_sha256}</p>
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-4 xl:grid-cols-[1.35fr_0.65fr]">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base"><Target className="h-4 w-4" /> Security review queue</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Symbol</TableHead><TableHead>Basket</TableHead><TableHead>State</TableHead>
                        <TableHead>Action</TableHead><TableHead className="text-right">Target</TableHead>
                        <TableHead className="text-right">Change</TableHead><TableHead className="text-right">Eligible factors</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {ticket.securities.map((row) => (
                        <TableRow key={row.symbol}>
                          <TableCell className="font-mono font-semibold">{row.symbol}</TableCell>
                          <TableCell>{row.basket || "—"}</TableCell>
                          <TableCell>{row.state}</TableCell>
                          <TableCell><Badge variant={actionVariant(row.action)}>{row.action}</Badge></TableCell>
                          <TableCell className="text-right">{pct(row.target_weight)}</TableCell>
                          <TableCell className="text-right">{pct(row.weight_change)}</TableCell>
                          <TableCell className="text-right">{row.eligible_factor_count}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>

            <div className="space-y-4">
              <Card>
                <CardHeader><CardTitle className="text-base">Action mix</CardTitle></CardHeader>
                <CardContent className="space-y-2">
                  {Object.entries(actionCounts).length ? Object.entries(actionCounts).map(([action, count]) => (
                    <div key={action} className="flex items-center justify-between text-sm">
                      <Badge variant={actionVariant(action)}>{action}</Badge><span className="font-mono font-semibold">{count}</span>
                    </div>
                  )) : <p className="text-sm text-muted-foreground">No security actions.</p>}
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle className="text-base">Warnings</CardTitle></CardHeader>
                <CardContent className="space-y-2">
                  {ticket.warnings.length ? ticket.warnings.map((warning) => (
                    <div key={warning} className="rounded border border-amber-500/30 bg-amber-500/5 px-3 py-2 font-mono text-xs">{warning}</div>
                  )) : <p className="text-sm text-muted-foreground">No ticket warnings.</p>}
                </CardContent>
              </Card>
            </div>
          </div>

          <Card>
            <CardHeader><CardTitle className="text-base">Basket attention</CardTitle></CardHeader>
            <CardContent>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {selectedBaskets.map((row) => (
                  <div key={row.basket} className={`rounded-lg border p-3 ${row.selected ? "border-primary/40 bg-primary/5" : ""}`}>
                    <div className="flex items-center justify-between">
                      <span className="font-semibold">{row.basket}</span>
                      <Badge variant={row.selected ? "default" : "outline"}>{row.selected ? "selected" : "watch"}</Badge>
                    </div>
                    <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                      <span>Composite {row.composite_percentile?.toFixed(2) ?? "—"}</span>
                      <span>Breadth {pct(row.breadth_above_sma50)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-base">Forward ticket history</CardTitle></CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {history.map((row) => (
                  <Badge key={row.as_of_date} variant={row.as_of_date === ticket.as_of_date ? "default" : "outline"}>
                    {row.as_of_date} · {row.market_regime || "unknown"} · {row.ticket_turnover?.toFixed(2) ?? "—"}x
                  </Badge>
                ))}
              </div>
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}
