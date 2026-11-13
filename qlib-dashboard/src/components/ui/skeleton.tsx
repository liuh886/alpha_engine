import { cn } from "@/lib/utils";

type SkeletonProps = React.HTMLAttributes<HTMLDivElement>

export function Skeleton({ className, ...props }: SkeletonProps) {
    return (
        <div
            data-slot="skeleton"
            className={cn("animate-pulse rounded-lg border border-border/40 bg-muted", className)}
            {...props}
        />
    );
}
