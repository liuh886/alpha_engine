import { useEffect, useMemo, useState } from 'react';
import type { GovernedRunSummary } from '@/lib/governed-run';
import { loadStrategyOperations, type StrategyOperationsSnapshot } from '@/lib/strategy-operations';

export function useStrategyOperations(runs: GovernedRunSummary[]) {
  const formalRuns = useMemo(() => runs.filter((run) => run.channel === 'formal'), [runs]);
  const [snapshots, setSnapshots] = useState<Map<string, StrategyOperationsSnapshot>>(new Map());
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setLoading(true);
    void loadStrategyOperations(formalRuns).then((next) => {
      if (!active) return;
      setSnapshots(next);
      setLoading(false);
    });
    return () => { active = false; };
  }, [formalRuns]);

  return { formalRuns, snapshots, loading };
}
