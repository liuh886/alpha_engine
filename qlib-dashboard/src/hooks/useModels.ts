import { useCallback, useEffect, useState } from 'react';
import { modelsApi } from '@/api/modelsApi';
import { parseQlibData, type ModelData } from '@/lib/data-parser';
import {
  adaptLocalRuns,
  loadFormalRuns,
  loadPreviewRuns,
  type GovernedRunSummary,
} from '@/lib/governed-run';
import { subscribeResearchBundle } from '@/lib/research-bundle';
import { useGlobalStore } from '@/store/globalStore';

const CHANNEL_ORDER: Record<GovernedRunSummary['channel'], number> = {
  formal: 0,
  preview: 1,
  local: 2,
};

function sortRuns(runs: GovernedRunSummary[]): GovernedRunSummary[] {
  return [...runs].sort((left, right) => (
    CHANNEL_ORDER[left.channel] - CHANNEL_ORDER[right.channel]
    || right.evidenceCutoff.localeCompare(left.evidenceCutoff)
    || left.title.localeCompare(right.title)
  ));
}

export function useModels() {
  const [models, setModels] = useState<ModelData[]>([]);
  const [runs, setRuns] = useState<GovernedRunSummary[]>([]);
  const [runLoadErrors, setRunLoadErrors] = useState<string[]>([]);
  const selectedModelId = useGlobalStore((state) => state.selectedModelId);
  const setSelectedModelId = useGlobalStore((state) => state.setSelectedModelId);
  const activeRunKey = useGlobalStore((state) => state.activeRunKey);
  const setActiveRunKey = useGlobalStore((state) => state.setActiveRunKey);

  const selectRun = useCallback((run: GovernedRunSummary) => {
    setActiveRunKey(run.key);
    const modelId = run.modelData?.id || run.modelVersionId;
    if (modelId) setSelectedModelId(modelId);
  }, [setActiveRunKey, setSelectedModelId]);

  const fetchModels = useCallback(async (opts?: { selectLatest?: boolean }) => {
    try {
      const json = await modelsApi.getDashboardDb();
      const repositoryModels = parseQlibData(json);
      const [formal, preview] = await Promise.all([
        loadFormalRuns(),
        loadPreviewRuns(),
      ]);
      if (formal.errors.length > 0) {
        throw new Error(`Formal Bundle v2 validation failed: ${formal.errors.join(' | ')}`);
      }
      if (formal.runs.length === 0) {
        throw new Error('The verified Formal Bundle v2 catalog contains no accepted baselines.');
      }
      const formalVersions = new Set(formal.runs.map((run) => run.modelVersionId));
      if (formalVersions.size !== formal.runs.length) {
        throw new Error('The verified Formal Bundle v2 catalog contains duplicate model versions.');
      }
      const byId = new Map(repositoryModels.map((model) => [model.id, model]));
      const formalRuns = formal.runs.map((run) => ({
        ...run,
        modelData: byId.get(run.modelVersionId) ?? null,
      }));
      const localModels = repositoryModels.filter((model) => !formalVersions.has(model.id));
      const governedRuns = sortRuns([
        ...formalRuns,
        ...preview.runs,
        ...adaptLocalRuns(localModels),
      ]);
      const generatedDates = governedRuns.map((record) => record.generatedAt).filter(Boolean).sort();
      useGlobalStore.getState().setDataGeneratedAt(
        generatedDates.length > 0 ? generatedDates[generatedDates.length - 1] : String(json.generated_at || ''),
      );
      setModels(repositoryModels);
      setRuns(governedRuns);
      setRunLoadErrors(preview.errors);

      if (governedRuns.length > 0) {
        const currentKey = useGlobalStore.getState().activeRunKey;
        const current = governedRuns.find((run) => run.key === currentKey);
        const selected = opts?.selectLatest || !current ? governedRuns[0] : current;
        selectRun(selected);
      } else {
        setActiveRunKey('');
        setSelectedModelId('');
      }
      return repositoryModels;
    } catch (error) {
      console.error('Failed to load governed model runs', error);
      setModels([]);
      setRuns([]);
      setRunLoadErrors([error instanceof Error ? error.message : String(error)]);
      setActiveRunKey('');
      setSelectedModelId('');
      return null;
    }
  }, [selectRun, setActiveRunKey, setSelectedModelId]);

  useEffect(
    () => subscribeResearchBundle(() => {
      void fetchModels({ selectLatest: true });
    }),
    [fetchModels],
  );

  return {
    models,
    runs,
    runLoadErrors,
    selectedModelId,
    setSelectedModelId,
    activeRunKey,
    setActiveRunKey,
    selectRun,
    fetchModels,
  };
}
