import type { ReactNode } from 'react';
import { createContext, useContext, useEffect } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { CompareEntityOption, CompareEntitySelection } from '@/lib/entity-overlays';
import { CompareControl } from './CompareControl';

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

const options: CompareEntityOption[] = [
  { id: 'model:us:qqq_v1', kind: 'model', label: 'QQQ Rotation', detail: 'qqq_v1 · formal NAV', available: true },
  { id: 'instrument:us:MSFT', kind: 'instrument', label: 'MSFT', detail: 'Microsoft', available: true },
  { id: 'instrument:us:NVDA', kind: 'instrument', label: 'NVDA', detail: 'NVIDIA', available: true },
  { id: 'instrument:us:AMD', kind: 'instrument', label: 'AMD', detail: 'Advanced Micro Devices', available: false, reason: 'No published price history.' },
];

const selected = (ids: string[]): CompareEntitySelection[] => ids.map(id => ({ id, kind: 'instrument', label: id }));

function renderControl(overrides: Partial<Parameters<typeof CompareControl>[0]> = {}) {
  const onToggle = vi.fn();
  render(
    <CompareControl
      options={options}
      selected={[]}
      onToggle={onToggle}
      marketLabel="US"
      displayed={new Map()}
      max={4}
      {...overrides}
    />,
  );
  return { onToggle };
}

describe('CompareControl', () => {
  it('names the overlay count and opens a searchable same-market picker', () => {
    renderControl();
    const trigger = screen.getByRole('button', { name: 'US compare: 0 of 4 overlays' });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByTestId('compare-search')).toHaveFocus();
    expect(screen.getByText('Models')).toBeInTheDocument();
    expect(screen.getByText('Instruments')).toBeInTheDocument();
    expect(screen.getByText('Same market only · up to 4 overlays · exact common dates, no interpolation')).toBeInTheDocument();
  });

  it('filters by symbol and name and reports an empty search honestly', () => {
    renderControl();
    fireEvent.click(screen.getByTestId('compare-control-trigger'));
    fireEvent.change(screen.getByTestId('compare-search'), { target: { value: 'micro' } });
    expect(screen.getByTestId('compare-option-instrument:us:MSFT')).toBeInTheDocument();
    expect(screen.queryByTestId('compare-option-instrument:us:NVDA')).not.toBeInTheDocument();
    fireEvent.change(screen.getByTestId('compare-search'), { target: { value: 'zzz' } });
    expect(screen.getByRole('status')).toHaveTextContent('No same-market entity matches this search.');
  });

  it('toggles a selectable entity and never toggles an unavailable one', () => {
    const { onToggle } = renderControl();
    fireEvent.click(screen.getByTestId('compare-control-trigger'));
    fireEvent.click(screen.getByTestId('compare-option-instrument:us:MSFT'));
    expect(onToggle).toHaveBeenCalledWith('instrument:us:MSFT');
    const unavailable = screen.getByTestId('compare-option-instrument:us:AMD');
    expect(unavailable).toHaveAttribute('aria-disabled', 'true');
    expect(unavailable).toHaveTextContent('No published price history.');
    fireEvent.click(unavailable);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it('keeps an entity already displayed elsewhere visible with its reason', () => {
    renderControl({ displayed: new Map([['instrument:us:NVDA', 'Already displayed as the QQQ baseline.']]) });
    fireEvent.click(screen.getByTestId('compare-control-trigger'));
    const duplicate = screen.getByTestId('compare-option-instrument:us:NVDA');
    expect(duplicate).toHaveAttribute('aria-disabled', 'true');
    expect(duplicate).toHaveTextContent('Already displayed as the QQQ baseline.');
  });

  it('enforces the cap with a visible message and disabled extras', () => {
    renderControl({ selected: selected(['a', 'b', 'c', 'd']) });
    fireEvent.click(screen.getByTestId('compare-control-trigger'));
    expect(screen.getByTestId('compare-max-message')).toHaveTextContent('Compare is limited to 4 overlays. Remove one to add another.');
    expect(screen.getByTestId('compare-option-model:us:qqq_v1')).toHaveAttribute('aria-disabled', 'true');
  });

  it('moves focus with arrow, Home and End keys from the search field', () => {
    renderControl();
    fireEvent.click(screen.getByTestId('compare-control-trigger'));
    const search = screen.getByTestId('compare-search');
    fireEvent.keyDown(search, { key: 'ArrowDown' });
    const rendered = ['model:us:qqq_v1', 'instrument:us:MSFT', 'instrument:us:NVDA', 'instrument:us:AMD']
      .map(id => screen.getByTestId(`compare-option-${id}`));
    expect(document.activeElement).toBe(rendered[0]);
    fireEvent.keyDown(document.activeElement as HTMLElement, { key: 'ArrowDown' });
    expect(document.activeElement).toBe(rendered[1]);
    fireEvent.keyDown(document.activeElement as HTMLElement, { key: 'End' });
    expect(document.activeElement).toBe(rendered[3]);
    fireEvent.keyDown(document.activeElement as HTMLElement, { key: 'Home' });
    expect(document.activeElement).toBe(rendered[0]);
  });
});
