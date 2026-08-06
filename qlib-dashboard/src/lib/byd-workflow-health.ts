const REPOSITORY = 'liuh886/alpha_engine';
const API_ROOT = `https://api.github.com/repos/${REPOSITORY}`;

export type BydWorkflowKey =
  | 'shadow'
  | 'paired'
  | 'trend_expansion'
  | 'signal_alert';

export interface BydWorkflowRun {
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

export interface BydWorkflowHealthEntry {
  key: BydWorkflowKey;
  label: string;
  workflowFile: string;
  run: BydWorkflowRun | null;
  error: string | null;
}

interface WorkflowRunsResponse {
  total_count: number;
  workflow_runs: BydWorkflowRun[];
}

const WORKFLOWS: Array<{
  key: BydWorkflowKey;
  label: string;
  workflowFile: string;
}> = [
  {
    key: 'shadow',
    label: 'BYD shadow observations',
    workflowFile: 'byd-prospective-shadow.yml',
  },
  {
    key: 'paired',
    label: 'BYD/515180 paired sleeve',
    workflowFile: 'byd-515180-prospective.yml',
  },
  {
    key: 'trend_expansion',
    label: 'BYD v1.2 trend expansion',
    workflowFile: 'byd-v1-2-trend-expansion-prospective.yml',
  },
  {
    key: 'signal_alert',
    label: 'BYD signal decision and Telegram delivery',
    workflowFile: 'byd-daily-signal-alert.yml',
  },
];

export function selectLatestOperationalRun(
  runs: BydWorkflowRun[],
): BydWorkflowRun | null {
  return runs.find((run) => run.event !== 'pull_request') ?? null;
}

async function fetchLatestRun(
  workflowFile: string,
): Promise<BydWorkflowRun | null> {
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
    const suffix =
      rateRemaining === '0' ? ' Public API rate limit exhausted.' : '';
    throw new Error(
      `GitHub BYD workflow request failed (${response.status}).${suffix}`,
    );
  }

  const payload = (await response.json()) as WorkflowRunsResponse;
  return selectLatestOperationalRun(payload.workflow_runs);
}

export async function fetchBydWorkflowHealth(): Promise<
  BydWorkflowHealthEntry[]
> {
  return Promise.all(
    WORKFLOWS.map(async (workflow) => {
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
          error:
            error instanceof Error
              ? error.message
              : 'Workflow status unavailable.',
        };
      }
    }),
  );
}

export function workflowHealthLabel(entry: BydWorkflowHealthEntry): {
  label: string;
  tone: 'healthy' | 'running' | 'attention' | 'unknown';
} {
  if (entry.error || !entry.run)
    return { label: 'Unavailable', tone: 'unknown' };
  if (entry.run.status === 'queued') return { label: 'Queued', tone: 'running' };
  if (entry.run.status === 'in_progress')
    return { label: 'Running', tone: 'running' };
  if (entry.run.conclusion === 'success')
    return { label: 'Succeeded', tone: 'healthy' };
  if (entry.run.conclusion)
    return {
      label: entry.run.conclusion.replace(/_/g, ' '),
      tone: 'attention',
    };
  return { label: entry.run.status, tone: 'unknown' };
}
