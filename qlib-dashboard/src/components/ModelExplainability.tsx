import { useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, CartesianGrid } from 'recharts';
import { BrainCircuit } from 'lucide-react';

export function ModelExplainability({ featureImportance }: { featureImportance?: Record<string, number> }) {
    const data = useMemo(() => {
        if (!featureImportance) return [];
        return Object.entries(featureImportance)
            .map(([name, value]) => ({ name: name.replace(/_/g, ' '), value }))
            .sort((a, b) => b.value - a.value);
    }, [featureImportance]);

    if (data.length === 0) return null;

    return (
        <Card className="border shadow-lg bg-card overflow-hidden">
            <CardHeader className="bg-muted/30 border-b flex flex-row items-center justify-between py-4 px-8">
                <div className="flex items-center gap-4">
                    <div className="p-2 bg-primary/10 rounded-xl text-primary">
                        <BrainCircuit className="h-5 w-5" />
                    </div>
                    <div className="space-y-0.5 text-left">
                        <CardTitle className="text-sm font-black uppercase tracking-[0.1em]">Explainable AI (XAI)</CardTitle>
                        <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-tight text-left">Feature Importance & Decision Drivers</p>
                    </div>
                </div>
            </CardHeader>
            <CardContent className="p-6">
                <div className="h-[240px] w-full">
                    <ResponsiveContainer width="100%" height="100%">
                        <BarChart layout="vertical" data={data} margin={{ left: 10, right: 30, top: 5, bottom: 5 }}>
                            <CartesianGrid strokeDasharray="3 3" horizontal={false} strokeOpacity={0.05} />
                            <XAxis type="number" tick={{ fontSize: 9, fontWeight: 800 }} axisLine={false} tickLine={false} />
                            <YAxis dataKey="name" type="category" width={140} tick={{ fontSize: 10, fontWeight: 800, fill: 'hsl(var(--foreground))' }} interval={0} axisLine={false} tickLine={false} />
                            <Tooltip
                                cursor={{ fill: 'rgba(0,0,0,0.03)' }}
                                contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 25px 50px -12px rgb(0 0 0 / 0.25)', fontSize: '10px', fontWeight: 'bold' }}
                                formatter={(v: number) => [`${(v * 100).toFixed(1)}%`, 'Influence Weight']}
                            />
                            <Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={20}>
                                {data.map((_, index) => (
                                    <Cell key={`cell-${index}`} fill="hsl(var(--primary))" fillOpacity={0.8 - index * 0.1} className="hover:fill-opacity-100 transition-all duration-300" />
                                ))}
                            </Bar>
                        </BarChart>
                    </ResponsiveContainer>
                </div>
                <div className="mt-4 p-4 rounded-xl bg-muted/20 border text-xs text-muted-foreground leading-relaxed italic text-left">
                    <strong>Agent Analysis:</strong> The model heavily relies on <span className="font-bold text-primary">{data[0]?.name}</span> ({((data[0]?.value || 0) * 100).toFixed(1)}%) weighting, indicating strong sensitivity to current market momentum regimes rather than pure value reversions. Caution advised during structural breaks.
                </div>
            </CardContent>
        </Card>
    );
}
