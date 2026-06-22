import { useEffect, useCallback } from 'react';
import { useGlobalStore } from '@/store/globalStore';
import { dataApi } from '@/api/dataApi';

export function normalizeQualityStatus(value: unknown): "ok" | "warning" | "error" {
  if (value === "warning" || value === "error") {
    return value;
  }
  return "ok";
}

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
        setQualityStatus(normalizeQualityStatus(statusData.quality_status));
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
