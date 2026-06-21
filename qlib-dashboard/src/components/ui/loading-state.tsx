import * as React from "react";
import { Loader2, AlertCircle, Inbox, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

import { Placeholder } from "@/components/Placeholder";

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
    <div className={className} {...props}>
      <Placeholder 
        className="border-none bg-transparent"
        icon={Loader2} 
        title="Loading" 
        description={message} 
      />
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
  icon?: any;
}

export function EmptyState({
  message,
  description,
  icon,
  className,
  ...props
}: EmptyStateProps) {
  return (
    <div className={className} {...props}>
      <Placeholder 
        className="border-none bg-transparent"
        icon={icon ?? Inbox} 
        title={message} 
        description={description} 
      />
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
    <div className={className} {...props}>
      <Placeholder 
        className="border-none bg-transparent"
        icon={AlertCircle} 
        title="Error" 
        description={message} 
        variant="error"
        action={onRetry ? (
          <Button variant="outline" size="sm" onClick={onRetry} className="gap-1.5 h-7 text-xs">
            <RefreshCw className="h-3.5 w-3.5" />
            Retry
          </Button>
        ) : undefined}
      />
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
