import { useMemo } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { ChevronsLeft, ChevronsRight, Orbit } from 'lucide-react';
import { cn } from '@/lib/utils';
import { groupRoutes } from '@/routes';
import { useGlobalStore } from '@/store/globalStore';

export function Sidebar() {
  const collapsed = useGlobalStore(state => state.sidebarCollapsed);
  const setCollapsed = useGlobalStore(state => state.setSidebarCollapsed);
  const location = useLocation();
  const groups = useMemo(() => Array.from(groupRoutes()).map(([title, items]) => ({ title, items })), []);
  return <aside className={cn('research-sidebar', collapsed ? 'research-sidebar-collapsed' : 'research-sidebar-expanded')}>
    <Link to="/app" className="research-brand" aria-label="Open today's research">
      <div className="research-brand-mark"><Orbit className="h-4 w-4" /></div>
      {!collapsed && <div className="min-w-0">
        <div className="research-brand-name">Alpha Engine</div>
        <div className="research-brand-subtitle">Research Workspace</div>
      </div>}
    </Link>
    <nav className="research-nav" aria-label="Research workspace navigation">
      {groups.map(group => <section key={group.title} className="research-nav-group">
        {!collapsed && <p className="mb-1.5 px-2 text-[9px] font-bold uppercase tracking-[0.18em] text-muted-foreground/75">{group.title}</p>}
        <div className="space-y-1">{group.items.map(item => {
          const Icon = item.icon;
          const target = '/' + item.path;
          const active = location.pathname === target || location.pathname.startsWith(target + '/');
          return <NavLink key={item.path} to={target}
            className={cn('research-nav-link', active && 'research-nav-link-active')}
            title={collapsed ? item.label : undefined} aria-current={active ? 'page' : undefined}>
            <Icon className="h-4 w-4 shrink-0" />
            {!collapsed && <span className="truncate">{item.label}</span>}
          </NavLink>;
        })}</div>
      </section>)}
    </nav>
    <div className="research-sidebar-footer">
      <button type="button" onClick={() => setCollapsed(!collapsed)}
        className="research-sidebar-action justify-center"
        aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}>
        {collapsed ? <ChevronsRight className="h-4 w-4" /> :
          <><ChevronsLeft className="h-4 w-4" /><span>Collapse rail</span></>}
      </button>
      {!collapsed && <div className="research-version">v{import.meta.env.VITE_APP_VERSION || 'dev'} · {import.meta.env.VITE_GIT_COMMIT_SHA || 'unknown'}</div>}
    </div>
  </aside>;
}
