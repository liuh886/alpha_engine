/**
 * Route-level authentication guard.
 *
 * Connected research mode remains protected by the backend session. Static and
 * local artifact modes are intentionally read-only and therefore bypass the
 * backend login wall.
 */
import type { ReactNode } from 'react';
import { Loader2 } from 'lucide-react';
import { useAuth } from '@/lib/auth';
import { LoginPage } from '@/components/LoginPage';
import { runtimeCapabilities } from '@/lib/runtime-capabilities';

interface AuthGuardProps {
  children: ReactNode;
}

export function AuthGuard({ children }: AuthGuardProps) {
  const { status } = useAuth();

  if (!runtimeCapabilities.requiresAuthentication) {
    return <>{children}</>;
  }

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
