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
  transientMessageQueue: [],
  announcement: null,
  announcement_updated_at: null,
  legal_first_name: null,
  legal_middle_name: null,
  legal_last_name: null,

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

  // ── Session Actions ──────────────────────────────────────────────────────
  setSession: (sessionData) => set({
    session_id: sessionData.session_id,
    heir_id: sessionData.heir_id,
    userRole: sessionData.user_role || 'HEIR',
    userStatus: sessionData.user_status,
    assets: sessionData.assets,
    isPaused: sessionData.is_paused,
    isDeadlocked: sessionData.is_deadlocked,
    is_hitl_suspended: sessionData.is_hitl_suspended || false,
    isSubmitted: sessionData.is_submitted,
    isAuthenticated: sessionData.isAuthenticated ?? false,
    draft_version: sessionData.draft_version || 0,
    sessionStatus: sessionData.status,
    announcement: sessionData.announcement ?? null,
    announcement_updated_at: sessionData.announcement_updated_at ?? null,
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
      isAuthenticated: false,
    });
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