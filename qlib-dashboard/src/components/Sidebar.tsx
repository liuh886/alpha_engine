import { NavLink, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  Database,
  FileText,
  TrendingUp,
  Cpu,
  AlertTriangle,
  BookOpen,
  X,
  LogOut,
  FlaskConical,
  Layers,
  BarChart3,
  ListChecks,
  ClipboardList,
  PieChart,
  Terminal,
  Swords,
  ScrollText,
  Settings,
  Bot,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useGlobalStore } from '../store/globalStore';

// ---------------------------------------------------------------------------
// Navigation groups
// ---------------------------------------------------------------------------

interface NavItem {
  path: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    title: "Core",
    items: [
      { path: '/', label: 'Dashboard', icon: LayoutDashboard },
      { path: '/terminal', label: 'Stock Terminal', icon: Terminal },
      { path: '/backtest', label: 'Backtest', icon: FlaskConical },
    ],
  },
  {
    title: "Research",
    items: [
      { path: '/models', label: 'Models', icon: Cpu },
      { path: '/factors', label: 'Factor Analysis', icon: BarChart3 },
      { path: '/factor-registry', label: 'Factor Registry', icon: ListChecks },
      { path: '/experiments', label: 'Experiments', icon: ClipboardList },
      { path: '/attribution', label: 'Attribution', icon: PieChart },
      { path: '/compare', label: 'Compare', icon: Layers },
    ],
  },
  {
    title: "Strategy",
    items: [
      { path: '/arena', label: 'Arena', icon: Swords },
      { path: '/strategy', label: 'Strategy Spec', icon: Settings },
      { path: '/reports', label: 'Reports', icon: ScrollText },
    ],
  },
  {
    title: "System",
    items: [
      { path: '/data', label: 'Data', icon: Database },
      { path: '/agent', label: 'Agent Center', icon: Bot },
      { path: '/methodology', label: 'Methodology', icon: BookOpen },
      { path: '/docs', label: 'Docs', icon: FileText },
    ],
  },
];

// ---------------------------------------------------------------------------
// Sidebar component
// ---------------------------------------------------------------------------

export function Sidebar() {
  const { sidebarCollapsed: collapsed, setSidebarCollapsed: setCollapsed } = useGlobalStore();
  const location = useLocation();

  return (
    <div
      className={cn(
        "flex flex-col border-r bg-card transition-all duration-200 h-screen sticky top-0 z-20",
        collapsed ? "w-14" : "w-52"
      )}
    >
      {/* Logo */}
      <div className="flex items-center h-12 px-3 border-b">
        <TrendingUp className="h-5 w-5 text-primary flex-shrink-0" />
        {!collapsed && (
          <span className="ml-2.5 font-bold text-sm tracking-tight">ALPHA ENGINE</span>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-3 px-1.5 space-y-3 text-left">
        {NAV_GROUPS.map((group) => (
          <div key={group.title}>
            {!collapsed && (
              <div className="px-2.5 pb-1 text-[10px] font-bold uppercase tracking-widest text-muted-foreground/60">
                {group.title}
              </div>
            )}
            <div className="space-y-0.5">
              {group.items.map((item) => {
                const Icon = item.icon;
                const isActive = item.path === '/'
                  ? location.pathname === '/'
                  : location.pathname.startsWith(item.path);

                return (
                  <NavLink
                    key={item.path}
                    to={item.path}
                    className={cn(
                      "w-full flex items-center gap-2.5 px-2.5 py-2 rounded text-sm transition-colors",
                      isActive
                        ? "bg-primary/10 text-primary font-medium"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground"
                    )}
                    title={collapsed ? item.label : undefined}
                  >
                    <Icon className="h-4 w-4 flex-shrink-0" />
                    {!collapsed && <span>{item.label}</span>}
                  </NavLink>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* Bottom controls */}
      <div className="p-1.5 border-t space-y-0.5">
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="w-full flex items-center justify-center p-2 rounded text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
        >
          {collapsed ? <LogOut className="w-4 h-4" /> : <X className="w-4 h-4" />}
          {!collapsed && <span className="ml-2 text-xs font-medium">Collapse</span>}
        </button>
        <button
          onClick={async () => {
            if (confirm("EMERGENCY KILL SWITCH: Halt all jobs?")) {
              try { await fetch("/api/system/panic", { method: "POST" }); alert("System Panic Engaged."); } catch { }
            }
          }}
          className="w-full flex items-center justify-center p-2 rounded bg-destructive/10 text-destructive hover:bg-destructive hover:text-destructive-foreground transition-colors"
          title="KILL SWITCH"
        >
          <AlertTriangle className="h-4 w-4" />
          {!collapsed && <span className="ml-2 text-xs font-bold">Panic</span>}
        </button>
      </div>
    </div>
  );
}
