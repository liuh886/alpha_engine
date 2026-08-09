import { Crown, LogIn, ShieldCheck } from 'lucide-react';

import type { AccessTier } from '@/lib/model-access';
import { Button } from './ui/button';

const COPY: Record<Exclude<AccessTier, 'public'>, { eyebrow: string; title: (resource: string) => string; description: string; action: string }> = {
  authenticated: {
    eyebrow: 'Signed-in access',
    title: (resource) => `Sign in to open ${resource}`,
    description: 'This product is available to every signed-in AlphaEngine account. AlphaEngine Pro is not required.',
    action: 'Sign in to continue',
  },
  pro: {
    eyebrow: 'AlphaEngine Pro',
    title: (resource) => `${resource} is a Pro product`,
    description: 'This product requires an active AlphaEngine Pro subscription. Sign in or open your account to review Pro access.',
    action: 'View Pro access',
  },
  owner: {
    eyebrow: 'Owner only',
    title: (resource) => `${resource} requires Owner access`,
    description: 'This area controls AlphaEngine access policy and is restricted to the verified product Owner.',
    action: 'Open account',
  },
};

export function AccessGate({ requiredTier, resource, openAccount }: { requiredTier: Exclude<AccessTier, 'public'>; resource: string; openAccount: () => void }) {
  const copy = COPY[requiredTier];
  const Icon = requiredTier === 'pro' ? Crown : requiredTier === 'owner' ? ShieldCheck : LogIn;
  return (
    <section className="mx-auto flex min-h-[420px] max-w-3xl items-center justify-center">
      <div className="w-full rounded-2xl border bg-card p-8 text-center shadow-sm md:p-12">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full border border-primary/20 bg-primary/10 text-primary"><Icon className="h-5 w-5" /></div>
        <div className="mt-5 text-xs font-bold uppercase tracking-[0.16em] text-primary">{copy.eyebrow}</div>
        <h2 className="mt-3 text-2xl font-black tracking-tight">{copy.title(resource)}</h2>
        <p className="mx-auto mt-3 max-w-xl text-sm leading-relaxed text-muted-foreground">{copy.description}</p>
        <Button type="button" className="mt-7 gap-2" onClick={openAccount}><Icon className="h-4 w-4" /> {copy.action}</Button>
      </div>
    </section>
  );
}
