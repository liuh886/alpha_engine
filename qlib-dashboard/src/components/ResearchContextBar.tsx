import { CheckCircle2, Clock3, Database, ShieldAlert } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { useActiveResearchBundle } from '@/hooks/useActiveResearchBundle';
import type { GovernedRunSummary } from '@/lib/governed-run';
import { runtimeCapabilities } from '@/lib/runtime-capabilities';

const RUNTIME_LABELS = {
  static_artifact: 'Published artifact',
  local_artifact: 'Local artifact',
} as const;

export function ResearchContextBar({ run, fleet }: { run?: GovernedRunSummary | null; fleet?: GovernedRunSummary[] }) {
  const bundle = useActiveResearchBundle();
  const manifest = bundle?.manifest;
  const markets = fleet ? [...new Set(fleet.map((item) => item.market.toUpperCase()))].sort() : [];

  return (
    <div className="research-context-bar" role="status" aria-label={fleet ? 'Strategy fleet context' : 'Active research context'}>
      <div className="research-context-item min-w-0">
        <Database className="h-3.5 w-3.5" />
        <span className="truncate font-medium">{fleet ? `Formal strategy fleet · ${fleet.length} strategies` : (run ? run.title : manifest?.title) || 'Formal research evidence'}</span>
      </div>
      <div className="research-context-item">
        <Clock3 className="h-3.5 w-3.5" />
        <span>{fleet ? 'Evidence cutoffs shown per strategy' : `Cutoff ${(run ? run.evidenceCutoff : manifest?.evidence_cutoff) || 'not declared'}`}</span>
      </div>
      <div className="research-context-item hidden lg:flex">
        <span>{(fleet ? markets.join(' · ') : run ? run.market.toUpperCase() : manifest?.scope.markets?.map((market) => market.toUpperCase()).join(' · ')) || 'No market scope'}</span>
      </div>
      <div className="ml-auto hidden items-center gap-2 sm:flex">
        <Badge variant="outline" className="context-badge">{RUNTIME_LABELS[runtimeCapabilities.mode]}</Badge>
        <Badge variant="outline" className="context-badge text-amber-700 dark:text-amber-300">
          <ShieldAlert className="mr-1 h-3 w-3" /> Research only
        </Badge>
        {!fleet && !run && bundle && (
          <Badge variant="outline" className="context-badge text-emerald-700 dark:text-emerald-300">
            <CheckCircle2 className="mr-1 h-3 w-3" /> {bundle.integrity === 'all_verified' ? 'Fully verified' : 'Core verified'}
          </Badge>
        )}
      </div>
    </div>
  );
}
