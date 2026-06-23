import { useState, useEffect, useRef } from 'react';
import { useGlobalStore } from '@/store/globalStore';
import { apiClient } from '@/lib/api-client';
import { useModels } from './useModels';
import { useJobs } from './useJobs';
import { useDataStatus } from './useDataStatus';

export function useAppBootstrap() {
  const [loading, setLoading] = useState(true);
  const { setApiError, setUsername } = useGlobalStore();
  
  const { models, selectedModelId, setSelectedModelId, fetchModels, deleteModel } = useModels();
  const { activeJobId, isPolling, startPolling, submitAndPoll, pollActiveJobsCount } = useJobs();
  const { loadDataStatus } = useDataStatus();

  // Keep stable references to callbacks so they don't trigger re-renders or get stale
  const callbacksRef = useRef({ loadDataStatus, fetchModels, pollActiveJobsCount, setUsername, setApiError });
  useEffect(() => {
    callbacksRef.current = { loadDataStatus, fetchModels, pollActiveJobsCount, setUsername, setApiError };
  });

  useEffect(() => {
    const bootstrap = async () => {
      try {
        setLoading(true);
        const { loadDataStatus: loadData, fetchModels: fetchM, pollActiveJobsCount: pollJobs, setUsername: setU, setApiError: setErr } = callbacksRef.current;
        // Load data status and models in parallel
        await Promise.all([
          loadData(),
          fetchM(),
          pollJobs(),
          apiClient.get<{ username: string }>('/api/system/me').then(data => {
            if (data?.username) setU(data.username);
          }).catch(() => {})
        ]);
        setErr(null);
      } catch (err) {
        callbacksRef.current.setApiError("Cannot reach server. Check if the backend is running.");
      } finally {
        setLoading(false);
      }
    };
    
    bootstrap();
  }, []);

  return {
    loading,
    models,
    selectedModelId,
    setSelectedModelId,
    fetchModels,
    loadDataStatus,
    deleteModel,
    jobs: {
      activeJobId,
      isPolling,
      startPolling,
      submitAndPoll
    }
  };
}
