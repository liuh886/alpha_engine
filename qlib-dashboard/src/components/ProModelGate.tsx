import { Crown, LockKeyhole } from 'lucide-react';
import type { GovernedRunSummary } from '@/lib/governed-run';
import { Button } from './ui/button';

export function ProModelGate({ run, openAccount }: { run: GovernedRunSummary; openAccount: () => void }) {
  return (
    <section className="mx-auto flex min-h-[420px] max-w-3xl items-center justify-center">
      <div className="w-full rounded-2xl border bg-card p-8 text-center shadow-sm md:p-12">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full border border-primary/20 bg-primary/10 text-primary">
          <LockKeyhole className="h-5 w-5" />
        </div>
        <div className="mt-5 flex items-center justify-center gap-2">
          <span className="rounded-full border border-primary/25 bg-primary/10 px-2.5 py-1 text-[10px] font-black uppercase tracking-[0.16em] text-primary">Pro model</span>
          <span className="text-xs text-muted-foreground">{run.modelVersionId}</span>
        </div>
        <h2 className="mt-4 text-2xl font-black tracking-tight">{run.title}</h2>
        <p className="mx-auto mt-3 max-w-xl text-sm leading-relaxed text-muted-foreground">
          QQQ strategy details, live allocation state, formal backtests, attribution and retained research evidence are available to AlphaEngine Pro members.
        </p>
        <Button type="button" className="mt-7 gap-2" onClick={openAccount}>
          <Crown className="h-4 w-4" /> Open Pro access
        </Button>
        <p className="mt-3 text-xs text-muted-foreground">Other formal AlphaEngine models remain available on the Free tier.</p>
      </div>
    </section>
  );
}
