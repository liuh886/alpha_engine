import type { ModelData } from './data-parser';
import type { GovernedRunSummary } from './governed-run';

export interface RunWorkspaceContext {
  models: ModelData[];
  selectedModelId: string;
  runs: GovernedRunSummary[];
  activeRunKey: string;
  activeRun: GovernedRunSummary | null;
  runLoadErrors: string[];
  selectRun: (run: GovernedRunSummary) => void;
}
