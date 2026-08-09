import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { AccessGate } from './AccessGate';

describe('AccessGate', () => {
  it('states that authenticated products do not require Pro', () => {
    render(<AccessGate requiredTier="authenticated" resource="Security Explorer" openAccount={vi.fn()} />);
    expect(screen.getByText(/available to every signed-in AlphaEngine account/i)).toBeInTheDocument();
    expect(screen.getByText(/AlphaEngine Pro is not required/i)).toBeInTheDocument();
  });

  it('clearly identifies a locked resource as a Pro product', () => {
    const openAccount = vi.fn();
    render(<AccessGate requiredTier="pro" resource="QQQR" openAccount={openAccount} />);
    expect(screen.getByRole('heading', { name: 'QQQR is a Pro product' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /view pro access/i }));
    expect(openAccount).toHaveBeenCalledOnce();
  });
});
