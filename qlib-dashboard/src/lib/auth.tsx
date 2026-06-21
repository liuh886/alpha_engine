/**
 * Authentication context and hooks for the dashboard.
 * Provides login state, credentials management, session expiry, and 401 handling.
 *
 * The `status` field gives consumers an explicit three-state view:
 *   - `'loading'`         — session check in progress; UI should show a spinner
 *   - `'authenticated'`   — credentials verified; safe to render protected content
 *   - `'unauthenticated'` — no valid session; show login page
 */
import { createContext, useContext, useState, useCallback, useEffect, useRef, type ReactNode } from 'react';
import { setUnauthorizedHandler } from './api';

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

interface AuthState {
  /** Explicit session-check state — prefer this over `isAuthenticated` for UI branching. */
  status: AuthStatus;
  /** Convenience flag: `true` when status is `'authenticated'`. */
  isAuthenticated: boolean;
  username: string;
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => void;
  authHeader: () => string | null;
}

const AuthContext = createContext<AuthState | null>(null);

/**
 * Encode credentials for HTTP Basic Auth.
 */
function encodeBasicAuth(username: string, password: string): string {
  return `Basic ${btoa(`${username}:${password}`)}`;
}

/**
 * Store credentials in sessionStorage (cleared on tab close).
 */
function storeCredentials(username: string, password: string): void {
  sessionStorage.setItem('auth_user', username);
  sessionStorage.setItem('auth_pass', btoa(password));
}

function clearCredentials(): void {
  sessionStorage.removeItem('auth_user');
  sessionStorage.removeItem('auth_pass');
}

function getStoredCredentials(): { username: string; password: string } | null {
  const user = sessionStorage.getItem('auth_user');
  const passB64 = sessionStorage.getItem('auth_pass');
  if (!user || !passB64) return null;
  try {
    return { username: user, password: atob(passB64) };
  } catch {
    return null;
  }
}

/**
 * Compute the initial status synchronously so we avoid a flash of the login
 * page when stored credentials exist but haven't been verified yet.
 */
function computeInitialStatus(): AuthStatus {
  return getStoredCredentials() ? 'loading' : 'unauthenticated';
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>(computeInitialStatus);
  const [username, setUsername] = useState('');
  const [credentials, setCredentials] = useState<{ username: string; password: string } | null>(null);

  // Guard against rapid-fire 401 handling (e.g. multiple concurrent requests).
  const lastUnauthorizedRef = useRef(0);

  // Try to restore session on mount
  useEffect(() => {
    const stored = getStoredCredentials();
    if (!stored) {
      // No stored credentials — already handled by computeInitialStatus.
      return;
    }

    // Verify credentials are still valid
    fetch('/api/system/me', {
      headers: { Authorization: encodeBasicAuth(stored.username, stored.password) },
    })
      .then((r) => {
        if (r.ok) {
          setStatus('authenticated');
          setUsername(stored.username);
          setCredentials(stored);
        } else {
          clearCredentials();
          setStatus('unauthenticated');
        }
      })
      .catch(() => {
        // Server might not be running — keep credentials for retry
        setStatus('authenticated');
        setUsername(stored.username);
        setCredentials(stored);
      });
  }, []);

  // Register 401 handler — fires when apiFetch receives a 401.
  // Debounced to 1 s so concurrent 401s don't thrash state or cause
  // re-render cascades that look like reload loops.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      const now = Date.now();
      if (now - lastUnauthorizedRef.current < 1000) return;
      lastUnauthorizedRef.current = now;

      setStatus('unauthenticated');
      setUsername('');
      setCredentials(null);
      clearCredentials();
    });
  }, []);

  const login = useCallback(async (user: string, pass: string): Promise<boolean> => {
    try {
      const resp = await fetch('/api/system/me', {
        headers: { Authorization: encodeBasicAuth(user, pass) },
      });
      if (resp.ok) {
        setStatus('authenticated');
        setUsername(user);
        setCredentials({ username: user, password: pass });
        storeCredentials(user, pass);
        return true;
      }
      return false;
    } catch {
      return false;
    }
  }, []);

  const logout = useCallback(() => {
    setStatus('unauthenticated');
    setUsername('');
    setCredentials(null);
    clearCredentials();
  }, []);

  const authHeader = useCallback((): string | null => {
    if (!credentials) return null;
    return encodeBasicAuth(credentials.username, credentials.password);
  }, [credentials]);

  const isAuthenticated = status === 'authenticated';

  return (
    <AuthContext.Provider value={{ status, isAuthenticated, username, login, logout, authHeader }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
