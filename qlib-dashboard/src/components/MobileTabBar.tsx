import { NavLink, useLocation } from 'react-router-dom';
import { routes } from '@/routes';
import { cn } from '@/lib/utils';
const TAB_PATHS = ['app', 'strategies', 'research', 'system'] as const;

export function MobileTabBar() {
  const location = useLocation();
  const tabs = TAB_PATHS.map(path => routes.find(route => route.path === path)).filter(
    (route): route is NonNullable<typeof route> => Boolean(route),
  );
  return <nav aria-label="Primary"
    className="research-mobile-tabbar fixed inset-x-0 bottom-0 z-30 border-t bg-card md:hidden"
    style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}>
    <div className="grid grid-cols-4" role="tablist" aria-orientation="horizontal">
      {tabs.map(tab => {
        const target = '/' + tab.path;
        const active = location.pathname === target || location.pathname.startsWith(target + '/');
        const Icon = tab.icon;
        return <NavLink key={tab.path} to={target} role="tab" aria-selected={active}
          aria-label={tab.title}
          className={cn('research-tab flex min-h-[56px] flex-col items-center justify-center gap-1 text-[10px] font-semibold tracking-[0.02em] transition-colors duration-150',
            active ? 'research-tab-active text-primary' : 'text-muted-foreground hover:text-foreground')}>
          <span className={cn('flex h-7 w-12 items-center justify-center rounded-md transition-colors duration-150',
            active ? 'bg-primary/10' : 'bg-transparent')}><Icon className="h-[18px] w-[18px]" aria-hidden="true" /></span>
          <span className="leading-none">{tab.label}</span>
        </NavLink>;
      })}
    </div>
  </nav>;
}
