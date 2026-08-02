import { NavLink, useLocation } from 'react-router-dom';
import {
  AlertTriangle,
  ChevronsLeft,
  ChevronsRight,
  FlaskConical,
  Orbit,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { cn } from '@/lib/utils';
import { apiFetch } from '@/lib/api';
import { runtimeCapabilities } from '@/lib/runtime-capabilities';
import { useGlobalStore } from '../store/globalStore';
import { groupRoutes } from '../routes';
import { useActiveResearchBundle } from '@/hooks/useActiveResearchBundle';

export function Sidebar() {
  const { sidebarCollapsed: collapsed, setSidebarCollapsed: setCollapsed, operatorMode, setOperatorMode } = useGlobalStore();
  const location = useLocation();
  const bundle = useActiveResearchBundle();
  const [panicConfirming, setPanicConfirming] = useState(false);
  const [panicPending, setPanicPending] = useState(false);

  const filteredGroups = useMemo(() => Array.from(groupRoutes())
    .map(([title, items]) => ({
      title,
      items: items.filter((route) => route.releaseLevel !== 'internal' || operatorMode),
    }))
    .filter((group) => group.items.length > 0), [operatorMode]);

  const handlePanicConfirm = async () => {
    if (!runtimeCapabilities.mutations) return;
    setPanicPending(true);
    try {
      await apiFetch('/api/system/panic', { method: 'POST' });
    } catch (error) {
      console.error('Panic failed:', error);
    } finally {
      setPanicPending(false);
      setPanicConfirming(false);
    }
  };

  return (
    <aside className={cn('research-sidebar', collapsed ? 'research-sidebar-collapsed' : 'research-sidebar-expanded')}>
      <div className="research-brand">
        <div className="research-brand-mark"><Orbit className="h-4 w-4" /></div>
        {!collapsed && (
          <div className="min-w-0">
            <div className="research-brand-name">Alpha Engine</div>
            <div className="research-brand-subtitle">Research Studio</div>
          </div>
        )}
      </div>

      {!collapsed && (
        <div className="research-bundle-card">
          <div className="research-bundle-label">Active evidence</div>
          <div className="research-bundle-title">{bundle?.manifest.title || 'Loading bundle'}</div>
          <div className="research-bundle-meta">Cutoff {bundle?.manifest.evidence_cutoff || 'not declared'}</div>
        </div>
      )}

      <nav className="research-nav" aria-label="Research studio navigation">
        {filteredGroups.map((group) => (
          <section key={group.title} className="research-nav-group">
            {!collapsed && <h2>{group.title}</h2>}
            <div className="space-y-1">
              {group.items.map((item) => {
                const Icon = item.icon;
                const navPath = item.path === '' ? '/' : `/${item.path}`;
                const active = item.path === ''
                  ? location.pathname === '/'
                  : location.pathname === navPath || location.pathname.startsWith(`${navPath}/`);
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
                    {!collapsed && item.releaseLevel === 'experimental' && <span className="research-nav-tag">Beta</span>}
                    {!collapsed && item.releaseLevel === 'internal' && <span className="research-nav-tag research-nav-tag-dev">Dev</span>}
                  </NavLink>
                );
              })}
            </div>
          </section>
        ))}
      </nav>

      <div className="research-sidebar-footer">
        {runtimeCapabilities.backendApi && !collapsed && (
          <button
            type="button"
            onClick={() => setOperatorMode(!operatorMode)}
            className={cn('research-sidebar-action', operatorMode && 'research-sidebar-action-active')}
          >
            <FlaskConical className="h-3.5 w-3.5" />
            <span>{operatorMode ? 'Developer tools visible' : 'Show developer tools'}</span>
          </button>
        )}

        <button
          type="button"
          onClick={() => setCollapsed(!collapsed)}
          className="research-sidebar-action justify-center"
          aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
        >
          {collapsed ? <ChevronsRight className="h-4 w-4" /> : <><ChevronsLeft className="h-4 w-4" /><span>Collapse rail</span></>}
        </button>

        {runtimeCapabilities.mutations && (operatorMode || location.pathname.startsWith('/system')) && (
          <div>
            {!panicConfirming ? (
              <button type="button" onClick={() => setPanicConfirming(true)} className="research-panic-button">
                <AlertTriangle className="h-4 w-4" />{!collapsed && <span>Emergency halt</span>}
              </button>
            ) : (
              <div className="research-panic-confirm">
                {!collapsed && <p>Halt every active job?</p>}
                <div className="flex gap-1">
                  <button onClick={handlePanicConfirm} disabled={panicPending}>{panicPending ? '…' : 'Halt'}</button>
                  <button onClick={() => setPanicConfirming(false)} disabled={panicPending}>Cancel</button>
                </div>
              </div>
            )}
          </div>
        )}

        {!collapsed && (
          <div className="research-version">v{import.meta.env.VITE_APP_VERSION || 'dev'} · {import.meta.env.VITE_GIT_COMMIT_SHA || 'unknown'}</div>
        )}
      </div>
    </aside>
  );
}
