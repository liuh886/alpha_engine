import type { ReactNode } from 'react';
import { createContext, useContext, useEffect } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { BaselineOption } from '@/lib/baseline';
import { BaselineControl } from './BaselineControl';

// Radix positioning/focus scopes are costly under jsdom and are not the
// behaviour under test; this mock preserves the controlled open state, the
// trigger click, the portal and the open-autofocus hook the component uses.
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
        <span
          onClick={event => {
            const button = (event.target as HTMLElement).closest('button');
            if (button?.disabled) return;
            context.setOpen?.(!context.open);
          }}
        >
          {children}
        </span>
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

const options: BaselineOption[] = [
  {
    key: 'declared:bench_byd_v1_2',
    label: 'BYD v1.2',
    kind: 'declared',
    market: 'us',
    source: 'formal_report',
    field: 'bench_byd_v1_2',
    available: true,
  },
  {
    key: 'market:QQQ',
    label: 'QQQ',
    kind: 'market',
    market: 'us',
    source: 'market_bars',
    available: true,
  },
  {
    key: 'declared:unresolved',
    label: 'Momentum sleeve',
    kind: 'declared',
    market: 'us',
    source: 'formal_report',
    available: false,
    reason: 'Benchmark wealth series not retained',
  },
  { key: 'none', label: 'No baseline', kind: 'none', market: 'us', available: true },
];

function renderControl(overrides: Partial<Parameters<typeof BaselineControl>[0]> = {}) {
  const onChange = vi.fn();
  render(
    <BaselineControl
      options={options}
      value="declared"
      onChange={onChange}
      marketLabel="US"
      {...overrides}
    />,
  );
  return { onChange };
}

describe('BaselineControl', () => {
  it('names the selected baseline and opens the listbox', () => {
    renderControl();
    const trigger = screen.getByRole('button', { name: 'US baseline: BYD v1.2' });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('listbox', { name: 'US baseline options' })).toBeInTheDocument();
    expect(screen.getAllByRole('option')).toHaveLength(4);
  });

  it('shows the data source and the selection state without relying on color', () => {
    renderControl();
    fireEvent.click(screen.getByRole('button', { name: 'US baseline: BYD v1.2' }));
    const [declared, market] = screen.getAllByRole('option');
    expect(declared).toHaveAttribute('aria-selected', 'true');
    expect(declared).toHaveTextContent('Formal report');
    expect(declared).toHaveTextContent('Selected');
    expect(market).toHaveAttribute('aria-selected', 'false');
    expect(market).toHaveTextContent('Market bars');
  });

  it('reports a selection by kind and closes the listbox', () => {
    const { onChange } = renderControl();
    fireEvent.click(screen.getByRole('button', { name: 'US baseline: BYD v1.2' }));
    fireEvent.click(screen.getByRole('option', { name: /QQQ/ }));
    expect(onChange).toHaveBeenCalledWith('market');
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('keeps an unavailable option visible with a reason and does not select it', () => {
    const { onChange } = renderControl();
    fireEvent.click(screen.getByRole('button', { name: 'US baseline: BYD v1.2' }));
    const unavailable = screen.getByRole('option', { name: /Momentum sleeve/ });
    expect(unavailable).toHaveAttribute('aria-disabled', 'true');
    expect(unavailable).toHaveTextContent('Unavailable: Benchmark wealth series not retained');
    fireEvent.click(unavailable);
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole('listbox')).toBeInTheDocument();
  });

  it('marks the trigger when the selected baseline has no retained series', () => {
    renderControl({ value: 'declared', options: [options[2], options[3]] });
    expect(screen.getByRole('button', { name: 'US baseline: Momentum sleeve (unavailable)' })).toBeInTheDocument();
  });

  it('moves focus with arrow, Home and End keys', () => {
    renderControl();
    fireEvent.click(screen.getByRole('button', { name: 'US baseline: BYD v1.2' }));
    const listbox = screen.getByRole('listbox');
    const rendered = screen.getAllByRole('option');
    expect(document.activeElement).toBe(rendered[0]);

    fireEvent.keyDown(listbox, { key: 'ArrowDown' });
    expect(document.activeElement).toBe(rendered[1]);
    fireEvent.keyDown(listbox, { key: 'End' });
    expect(document.activeElement).toBe(rendered[3]);
    fireEvent.keyDown(listbox, { key: 'ArrowDown' });
    expect(document.activeElement).toBe(rendered[0]);
    fireEvent.keyDown(listbox, { key: 'ArrowUp' });
    expect(document.activeElement).toBe(rendered[3]);
    fireEvent.keyDown(listbox, { key: 'Home' });
    expect(document.activeElement).toBe(rendered[0]);
  });

  it('disables the trigger and keeps the blocking reason visible', () => {
    renderControl({ disabledReason: 'No comparable baseline for this market.' });
    const trigger = screen.getByRole('button', { name: 'US baseline: BYD v1.2' });
    expect(trigger).toBeDisabled();
    const reason = screen.getByRole('note');
    expect(reason).toHaveTextContent('No comparable baseline for this market.');
    expect(trigger.getAttribute('aria-describedby')).toBe(reason.id);
    fireEvent.click(trigger);
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('explains when there are no baseline options', () => {
    renderControl({ options: [], value: 'none' });
    fireEvent.click(screen.getByRole('button', { name: 'US baseline: No baseline' }));
    expect(screen.getByRole('status')).toHaveTextContent('No baseline options are available.');
    expect(screen.queryByRole('option')).not.toBeInTheDocument();
  });
});
