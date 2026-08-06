import { describe, expect, it } from 'vitest';
import {
  selectLatestOperationalRun,
  workflowHealthLabel,
  type V42WorkflowHealthEntry,
  type V42WorkflowRun,
} from './v42-workflow-health';

function run(overrides: Partial<V42WorkflowRun> = {}): V42WorkflowRun {
  return {
    id: 1,
    name: 'QQQI v4.2 Signal Alert',
    status: 'completed',
    conclusion: 'success',
    event: 'schedule',
    html_url: 'https://github.com/liuh886/alpha_engine/actions/runs/1',
    run_started_at: '2026-08-02T01:00:00Z',
    updated_at: '2026-08-02T01:10:00Z',
    head_sha: 'a'.repeat(40),
    ...overrides,
  };
}

function entry(overrides: Partial<V42WorkflowHealthEntry> = {}): V42WorkflowHealthEntry {
  return {
    key: 'signal_alert',
    label: 'Signal evaluation and delivery-receipt workflow',
    workflowFile: 'qqqi-vxn-v4-2-signal-alert.yml',
    error: null,
    run: run(),
    ...overrides,
  };
}

describe('v4.2 workflow health', () => {
  it('excludes pull-request validation runs from operating health', () => {
    const selected = selectLatestOperationalRun([
      run({ id: 3, event: 'pull_request' }),
      run({ id: 2, event: 'workflow_dispatch' }),
      run({ id: 1, event: 'schedule' }),
    ]);

    expect(selected?.id).toBe(2);
    expect(selectLatestOperationalRun([run({ event: 'pull_request' })])).toBeNull();
  });

  it('reports workflow execution success without claiming Telegram delivery', () => {
    expect(workflowHealthLabel(entry())).toEqual({ label: 'Workflow succeeded', tone: 'healthy' });
  });

  it('keeps queued and in-progress runs distinct from failures', () => {
    expect(workflowHealthLabel(entry({ run: run({ status: 'queued', conclusion: null }) }))).toEqual({
      label: 'Queued',
      tone: 'running',
    });
    expect(workflowHealthLabel(entry({ run: run({ status: 'in_progress', conclusion: null }) }))).toEqual({
      label: 'Running',
      tone: 'running',
    });
  });

  it('surfaces failed and unavailable workflow evidence', () => {
    expect(workflowHealthLabel(entry({ run: run({ conclusion: 'failure' }) }))).toEqual({
      label: 'failure',
      tone: 'attention',
    });
    expect(workflowHealthLabel(entry({ run: null, error: 'rate limited' }))).toEqual({
      label: 'Unavailable',
      tone: 'unknown',
    });
  });
});
