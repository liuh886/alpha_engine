import { useEffect, useMemo, useState } from 'react';
import { Menu, Orbit, X } from 'lucide-react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { groupRoutes } from '@/routes';

export function MobileNavigation() {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const groups = useMemo(
    () => Array.from(groupRoutes()).map(([title, items]) => ({ title, items })),
    [],
  );

  useEffect(() => setOpen(false), [location.pathname]);
  useEffect(() => {
    if (!open) return undefined;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [open]);

  return (
    <div className="md:hidden">
      <Button
        type="button"
        variant="outline"
        size="icon"
        className="h-9 w-9"
        onClick={() => setOpen(true)}
        aria-label="Open strategy navigation"
        aria-expanded={open}
        aria-controls="mobile-strategy-navigation"
      >
        <Menu className="h-4 w-4" aria-hidden="true" />
      </Button>

      {open && (
        <div className="fixed inset-0 z-[60]" role="dialog" aria-modal="true" aria-label="Strategy navigation">
          <button
            type="button"
            className="absolute inset-0 bg-black/60"
            onClick={() => setOpen(false)}
            aria-label="Dismiss strategy navigation"
          />
          <div
            id="mobile-strategy-navigation"
            className="research-mobile-drawer absolute left-0 top-0 flex h-[100dvh] w-[min(86vw,320px)] flex-col border-r bg-card"
            style={{
              paddingTop: 'env(safe-area-inset-top)',
              paddingBottom: 'env(safe-area-inset-bottom)',
              paddingLeft: 'env(safe-area-inset-left)',
              boxShadow: 'var(--shadow-popover)',
            }}
          >
            <div className="flex min-h-[60px] items-center justify-between border-b px-4">
              <Link to="/app" className="flex items-center gap-2.5" onClick={() => setOpen(false)} aria-label="Open daily research">
                <span className="research-brand-mark"><Orbit className="h-4 w-4" aria-hidden="true" /></span>
                <span>
                  <span className="block text-[13px] font-semibold leading-5">Alpha Engine</span>
                </span>
              </Link>
              <Button type="button" variant="ghost" size="icon" onClick={() => setOpen(false)} aria-label="Close strategy navigation">
                <X className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
            <nav className="min-h-0 flex-1 space-y-5 overflow-y-auto overscroll-contain p-3" aria-label="Mobile strategy console navigation">
              {groups.map((group) => (
                <section key={group.title} className="research-nav-group">
                  <p className="research-nav-group-label">{group.title}</p>
                  <div className="space-y-0.5">
                    {group.items.map((item) => {
                      const Icon = item.icon;
                      const target = `/${item.path}`;
                      const active = location.pathname === target || location.pathname.startsWith(`${target}/`);
                      return (
                        <NavLink
                          key={item.path}
                          to={target}
                          className={cn('research-nav-link', active && 'research-nav-link-active')}
                          aria-current={active ? 'page' : undefined}
                        >
                          <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                          <span>{item.label}</span>
                        </NavLink>
                      );
                    })}
                  </div>
                </section>
              ))}
            </nav>
          </div>
        </div>
      )}
    </div>
  );
}
