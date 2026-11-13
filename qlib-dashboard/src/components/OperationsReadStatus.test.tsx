import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { OperationsReadStatus } from './OperationsReadStatus';
import type { GovernedRunSummary } from '@/lib/governed-run';
import type { StrategyOperationsReadIssue } from '@/hooks/useStrategyOperations';

const runs = [
  { modelVersionId: 'qqq', market: 'us' },
  { modelVersionId: 'us', market: 'us' },
  { modelVersionId: 'byd', market: 'cn' },
  { modelVersionId: 'cn', market: 'cn' },
] as GovernedRunSummary[];

function renderStatus(overrides: { issues?: StrategyOperationsReadIssue[]; checkedAt?: string | null } = {}) {
  render(<OperationsReadStatus loading={false} issues={overrides.issues ?? []} reload={vi.fn()}
    checkedAt={overrides.checkedAt === undefined ? '2026-11-14T18:01:00Z' : overrides.checkedAt} runs={runs} />);
}

describe('OperationsReadStatus', () => {
  it('reports a completed read without claiming hidden observations were verified', () => {
    renderStatus();
    const status = screen.getByRole('status');
    expect(status).toHaveTextContent('Checked 18:01 UTC · 4 of 4 observation reads succeeded');
    expect(status).not.toHaveTextContent('observations verified');
  });

  it('keeps the affected-market issue path instead of a success count', () => {
    renderStatus({ issues: [{ modelVersionId: 'byd', message: 'Published operations could not be verified.' }] });
    const status = screen.getByRole('status');
    expect(status).toHaveTextContent('1 record needs attention');
    expect(status).toHaveTextContent('affects China');
    expect(status).not.toHaveTextContent('observation reads succeeded');
  });

  it('falls back to the undated sentence when no read time is recorded', () => {
    renderStatus({ checkedAt: null });
    expect(screen.getByRole('status')).toHaveTextContent('Published operations checked. Each record retains its own evidence cutoff.');
  });
});
