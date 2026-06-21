/**
 * Shared formatting and UI utilities used across multiple page components.
 * Import from "@/lib/format" instead of re-defining these in each file.
 */
import { useState, useCallback } from 'react';
import { ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react';

// ---------------------------------------------------------------------------
// Number formatters
// ---------------------------------------------------------------------------

/** Format a number with fixed decimals. Returns "N/A" for null/undefined/NaN. */
export function formatNum(v: number | null | undefined, decimals = 4): string {
  if (v === null || v === undefined || Number.isNaN(v)) return 'N/A';
  return v.toFixed(decimals);
}

/** Format a number as a percentage string (e.g. 0.1234 → "12.34%"). */
export function formatPct(v: number | null | undefined, decimals = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return 'N/A';
  return `${(v * 100).toFixed(decimals)}%`;
}

/** Format a large number with K/M suffixes. */
export function formatCompact(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return 'N/A';
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v.toFixed(2);
}

// ---------------------------------------------------------------------------
// String helpers
// ---------------------------------------------------------------------------

/** Truncate an ID to 8 characters for display. */
export function shortId(value: string): string {
  if (!value) return '';
  return value.length <= 8 ? value : value.slice(0, 8);
}

// ---------------------------------------------------------------------------
// Sort helpers
// ---------------------------------------------------------------------------

export type SortDirection = 'asc' | 'desc' | null;

// ---------------------------------------------------------------------------
// Sort indicator icon
// ---------------------------------------------------------------------------

/** Renders a sort arrow icon for table column headers. */
export function SortIndicator({ column, sortKey, sortAsc }: {
  column: string;
  sortKey: string;
  sortAsc: boolean;
}) {
  if (sortKey !== column) return <ArrowUpDown className="h-3 w-3 opacity-30" />;
  return sortAsc ? (
    <ArrowUp className="h-3 w-3 text-primary" />
  ) : (
    <ArrowDown className="h-3 w-3 text-primary" />
  );
}

// ---------------------------------------------------------------------------
// useSort hook — consolidates toggleSort + SortIcon pattern
// ---------------------------------------------------------------------------

/**
 * Manages sort state for sortable table columns.
 * Returns { sortKey, sortAsc, setSortKey, setSortAsc, toggleSort, SortIcon }.
 *
 * Usage:
 *   const { sortKey, sortAsc, toggleSort, SortIcon } = useSort<SortKey>("timestamp");
 *   // In JSX: <SortIcon column="name" />
 *   // On click: onClick={() => toggleSort("name")}
 */
export function useSort<K extends string>(defaultKey: K) {
  const [sortKey, setSortKey] = useState<K>(defaultKey);
  const [sortAsc, setSortAsc] = useState(false);

  const toggleSort = useCallback((key: K) => {
    if (sortKey === key) {
      setSortAsc(prev => !prev);
    } else {
      setSortKey(key);
      setSortAsc(false);
    }
  }, [sortKey]);

  const SortIcon = useCallback(
    ({ column }: { column: K }) => (
      <SortIndicator column={column} sortKey={sortKey} sortAsc={sortAsc} />
    ),
    [sortKey, sortAsc],
  );

  return { sortKey, sortAsc, setSortKey: setSortKey as (key: K) => void, setSortAsc, toggleSort, SortIcon } as const;
}
