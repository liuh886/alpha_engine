import { ReactNode } from "react";
import { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface PlaceholderProps {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
  variant?: "default" | "error" | "success" | "warning";
}

export function Placeholder({ icon: Icon, title, description, action, className, variant = "default" }: PlaceholderProps) {
  const iconColors = {
    default: "text-muted-foreground/30 group-hover:text-primary transition-colors",
    error: "text-destructive/50",
    warning: "text-amber-500/50",
    success: "text-green-500/50",
  };

  return (
    <div className={cn("flex flex-col items-center justify-center p-8 text-center bg-muted/10 rounded-2xl border-2 border-dashed border-border/50 group h-full min-h-[200px]", className)}>
      <Icon className={cn("h-12 w-12 mb-4 stroke-1", iconColors[variant])} />
      <h3 className="text-xs font-black uppercase tracking-widest text-muted-foreground mb-1">{title}</h3>
      {description && (
        <p className="text-[10px] text-muted-foreground max-w-[250px] font-medium leading-relaxed">{description}</p>
      )}
      {action && (
        <div className="mt-4">
          {action}
        </div>
      )}
    </div>
  );
}
