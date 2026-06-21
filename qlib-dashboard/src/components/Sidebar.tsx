import { NavLink, useLocation } from 'react-router-dom';
import {
  TrendingUp,
  AlertTriangle,
  X,
  LogOut,
  FlaskConical,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { apiFetch } from '@/lib/api';
import { useGlobalStore } from '../store/globalStore';
import { groupRoutes } from '../routes';

// ---------------------------------------------------------------------------
// Navigation groups — derived from the route registry
// ---------------------------------------------------------------------------

const NAV_GROUPS = Array.from(groupRoutes()).map(([title, items]) => ({
  title,
  items,
}));

// ---------------------------------------------------------------------------
// Sidebar component
// ---------------------------------------------------------------------------

export function Sidebar() {
  const { sidebarCollapsed: collapsed, setSidebarCollapsed: setCollapsed, operatorMode, setOperatorMode } = useGlobalStore();
  const location = useLocation();

  // Filter groups: hide internal routes unless operatorMode is on
  const filteredGroups = NAV_GROUPS
    .map((group) => ({
      ...group,
      items: group.items.filter(
        (r) => r.releaseLevel !== 'internal' || operatorMode,
      ),
    }))
    .filter((group) => group.items.length > 0);

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
        {filteredGroups.map((group) => (
          <div key={group.title}>
            {!collapsed && (
              <div className="px-2.5 pb-1 text-[10px] font-bold uppercase tracking-widest text-muted-foreground/60">
                {group.title}
              </div>
            )}
            <div className="space-y-0.5">
              {group.items.map((item) => {
                const Icon = item.icon;
                const navPath = item.path === '' ? '/' : `/${item.path}`;
                const isActive = item.path === ''
                  ? location.pathname === '/'
                  : location.pathname.startsWith(navPath);

                return (
                  <NavLink
                    key={item.path}
                    to={navPath}
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
                    {!collapsed && item.releaseLevel === 'experimental' && (
                      <span className="ml-auto text-[9px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-600 dark:text-amber-400">
                        beta
                      </span>
                    )}
                    {!collapsed && item.releaseLevel === 'internal' && (
                      <span className="ml-auto text-[9px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded bg-red-500/10 text-red-600 dark:text-red-400">
                        dev
                      </span>
                    )}
                  </NavLink>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* Bottom controls */}
      <div className="p-1.5 border-t space-y-0.5">
        {!collapsed && (
          <button
            onClick={() => setOperatorMode(!operatorMode)}
            className={cn(
              "w-full flex items-center gap-2 px-2.5 py-1.5 rounded text-xs font-medium transition-colors",
              operatorMode
                ? "bg-amber-500/10 text-amber-600 dark:text-amber-400"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
            aria-label={operatorMode ? "Disable operator mode" : "Enable operator mode"}
            title="Toggle operator mode (shows internal routes)"
          >
            <FlaskConical className="h-3.5 w-3.5 flex-shrink-0" />
            <span>{operatorMode ? 'Operator: ON' : 'Operator: OFF'}</span>
          </button>
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="w-full flex items-center justify-center p-2 rounded text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <LogOut className="w-4 h-4" /> : <X className="w-4 h-4" />}
          {!collapsed && <span className="ml-2 text-xs font-medium">Collapse</span>}
        </button>
        {(operatorMode || location.pathname.startsWith('/system')) && (
          <button
            onClick={async () => {
              if (confirm("EMERGENCY KILL SWITCH: Halt all jobs?")) {
                try { await apiFetch("/api/system/panic", { method: "POST" }); alert("System Panic Engaged."); } catch (e) { console.error("Panic failed:", e); }
              }
            }}
            className="w-full flex items-center justify-center p-2 rounded bg-destructive/10 text-destructive hover:bg-destructive hover:text-destructive-foreground transition-colors"
            aria-label="Emergency kill switch — halt all jobs"
            title="KILL SWITCH"
          >
            <AlertTriangle className="h-4 w-4" />
            {!collapsed && <span className="ml-2 text-xs font-bold">Panic</span>}
          </button>
        )}
      </div>
    </div>
  );
}
