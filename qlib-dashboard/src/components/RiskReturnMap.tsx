import { useMemo } from 'react';
import {
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { ModelData } from '@/lib/data-parser';
import { projectFormalMetric } from '@/lib/formal-evidence';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

const POINT_COLORS = ['hsl(var(--primary))', '#f59e0b', '#0ea5e9', '#8b5cf6', '#ec4899'];

type RiskReturnPoint = {
  id: string;
  label: string;
  drawdown: number;
  annualReturn: number;
  sharpe: number | null;
};

function formatPct(value: number) {
  return `${(value * 100).toFixed(2)}%`;
}

export function RiskReturnMap({ models, comparable }: { models: ModelData[]; comparable: boolean }) {
  const points = useMemo<RiskReturnPoint[]>(() => models.flatMap((model) => {
    const annualReturn = projectFormalMetric(model, ['Annualized Return', 'CAGR']).value;
    const maxDrawdown = projectFormalMetric(model, ['Max Drawdown']).value;
    const sharpe = projectFormalMetric(model, ['Sharpe Ratio']).value;
    if (annualReturn === null || maxDrawdown === null) return [];
    return [{
      id: model.id,
      label: (model.name || model.id).length > 22 ? `${(model.name || model.id).slice(0, 21)}…` : (model.name || model.id),
      drawdown: Math.abs(maxDrawdown),
      annualReturn,
      sharpe,
    }];
  }), [models]);

  if (points.length < 2) return null;

  return (
    <Card data-testid="risk-return-map">
      <CardHeader className="border-b pb-3">
        <CardTitle className="text-sm font-semibold">Risk–return map</CardTitle>
        <p className="mt-1 text-xs text-muted-foreground">
          Annualized return versus absolute max drawdown. Upper-left is more efficient, but {comparable ? 'only aligned formal records are ranked in the table above.' : 'the selected records are not contract-aligned, so this view is descriptive only.'}
        </p>
      </CardHeader>
      <CardContent className="h-[330px] pt-4 sm:h-[380px]">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 24, right: 34, bottom: 12, left: 6 }}>
            <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.12} />
            <XAxis
              type="number"
              dataKey="drawdown"
              name="Max drawdown"
              tickFormatter={(value) => `${(Number(value) * 100).toFixed(0)}%`}
              tick={{ fontSize: 9 }}
              axisLine={false}
              tickLine={false}
              label={{ value: 'Max drawdown →', position: 'insideBottomRight', offset: -6, fontSize: 9 }}
            />
            <YAxis
              type="number"
              dataKey="annualReturn"
              name="Annualized return"
              tickFormatter={(value) => `${(Number(value) * 100).toFixed(0)}%`}
              tick={{ fontSize: 9 }}
              axisLine={false}
              tickLine={false}
              width={48}
            />
            <Tooltip
              cursor={{ strokeDasharray: '3 3' }}
              formatter={(value, name) => [name === 'Max drawdown' || name === 'Annualized return' ? formatPct(Number(value)) : value, name]}
              contentStyle={{ fontSize: '10px' }}
            />
            <Scatter data={points} name="Models">
              {points.map((point, index) => <Cell key={point.id} fill={POINT_COLORS[index % POINT_COLORS.length]} />)}
              <LabelList dataKey="label" position="top" offset={8} style={{ fontSize: 9, fill: 'hsl(var(--foreground))' }} />
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
