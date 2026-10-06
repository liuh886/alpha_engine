import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import type { ModelData } from '@/lib/data-parser';
import type { FormalBacktestPackage } from '@/lib/formal-backtest';
import { ComparePage } from './ComparePage';

function model(id: string, benchmark: string, start: string): ModelData {
  const formal: FormalBacktestPackage = {
    schema_version: '1.0.0', record_type: 'formal_model_backtest', backtest_id: id,
    model_id: id, display_name: id, market: 'us', benchmark,
    publication_status: 'accepted_formal_baseline', generated_at: '2026-10-07T00:00:00Z',
    evidence_cutoff: '2026-10-05', trace_frequency: 'daily',
    date_range: { start, end: '2026-10-05' }, metrics: {}, portfolio_contract: { cost_bps: 20 },
    report: [], positions: [], trades: [], attribution: [], window_summary: [], evidence: {},
    evidence_completeness: { status: 'partial', missing: ['trades'] },
    interpretation_notes: [`${id}: retained drawdown gate did not pass.`], research_only: true, trade_ready: false,
  };
  return { id, name: id, market: 'us', snapshot_id: 'same-snapshot', metrics: {}, backtest: { metrics: { 'Sharpe Ratio': id === 'us-a' ? 1 : 2 }, meta: { benchmark: 'stale-projection', start: '2000-01-01' }, formalBacktest: formal } } as unknown as ModelData;
}
describe('ComparePage comparison context', () => {
  it('shows each model period and benchmark alongside metrics and retained limits', () => {
    render(<MemoryRouter><ComparePage models={[model('us-a', 'QQQ', '2024-01-02'), model('us-b', 'SPY', '2025-01-02')]} /></MemoryRouter>);
    expect(within(screen.getByRole('row', { name: /^Start/ })).getByText('2024-01-02')).toBeInTheDocument();
    const benchmark = screen.getByRole('row', { name: /^Benchmark/ });
    expect(within(benchmark).getByText('QQQ')).toBeInTheDocument();
    expect(within(benchmark).getByText('SPY')).toBeInTheDocument();
    expect(screen.getByText('us-a: retained drawdown gate did not pass.')).toBeInTheDocument();
    expect(screen.getByText('us-b: retained drawdown gate did not pass.')).toBeInTheDocument();
    expect(screen.getByText(/differ or are not declared. No winner is inferred/)).toBeInTheDocument();
    expect(screen.queryByText('stale-projection')).not.toBeInTheDocument();
    expect(screen.getByText('2.000')).not.toHaveClass('font-bold');
    const choice = screen.getByRole('button', { name: /us-a/ });
    expect(choice).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(choice);
    expect(choice).toHaveAttribute('aria-pressed', 'false');
  });
  it('keeps unavailable formal context explicit', () => {
    render(<MemoryRouter><ComparePage models={['a', 'b'].map((id) => ({ id, market: 'us', snapshot_id: 'same', backtest: { metrics: { 'Sharpe Ratio': id === 'a' ? 1 : 2 } }, metrics: {} } as unknown as ModelData))} /></MemoryRouter>);
    expect(within(screen.getByRole('row', { name: /^Start/ })).getAllByText('Contract violation')).toHaveLength(2);
    expect(screen.getByText(/No winner is inferred/)).toBeInTheDocument();
    expect(screen.getByText('2.000')).not.toHaveClass('font-bold');
  });
  it('highlights the best retained metric only with fully declared aligned identities', () => {
    render(<MemoryRouter><ComparePage models={[model('us-a', 'QQQ', '2024-01-02'), model('us-b', 'QQQ', '2024-01-02')]} /></MemoryRouter>);
    expect(screen.queryByText(/No winner is inferred/)).not.toBeInTheDocument();
    expect(screen.getByText('2.000')).toHaveClass('font-bold');
  });
});
