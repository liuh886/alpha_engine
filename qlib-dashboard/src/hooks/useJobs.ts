import { useState, useEffect, useCallback, useRef } from 'react';
import { jobsApi, JobEnvelope } from '@/api/jobsApi';
import { useGlobalStore } from '@/store/globalStore';
import { runtimeCapabilities } from '@/lib/runtime-capabilities';

const MAX_POLL_ATTEMPTS = 150;

export function useJobs() {
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const { setActiveJobsCount } = useGlobalStore();

  const pollActiveJobsCount = useCallback(async () => {
    if (!runtimeCapabilities.jobs) {
      setActiveJobsCount(0);
      return;
    }
    try {
      const resp = await jobsApi.getActiveJobs();
      setActiveJobsCount(resp.jobs?.length || 0);
    } catch {
      setActiveJobsCount(0);
    }
  }, [setActiveJobsCount]);

  useEffect(() => {
    if (!runtimeCapabilities.jobs) {
      setActiveJobsCount(0);
      return undefined;
    }

    void pollActiveJobsCount();
    let timer: ReturnType<typeof setInterval> | null = setInterval(pollActiveJobsCount, 10000);

    const handleVisibility = () => {
      if (document.hidden) {
        if (timer !== null) {
          clearInterval(timer);
          timer = null;
        }
      } else {
        void pollActiveJobsCount();
        timer = setInterval(pollActiveJobsCount, 10000);
      }
    };

    document.addEventListener('visibilitychange', handleVisibility);
    return () => {
      if (timer !== null) clearInterval(timer);
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, [pollActiveJobsCount, setActiveJobsCount]);

  const timerRef = useRef<number | null>(null);
  const pollAttemptsRef = useRef(0);

  const stopPolling = useCallback(() => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    pollAttemptsRef.current = 0;
    setIsPolling(false);
    setActiveJobId(null);
  }, []);

  const startPolling = useCallback(
    (jobId: string, onComplete?: (status: string) => void) => {
      stopPolling();
      if (!runtimeCapabilities.jobs) {
        if (onComplete) onComplete('unsupported');
        return stopPolling;
      }

      setActiveJobId(jobId);
      setIsPolling(true);
      pollAttemptsRef.current = 0;

      timerRef.current = window.setInterval(async () => {
        pollAttemptsRef.current += 1;
        if (pollAttemptsRef.current > MAX_POLL_ATTEMPTS) {
          stopPolling();
          void pollActiveJobsCount();
          if (onComplete) onComplete('timeout');
          return;
        }

        try {
          const resp = await jobsApi.getJob(jobId);
          const status = resp.job?.status || '';
          if (status === 'succeeded' || status === 'failed') {
            stopPolling();
            void pollActiveJobsCount();
            if (onComplete) onComplete(status);
          }
        } catch {
          // Ignore transient connected-runtime polling errors.
        }
      }, 2000);

      void pollActiveJobsCount();
      return stopPolling;
    },
    [pollActiveJobsCount, stopPolling],
  );

  useEffect(() => () => stopPolling(), [stopPolling]);

  const submitAndPoll = useCallback(
    async (submitFn: () => Promise<JobEnvelope>, onComplete?: (status: string) => void) => {
      if (!runtimeCapabilities.jobs) {
        throw new Error('Job submission is unavailable in this read-only runtime.');
      }
      try {
        const envelope = await submitFn();
        if (envelope?.job_id) startPolling(envelope.job_id, onComplete);
        return envelope;
      } catch (error) {
        console.error('Job submission failed', error);
        throw error;
      }
    },
    [startPolling],
  );

  return {
    activeJobId,
    isPolling,
    startPolling,
    submitAndPoll,
    pollActiveJobsCount,
  };
}
