import type { ReactNode } from 'react';
import { createContext, useContext, useEffect } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@radix-ui/react-popover', () => {
  const PopoverContext = createContext<{ open: boolean; setOpen?: (open: boolean) => void }>({ open: false });
  return {
    Root: ({ children, open, onOpenChange }: {
      children: ReactNode;
      open?: boolean;
      onOpenChange?: (open: boolean) => void;
    }) => (
      <PopoverContext.Provider value={{ open: Boolean(open), setOpen: onOpenChange }}>
        {children}
      </PopoverContext.Provider>
    ),
    Trigger: ({ children }: { children: ReactNode }) => {
      const context = useContext(PopoverContext);
      return (
        <span onClick={() => context.setOpen?.(!context.open)}>{children}</span>
      );
    },
    Portal: ({ children }: { children: ReactNode }) => <>{children}</>,
    Content: ({ children, onOpenAutoFocus }: {
      children: ReactNode;
      onOpenAutoFocus?: (event: Event) => void;
    }) => {
      const { open } = useContext(PopoverContext);
      useEffect(() => {
        if (open) onOpenAutoFocus?.(new Event('focus'));
      }, [open, onOpenAutoFocus]);
      return open ? <div>{children}</div> : null;
    },
  };
});

import { IndicatorControl, type IndicatorControlOption } from './IndicatorControl';

const options: IndicatorControlOption[] = [
  {
    id: 'instrument_sma_20',
    label: 'SMA 20',
    scope: 'instrument',
    group: 'price',
    description: '20-session SMA',
    available: true,
  },
  {
    id: 'instrument_rsi_14',
    label: 'RSI 14',
    scope: 'instrument',
    group: 'indicator',
    description: '14-session RSI',
    available: true,
  },
  {
    id: 'market_us_vix',
    label: 'VIX',
    scope: 'market',
    group: 'indicator',
    description: 'US VIX',
    available: false,
    reason: 'This instrument has no published price history in this market.',
  },
];

describe('IndicatorControl', () => {
  it('opens to grouped keyboard-operable toggles with aria-pressed state', () => {
    render(<IndicatorControl options={options} selected={['instrument_sma_20']} onToggle={vi.fn()} marketLabel="US" />);
    expect(screen.getByRole('button', { name: 'US indicators: 1 active' })).toBeInTheDocument();
    const trigger = screen.getByRole('button', { name: 'US indicators: 1 active' });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');

    expect(screen.getAllByText('Price pane').length).toBeGreaterThan(0);
    expect(screen.getByText('Market')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /SMA 20/ })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /RSI 14/ })).toHaveAttribute('aria-pressed', 'false');
  });

  it('toggles an indicator through its option button', () => {
    const onToggle = vi.fn();
    render(<IndicatorControl options={options} selected={[]} onToggle={onToggle} marketLabel="US" />);
    fireEvent.click(screen.getByRole('button', { name: 'US indicators: none active' }));
    fireEvent.click(screen.getByRole('button', { name: /RSI 14/ }));
    expect(onToggle).toHaveBeenCalledWith('instrument_rsi_14');
  });

  it('keeps an unavailable market indicator selectable and states the reason', () => {
    const onToggle = vi.fn();
    render(<IndicatorControl options={options} selected={[]} onToggle={onToggle} marketLabel="US" />);
    fireEvent.click(screen.getByRole('button', { name: 'US indicators: none active' }));
    const vix = screen.getByRole('button', { name: /VIX/ });
    expect(vix).toHaveTextContent('Unavailable');
    expect(vix).toHaveTextContent('no published price history');
    fireEvent.click(vix);
    expect(onToggle).toHaveBeenCalledWith('market_us_vix');
  });

  it('offers no market group when the chart has no market indicators', () => {
    const cn = options.filter(option => option.scope !== 'market');
    render(<IndicatorControl options={cn} selected={[]} onToggle={vi.fn()} marketLabel="CN" />);
    fireEvent.click(screen.getByRole('button', { name: 'CN indicators: none active' }));
    expect(screen.queryByText('Market')).not.toBeInTheDocument();
  });
});
