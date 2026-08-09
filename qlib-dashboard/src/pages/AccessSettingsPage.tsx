import { CheckCircle2, Loader2, LockKeyhole, RefreshCw, ShieldAlert } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useOutletContext } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useAccessControl } from '@/hooks/useAccessControl';
import { ACCESS_TIERS, type AccessResourceType, type AccessTier } from '@/lib/model-access';
import type { RunWorkspaceContext } from '@/lib/run-workspace';
import { routes } from '@/routes';

const TIER_LABEL: Record<AccessTier, string> = {
  public: 'Guest — no sign-in',
  authenticated: 'Member — signed in',
  pro: 'Pro subscription',
  owner: 'Owner only',
};

function PolicyRow({ type, id, label }: { type: AccessResourceType; id: string; label: string }) {
  const access = useAccessControl();
  const current = access.requiredTier(type, id);
  const [selected, setSelected] = useState<AccessTier>(current);
  const [saving, setSaving] = useState(false);
  const [outcome, setOutcome] = useState<string | null>(null);

  useEffect(() => setSelected(current), [current]);

  const save = async () => {
    setSaving(true);
    setOutcome(null);
    try {
      await access.savePolicy(type, id, selected);
      setOutcome('Saved');
    } catch (error) {
      setOutcome(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="grid gap-3 border-b p-4 last:border-b-0 md:grid-cols-[minmax(0,1fr)_240px_96px] md:items-center">
      <div className="min-w-0"><p className="text-sm font-semibold">{label}</p><p className="mt-1 break-all font-mono text-[10px] text-muted-foreground">{type}:{id}</p>{outcome && <p className="mt-1 text-xs text-muted-foreground">{outcome}</p>}</div>
      <select value={selected} onChange={(event) => { setSelected(event.target.value as AccessTier); setOutcome(null); }} className="h-9 rounded-md border bg-background px-2 text-sm" aria-label={`${label} minimum access tier`}>
        {ACCESS_TIERS.map((tier) => <option key={tier} value={tier}>{TIER_LABEL[tier]}</option>)}
      </select>
      <Button type="button" size="sm" disabled={saving || selected === current} onClick={() => void save()}>{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Save'}</Button>
    </div>
  );
}

export function AccessSettingsPage() {
  const workspace = useOutletContext<RunWorkspaceContext>();
  const access = useAccessControl();
  const modelFamilies = useMemo(() => {
    const rows = new Map<string, string>();
    workspace.runs.filter((run) => run.channel === 'formal').forEach((run) => rows.set(run.modelFamilyId, run.title));
    return [...rows.entries()].sort((left, right) => left[1].localeCompare(right[1]));
  }, [workspace.runs]);
  const modules = routes.filter((route) => route.accessResourceId).map((route) => [route.accessResourceId!, route.title] as const);

  return (
    <div className="mx-auto max-w-[1100px] space-y-6 pb-16">
      <header className="max-w-3xl"><p className="text-xs font-bold uppercase tracking-[0.2em] text-primary">Owner control</p><h1 className="mt-2 text-3xl font-black tracking-tight">Access Settings</h1><p className="mt-3 text-sm leading-relaxed text-muted-foreground">Choose the minimum audience for each formal model family and protected product module. Model identity and evidence artifacts are not changed.</p></header>

      <div className="flex items-start gap-3 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm"><ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" /><div><p className="font-semibold">Four-level access order</p><p className="mt-1 text-xs text-muted-foreground">Guest &lt; Member &lt; Pro &lt; Owner. Higher levels inherit lower-level access. Owner status comes from verified Supabase app metadata, never editable profile metadata.</p></div></div>

      {access.policyError && <div className="flex items-start justify-between gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm"><div><p className="font-semibold text-destructive">Remote policy store unavailable</p><p className="mt-1 text-xs text-muted-foreground">Safe built-in defaults remain active. {access.policyError}</p></div><Button type="button" size="sm" variant="outline" onClick={() => void access.reloadPolicies()}><RefreshCw className="mr-2 h-4 w-4" />Retry</Button></div>}

      <Card><CardHeader><CardTitle className="flex items-center gap-2 text-base"><LockKeyhole className="h-4 w-4" />Model families</CardTitle></CardHeader><CardContent className="p-0">{modelFamilies.map(([id, label]) => <PolicyRow key={id} type="model" id={id} label={label} />)}</CardContent></Card>
      <Card><CardHeader><CardTitle className="flex items-center gap-2 text-base"><CheckCircle2 className="h-4 w-4" />Product modules</CardTitle></CardHeader><CardContent className="p-0">{modules.map(([id, label]) => <PolicyRow key={id} type="module" id={id} label={label} />)}</CardContent></Card>
    </div>
  );
}
