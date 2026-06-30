import { useState, useEffect, useRef } from 'react';
import { useGlobalStore } from '@/store/globalStore';
import { apiClient } from '@/lib/api-client';
import { useModels } from './useModels';
import { useJobs } from './useJobs';
import { useDataStatus } from './useDataStatus';

export function useAppBootstrap() {
  const [loading, setLoading] = useState(true);
  const { setApiError, setUsername, setDemoMode } = useGlobalStore();
  
  const { models, selectedModelId, setSelectedModelId, fetchModels, deleteModel } = useModels();
  const { activeJobId, isPolling, startPolling, submitAndPoll, pollActiveJobsCount } = useJobs();
  const { loadDataStatus } = useDataStatus();

  // Collect all callbacks in a ref so the bootstrap effect below can call the
  // latest version of each function without listing them as deps (which would
  // re-run the one-time bootstrap on every render cycle).
  // Pattern: write to ref on every render (useEffect with no deps array)
  // so the ref is always fresh, then read from ref inside the stable callback.
  const callbacksRef = useRef({ loadDataStatus, fetchModels, pollActiveJobsCount, setUsername, setApiError, setDemoMode });
  useEffect(() => {
    callbacksRef.current = { loadDataStatus, fetchModels, pollActiveJobsCount, setUsername, setApiError, setDemoMode };
  });

  // Bootstrap runs exactly once on mount.  All network calls are issued in
  // parallel via Promise.all so the initial load time equals the slowest
  // individual call rather than their sum.
  useEffect(() => {
    const bootstrap = async () => {
      try {
        setLoading(true);
        const {
          loadDataStatus: loadData,
          fetchModels: fetchM,
          pollActiveJobsCount: pollJobs,
          setUsername: setU,
          setApiError: setErr,
          setDemoMode: setDemo,
        } = callbacksRef.current;

        await Promise.all([
          loadData(),
          fetchM(),
          pollJobs(),
          // Fetch the authenticated user's display name — ignore failures
          // (endpoint may not exist in older backend versions).
          apiClient.get<{ username: string }>('/api/system/me').then(data => {
            if (data?.username) setU(data.username);
          }).catch(() => {}),
          // Detect demo mode from the health endpoint — ignore failures.
          apiClient.get<{ demo_mode: boolean }>('/api/system/health').then(data => {
            if (data?.demo_mode) setDemo(true);
          }).catch(() => {}),
        ]);

        setErr(null);
      } catch (err) {
        callbacksRef.current.setApiError('Cannot reach server. Check if the backend is running.');
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
