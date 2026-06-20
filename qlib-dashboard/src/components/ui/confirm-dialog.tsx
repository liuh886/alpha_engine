import * as React from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/*  ConfirmDialog                                                      */
/* ------------------------------------------------------------------ */

export interface ConfirmDialogProps {
  /** Whether the dialog is open. */
  open: boolean;
  /** Called when the open state changes. */
  onOpenChange: (open: boolean) => void;
  /** Dialog title. */
  title: string;
  /** Optional description / explanation. */
  description?: string;
  /** Optional impact warning shown in a highlighted box. */
  impact?: string;
  /** Label for the confirm button. Defaults to "Confirm". */
  confirmLabel?: string;
  /** Label for the cancel button. Defaults to "Cancel". */
  cancelLabel?: string;
  /** When true, the confirm button uses the destructive variant. */
  destructive?: boolean;
  /** Called when the user confirms. */
  onConfirm: () => void;
  /** Called when the user cancels. */
  onCancel?: () => void;
  /** Disables the confirm button (e.g. while the mutation is in flight). */
  disabled?: boolean;
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  impact,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  destructive = false,
  onConfirm,
  onCancel,
  disabled = false,
}: ConfirmDialogProps) {
  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) {
      onCancel?.();
    }
    onOpenChange(nextOpen);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>

        {impact && (
          <div
            className={cn(
              "rounded-md border px-3 py-2 text-sm",
              destructive
                ? "border-destructive/30 bg-destructive/10 text-destructive"
                : "border-muted-foreground/20 bg-muted/50 text-muted-foreground",
            )}
          >
            {impact}
          </div>
        )}

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => {
              onCancel?.();
              onOpenChange(false);
            }}
            disabled={disabled}
          >
            {cancelLabel}
          </Button>
          <Button
            variant={destructive ? "destructive" : "default"}
            onClick={onConfirm}
            disabled={disabled}
          >
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ */
/*  useConfirm — imperative helper                                     */
/* ------------------------------------------------------------------ */

interface ConfirmOptions {
  title: string;
  description?: string;
  impact?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
}

interface ConfirmState extends ConfirmOptions {
  open: boolean;
  resolve: ((value: boolean) => void) | null;
}

/**
 * Imperative confirm dialog hook.
 *
 * ```tsx
 * const confirm = useConfirm();
 * const ok = await confirm({ title: "Delete?", destructive: true });
 * if (ok) { ... }
 * ```
 */
export function useConfirm() {
  const [state, setState] = React.useState<ConfirmState>({
    open: false,
    title: "",
    resolve: null,
  });

  const confirm = React.useCallback(
    (options: ConfirmOptions): Promise<boolean> => {
      return new Promise<boolean>((resolve) => {
        setState({ ...options, open: true, resolve });
      });
    },
    [],
  );

  const handleConfirm = React.useCallback(() => {
    state.resolve?.(true);
    setState((s) => ({ ...s, open: false, resolve: null }));
  }, [state]);

  const handleCancel = React.useCallback(() => {
    state.resolve?.(false);
    setState((s) => ({ ...s, open: false, resolve: null }));
  }, [state]);

  const handleOpenChange = React.useCallback((open: boolean) => {
    if (!open) {
      setState((s) => {
        s.resolve?.(false);
        return { ...s, open: false, resolve: null };
      });
    }
  }, []);

  const DialogComponent = React.useCallback(
    (props?: Partial<ConfirmDialogProps>) => (
      <ConfirmDialog
        open={state.open}
        onOpenChange={handleOpenChange}
        title={state.title}
        description={state.description}
        impact={state.impact}
        confirmLabel={state.confirmLabel}
        cancelLabel={state.cancelLabel}
        destructive={state.destructive}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
        {...props}
      />
    ),
    [state, handleOpenChange, handleConfirm, handleCancel],
  );

  return { confirm, ConfirmDialog: DialogComponent };
}
