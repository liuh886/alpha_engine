import { useGlobalStore } from '@/store/globalStore';
import { dataApi } from '@/api/dataApi';
import { useSystemHealth } from '@/hooks/useSystemHealth';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Play, Database, Activity, CheckCircle2, Target, ClipboardList, ScrollText, ArrowRight, BarChart3 } from 'lucide-react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import type { ModelData } from '@/lib/data-parser';
import type { JobEnvelope } from '@/api/jobsApi';

interface AppContext {
  models: ModelData[];
  selectedModelId: string;
  refreshModels: (opts?: { selectLatest?: boolean }) => Promise<ModelData[] | null>;
  refreshDataStatus: () => Promise<void>;
  submitAndPoll: (submitFn: () => Promise<JobEnvelope>, onComplete?: (status: string) => void) => Promise<JobEnvelope>;
}

const HEALTH_BADGE: Record<string, { label: string; className: string }> = {
  online: { label: 'Online', className: 'text-green-500 bg-green-500/10' },
  checking: { label: 'Checking', className: 'text-muted-foreground bg-muted animate-pulse' },
  unavailable: { label: 'Unavailable', className: 'text-red-500 bg-red-500/10 animate-pulse' },
  degraded: { label: 'Degraded', className: 'text-yellow-500 bg-yellow-500/10' },
};

export function HomePage() {
  const { qualityStatus, latestCalendarDay, activeJobsCount, dataGeneratedAt, demoMode } = useGlobalStore();
  const { models, refreshModels, refreshDataStatus, submitAndPoll } = useOutletContext<AppContext>();
  const { state: healthState } = useSystemHealth();
  const navigate = useNavigate();

  const latestModel = models.length > 0 ? models[0] : null;

  const startUpdateData = async () => {
    try {
      await submitAndPoll(
        () => dataApi.updateData(false, 30),
        async () => {
          await refreshModels();
          await refreshDataStatus();
        }
      );
    } catch {
      // ignore
    }
  };

  return (
    <div className="space-y-6 max-w-[1400px] mx-auto pb-16">
      <div className="border-b pb-4">
        <div className="flex items-center gap-3">
          <h1 className="text-4xl font-black tracking-tight text-foreground">System Home</h1>
          <Badge variant="secondary" className={`font-mono text-[10px] uppercase border-none ${demoMode ? 'text-blue-500 bg-blue-500/10' : 'text-green-500 bg-green-500/10'}`}>
            {demoMode ? 'Demo Mode' : 'Live Mode'}
          </Badge>
        </div>
        <p className="text-muted-foreground mt-2 font-medium">
          {demoMode
            ? 'Explore the dashboard with sample data. No real trades or data updates.'
            : 'Daily system readiness and operations snapshot.'
          }
        </p>
      </div>

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
            {qualityStatus !== 'ok' && !demoMode && (
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
            <Badge variant="secondary" className={`font-mono text-[10px] uppercase border-none ${HEALTH_BADGE[healthState].className}`}>
              {HEALTH_BADGE[healthState].label}
            </Badge>
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

      <h2 className="text-lg font-bold uppercase tracking-widest text-muted-foreground mt-8 mb-4">Workbench Actions</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card className="bg-card shadow-md border-primary/20 bg-primary/5">
          <CardHeader className="pb-3 border-b border-primary/10 flex flex-row items-center justify-between">
            <CardTitle className="text-sm font-bold flex items-center gap-2 uppercase tracking-wider text-primary">
              <Target className="h-4 w-4" /> {demoMode ? 'Explore Demo' : 'Recommended Action'}
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-5 space-y-4 flex flex-col justify-between">
            {demoMode ? (
              <>
                <div className="text-sm text-blue-600 font-medium mb-2">
                  You are viewing sample data. Explore the dashboard, model registry, and data pages.
                </div>
                {latestModel && (
                  <div className="text-xs text-muted-foreground">
                    Latest model: <span className="font-mono font-bold">{latestModel.name}</span>
                  </div>
                )}
                <div className="flex flex-col gap-2">
                  <Button onClick={() => navigate('/dashboard')} className="w-full text-xs font-bold uppercase tracking-widest">
                    <Play className="h-3 w-3 mr-2" /> Explore Demo Dashboard
                  </Button>
                  <Button onClick={() => navigate('/models')} variant="outline" className="w-full text-xs font-bold uppercase tracking-widest">
                    <Database className="h-3 w-3 mr-2" /> View Model Registry
                  </Button>
                </div>
              </>
            ) : (
              <>
                {qualityStatus !== 'ok' ? (
                  <div className="text-sm text-destructive font-medium mb-2">Data is stale. Your next step is to run a data sync.</div>
                ) : (
                  <div className="text-sm text-green-600 font-medium mb-2">System ready. Time to research new factors or run a backtest.</div>
                )}
                {latestModel && (
                  <div className="text-xs text-muted-foreground">
                    Latest model: <span className="font-mono font-bold">{latestModel.name}</span>
                  </div>
                )}
                <Button onClick={() => navigate(qualityStatus !== 'ok' ? '/data' : '/backtest')} className="w-full text-xs font-bold uppercase tracking-widest mt-auto">
                  <Play className="h-3 w-3 mr-2" /> {qualityStatus !== 'ok' ? 'Go to Data Manager' : 'Start Backtest'}
                </Button>
              </>
            )}
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
