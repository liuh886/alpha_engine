import { useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import * as Popover from '@radix-ui/react-popover';
import { Check, ChevronDown } from 'lucide-react';
import type { BaselineKind, BaselineOption } from '@/lib/baseline';
import { cn } from '@/lib/utils';

export interface BaselineControlProps {
  options: BaselineOption[];
  value: BaselineKind;
  onChange: (kind: BaselineKind) => void;
  /** Market context for the accessible name, for example "US" or "CN". */
  marketLabel: string;
  /** When set, the control is disabled and the reason stays visible. */
  disabledReason?: string;
}

function fallbackLabel(kind: BaselineKind): string {
  if (kind === 'declared') return 'Declared benchmark';
  if (kind === 'market') return 'Market baseline';
  return 'No baseline';
}

function sourceLabel(option: BaselineOption): string {
  if (option.source === 'formal_report') return 'Formal report';
  if (option.source === 'market_bars') return 'Market bars';
  return 'No overlay';
}

/** Compact single-select baseline control with keyboard-operable options. */
export function BaselineControl({ options, value, onChange, marketLabel, disabledReason }: BaselineControlProps) {
  const [open, setOpen] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const reasonId = useId();
  const disabled = typeof disabledReason === 'string' && disabledReason.trim() !== '';
  const selected = options.find(option => option.kind === value) ?? null;
  const selectedLabel = selected?.label ?? fallbackLabel(value);
  const selectedUnavailable = selected !== null && !selected.available;

  const optionNodes = () => Array.from(listRef.current?.querySelectorAll<HTMLButtonElement>('[role="option"]') ?? []);

  const focusOption = (index: number) => {
    const nodes = optionNodes();
    if (nodes.length === 0) return;
    const wrapped = ((index % nodes.length) + nodes.length) % nodes.length;
    nodes[wrapped]?.focus();
  };

  const handleOpenAutoFocus = (event: Event) => {
    event.preventDefault();
    const selectedIndex = options.findIndex(option => option.kind === value);
    focusOption(selectedIndex >= 0 ? selectedIndex : 0);
  };

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const nodes = optionNodes();
    if (nodes.length === 0) return;
    const current = nodes.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      focusOption(current + 1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      focusOption(current - 1);
    } else if (event.key === 'Home') {
      event.preventDefault();
      focusOption(0);
    } else if (event.key === 'End') {
      event.preventDefault();
      focusOption(nodes.length - 1);
    }
  };

  const select = (option: BaselineOption) => {
    if (!option.available) return;
    onChange(option.kind);
    setOpen(false);
  };

  return (
    <div className="inline-flex min-w-0 flex-col items-start gap-1">
      <Popover.Root open={open} onOpenChange={next => setOpen(disabled ? false : next)}>
        <Popover.Trigger asChild>
          <button
            type="button"
            disabled={disabled}
            aria-label={`${marketLabel} baseline: ${selectedLabel}${selectedUnavailable ? ' (unavailable)' : ''}`}
            aria-haspopup="listbox"
            aria-expanded={open}
            aria-describedby={disabled ? reasonId : undefined}
            className={cn(
              'research-touch inline-flex min-h-8 min-w-0 items-center gap-2 rounded-md border bg-background px-2.5 text-[11px] font-medium text-foreground shadow-sm transition-colors hover:bg-muted/50',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
              disabled && 'cursor-not-allowed opacity-60',
            )}
          >
            <span className="shrink-0 text-muted-foreground">Baseline</span>
            <span className="max-w-[180px] truncate">{selectedLabel}</span>
            {selectedUnavailable && <span className="shrink-0 text-[10px] font-semibold text-warning">Unavailable</span>}
            <ChevronDown aria-hidden="true" className="h-3 w-3 shrink-0 text-muted-foreground" />
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            align="start"
            sideOffset={6}
            onOpenAutoFocus={handleOpenAutoFocus}
            className="z-50 w-[300px] rounded-[10px] border bg-popover p-1.5 text-popover-foreground shadow-popover"
          >
            <div role="listbox" aria-label={`${marketLabel} baseline options`} ref={listRef} onKeyDown={handleKeyDown}>
              <p className="px-2 pb-1.5 pt-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                {marketLabel} baseline
              </p>
              {options.map(option => {
                const isSelected = option.kind === value;
                return (
                  <button
                    key={option.key}
                    type="button"
                    role="option"
                    tabIndex={-1}
                    aria-selected={isSelected}
                    aria-disabled={!option.available || undefined}
                    data-unavailable={option.available ? undefined : 'true'}
                    onClick={() => select(option)}
                    className={cn(
                      'research-touch flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                      option.available ? 'hover:bg-accent' : 'cursor-not-allowed opacity-70',
                      isSelected && 'bg-primary/10',
                    )}
                  >
                    <Check
                      aria-hidden="true"
                      className={cn('mt-0.5 h-3 w-3 shrink-0', isSelected ? 'text-primary' : 'text-transparent')}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{option.label}</span>
                      <span className="block text-[10px] text-muted-foreground">{sourceLabel(option)}</span>
                      {!option.available && option.reason && (
                        <span className="mt-0.5 block text-[10px] leading-4 text-warning">Unavailable: {option.reason}</span>
                      )}
                    </span>
                    {isSelected && <span className="shrink-0 text-[10px] font-semibold text-primary">Selected</span>}
                    {!option.available && <span className="shrink-0 text-[10px] font-semibold text-warning">Unavailable</span>}
                  </button>
                );
              })}
              {options.length === 0 && (
                <p role="status" className="px-2 py-3 text-xs text-muted-foreground">No baseline options are available.</p>
              )}
            </div>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
      {disabled && (
        <p id={reasonId} role="note" className="max-w-[260px] text-[11px] leading-4 text-muted-foreground">
          {disabledReason}
        </p>
      )}
    </div>
  );
}
