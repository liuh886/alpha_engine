import { CheckCircle2, Loader2, RefreshCw, ShieldAlert } from 'lucide-react';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useAccessControl } from '@/hooks/useAccessControl';
import { ACCESS_TIERS, type AccessResourceType, type AccessTier } from '@/lib/model-access';
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
  const access = useAccessControl();
  const modules = routes.filter((route) => route.accessResourceId).map((route) => [route.accessResourceId!, route.title] as const);

  return (
    <div className="mx-auto max-w-[1100px] space-y-6 pb-16">
      <header className="max-w-3xl"><p className="text-xs font-bold uppercase tracking-[0.2em] text-primary">Owner control</p><h1 className="mt-2 text-3xl font-black tracking-tight">Access Settings</h1><p className="mt-3 text-sm leading-relaxed text-muted-foreground">Configure independent product modules only. Historical strategy evidence stays public; live-strategy access comes from the governed Active Strategy Catalog.</p></header>

      <div className="flex items-start gap-3 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm"><ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" /><div><p className="font-semibold">One access authority per surface</p><p className="mt-1 text-xs text-muted-foreground">Guest &lt; Member &lt; Pro &lt; Owner. Strategy live-operation tiers are code-reviewed product policy; this screen only manages independent modules such as Security Explorer.</p></div></div>

      {access.policyError && <div className="flex items-start justify-between gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm"><div><p className="font-semibold text-destructive">Remote module policy store unavailable</p><p className="mt-1 text-xs text-muted-foreground">Safe built-in module defaults remain active. {access.policyError}</p></div><Button type="button" size="sm" variant="outline" onClick={() => void access.reloadPolicies()}><RefreshCw className="mr-2 h-4 w-4" />Retry</Button></div>}

      <Card><CardHeader><CardTitle className="flex items-center gap-2 text-base"><CheckCircle2 className="h-4 w-4" />Product modules</CardTitle></CardHeader><CardContent className="p-0">{modules.map(([id, label]) => <PolicyRow key={id} type="module" id={id} label={label} />)}</CardContent></Card>
    </div>
  );
}
