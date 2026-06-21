import { useState, useEffect, useCallback, useRef } from 'react';
import { jobsApi, JobEnvelope } from '@/api/jobsApi';
import { useGlobalStore } from '@/store/globalStore';

export function useJobs() {
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const { setActiveJobsCount } = useGlobalStore();

  const pollActiveJobsCount = useCallback(async () => {
    try {
      const resp = await jobsApi.getActiveJobs();
      setActiveJobsCount(resp.jobs?.length || 0);
    } catch {
      setActiveJobsCount(0);
    }
  }, [setActiveJobsCount]);

  useEffect(() => {
    pollActiveJobsCount();
    const timer = setInterval(pollActiveJobsCount, 10000);
    return () => clearInterval(timer);
  }, [pollActiveJobsCount]);

  const timerRef = useRef<number | null>(null);

  const stopPolling = useCallback(() => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    setIsPolling(false);
    setActiveJobId(null);
  }, []);

  const startPolling = useCallback((jobId: string, onComplete?: (status: string) => void) => {
    stopPolling();
    setActiveJobId(jobId);
    setIsPolling(true);
    
    timerRef.current = window.setInterval(async () => {
      try {
        const resp = await jobsApi.getJob(jobId);
        const status = resp.job?.status || "";
        if (status === "succeeded" || status === "failed") {
          stopPolling();
          pollActiveJobsCount();
          if (onComplete) onComplete(status);
        }
      } catch (e) {
        // ignore network error during polling
      }
    }, 2000);

    // Initial check
    pollActiveJobsCount();

    return stopPolling;
  }, [pollActiveJobsCount, stopPolling]);

  useEffect(() => stopPolling, [stopPolling]);
  const submitAndPoll = useCallback(async (
    submitFn: () => Promise<JobEnvelope>, 
    onComplete?: (status: string) => void
  ) => {
    try {
      const envelope = await submitFn();
      if (envelope?.job_id) {
        startPolling(envelope.job_id, onComplete);
      }
      return envelope;
    } catch (e) {
      console.error("Job submission failed", e);
      throw e;
    }
  }, [startPolling]);

  return {
    activeJobId,
    isPolling,
    startPolling,
    submitAndPoll,
    pollActiveJobsCount
  };
}
