import { describe, expect, it } from 'vitest';
import {
  workflowHealthLabel,
  type V42WorkflowHealthEntry,
} from './v42-workflow-health';

function entry(overrides: Partial<V42WorkflowHealthEntry> = {}): V42WorkflowHealthEntry {
  return {
    key: 'signal_alert',
    label: 'Signal decision and Telegram delivery',
    workflowFile: 'qqqi-vxn-v4-2-signal-alert.yml',
    error: null,
    run: {
      id: 1,
      name: 'QQQI v4.2 Signal Alert',
      status: 'completed',
      conclusion: 'success',
      event: 'schedule',
      html_url: 'https://github.com/liuh886/alpha_engine/actions/runs/1',
      run_started_at: '2026-08-02T01:00:00Z',
      updated_at: '2026-08-02T01:10:00Z',
      head_sha: 'a'.repeat(40),
    },
    ...overrides,
  };
}

describe('v4.2 workflow health labels', () => {
  it('reports successful completed runs as healthy', () => {
    expect(workflowHealthLabel(entry())).toEqual({ label: 'Succeeded', tone: 'healthy' });
  });

  it('keeps queued and in-progress runs distinct from failures', () => {
    expect(workflowHealthLabel(entry({ run: { ...entry().run!, status: 'queued', conclusion: null } }))).toEqual({
      label: 'Queued',
      tone: 'running',
    });
    expect(workflowHealthLabel(entry({ run: { ...entry().run!, status: 'in_progress', conclusion: null } }))).toEqual({
      label: 'Running',
      tone: 'running',
    });
  });

  it('surfaces failed and unavailable workflow evidence', () => {
    expect(workflowHealthLabel(entry({ run: { ...entry().run!, conclusion: 'failure' } }))).toEqual({
      label: 'failure',
      tone: 'attention',
    });
    expect(workflowHealthLabel(entry({ run: null, error: 'rate limited' }))).toEqual({
      label: 'Unavailable',
      tone: 'unknown',
    });
  });
});
