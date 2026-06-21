import { useAppBootstrap } from '@/hooks/useAppBootstrap';
import { useGlobalStore } from '@/store/globalStore';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Play, Database, Cpu, Activity, AlertCircle, CheckCircle2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export function TrueDashboard({ startUpdateData }: { startUpdateData: () => Promise<void> }) {
  const { qualityStatus, latestCalendarDay, activeJobsCount } = useGlobalStore();
  const { models } = useAppBootstrap();
  const navigate = useNavigate();

  const bestModel = models.length > 0 ? models[0] : null; // simplify: first is best

  return (
    <div className="space-y-6 max-w-[1200px] mx-auto pb-16">
      <div className="border-b pb-4">
        <h1 className="text-3xl font-bold tracking-tight">Daily Research Home</h1>
        <p className="text-muted-foreground mt-2">Welcome to your quantitative research workspace.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Q1: Data Status */}
        <Card>
          <CardHeader className="pb-3 border-b flex flex-row items-center justify-between">
            <CardTitle className="text-lg font-semibold flex items-center gap-2">
              <Database className="h-5 w-5" /> Data Status
            </CardTitle>
            <Badge variant={qualityStatus === 'ok' ? 'default' : 'destructive'}>
              {qualityStatus === 'ok' ? 'Available' : 'Needs Attention'}
            </Badge>
          </CardHeader>
          <CardContent className="pt-5 space-y-4">
            <div>
              <span className="text-sm text-muted-foreground block mb-1">Latest Calendar Day:</span>
              <span className="text-xl font-mono">{latestCalendarDay || 'N/A'}</span>
            </div>
            {qualityStatus !== 'ok' && (
              <Button onClick={startUpdateData} variant="outline" className="w-full text-xs">
                Update Data Now
              </Button>
            )}
          </CardContent>
        </Card>

        {/* Q2: Best Model */}
        <Card>
          <CardHeader className="pb-3 border-b flex flex-row items-center justify-between">
            <CardTitle className="text-lg font-semibold flex items-center gap-2">
              <Cpu className="h-5 w-5" /> Best Model
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-5 space-y-4">
            {bestModel ? (
              <>
                <div>
                  <span className="text-sm font-semibold truncate block mb-1">{bestModel.name}</span>
                  <span className="text-xs text-muted-foreground font-mono block">Run: {bestModel.id}</span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div>
                    <span className="text-muted-foreground text-xs block">Return</span>
                    <span className="font-mono text-green-500">
                      {(bestModel.backtest.metrics.annualized_return * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div>
                    <span className="text-muted-foreground text-xs block">Sharpe</span>
                    <span className="font-mono">
                      {bestModel.backtest.metrics.information_ratio.toFixed(2)}
                    </span>
                  </div>
                </div>
                <Button onClick={() => navigate('/models')} variant="outline" className="w-full text-xs">
                  Model Lab
                </Button>
              </>
            ) : (
              <div className="text-muted-foreground text-sm py-4 text-center">
                No models found in registry.
              </div>
            )}
          </CardContent>
        </Card>

        {/* Q3: Today's Actions */}
        <Card>
          <CardHeader className="pb-3 border-b flex flex-row items-center justify-between">
            <CardTitle className="text-lg font-semibold flex items-center gap-2">
              <Activity className="h-5 w-5" /> What to do today?
            </CardTitle>
            {activeJobsCount > 0 && (
              <Badge variant="outline" className="animate-pulse">
                {activeJobsCount} Active Job{activeJobsCount > 1 ? 's' : ''}
              </Badge>
            )}
          </CardHeader>
          <CardContent className="pt-5 space-y-3">
            {qualityStatus !== 'ok' ? (
              <div className="flex items-start gap-3 p-3 bg-destructive/10 rounded-lg">
                <AlertCircle className="h-5 w-5 text-destructive mt-0.5" />
                <div className="text-sm text-destructive">Data is stale. Please bootstrap or update data first.</div>
              </div>
            ) : (
              <div className="flex items-start gap-3 p-3 bg-green-500/10 rounded-lg">
                <CheckCircle2 className="h-5 w-5 text-green-500 mt-0.5" />
                <div className="text-sm text-green-600">Data is up to date. Ready for backtesting.</div>
              </div>
            )}
            <Button onClick={() => navigate('/backtest')} className="w-full justify-between mt-4">
              <span>Go to Backtest Workbench</span>
              <Play className="h-4 w-4" />
            </Button>
            <Button onClick={() => navigate('/system')} variant="outline" className="w-full">
              System & Ops
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
