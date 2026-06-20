/**
 * Route-level authentication guard.
 *
 * Wraps protected content so it is never rendered before the initial session
 * check resolves.  On session expiry (401) the guard automatically surfaces
 * the login page while preserving the browser URL — after re-authenticating
 * the user lands back on the page they were viewing.
 */
import type { ReactNode } from 'react';
import { Loader2 } from 'lucide-react';
import { useAuth } from '@/lib/auth';
import { LoginPage } from '@/components/LoginPage';

interface AuthGuardProps {
  children: ReactNode;
}

export function AuthGuard({ children }: AuthGuardProps) {
  const { status } = useAuth();

  if (status === 'loading') {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <Loader2 className="h-6 w-6 animate-spin text-primary opacity-50" />
      </div>
    );
  }

  if (status === 'unauthenticated') {
    return <LoginPage />;
  }

  return <>{children}</>;
}
