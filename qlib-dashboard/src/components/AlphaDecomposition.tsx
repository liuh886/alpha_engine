import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, CartesianGrid } from "recharts";
import { cn } from "@/lib/utils";

interface AlphaComponent {
  name: string;
  value: number;
  description: string;
}

interface DecompositionData {
  total_return: number;
  market_return: number;
  components: AlphaComponent[];
}

const COLORS: Record<string, string> = {
  Selection: "#22c55e",
  Timing: "#3b82f6",
  Sizing: "#8b5cf6",
  Cost: "#ef4444",
  Beta: "#f59e0b",
};

export function AlphaDecomposition({ runId }: { runId: string }) {
  const [data, setData] = useState<DecompositionData | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!runId) return;
    setLoading(true);
    fetch(`/api/backtest/${encodeURIComponent(runId)}/alpha-decomposition`)
      .then(r => r.json())
      .then(json => {
        if (json.ok && json.components?.length) setData(json);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [runId]);

  if (loading) return <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">Computing...</CardContent></Card>;
  if (!data) return null;

  const CustomTooltip = ({ active, payload }: any) => {
    if (!active || !payload?.length) return null;
    const d = payload[0].payload;
    return (
      <div className="bg-background/95 border shadow-lg rounded p-2.5 text-[10px] min-w-[160px]">
        <p className="font-semibold mb-1">{d.name}</p>
        <p className="text-muted-foreground">{d.description}</p>
        <p className="font-mono mt-1">{d.value >= 0 ? "+" : ""}{d.value.toFixed(2)}%</p>
      </div>
    );
  };

  return (
    <Card>
      <CardHeader className="pb-3 border-b">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold">Alpha Decomposition</CardTitle>
          <div className="flex gap-3 text-xs text-muted-foreground">
            <span>Total: <span className="font-mono text-foreground">{data.total_return.toFixed(2)}%</span></span>
            <span>Market: <span className="font-mono text-foreground">{data.market_return.toFixed(2)}%</span></span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-4">
        <div className="h-[200px] mb-4">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data.components} margin={{ left: 10, right: 30, top: 5, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} strokeOpacity={0.05} />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={v => `${v}%`} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} width={45} />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: "rgba(0,0,0,0.03)" }} />
              <Bar dataKey="value" radius={[3, 3, 0, 0]} barSize={40}>
                {data.components.map((entry, i) => (
                  <Cell key={i} fill={COLORS[entry.name] || "hsl(var(--primary))"} fillOpacity={0.8} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="space-y-1.5">
          {data.components.map((c, i) => (
            <div key={i} className="flex items-center justify-between text-xs py-1 border-b last:border-0">
              <div className="flex items-center gap-2">
                <div className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: COLORS[c.name] || "hsl(var(--primary))" }} />
                <span className="font-medium">{c.name}</span>
                <span className="text-muted-foreground">— {c.description}</span>
              </div>
              <span className={cn("font-mono", c.value >= 0 ? "text-green-500" : "text-red-500")}>
                {c.value >= 0 ? "+" : ""}{c.value.toFixed(2)}%
              </span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
