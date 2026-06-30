# Estate Steward: Technical Frontend Specification (v4.1)

This specification defines the frontend codebase architecture, client-side routing, Zustand state management stores, TanStack Query integration, and WebSocket communications.

---

## 1. Frontend Tech Stack & Directory Structure

*   **Build Tool**: Vite (SPA)
*   **Framework**: React (Functional Components + Hooks)
*   **State Management**: Zustand
*   **Data Fetching**: TanStack Query (`@tanstack/react-query`)
*   **Routing**: React Router (or lightweight file-based router)
*   **WebSockets**: Native browser WebSocket client.

### 1.1 Recommended Directory Tree
```
frontend/
├── public/
├── src/
│   ├── assets/
│   ├── components/      # Reusable visual components (Cards, Banners, MicButton)
│   ├── hooks/           # Custom React hooks (useSpeech, useWebsocket)
│   ├── routes/          # Layout controllers (Invite, Dashboard, Admin)
│   ├── store/           # Zustand store files (useMediationStore)
│   ├── App.jsx          # Route mapping
│   ├── index.css        # Custom CSS variables & global layers
│   └── main.jsx
├── index.html
├── package.json
└── vite.config.js
```

---

## 2. Client-Side Routing & Access Control

The application implements three main client-side routes:

### 2.1 `/invite/:token`
*   **Access**: Public.
*   **Logic (GDPR & CCPA Consent Onboarding & Resumption)**: 
    1. **Status Check**: On page mount, the frontend issues a `GET /api/invite/status/{token}` request to check the invitation status.
       *   **If `used` is `true`**: The frontend hides the onboarding form and renders the **Session Resumption Card**. This card displays a welcome back message with the Heir's pre-registered name and a "Resume Mediation" button. Clicking this button triggers `POST /api/invite/login` with the token. On success, the backend sets the HTTP-only JWT session cookie, the frontend store updates `isAuthenticated = true`, and redirects the user to `/dashboard`.
       *   **If `used` is `false`**: The frontend renders the standard onboarding flow starting with the **Privacy and Consent Agreement Card** informing the user of data processing (detailing that raw chat and point inputs are encrypted at rest using AES-Fernet, and text is filtered through Microsoft Presidio before LLM processing).
    2. **Consent & Age Gate**: (Only if `used` is `false`) The page contains a mandatory checkbox confirming the user is 18+ or has guardian consent. The "Accept & Enter Workspace" button remains disabled until checked.
    3. **Consent Trigger**: (Only if `used` is `false`) If the user clicks "Accept & Enter Workspace", the frontend issues a `POST /api/invite/verify` request containing the complete payload:
       ```json
       {
         "token": "UUID",
         "consent_accepted": true,
         "age_verified": true,
         "legal_first_name": "string",
         "legal_middle_name": "string (optional)",
         "legal_last_name": "string",
         "relationship_to_decedent": "string",
         "date_of_birth": "YYYY-MM-DD"
       }
       ```
       The legal profile fields are pre-populated from the Executor's registration data and are editable during the consent flow if the Heir spots a typo. Sending them here allows the backend to persist any corrections in the same atomic transaction as the consent record.
    4. If verification succeeds, the backend sets the HTTP-only JWT session cookie, the frontend store updates `isAuthenticated = true`, and redirects the user to `/dashboard`.
    5. If verification fails, or if the user clicks "Decline & Exit", clears state and redirects to the `/opt-out` exit route.

### 2.2 `/login`
*   **Access**: Public.
*   **Logic (Heir password re-login)**:
    1. The form collects `identifier` (email or display name/username) and `password`, then issues `POST /api/auth/heir-login` (see Backend Spec §9.5).
    2. **Multi-session disambiguation**: Because the same identifier can belong to onboarded Heir records in more than one mediation session (e.g. the person is an heir to two different decedents, each session with its own password), a single `identifier`/`password` pair can validly match more than one session. If the response is `{"status": "multiple_sessions", "sessions": [...]}`, the frontend does **not** authenticate yet — it stores the candidate list and renders a **Choose an Estate** picker listing each session's `title`. Selecting one re-issues `POST /api/auth/heir-login` with `session_id` set to the chosen session's UUID.
    3. If the response is `{"status": "success", ...}` (either on the first attempt, when the identifier/password pair is unambiguous, or after the disambiguation retry), the frontend store updates `isAuthenticated = true`, `session_id`, `heir_id`, and `userStatus` from the response, then redirects to `/dashboard`.
    4. Any `401` response (no candidate's password verified, or no candidate remains in the chosen `session_id`) renders a generic "Invalid credentials" error — the endpoint never reveals which sessions or identifiers exist before the password is verified.

### 2.3 `/dashboard`
*   **Access**: Protected (requires JWT session cookie).
*   **Logic**:
    1. If not authenticated, redirects to `/`.
    2. Establishes the WebSocket session connection `ws://<host>/api/sessions/{session_id}/ws` using the JWT cookie for authentication. The `session_id` is retrieved from the Zustand store (populated during login). This session-parameterized URL is required for the backend to isolate heir threads and authenticate the session scope (see Backend Spec §9.6).
    3. Renders the Heir Workspace according to the active session phase.
    4. **Switch Estate**: For Heirs only (`userRole === 'HEIR'`), the dashboard header renders a "Switch Estate" button (`SwitchEstateModal` component). A Heir is not limited to one mediation session — the same email can legitimately be onboarded as an Heir in two or more separate estates. Clicking the button calls `GET /api/auth/heir-sessions` to list sibling sessions sharing the Heir's email/username (each annotated with `is_current`), and lets the Heir pick a different one. Selecting a non-current session calls `POST /api/auth/heir-switch-session` with that session's ID, which re-issues the JWT cookie scoped to the new session without requiring the Heir to re-enter a password. The store clears session-scoped state (`assets`, `valuations`, `messages`, `announcement`) on switch so stale data from the previous estate doesn't briefly render, then reloads the profile; the existing `session_id`-keyed effects (WebSocket connection, `DashboardGuard`'s session details fetch) pick up the new session automatically.

### 2.4 `/admin`
*   **Access**: Protected (requires Admin role credentials).
*   **Logic**:
    1. On mount, before rendering first-boot setup or the login form, the route attempts cookie-based session rehydration by calling `GET /api/auth/me` with same-origin credentials.
    2. While rehydration is pending, renders a non-interactive restoring state such as "Restoring Executor Session".
    3. If `/api/auth/me` returns `role == 'ADMIN'`, the frontend updates Zustand with `isAuthenticated = true`, `userRole = 'ADMIN'`, restores any available `session_id`, reloads the Admin session list, and renders the Admin management panel, TanStack Monitor tables, and Resolution Console without forcing a new password entry.
    4. If `/api/auth/me` returns a non-Admin role, `401`, or another failure, the route falls through to the normal setup/login gate. A valid Heir cookie must never open the Admin console.
    5. Admin logout calls `POST /api/auth/logout`, clears the server cookie, clears local Zustand auth/session state, removes the saved active Admin console session selection, and returns the user to the Admin login/setup gate.
    6. A hard browser refresh on `/admin` must not log out an Admin while the HTTP-only cookie remains valid.
    7. **Scalable session index**: The Admin landing state must treat session selection as an operational index, not a short static list. It must support search, status filtering, sorting, compact/comfortable density views, and pagination or equivalent incremental loading before the list grows large. Mobile layouts must avoid repeating full-width destructive buttons for every session; each session should render as a compact card/row with a primary open target and secondary edit/delete actions.

### 2.5 `/opt-out`
*   **Access**: Public.
*   **Logic**:
    1. Renders the opt-out/decline screen informing the user that they have declined consent, no personal data was saved, and their invitation remains uncompleted.

---

## 3. Zustand State Management (`useMediationStore`)

The global client-side state is handled by a unified Zustand store to manage active session assets, points allocation, mediation chat messages, and support alerts.

```javascript
import { create } from 'zustand';

export const useMediationStore = create((set, get) => ({
  // --- State Variables ---
  session_id: null,
  heir_id: null,
  userRole: null,        // 'ADMIN' | 'HEIR' (tracks active user permissions)
  userStatus: 'PENDING', // 'PENDING' | 'PROFILE_HOLD' | 'ACTIVE' | 'SUBMITTED' | 'ABSTAINED' | 'EXPIRED_NON_PARTICIPATING'
  assets: [],            // List of AssetSchema objects
  valuations: {},        // Map of asset_id (asset.id) -> { points: int, reasoning: str, is_reasoning_shared: bool }
  unallocatedPoints: 1000,
  messages: [],          // Chat history array: { sender: 'heir'|'agent', text: str }
  isPaused: false,
  isDeadlocked: false,
  is_hitl_suspended: false,      // Tracks if Heir's thread is held at HITL_GUARD for sum validation errors
  isAuthenticated: false,
  isSubmitted: false,            // Tracks if this Heir has locked in and submitted points
  draft_version: 0,              // Version counter checked on backend to prevent out-of-order race conditions
  critique_loopback_count: 0,    // Tracks LLM compliance feedback retry loops
  sessionStatus: 'SETUP',        // 'SETUP' | 'ACTIVE' | 'LOCKED' | 'FINALIZED'
  networkStatus: 'Disconnected', // 'Connected' | 'Reconnecting...' | 'Disconnected'
  openSupportRequests: [], // For Admin view
  transientMessageQueue: [],     // Buffered offline messages: Array of {text: str, metadata: {...}}

  // --- State Actions ---
  checkInviteStatus: async (token) => {
    // Calls GET /api/invite/status/{token}
    // Returns status response: {"used": bool, "legal_first_name": str, "legal_last_name": str}
  },

  resumeSession: async (token) => {
    // Calls POST /api/invite/login with {"token": token}
    // On success, backend sets HTTP-only JWT cookie.
    // The action then sets isAuthenticated = true, calls loadProfile(), and redirects to /dashboard.
  },

  heirPasswordLogin: async ({ identifier, password, session_id = null }) => {
    // Calls POST /api/auth/heir-login with {identifier, password, session_id}.
    // If the response is {"status": "multiple_sessions", "sessions": [...]}, returns
    // it as-is WITHOUT setting isAuthenticated — the same identifier/password matched
    // Heir records in more than one mediation session, and the caller (HeirLoginPage)
    // must render a session picker and re-invoke this action with session_id set to
    // the chosen session's UUID to disambiguate.
    // On {"status": "success", ...}, sets isAuthenticated = true, session_id, heir_id,
    // userStatus from the response, calls loadProfile(), and returns the response.
  },

  loadHeirSessions: async () => {
    // Calls GET /api/auth/heir-sessions (current session cookie, no password needed).
    // Returns the sibling-session list: [{session_id, title, status, is_current}, ...]
    // Powers the dashboard's "Switch Estate" picker (SwitchEstateModal).
  },

  switchHeirSession: async (sessionId) => {
    // Calls POST /api/auth/heir-switch-session with {session_id: sessionId}.
    // Backend verifies the target session has a Heir record sharing the calling
    // Heir's email/username, then re-issues the JWT cookie scoped to it — no
    // password re-entry required.
    // On success, sets isAuthenticated = true, session_id, heir_id, userStatus from
    // the response, clears session-scoped state (assets, valuations, messages,
    // announcement) to avoid a stale flash of the previous estate's data, then calls
    // loadProfile(). Existing session_id-keyed effects (useWebSocket, DashboardGuard's
    // loadSessionDetails) pick up the new session automatically.
  },

  restoreAdminSession: async () => {
    // Calls GET /api/auth/me with same-origin credentials.
    // If the response is an authenticated ADMIN, sets isAuthenticated = true,
    // userRole = 'ADMIN', restores the session_id if present, and lets the Admin
    // route reload its session list. If the cookie is missing, expired, or belongs
    // to a Heir, it does not authenticate the Admin route.
  },

  logoutAdmin: async () => {
    // Calls POST /api/auth/logout, then clears local auth state and any saved
    // Admin console session selection. Local state must not default userRole
    // back to HEIR when isAuthenticated is explicitly false.
  },

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
    draft_version: sessionData.draft_version || 0,
    sessionStatus: sessionData.status
  }),

  saveDraft: async () => {
    // Increments local draft_version and triggers debounced PUT /api/sessions/{session_id}/valuations/draft
    // Request body: {"draft_version": draft_version, "valuations": List[ValuationDraftSchema]}
    // If browser is offline, queues the bulk sync payload in Zustand and flushes on connection.
    // Handles 409 Conflict response by rejecting old draft state.
  },

  abstainSession: async (legalName) => {
    // Calls POST /api/heirs/me/abstain with {"legal_name_signature": legalName}
    // On success, updates userStatus = 'ABSTAINED' and triggers redirect to wait/opt-out screen
  },

  downloadWaiverReceipt: async () => {
    // Fetches GET /api/heirs/me/abstain/receipt to download the signed waiver receipt PDF
  },

  updateValuation: (assetId, points) => {
    const currentVal = get().valuations[assetId] || { points: 0, reasoning: '', is_reasoning_shared: false };
    const diff = points - currentVal.points;
    
    // Check points pool headroom and lock inputs if already submitted
    if (get().isSubmitted || get().unallocatedPoints - diff < 0) return;

    set((state) => ({
      valuations: { 
        ...state.valuations, 
        [assetId]: { ...currentVal, points } 
      },
      unallocatedPoints: state.unallocatedPoints - diff
    }));
  },

  updateValuationText: (assetId, reasoning, isReasoningShared) => {
    if (get().isSubmitted) return;
    set((state) => {
      const currentVal = state.valuations[assetId] || { points: 0, reasoning: '', is_reasoning_shared: false };
      return {
        valuations: {
          ...state.valuations,
          [assetId]: { ...currentVal, reasoning, is_reasoning_shared: isReasoningShared }
        }
      };
    });
  },

  submitValuations: async () => {
    // Calls POST /api/sessions/{session_id}/valuations/submit with local valuations list
    // On success, sets isSubmitted = true to lock inputs in the client
  },

  loadValuations: async () => {
    // Calls GET /api/sessions/{session_id}/heirs/{heir_id}/valuations
    // On success, updates valuations map in state and recalculates unallocatedPoints
  },

  loadChatHistory: async () => {
    // Calls GET /api/sessions/{session_id}/heirs/{heir_id}/chat
    // Maps list of ChatMessageSchema elements to messages state: { sender: msg.sender, text: msg.scrubbed_text }
  },

  deleteAccount: async () => {
    // Calls DELETE /api/heirs/me
    // Clears all local state variables (session_id, heir_id, assets, valuations, messages)
    // Resets isAuthenticated = false, and triggers client-side router redirect to root "/"
  },

  updateProfile: async (profileData) => {
    // Calls PUT /api/heirs/me/profile with profileData (matching HeirProfileUpdate request schema)
    // On success, updates userStatus and identity_verified flag in local state and queries cache
  },

  loadProfile: async () => {
    // Calls GET /api/heirs/me
    // On success, updates session state variables: heir_id, session_id, userRole = 'HEIR', userStatus, isSubmitted, is_hitl_suspended, draft_version, etc.
  },

  emailKeepsake: async (heirId = null) => {
    // Calls POST /api/sessions/{session_id}/keepsake/email with request body {"heir_id": heirId}
    // On success, displays a UI notification alert confirming the email is queued.
  },

  addMessage: (msg) => set((state) => ({ 
    messages: [...state.messages, msg] 
  })),

  setNetworkStatus: (status) => set({ networkStatus: status }),

  enqueueOfflineMessage: (msg) => set((state) => ({
    transientMessageQueue: [...state.transientMessageQueue, msg]
  })),

  flushOfflineQueue: async (wsSend) => {
    const queue = get().transientMessageQueue;
    for (const msg of queue) { wsSend(msg); }
    set({ transientMessageQueue: [] });
  }
}));
```

---

## 4. TanStack Query & Cache Keys

We utilize TanStack Query to manage server caching, automatic polling, and background syncing.

### 4.1 Query Definitions
*   `queryKeys.assets`: `["assets"]` $\rightarrow$ Fetches the current inventory of assets. Polled occasionally during the Discovery Phase.
*   `queryKeys.session`: `["session_status"]` $\rightarrow$ Fetches global `is_paused` and `is_deadlocked` flags.
*   `queryKeys.valuations`: `["valuations", heir_id]` $\rightarrow$ Fetches the current points valuations from the backend to initialize the store and sliders.
*   `queryKeys.support`: `["support_requests"]` $\rightarrow$ (Admin-only) Fetches open heir help requests.
*   `queryKeys.profile`: `["heir_profile"]` $\rightarrow$ Fetches the calling Heir's own profile and verification status details via `GET /api/heirs/me` to synchronize the workspace.

---

## 5. WebSocket Lifecycle & Reconnection Logic

The chat workspace maintains a persistent WebSocket connection to support low-latency dual-brain inference.

### 5.1 Connection Flow
1.  On mounting `/dashboard`, the component triggers a WebSocket connection: `new WebSocket("ws://<host>/api/sessions/" + session_id + "/ws")`.
2.  If `onopen` fires, the store updates `networkStatus = 'Connected'`.
3.  If `onclose` or `onerror` fires, the store updates `networkStatus = 'Reconnecting...'` and invokes the reconnection loop.

### 5.2 Reconnection Loop
*   A custom hook or middleware retries the connection after a **3-second delay**.
*   If the connection fails, it retries with exponential backoff (e.g. 3s, 6s, 12s) up to 5 attempts.
*   If all attempts fail, updates state to `Disconnected`, alerting the user via the top header banner.
*   Any messages typed while offline are appended to a `transientMessageQueue` in the Zustand store (using `enqueueOfflineMessage`) and automatically flushed (using `flushOfflineQueue` triggered inside the WebSocket `onopen` handler) once `networkStatus = 'Connected'` is re-established.

### 5.3 WebSocket Client Audio Playback Queue Protocol
When the WebSocket client receives a `chat_reply_chunk` frame from the server containing a non-null `"audio"` base64 string, it must manage playback using an **Audio Playlist Queue** to ensure seamless, continuous speech transitions:

1.  **Queue Data Structure**:
    Maintain a queue array (e.g. `audioQueue = []`) and a playback state flag (e.g. `isPlaying = false`) in the client layer.
2.  **Decode and Enqueue**:
    Upon receiving a chunk:
    ```javascript
    // Guard against null, undefined, or empty audio payloads
    if (!payload.audio) {
        if (payload.text) {
            store.appendReplyText(payload.text);
        }
        return;
    }

    // Decode base64 to Blob URL
    const binaryString = window.atob(payload.audio);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
    }
    const blob = new Blob([bytes.buffer], { type: 'audio/wav' });
    const audioUrl = URL.createObjectURL(blob);
    
    // Add text chunk to UI message block
    store.appendReplyText(payload.text);
    
    // Enqueue audio URL
    audioQueue.push(audioUrl);
    
    // Trigger player loop
    playNextInQueue();
    ```
3.  **Sequential Playback Loop**:
    The player function plays chunks one after another, releasing resource handles:
    ```javascript
    function playNextInQueue() {
        if (isPlaying || audioQueue.length === 0) return;
        
        isPlaying = true;
        const nextUrl = audioQueue.shift();
        const audio = new Audio(nextUrl);
        audio.volume = 0.8;
        
        audio.onended = () => {
            // Revoke object URL to free browser memory
            URL.revokeObjectURL(nextUrl);
            isPlaying = false;
            // Play next segment
            playNextInQueue();
        };
        
        audio.play().catch(err => {
            console.warn("Audio playback blocked by browser gesture rules:", err);
            isPlaying = false;
            playNextInQueue();
        });
    }
    ```

4.  **Component Lifecycle Cleanup**:
    To prevent background audio leaks and memory build-up when navigation occurs during active voice synthesis playback, the mounting hook or dashboard component wrapper must return a cleanup function (e.g., in a React `useEffect` hook return):
    ```javascript
    // Pause any playing audio and clear playback state on unmount
    if (activeAudioElement) {
        activeAudioElement.pause();
        activeAudioElement = null;
    }
    // Revoke all remaining generated Blob URLs in the queue
    while (audioQueue.length > 0) {
        const url = audioQueue.shift();
        URL.revokeObjectURL(url);
    }
    isPlaying = false;
    ```

### 5.4 Client-Side View Rendering Guards & Logic
To prevent inconsistent user states (e.g. heirs editing points after submitting or during a pause), the React router and component tree must enforce the following conditional rendering guards:

> **Invariant — Asset Detail View is never gated.** All of the guards below govern *editing* controls (sliders, chat, justification text, memory sharing). None of them may gate the heir's ability to click an asset card and view its full detail (images, description, structured details, valuation, audio). When introducing a new `sessionStatus`/`userStatus` layout or replacing the dashboard body (as the Finalized layout does in item 6 below), explicitly verify the new layout still renders a working click-to-detail path for every asset card — don't assume it carries over from the previous layout.

1.  **Authentication Guard**:
    *   If `isAuthenticated` is `false`, client-side router blocks access to `/dashboard` and redirects to `/`.
2.  **Abstention / Expiration Gate**:
    *   If `userStatus` is `'ABSTAINED'` or `'EXPIRED_NON_PARTICIPATING'`, the frontend must unmount all active dashboard panels, gallery cards, and chat interfaces, and instead mount the centered **Abstention / Non-Participation Wait Screen UI** component defined in [UI Spec Section 8.9](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_ui.md#89-heir-abstention--non-participation-wait-screen-ui).
3.  **Setup Session Layout (`sessionStatus == 'SETUP'`)**:
    *   The Heir is permitted to browse the asset gallery, view details, and read shared family stories.
    *   All points sliders, justification inputs, and chat mediator textareas/microphone buttons are locked (`disabled = true`).
    *   Renders a header banner: *"Welcome! The Executor is currently setting up the estate catalog. Sliders and mediation chat will unlock once the session is launched."*
4.  **Active Session Layout (`sessionStatus == 'ACTIVE'`)**:
    *   **Profile Hold Lock**: If `userStatus == 'PROFILE_HOLD'`, all points sliders, numerical input boxes, and chat textareas/microphone buttons must have their HTML `disabled` attributes set to `true`. Renders the alert banner: *"Profile Hold. Your identity details are unverified or require correction. Sliders and chat are locked until approved."*
    *   **Grief Pause Lock**: If `userStatus != 'PROFILE_HOLD'` and `isPaused` is `true`, all points sliders, numerical input boxes, and chat message textareas/mic buttons must have their HTML `disabled` attributes set to `true`. Renders the Amber alert banner: *"Session Paused. The mediation space has been temporarily paused by the Executor."*
    *   **Sum Validation Hold Lock**: If `userStatus != 'PROFILE_HOLD'` and `isPaused` is `false` and `isSubmitted` is `false` and `is_hitl_suspended` is `true`, all points sliders, numerical input boxes, and chat message textareas/microphone buttons must have their HTML `disabled` attributes set to `true` to block submissions and chat interactions. Renders the error banner: *"Points submission suspended. Your allocations require review and correction by the Executor."* Note: The draft saving controls and the proportional auto-balance points button remain active to allow the Heir to adjust allocations to sum to exactly 1000 points.
    *   **Heir Submission Lock**: If `userStatus != 'PROFILE_HOLD'` and `isPaused` is `false` and `is_hitl_suspended` is `false` and `isSubmitted` is `true`, all points sliders, input boxes, and chat input buttons are `disabled = true`. Renders the banner: *"Valuations Submitted. Your selections are now locked. Waiting for other family members to submit."*
    *   **Active Editing**: If `userStatus != 'PROFILE_HOLD'` and `isPaused` is `false` and `isSubmitted` is `false` and `is_hitl_suspended` is `false`, all sliders and chat inputs are enabled. The "Submit Valuations" button is only enabled when `unallocatedPoints == 0`.
5.  **Conflict Review Layout (`sessionStatus == 'LOCKED'`)**:
    *   All slider controls and chat inputs are `disabled = true`.
    *   If `isPaused` is `true`, render the Grief Pause banner (*"Session Paused. The mediation space has been temporarily paused by the Executor."*) instead of the Conflict Review banner.
    *   If `isPaused` is `false` and `isDeadlocked` is `true`, renders the banner: *"Conflict Review. The session is temporarily under review by the Executor to resolve conflicting allocations."*
6.  **Finalized Keepsake Layout (`sessionStatus == 'FINALIZED'`)**:
    *   The entire dashboard layout is replaced with the **Keepsake Memory Book** view. The chat panel and points sliders are hidden. The page displays the Heir's final allocated assets list and provides download triggers for the keepsake PDF.
    *   Each asset in this list remains a clickable card that opens the same Asset Detail Pane modal used in all other layouts (full image gallery, description, structured details, valuation, sentiment tags, spoken-story audio). The finalized layout swaps out *editing* affordances (sliders, submission controls), not the detail-viewing affordance — see the invariant at the top of §5.4.
7.  **Family Memories & Stories Layout**:
    *   On the asset details view, if the asset's `shared_memories` list is populated, it renders them in a read-only collapsible section. No comments, replies, likes, or delete controls (other than one's own) are shown.
    *   During active editing (`isPaused == false` and `isSubmitted == false`), the memory textbox and the *"Share this memory with my family"* checkbox are active.
    *   If `isPaused == true` or `isSubmitted == true`, both the memory text input and the sharing checkbox are locked (`disabled = true`).

### 5.5 Browser Autoplay Gesture & AudioContext Unlock
*   To comply with browser security constraints (which block programmatic audio playback until a user gesture occurs), the frontend must initialize and resume the Web Audio context inside a user click handler.
*   **Implementation**: On mounting `/dashboard`, if the `AudioContext` is `suspended`, the UI displays a subtle volume/speaker button in the header labeled *"Enable Audio"*. Tapping this button (or clicking anywhere inside the active workspace) triggers `audioContext.resume()` or plays a silent sound buffer to authorize speech synthesis output. The button is then hidden.

### 5.6 Responsive Layout Framework
To maximize user experience across diverse screens, the React routing wrapper and layout manager enforces responsive design structures:
1.  **Mobile Viewport (< 768px Width)**:
    *   Renders a **Single-Pane Navigation** system.
    *   Displays a fixed bottom navigation bar with four tab buttons:
        *   `Discovery`: Browse the asset catalog and shared memories.
        *   `Mediation Chat`: Process thoughts and stories with the AI Mediator.
        *   `Points Sliders`: Edit and submit points valuations.
        *   `Help & FAQs`: View guidelines and file tickets.
    *   Each tab displays a full-screen view panel. Tab selections update client state.
2.  **Desktop Viewport (>= 768px Width)**:
    *   Renders a **Multi-Pane Split-Screen Dashboard** (no bottom navigation).
    *   Columns are arranged in a 3-pane split grid:
        *   *Left Pane (30% width)*: Scrollable Asset Catalog and search bar.
        *   *Center Pane (40% width)*: Persistent AI Mediator chat window and mic interface.
        *   *Right Pane (30% width)*: Allocated points details, unallocated counter, and individual sliders.
    *   Clicking an asset in the left pane updates the details card and filters comments in-place without triggering full-page routing reloads.

---

## 6. Admin Management Panels & Components

To support the Executor/Admin role in setting up and directing the estate mediation session, the frontend implements four custom dashboard views:

### 6.0 Scalable Admin Information Architecture
Admin UI surfaces must be designed for growth from the first implementation, even when seed/demo data is small. Any Admin surface that can plausibly contain more than 10 records (sessions, heirs, assets, support tickets, categories, notices, documents, audit entries) must provide:
*   **Findability**: Search by the most likely human identifier (estate title, heir name/email, asset title/category, ticket sender).
*   **Filtering**: At minimum, status/phase filters for lifecycle records and category filters for catalog records.
*   **Sorting**: At minimum, newest/oldest and alphabetical sorting where applicable.
*   **Density control**: A comfortable card view for review and a compact list view for high-volume scanning.
*   **Progressive disclosure**: Primary action is visible; secondary/destructive actions are grouped or visually subordinate so users are not overwhelmed.
*   **Pagination or incremental loading**: Long lists must not render as one unbounded scroll on mobile. Default page/window size should be small enough for phone use (for example, 8 sessions per page) and can grow on desktop if performance and readability allow.
*   **Responsive controls**: Mobile controls stack into a clear command bar. Desktop controls may use a horizontal toolbar. Controls must not force horizontal scrolling or truncate critical actions.

The Admin session picker is the reference pattern: search + status filter + sort + card/list density + pagination + summary chips. Future list-like Admin features should reuse this interaction pattern unless a domain-specific workflow requires a stronger alternative.

### 6.1 `AdminSetupChecklist`
Guarantees the estate catalog is fully prepared before launching. Renders:
*   **Infrastructure Health**: Verifies connection pool status, dynamic LLM provider keys, and SMTP server connectivity.
*   **Estate Setup Steps**: Checks that at least two active heirs have been registered and at least five staged assets are published into the live catalog.
*   **Status Indicators**: Green checkmarks for complete requirements and amber warnings with action links for pending configurations.

### 6.2 `AdminSessionLifecycleControls`
Orchestrates active mediation session states:
*   **Launch Session**: Transitions the session status from `'SETUP'` to `'ACTIVE'`.
*   **Grief Pause Control**: Toggles the `is_paused` flag, locking sliders and AI chats on the heir's client side during emotional halts.
*   **Finalize / Lock Session**: Transitions the session status to `'LOCKED'` to calculate distribution matrices or `'FINALIZED'` to output documents.

### 6.3 `AdminCommunicationsPanel`
Facilitates Executor announcements and direct assistance:
*   **Estate Announcements**: Publishes text updates visible at the top of heirs' screens.
*   **Support Ticket Workspace**: Lists open help tickets, displays heir screenshot attachments, and allows Executors to type replies (`admin_response`), upload response attachments, and resolve tickets.

### 6.4 `AdminFinalDocumentsPanel`
Handles outputs and fiduciary accounting:
*   **Probate Audit Ledger**: Fetches the encrypted JSON chain, verifies historical hashes, and triggers PDF rendering with page templates.
*   **Keepsake Memory Books**: Triggers background tasks that generate custom keepsakes for each heir and emails them using the SMTP dispatch service.

### 6.5 `AdminSettingsPanel` — Grouped Purpose Cards (LLM Section)

The LLM configuration section of `AdminSettingsPanel.jsx` is organized as one card per AI purpose. Each purpose card is fully self-contained:

*   **Card layout** (one card per purpose: Fast, Slow, Vision, Embedding, Pricing):
    *   Provider dropdown (options: `ollama`, `openai`, `anthropic`, `google`, `openrouter`, `nvidia`).
    *   Model name text input (auto-filled with a sane default when the provider dropdown changes; defaults sourced from `PROVIDER_DEFAULT_MODELS` constant in the component).
    *   API Key password input (per-purpose; maps to e.g. `FAST_API_KEY`, `VISION_API_KEY`).
    *   Base URL text input (per-purpose; maps to e.g. `FAST_BASE_URL`, `VISION_BASE_URL`). Enables any OpenAI-compatible endpoint.
    *   "Test Connection" button inside the card — sends the card's current draft values as `overrides` to `POST /api/admin/settings/test-connection` with the matching `purpose` string. Shows `✓ {detail} ({elapsed_ms}ms)` or `✗ {error}` inline beneath the button.
*   **No separate "Credentials" section**: Per-purpose API key and base URL live inside the purpose card, not in a shared section below.
*   **"Shared Provider Credentials" card** at the bottom of the LLM section only — shows company-level fallback keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OLLAMA_BASE_URL`). These are used when a purpose card's per-purpose key is left blank.
*   **`PURPOSE_CREDENTIAL_FIELDS`**: a constant mapping each purpose key (`fast`, `slow`, `vision`, `embedding`, `pricing`) to its `_API_KEY` and `_BASE_URL` field names, used to construct the `overrides` payload for test-connection calls.
*   **Non-LLM tabs** (smtp, storage) keep the original flat field layout — the grouped card design applies only to the `llm` tab.

### 6.6 Edit Keepsake Details Drawer — AI Generation Workflow

The Edit Keepsake Details slide-out drawer (in `AdminInventoryDashboard.jsx`) supports a full AI-assisted listing workflow:

#### AI Generation

*   **"✨ Generate with AI" button** in the drawer toolbar (right side). Calls `POST /api/assets/{asset_id}/generate-details`.
*   On success, populates all drawer form fields (title, category, item_overview/description, specifications, condition_report, keywords, sentiment_tags, dimensions).
*   After generation the asset is tracked in `aiGeneratedAssets` state (a `Set` of asset IDs) for the current admin session — used to show the "please review" banner until verified.

#### AI Generation Error Modal

When the generate-details call fails, a dedicated modal dialog renders on top of the drawer (z-index 1300 — above the drawer overlay):
*   Title: "⚠ AI Generation Failed" (red/destructive styling).
*   Body: the actual `detail` error message from the backend response.
*   Note: "No fields were changed."
*   "OK" dismiss button.

This is kept separate from the shared `error` state/banner so it cannot be hidden behind the drawer overlay.

#### Human Verification Workflow

After AI generates listing details, the Admin reviews and optionally edits them, then clicks "✓ Mark as Verified":
*   Calls `POST /api/assets/{asset_id}/ai-feedback` with `{ "rating": "thumbs_up", "comment": "Human verified after AI generation" }`.
*   While saving, the asset ID is added to `verifyingAssets` state (a `Set`) to show a spinner/disabled state on the button.
*   On success, the asset's `ai_feedback` field in local state is updated to reflect the verified state.

#### Drawer Toolbar Layout

The toolbar inside the Edit drawer renders:
*   **Left side — status banner** (one of):
    *   `"✓ Human Verified"` (green) — if `asset.ai_feedback?.rating === 'thumbs_up'`.
    *   `"⚠ AI Generated — please review"` (amber) — if the asset is in `aiGeneratedAssets` but not yet verified.
    *   `"✨ AI Generated — not yet verified"` (neutral) — if `ai_feedback` exists but rating is not `thumbs_up`.
    *   No banner if no AI generation has occurred for this asset.
*   **Right side — action buttons**:
    *   `"✓ Verified"` label (static, green) if already verified; otherwise `"✓ Mark as Verified"` button.
    *   `"✨ Generate with AI"` button (always visible in drawer toolbar).
*   **Error banner for verify failures** renders INSIDE the drawer toolbar (not at the top of the page behind the overlay).

### 6.7 Asset Card AI Badges

Asset cards in the `AdminInventoryDashboard` inventory list display a status badge based on the asset's `ai_feedback` field:
*   `"✓ Human Verified"` — green badge — when `ai_feedback?.rating === 'thumbs_up'`.
*   `"✨ AI Generated"` — amber badge — when `ai_feedback` exists but the rating is not `thumbs_up` (i.e. AI-generated but not yet human-verified).
*   No badge if `ai_feedback` is null/absent.

---

## 7. Mobile Distribution Strategy (Phone-Based Usage Without App Store Submission)

**Missed requirement, identified post-launch-planning**: both roles need a phone-first experience without going through Apple's App Store or Google Play review process. The Admin/Executor needs a phone in-hand to walk the decedent's home, photograph inventory items, and monitor/communicate with heirs from anywhere. Heirs need a single-phone experience to complete the entire review/allocation process without a desktop.

### 7.1 Decision: Progressive Web App (PWA), not a native app store submission
*   The existing Vite/React frontend is extended with a `manifest.json` (app name, icons, `display: "standalone"`, theme colors) and a service worker (Workbox or hand-rolled), enabling "Add to Home Screen" installation on both iOS Safari and Android Chrome.
*   This avoids Apple/Google marketplace review, signing, and release-cycle overhead entirely — the installed PWA is served directly from the same Cloudflare Tunnel / Nginx origin already used for browser access (see Backend Spec §Docker-Compose deployment, Phase 7 Cloudflare Tunnel).
*   Camera access for both the Admin's inventory photography flow and the Heir's `IDScanner` government ID capture uses standard `<input type="file" accept="image/*" capture="environment">` / `getUserMedia` browser APIs, which already work inside an installed PWA with no additional native permissions plumbing.
*   **Known limitation**: iOS web push (for "monitor and communicate at anytime" alerting) is only supported for installed PWAs on iOS 16.4+, and is materially less reliable than native push. Until this is hardened, the existing WebSocket reconnect loop (`useWebSocket` hook, Frontend Spec §5.2) remains the primary real-time channel while the app is foregrounded/backgrounded-briefly, and SMTP email dispatch (Backend Spec) is the fallback channel for alerts that must reach the user when the PWA is fully closed.
*   **Implementation**: `frontend/vite.config.js` registers `vite-plugin-pwa` (`registerType: 'autoUpdate'`), which generates `dist/manifest.webmanifest` and a Workbox service worker (`dist/sw.js`) on every `npm run build`. API and WebSocket traffic (`/api/*`, `/ws`) is explicitly excluded from the Workbox cache (`NetworkOnly`) so mediation state, valuations, and chat never serve a stale offline copy. `frontend/index.html` carries the `apple-touch-icon`, `theme-color`, and `apple-mobile-web-app-*` meta tags Safari requires for a correct standalone-mode install. Icons (`frontend/public/icon-192.png`, `icon-512.png`) are rendered from the existing brand mark (`favicon.svg`).

### 7.2 `scripts/install_on_phone.sh` — One-Command Phone Install
To make installing the PWA on a physical iPhone/Android as low-friction as typing a URL by hand, `scripts/install_on_phone.sh`:
1.  Runs `npm run build` in `frontend/` to (re)generate the manifest and service worker.
2.  Starts the Docker stack (`app`, `nginx`) via `docker compose up -d`.
3.  Reads `CLOUDFLARE_TUNNEL_TOKEN` / `PUBLIC_BASE_URL` from `.env`:
    *   **If set**: also starts the `cloudflared` profile and prints the real public HTTPS URL — the only path where the service worker fully registers and offline caching works.
    *   **If unset**: auto-detects the host machine's LAN IPv4 address (scans `en0`–`en3`, then falls back to scanning all interfaces for a private-range address) and prints `http://<lan-ip>` instead, with an explicit warning that this is HTTP-only — "Add to Home Screen" still creates the icon, but the service worker will not register without HTTPS, so this path is for quick visual testing only, not the real install.
4.  Renders the chosen URL as a QR code and opens it as a PNG image (`open` on macOS) so a phone camera can scan a crisp, full-resolution image — terminal ASCII-art QR codes are unreliable for camera scanning due to font anti-aliasing distorting the module grid. Falls back to ASCII-art QR (with a warning) only if PNG rendering is unavailable.
5.  Prints the iPhone-Safari / Android-Chrome "Add to Home Screen" steps.

The generated `.qr-install.png` is gitignored (regenerated per run, not committed).

### 7.3 Future Consideration: Native App Wrapper
*   If PWA push reliability or offline photo-queueing limitations become a real adoption blocker, the React codebase can be wrapped with Capacitor (or React Native re-implementation of the view layer) to ship true native iOS/Android binaries with full background push and offline storage APIs.
*   This is **not** scheduled in the current implementation plan — it is a deliberate future option, not a committed phase. Going this route would still require either official App Store/Play Store distribution (re-introducing the marketplace dependency this plan is trying to avoid) or enterprise/ad-hoc sideloading, which is high-friction for non-technical heirs.
*   To keep this option viable without rework, frontend code should avoid baking browser-only assumptions into business logic (keep API calls, Zustand store actions, and validation logic decoupled from DOM/browser-specific code), so a future Capacitor wrap is primarily "add a native shell" rather than a rewrite.
