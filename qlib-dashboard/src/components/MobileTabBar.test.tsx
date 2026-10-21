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
  it('renders two primary tabs with accessible names', () => {
    renderTabBar();
    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(2);
    for (const label of ['Daily Research', 'Operating Status']) {
      expect(screen.getByRole('tab', { name: label })).toBeInTheDocument();
    }
  });

  it('marks the active destination selected and keeps touch targets tall', () => {
    const { container } = renderTabBar('/system');
    const active = screen.getByRole('tab', { name: 'Operating Status' });
    expect(active).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Daily Research' })).toHaveAttribute('aria-selected', 'false');
    const links = container.querySelectorAll('nav a');
    expect(links.length).toBe(2);
    for (const link of Array.from(links)) {
      expect(link.className).toMatch(/min-h-\[56px\]/);
    }
  });

  it('navigates between destinations without full reload', () => {
    renderTabBar('/app');
    fireEvent.click(screen.getByRole('tab', { name: 'Operating Status' }));
    expect(screen.getByRole('tab', { name: 'Operating Status' })).toHaveAttribute('aria-selected', 'true');
  });
});
