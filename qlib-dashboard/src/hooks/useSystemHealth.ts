import { useQuery } from './useQuery';
import { apiClient } from '@/lib/api-client';
import { runtimeCapabilities } from '@/lib/runtime-capabilities';

export interface SystemHealthResult {
  ok?: boolean;
  status: string;
  demo_mode?: boolean;
  timestamp?: number;
  uptime?: number;
}

export type HealthState = 'online' | 'checking' | 'unavailable' | 'degraded';

export function useSystemHealth() {
  const { data, loading, error } = useQuery<SystemHealthResult>({
    queryKey: 'system_health',
    enabled: runtimeCapabilities.backendApi,
    fetcher: (signal) => apiClient.get<SystemHealthResult>('/api/system/health', { signal, timeout: 3000 }),
  });

  let state: HealthState = runtimeCapabilities.backendApi ? 'checking' : 'unavailable';
  if (runtimeCapabilities.backendApi) {
    if (error) {
      state = 'unavailable';
    } else if (data) {
      state = data.ok === false ? 'degraded' : 'online';
    }
  }

  return { data, loading, error, state };
}
