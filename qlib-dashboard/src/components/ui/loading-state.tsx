import * as React from "react";
import { Loader2, AlertCircle, Inbox, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

/* ------------------------------------------------------------------ */
/*  LoadingSpinner                                                     */
/* ------------------------------------------------------------------ */

export interface LoadingSpinnerProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Optional message shown below the spinner. */
  message?: string;
  /** Spinner size in pixels. Defaults to 24. */
  size?: number;
}

export function LoadingSpinner({
  message,
  size = 24,
  className,
  ...props
}: LoadingSpinnerProps) {
  return (
    <div
      role="status"
      className={cn("flex flex-col items-center justify-center gap-2 py-8", className)}
      {...props}
    >
      <Loader2 className="animate-spin text-muted-foreground" style={{ width: size, height: size }} />
      {message && <p className="text-sm text-muted-foreground">{message}</p>}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  EmptyState                                                         */
/* ------------------------------------------------------------------ */

export interface EmptyStateProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Message to display. */
  message: string;
  /** Optional description below the message. */
  description?: string;
  /** Optional icon. Defaults to Inbox. */
  icon?: React.ReactNode;
}

export function EmptyState({
  message,
  description,
  icon,
  className,
  ...props
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 py-12 text-center",
        className,
      )}
      {...props}
    >
      {icon ?? <Inbox className="h-10 w-10 text-muted-foreground/50" />}
      <p className="text-sm font-medium text-muted-foreground">{message}</p>
      {description && (
        <p className="text-xs text-muted-foreground/70 max-w-xs">{description}</p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  ErrorState                                                         */
/* ------------------------------------------------------------------ */

export interface ErrorStateProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Error message to display. */
  message: string;
  /** Called when the user clicks the retry button. Omit to hide the button. */
  onRetry?: () => void;
}

export function ErrorState({
  message,
  onRetry,
  className,
  ...props
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center gap-3 py-12 text-center",
        className,
      )}
      {...props}
    >
      <AlertCircle className="h-10 w-10 text-destructive/70" />
      <p className="text-sm font-medium text-destructive">{message}</p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry} className="gap-1.5">
          <RefreshCw className="h-3.5 w-3.5" />
          Retry
        </Button>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  StaleDataIndicator                                                 */
/* ------------------------------------------------------------------ */

export interface StaleDataIndicatorProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Optional timestamp string shown alongside the stale warning. */
  since?: string;
}

export function StaleDataIndicator({
  since,
  className,
  ...props
}: StaleDataIndicatorProps) {
  return (
    <div
      className={cn(
        "flex items-center gap-1.5 rounded-md border border-yellow-500/30 bg-yellow-500/10 px-3 py-1.5 text-xs text-yellow-700 dark:text-yellow-400",
        className,
      )}
      {...props}
    >
      <RefreshCw className="h-3 w-3" />
      <span>
        Showing stale data{since ? ` (fetched ${since})` : ""}. Refresh to update.
      </span>
    </div>
  );
}
