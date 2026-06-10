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

### 2.2 `/dashboard`
*   **Access**: Protected (requires JWT session cookie).
*   **Logic**:
    1. If not authenticated, redirects to `/`.
    2. Establishes the WebSocket session connection `ws://<host>/api/sessions/{session_id}/ws` using the JWT cookie for authentication. The `session_id` is retrieved from the Zustand store (populated during login). This session-parameterized URL is required for the backend to isolate heir threads and authenticate the session scope (see Backend Spec §9.6).
    3. Renders the Heir Workspace according to the active session phase.

### 2.3 `/admin`
*   **Access**: Protected (requires Admin role credentials).
*   **Logic**:
    1. Renders the Admin management panel, TanStack Monitor tables, and Resolution Console.

### 2.4 `/opt-out`
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

