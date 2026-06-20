/**
 * Page-level layout constants for consistent visual rhythm across release pages.
 *
 * Import these in page components to replace ad-hoc Tailwind values.
 * Values are Tailwind class strings so they compose naturally with `cn()`.
 */

// ---------------------------------------------------------------------------
// Page container
// ---------------------------------------------------------------------------

/** Outer wrapper — max width + horizontal center + bottom padding. */
export const PAGE_CONTAINER = "space-y-5 max-w-[1400px] mx-auto pb-16" as const;

/** Wide variant for data-heavy pages (compare, factors, models). */
export const PAGE_CONTAINER_WIDE = "space-y-5 max-w-[1600px] mx-auto pb-16" as const;

// ---------------------------------------------------------------------------
// Header / title area
// ---------------------------------------------------------------------------

/** Header bar: bottom border + padding. */
export const PAGE_HEADER = "border-b pb-4 flex items-end justify-between" as const;

/** Main page title. */
export const PAGE_TITLE = "text-2xl font-bold tracking-tight" as const;

/** Subtitle / description under the title. */
export const PAGE_SUBTITLE = "text-muted-foreground text-sm mt-1" as const;

// ---------------------------------------------------------------------------
// Toolbar (filters, sort controls)
// ---------------------------------------------------------------------------

/** Toolbar row: flex wrap with consistent gap. */
export const TOOLBAR = "flex flex-wrap items-end gap-3" as const;

/** Toolbar label (above an input or button group). */
export const TOOLBAR_LABEL = "text-xs text-muted-foreground" as const;

// ---------------------------------------------------------------------------
// Form controls
// ---------------------------------------------------------------------------

/** Compact form input height + text size used in toolbars. */
export const INPUT_SM = "h-7 text-xs" as const;

/** Compact select element. */
export const SELECT_SM = "h-7 px-2 text-xs border rounded bg-background" as const;

// ---------------------------------------------------------------------------
// Cards
// ---------------------------------------------------------------------------

/** Standard card header with bottom border. */
export const CARD_HEADER = "pb-3 border-b" as const;

/** Card title with icon slot. */
export const CARD_TITLE = "text-sm font-semibold" as const;

// ---------------------------------------------------------------------------
// Tables
// ---------------------------------------------------------------------------

/** Column header text style. */
export const TABLE_HEAD = "text-[10px] font-bold uppercase tracking-wider text-muted-foreground" as const;

// ---------------------------------------------------------------------------
// Charts
// ---------------------------------------------------------------------------

/** Standard chart card height for single-line charts. */
export const CHART_HEIGHT_SM = 280 as const;

/** Standard chart card height for full-width charts. */
export const CHART_HEIGHT_MD = 450 as const;
