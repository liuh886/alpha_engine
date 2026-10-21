import { useCallback, useState } from 'react';
import { loadFormalRuns, type GovernedRunSummary } from '@/lib/governed-run';
import { useGlobalStore } from '@/store/globalStore';

/** The daily console reads only the accepted formal catalog. */
export function useModels() {
  const [runs, setRuns] = useState<GovernedRunSummary[]>([]);
  const [runLoadErrors, setRunLoadErrors] = useState<string[]>([]);
  const activeRunKey = useGlobalStore(state => state.activeRunKey);
  const setActiveRunKey = useGlobalStore(state => state.setActiveRunKey);
  const selectRun = useCallback((run: GovernedRunSummary) => {
    setActiveRunKey(run.key);
    useGlobalStore.getState().setSelectedModelId(run.modelVersionId);
  }, [setActiveRunKey]);
  const fetchModels = useCallback(async () => {
    try {
      const formal = await loadFormalRuns();
      if (formal.errors.length || !formal.runs.length) {
        throw new Error(formal.errors.join(' | ') || 'Formal catalog contains no accepted strategy evidence.');
      }
      setRuns(formal.runs);
      setRunLoadErrors([]);
      const selected = formal.runs.find(run => run.key === useGlobalStore.getState().activeRunKey)
        ?? formal.runs.find(run => run.modelVersionId === useGlobalStore.getState().selectedModelId) ?? formal.runs[0];
      selectRun(selected);
      return formal.runs;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setRuns([]);
      setRunLoadErrors([message]);
      setActiveRunKey('');
      return null;
    }
  }, [selectRun, setActiveRunKey]);
  return { runs, runLoadErrors, activeRunKey, selectRun, fetchModels };
}
