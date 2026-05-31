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
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useGlobalStore } from '../store/globalStore';

export function Sidebar() {
  const { sidebarCollapsed: collapsed, setSidebarCollapsed: setCollapsed } = useGlobalStore();
  const location = useLocation();

  const navItems = [
    { path: '/', label: 'Dashboard', icon: LayoutDashboard },
    { path: '/backtest', label: 'Backtest', icon: FlaskConical },
    { path: '/models', label: 'Models', icon: Cpu },
    { path: '/compare', label: 'Compare', icon: Layers },
    { path: '/data', label: 'Data', icon: Database },
    { path: '/methodology', label: 'Methodology', icon: BookOpen },
    { path: '/docs', label: 'Docs', icon: FileText },
  ];

  return (
    <div
      className={cn(
        "flex flex-col border-r bg-card transition-all duration-200 h-screen sticky top-0 z-20",
        collapsed ? "w-14" : "w-52"
      )}
    >
      <div className="flex items-center h-12 px-3 border-b">
        <TrendingUp className="h-5 w-5 text-primary flex-shrink-0" />
        {!collapsed && (
          <span className="ml-2.5 font-bold text-sm tracking-tight">ALPHA ENGINE</span>
        )}
      </div>

      <nav className="flex-1 overflow-y-auto py-3 px-1.5 space-y-0.5 text-left">
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
      </nav>

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
