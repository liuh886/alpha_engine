import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ResearchContextBar } from './ResearchContextBar';
import type { GovernedRunSummary } from '@/lib/governed-run';

vi.mock('@/hooks/useActiveResearchBundle', () => ({
  useActiveResearchBundle: () => ({
    integrity: 'all_verified',
    manifest: { title: 'Older overview', evidence_cutoff: '2026-07-31', scope: { markets: ['cn', 'us'] } },
  }),
}));

describe('ResearchContextBar evidence identity', () => {
  it('uses the selected run cutoff and market rather than the unrelated overview', () => {
    render(<ResearchContextBar run={{ title: 'US frozen baseline', evidenceCutoff: '2026-10-07', market: 'us' } as GovernedRunSummary} />);
    expect(screen.getByText('US frozen baseline')).toBeInTheDocument();
    expect(screen.getByText('Cutoff 2026-10-07')).toBeInTheDocument();
    expect(screen.getByText('US')).toBeInTheDocument();
    expect(screen.queryByText('Fully verified')).not.toBeInTheDocument();
    expect(screen.queryByText(/2026-07-31/)).not.toBeInTheDocument();
  });

  it('does not substitute an overview cutoff for an undeclared run cutoff', () => {
    render(<ResearchContextBar run={{ title: 'Undated run', evidenceCutoff: '', market: 'cn' } as GovernedRunSummary} />);
    expect(screen.getByText('Cutoff not declared')).toBeInTheDocument();
    expect(screen.queryByText(/2026-07-31/)).not.toBeInTheDocument();
  });

  it('shows the overview and its own integrity when no run is selected', () => {
    render(<ResearchContextBar />);
    expect(screen.getByText('Older overview')).toBeInTheDocument();
    expect(screen.getByText('Cutoff 2026-07-31')).toBeInTheDocument();
    expect(screen.getByText('Fully verified')).toBeInTheDocument();
  });
});
