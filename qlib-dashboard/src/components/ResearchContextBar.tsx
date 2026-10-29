import { Clock3, Database, ShieldAlert } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import type { GovernedRunSummary } from '@/lib/governed-run';

export function ResearchContextBar({ run, fleet, loading = false, unavailable = false }: {
  run?: GovernedRunSummary | null; fleet?: GovernedRunSummary[]; loading?: boolean; unavailable?: boolean;
}) {
  const pending = loading && !run && !fleet?.length;
  return <div className="research-context-bar" role="status" aria-busy={loading} aria-label={fleet ? 'Strategy fleet context' : 'Active research context'}>
    <div className="research-context-item min-w-0"><Database className="h-3.5 w-3.5" /><span className="truncate font-medium">{pending ? 'Reading formal strategy catalog…' : unavailable ? 'Formal strategy catalog unavailable' : fleet ? 'Formal strategy fleet · ' + fleet.length + ' strategies' : run?.title || 'Formal research evidence'}</span></div>
    <div className="research-context-item"><Clock3 className="h-3.5 w-3.5" /><span>{pending ? 'Reading evidence cutoffs…' : unavailable ? 'Evidence cutoffs unavailable' : fleet ? 'Evidence cutoffs shown per strategy' : 'Cutoff ' + (run?.evidenceCutoff || 'not declared')}</span></div>
    <div className="research-context-item hidden lg:flex">{fleet ? [...new Set(fleet.map(item => item.market.toUpperCase()))].sort().join(' · ') : run?.market.toUpperCase()}</div>
    <Badge variant="outline" className="context-badge ml-auto text-amber-700 dark:text-amber-300"><ShieldAlert className="mr-1 h-3 w-3" />Research only</Badge>
  </div>;
}
