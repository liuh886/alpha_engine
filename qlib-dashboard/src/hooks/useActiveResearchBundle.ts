import { useSyncExternalStore } from 'react';
import {
  getActiveResearchBundle,
  subscribeResearchBundle,
  type OpenedResearchBundle,
} from '@/lib/research-bundle';

export function useActiveResearchBundle(): OpenedResearchBundle | null {
  return useSyncExternalStore(
    subscribeResearchBundle,
    getActiveResearchBundle,
    getActiveResearchBundle,
  );
}
