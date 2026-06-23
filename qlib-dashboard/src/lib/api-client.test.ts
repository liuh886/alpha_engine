/**
 * Tests for ApiClient — error handling, timeout, abort, and HTTP verbs.
 *
 * We mock `@/lib/api` (apiFetch) so no real network calls are made.
 */

import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest';

// Mock the apiFetch dependency before importing the module under test.
vi.mock('./api', () => ({
  apiFetch: vi.fn(),
}));

import { apiFetch } from './api';
import { apiClient } from './api-client';
import { ApiError } from './api-types';

const mockApiFetch = apiFetch as Mock;

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(typeof body === 'string' ? body : JSON.stringify(body)),
    headers: new Headers({ 'Content-Type': 'application/json' }),
  } as unknown as Response;
}

describe('ApiClient', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiClient.setDefaultTimeout(30_000);
  });

  // -----------------------------------------------------------------------
  // Successful responses
  // -----------------------------------------------------------------------

  describe('successful responses', () => {
    it('GET returns parsed JSON on 200', async () => {
      const payload = { ok: true as const, data: 'hello' };
      mockApiFetch.mockResolvedValueOnce(jsonResponse(payload));

      const result = await apiClient.get<typeof payload>('/api/test');
      expect(result).toEqual(payload);
      expect(mockApiFetch).toHaveBeenCalledOnce();

      // Verify the fetch was called with GET method
      const [, init] = mockApiFetch.mock.calls[0];
      expect(init.method).toBe('GET');
    });

    it('POST sends JSON body', async () => {
      const payload = { ok: true as const, job_id: 'j-1' };
      mockApiFetch.mockResolvedValueOnce(jsonResponse(payload));

      const body = { name: 'test' };
      const result = await apiClient.post<typeof payload>('/api/jobs', body);
      expect(result).toEqual(payload);

      const [, init] = mockApiFetch.mock.calls[0];
      expect(init.method).toBe('POST');
      expect(init.body).toBe(JSON.stringify(body));
    });

    it('PUT sends JSON body', async () => {
      const payload = { ok: true };
      mockApiFetch.mockResolvedValueOnce(jsonResponse(payload));

      await apiClient.put('/api/resource', { id: 1 });
      const [, init] = mockApiFetch.mock.calls[0];
      expect(init.method).toBe('PUT');
    });

    it('DELETE sends no body', async () => {
      const payload = { ok: true };
      mockApiFetch.mockResolvedValueOnce(jsonResponse(payload));

      await apiClient.del('/api/resource');
      const [, init] = mockApiFetch.mock.calls[0];
      expect(init.method).toBe('DELETE');
    });
  });

  // -----------------------------------------------------------------------
  // Error responses
  // -----------------------------------------------------------------------

  describe('error responses', () => {
    it('throws ApiError with detail string on 400', async () => {
      const errBody = { detail: 'Bad request: missing field' };
      mockApiFetch.mockResolvedValueOnce(jsonResponse(errBody, 400));

      try {
        await apiClient.get('/api/bad');
        expect.fail('should have thrown');
      } catch (err) {
        expect(err).toBeInstanceOf(ApiError);
        expect(err).toMatchObject({
          status: 400,
          message: 'Bad request: missing field',
        });
      }
    });

    it('throws ApiError with object detail', async () => {
      const errBody = { detail: { message: 'Validation failed', code: 42 } };
      mockApiFetch.mockResolvedValueOnce(jsonResponse(errBody, 422));

      await expect(apiClient.get('/api/unprocessable')).rejects.toMatchObject({
        status: 422,
        message: 'Validation failed',
      });
    });

    it('falls back to status text when body is not JSON', async () => {
      const badResp = {
        ok: false,
        status: 502,
        statusText: 'Bad Gateway',
        json: () => Promise.reject(new Error('not json')),
        text: () => Promise.resolve('<html>502 Bad Gateway</html>'),
      } as unknown as Response;
      mockApiFetch.mockResolvedValueOnce(badResp);

      await expect(apiClient.get('/api/gateway')).rejects.toMatchObject({
        status: 502,
        message: 'Bad Gateway',
      });
    });

    it('uses HTTP status as message fallback', async () => {
      const badResp = {
        ok: false,
        status: 503,
        statusText: '',
        json: () => Promise.reject(new Error('nope')),
        text: () => Promise.resolve(''),
      } as unknown as Response;
      mockApiFetch.mockResolvedValueOnce(badResp);

      await expect(apiClient.get('/api/unavailable')).rejects.toMatchObject({
        status: 503,
        message: 'HTTP 503',
      });
    });
  });

  // -----------------------------------------------------------------------
  // Abort / Timeout
  // -----------------------------------------------------------------------

  describe('abort and timeout', () => {
    it('throws ApiError on AbortError from fetch', async () => {
      const abortErr = new DOMException('The operation was aborted', 'AbortError');
      mockApiFetch.mockRejectedValueOnce(abortErr);

      await expect(apiClient.get('/api/slow')).rejects.toMatchObject({
        status: 0,
        message: 'Request timed out or was aborted',
      });
    });

    it('throws ApiError when caller signal is already aborted', async () => {
      const controller = new AbortController();
      controller.abort();

      await expect(
        apiClient.get('/api/aborted', { signal: controller.signal }),
      ).rejects.toMatchObject({
        status: 0,
        message: 'Request aborted',
      });

      // apiFetch should not have been called at all
      expect(mockApiFetch).not.toHaveBeenCalled();
    });
  });

  // -----------------------------------------------------------------------
  // Query params
  // -----------------------------------------------------------------------

  describe('query parameters', () => {
    it('appends params to URL', async () => {
      const payload = { ok: true };
      mockApiFetch.mockResolvedValueOnce(jsonResponse(payload));

      await apiClient.get('/api/data', {
        params: { market: 'cn', limit: 10 },
      });

      const [url] = mockApiFetch.mock.calls[0];
      expect(url).toContain('market=cn');
      expect(url).toContain('limit=10');
    });

    it('skips undefined params', async () => {
      const payload = { ok: true };
      mockApiFetch.mockResolvedValueOnce(jsonResponse(payload));

      await apiClient.get('/api/data', {
        params: { market: 'cn', tag: undefined },
      });

      const [url] = mockApiFetch.mock.calls[0];
      expect(url).toContain('market=cn');
      expect(url).not.toContain('tag=');
    });
  });

  // -----------------------------------------------------------------------
  // Network errors
  // -----------------------------------------------------------------------

  describe('network errors', () => {
    it('wraps generic errors in ApiError', async () => {
      mockApiFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));

      await expect(apiClient.get('/api/down')).rejects.toMatchObject({
        status: 0,
      });
    });
  });
});
