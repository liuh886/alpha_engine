import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { LandingPage } from './LandingPage';

describe('Alpha Engine landing page', () => {
  it('explains the strategy operating workflow and links into the console', () => {
    render(
      <MemoryRouter>
        <LandingPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { name: /run systematic strategies with the evidence still attached/i })).toBeInTheDocument();
    expect(screen.getAllByText(/start with what the strategies are doing now/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/decision first\. evidence on demand/i)).toBeInTheDocument();
    expect(screen.getByText(/every target keeps its research context/i)).toBeInTheDocument();

    const consoleLinks = screen.getAllByRole('link', { name: /open strategy console|open console|enter alpha engine/i });
    expect(consoleLinks.length).toBeGreaterThan(0);
    consoleLinks.forEach((link) => expect(link).toHaveAttribute('href', '/app'));

    expect(screen.getByRole('link', { name: /view formal strategies/i })).toHaveAttribute('href', '/strategies');
  });
});
