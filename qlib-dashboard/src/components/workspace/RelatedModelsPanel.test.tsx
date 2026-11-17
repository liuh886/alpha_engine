import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import type { RelatedModelEntry } from '@/lib/related-entities';
import { RelatedModelsPanel } from './RelatedModelsPanel';

function entry(overrides: Partial<RelatedModelEntry> = {}): RelatedModelEntry {
  return {
    modelVersionId: 'model_a',
    title: 'Model A',
    events: { eventCount: 12, lastAction: 'SELL', lastEventDate: '2026-11-13' },
    holding: { status: 'held', weight: 0.75, asOf: '2026-11-13', cutoff: '2026-11-16', instrument: 'AAA' },
    ...overrides,
  };
}

function renderPanel(entries: RelatedModelEntry[]) {
  return render(
    <MemoryRouter initialEntries={['/securities/us/AAA']}>
      <RelatedModelsPanel entries={entries} />
    </MemoryRouter>,
  );
}

describe('RelatedModelsPanel', () => {
  it('renders nothing when no model traded or held the instrument', () => {
    const { container } = renderPanel([]);
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByTestId('related-models')).not.toBeInTheDocument();
  });

  it('lists multiple models with event counts, last action and date, and a model route', () => {
    renderPanel([
      entry({ modelVersionId: 'model_a', title: 'Model A' }),
      entry({
        modelVersionId: 'model_b',
        title: 'Model B',
        events: { eventCount: 1, lastAction: 'BUY', lastEventDate: '2025-08-28' },
        holding: { status: 'not_held', asOf: '2026-09-04', cutoff: '2026-11-16' },
      }),
    ]);
    const rows = screen.getAllByTestId('related-model');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAttribute('data-model-id', 'model_a');
    expect(rows[0]).toHaveTextContent('12 retained events · last Sell on 2026-11-13');
    expect(rows[1]).toHaveTextContent('1 retained event · last Buy on 2025-08-28');
    expect(screen.getByRole('link', { name: 'Model A' })).toHaveAttribute('href', '/strategies/model_a');
    expect(screen.getByRole('link', { name: 'Model B' })).toHaveAttribute('href', '/strategies/model_b');
  });

  it('shows the retained weight and the run as-of/cutoff for a held model', () => {
    renderPanel([entry({ holding: { status: 'held', weight: 0.75, asOf: '2026-11-13', cutoff: '2026-11-16', instrument: 'BYD' } })]);
    expect(screen.getByTestId('related-model-holding')).toHaveTextContent(
      'Held at last publication · 75.0% · as of 2026-11-13 · cutoff 2026-11-16',
    );
    expect(screen.getByTestId('related-model-holding')).toHaveAttribute('data-holding-status', 'held');
  });

  it('states why the latest holdings are unavailable instead of inferring them', () => {
    renderPanel([entry({ holding: { status: 'unavailable', reason: 'portfolio is not_retained' } })]);
    expect(screen.getByTestId('related-model-holding')).toHaveTextContent(
      'Latest holdings unavailable · portfolio is not_retained',
    );
    expect(screen.getByTestId('related-model-holding')).toHaveAttribute('data-holding-status', 'unavailable');
  });

  it('keeps an event-only model readable while holdings load', () => {
    renderPanel([entry({ holding: { status: 'loading' } })]);
    expect(screen.getByTestId('related-model-holding')).toHaveTextContent('Reading latest published holdings…');
  });
});
