# Estate Steward: UI/UX Component & Layout Specification (v2.0)

This specification defines the design system, responsive layouts, print styles, semantic search interfaces, touch/mouse voice controls, and mobile camera workflows.

---

## 1. Grief-Informed Design System & Tokens

The visual identity of The Estate Steward is designed to feel like an **Archival Index Card** system—warm, tactical, and grounded. We explicitly prohibit glowing gradients, neon drop-shadows, or glassmorphic backdrops.

### 1.1 Color Tokens (Vanilla CSS variables)
```css
:root {
  --color-bg: #FDFBF7;           /* Cream-50: Calming background */
  --color-card-bg: #FFFFFF;      /* Solid white: Crisp card fill */
  --color-text: #1E293B;         /* Slate-900: High-contrast text */
  --color-border: #E6DFD3;       /* Warm-Grey: Fine organic lines */
  --color-primary: #4A6741;      /* Sage-600: Calming action and growth tone */
  --color-primary-light: #F2F5F0;/* Sage-50: Soft highlights */
  --color-alert: #F59E0B;        /* Amber-500: Reconnecting / warnings */
  --color-alert-light: #FEF3C7;  /* Amber-50: Soft warnings */
}
```

### 1.2 Typography
*   **Headers & Titles**: *Playfair Display* (Serif) – conveys transition and historical weight.
*   **Data, Inputs & Chat**: *Inter* (Sans-serif) – optimizes readability for numbers, values, and dialogues.

### 1.3 Motion & Transitions
*   **Duration**: All UI transitions (e.g., hover states, slide drawers) are fixed at `300ms` using `transition: all 0.3s ease-in-out`.
*   **Behavior**: Smooth, linear, or ease-in-out animations. No bouncy, snappy, or dramatic zooms.

### 1.4 Premium Editorial UI Styles (Vanilla CSS Rules)
To ensure the interface feels like a high-quality physical catalog and does not look like a generic web template, developers must implement the following Vanilla CSS styling definitions:

```css
/* 1. The Archival Index Card Component */
.archival-card {
  background-color: var(--color-card-bg);
  border: 1px solid var(--color-border);
  border-radius: 4px; /* Cardstock edges, not generic round bubbles */
  padding: 24px;
  box-shadow: 3px 3px 0px var(--color-border); /* Tactile rigid offset shadow */
  transition: border-color 0.3s ease-in-out, box-shadow 0.3s ease-in-out;
}

.archival-card:hover {
  border-color: var(--color-primary);
  box-shadow: 4px 4px 0px rgba(74, 103, 65, 0.15); /* Soft Sage Green shadow lift */
}

/* 2. Jitter-Free Numerals (Crucial for Points Adjustment) */
.tabular-value {
  font-family: 'Inter', sans-serif;
  font-weight: 600;
  font-variant-numeric: tabular-nums; /* Prevents text layout shifting on slider drag */
  color: var(--color-text);
}

/* 3. Custom Archival Slider Track & Thumb (Replacing cheap browser defaults) */
.archival-slider {
  -webkit-appearance: none;
  width: 100%;
  height: 2px;
  background: var(--color-border);
  outline: none;
  margin: 12px 0;
}

.archival-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 2px; /* Rigid square folder tab design */
  background: var(--color-primary);
  cursor: pointer;
  transition: transform 0.1s ease-in-out;
}

.archival-slider::-webkit-slider-thumb:hover {
  transform: scale(1.25);
  background: #3B5234; /* Muted darker Sage Green */
}

/* 4. Empathic Speech Pulsing Waveform */
.mic-wave-pulse {
  position: relative;
  display: inline-flex;
  justify-content: center;
  align-items: center;
}

.mic-wave-pulse::after {
  content: '';
  position: absolute;
  width: 100%;
  height: 100%;
  border: 2px solid var(--color-primary);
  border-radius: 50%;
  opacity: 0.8;
  animation: pulse-ring 2s cubic-bezier(0.215, 0.610, 0.355, 1) infinite;
}

@keyframes pulse-ring {
  0% {
    transform: scale(0.95);
    opacity: 0.8;
  }
  80%, 100% {
    transform: scale(1.6);
    opacity: 0;
  }
}
```

---

---

## 2. Responsive Layout Strategy & Breakpoints

We implement a **Mobile-First CSS Grid and Flexbox** layout system.

### 2.1 Responsive Breakpoints
*   **Mobile (`< 768px`)**: Single-column layouts, full-width drawers, bottom-tab navigation for heirs.
*   **Tablet (`768px - 1024px`)**: Two-column grids for galleries, modal overlays.
*   **Desktop (`> 1024px`)**: Multi-column split layouts (e.g., side-by-side asset detail, chat mediator, and sliders).

### 2.2 Layout Configurations

#### The Heir Dashboard
*   **Header Controls (Global)**:
    *   **Network Status Indicator**: A small text pill displaying connection status (e.g., `Connected` in Sage Green text, or `Reconnecting...` in Amber-500). Refer to [specs_frontend.md](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_frontend.md) for retry interval logic.
    *   **Unallocated Points Status Bar**: A sticky horizontal bar: `Unallocated Points: P / 1000` (where `P = 1000 - Sum(allocated_points)`).
*   **Point Slider UI Mechanics**:
    *   Adjusting any asset slider or typing in an allocation input box draws points directly from the `Unallocated Points` pool.
    *   If the pool reaches `0`, the UI disables the "increase" thumb handlers on all other asset sliders and dynamically locks the maximum input limit on numerical input boxes (`max = current_value + unallocated_points`). To increase points for Asset A, the Heir must manually decrease points on Asset B first.
    *   **Auto-Rebalance Helper Button**: Render a small, subtle button labeled **"Auto-Balance Points"** (styled in Slate-900 border with low weight) next to the points status bar. If the Heir's current slider allocations do not sum to exactly 1000 points, clicking this button automatically runs a proportional scaling algorithm on all non-zero slider values:
        $$x_i^{\text{new}} = \text{round}\left( \frac{x_i^{\text{old}}}{\sum x_k^{\text{old}}} \times 1000 \right)$$
        Adjusts any rounding remainders (adding or subtracting the remainder to/from the highest-point asset) to ensure the total sums to exactly 1000 points, updates all sliders in the local Zustand store, and triggers a draft sync.
        *   **Safety Guard (Zero Allocations)**: The "Auto-Balance Points" button must be disabled in the UI if the sum of all current points is 0 (initial state). If triggered, the calculations must check that $\sum x_k^{\text{old}} > 0$. If the sum is 0, it must abort the scaling calculation to prevent Division by Zero (`NaN` / `Infinity`) errors.
    *   **Visual Sentiment Labels**: Next to the numeric points display on each slider card, render an italicized text label matching these ranges:
        *   `0`: *Neutral / Pass*
        *   `1 - 250`: *Would like to have*
        *   `251 - 500`: *Sentimental Attachment*
        *   `501 - 999`: *Deep Sentimental Connection*
        *   `1000`: *Absolute Priority / Keepsake*
    *   **Debounced Bulk Draft Sync**: To prevent losing work upon browser tab closure or network drops, all slider adjustments and reasoning text entries are queued in the local Zustand store. Upon slider release (`onChangeEnd`) or keyup pauses, the frontend debounces for 1.5 seconds before calling `PUT /api/sessions/{session_id}/valuations/draft` to save the active allocations database-side. If the browser goes offline, the bulk sync payload is preserved in Zustand and dispatched immediately upon connection re-establishment.
*   **Mobile View**: Bottom-tab navigation menu:
    1.  **Gallery**: Single-column vertical scroll of asset cards (large images).
    2.  **Mediation**: Fullscreen active chat room with the Mediator Agent. A permanent, low-contrast disclosure banner must be rendered at the top of the chat page: **"Chatting with AI Mediator"** (satisfying California SB 1001 Bot Disclosure requirements).
    3.  **Allocations**: Dedicated slider control list with the sticky unallocated points header.
*   **Desktop View**: Three-pane split-screen:
    *   **Left Pane (30%)**: Asset Gallery navigation list.
    *   **Center Pane (40%)**: Selected Asset view (high-fidelity image carousel, metadata, points slider, and a custom **Audio Player Widget** if `audio_uri` is present, styled with Sage-Green borders and cream background, permitting heirs to play and stream the Admin's spoken story).
    *   **Right Pane (30%)**: Persistent Mediator Agent chat window with voice toggle. Includes a permanent, highly visible header label: **"AI Mediator Agent"** to ensure compliance with California's AI transparency rules.
*   **Fiduciary Disclaimer Footer (Global)**: A permanent footer centered at the bottom of the layout in Helvetica 8pt, Slate-500 text:
    *"Disclaimer: The Estate Steward is a collaborative mediation aid designed to assist executors and heirs in dividing personal property. It does not provide legal advice, estate planning, or tax counsel. Use of this tool does not guarantee probate court approval. Executors are advised to consult with a licensed probate attorney regarding their fiduciary obligations and court filings."*

#### The Admin Dashboard
*   **Mobile View (Staging & Snapping)**: Streamlined photo capture view. Large "Capture Asset" button, camera staging uploader, and quick meta forms.
*   **Desktop View (Management Console)**: Full management dashboard. Left side features asset grids; right side displays the Heir Registration Panel, the TanStack Session Monitor Table, and Deadlock Resolution overrides.
*   **Heir Registration Panel**: An input form allowing the Executor to register heirs.
    *   *Inputs*: Display Name (`username` - text), Email Address (`email` - email), Phone Number (`phone` - tel, optional), and Physical Mailing Address (`physical_address` - textarea, optional).
    *   *Action*: "Register Heir" button (styled in Sage-Green `var(--color-primary)`) that triggers `POST /api/sessions/{session_id}/heirs`.
*   **TanStack Session Monitor Table**: A grid displaying all registered beneficiaries in the active session.
    *   *Columns*: Name, Email, Phone, Address, Invite Token (with a copy-to-clipboard button), Dispatch Timestamp, Token Expiration, and Status/Submission progress checkmark.
*   **Staged Asset Deletion Control**: In the Setup Phase asset grid, each card must render a **"Delete Asset"** icon button (Trash Can icon, styled in Slate-600 with low contrast, shifting to Red on hover). Clicking it displays a confirmation dialog: *"Are you sure you want to permanently delete this asset and its associated image? This action cannot be undone."* If confirmed, triggers `DELETE /api/assets/{asset_id}` and removes the card.
*   **Asset Upload Scope Warning**: In the asset uploading and staging forms, a prominent alert block must be rendered:
    *   *Aesthetics*: 1px solid border matching `var(--color-alert)`, light background `var(--color-alert-light)`.
    *   *Text*: *"Scope Limit Notice: This system is designed exclusively for tangible personal property (keepsakes, furniture, jewelry, etc.). Do not upload real estate, financial/bank accounts, securities, or titled vehicles."*
*   **Fiduciary Disclaimer Footer (Global)**: A permanent disclaimer footer identical to the Heir Dashboard must be rendered at the bottom of the Admin panel.

---

## 3. Inventory View & Semantic Search

### 3.1 Inventory Visual Cards
*   **Aesthetics**: Warm Editorial Archival Index Cards:
    *   **Fill**: `var(--color-card-bg)` resting on the `var(--color-bg)` background.
    *   **Border**: `1px solid var(--color-border)`.
    *   **Shadow**: A flat, tactile offset shadow (`box-shadow: 3px 3px 0px var(--color-border)`).
    *   **Hover Interaction**: On hover, the border transitions smoothly to `var(--color-primary)` over `300ms` with a very soft rise (`box-shadow: 4px 4px 0px rgba(74, 103, 65, 0.15)`).
*   **Image Rendering**:
    *   **Gallery Grid Cards**: Card thumbnails have an `aspect-ratio: 4/3`. Images use `object-fit: cover` to maintain grid alignment.
    *   **Asset Detail Pane**: High-fidelity previews use `object-fit: contain` inside a solid boxed frame, rendering the full, original photograph.
*   **Metadata Badges**: Flat, border-only categorization pills with no backgrounds:
    *   `Jewelry` (Gold border `#C29F53`), `Furniture` (Warm brown border `#8E7558`), `Art` (Muted violet border `#7E6C84`), `Other` (Cool grey border `#64748B`).

### 3.2 Semantic Vector Search & Filter Controls
*   **The Search Bar**: A prominent search input at the top of the gallery with a filter menu toggle.
*   **Filter Options Panel**: Clicking the filter toggle expands a drawer containing the following options:
    1.  **Category Filters**: Checklist buttons for `Jewelry`, `Furniture`, `Art`, and `Other`.
    2.  **My Allocations (Heir View)**:
        *   *All*: Shows everything.
        *   *Allocated*: Shows only items where the Heir has assigned $>0$ points.
        *   *Unallocated*: Shows only items with $0$ points assigned.
        *   *Pre-Allocated*: Shows items locked to specific heirs via Will devises.
    3.  **Spoken Provenance**: Toggle to show only items containing an **Admin Spoken Story** recording.
    4.  **Shared Stories**: Toggle to show only items where another Heir has written and shared a family memory.
*   **Sorting Options**: A dropdown menu allowing users to sort by:
    *   *Relevance* (active only during searches).
    *   *My Points* (High to Low / Low to High).
    *   *Title* (A-Z / Z-A).
    *   *Category*.
*   **Confidence Thresholds & Fallbacks**:
    *   **High Confidence (Similarity Score $\ge 75\%$)**: Displayed directly in the results grid with a Sage Green relevance match pill (e.g., *"90% Match"*).
    *   **Low Confidence (Similarity Score $< 75\%$)**: Filtered out of the results grid to prevent clutter.
    *   **Zero-Match Fallback State**: If no assets meet the $75\%$ threshold, the gallery displays a clean, editorial empty state card:
        *   *"We couldn't find a close match for '[Search Query]'. Try searching by general category (e.g. 'Furniture') or ask the Mediator Agent."*
        *   **"Ask the Mediator" Button**: Automatically opens the chat panel, injects the search query as a question (e.g. *"Did you find any [Search Query] in the estate?"*), and triggers a chat request.

---

## 4. Voice Interaction & Touch/Mouse Triggers

Voice mediation is built client-side via the browser's Web Speech API (`window.SpeechRecognition` or `window.webkitSpeechRecognition`).

### 4.0 Secure Contexts & API Guard
*   **HTTPS Requirement**: The Web Speech API is blocked by browsers in non-secure contexts. For voice transcription to function on mobile devices connected over the local network, the server must be accessed via **HTTPS** (or localhost for local development). If accessed via unsecure HTTP, the frontend must disable the microphone button and show a helper icon: *"Voice input requires a secure HTTPS connection."*
*   **Permission Delay Guard**: Because requesting microphone permission is asynchronous, the React hook must handle states where `touchend` is fired *before* the user has approved the permission prompt. Calling `.stop()` on a non-started recognition instance throws an `InvalidStateError`. Developers must wrap all `.start()` and `.stop()` calls in safety checks (e.g. tracking `isStarted` and `isListening` flags in local states) and try-catch blocks to prevent UI crashes.
*   **Auto-Silence Timeout Handler**: Mobile webviews (like Safari on iOS) automatically kill active speech recognition after 3-5 seconds of silence, firing the `onend` event prematurely. If the user is still physically holding the button, the `touchend` event will eventually fire and call `.stop()`, which crashes if the browser already auto-stopped. The UI hook must listen to `onend` to reset the listening state variables automatically, and ignore `.stop()` if `onend` has already fired.

### 4.1 Touch Triggers (Mobile / Tablet)
*   **Action**: Press-and-Hold mic button.
*   **Events**:
    *   `touchstart`: Initializes browser Speech Recognition. Triggers a light haptic vibration (if supported) and shows a pulsing sage-green wave animation around the microphone icon.
    *   `touchend` / `touchcancel`: Halts speech recognition. The final transcribed string is injected directly into the message text area. The user can review the text and click "Send".

### 4.2 Mouse Triggers (Desktop / Laptop)
*   **Action**: Dual Mode (Click-to-Toggle or Hold-to-Talk).
*   **Events**:
    *   **Hold Mode**: Triggers on `mousedown` and stops on `mouseup`/`mouseleave`.
    *   **Toggle Mode**: A single quick click starts recording (turning the mic button solid sage green). A second click stops it.
*   **Accessibility**: Focusable mic button (`tabindex="0"`) triggerable via the `Spacebar` or `Enter` keys (Hold on keydown, stop on keyup).

---

## 5. Mobile Camera Uploader (Admin Flow)

Interfaces with native camera hardware for quick asset snapping.

### 5.1 HTML Camera Capture Trigger
We use standard HTML uploader elements with special capture attributes:
```html
<input 
  type="file" 
  id="asset-camera-upload" 
  accept="image/*" 
  capture="environment" 
  style="display: none;" 
/>
```
*   **Mobile**: Triggers native rear-facing device camera.
*   **Desktop**: Opens the standard OS file picker.

### 5.2 Staging UI Flow
1.  Admin snaps the photo.
2.  Image displays inside a loading card with a sage-green progress spinner, indicating that background OCR metadata extraction is in progress.
3.  The frontend issues `POST /api/sessions/{session_id}/assets/stage` sending the image file.
4.  The backend triggers the `llava` visual OCR background task and sets `ocr_status = 'PROCESSING'`.
5.  The frontend remains in a loading state, listening to the Admin WebSocket broadcast channel. Once the backend finishes extraction, it broadcasts the `"asset_ocr_completed"` event containing the pre-filled fields (title, category, tags, description, and suggested valuation ranges). The frontend captures this event, hides the spinner, displays the slide-up editing form, and triggers a haptic confirmation tick.
    *   **Admin Voice-Dictated Stories**: Next to the Description and Sentiment Tag input fields, a microphone icon is provided. When tapped (using the Web Speech API transcription service), the Admin can dictate their personal stories or descriptions of the item, transcribing them directly into the fields to simplify cataloging.
6.  Admin edits details if needed, ensures all fields (including the valuation source) are valid, and clicks "Publish Live" to transition the asset to `LIVE`.

### 5.3 Admin Voice Recorder Interface
To capture the Admin's actual spoken voice telling the story of an heirloom, the asset staging slide-up editing card includes a dedicated **Voice Story Recording Widget**:
*   **Controls & Buttons**:
    1.  **Record Button** (Red microphone icon): Clicking it starts device audio capture using the browser's `MediaRecorder` API. A pulsing red recording ring appears, along with a timer displaying elapsed seconds (e.g. `0:15 / 2:00` - max 2 minutes).
    2.  **Stop Button** (Solid grey square): Halts recording. The browser stops the media stream, saves the recorded audio chunks into a local `Blob` (type `audio/webm` or `audio/ogg`), and generates a local URL for preview.
    3.  **Listen / Playback Controls**: Shows a mini play/pause tracker. Allows the Admin to listen back to their recorded audio story.
    4.  **Re-do / Delete Button**: Clears the active recording and resets the widget, allowing the Admin to record a fresh take.
    5.  **Save / Upload Trigger**: Initiated when the Admin clicks "Publish Live". The frontend packages the audio blob as multipart form data and calls `POST /api/assets/{asset_id}/audio` in parallel.
*   **Aesthetics**: Housed in a dedicated panel labeled *"Record Spoken Story / Provenance"* styled with a thin sage-green border (`var(--color-primary-light)` background).

---

## 6. UI State Transitions & User Guidance (Preventing Confusion)

### 6.1 Heir Dashboard State Matrices

| Active System State | Frontend UI Modifications | Helper Banner & Message (Amber-500) |
| :--- | :--- | :--- |
| **Setup (Wait)** | Sliders disabled. Chat input disabled. Permitted to browse gallery and read shared family memories. | *"Welcome! The Executor is currently setting up the estate catalog. Sliders and mediation chat will unlock once the session is launched."* |
| **PROFILE_HOLD** | Sliders disabled. Chat input disabled. Permitted to browse gallery, view/edit personal profile details, and re-upload ID scans. | *"Profile Hold. Your identity details are unverified or require correction. Sliders and chat are locked until approved."* |
| **In-Progress** | All sliders active. Chat mediator input fully unlocked. | `Allocated: X / 1000 pts`. Shows a soft notice: *"Please allocate exactly 1000 points to finalize your submissions."* |
| **User Submitted** | Sliders disabled and replaced with flat point badges. Chat input disabled. | *"Valuations Submitted. Your selections are now locked. Waiting for other family members to submit."* |
| **Grief Pause / Locked** | Sliders disabled. Chat input disabled. | *"Session Paused. The mediation space has been temporarily paused by the Executor. You can browse assets but allocations are frozen."* |
| **Deadlocked** | Sliders disabled. Chat input disabled. | *"Conflict Review. The session is temporarily under review by the Executor to resolve conflicting allocations."* |
| **Finalized** | Swaps Dashboard view to the **Keepsake Memory Book** view. Renders "Download PDF" and "Email Keepsake" buttons. | *"Mediation Finalized. Below is your keepsake ledger. You can save this report locally, print a copy, or email it to your registered address."* |

### 6.2 Admin Dashboard State Matrices

| Active System State | Frontend UI Modifications | Console Alert Banner |
| :--- | :--- | :--- |
| **Setup Phase** | Allows uploading, editing, staging, and publishing assets. Displays the "Launch Session" action button (which locks the catalog and transitions the session to ACTIVE). | Banner: *"Setup Phase. Stage and publish assets. Click 'Launch Session' to open mediation to heirs."* |
| **Active Mediation** | Displays the TanStack Heir Monitor Table with live checkmarks showing who has submitted. | Banner: *"Mediation Session Active. Waiting for Heir submissions."* |
| **Grief Pause (Lock)** | Enforces a global lock. Banners display the "Unlock Session" button. | Banner: *"Session Locked. Sliders are frozen on all Heir devices."* (Sage Green button to unlock). |
| **Deadlocked** | Opens the **Resolution Console** overlay. Highlights the specific assets with overlapping maximum bids. | Alert: *"Deadlock Detected. Mathematical MNW limits exceeded. Please utilize the Force Allocation override sliders below."* |
| **Finalized** | Replaces active controls with the "Download Final Audit Ledger" button. Displays the cryptographic seal verified hash. | Banner: *"Estate Mediation Closed. Ledger Cryptographically Sealed."* |

---

## 7. CSS Print Ledger Stylesheets (`@media print`)

To support printing physical ledgers and saving clean PDF records of the finalized estate distribution, we enforce custom print styles.

```css
@media print {
  /* 1. Hide interactive elements, navigation tabs, chat panels, and buttons */
  nav, 
  button, 
  input, 
  .mediator-chat-window, 
  .network-status-bar,
  .points-sliders-controls {
    display: none !important;
  }

  /* 2. Format body for standard physical page dimensions */
  body {
    background: #FFFFFF !important;
    color: #000000 !important;
    font-family: serif; /* Default to high-legibility print serif */
    font-size: 11pt;
    line-height: 1.5;
    margin: 1.5cm;
  }

  /* 3. Convert visual card components into clean table rows or flat blocks */
  .asset-card {
    border: none !important;
    border-bottom: 1px solid #000000 !important;
    box-shadow: none !important;
    page-break-inside: avoid;
  }

  /* 4. Table properties */
  table {
    width: 100%;
    border-collapse: collapse;
  }
  
  thead {
    display: table-header-group; /* Repeat headers across pages */
  }

  tr {
    page-break-inside: avoid;
  }

  /* 5. Cryptographic Monospace Seal Section */
  .cryptographic-seal {
    font-family: monospace;
    font-size: 9pt;
    border: 1px solid #000000;
    padding: 10px;
    margin-top: 2cm;
    page-break-inside: avoid;
  }
}
```

---

## 8. Heir Assistance & Support UI Components

### 8.1 Heir "Request Help" Modal
*   **The Trigger**: A permanent link at the bottom of the Heir workspace: *"Need assistance? Contact the Executor."* (Styled in Slate-900, low weight, subtle spacing).
*   **The Modal overlay**: When tapped, opens an organic warm-white index card modal with a text field:
    *   *Helper Prompt*: *"If you are experiencing issues, have questions about an asset, or feel overwhelmed and need a pause, please enter your message below. The Executor will be notified immediately."*
    *   *Inputs*: Text area (`message` - min 5 chars, max 1000).
    *   *Actions*: "Send Message" (Sage Green fill) and "Cancel" (neutral text).
*   **Confirmation Feedback**: Shows a quiet haptic tick and a confirmation badge: *"Your message has been delivered to the Executor."*

### 8.2 Admin Support Alert Console
*   **The Alert Indicator**: A persistent alert indicator (styled with a soft Amber-500 pulsing dot) is visible next to the Admin's session header when there are unresolved heir messages.
*   **The Drawer Panel**: Clicking the alert opens a slide-out panel listing open requests:
    *   Displays: Heir Name, message text, and timestamp.
    *   **Quick Controls**:
        1.  **Mark Resolved**: Changes status to `RESOLVED` in the database.
        2.  **Trigger Pause**: Instantly locks the session to freeze active sliders, allowing the Admin to personally contact the Heir and resolve the issue.

### 8.3 Heir "Delete My Account & Data" (GDPR Compliance)
Refer to the [Compliance Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_compliance.md#35-account-deletion-drawer-gdpr-article-17) for the user trigger, double-confirmation dialog warning, verification safety gate, and action behaviors.

### 8.4 Heir Onboarding Consent Card (GDPR Article 7 & CCPA/CPRA)
Refer to the [Compliance Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_compliance.md#31-onboarding-consent-card--age-gate) for layout tokens, privacy texts, CCPA/CPRA notice clauses, age gate checkbox logic, and accept/decline action handlers.

### 8.5 Data Portability "Export My Data" Button (GDPR Article 20)
Refer to the [Compliance Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_compliance.md#34-data-portability-trigger-gdpr-article-20) for the drawer trigger styling and JSON download behavior.

### 8.6 AI Model Transparency & Provenance Card (California AB 2013)
Refer to the [Compliance Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_compliance.md#36-ai-model-transparency--provenance-modal-california-ab-2013) for the drawer link, modal design, metadata grid, and close actions.

### 8.7 Read-Only Shared Sentimental Stories UI Component
*   **The Valuation Slider & Story Form (Heir Detail View)**:
    *   In the asset detail view, directly beneath the points allocation slider, a text area is provided for the Heir to write a personal story or memory justifying their sentimental attachment to the item.
    *   **Sharing Checkbox**: A checkbox labeled *"Share this memory with my family"* is positioned directly below the text area.
    *   **State Integration**: Activating this checkbox toggles `is_reasoning_shared = true` in the Zustand store. When valuations are submitted, this flag dictates whether the text is visible to others.
*   **Family Memories Section (Heir Detail View)**:
    *   A collapsible block titled **"Family Memories & Stories"** is rendered in the asset detail container.
    *   If another Heir has saved a valuation with `is_reasoning_shared = true`, their text is listed here.
    *   **Aesthetics**: Rendered inside a solid cream-filled card (`var(--color-bg)`) with a subtle sage border.
    *   **Layout**: Displays the sharing Heir's display name followed by their written story (e.g. *Alice Melton: "This clock stood in grandmother's hallway. I remember it chiming every Christmas..."*).
    *   **Anti-Conflict & Trust Restraints**:
        *   **No Point Leaks**: The numeric points allocated by the sharing Heir remain strictly hidden and private.
        *   **No Direct Reply Loop**: There are no reply fields, like buttons, emoji reactions, or comment inputs. The interface is strictly read-only to prevent back-and-forth arguments.
        *   **No Timestamps**: Edit or submission timestamps are excluded to prevent heirs from comparing pacing or speed.

### 8.8 Heir "Abstention Waiver" Modal UI Component
*   **Trigger**: A secondary button next to "Submit Valuations" labeled *"Abstain & Waive Allocation Rights"* (styled in plain Slate-900 border with low weight).
*   **The Modal Overlay**: When tapped, opens an organic Warm Archival Index Card modal container centered on screen (`var(--color-card-bg)` resting on `var(--color-bg)` backdrop):
    *   **Header**: *Playfair Display* serif font, 16pt, title: *"Waiver of Allocation Rights"*.
    *   **Legal Text Box**: Rendered inside a box with a solid Warm-Grey (`var(--color-border)`) border and light background (`var(--color-primary-light)`):
        > *"I, [Heir Name], hereby voluntarily abstain from the points allocation process and waive all rights to claim physical assets through the digital mediation system. I consent to having the remaining assets distributed among the participating heirs."*
    *   **Signature Input Field**: A mandatory text input box styled with a thin Warm-Grey bottom border:
        *   *Label*: *"To confirm, please type your full legal name below:"*
        *   *Input Transition*: On focus, the bottom border shifts to Sage-Green (`var(--color-primary)`) over `300ms`.
    *   **Action Controls**:
        1.  **Sign & Abstain** (Amber-500 fill, `#F59E0B`). Disabled until the input text exactly matches the Heir's **full legal name** (constructed dynamically by filtering out `null`, `None`, or empty strings from the list of `[legal_first_name, legal_middle_name, legal_last_name]` and joining the remaining non-empty elements with a single space, trimmed, case-sensitive). Using the legal name (not the display username) is required to ensure the waiver signature is legally admissible in probate court and matches the government ID on file. On click, calls `POST /api/heirs/me/abstain` with `{"legal_name_signature": "<typed legal name>"}` and updates local state.
        2.  **Cancel & Return** (Muted text button). Closes the modal and returns the user to the active valuation sliders.

### 8.9 Heir "Abstention / Non-Participation" Wait Screen UI
*   **Trigger**: Replaces the entire dashboard panel if the user's `userStatus` is updated to `'ABSTAINED'` or `'EXPIRED_NON_PARTICIPATING'`.
*   **Layout**: Centered Archival Card (`.archival-card` component styling) on a flat cream page backdrop.
*   **Typography**: *Playfair Display* header, 18pt, bold.
*   **View Variants**:
    *   **Active Abstention (`status == 'ABSTAINED'`)**:
        *   *Header*: *"Mediation Opt-Out Registered"*
        *   *Text*: *"You have voluntarily chosen to abstain from the points allocation process. Your signed waiver has been cryptographically recorded in the audit logs. You are excluded from the division math, and no assets will be allocated to you. You can return to this screen once the session is finalized by the Executor to download the final Keepsake Memory Book."*
        *   *Controls*: Displays a centered button: **"Download Signed Waiver Receipt (PDF)"** (styled in Slate-900 border with low weight). Clicking triggers the browser to call `GET /api/heirs/me/abstain/receipt` to download the server-generated single-page PDF receipt documenting the waiver text, legal name signature, timestamp, and verification hash.
    *   **Silent Non-Participation (`status == 'EXPIRED_NON_PARTICIPATING'`)**:
        *   *Header*: *"Invitation Link Expired"*
        *   *Text*: *"The invitation link for this mediation session has expired. If you did not intend to opt out or need to request a new link, please contact the Executor of the estate directly."*
    *   **Session Resumption (on `/invite/:token` check showing `USED`)**:
        *   *Header*: *"Mediation Workspace Resumption"*
        *   *Text*: *"This invitation has already been verified and onboarding is complete. If you are returning to resume your active mediation session as [username] (on a new device or after clearing cookies), please click below to enter the workspace without re-accepting consent."*
        *   *Controls*: Displays a centered primary button: **"Resume Mediation"** (Sage-Green `var(--color-primary)` background). Clicking this button issues the `POST /api/invite/login` API request, sets the session cookie, and routes the user to `/dashboard`.*

### 8.10 Admin Backup & Restore Panel UI
*   **Location**: Rendered within the Settings drawer of the Admin Console.
*   **Layout**: A dedicated section titled *"System Backup & Disaster Recovery"* (styled with a horizontal divider and a warning indicator).
*   **Controls**:
    1.  **Generate System Backup** button:
        *   *Aesthetics*: Sage-Green (`var(--color-primary)`) border, tab-rounded button.
        *   *Action*: Triggers authenticated download of `/api/system/backup`, saving the `.estate.bak` archive.
    2.  **Upload & Restore Backup** button:
        *   *Aesthetics*: Amber-500 (`var(--color-alert)`) border, tab-rounded button.
        *   *Action*: Opens standard browser file selector, accepting only `.estate.bak` files. Sends chosen file via multipart POST to `/api/system/restore`.
    3.  **Paper Recovery Key Input Field**:
        *   *Aesthetics*: Monospace text input field, labeled *"Paper Recovery Key (Optional)"*.
        *   *Description*: Used to input the 24-word recovery seed phrase if restoring on a fresh system where the original `ENCRYPTION_KEY` is not present in `.env`.
*   **Interaction State**:
    *   **Progress overlay**: During restoration, displays a full-pane loading screen: *"Restoring system state... please do not close or refresh this page."*
    *   **Success Modal**: A centered alert card confirming successful recovery and prompting page reload to refresh the active state.
    *   **Failure Banner**: Renders a warning message at the top of the panel if decryption or schema validation fails, explaining the reason without exposing encryption details.

### 8.11 Admin Setup & Paper Recovery Key Screen
*   **Trigger**: Shown automatically upon initial login if the database is uninitialized and the Admin account is being created (`POST /api/setup/admin`).
*   **Layout**: Centered Archival Card with a Playfair Display title: *"Administrative Setup & Recovery Key"*.
*   **Mnemonic Display Card**:
    *   *Aesthetics*: A distinct, light-grey monospace panel with a dashed border.
    *   *Content*: Displays the generated 24-word BIP39 mnemonic Paper Recovery Key in a clear 3x8 word grid.
    *   **Warning Banner**: A bold yellow alert box: **"WARNING: Store this key offline in a secure physical location (such as a safe). If your host device fails, this 24-word key is the ONLY way to decrypt and restore your backups. If lost, your backups are permanently unrecoverable."**
*   **Confirmation Field**:
    *   *Action*: The "Proceed to Console" button is disabled until the Admin checks a confirmation box: *"I have copied and verified my 24-word Paper Recovery Key and understand it cannot be recovered if lost."*

### 8.12 Heir FAQ & Help Drawer
*   **Trigger**: A question mark icon button `(?)` (styled in Slate-600, low contrast) placed in the global Heir Dashboard header.
*   **Layout**: Clicking it slides out a right-hand drawer (`var(--color-card-bg)` background, Sage border) listing the categorized Heir FAQs in an accordion layout. It dynamically merges general system FAQs with a dedicated top-level section: **"Estate Specific Guidelines"** containing the Executor's custom FAQs. Clicking a question expands the answer smoothly over 300ms using CSS height transitions.

### 8.13 Admin Help Portal
*   **Trigger**: A *"Quick-Start & FAQ Guide"* link is placed at the top of the Admin Console navigation sidebar.
*   **Layout**: Opens a full-screen modal card styled with standard Archival tokens, utilizing a single, elegant scrolling narrative view (ditching multi-tab menus to maintain focus and ease of reading). It guides the Executor chronologically:
    1.  *Snap & Catalog Guide*: How to snap photos, use local OCR, and dictate voice stories.
    2.  *Disaster Recovery & Keys*: Write-down instructions for the 24-word seed phrase and how to perform database restores.
    3.  *Probate / Fiduciary Checklist*: Unified Probate Code summary, specific devises pre-allocations, and E-SIGN waiver legal rules.
    4.  *Troubleshooting*: Service status indicators (local Ollama / Kokoro threads).
    5.  *Estate Specific Guidelines (FAQ Editor)*: An inline FAQ manager situated at the bottom of the page, allowing the Admin to create, edit, or delete custom FAQ rows (`POST/PUT/DELETE /api/sessions/{session_id}/faqs`). Custom items update immediately on Heir dashboards.

### 8.14 Custom Session Announcement UI Components

#### Admin Announcement Console
*   **Placement**: Rendered in a panel labeled *"Active Session Announcement"* on the Admin Dashboard console.
*   **Input Controls**:
    *   A multiline text input (up to 500 characters) to draft or edit the announcement text.
    *   A **"Broadcast Announcement"** button (styled in Sage-Green `var(--color-primary)` background) to commit and dispatch via `PUT /api/sessions/{session_id}/announcement`.
    *   A **"Clear Announcement"** button (styled in low-contrast Slate border) to clear the active announcement.
*   **Aesthetics**: Follows the `.archival-card` component design.

#### Heir Dashboard Alert Banner
*   **Trigger**: Active whenever a session contains a non-null `announcement` value.
*   **Layout**: A sticky horizontal alert bar spanning the top of the Heir Dashboard workspace, immediately below the points status bar.
*   **Aesthetics**: 
    *   *Background*: `var(--color-alert-light)` (Amber-50).
    *   *Border*: `1px solid var(--color-alert)` (Amber-500).
    *   *Text color*: `var(--color-text)` (Slate-900).
    *   *Icon*: A small solid Warning/Megaphone icon in Amber-500.
*   **Dismissal**: Includes a small "Dismiss" text button. Clicking it collapses the banner locally for the current browser session. A fresh broadcast or login re-displays the banner.

#### Heir Login Announcement Modal
*   **Trigger**: Displayed automatically when the Heir accepts the invite or logs in, IF a non-null `announcement` exists AND has not been acknowledged in local storage for this device/session.
*   **Layout**: A centered `.archival-card` modal overlay with a Playfair Display title: *"Important Estate Notice"*.
*   **Content**: Renders the raw announcement text in high contrast (`var(--color-text)`).
*   **Required Action**: A centered **"Acknowledge & Close"** button (Sage-Green `var(--color-primary)`). Clicking this button writes an acknowledgement flag to local storage and closes the modal, enabling normal slider and chat interactions.

### 8.15 Legal Identity Verification UI Components

#### Heir Onboarding Consent Card
*   **Location**: Rendered within the public Onboarding Consent card block on the `/invite/:token` route.
*   **Profile Summary Form**:
    *   Displays pre-filled, directly editable text input fields containing the Heir's registered legal details (First Name, Middle Name, Last Name, DOB, Relationship, Email, Phone, Address) pre-populated from the Executor's setup entries.
    *   If an Heir spots a typo, they can modify these fields directly inside the form inputs.
    *   Features a single mandatory checkbox: *"I confirm that I am at least 18 years of age, verify that my legal profile is correct, and explicitly agree to the Privacy Policy and E-SIGN Electronic Records Disclosure."*
    *   Tapping the "Accept & Enter Workspace" button (disabled until checkbox is checked) packages these profile fields and submits them directly in the request body of the public `POST /api/invite/verify` endpoint. No authenticated profile or ID upload API calls are triggered.

#### Heir Dashboard Identity Form
*   **Location**: Rendered as a prominent workspace card overlay on the `/dashboard` page only when the Heir's status is `'PROFILE_HOLD'` (which occurs immediately after onboarding login, or if they update their legal fields from settings later).
*   **Government ID Camera Scanner (Mobile)**:
    *   Tapping the *"Scan ID"* button triggers the rear camera directly.
    *   Renders a card-shaped graphic overlay on the live camera viewport.
    *   Snaps the ID image automatically on alignment, converts it to encrypted bytes, and uploads it via the authenticated `POST /api/heirs/me/upload-id` endpoint (succeeds because the Heir now has the JWT session cookie).
*   **Government ID Drop Slot (Desktop)**: A simple drag-and-drop target labeled *"Drop ID Scan / Photo Here"* with fallback file selection, uploading files via `POST /api/heirs/me/upload-id`.
*   **Status Indicator**: A soft, italicized label: *"Your ID is encrypted locally with AES-256 and is permanently deleted as soon as your profile is verified by the Executor."*
*   **Edit Profile Button**:
    *   Features an *"Edit Profile"* button. Clicking it allows the Heir to modify their legal and contact details, calling the authenticated `PUT /api/heirs/me/profile` endpoint. If any legal fields are changed, it resets the Heir's status to `'PROFILE_HOLD'`, deletes any existing ID scan from disk storage, and prompts them to upload a new ID document.

#### Admin "Inspect ID" Modal
*   **Trigger**: A click on a row in the **TanStack Session Monitor Table** where `identity_verified = False` and `id_scan_uri != NULL`.
*   **Layout**: A large centered modal styled with Playfair Display title: *"Inspect Beneficiary Identity"*.
*   **Content Split Pane**:
    *   **Left Side**: Displays the decrypted image of the Heir's uploaded ID document (e.g. Driver's License or Passport) fetched from the backend. The image is rendered inside a scrollable, zoomable canvas.
    *   **Right Side**: Displays the Heir's submitted details side-by-side:
        *   *Legal Name*: First Middle Last
        *   *Date of Birth*: YYYY-MM-DD
        *   *Relationship*: Son/Daughter/etc.
        *   *Contact Info*: Email, Phone, Physical Address
*   **Action Controls**:
    1.  **Approve Identity**: Styled in Sage-Green (`var(--color-primary)`). Calls `POST /api/heirs/{heir_id}/verify-identity` to mark the profile verified, delete the temporary ID image file from storage, and close the modal.
    2.  **Reject & Flag**: Styled in Amber-500 (`var(--color-alert)`). Triggers a dialog allowing the Executor to type a correction note (e.g., *"Name spelling on ID does not match profile"*). Calls `POST /api/heirs/{heir_id}/verify-identity` with `action: reject` and the rejection reason. This immediately purges the uploaded ID scan from disk storage, resets `id_scan_uri = NULL`, sends an alert to the Heir's dashboard via WebSocket, transitions the Heir to `'PROFILE_HOLD'` state, and prompts them to re-upload.
    3.  **Cancel**: Closes the modal without modifications.




