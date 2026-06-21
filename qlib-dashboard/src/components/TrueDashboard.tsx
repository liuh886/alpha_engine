import { useAppBootstrap } from '@/hooks/useAppBootstrap';
import { useGlobalStore } from '@/store/globalStore';
import { useJobs } from '@/hooks/useJobs';
import { dataApi } from '@/api/dataApi';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Placeholder } from '@/components/Placeholder';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Play, Database, Cpu, Activity, AlertCircle, CheckCircle2, FlaskConical, Target, ShieldAlert, BarChart3, ClipboardList, ScrollText, ArrowRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export function TrueDashboard() {
  const { qualityStatus, latestCalendarDay, activeJobsCount, dataGeneratedAt } = useGlobalStore();
  const { models, fetchModels, loadDataStatus } = useAppBootstrap();
  const { submitAndPoll } = useJobs();
  const navigate = useNavigate();

  const startUpdateData = async () => {
    try {
      await submitAndPoll(
        () => dataApi.updateData(false, 30),
        async () => {
          await fetchModels();
          await loadDataStatus();
        }
      );
    } catch {
      // ignore
    }
  };

  const bestModel = models.length > 0 ? models[0] : null;

  return (
    <div className="space-y-6 max-w-[1400px] mx-auto pb-16">
      <div className="border-b pb-4">
        <h1 className="text-4xl font-black tracking-tight text-foreground">Research Cockpit</h1>
        <p className="text-muted-foreground mt-2 font-medium">Daily system readiness and model performance snapshot.</p>
      </div>

      {/* TOP LAYER: Readiness */}
      <h2 className="text-lg font-bold uppercase tracking-widest text-muted-foreground mt-8 mb-4">Readiness & Jobs</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card className="bg-card shadow-md border-border/50 transition-colors hover:border-primary/30">
          <CardHeader className="pb-3 border-b flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-bold flex items-center gap-2 uppercase tracking-wider text-muted-foreground">
              <Database className="h-4 w-4" /> Data Freshness
            </CardTitle>
            <Badge variant={qualityStatus === 'ok' ? 'default' : 'destructive'} className="font-mono text-[10px] uppercase">
              {qualityStatus === 'ok' ? 'Up to date' : 'Stale'}
            </Badge>
          </CardHeader>
          <CardContent className="pt-5 space-y-4">
            <div>
              <span className="text-xs text-muted-foreground uppercase font-bold tracking-widest block mb-1">Calendar Day</span>
              <span className="text-2xl font-mono font-black">{latestCalendarDay || 'N/A'}</span>
            </div>
            {qualityStatus !== 'ok' && (
              <Button onClick={startUpdateData} variant="outline" size="sm" className="w-full text-xs font-bold uppercase tracking-wider">
                <Play className="h-3 w-3 mr-2" /> Sync Data
              </Button>
            )}
          </CardContent>
        </Card>

        <Card className="bg-card shadow-md border-border/50 transition-colors hover:border-primary/30">
          <CardHeader className="pb-3 border-b flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-bold flex items-center gap-2 uppercase tracking-wider text-muted-foreground">
              <Activity className="h-4 w-4" /> Active Jobs
            </CardTitle>
            {activeJobsCount > 0 ? (
              <Badge variant="outline" className="font-mono text-[10px] uppercase border-amber-500 text-amber-500 animate-pulse">Running</Badge>
            ) : (
              <Badge variant="secondary" className="font-mono text-[10px] uppercase">Idle</Badge>
            )}
          </CardHeader>
          <CardContent className="pt-5 space-y-4 flex flex-col justify-between">
            <div>
              <span className="text-xs text-muted-foreground uppercase font-bold tracking-widest block mb-1">Background Tasks</span>
              <span className="text-2xl font-mono font-black">{activeJobsCount}</span>
            </div>
            <Button onClick={() => navigate('/system')} variant="ghost" size="sm" className="w-full text-xs font-bold uppercase tracking-wider mt-auto justify-between group">
              View System Logs <ArrowRight className="h-3 w-3 opacity-50 group-hover:opacity-100 transition-opacity" />
            </Button>
          </CardContent>
        </Card>

        <Card className="bg-card shadow-md border-border/50 transition-colors hover:border-primary/30">
          <CardHeader className="pb-3 border-b flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-bold flex items-center gap-2 uppercase tracking-wider text-muted-foreground">
              <CheckCircle2 className="h-4 w-4" /> System Health
            </CardTitle>
            <Badge variant="secondary" className="font-mono text-[10px] uppercase text-green-500 bg-green-500/10 border-none">Online</Badge>
          </CardHeader>
          <CardContent className="pt-5 space-y-4">
            <div>
              <span className="text-xs text-muted-foreground uppercase font-bold tracking-widest block mb-1">Last Data Gen</span>
              <span className="text-sm font-mono font-bold">{dataGeneratedAt ? new Date(dataGeneratedAt).toLocaleTimeString() : 'N/A'}</span>
            </div>
            <Button onClick={() => navigate('/agent')} variant="ghost" size="sm" className="w-full text-xs font-bold uppercase tracking-wider justify-between group">
              Agent Control <ArrowRight className="h-3 w-3 opacity-50 group-hover:opacity-100 transition-opacity" />
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* MIDDLE LAYER: Model & Risk Snapshot */}
      <h2 className="text-lg font-bold uppercase tracking-widest text-muted-foreground mt-8 mb-4">Model & Risk</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card className="bg-card shadow-md border-border/50 transition-colors hover:border-primary/30">
          <CardHeader className="pb-3 border-b flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-bold flex items-center gap-2 uppercase tracking-wider text-muted-foreground">
              <Cpu className="h-4 w-4" /> Top Model
            </CardTitle>
            <Badge variant="outline" className="font-mono text-[10px] uppercase border-primary text-primary">Champion</Badge>
          </CardHeader>
          <CardContent className="pt-5 space-y-4">
            {bestModel ? (
              <>
                <div>
                  <span className="text-lg font-black truncate block mb-1">{bestModel.name}</span>
                  <span className="text-[10px] text-muted-foreground font-mono uppercase tracking-widest block">{bestModel.id.slice(0,18)}</span>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <span className="text-muted-foreground text-[10px] font-bold uppercase tracking-wider block">Return</span>
                    <span className="font-mono text-lg font-black text-green-500">
                      {(bestModel.backtest.metrics.annualized_return * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div>
                    <span className="text-muted-foreground text-[10px] font-bold uppercase tracking-wider block">Sharpe</span>
                    <span className="font-mono text-lg font-black">
                      {bestModel.backtest.metrics.information_ratio.toFixed(2)}
                    </span>
                  </div>
                </div>
              </>
            ) : (
              <Placeholder icon={Cpu} title="No Models" description="No models found in the registry." />
            )}
          </CardContent>
        </Card>

        <Card className="bg-card shadow-md border-border/50 transition-colors hover:border-primary/30">
          <CardHeader className="pb-3 border-b flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-bold flex items-center gap-2 uppercase tracking-wider text-muted-foreground">
              <FlaskConical className="h-4 w-4" /> Latest Backtest
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-5 space-y-4">
            {bestModel ? (
              <>
                <div>
                  <span className="text-xs text-muted-foreground uppercase font-bold tracking-widest block mb-1">Win Rate</span>
                  <span className="font-mono text-lg font-black">
                    {(bestModel.backtest.metrics.win_rate * 100).toFixed(1)}%
                  </span>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground uppercase font-bold tracking-widest block mb-1">Market</span>
                  <Badge variant="secondary" className="font-mono text-[10px]">{bestModel.market}</Badge>
                </div>
              </>
            ) : (
              <Placeholder icon={FlaskConical} title="N/A" description="Awaiting model selection." />
            )}
          </CardContent>
        </Card>

        <Card className="bg-card shadow-md border-border/50 transition-colors hover:border-primary/30">
          <CardHeader className="pb-3 border-b flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-bold flex items-center gap-2 uppercase tracking-wider text-muted-foreground">
              <ShieldAlert className="h-4 w-4" /> Risk Snapshot
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-5 space-y-4">
            {bestModel ? (
              <>
                <div>
                  <span className="text-xs text-muted-foreground uppercase font-bold tracking-widest block mb-1">Max Drawdown</span>
                  <span className="font-mono text-lg font-black text-red-500">
                    {(bestModel.backtest.metrics.max_drawdown * 100).toFixed(1)}%
                  </span>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground uppercase font-bold tracking-widest block mb-1">Annual Volatility</span>
                  <span className="font-mono text-lg font-black">
                    {(bestModel.backtest.metrics.annualized_volatility * 100).toFixed(1)}%
                  </span>
                </div>
              </>
            ) : (
              <Placeholder icon={ShieldAlert} title="N/A" description="Awaiting model selection." />
            )}
          </CardContent>
        </Card>
      </div>

      {/* BOTTOM LAYER: Actions */}
      <h2 className="text-lg font-bold uppercase tracking-widest text-muted-foreground mt-8 mb-4">Workbench Actions</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card className="bg-card shadow-md border-primary/20 bg-primary/5">
          <CardHeader className="pb-3 border-b border-primary/10 flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-bold flex items-center gap-2 uppercase tracking-wider text-primary">
              <Target className="h-4 w-4" /> Recommended Action
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-5 space-y-4 flex flex-col justify-between">
            {qualityStatus !== 'ok' ? (
              <div className="text-sm text-destructive font-medium mb-2">Data is stale. Your next step is to run a data sync.</div>
            ) : (
              <div className="text-sm text-green-600 font-medium mb-2">System ready. Time to research new factors or run a backtest.</div>
            )}
            <Button onClick={() => navigate(qualityStatus !== 'ok' ? '/data' : '/backtest')} className="w-full text-xs font-bold uppercase tracking-widest mt-auto">
              <Play className="h-3 w-3 mr-2" /> {qualityStatus !== 'ok' ? 'Go to Data Manager' : 'Start Backtest'}
            </Button>
          </CardContent>
        </Card>

        <Card className="bg-card shadow-md border-border/50 hover:border-primary/30 transition-colors cursor-pointer group" onClick={() => navigate('/experiments')}>
          <CardHeader className="pb-3 border-b flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-bold flex items-center gap-2 uppercase tracking-wider text-muted-foreground">
              <ClipboardList className="h-4 w-4" /> Experiments
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-5 flex flex-col justify-center h-full">
            <div className="text-center space-y-2">
              <BarChart3 className="h-8 w-8 text-muted-foreground/30 mx-auto group-hover:text-primary transition-colors" />
              <p className="text-sm font-bold text-muted-foreground group-hover:text-foreground transition-colors">View Training Logs</p>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-card shadow-md border-border/50 hover:border-primary/30 transition-colors cursor-pointer group" onClick={() => navigate('/reports')}>
          <CardHeader className="pb-3 border-b flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-bold flex items-center gap-2 uppercase tracking-wider text-muted-foreground">
              <ScrollText className="h-4 w-4" /> Reports
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-5 flex flex-col justify-center h-full">
            <div className="text-center space-y-2">
              <ScrollText className="h-8 w-8 text-muted-foreground/30 mx-auto group-hover:text-primary transition-colors" />
              <p className="text-sm font-bold text-muted-foreground group-hover:text-foreground transition-colors">Attribution & Tearsheets</p>
            </div>
          </CardContent>
        </Card>
      </div>

    </div>
  );
}
