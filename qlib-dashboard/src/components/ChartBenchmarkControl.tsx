import { useMemo, useState } from 'react';
import * as Popover from '@radix-ui/react-popover';
import { Check, ChevronDown, Search, Star } from 'lucide-react';
import type { PerformanceComparisonOption } from '@/lib/performanceComparisons';
import { cn } from '@/lib/utils';

export function ChartBenchmarkControl({
  options,
  primaryKey,
  selectedKeys,
  loadingKeys = [],
  unavailableLabel,
  onPrimaryChange,
  onToggle,
}: {
  options: PerformanceComparisonOption[];
  primaryKey: string | null;
  selectedKeys: string[];
  loadingKeys?: string[];
  unavailableLabel?: string;
  onPrimaryChange: (key: string) => void;
  onToggle: (key: string) => void;
}) {
  const [query, setQuery] = useState('');
  const selected = new Set(selectedKeys);
  const loading = new Set(loadingKeys);
  const primary = options.find(option => option.key === primaryKey) ?? null;
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return options;
    return options.filter(option => `${option.label} ${option.detail ?? ''}`.toLowerCase().includes(needle));
  }, [options, query]);
  const groups = ['Benchmarks', 'Stock pool'] as const;

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          type="button"
          aria-label="Benchmark comparisons"
          className="inline-flex h-8 items-center gap-2 rounded-md border bg-background px-2.5 text-[11px] font-medium text-foreground shadow-sm transition-colors hover:bg-muted/50"
        >
          <span className="text-muted-foreground">Compare</span>
          <span>{primary?.label ?? unavailableLabel ?? 'No primary'}</span>
          {selectedKeys.length > 1 && (
            <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[9px] text-muted-foreground">+{selectedKeys.length - 1}</span>
          )}
          <ChevronDown className="h-3 w-3 text-muted-foreground" />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={6}
          className="z-50 w-[320px] rounded-lg border bg-popover p-2 text-popover-foreground shadow-xl"
        >
          <div className="px-1 pb-2">
            <p className="text-xs font-semibold">Benchmarks & comparisons</p>
            <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">
              Star sets the primary benchmark for Excess. Check any number of series to overlay.
            </p>
          </div>
          <div className="relative mb-2">
            <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-muted-foreground" />
            <input
              aria-label="Search benchmarks or stock pool"
              value={query}
              onChange={event => setQuery(event.target.value)}
              placeholder="Search symbol or company"
              className="h-8 w-full rounded-md border bg-background pl-8 pr-2 text-xs outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
          <div className="max-h-[360px] overflow-y-auto pr-1">
            {groups.map(group => {
              const rows = filtered.filter(option => option.group === group);
              if (!rows.length) return null;
              return (
                <div key={group} className="mb-2 last:mb-0">
                  <p className="sticky top-0 z-10 bg-popover px-2 py-1 text-[9px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                    {group}
                  </p>
                  <div className="space-y-0.5">
                    {rows.map(option => {
                      const isPrimary = option.key === primaryKey;
                      const isSelected = selected.has(option.key);
                      const isLoading = loading.has(option.key);
                      return (
                        <div key={option.key} className="group flex items-center gap-1 rounded-md px-1 py-0.5 hover:bg-muted/50">
                          <button
                            type="button"
                            aria-label={`Compare ${option.label}`}
                            aria-pressed={isSelected}
                            onClick={() => onToggle(option.key)}
                            className="flex min-w-0 flex-1 items-center gap-2 rounded px-1 py-1.5 text-left"
                          >
                            <span className={cn(
                              'flex h-4 w-4 shrink-0 items-center justify-center rounded border',
                              isSelected ? 'border-primary bg-primary text-primary-foreground' : 'border-muted-foreground/30',
                            )}>
                              {isSelected && <Check className="h-3 w-3" />}
                            </span>
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-xs font-medium">{option.label}</span>
                              {option.detail && <span className="block truncate text-[9px] text-muted-foreground">{option.detail}</span>}
                            </span>
                            {isLoading && <span className="text-[9px] text-muted-foreground">Loading</span>}
                          </button>
                          <button
                            type="button"
                            aria-label={`Use ${option.label} as primary benchmark`}
                            aria-pressed={isPrimary}
                            onClick={() => onPrimaryChange(option.key)}
                            className={cn(
                              'rounded p-1.5 transition-colors hover:bg-background',
                              isPrimary ? 'text-amber-500' : 'text-muted-foreground/35 hover:text-muted-foreground',
                            )}
                          >
                            <Star className={cn('h-3.5 w-3.5', isPrimary && 'fill-current')} />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
            {!filtered.length && (
              <p className="px-2 py-6 text-center text-xs text-muted-foreground">No matching comparison.</p>
            )}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
