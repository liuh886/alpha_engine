import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { Skeleton } from './skeleton';

describe('Skeleton', () => {
  it('renders without crashing', () => {
    const { container } = render(<Skeleton />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it('applies custom className', () => {
    const { container } = render(<Skeleton className="w-20 h-4" />);
    expect(container.firstChild).toHaveClass('w-20', 'h-4');
  });

  it('has animate-pulse class', () => {
    const { container } = render(<Skeleton />);
    expect(container.firstChild).toHaveClass('animate-pulse');
  });
});
