import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useApi } from '@/lib/api';

const { mockGetToken } = vi.hoisted(() => ({
  mockGetToken: vi.fn((): Promise<string | null> => Promise.resolve('mock-jwt-token')),
}));

vi.mock('@clerk/nextjs', () => ({
  useAuth: () => ({
    isSignedIn: true,
    isLoaded: true,
    userId: 'user_test_123',
    getToken: mockGetToken,
  }),
}));

// Mock fetch globally for API tests
const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

describe('useApi hook', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetToken.mockImplementation(() => Promise.resolve('mock-jwt-token'));
  });

  describe('syncUser', () => {
    it('calls POST /users/sync', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ status: 'exists', user_id: 'user_test_123' }),
      });

      const { result } = renderHook(() => useApi());
      const response = await result.current.syncUser();

      expect(response).toEqual({
        status: 'exists',
        user_id: 'user_test_123',
      });
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/users/sync'),
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });

  describe('get', () => {
    it('sends GET request with auth header', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ agents: [] }),
      });

      const { result } = renderHook(() => useApi());
      const response = await result.current.get('/agents');

      expect(response).toEqual({ agents: [] });
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/agents'),
        expect.objectContaining({
          method: 'GET',
          headers: expect.objectContaining({
            Authorization: 'Bearer mock-jwt-token',
          }),
        }),
      );
    });
  });

  describe('post', () => {
    it('sends POST request with body', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ status: 'ok' }),
      });

      const { result } = renderHook(() => useApi());
      const response = await result.current.post('/users/sync', {});

      expect(response).toHaveProperty('status');
    });
  });

  describe('error handling', () => {
    it('throws error when no token available', async () => {
      mockGetToken.mockImplementation(() => Promise.resolve(null));
      const { result } = renderHook(() => useApi());

      await expect(result.current.syncUser()).rejects.toThrow('No authentication token available');
    });

    it('throws error on non-ok response', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: () => Promise.resolve({ detail: 'Not found' }),
      });

      const { result } = renderHook(() => useApi());
      await expect(result.current.get('/nonexistent')).rejects.toThrow('Not found');
    });
  });
});
