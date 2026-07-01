import { create } from 'zustand';

const API_BASE = '';

let draftTimer = null;

export const useMediationStore = create((set, get) => ({
  // ── State Variables ──────────────────────────────────────────────────────
  session_id: null,
  heir_id: null,
  userRole: null,        // 'ADMIN' | 'HEIR'
  userStatus: 'PENDING', // 'PENDING' | 'PROFILE_HOLD' | 'ACTIVE' | 'SUBMITTED' | 'ABSTAINED' | 'EXPIRED_NON_PARTICIPATING'
  assets: [],            // List of AssetSchema objects
  valuations: {},        // Map of asset_id -> { points: int, reasoning: str, is_reasoning_shared: bool }
  unallocatedPoints: 1000,
  messages: [],          // Chat history: { sender: 'heir'|'agent', text: str }
  audioChunks: [],       // WebSocket chat_reply_chunk frames waiting for playback
  isPaused: false,
  isDeadlocked: false,
  is_hitl_suspended: false,
  isAuthenticated: false,
  isSubmitted: false,
  draft_version: 0,
  critique_loopback_count: 0,
  sessionStatus: 'SETUP', // 'SETUP' | 'ACTIVE' | 'LOCKED' | 'FINALIZED'
  networkStatus: 'Disconnected', // 'Connected' | 'Reconnecting...' | 'Disconnected'
  openSupportRequests: [],
  latestSupportNotice: null,
  supportRefreshToken: 0,
  transientMessageQueue: [],
  announcement: null,
  announcement_updated_at: null,
  legal_first_name: null,
  legal_middle_name: null,
  legal_last_name: null,
  practiceCompletedAt: null,
  practiceRequired: false,
  simulationPublishedAt: null,

  // ── Invite Actions ───────────────────────────────────────────────────────
  checkInviteStatus: async (token) => {
    const res = await fetch(`${API_BASE}/api/invite/status/${encodeURIComponent(token)}`);
    if (!res.ok) throw new Error(`Invite status check failed: ${res.status}`);
    return res.json();
  },

  resumeSession: async (token) => {
    const res = await fetch(`${API_BASE}/api/invite/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    });
    if (!res.ok) throw new Error(`Session resumption failed: ${res.status}`);
    set({ isAuthenticated: true });
    await get().loadProfile();
  },

  // Re-hydrate a Heir's auth state from the estate_session cookie on a hard
  // refresh (DashboardGuard calls this whenever a heir lands on /dashboard
  // without isAuthenticated already set in memory). Mirrors the Admin
  // restore pattern in AdminDashboard.jsx (GET /api/auth/me, then
  // setSession) so the same cookie/JWT contract works for both roles —
  // and for a future federated login, since /api/auth/me and the cookie
  // it reads are already provider-agnostic.
  restoreHeirSession: async () => {
    const res = await fetch(`${API_BASE}/api/auth/me`, { credentials: 'same-origin' });
    if (!res.ok) throw new Error(`Session restore failed: ${res.status}`);
    const data = await res.json();
    if (data.role !== 'HEIR') throw new Error('Not a heir session');
    set({
      isAuthenticated: true,
      userRole: 'HEIR',
      session_id: data.session_id,
      heir_id: data.user_id,
    });
  },

  // ── Auth Actions ─────────────────────────────────────────────────────────
  // Returns { status: 'multiple_sessions', sessions: [...] } when the same
  // identifier/password matches heir records in more than one estate
  // session; caller must re-invoke with session_id set to disambiguate.
  heirPasswordLogin: async ({ identifier, password, session_id = null }) => {
    const payload = { identifier, password };
    if (session_id) payload.session_id = session_id;
    const res = await fetch(`${API_BASE}/api/auth/heir-login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      throw new Error(errorData.detail || `Sign in failed: ${res.status}`);
    }
    const data = await res.json();
    if (data.status === 'multiple_sessions') {
      return data;
    }
    set({
      isAuthenticated: true,
      userRole: data.role || 'HEIR',
      session_id: data.session_id,
      heir_id: data.heir_id,
      userStatus: data.user_status,
    });
    await get().loadProfile();
    await get().loadAssets();
    return data;
  },

  // List sibling estate sessions sharing this heir's email/username, for
  // the in-dashboard "Switch Estate" picker.
  loadHeirSessions: async () => {
    const res = await fetch(`${API_BASE}/api/auth/heir-sessions`);
    if (!res.ok) throw new Error(`Load estate sessions failed: ${res.status}`);
    const data = await res.json();
    return data.sessions || [];
  },

  // Re-issues the JWT cookie scoped to a sibling estate session without
  // re-entering a password, then refreshes profile/session state.
  switchHeirSession: async (sessionId) => {
    const res = await fetch(`${API_BASE}/api/auth/heir-switch-session`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId }),
    });
    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      throw new Error(errorData.detail || `Switch estate failed: ${res.status}`);
    }
    const data = await res.json();
    set({
      isAuthenticated: true,
      userRole: data.role || 'HEIR',
      session_id: data.session_id,
      heir_id: data.heir_id,
      userStatus: data.user_status,
      // Clear session-scoped state so stale data from the previous estate
      // doesn't briefly render before the new session's data loads.
      assets: [],
      valuations: {},
      messages: [],
      announcement: null,
      announcement_updated_at: null,
    });
    await get().loadProfile();
    return data;
  },

  // Shared logout action for both Admin and Heir (role-agnostic: the
  // backend cookie/session is not tied to how the user authenticated).
  // Single choke point so that a future federated/SSO login (Google,
  // Apple, generic OIDC — see user_journeys.md §0.5) only needs to teach
  // *this* action about redirecting to the IdP's end-session endpoint,
  // rather than every caller that currently hand-rolls a logout fetch.
  logout: async () => {
    try {
      await fetch(`${API_BASE}/api/auth/logout`, {
        method: 'POST',
        credentials: 'same-origin',
      });
    } catch (err) {
      console.error('Failed to clear auth cookie', err);
    } finally {
      get().setSession({ isAuthenticated: false, user_role: null, session_id: null });
    }
  },

  // ── Session Actions ──────────────────────────────────────────────────────
  setSession: (sessionData) => set((state) => {
    const has = (key) => Object.prototype.hasOwnProperty.call(sessionData, key);
    const pick = (key, fallback) => (has(key) ? sessionData[key] : fallback);
    const isLoggingOut = sessionData.isAuthenticated === false;
    const nextRole = isLoggingOut
      ? null
      : pick('user_role', pick('userRole', state.userRole || 'HEIR'));

    return {
      session_id: isLoggingOut ? null : pick('session_id', state.session_id),
      heir_id: isLoggingOut ? null : pick('heir_id', state.heir_id),
      userRole: nextRole,
      userStatus: isLoggingOut ? 'PENDING' : pick('user_status', state.userStatus),
      assets: isLoggingOut ? [] : pick('assets', state.assets),
      isPaused: isLoggingOut ? false : pick('is_paused', state.isPaused),
      isDeadlocked: isLoggingOut ? false : pick('is_deadlocked', state.isDeadlocked),
      is_hitl_suspended: isLoggingOut ? false : pick('is_hitl_suspended', state.is_hitl_suspended),
      isSubmitted: isLoggingOut ? false : pick('is_submitted', state.isSubmitted),
      isAuthenticated: pick('isAuthenticated', state.isAuthenticated),
      draft_version: isLoggingOut ? 0 : pick('draft_version', state.draft_version),
      sessionStatus: isLoggingOut ? 'SETUP' : pick('status', state.sessionStatus),
      announcement: isLoggingOut ? null : pick('announcement', state.announcement),
      announcement_updated_at: isLoggingOut ? null : pick('announcement_updated_at', state.announcement_updated_at),
      practiceCompletedAt: isLoggingOut ? null : pick('practice_completed_at', state.practiceCompletedAt),
      practiceRequired: isLoggingOut ? false : pick('practice_required', state.practiceRequired),
      simulationPublishedAt: isLoggingOut ? null : pick('simulation_published_at', state.simulationPublishedAt),
    };
  }),

  // ── Valuation Actions ────────────────────────────────────────────────────
  updateValuation: (assetId, points) => {
    const currentVal = get().valuations[assetId] || { points: 0, reasoning: '', is_reasoning_shared: false };
    const diff = points - currentVal.points;

    if (get().isSubmitted || get().unallocatedPoints - diff < 0) return;

    set((state) => ({
      valuations: {
        ...state.valuations,
        [assetId]: { ...currentVal, points },
      },
      unallocatedPoints: state.unallocatedPoints - diff,
    }));
  },

  updateValuationText: (assetId, reasoning, isReasoningShared) => {
    if (get().isSubmitted) return;
    set((state) => {
      const currentVal = state.valuations[assetId] || { points: 0, reasoning: '', is_reasoning_shared: false };
      return {
        valuations: {
          ...state.valuations,
          [assetId]: { ...currentVal, reasoning, is_reasoning_shared: isReasoningShared },
        },
      };
    });
  },

  // Debounced bulk draft sync — 1.5s debounce
  saveDraft: async () => {
    const state = get();
    if (!state.session_id || !state.heir_id) return;

    if (draftTimer) clearTimeout(draftTimer);

    draftTimer = setTimeout(async () => {
      const current = get();
      const url = `${API_BASE}/api/sessions/${current.session_id}/valuations/draft`;

      // Build the valuations array from the map
      const valuationsArray = Object.entries(current.valuations).map(([assetId, val]) => ({
        asset_id: assetId,
        points: val.points,
        reasoning: val.reasoning,
        is_reasoning_shared: val.is_reasoning_shared,
      }));

      try {
        const res = await fetch(url, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            draft_version: current.draft_version,
            valuations: valuationsArray,
          }),
        });
        if (res.status === 409) {
          // Conflict — reject the old draft version, server state wins
          const serverState = await res.json();
          if (serverState.valuations) {
            const newValuations = {};
            let pointsUsed = 0;
            for (const v of serverState.valuations) {
              newValuations[v.asset_id] = {
                points: v.points || 0,
                reasoning: v.reasoning || '',
                is_reasoning_shared: v.is_reasoning_shared || false,
              };
              pointsUsed += v.points || 0;
            }
            set({
              valuations: newValuations,
              unallocatedPoints: 1000 - pointsUsed,
              draft_version: serverState.draft_version || current.draft_version,
            });
          }
        } else if (res.ok) {
          const data = await res.json();
          set({ draft_version: data.draft_version || current.draft_version + 1 });
        }
      } catch {
        // If offline, the draft stays in store; resync happens on reconnect
      }
    }, 1500);
  },

  submitValuations: async () => {
    const state = get();
    const url = `${API_BASE}/api/sessions/${state.session_id}/valuations/submit`;

    const valuationsArray = Object.entries(state.valuations).map(([assetId, val]) => ({
      asset_id: assetId,
      points: val.points,
      reasoning: val.reasoning,
      is_reasoning_shared: val.is_reasoning_shared,
    }));

    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ valuations: valuationsArray }),
    });
    if (!res.ok) throw new Error(`Submit failed: ${res.status}`);
    set({ isSubmitted: true });
  },

  loadValuations: async () => {
    const state = get();
    const url = `${API_BASE}/api/sessions/${state.session_id}/heirs/${state.heir_id}/valuations`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Load valuations failed: ${res.status}`);
    const data = await res.json();

    const newValuations = {};
    let pointsUsed = 0;
    for (const v of data.valuations || data) {
      newValuations[v.asset_id] = {
        points: v.points || 0,
        reasoning: v.reasoning || '',
        is_reasoning_shared: v.is_reasoning_shared || false,
      };
      pointsUsed += v.points || 0;
    }
    set({
      valuations: newValuations,
      unallocatedPoints: 1000 - pointsUsed,
    });
  },

  loadAssets: async () => {
    const state = get();
    if (!state.session_id) return;
    set({ assetsLoading: true, assetsError: null });
    try {
      const res = await fetch(`${API_BASE}/api/sessions/${state.session_id}/assets`);
      if (!res.ok) throw new Error(`Load assets failed: ${res.status}`);
      const assets = await res.json();
      set({
        assets: Array.isArray(assets) ? assets : [],
        assetsLoadedForSession: state.session_id,
        assetsLoading: false,
        assetsError: null,
      });
    } catch (err) {
      set({
        assetsLoading: false,
        assetsError: err.message || 'Failed to load assets',
      });
      throw err;
    }
  },

  // ── Chat Actions ─────────────────────────────────────────────────────────
  loadChatHistory: async () => {
    const state = get();
    const url = `${API_BASE}/api/sessions/${state.session_id}/heirs/${state.heir_id}/chat`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Load chat failed: ${res.status}`);
    const data = await res.json();
    const messages = (data.chat_history || data).map((msg) => ({
      sender: msg.sender,
      text: msg.scrubbed_text || msg.text,
    }));
    set({ messages });
  },

  addMessage: (msg) => set((state) => ({
    messages: [...state.messages, msg],
  })),

  enqueueAudioChunk: (chunk) => set((state) => ({
    audioChunks: [...state.audioChunks, chunk],
  })),

  clearAudioChunks: () => set({ audioChunks: [] }),

  recordSupportAlert: (notice) => set((state) => ({
    openSupportRequests: [
      notice,
      ...state.openSupportRequests.filter((ticket) => ticket.ticket_id !== notice.ticket_id),
    ],
    supportRefreshToken: (state.supportRefreshToken || 0) + 1,
  })),

  recordSupportReply: (notice) => set((state) => ({
    latestSupportNotice: notice,
    supportRefreshToken: (state.supportRefreshToken || 0) + 1,
  })),

  clearLatestSupportNotice: () => set({ latestSupportNotice: null }),

  // ── Network Actions ──────────────────────────────────────────────────────
  setNetworkStatus: (status) => set({ networkStatus: status }),

  enqueueOfflineMessage: (msg) => set((state) => ({
    transientMessageQueue: [...state.transientMessageQueue, msg],
  })),

  flushOfflineQueue: async (wsSend) => {
    const queue = get().transientMessageQueue;
    for (const msg of queue) {
      wsSend(msg);
    }
    set({ transientMessageQueue: [] });
  },

  // ── Profile Actions ──────────────────────────────────────────────────────
  loadProfile: async () => {
    const res = await fetch(`${API_BASE}/api/heirs/me`);
    if (!res.ok) throw new Error(`Load profile failed: ${res.status}`);
    const data = await res.json();
    set({
      heir_id: data.heir_id || data.id,
      session_id: data.session_id,
      legal_first_name: data.legal_first_name,
      legal_middle_name: data.legal_middle_name,
      legal_last_name: data.legal_last_name,
      userRole: 'HEIR',
      userStatus: data.user_status || data.status,
      isSubmitted: data.is_submitted || false,
      is_hitl_suspended: data.is_hitl_suspended || false,
      draft_version: data.draft_version || 0,
      practiceCompletedAt: data.practice_completed_at || null,
    });
  },

  loadSessionDetails: async () => {
    const state = get();
    if (!state.session_id) return;
    const res = await fetch(`${API_BASE}/api/sessions/${state.session_id}`);
    if (!res.ok) throw new Error(`Load session details failed: ${res.status}`);
    const data = await res.json();
    set({
      announcement: data.announcement || null,
      announcement_updated_at: data.announcement_updated_at || null,
      isPaused: data.is_paused || false,
      isDeadlocked: data.is_deadlocked || false,
      sessionStatus: data.status,
      practiceRequired: data.practice_required || false,
      simulationPublishedAt: data.simulation_published_at || null,
    });
  },

  updateProfile: async (profileData) => {
    const res = await fetch(`${API_BASE}/api/heirs/me/profile`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(profileData),
    });
    if (!res.ok) throw new Error(`Update profile failed: ${res.status}`);
    const data = await res.json();
    set({
      userStatus: data.user_status || data.status,
      identity_verified: data.identity_verified,
    });
  },

  // ── Abstention Actions ───────────────────────────────────────────────────
  abstainSession: async (legalName) => {
    const res = await fetch(`${API_BASE}/api/heirs/me/abstain`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ legal_name_signature: legalName }),
    });
    if (!res.ok) throw new Error(`Abstain failed: ${res.status}`);
    set({ userStatus: 'ABSTAINED' });
  },

  downloadWaiverReceipt: async () => {
    const res = await fetch(`${API_BASE}/api/heirs/me/abstain/receipt`);
    if (!res.ok) throw new Error(`Download waiver failed: ${res.status}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'abstention-waiver-receipt.pdf';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  // ── GDPR / Account Actions ───────────────────────────────────────────────
  deleteAccount: async () => {
    const res = await fetch(`${API_BASE}/api/heirs/me`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`Delete failed: ${res.status}`);
    set({
      session_id: null,
      heir_id: null,
      assets: [],
      valuations: {},
      messages: [],
      audioChunks: [],
      isAuthenticated: false,
    });
  },

  // ── Auto-Balance Points ─────────────────────────────────────────────────
  autoBalancePoints: () => {
    const state = get();
    if (state.isSubmitted) return;

    const entries = Object.entries(state.valuations);
    // Division-by-zero guard: abort if no points allocated
    const totalPoints = entries.reduce((sum, [, v]) => sum + (v.points || 0), 0);
    if (totalPoints === 0) return;

    const newValuations = {};
    // Proportional scaling to sum to exactly 1000
    let scaledSum = 0;
    const scaled = entries.map(([assetId, v]) => {
      const raw = Math.round((v.points / totalPoints) * 1000);
      newValuations[assetId] = { ...v, points: raw };
      scaledSum += raw;
      return { assetId, raw };
    });

    // Adjust rounding remainder: add or subtract to highest-point asset
    const remainder = 1000 - scaledSum;
    if (remainder !== 0) {
      // Find the asset with the most points to absorb the remainder
      let maxAssetId = entries[0][0];
      let maxPoints = 0;
      for (const [assetId, v] of entries) {
        if ((v.points || 0) > maxPoints) {
          maxPoints = v.points || 0;
          maxAssetId = assetId;
        }
      }
      newValuations[maxAssetId] = {
        ...newValuations[maxAssetId],
        points: (newValuations[maxAssetId].points || 0) + remainder,
      };
    }

    set({ valuations: newValuations, unallocatedPoints: 0 });
  },

  // ── Keepsake Actions ─────────────────────────────────────────────────────
  emailKeepsake: async (heirId = null) => {
    const state = get();
    const res = await fetch(`${API_BASE}/api/sessions/${state.session_id}/keepsake/email`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ heir_id: heirId }),
    });
    if (!res.ok) throw new Error(`Email keepsake failed: ${res.status}`);
  },
}));
