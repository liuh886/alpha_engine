import { CheckCircle2, Clock3, Database, ShieldAlert } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { useActiveResearchBundle } from '@/hooks/useActiveResearchBundle';
import { runtimeCapabilities } from '@/lib/runtime-capabilities';

const RUNTIME_LABELS = {
  static_artifact: 'Published bundle',
  local_artifact: 'Local bundle',
  connected_research: 'Connected runtime',
} as const;

export function ResearchContextBar() {
  const bundle = useActiveResearchBundle();
  const manifest = bundle?.manifest;

  return (
    <div className="research-context-bar" role="status" aria-label="Active research context">
      <div className="research-context-item min-w-0">
        <Database className="h-3.5 w-3.5" />
        <span className="truncate font-medium">{manifest?.title || 'Loading research bundle'}</span>
      </div>
      <div className="research-context-item">
        <Clock3 className="h-3.5 w-3.5" />
        <span>Cutoff {manifest?.evidence_cutoff || 'not declared'}</span>
      </div>
      <div className="research-context-item hidden lg:flex">
        <span>{manifest?.scope.markets?.map((market) => market.toUpperCase()).join(' · ') || 'No market scope'}</span>
      </div>
      <div className="ml-auto flex items-center gap-2">
        <Badge variant="outline" className="context-badge">{RUNTIME_LABELS[runtimeCapabilities.mode]}</Badge>
        <Badge variant="outline" className="context-badge text-amber-700 dark:text-amber-300">
          <ShieldAlert className="mr-1 h-3 w-3" /> Research only
        </Badge>
        {bundle && (
          <Badge variant="outline" className="context-badge hidden sm:flex text-emerald-700 dark:text-emerald-300">
            <CheckCircle2 className="mr-1 h-3 w-3" /> {bundle.integrity === 'all_verified' ? 'Fully verified' : 'Core verified'}
          </Badge>
        )}
      </div>
    </div>
  );
}
