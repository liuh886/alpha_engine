import { useEffect, useCallback } from 'react';
import { useGlobalStore } from '@/store/globalStore';
import { dataApi } from '@/api/dataApi';

export function useDataStatus() {
  const { 
    setLatestCalendarDay, 
    setQualityStatus, 
    setQualityWarnings,
    setDataGeneratedAt
  } = useGlobalStore();

  const loadDataStatus = useCallback(async () => {
    try {
      const resp = await dataApi.getStatus();
      const statusData = resp.data;
      if (statusData) {
        setLatestCalendarDay(String(statusData.latest_calendar_day || ""));
        setQualityStatus(statusData.quality_status || "ok");
        setQualityWarnings(statusData.quality_warnings || []);
        if (statusData.dashboard_generated_at) {
          setDataGeneratedAt(String(statusData.dashboard_generated_at));
        }
      }
    } catch {
      // server not running or error
    }
  }, [setLatestCalendarDay, setQualityStatus, setQualityWarnings, setDataGeneratedAt]);

  useEffect(() => {
    loadDataStatus();
    const timer = setInterval(loadDataStatus, 10000);
    return () => clearInterval(timer);
  }, [loadDataStatus]);

  return { loadDataStatus };
}
