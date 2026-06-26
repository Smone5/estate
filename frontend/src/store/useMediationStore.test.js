// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useMediationStore } from './useMediationStore';

describe('useMediationStore heirPasswordLogin', () => {
  beforeEach(() => {
    useMediationStore.setState({
      isAuthenticated: false,
      userRole: null,
      session_id: null,
      heir_id: null,
      userStatus: 'PENDING',
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('authenticates the heir and loads their profile', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          status: 'success',
          role: 'HEIR',
          session_id: 'session-1',
          heir_id: 'heir-1',
          user_status: 'ACTIVE',
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          id: 'heir-1',
          session_id: 'session-1',
          user_status: 'ACTIVE',
          legal_first_name: 'Alex',
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [],
      });

    await useMediationStore.getState().heirPasswordLogin({
      identifier: 'heir@example.com',
      password: 'heirpass123',
    });

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/auth/heir-login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        identifier: 'heir@example.com',
        password: 'heirpass123',
      }),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/heirs/me');
    expect(fetchMock).toHaveBeenNthCalledWith(3, '/api/sessions/session-1/assets');
    expect(useMediationStore.getState()).toMatchObject({
      isAuthenticated: true,
      userRole: 'HEIR',
      session_id: 'session-1',
      heir_id: 'heir-1',
      userStatus: 'ACTIVE',
      legal_first_name: 'Alex',
    });
  });

  it('surfaces the backend error and leaves the heir signed out', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ detail: 'Invalid credentials' }),
    });

    await expect(useMediationStore.getState().heirPasswordLogin({
      identifier: 'heir@example.com',
      password: 'wrong',
    })).rejects.toThrow('Invalid credentials');

    expect(useMediationStore.getState().isAuthenticated).toBe(false);
  });

  it('loads distributed assets for a finalized session', async () => {
    useMediationStore.setState({ session_id: 'session-final' });
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      json: async () => [
        {
          id: 'asset-1',
          title: 'Pocket Watch',
          status: 'DISTRIBUTED',
          allocated_to_id: 'heir-1',
        },
      ],
    });

    await useMediationStore.getState().loadAssets();

    expect(globalThis.fetch).toHaveBeenCalledWith('/api/sessions/session-final/assets');
    expect(useMediationStore.getState()).toMatchObject({
      assetsLoadedForSession: 'session-final',
      assetsLoading: false,
      assetsError: null,
      assets: [
        {
          id: 'asset-1',
          title: 'Pocket Watch',
          status: 'DISTRIBUTED',
          allocated_to_id: 'heir-1',
        },
      ],
    });
  });
});
