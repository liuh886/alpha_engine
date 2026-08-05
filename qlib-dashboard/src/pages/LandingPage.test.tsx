import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { LandingPage } from './LandingPage';

describe('Alpha Engine landing page', () => {
  it('explains the governed research workflow and links into the studio', () => {
    render(
      <MemoryRouter>
        <LandingPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { name: /turn systematic research into decisions you can inspect/i })).toBeInTheDocument();
    expect(screen.getByText(/choose the run before reading the result/i)).toBeInTheDocument();
    expect(screen.getByText(/performance is only useful when its source is visible/i)).toBeInTheDocument();
    expect(screen.getByText(/every conclusion keeps its evidence attached/i)).toBeInTheDocument();

    const studioLinks = screen.getAllByRole('link', { name: /open research studio|open studio|enter alpha engine/i });
    expect(studioLinks.length).toBeGreaterThan(0);
    studioLinks.forEach((link) => expect(link).toHaveAttribute('href', '/app'));

    expect(screen.getByRole('link', { name: /view formal backtests/i })).toHaveAttribute('href', '/backtests');
  });
});
