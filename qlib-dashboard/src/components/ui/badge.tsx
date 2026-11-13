import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[11px] font-semibold leading-4 tracking-[0.01em] transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary text-primary-foreground hover:bg-primary/90",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80",
        destructive:
          "border-destructive/25 bg-destructive/10 text-destructive hover:bg-destructive/15 dark:text-negative",
        outline: "border-border bg-transparent text-foreground",
        positive: "border-positive/25 bg-positive/10 text-positive",
        negative: "border-negative/25 bg-negative/10 text-negative",
        warning: "border-warning/25 bg-warning/10 text-warning",
        info: "border-info/25 bg-info/10 text-info",
        muted: "border-border bg-muted/60 text-muted-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props} />
  )
}

export { Badge, badgeVariants }
