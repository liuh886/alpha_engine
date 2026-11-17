import { useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import * as Popover from '@radix-ui/react-popover';
import { Check, ChevronDown } from 'lucide-react';
import type { IndicatorOption } from '@/lib/indicator-overlays';
import { cn } from '@/lib/utils';

export interface IndicatorControlOption extends IndicatorOption {
  available: boolean;
  reason?: string;
}

export interface IndicatorControlProps {
  options: readonly IndicatorControlOption[];
  selected: readonly string[];
  onToggle: (id: string) => void;
  /** Market context for the accessible name, for example "US" or "CN". */
  marketLabel: string;
}

const GROUP_ORDER: ReadonlyArray<{ group: IndicatorOption['group']; label: string }> = [
  { group: 'price', label: 'Price pane' },
  { group: 'volume', label: 'Volume pane' },
  { group: 'indicator', label: 'Indicator pane' },
];

function groupLabel(group: IndicatorOption['group']): string {
  if (group === 'price') return 'Price pane';
  if (group === 'volume') return 'Volume pane';
  return 'Indicator pane';
}

/**
 * One compact multi-select control for governed chart indicators. Every entry
 * is a keyboard-operable toggle with `aria-pressed`; unavailable market entries
 * stay selectable so their reason remains readable, but they never emit a value.
 */
export function IndicatorControl({ options, selected, onToggle, marketLabel }: IndicatorControlProps) {
  const [open, setOpen] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const selectedIds = new Set(selected);
  const reasonId = useId();
  const active = options.filter(option => selectedIds.has(option.id));
  const activeLabel = active.length === 0 ? 'none active' : `${active.length} active`;

  const optionNodes = () => Array.from(listRef.current?.querySelectorAll<HTMLButtonElement>('[data-indicator-option]') ?? []);
  const focusOption = (index: number) => {
    const nodes = optionNodes();
    if (nodes.length === 0) return;
    const wrapped = ((index % nodes.length) + nodes.length) % nodes.length;
    nodes[wrapped]?.focus();
  };
  const handleOpenAutoFocus = (event: Event) => {
    event.preventDefault();
    const focused = options.findIndex(option => selectedIds.has(option.id));
    focusOption(focused >= 0 ? focused : 0);
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

  const groups = [
    ...GROUP_ORDER.map(({ group, label }) => ({
      label,
      items: options.filter(option => option.group === group && option.scope !== 'market'),
    })),
    { label: 'Market', items: options.filter(option => option.scope === 'market') },
  ].filter(entry => entry.items.length > 0);

  return (
    <div className="inline-flex min-w-0 flex-col items-start gap-1">
      <Popover.Root open={open} onOpenChange={setOpen}>
        <Popover.Trigger asChild>
          <button
            type="button"
            aria-label={`${marketLabel} indicators: ${activeLabel}`}
            aria-haspopup="dialog"
            aria-expanded={open}
            className={cn(
              'research-touch inline-flex min-h-8 min-w-0 items-center gap-2 rounded-md border bg-background px-2.5 text-[11px] font-medium text-foreground shadow-sm transition-colors hover:bg-muted/50',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
            )}
          >
            <span className="shrink-0 text-muted-foreground">Indicators</span>
            <span data-testid="indicator-control-count" className="max-w-[180px] truncate">
              {active.length === 0 ? 'None' : `${active.length} active`}
            </span>
            <ChevronDown aria-hidden="true" className="h-3 w-3 shrink-0 text-muted-foreground" />
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            align="start"
            sideOffset={6}
            onOpenAutoFocus={handleOpenAutoFocus}
            className="z-50 w-[320px] rounded-[10px] border bg-popover p-1.5 text-popover-foreground shadow-popover"
          >
            <div role="group" aria-label={`${marketLabel} chart indicators`} ref={listRef} onKeyDown={handleKeyDown} className="max-h-[min(60vh,360px)] overflow-y-auto">
              {groups.map(group => (
                <div key={group.label} className="pb-1">
                  <p className="px-2 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                    {group.label}
                  </p>
                  {group.items.map(option => {
                    const isOn = selectedIds.has(option.id);
                    return (
                      <button
                        key={option.id}
                        type="button"
                        data-indicator-option={option.id}
                        aria-pressed={isOn}
                        aria-describedby={!option.available ? reasonId : undefined}
                        onClick={() => onToggle(option.id)}
                        className={cn(
                          'research-touch flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors',
                          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                          'hover:bg-accent',
                          isOn && 'bg-primary/10',
                        )}
                      >
                        <span
                          aria-hidden="true"
                          className={cn(
                            'mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border',
                            isOn ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-background',
                          )}
                        >
                          {isOn && <Check className="h-3 w-3" />}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-1.5">
                            <span className="truncate font-medium">{option.label}</span>
                            {!option.available && (
                              <span className="shrink-0 text-[10px] font-semibold text-warning">Unavailable</span>
                            )}
                          </span>
                          <span className="block text-[10px] text-muted-foreground">{groupLabel(option.group)}</span>
                          {!option.available && option.reason && (
                            <span className="mt-0.5 block text-[10px] leading-4 text-warning">{option.reason}</span>
                          )}
                        </span>
                        <span className="shrink-0 pt-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                          {isOn ? 'On' : 'Off'}
                        </span>
                      </button>
                    );
                  })}
                </div>
              ))}
              {options.length === 0 && (
                <p role="status" className="px-2 py-3 text-xs text-muted-foreground">
                  No governed indicators are available for this chart.
                </p>
              )}
              <p className="border-t px-2 py-1.5 text-[10px] leading-4 text-muted-foreground">
                Browser-derived from observed bars · not a signal
              </p>
              <span id={reasonId} className="sr-only">
                This market indicator has no governed series published, so it cannot render values.
              </span>
            </div>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </div>
  );
}
