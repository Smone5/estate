# Phase 5: Frontend Architecture, Zustand, & Routing

## Phase Objective
Structure the React Vite application shell, Zustand global stores, custom client routing guards, legal disclaimer footers, and Admin configuration/setup/components panels. Note: A 2 to 3 business day schedule buffer is injected between Phase 5 and Phase 6 to allow frontend routing/store state to stabilize before WebSocket hooks depend on them. WebSocket connection hooks (T23–T25) are structurally fragile to changes in Zustand store shape, and the Admin Routing guards (T19) must be in their final form before the Admin Voice Recorder Widget (T45) is wired.

## Technical Specifications References
* [Technical Frontend Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_frontend.md)
* [UI/UX Component & Layout Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_ui.md)
* [Compliance & Privacy Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_compliance.md)
* [Legal Estate & Probate Compliance Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_legal.md)

## Detailed Requirements & Architecture
1. **Design System & CSS Styling tokens**:
   * Set up Global CSS tokens in `index.css` defining the Archival Index Card styling: Cream-50 background (`#FDFBF7`), Card background (`#FFFFFF`), Slate-900 text (`#1E293B`), Warm-Grey borders (`#E6DFD3`), and Sage-Green action tokens (`#4A6741`).
   * Code custom CSS rules for rigid `.archival-card` designs (box-shadow offset, 4px border-radius), `.tabular-value` tabular numerals, and `.archival-slider` square folder-tab thumbs.
   * **Print-specific CSS**: Implement `@media print` rules stripping backgrounds, shadows, and navigation elements. Add `.print-only` display utilities and `.no-print` hide classes. Ensure cryptographic seal blocks render in monospace with sufficient contrast for photocopy reproduction per DB Spec §7.

2. **Zustand Global Store (`useMediationStore`)**:
   * Define store variables: `session_id`, `heir_id`, `userRole`, `userStatus`, `assets`, `valuations`, `unallocatedPoints` (default: 1000), `messages`, `isPaused`, `isDeadlocked`, `is_hitl_suspended`, `sessionStatus`.
   * **Auto-Balance Points Guard**: Implement proportional rebalancing checks in the store. Disable rebalancing if the sum of all points is 0 to prevent Division by Zero (`NaN` / `Infinity`) errors.
   * **Debounced Bulk Draft Sync**: Implement draft actions debouncing slider adjustments and text inputs for 1.5 seconds. Flush updates via `PUT /api/sessions/{session_id}/valuations/draft`. If the network is offline, buffer the sync payload and flush immediately upon connection. Handle `409 Conflict` REST responses by updating store values from server states.
3. **TanStack Query Configurations**:
   * Implement queries for cache keys: `queryKeys.assets`, `queryKeys.session`, `queryKeys.valuations`, and `queryKeys.profile` (`GET /api/heirs/me`).
4. **Client Routing**:
   * Map client paths in `App.jsx` using React Router:
     * `/invite/:token` (loads invitation check; renders Session Resumption card if used, or Onboarding Consent if unused).
     * `/dashboard` (protected path).
     * `/admin` (protected path).
     * `/opt-out` (exits onboarding).
5. **Conditional UI Layout Rendering Guards**:
   * Disable sliders, text inputs, and chat panels (`disabled = true`) if any of these conditions are met:
     1. *Setup Phase*: `sessionStatus == 'SETUP'` (renders Setup Wait banner).
     2. *Profile Hold*: `userStatus == 'PROFILE_HOLD'` (renders Hold banner, mounts the Government ID scanner overlay card).
     3. *Grief Pause*: `isPaused == true` (renders Amber Pause banner).
     4. *User Submitted*: `isSubmitted == true` (replaces slider thumbs with flat point badges, locks inputs).
     5. *Deadlocked*: `isDeadlocked == true` (renders Conflict Review banner).
     6. *Sum Validation Hold*: `is_hitl_suspended == true` (renders the Sum Validation Hold error banner: *"Points submission suspended. Your allocations require review and correction by the Executor."*, and disables points sliders, numerical input boxes, and chat panel, while keeping draft saving and the proportional auto-balance points button enabled).
   * **Finalization Swap**: If `sessionStatus == 'FINALIZED'`, replace the entire dashboard pane with the Keepsake Memory Book view.
   * **Abstention / Non-Participation Wait Screen**: Mount the centered non-participation screen if `userStatus` is `'ABSTAINED'` or `'EXPIRED_NON_PARTICIPATING'`. Both statuses render the same wait-screen component.
6. **Semantic Vector Search UI**:
   * Build the search bar at the top of the asset gallery. Connect it to the backend's vector similarity search endpoint.
   * Implement the filter panel: Category checkboxes (`Jewelry`, `Furniture`, `Art`, `Other`), Allocation filter (All / Allocated / Unallocated / Pre-Allocated), Spoken Provenance toggle, and Shared Stories toggle.
   * Implement sorting dropdown (Relevance, My Points High/Low, Title A-Z, Category).
   * Render Sage Green confidence pills (e.g. `"90% Match"`) on results with similarity ≥ 75%.
   * Display the zero-match fallback state with the **"Ask the Mediator"** button that auto-injects the query into the chat panel.
7. **FAQ/Help UI Components**:
   * Build the **Heir FAQ Drawer**: A right-hand side-out drawer triggered by the `(?)` icon in the Heir header. Renders general FAQs in accordion format plus a dynamic **"Estate Specific Guidelines"** section populated from `GET /api/sessions/{session_id}/faqs`.
   * Build the **Admin Help Portal**: A full-screen modal with the scrolling Quick-Start tutorial. Includes the inline FAQ Editor at the bottom allowing Admin to create, edit, and delete custom FAQ entries.
8. **Session Announcement UI Components**:
   * Build the **Admin Announcement Console**: Multiline text input + "Broadcast" and "Clear" buttons in the Admin panel, wired to `PUT /api/sessions/{session_id}/announcement`.
   * Build the **Heir Sticky Alert Banner**: Rendered at the top of the Heir dashboard when `announcement != null`. Dismissable per session. Uses Amber-500 styling.
   * Build the **Heir Login Announcement Modal**: Auto-displayed on login if an unacknowledged announcement exists. Requires "Acknowledge & Close" to proceed. Writes acknowledgment to localStorage.
9. **Active Abstention Waiver UI Components**:
   * Build the **Heir Active Abstention Waiver button** (secondary button next to "Submit Valuations"), legal name signature verification modal, and post-abstention wait screen containing the "Download Signed Waiver Receipt (PDF)" button. Validate signature text matches concatenated legal first+middle+last name without nulls.
   * **Extended for `'EXPIRED_NON_PARTICIPATING'`**: The same centered wait-screen component must render for both `'ABSTAINED'` and `'EXPIRED_NON_PARTICIPATING'` statuses.
10. **Admin Inventory Dashboard UI**:
      * Build the Admin catalog staging card, edit metadata form, pre-allocation dropdowns, and publish buttons. **Includes permanent notice: "This system is strictly for personal property and keepsakes. Do not upload real estate, vehicles, or bank/financial accounts." per Legal Spec §4.**
11. **Admin Session Control UI**:
      * Build the Executor dashboard panel to manage heir profiles, send invitation emails, track progress with checkmark status tables, pause/unpause sessions, and trigger the finalization solver.
12. **Admin Onboarding & Credentials Setup UI**:
      * Build the first-boot interface displaying the 24-word BIP39 paper recovery seed phrase and requiring confirmation before enabling session creation.
13. **GDPR Data Portability UI Button**:
      * Build the 'Export My Data (JSON)' button in the settings/help drawer. Trigger an authenticated fetch to `GET /api/heirs/me/export` and download the structured JSON file.
14. **GDPR Account Deletion UI Drawer**:
      * Build the slide-out warning drawer for account deletion. Prompt a warning modal explaining soft-anonymization and deletion of chat logs, requiring the case-sensitive username confirmation input to enable deletion.
15. **Legal Disclaimer Footer (T73_UI)**:
      * Build the permanent legal disclaimer footer component rendered on all dashboard views (both Heir and Admin). Displays: *"Disclaimer: The Estate Steward is a collaborative mediation aid designed to assist executors and heirs in dividing personal property. It does not provide legal advice, estate planning, or tax counsel. Use of this tool does not guarantee probate court approval. Executors are advised to consult with a licensed probate attorney regarding their fiduciary obligations and court filings."* per Legal Spec §5.

## Phase Checklist & Tasks

### [x] Task T17: Frontend Vite Base & Vanilla CSS
* **Objective**: Configure Vite, React index files, and define Vanilla CSS global tokens and archival layout cards. **Must include `@media print` CSS rules for printable paper records per DB Spec §7.**
* **Verification**: Verify visual index card layouts render with rigid offset shadows. Verify that `window.print()` produces legible printer-friendly output with visible cryptographic seals.

### [x] Task T18: Zustand store & cache keys
* **Objective**: Build `useMediationStore` implementing state variables (including `is_hitl_suspended`), points calculation math, and debounced draft saving.
* **Verification**: Verify slider changes deduct points from the 1000-point unallocated pool in state, and confirm the store successfully holds and updates `is_hitl_suspended`.

### [x] Task T19: Client Routing & Onboarding views
* **Objective**: Program React Router pages, onboarding checkbox gates, the Session Resumption layout, and the Onboarding Consent card layout containing the legally required E-SIGN Act Consumer Disclosure Banner. **Additionally, implement the pre-filled legal profile summary card (rendered as editable text inputs to support typo correction) with confirmation checkbox per Compliance Spec §3.1. Also implement the Executor acknowledgment checkbox during session initialization confirming the advisory nature of algorithm results per Legal Spec §5.**
* **Verification**: Verify that used tokens bypass consent screens, mounting resumption cards. Check that E-SIGN disclosures render correctly on onboarding. Verify that the legal profile summary card displays pre-filled details as editable text inputs with a confirmation checkbox. Verify that the executor acknowledgment checkbox is required before session creation is unlocked.

### [x] Task T20: Heir & Admin Dashboard View Guards
* **Objective**: Code layout wrappers enforcing Setup, Hold, Pause, Sum Validation Hold (HITL_GUARD suspension), and Submission locks. Render the permanent low-contrast SB 1001 Bot Disclosure banners ("Chatting with AI Mediator" top banner on mobile, and "AI Mediator Agent" header on desktop), and the Sum Validation Hold warning banner (*"Points submission suspended. Your allocations require review and correction by the Executor."*). **(Note: SB 942 'Synthesized AI Voice' synthetic voice labels are NOT owned by T20 — this responsibility is consolidated under T25.)**
* **Verification**: Verify that setting isPaused = true or is_hitl_suspended = true in state disables sliders and chat, and check that the AI Mediator banner renders permanently on the respective views. Verify that draft saving remains enabled during Sum Validation Hold.

### [x] Task T73_UI: Legal Disclaimer Footer Component
* **Objective**: Build the permanent legal disclaimer footer component rendered on all dashboard views (Heir and Admin). Display the full disclaimer text per Legal Spec §5. Must be non-dismissable and visible on every route after authentication (not on the public onboarding page to avoid clutter, but on `/dashboard`, `/admin`, and all sub-routes).
* **Verification**: Verify that the disclaimer footer is rendered on both Heir and Admin dashboard views and contains all required disclaimer language. Verify it does not appear on the public `/invite/:token` onboarding page.

### [x] Task T32: Government ID Scanner & File Drop UI
* **Objective**: Build the HTML5 rear-camera overlay guide and desktop drag-and-drop ID scan file upload UI cards on the frontend dashboard. Ensure it renders only under `'PROFILE_HOLD'` status, and not on the public onboarding page. Depends on `T31` for ID uploads.
* **Verification**: Mount the uploader on `/dashboard` with status `'PROFILE_HOLD'`, and verify that the HTML5 camera scanner opens and uploader drag-and-drop actions trigger file transmission.

### [x] Task T35: Executor Force Allocation Console UI
* **Objective**: Construct the Executor dashboard "Force Allocation Console" UI where the Executor can view deadlocked items, select winning beneficiaries, write fiduciary override reasons, and submit them via `POST /api/sessions/{session_id}/override`. Depends on `T44` for the override endpoint.
* **Verification**: Verify that under session deadlock status, the console displays contested assets and enables manual allocations.

### [x] Task T46: Semantic Search UI
* **Objective**: Build the asset gallery search bar, filter panel (category, allocation, provenance, shared stories toggles), sorting controls, confidence badge rendering, and zero-match fallback state with the "Ask the Mediator" chat injection button.
* **Verification**: Enter a search query and verify filtered results render with confidence pills. Verify zero results show the fallback card and the "Ask the Mediator" button pre-fills the chat input.

### [x] Task T47: FAQ/Help UI Components
* **Objective**: Build the Heir FAQ drawer accordion drawer (triggered by `(?)` header icon) showing static FAQs plus dynamic estate-specific FAQs from the API. Build the Admin Help Portal full-screen modal with the 5-section scrolling tutorial and inline FAQ editor.
* **Verification**: Verify FAQ drawer opens, accordion items expand, and estate-specific FAQs load dynamically. Verify Admin can create, edit, and delete FAQ entries from the Help Portal.

### [ ] Task T48: Session Announcement UI Components
* **Objective**: Build the Admin Announcement Console (broadcast/clear inputs), the Heir sticky Amber-500 alert banner (dismissable, reads `announcement` from session state), and the Heir login modal (shown if announcement unacknowledged, blocks interaction until "Acknowledge & Close" is clicked).
* **Verification**: Set an announcement as Admin. Verify Heir dashboard shows the banner. Dismiss it and verify it collapses. Log in again and verify the modal appears before sliders are enabled.

### [ ] Task T51: Active Abstention Waiver UI Components
* **Objective**: Build Heir Active Abstention Waiver button, legal name signature verification modal, and post-abstention wait screen with PDF receipt download trigger. **Extended to also handle the `'EXPIRED_NON_PARTICIPATING'` state.**
* **Verification**: Verify that the "Sign & Abstain" button is disabled until the signature input matches the concatenated legal name (ignoring null middle names). Test that clicking it calls the abstain endpoint, redirects to the wait screen, and shows the PDF receipt download button.

### [ ] Task T52: Admin Inventory Dashboard UI
* **Objective**: Build the Admin catalog staging card, edit metadata form, pre-allocation dropdowns, and publish buttons. **Includes permanent notice: "This system is strictly for personal property and keepsakes. Do not upload real estate, vehicles, or bank/financial accounts." per Legal Spec §4.** Depends on T17, T18, and T11.
* **Verification**: Verify that staging upload assets and editing their values operates reactively, updating status on save. Verify that the legal scope notice is permanently visible on the inventory dashboard.

### [ ] Task T53: Admin Session Control UI
* **Objective**: Build the Executor dashboard panel to manage heir profiles, send invitation emails, track progress with checkmark status tables, pause/unpause sessions, and trigger the finalization solver. Depends on T17, T18, T13, T34, T37, and T16.
* **Verification**: Verify pause/unpause locks and unlocks screens, adding heirs triggers invite emails, and finalize triggers division outcome rendering.

### [ ] Task T54: Admin Onboarding & Credentials Setup UI
* **Objective**: Build the first-boot interface displaying the 24-word BIP39 paper recovery seed phrase and requiring confirmation before enabling session creation. Depends on T17, T18, T39, and T27.
* **Verification**: Verify the Setup Admin wizard enforces offline confirmation of the recovery phrase before unlocking dashboard pathways.

### [ ] Task T27: BIP39 Mnemonic Onboarding Screen
* **Objective**: Create 24-word paper recovery seed phrase display screen for onboarding setup confirmation. Depends on T18 and T39.
* **Verification**: Verify the seed phrase display screen renders the 24-word grid and enables the confirmation checkbox.

### [ ] Task T58: GDPR Data Portability UI Button
* **Objective**: Build "Export My Data (JSON)" button in the settings/help drawer. Depends on T17, T18, and T57.
* **Verification**: Verify that clicking the button triggers a download of a JSON file with heir data.

### [ ] Task T59: GDPR Account Deletion UI Drawer
* **Objective**: Build the slide-out account deletion drawer, warnings, case-sensitive username confirmation input, and action triggers. Depends on T17, T18, and T55.
* **Verification**: Verify that typing the incorrect username leaves the deletion button disabled, and typing it correctly calls the soft-anonymization endpoint.

### [ ] Task T56: BIP39 Mnemonic Restore Panel
* **Objective**: Create the recovery seed input fields on the Admin Restore panel UI for backup decryption. Depends on T18 and T26.
* **Verification**: Verify that the restore panel allows entry of a 24-word seed phrase, checking formatting and word length.

### [ ] Task T66: Family Memories & Stories UI Component
* **Objective**: Build the collapsible, read-only "Family Memories & Stories" section in the Heir's asset detail container. Renders shared stories with no reply or reaction options, and locks text boxes during un-submitted or paused sessions. Depends on T17, T18.
* **Verification**: Verify that clicking the section expands the family memories stack showing other heirs' display names and descriptions, while disabling text entries if the session is paused or submitted.

### [ ] Task T67: Admin "Inspect ID" Modal Component
* **Objective**: Build the split-pane verification card for Admin. Left pane shows the decrypted ID scan in a scrollable canvas, right pane displays heir's legal details side-by-side. Connects approve/reject triggers. Depends on T17, T18, T34.
* **Verification**: Verify that opening the modal shows the image and details side-by-side, and that clicking approve/reject fires the verify-identity API endpoint.

### [ ] Task T68: Heir "Request Help" Modal Component
* **Objective**: Build the slide-up modal for Heirs to request assistance from the Executor. Displays name, text field, character counter, and sends to the help/support endpoint (`POST /api/sessions/{session_id}/help`, matching Backend Spec §9.4). Depends on T17, T18, T42.
* **Verification**: Verify that Heirs can type help messages, validation blocks short queries (<5 chars), and successful post displays confirmation and sends an alert.

### [ ] Task T69: Auto-Balance Points Button UI
* **Objective**: Build the proportional points balance button inside the Heir's valuations panel. Displays dynamic distribution adjustments when clicked, with a division-by-zero guard disabled if allocations == 0. Depends on T17, T18.
* **Verification**: Set allocations to non-zero values (e.g. sum is 500) and verify that clicking the button distributes the remaining 500 points proportionally across active assets. Check that if sum is 0, the button is disabled.

### [ ] Task T28b: Backend Tests — Phases 4–5 Scope
* **Objective**: Write `pytest` coverage for fairpyx solver tie-breakers, ReportLab PDF layouts, finalization router, valuation submission locking, GDPR erasure router, GDPR data portability, active abstention waiver, tie-breaker records, and proof of notice log contracts. **Run at end of Phase 5.** Depends on T12, T14, T15, T16, T33, T55, T57, T70, T71.
* **Verification**: Execute `pytest backend/tests/` and verify Phase 4–5 tests pass.

## Phase Dependency Graph
```mermaid
graph TD
    T17[T17: Frontend Vite Base & Vanilla CSS] --> T18[T18: Zustand store & cache keys]
    T18 --> T19[T19: Client Routing & Onboarding views]
    T17 --> T19
    T18 --> T20[T20: Heir & Admin Dashboard View Guards]
    T19 --> T20
    
    T17 --> T73_UI[T73_UI: Legal Disclaimer Footer Component]
    T18 --> T73_UI
    
    T17 --> T32[T32: Government ID Scanner & File Drop UI]
    T18 --> T32
    T19 --> T32
    T31[T31: Government ID Scan Upload API] --> T32
    
    T18 --> T35[T35: Executor Force Allocation Console UI]
    T20 --> T35
    T44[T44: Session Override API] --> T35
 
    T17 --> T46[T46: Semantic Search UI]
    T18 --> T46
 
    T17 --> T47[T47: FAQ/Help UI Components]
    T18 --> T47
    T43[T43: Custom FAQ CRUD API] --> T47
 
    T17 --> T48[T48: Session Announcement UI Components]
    T18 --> T48
    T37[T37: FastAPI Session Lifecycle & Announcement API] --> T48

    T17 --> T51[T51: Active Abstention Waiver UI Components]
    T18 --> T51
    T20 --> T51
    T33[T33: Active Abstention Waiver PDF Receipt & Email] --> T51

    T17 --> T52[T52: Admin Inventory Dashboard UI]
    T18 --> T52
    T11[T11: FastAPI Asset Router] --> T52

    T17 --> T53[T53: Admin Session Control UI]
    T18 --> T53
    T13[T13: FastAPI Heir Management & Invitations] --> T53
    T34[T34: Executor ID Verification State Transition API] --> T53
    T37 --> T53
    T16[T16: FastAPI Keepsake & Finalization Router] --> T53

    T17 --> T54[T54: Admin Onboarding & Credentials Setup UI]
    T18 --> T54
    T39[T39: Admin Setup & Session Creation API] --> T54
    T27[T27: BIP39 Mnemonic Onboarding Screen] --> T54

    T18 --> T27
    T39 --> T27

    T17 --> T58[T58: GDPR Data Portability UI Button]
    T18 --> T58
    T57[T57: FastAPI GDPR Data Portability API] --> T58

    T17 --> T59[T59: GDPR Account Deletion UI Drawer]
    T18 --> T59
    T55[T55: FastAPI Heir GDPR Erasure Router] --> T59

    T17 --> T56[T56: BIP39 Mnemonic Restore Panel]
    T18 --> T56
    T26[T26: pg_dump System Backup & Restore] --> T56

    T17 --> T66[T66: Family Memories & Stories UI Component]
    T18 --> T66
    
    T17 --> T67[T67: Admin "Inspect ID" Modal Component]
    T18 --> T67
    T34 --> T67

    T17 --> T68[T68: Heir "Request Help" Modal Component]
    T18 --> T68
    T42[T42: Support Request & Help CRUD API] --> T68

    T17 --> T69[T69: Auto-Balance Points Button UI]
    T18 --> T69

    T12[T12: FastAPI Valuation Router] --> T28b[T28b: Backend Tests — Phases 4-5 Scope]
    T14[T14: ReportLab PDF Builders] --> T28b
    T15[T15: Fairpyx MNW Solver & Tie-Breakers] --> T28b
    T16[T16: FastAPI Keepsake & Finalization Router] --> T28b
    T33[T33: Active Abstention Waiver PDF Receipt & Email] --> T28b
    T55[T55: FastAPI Heir GDPR Erasure Router] --> T28b
    T57[T57: FastAPI GDPR Data Portability API] --> T28b
    T70[T70: Tie-Breaker Resolution Record in PDF] --> T28b
    T71[T71: Proof of Notice Log Data Contract] --> T28b