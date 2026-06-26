/**
 * Typed API client with error normalisation, timeout, and abort support.
 *
 * Uses the existing `apiFetch` under the hood so auth-header injection and
 * 401 handling remain centralised. Returns parsed, typed payloads on success
 * and throws `ApiError` on any non-2xx response or network failure.
 *
 * Usage:
 *   import { apiClient } from '@/lib/api-client';
 *   const data = await apiClient.get<ModelListResponse>('/api/models');
 */

import { apiFetch } from './api';
import { ApiError } from './api-types';

// ---------------------------------------------------------------------------
// Request options
// ---------------------------------------------------------------------------

export interface ApiRequestOptions {
  /** Request timeout in milliseconds (default 30 000). */
  timeout?: number;
  /** AbortSignal for external cancellation. */
  signal?: AbortSignal;
  /** Query-string parameters — appended to the URL. */
  params?: Record<string, string | number | boolean | undefined>;
  /** Extra fetch init fields forwarded to `apiFetch`. */
  init?: Omit<RequestInit, 'method' | 'body' | 'signal'>;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildUrl(
  path: string,
  params?: Record<string, string | number | boolean | undefined>,
): string {
  if (!params) return path;
  const url = new URL(path, window.location.origin);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) {
      url.searchParams.set(key, String(value));
    }
  }
  return url.pathname + url.search;
}

// ---------------------------------------------------------------------------
// ApiClient
// ---------------------------------------------------------------------------

class ApiClient {
  /** Default timeout for all requests (ms). */
  private _defaultTimeout = 30_000;

  setDefaultTimeout(ms: number): void {
    this._defaultTimeout = ms;
  }

  // -- HTTP verbs -----------------------------------------------------------

  async get<T>(
    path: string,
    options?: ApiRequestOptions,
  ): Promise<T> {
    return this.request<T>('GET', path, options);
  }

  async post<T>(
    path: string,
    body?: unknown,
    options?: ApiRequestOptions,
  ): Promise<T> {
    return this.request<T>('POST', path, options, body);
  }

  async put<T>(
    path: string,
    body?: unknown,
    options?: ApiRequestOptions,
  ): Promise<T> {
    return this.request<T>('PUT', path, options, body);
  }

  async del<T>(
    path: string,
    options?: ApiRequestOptions,
  ): Promise<T> {
    return this.request<T>('DELETE', path, options);
  }

  // -- Core request ---------------------------------------------------------

  async request<T>(
    method: string,
    path: string,
    options?: ApiRequestOptions,
    body?: unknown,
  ): Promise<T> {
    const timeout = options?.timeout ?? this._defaultTimeout;
    const url = buildUrl(path, options?.params);

    // Merge caller signal with our own timeout abort.
    const controller = new AbortController();
    const callerSignal = options?.signal;

    // If the caller already aborted, propagate immediately.
    if (callerSignal?.aborted) {
      throw new ApiError(0, 'Request aborted');
    }

    // Forward caller abort to our controller with a brief debounce to
    // tolerate React StrictMode double-mount (which aborts and re-fires
    // within the same microtask).  If the caller re-attaches a fresh
    // signal within 200ms we ignore the transient abort.
    let abortTimer: ReturnType<typeof setTimeout> | null = null;
    callerSignal?.addEventListener('abort', () => {
      // Defer the actual abort briefly; if a fresh request with a
      // new signal arrives before the timer fires, this one is stale.
      abortTimer = setTimeout(() => controller.abort(), 200);
    }, { once: true });

    // Set up timeout.
    const timeoutId = setTimeout(() => controller.abort(), timeout);

    try {
      const fetchInit: RequestInit = {
        method,
        signal: controller.signal,
        ...options?.init,
      };

      if (body !== undefined) {
        fetchInit.headers = {
          'Content-Type': 'application/json',
          ...(options?.init?.headers as Record<string, string>),
        };
        fetchInit.body = JSON.stringify(body);
      }

      const resp = await apiFetch(url, fetchInit);

      if (!resp.ok) {
        // Normalise error body — FastAPI returns { detail: ... }.
        let message = `HTTP ${resp.status}`;
        let detail: unknown;
        try {
          const errBody = await resp.json();
          detail = errBody?.detail ?? errBody;
          if (typeof detail === 'string') {
            message = detail;
          } else if (Array.isArray(detail)) {
            // Handle FastAPI 422 array details
            message = detail.map(d => d.msg || JSON.stringify(d)).join(', ');
          } else if (detail && typeof detail === 'object') {
            if ('message' in detail) message = String((detail as { message: string }).message);
            else if ('error' in detail) message = String((detail as { error: string }).error);
          }
        } catch {
          // Body not JSON — fall back to status text.
          message = resp.statusText || message;
        }
        throw new ApiError(resp.status, message, detail);
      }

      // Handle 204 No Content or empty responses safely
      if (resp.status === 204) return {} as T;
      const text = await resp.text();
      if (!text) return {} as T;
      
      const json: T = JSON.parse(text);
      return json;
    } catch (err) {
      if (err instanceof ApiError) throw err;
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw new ApiError(0, 'Request timed out or was aborted');
      }
      throw new ApiError(0, (err as Error).message ?? 'Network error');
    } finally {
      clearTimeout(timeoutId);
      if (abortTimer) clearTimeout(abortTimer);
    }
  }
}

// ---------------------------------------------------------------------------
// Singleton — re-uses the auth-header and 401 handler registered in api.ts
// ---------------------------------------------------------------------------

export const apiClient = new ApiClient();
