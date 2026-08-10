import type { BenchmarkOption } from '@/lib/performanceBenchmarks';

export function ChartBaselineSelector({
  options,
  activeKey,
  unavailableLabel,
  onChange,
}: {
  options: BenchmarkOption[];
  activeKey: string | null;
  unavailableLabel?: string;
  onChange: (key: string | null) => void;
}) {
  const active = options.find(option => option.key === activeKey) ?? null;

  return (
    <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
      <span>Chart baseline</span>
      {options.length > 1 ? (
        <select
          aria-label="Chart baseline"
          className="h-7 rounded-md border bg-background px-2 text-xs text-foreground"
          value={activeKey ?? ''}
          onChange={(event) => onChange(event.target.value || null)}
        >
          {!activeKey && <option value="">Unavailable</option>}
          {options.map(option => (
            <option key={option.key} value={option.key}>{option.label}</option>
          ))}
        </select>
      ) : (
        <span className="font-medium text-foreground">
          {active?.label ?? unavailableLabel ?? 'Unavailable'}
        </span>
      )}
    </div>
  );
}
