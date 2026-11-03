import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { MobileTabBar } from './MobileTabBar';

function renderTabBar(path = '/app') {
  return render(<MemoryRouter initialEntries={[path]}><MobileTabBar /></MemoryRouter>);
}
describe('MobileTabBar', () => {
  it('renders four meaningful destinations', () => {
    renderTabBar();
    expect(screen.getAllByRole('tab')).toHaveLength(4);
    for (const label of ['Today', 'Formal Strategies', 'Research Lab', 'Operating Status']) {
      expect(screen.getByRole('tab', { name: label })).toBeInTheDocument();
    }
  });
  it('selects destination and keeps touch targets tall', () => {
    const { container } = renderTabBar('/system');
    expect(screen.getByRole('tab', { name: 'Operating Status' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Today' })).toHaveAttribute('aria-selected', 'false');
    const links = container.querySelectorAll('nav a');
    expect(links.length).toBe(4);
    for (const link of Array.from(links)) expect(link.className).toMatch(/min-h-\[56px\]/);
  });
  it('navigates via the router without reload', () => {
    renderTabBar('/app');
    fireEvent.click(screen.getByRole('tab', { name: 'Research Lab' }));
    expect(screen.getByRole('tab', { name: 'Research Lab' })).toHaveAttribute('aria-selected', 'true');
  });
});
