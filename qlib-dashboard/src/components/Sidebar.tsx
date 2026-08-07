import { useMemo } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { ChevronsLeft, ChevronsRight, Orbit } from 'lucide-react';
import { useActiveResearchBundle } from '@/hooks/useActiveResearchBundle';
import { formatEvidenceLabel } from '@/lib/format-evidence-label';
import type { GovernedRunSummary } from '@/lib/governed-run';
import { cn } from '@/lib/utils';
import { groupRoutes } from '@/routes';
import { useGlobalStore } from '@/store/globalStore';

export function Sidebar({ activeRun = null }: { activeRun?: GovernedRunSummary | null }) {
  const collapsed = useGlobalStore((state) => state.sidebarCollapsed);
  const setCollapsed = useGlobalStore((state) => state.setSidebarCollapsed);
  const location = useLocation();
  const bundle = useActiveResearchBundle();
  const groups = useMemo(
    () => Array.from(groupRoutes()).map(([title, items]) => ({ title, items })),
    [],
  );

  return (
    <aside className={cn('research-sidebar', collapsed ? 'research-sidebar-collapsed' : 'research-sidebar-expanded')}>
      <Link to="/" className="research-brand" aria-label="Back to Alpha Engine homepage">
        <div className="research-brand-mark"><Orbit className="h-4 w-4" /></div>
        {!collapsed && (
          <div className="min-w-0">
            <div className="research-brand-name">Alpha Engine</div>
            <div className="research-brand-subtitle">Strategy Console</div>
          </div>
        )}
      </Link>

      {!collapsed && (
        <div className="research-bundle-card">
          <div className="flex items-center justify-between gap-2">
            <div className="research-bundle-label">Active evidence</div>
            {activeRun && <span className="rounded border px-1.5 py-0.5 text-[9px] font-bold uppercase">{activeRun.channel}</span>}
          </div>
          <div className="research-bundle-title">{activeRun?.title || bundle?.manifest.title || 'Loading bundle'}</div>
          <div className="research-bundle-meta">Cutoff {activeRun?.evidenceCutoff || bundle?.manifest.evidence_cutoff || 'not declared'}</div>
          {activeRun && <div className="mt-1 truncate text-[10px] text-muted-foreground">{formatEvidenceLabel(activeRun.publicationStatus)}</div>}
        </div>
      )}

      <nav className="research-nav" aria-label="Strategy console navigation">
        {groups.map((group) => (
          <section key={group.title} className="research-nav-group">
            {!collapsed && <h2>{group.title}</h2>}
            <div className="space-y-1">
              {group.items.map((item) => {
                const Icon = item.icon;
                const navPath = `/${item.path}`;
                const active = location.pathname === navPath || location.pathname.startsWith(`${navPath}/`);
                return (
                  <NavLink
                    key={item.path}
                    to={navPath}
                    className={cn('research-nav-link', active && 'research-nav-link-active')}
                    title={collapsed ? item.label : undefined}
                    aria-current={active ? 'page' : undefined}
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    {!collapsed && <span className="truncate">{item.label}</span>}
                  </NavLink>
                );
              })}
            </div>
          </section>
        ))}
      </nav>

      <div className="research-sidebar-footer">
        <button
          type="button"
          onClick={() => setCollapsed(!collapsed)}
          className="research-sidebar-action justify-center"
          aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
        >
          {collapsed
            ? <ChevronsRight className="h-4 w-4" />
            : <><ChevronsLeft className="h-4 w-4" /><span>Collapse rail</span></>}
        </button>

        {!collapsed && (
          <div className="research-version">v{import.meta.env.VITE_APP_VERSION || 'dev'} · {import.meta.env.VITE_GIT_COMMIT_SHA || 'unknown'}</div>
        )}
      </div>
    </aside>
  );
}
