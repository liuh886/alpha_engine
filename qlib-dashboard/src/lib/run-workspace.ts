import type { GovernedRunSummary } from './governed-run';
export interface RunWorkspaceContext {
  runs: GovernedRunSummary[];
  activeRunKey: string;
  activeRun: GovernedRunSummary | null;
  runLoadErrors: string[];
  selectRun: (run: GovernedRunSummary) => void;
}
