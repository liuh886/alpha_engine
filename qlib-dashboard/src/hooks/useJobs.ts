import { useState, useEffect, useCallback, useRef } from 'react';
import { jobsApi, JobEnvelope } from '@/api/jobsApi';
import { useGlobalStore } from '@/store/globalStore';

/** Maximum number of 2-second poll ticks before a job is considered timed-out. */
const MAX_POLL_ATTEMPTS = 150; // 150 × 2 s = 5 minutes

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

  // Background counter: poll every 10 s, but pause while the tab is hidden
  // to avoid unnecessary network traffic.
  useEffect(() => {
    pollActiveJobsCount();

    let timer: ReturnType<typeof setInterval> | null = setInterval(pollActiveJobsCount, 10000);

    const handleVisibility = () => {
      if (document.hidden) {
        if (timer !== null) {
          clearInterval(timer);
          timer = null;
        }
      } else {
        // Resume immediately on tab focus
        pollActiveJobsCount();
        timer = setInterval(pollActiveJobsCount, 10000);
      }
    };

    document.addEventListener('visibilitychange', handleVisibility);

    return () => {
      if (timer !== null) clearInterval(timer);
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, [pollActiveJobsCount]);

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
      setActiveJobId(jobId);
      setIsPolling(true);
      pollAttemptsRef.current = 0;

      timerRef.current = window.setInterval(async () => {
        // Guard: stop after MAX_POLL_ATTEMPTS to prevent infinite loops
        pollAttemptsRef.current += 1;
        if (pollAttemptsRef.current > MAX_POLL_ATTEMPTS) {
          stopPolling();
          pollActiveJobsCount();
          if (onComplete) onComplete('timeout');
          return;
        }

        try {
          const resp = await jobsApi.getJob(jobId);
          const status = resp.job?.status || '';
          if (status === 'succeeded' || status === 'failed') {
            stopPolling();
            pollActiveJobsCount();
            if (onComplete) onComplete(status);
          }
        } catch {
          // Ignore transient network errors during polling
        }
      }, 2000);

      // Eagerly refresh the active-jobs count
      pollActiveJobsCount();

      return stopPolling;
    },
    [pollActiveJobsCount, stopPolling],
  );

  // Clean up the job-specific polling interval on unmount
  useEffect(() => () => stopPolling(), [stopPolling]);

  const submitAndPoll = useCallback(
    async (submitFn: () => Promise<JobEnvelope>, onComplete?: (status: string) => void) => {
      try {
        const envelope = await submitFn();
        if (envelope?.job_id) {
          startPolling(envelope.job_id, onComplete);
        }
        return envelope;
      } catch (e) {
        console.error('Job submission failed', e);
        throw e;
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
