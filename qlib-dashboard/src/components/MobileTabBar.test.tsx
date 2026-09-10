import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { MobileTabBar } from './MobileTabBar';

function renderTabBar(path = '/app') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <MobileTabBar />
    </MemoryRouter>,
  );
}

describe('MobileTabBar', () => {
  it('renders five primary tabs with accessible names', () => {
    renderTabBar();
    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(5);
    for (const label of ['Strategy Overview', 'Formal Strategies', 'Strategy Research', 'Data Lineage', 'System Trust']) {
      expect(screen.getByRole('tab', { name: label })).toBeInTheDocument();
    }
  });

  it('marks the active destination selected and keeps touch targets tall', () => {
    const { container } = renderTabBar('/research');
    const active = screen.getByRole('tab', { name: 'Strategy Research' });
    expect(active).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Strategy Overview' })).toHaveAttribute('aria-selected', 'false');
    const links = container.querySelectorAll('nav a');
    expect(links.length).toBe(5);
    for (const link of Array.from(links)) {
      expect(link.className).toMatch(/min-h-\[56px\]/);
    }
  });

  it('navigates between destinations without full reload', () => {
    renderTabBar('/app');
    fireEvent.click(screen.getByRole('tab', { name: 'Data Lineage' }));
    expect(screen.getByRole('tab', { name: 'Data Lineage' })).toHaveAttribute('aria-selected', 'true');
  });
});
