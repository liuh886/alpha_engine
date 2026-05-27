import { NavLink, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  Database,
  Trophy,
  FileText,
  Settings,
  Monitor,
  Layers,
  TrendingUp,
  Cpu,
  AlertTriangle,
  BookOpen,
  X,
  LogOut,
} from 'lucide-react';
import { BrainCircuit } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useGlobalStore } from '../store/globalStore';

export function Sidebar() {
  const { sidebarCollapsed: collapsed, setSidebarCollapsed: setCollapsed } = useGlobalStore();
  const location = useLocation();

  const navItems = [
    { path: '/', label: 'Agent Center', icon: BrainCircuit },
    { path: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { path: '/terminal', label: 'Stock Terminal', icon: Monitor },
    { path: '/arena', label: 'Arena', icon: Trophy },
    { path: '/models', label: 'Model Registry', icon: Cpu },
    { path: '/compare', label: 'Compare', icon: Layers },
    { path: '/reports', label: 'Reports', icon: FileText },
    { path: '/data', label: 'Data Management', icon: Database },
    { path: '/strategy', label: 'Strategy Spec', icon: Settings },
    { path: '/docs', label: 'Docs', icon: BookOpen },
  ];

  return (
    <div
      className={cn(
        "flex flex-col border-r border-white/5 bg-background/40 backdrop-blur-2xl transition-all duration-300 ease-in-out h-screen sticky top-0 shadow-[4px_0_24px_-12px_rgba(0,0,0,0.5)] z-20",
        collapsed ? "w-16" : "w-64"
      )}
    >
      <div className="flex items-center h-14 px-4 border-b">
        <TrendingUp className="h-6 w-6 text-primary flex-shrink-0" />
        {!collapsed && (
          <span className="ml-3 font-black text-lg tracking-tight truncate">ALPHA ENGINE</span>
        )}
      </div>

      <nav className="flex-1 overflow-y-auto py-4 px-2 space-y-1 text-left">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = item.path === '/'
            ? location.pathname === '/'
            : location.pathname.startsWith(item.path);

          return (
            <NavLink
              key={item.path}
              to={item.path}
              className={cn(
                "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-semibold transition-all duration-300 relative group overflow-hidden",
                isActive
                  ? "bg-primary/20 text-primary shadow-[inset_0_1px_1px_rgba(255,255,255,0.1)] border border-primary/20"
                  : "text-muted-foreground/80 hover:bg-white/5 hover:text-foreground border border-transparent"
              )}
              title={collapsed ? item.label : undefined}
            >
              {isActive && (
                <div className="absolute left-0 top-0 bottom-0 w-1 bg-primary rounded-r-full shadow-[0_0_8px_var(--primary)]" />
              )}
              <Icon className={cn("h-4 w-4 flex-shrink-0 transition-transform duration-300", isActive ? "scale-110 drop-shadow-[0_0_5px_rgba(59,130,246,0.5)]" : "group-hover:scale-110")} />
              {!collapsed && <span>{item.label}</span>}
            </NavLink>
          );
        })}
      </nav>

      <div className="p-2 border-t">
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="w-full flex items-center justify-center p-2 rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
        >
          {collapsed ? <LogOut className="w-4 h-4" /> : <X className="w-4 h-4" />}
          {!collapsed && <span className="ml-2 text-xs font-bold uppercase tracking-widest">Collapse</span>}
        </button>
        <button
          onClick={async () => {
            if (confirm("EMERGENCY KILL SWITCH: This will instantly halt all AI Agent tasks and backend jobs. Proceed?")) {
              try { await fetch("/api/system/panic", { method: "POST" }); alert("System Panic Engaged."); } catch { }
            }
          }}
          className="w-full flex items-center justify-center p-2 mt-2 rounded-md bg-destructive/10 text-destructive hover:bg-destructive hover:text-destructive-foreground transition-colors"
          title="KILL SWITCH"
        >
          <AlertTriangle className="h-4 w-4" />
          {!collapsed && <span className="ml-2 text-xs font-black uppercase tracking-widest">Panic</span>}
        </button>
      </div>
    </div>
  );
}
