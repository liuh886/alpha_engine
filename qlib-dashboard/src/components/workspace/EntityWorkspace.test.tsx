import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import {
  EntityChartPanel,
  EntityDateFacts,
  EntityEvidenceSections,
  EntityRelatedEntities,
  EntityWorkspace,
  type EntityIdentity,
  type RelatedEntityLink,
} from './EntityWorkspace';

function identity(overrides: Partial<EntityIdentity> = {}): EntityIdentity {
  return {
    kind: 'model',
    name: 'QQQR v4.3',
    entityId: 'qqqi_qqq_tqqq_v4_3',
    market: 'us',
    asOf: '2026-11-14',
    evidenceCutoff: '2026-11-16',
    staleDays: 2,
    benchmark: 'QQQ',
    role: 'Formal model evidence',
    ...overrides,
  };
}

function renderWorkspace(overrides: Partial<EntityIdentity> = {}, children = <p>Body</p>) {
  return render(
    <MemoryRouter initialEntries={['/app']}>
      <EntityWorkspace
        identity={identity(overrides)}
        back={{ to: '/app', label: 'Overview' }}
        metrics={<span data-testid="metric-slot">metric</span>}
      >
        {children}
      </EntityWorkspace>
    </MemoryRouter>,
  );
}

describe('EntityWorkspace header', () => {
  it('renders one model header with kind, identity, facts, benchmark, role and a back link', () => {
    renderWorkspace();
    const workspace = screen.getByTestId('entity-workspace');
    expect(workspace).toHaveAttribute('data-entity-kind', 'model');
    expect(screen.getByTestId('entity-kind-badge')).toHaveTextContent('Model');
    expect(screen.getByTestId('entity-title')).toHaveTextContent('QQQR v4.3');
    expect(screen.getByTestId('entity-id')).toHaveTextContent('qqqi_qqq_tqqq_v4_3');
    expect(screen.getByTestId('entity-back')).toHaveAttribute('href', '/app');
    expect(screen.getByTestId('entity-facts')).toHaveTextContent('As of');
    expect(screen.getByTestId('entity-facts')).toHaveTextContent('Evidence cutoff');
    expect(screen.getByTestId('entity-facts')).toHaveTextContent('Benchmark');
    expect(screen.getByTestId('entity-facts')).toHaveTextContent('Formal model evidence');
    expect(screen.getByTestId('entity-facts')).toHaveTextContent('Research only · Not trade ready');
    expect(screen.getByTestId('metric-slot')).toBeInTheDocument();
    expect(screen.queryByTestId('entity-stale')).not.toBeInTheDocument();
  });

  it('renders the same header frame for instrument, index and reference kinds', () => {
    for (const [kind, label, name] of [
      ['instrument', 'Instrument', 'AAPL'],
      ['index', 'Index', 'QQQ'],
      ['reference', 'Reference', 'S&P 500'],
    ] as const) {
      const view = renderWorkspace({ kind, name, entityId: `us:${name}` });
      expect(view.getByTestId('entity-workspace')).toHaveAttribute('data-entity-kind', kind);
      expect(view.getByTestId('entity-kind-badge')).toHaveTextContent(label);
      expect(view.getByTestId('entity-title')).toHaveTextContent(name);
      view.unmount();
    }
  });

  it('shows the shared stale chip only beyond the governed threshold', () => {
    const stale = renderWorkspace({ staleDays: 21 });
    expect(stale.getByTestId('entity-stale')).toHaveTextContent('Stale · 21d behind cutoff');
    stale.unmount();

    const fresh = renderWorkspace({ staleDays: 14 });
    expect(fresh.queryByTestId('entity-stale')).not.toBeInTheDocument();
  });

  it('collapses equal as-of and cutoff dates into one labelled fact', () => {
    const { container } = render(
      <dl>
        <EntityDateFacts asOf="2026-11-16" cutoff="2026-11-16" />
      </dl>,
    );
    expect(screen.getByText('As of · evidence cutoff')).toBeInTheDocument();
    expect(screen.getByTestId('entity-as-of-cutoff')).toHaveTextContent('2026-11-16');
    expect(container.textContent).not.toContain('Evidence cutoff2026-11-16');
  });
});

describe('EntityChartPanel', () => {
  it('owns one heading, control row and disclosure while leaving the renderer untouched', () => {
    render(
      <EntityChartPanel
        testId="entity-chart"
        title="Performance path"
        description={<p>Renderer-specific method.</p>}
        controls={<button type="button">1Y</button>}
        dataMarkerCount={4}
      >
        <div data-testid="renderer">renderer</div>
      </EntityChartPanel>,
    );
    expect(screen.getByTestId('entity-chart')).toHaveAttribute('data-marker-count', '4');
    expect(screen.getByRole('heading', { name: 'Performance path' })).toBeInTheDocument();
    expect(screen.getByText('Renderer-specific method.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '1Y' })).toBeInTheDocument();
    expect(screen.getByTestId('renderer')).toBeInTheDocument();
    expect(screen.getByTestId('entity-chart-disclosure')).toHaveTextContent(
      'Historical research evidence, not a live signal or fill.',
    );
  });
});

describe('EntityEvidenceSections and related-entity slot', () => {
  it('composes each kind’s existing sections without adding a section', () => {
    render(
      <EntityEvidenceSections label="Instrument evidence">
        <div data-testid="price-history">price</div>
        <div data-testid="bindings">bindings</div>
      </EntityEvidenceSections>,
    );
    expect(screen.getByTestId('entity-evidence-sections')).toHaveAttribute('aria-label', 'Instrument evidence');
    expect(screen.getByTestId('price-history')).toBeInTheDocument();
    expect(screen.getByTestId('bindings')).toBeInTheDocument();
  });

  it('renders nothing until Phase 3 supplies typed related-entity links', () => {
    const { container } = render(<EntityRelatedEntities />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders a typed related-entity link when one is supplied', () => {
    const links: RelatedEntityLink[] = [{
      relation: 'holds',
      kind: 'instrument',
      market: 'us',
      entityId: 'us:AAPL',
      label: 'Apple',
      href: '#/securities/us/AAPL',
    }];
    render(<EntityRelatedEntities links={links} />);
    const section = screen.getByTestId('entity-related');
    expect(section).toHaveTextContent('Holds');
    expect(section).toHaveTextContent('Apple');
    expect(section).toHaveTextContent('Instrument · US · us:AAPL');
    expect(screen.getByRole('link', { name: 'Apple' })).toHaveAttribute('href', '#/securities/us/AAPL');
  });
});
