import type { useStrategyOperations } from '../hooks/useStrategyOperations';
import type { GovernedRunSummary } from './governed-run';
export interface RunWorkspaceContext {
  runs: GovernedRunSummary[];
  operations: ReturnType<typeof useStrategyOperations>;
  activeRunKey: string;
  activeRun: GovernedRunSummary | null;
  runLoadErrors: string[];
  selectRun: (run: GovernedRunSummary) => void;
}
