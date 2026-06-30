import { useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

export function ModelExplainability({ featureImportance }: { featureImportance?: Record<string, number> }) {
  const data = useMemo(() => {
    if (!featureImportance) return [];
    return Object.entries(featureImportance)
      .map(([name, value]) => ({ name: name.replace(/_/g, ' '), value }))
      .sort((a, b) => b.value - a.value);
  }, [featureImportance]);

  if (data.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-muted-foreground gap-3">
        <span className="text-4xl">🔬</span>
        <p className="text-sm font-medium">Model Explainability</p>
        <p className="text-xs text-muted-foreground/60 max-w-xs text-center">
          Feature importance is unavailable for this model. SHAP waterfall charts are planned.
        </p>
      </div>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-3 border-b">
        <CardTitle className="text-sm font-semibold">Feature Importance</CardTitle>
      </CardHeader>
      <CardContent className="pt-4">
        <div className="h-[240px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart layout="vertical" data={data} margin={{ left: 10, right: 30, top: 5, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} strokeOpacity={0.05} />
              <XAxis type="number" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis
                dataKey="name"
                type="category"
                width={140}
                tick={{ fontSize: 10 }}
                interval={0}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                cursor={{ fill: 'rgba(0,0,0,0.03)' }}
                formatter={(v: number) => [`${(v * 100).toFixed(1)}%`, 'Weight']}
              />
              <Bar dataKey="value" radius={[0, 3, 3, 0]} barSize={18}>
                {data.map((_, i) => (
                  <Cell key={i} fill="hsl(var(--primary))" fillOpacity={Math.max(0.3, 0.9 - i * 0.08)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        {data[0] && (
          <p className="mt-3 text-xs text-muted-foreground">
            Top feature: <span className="font-medium text-foreground">{data[0].name}</span> (
            {(data[0].value * 100).toFixed(1)}%)
          </p>
        )}
      </CardContent>
    </Card>
  );
}
