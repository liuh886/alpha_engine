import { NavLink, useLocation } from 'react-router-dom';
import { routes } from '@/routes';
import { cn } from '@/lib/utils';

const TAB_PATHS = ['app', 'strategies', 'research', 'data', 'system'] as const;

/**
 * Commercial bottom tab bar for handset viewports. Renders the five primary
 * destinations with 56px touch targets, active pill indicator and safe-area
 * padding; hidden on md+ where the sidebar owns navigation.
 */
export function MobileTabBar() {
  const location = useLocation();
  const tabs = TAB_PATHS.map((path) => routes.find((route) => route.path === path)).filter(
    (route): route is NonNullable<typeof route> => Boolean(route),
  );

  return (
    <nav
      aria-label="Primary"
      className="fixed inset-x-0 bottom-0 z-30 border-t bg-card/95 backdrop-blur md:hidden"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      <div className="grid grid-cols-5" role="tablist" aria-orientation="horizontal">
        {tabs.map((tab) => {
          const target = `/${tab.path}`;
          const active =
            location.pathname === target || location.pathname.startsWith(`${target}/`);
          const Icon = tab.icon;
          return (
            <NavLink
              key={tab.path}
              to={target}
              role="tab"
              aria-selected={active}
              aria-label={tab.title}
              className={cn(
                'flex min-h-[56px] flex-col items-center justify-center gap-1 text-[10px] font-semibold transition-colors',
                active ? 'text-primary' : 'text-muted-foreground hover:text-foreground',
              )}
            >
              <span
                className={cn(
                  'flex h-8 w-16 items-center justify-center rounded-full transition-colors',
                  active && 'bg-primary/10',
                )}
              >
                <Icon className="h-5 w-5" aria-hidden="true" />
              </span>
              <span className="leading-none">{tab.label}</span>
            </NavLink>
          );
        })}
      </div>
    </nav>
  );
}
