import { useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import * as Popover from '@radix-ui/react-popover';
import { ChevronDown, Plus, Search } from 'lucide-react';
import {
  filterEntityOptions,
  type CompareEntityOption,
  type CompareEntitySelection,
} from '@/lib/entity-overlays';
import { cn } from '@/lib/utils';

export interface CompareControlProps {
  options: readonly CompareEntityOption[];
  selected: readonly CompareEntitySelection[];
  /** Toggle one entity; the page enforces the cap and same-market scope. */
  onToggle: (id: string) => void;
  /** Market context for the accessible name, for example "US" or "CN". */
  marketLabel: string;
  /**
   * Identity already displayed elsewhere (the page's own instrument or the
   * active market baseline) mapped to the reason it cannot be added again.
   */
  displayed: ReadonlyMap<string, string>;
  /** Hard cap for entity overlays beside the page's own instrument. */
  max: number;
}

/**
 * One searchable add control for same-market comparison entities. Models come
 * from the formal runs and instruments from the market evidence catalog; the
 * control never lists another market. Unavailable entities keep their reason.
 */
export function CompareControl({
  options,
  selected,
  onToggle,
  marketLabel,
  displayed,
  max,
}: CompareControlProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const listRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const reasonId = useId();
  const selectedIds = new Set(selected.map(item => item.id));
  const atLimit = selected.length >= max;
  const visible = filterEntityOptions(options, query);
  const groups = [
    { label: 'Models', items: visible.filter(option => option.kind === 'model') },
    { label: 'Instruments', items: visible.filter(option => option.kind === 'instrument') },
  ].filter(group => group.items.length > 0);

  const optionNodes = () => Array.from(
    listRef.current?.querySelectorAll<HTMLButtonElement>('[data-compare-option]') ?? [],
  );
  const focusOption = (index: number) => {
    const nodes = optionNodes();
    if (nodes.length === 0) return;
    const wrapped = ((index % nodes.length) + nodes.length) % nodes.length;
    nodes[wrapped]?.focus();
  };
  const handleOpenAutoFocus = (event: Event) => {
    event.preventDefault();
    searchRef.current?.focus();
  };
  const handleButtonKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
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
  const totalLabel = `${selected.length} of ${max} overlays`;

  return (
    <div className="inline-flex min-w-0 flex-col items-start gap-1">
      <Popover.Root open={open} onOpenChange={next => { setOpen(next); if (!next) setQuery(''); }}>
        <Popover.Trigger asChild>
          <button
            type="button"
            data-testid="compare-control-trigger"
            aria-label={`${marketLabel} compare: ${totalLabel}`}
            aria-haspopup="dialog"
            aria-expanded={open}
            className={cn(
              'research-touch inline-flex min-h-8 min-w-0 items-center gap-2 rounded-md border bg-background px-2.5 text-[11px] font-medium text-foreground shadow-sm transition-colors hover:bg-muted/50',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
            )}
          >
            <Plus aria-hidden="true" className="h-3 w-3 shrink-0 text-muted-foreground" />
            <span className="shrink-0 text-muted-foreground">Compare</span>
            <span className="max-w-[140px] truncate">{totalLabel}</span>
            <ChevronDown aria-hidden="true" className="h-3 w-3 shrink-0 text-muted-foreground" />
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            align="start"
            sideOffset={6}
            onOpenAutoFocus={handleOpenAutoFocus}
            className="z-50 w-[320px] max-w-[calc(100vw-2rem)] rounded-[10px] border bg-popover p-1.5 text-popover-foreground shadow-popover"
          >
            <div data-testid="compare-control" className="space-y-1">
              <label className="flex items-center gap-2 rounded-md border bg-background px-2 py-1.5">
                <Search aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <input
                  ref={searchRef}
                  type="search"
                  value={query}
                  placeholder="Search symbol, name or model"
                  aria-label={`Search ${marketLabel} comparison entities`}
                  data-testid="compare-search"
                  onChange={event => setQuery(event.target.value)}
                  onKeyDown={event => {
                    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                      event.preventDefault();
                      focusOption(0);
                    }
                  }}
                  className="h-6 w-full min-w-0 bg-transparent text-xs outline-none placeholder:text-muted-foreground"
                />
              </label>
              {atLimit && (
                <p
                  role="status"
                  data-testid="compare-max-message"
                  className="rounded-md border border-warning/40 bg-warning/5 px-2 py-1.5 text-[11px] leading-4 text-warning"
                >
                  Compare is limited to {max} overlays. Remove one to add another.
                </p>
              )}
              <div
                role="group"
                aria-label={`${marketLabel} comparison entities`}
                ref={listRef}
                onKeyDown={handleButtonKeyDown}
                className="max-h-72 overflow-y-auto"
              >
                {groups.map(group => (
                  <div key={group.label} className="pb-1">
                    <p className="px-2 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                      {group.label}
                    </p>
                    {group.items.map(option => {
                      const isSelected = selectedIds.has(option.id);
                      const duplicateReason = displayed.get(option.id);
                      const capReason = !isSelected && atLimit
                        ? `Compare is limited to ${max} overlays. Remove one to add another.`
                        : undefined;
                      const blockedReason = duplicateReason ?? capReason;
                      const disabled = blockedReason !== undefined || !option.available;
                      return (
                        <button
                          key={option.id}
                          type="button"
                          data-compare-option={option.id}
                          data-testid={`compare-option-${option.id}`}
                          aria-pressed={isSelected}
                          aria-disabled={disabled || undefined}
                          aria-describedby={disabled ? reasonId : undefined}
                          onClick={() => { if (!disabled || isSelected) onToggle(option.id); }}
                          className={cn(
                            'research-touch flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors',
                            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                            disabled && !isSelected ? 'cursor-not-allowed opacity-70' : 'hover:bg-accent',
                            isSelected && 'bg-primary/10',
                          )}
                        >
                          <span
                            aria-hidden="true"
                            className={cn(
                              'mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border text-[10px] font-bold',
                              isSelected ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-background text-transparent',
                            )}
                          >
                            {isSelected ? '−' : '+'}
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center gap-1.5">
                              <span className="truncate font-medium">{option.label}</span>
                              {(!option.available || duplicateReason) && (
                                <span className="shrink-0 text-[10px] font-semibold text-warning">Unavailable</span>
                              )}
                            </span>
                            <span className="block text-[10px] text-muted-foreground">{option.detail}</span>
                            {!option.available && option.reason && (
                              <span className="mt-0.5 block text-[10px] leading-4 text-warning">{option.reason}</span>
                            )}
                            {blockedReason && (
                              <span className="mt-0.5 block text-[10px] leading-4 text-muted-foreground">{blockedReason}</span>
                            )}
                          </span>
                          <span className="shrink-0 pt-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                            {isSelected ? 'Remove' : 'Add'}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                ))}
                {visible.length === 0 && (
                  <p role="status" className="px-2 py-3 text-xs text-muted-foreground">
                    No same-market entity matches this search.
                  </p>
                )}
                {options.length === 0 && (
                  <p role="status" className="px-2 py-3 text-xs text-muted-foreground">
                    No same-market entities are available for this chart.
                  </p>
                )}
              </div>
              <p className="border-t px-2 py-1.5 text-[10px] leading-4 text-muted-foreground">
                Same market only · up to {max} overlays · exact common dates, no interpolation
              </p>
              <span id={reasonId} className="sr-only">
                This entity is unavailable or already displayed, so it cannot be added again.
              </span>
            </div>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </div>
  );
}
