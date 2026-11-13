import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SecurityAsOfMetrics } from './SecurityDetailPage';

function renderMetrics(asOf: string | null, cutoff: string) {
  return render(
    <dl>
      <SecurityAsOfMetrics asOf={asOf} cutoff={cutoff} />
    </dl>,
  );
}

describe('SecurityAsOfMetrics', () => {
  it('shows one labelled metric when the as-of date equals the evidence cutoff', () => {
    renderMetrics('2026-11-11', '2026-11-11');
    expect(screen.getByText('As of · evidence cutoff')).toBeInTheDocument();
    expect(screen.getByTestId('security-as-of-cutoff')).toHaveTextContent('2026-11-11');
    expect(screen.queryByText('As of')).not.toBeInTheDocument();
    expect(screen.queryByText('Evidence cutoff')).not.toBeInTheDocument();
    expect(screen.queryByTestId('security-as-of')).not.toBeInTheDocument();
  });

  it('keeps both labelled metrics when the dates differ', () => {
    renderMetrics('2026-11-10', '2026-11-12');
    expect(screen.getByText('As of')).toBeInTheDocument();
    expect(screen.getByText('Evidence cutoff')).toBeInTheDocument();
    expect(screen.getByTestId('security-as-of')).toHaveTextContent('2026-11-10');
    expect(screen.getByTestId('security-evidence-cutoff')).toHaveTextContent('2026-11-12');
    expect(screen.queryByText('As of · evidence cutoff')).not.toBeInTheDocument();
  });

  it('never borrows a cutoff when no observation date is retained', () => {
    renderMetrics(null, '2026-11-12');
    expect(screen.getByText('As of')).toBeInTheDocument();
    expect(screen.getByTestId('security-as-of')).toHaveTextContent('—');
    expect(screen.getByTestId('security-evidence-cutoff')).toHaveTextContent('2026-11-12');
    expect(screen.queryByText('As of · evidence cutoff')).not.toBeInTheDocument();
  });
});
