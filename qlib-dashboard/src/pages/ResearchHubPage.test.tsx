import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ResearchHubPage } from './ResearchHubPage';

vi.mock('@/components/RdiResearchStatus', () => ({
  RdiResearchStatus: () => <div data-testid="rdi-status">RDI Content</div>,
}));

vi.mock('@/components/research/StudyReviewDesk', () => ({
  StudyReviewDesk: () => <div data-testid="study-review-desk">Study Review Desk Content</div>,
}));

vi.mock('@/components/racetrack/RacetrackWorkspace', () => ({
  RacetrackWorkspace: () => <div data-testid="racetrack-workspace">Racetrack Workspace Content</div>,
}));

describe('ResearchHubPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders 3 independent research areas and defaults to Racetrack', async () => {
    render(
      <MemoryRouter initialEntries={['/research']}>
        <ResearchHubPage />
      </MemoryRouter>
    );

    expect(screen.getByRole('heading', { level: 1, name: 'Research Lab' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Racetrack · Strategy experiments/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Review Desk · Hypothesis review/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /RDI · A-share risk research/i })).toBeInTheDocument();

    expect(await screen.findByTestId('racetrack-workspace')).toBeInTheDocument();
  });

  it('switches to Review Desk when clicked', async () => {
    render(
      <MemoryRouter initialEntries={['/research']}>
        <ResearchHubPage />
      </MemoryRouter>
    );

    const reviewDeskBtn = screen.getByRole('button', { name: /Review Desk · Hypothesis review/i });
    fireEvent.click(reviewDeskBtn);

    expect(await screen.findByTestId('study-review-desk')).toBeInTheDocument();
  });

  it('switches to RDI when clicked', async () => {
    render(
      <MemoryRouter initialEntries={['/research']}>
        <ResearchHubPage />
      </MemoryRouter>
    );

    const rdiBtn = screen.getByRole('button', { name: /RDI · A-share risk research/i });
    fireEvent.click(rdiBtn);

    expect(await screen.findByTestId('rdi-status')).toBeInTheDocument();
  });
});
