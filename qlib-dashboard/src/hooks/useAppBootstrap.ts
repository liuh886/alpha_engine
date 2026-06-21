import { useState, useEffect } from 'react';
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

  useEffect(() => {
    const bootstrap = async () => {
      try {
        setLoading(true);
        // Load data status and models in parallel
        await Promise.all([
          loadDataStatus(),
          fetchModels(),
          pollActiveJobsCount(),
          apiClient.get<{ username: string }>('/api/system/me').then(data => {
            if (data?.username) setUsername(data.username);
          }).catch(() => {})
        ]);
        setApiError(null);
      } catch (err) {
        setApiError("Cannot reach server. Check if the backend is running.");
      } finally {
        setLoading(false);
      }
    };
    
    bootstrap();
  }, [loadDataStatus, fetchModels, pollActiveJobsCount, setApiError, setUsername]);

  return {
    loading,
    models,
    selectedModelId,
    setSelectedModelId,
    fetchModels,
    deleteModel,
    jobs: {
      activeJobId,
      isPolling,
      startPolling,
      submitAndPoll
    }
  };
}
