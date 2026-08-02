const REPOSITORY = 'liuh886/alpha_engine';
const API_ROOT = `https://api.github.com/repos/${REPOSITORY}`;

export type V42WorkflowKey = 'signal_alert' | 'prospective_ledger';

export interface V42WorkflowRun {
  id: number;
  name: string;
  status: 'queued' | 'in_progress' | 'completed' | string;
  conclusion: string | null;
  event: string;
  html_url: string;
  run_started_at: string | null;
  updated_at: string;
  head_sha: string;
}

export interface V42WorkflowHealthEntry {
  key: V42WorkflowKey;
  label: string;
  workflowFile: string;
  run: V42WorkflowRun | null;
  error: string | null;
}

interface WorkflowRunsResponse {
  total_count: number;
  workflow_runs: V42WorkflowRun[];
}

const WORKFLOWS: Array<{
  key: V42WorkflowKey;
  label: string;
  workflowFile: string;
}> = [
  {
    key: 'signal_alert',
    label: 'Signal decision and Telegram delivery',
    workflowFile: 'qqqi-vxn-v4-2-signal-alert.yml',
  },
  {
    key: 'prospective_ledger',
    label: 'Prospective evidence ledger',
    workflowFile: 'qqqi-v4-2-prospective-evidence-ledger.yml',
  },
];

export function selectLatestOperationalRun(runs: V42WorkflowRun[]): V42WorkflowRun | null {
  return runs.find((run) => run.event !== 'pull_request') ?? null;
}

async function fetchLatestRun(workflowFile: string): Promise<V42WorkflowRun | null> {
  const response = await fetch(
    `${API_ROOT}/actions/workflows/${encodeURIComponent(workflowFile)}/runs?per_page=20`,
    {
      headers: {
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
      },
    },
  );

  if (!response.ok) {
    const rateRemaining = response.headers.get('x-ratelimit-remaining');
    const suffix = rateRemaining === '0' ? ' Public API rate limit exhausted.' : '';
    throw new Error(`GitHub workflow request failed (${response.status}).${suffix}`);
  }

  const payload = await response.json() as WorkflowRunsResponse;
  return selectLatestOperationalRun(payload.workflow_runs);
}

export async function fetchV42WorkflowHealth(): Promise<V42WorkflowHealthEntry[]> {
  return Promise.all(WORKFLOWS.map(async (workflow) => {
    try {
      return {
        ...workflow,
        run: await fetchLatestRun(workflow.workflowFile),
        error: null,
      };
    } catch (error) {
      return {
        ...workflow,
        run: null,
        error: error instanceof Error ? error.message : 'Workflow status unavailable.',
      };
    }
  }));
}

export function workflowHealthLabel(entry: V42WorkflowHealthEntry): {
  label: string;
  tone: 'healthy' | 'running' | 'attention' | 'unknown';
} {
  if (entry.error || !entry.run) return { label: 'Unavailable', tone: 'unknown' };
  if (entry.run.status === 'queued') return { label: 'Queued', tone: 'running' };
  if (entry.run.status === 'in_progress') return { label: 'Running', tone: 'running' };
  if (entry.run.conclusion === 'success') return { label: 'Succeeded', tone: 'healthy' };
  if (entry.run.conclusion) return { label: entry.run.conclusion.replace(/_/g, ' '), tone: 'attention' };
  return { label: entry.run.status, tone: 'unknown' };
}
