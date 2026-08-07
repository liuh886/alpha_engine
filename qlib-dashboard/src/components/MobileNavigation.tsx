import { useEffect, useMemo, useState } from 'react';
import { Menu, X } from 'lucide-react';
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
    return () => { document.body.style.overflow = previous; };
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
      >
        <Menu className="h-4 w-4" />
      </Button>

      {open && (
        <div className="fixed inset-0 z-[80]" role="dialog" aria-modal="true" aria-label="Strategy navigation">
          <button
            type="button"
            className="absolute inset-0 bg-slate-950/45 backdrop-blur-[1px]"
            onClick={() => setOpen(false)}
            aria-label="Dismiss strategy navigation"
          />
          <div className="absolute inset-y-0 left-0 flex w-[min(86vw,340px)] flex-col border-r bg-card shadow-2xl">
            <div className="flex h-16 items-center justify-between border-b px-4">
              <Link to="/" onClick={() => setOpen(false)} aria-label="Back to Alpha Engine homepage">
                <p className="text-sm font-bold">Alpha Engine</p>
                <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-muted-foreground">Strategy Console</p>
              </Link>
              <Button type="button" variant="ghost" size="icon" onClick={() => setOpen(false)} aria-label="Close strategy navigation">
                <X className="h-4 w-4" />
              </Button>
            </div>
            <nav className="flex-1 space-y-5 overflow-y-auto p-3" aria-label="Mobile strategy console navigation">
              {groups.map((group) => (
                <section key={group.title}>
                  <h2 className="mb-1.5 px-2 text-[9px] font-bold uppercase tracking-[0.18em] text-muted-foreground/75">{group.title}</h2>
                  <div className="space-y-1">
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
                          <Icon className="h-4 w-4 shrink-0" />
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
