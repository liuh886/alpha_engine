import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ResearchContextBar } from './ResearchContextBar';
import type { GovernedRunSummary } from '@/lib/governed-run';
describe('formal context', () => {
  it('does not present an unread catalog as zero strategies or an undeclared cutoff', () => {
    render(<ResearchContextBar fleet={[]} loading />);
    expect(screen.getByText('Reading formal strategy catalog…')).toBeInTheDocument();
    expect(screen.getByText('Reading evidence cutoffs…')).toBeInTheDocument();
    expect(screen.queryByText(/0 strategies|Cutoff not declared/)).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true');
  });
  it('distinguishes a failed catalog read from an empty verified fleet', () => {
    render(<ResearchContextBar fleet={[]} unavailable />);
    expect(screen.getByText('Formal strategy catalog unavailable')).toBeInTheDocument();
    expect(screen.queryByText(/0 strategies/)).not.toBeInTheDocument();
  });
  it('keeps fleet cutoffs separate', () => {
    render(<ResearchContextBar fleet={[{ market: 'us' }, { market: 'cn' }] as GovernedRunSummary[]} />);
    expect(screen.getByText('Formal strategy fleet · 2 strategies')).toBeInTheDocument();
    expect(screen.getByText('Evidence cutoffs shown per strategy')).toBeInTheDocument();
  });
  it('uses the selected run identity', () => {
    render(<ResearchContextBar run={{ title: 'US frozen baseline', evidenceCutoff: '2026-10-07', market: 'us' } as GovernedRunSummary} />);
    expect(screen.getByText('US frozen baseline')).toBeInTheDocument();
    expect(screen.getByText('Cutoff 2026-10-07')).toBeInTheDocument();
    expect(screen.getByText('US')).toBeInTheDocument();
  });
  it('does not borrow an undeclared cutoff from another bundle', () => {
    render(<ResearchContextBar />);
    expect(screen.getByText('Cutoff not declared')).toBeInTheDocument();
    expect(screen.queryByText('Fully verified')).not.toBeInTheDocument();
  });
});
