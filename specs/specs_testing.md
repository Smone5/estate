# Estate Steward: Testing & Verification Specification (v1.0)

This specification defines the test suites, verification assertions, and mock boundaries required to prove the implementation of **The Estate Steward** is correct, secure, and complete. All tests are written using `pytest` and `pytest-asyncio` for the backend, and standard testing libraries for the frontend.

---

## 1. Backend Unit Tests (`pytest`)

### 1.1 Authentication & Compliance Guards
*   **Test Admin Hashing & Login**:
    *   Verify that seeding the admin account hashes passwords using Argon2 (`argon2-cffi`).
    *   Verify `POST /api/auth/login` returns a secure, HTTP-only JWT cookie on success and throws `401 Unauthorized` on incorrect credentials.
    *   Verify `GET /api/auth/me` restores a valid Admin cookie with `role = 'ADMIN'`, returns `session_id = null` or the encoded Admin session scope, and refreshes the cookie according to the configured session lifetime.
    *   Verify `GET /api/auth/me` restores a valid Heir cookie with `role = 'HEIR'` and the correct `session_id`, and rejects expired, malformed, or revoked cookies with `401 Unauthorized`.
    *   Verify role boundaries during restoration: a Heir cookie must not satisfy Admin-only authorization, and an Admin cookie must not satisfy Heir-only profile/session endpoints.
    *   Verify `POST /api/auth/logout` clears the HTTP-only cookie idempotently and prevents subsequent `GET /api/auth/me` restoration.
*   **Test Invite Consent & Onboarding Bootstrapping (BUG-61)**:
    *   Verify `POST /api/invite/verify` fails with `400 Bad Request` if `consent_accepted`, `privacy_notice_acknowledged`, or `age_verified` is `false`.
    *   Verify `POST /api/invite/verify` fails with `400 Bad Request` if the invitation token's `invite_token_expires_at` is in the past, preventing expired link logins.
    *   Verify that if flags are `true` and the token is not expired, database updates `invite_token_used = True`, sets consent fields, records `consent_timestamp`, updates profile details from the request payload (`legal_first_name`, `legal_middle_name`, `legal_last_name`, `relationship_to_decedent`, `date_of_birth`), transitions the Heir's status to `'PROFILE_HOLD'`, and issues the HTTP-only JWT cookie.
    *   Verify that unauthenticated requests to `PUT /api/heirs/me/profile` and `POST /api/heirs/me/upload-id` fail with `401 Unauthorized`.
*   **Future Test OIDC / Federated Identity Security**:
    *   Verify OIDC login uses Authorization Code Flow with PKCE, validates `state`, `nonce`, issuer, audience, expiry, and signature, and rejects invalid callback parameters.
    *   Verify external identities are linked and resolved by `issuer + subject`, not email alone.
    *   Verify Admin SSO linking requires an already-authenticated Admin session and cannot remove the last usable Admin login method.
    *   Verify Heir SSO linking is unavailable during invite acceptance and `PROFILE_HOLD`.
    *   Verify Heir SSO linking succeeds only after Executor identity approval (`identity_verified = true`, status `'ACTIVE'` or later).
    *   Verify a provider account with a matching email but different `issuer + subject` cannot claim an invite or existing account.
*   **Test GDPR Erasure (Soft Anonymization & Checkpointer Cleanup)**:
    *   Verify `DELETE /api/heirs/me` performs soft anonymization for both submitted and unsubmitted heirs (preserving the user row with display name anonymized to `"Anonymized Beneficiary [UUID]"`, other PII columns set to `NULL`, and deleting all private chat messages).
    *   If the Heir is unsubmitted (`is_submitted = False`), verify the system deletes their default valuations and sets their status to `'ABSTAINED'`.
    *   If the Heir is submitted (`is_submitted = True`), verify the system preserves their valuations, public shared memories, and status as `'SUBMITTED'`.
    *   Verify that `DELETE /api/heirs/me` (and Admin heir deletion) decrypts, sanitizes PII (legal names/contact details), and re-encrypts historical snapshots stored in the `audit_logs.state_snapshot` column.
    *   Verify that for both paths (and when an Admin deletes an Heir via `DELETE /api/sessions/{session_id}/heirs/{heir_id}`), all database records in the LangGraph checkpointer tables (e.g. `checkpoints` and `checkpoint_writes`) matching the Heir's thread ID (`f"{session_id}:{heir_id}"`) are permanently deleted.
    *   Verify deletion returns `400 Bad Request` if the session's status is `'LOCKED'` or `'FINALIZED'`.
*   **Test GDPR Portability Export**:
    *   Verify `GET /api/heirs/me/export` returns a structured JSON payload containing the decrypted chat history, valuations, and support logs.
*   **Test Mediation Confidentiality Access Control**:
    *   Verify `GET /api/sessions/{session_id}/heirs/{heir_id}/chat` returns the conversation history when called with the matching Heir's JWT cookie.
    *   Verify that if the same endpoint is called with Admin credentials, it is rejected with a `403 Forbidden` status code, enforcing the confidentiality of the active listening transcripts.
*   **Test Invitation Notice Tracking**:
    *   Verify `POST /api/sessions/{session_id}/heirs` and `POST /api/heirs/{heir_id}/invite-token` correctly set `created_at` and `invite_token_expires_at` based on configured notice window (defaulting to 14 days from creation).
    *   Verify `POST /api/heirs/{heir_id}/send-invite` sends an SMTP message and records `invitation_dispatched_at = UTC_NOW` on successful relay.
*   **Test Keepsake Email Dispatch**:
    *   Verify `POST /api/sessions/{session_id}/keepsake/email` triggers a background task that compiles the Keepsake PDF and dispatches it via async SMTP.
    *   Verify that if called by an Admin without a specific `heir_id` target, the system queues email dispatches for *all* registered active/submitted heirs in the session.
*   **Test Profile Update and ID Invalidation**:
    *   Verify `PUT /api/heirs/me/profile` resetting identity verification also deletes the physical encrypted ID scan file from storage and sets `id_scan_uri = NULL` in the database when legal fields are changed.
*   **Test Active Abstention Flow**:
    *   Verify `POST /api/heirs/me/abstain` checks status, records the `'ABSTENTION_WAIVER'` audit log event block (storing IP, timestamp, and signature name), cascade deletes default valuations, and updates user status to `'ABSTAINED'`.
    *   Verify that if the E-SIGN/UETA waiver receipt email SMTP delivery fails, the system sets `users.waiver_email_failed = True` and auto-generates a system support request ticket in the database.
    *   Verify `GET /api/heirs/me/abstain/receipt` generates and returns a valid single-page PDF receipt.
*   **Test Finalization Status Transition Logic**:
    *   Verify that during `POST /api/sessions/{session_id}/finalize`, non-submitting users with expired invitation tokens are automatically transitioned to `'EXPIRED_NON_PARTICIPATING'` and non-submitting active users are marked as `'ABSTAINED'`.
    *   Verify that both statuses are correctly excluded from the `fairpyx` preferences matrix division.
    *   Verify that `POST /api/sessions/{session_id}/finalize` successfully persists the solver's asset allocations by updating each allocated asset's `status` to `'DISTRIBUTED'` and writing the winning heir ID to `allocated_to_id` in the database.
*   **Test Invite Session Resumption**:
    *   Verify `GET /api/invite/status/{token}` returns `"NEW"` for an unused token, and `"USED"` (along with username) for an already-used token.
    *   Verify `POST /api/invite/login` rejects unused tokens, and logs in already-used unexpired tokens, returning a valid JWT session cookie and user details (`session_id`, `heir_id`, `user_status`).
*   **Test Pre-Allocation Endpoint**:
    *   Verify `POST /api/assets/{asset_id}/pre-allocate` allows an Admin to assign an asset to a specific Heir during `'SETUP'` phase, transitioning the asset status to `'PRE_ALLOCATED'` and setting its `allocated_to_id`.
    *   Verify that attempting to pre-allocate an asset when session is not in `'SETUP'` returns `400 Bad Request`.
*   **Test Session Row Pessimistic Lock**:
    *   Verify that write endpoints logging to `audit_logs` (e.g. `POST .../valuations/submit`, `PUT .../heirs/me/profile`, `POST .../heirs/me/abstain`) acquire an exclusive lock (`FOR UPDATE`) on the matching `sessions` row before performing audit log operations, preventing ledger forks.
*   **Test Auto-Lock Submission Verification**:
    *   Verify that `POST /api/sessions/{session_id}/valuations/submit` checks for any remaining unsubmitted heirs whose status is in `('PENDING', 'PROFILE_HOLD', 'ACTIVE')`.
    *   Verify that if there are still heirs in `'PENDING'` status (e.g. newly invited heirs who have not onboarded yet), the deadlock detection and auto-lock logic is **not** triggered.


### 1.2 Data Security & Privacy (PII Scrubbing & Encryption)
*   **Test AES-Fernet Field Decoration**:
    *   Verify that `audit_logs.state_snapshot`, `chat_messages.message_text`, and `valuations.reasoning` values are stored in the database as encrypted ciphertext.
    *   Verify that querying the database decrypts these values transparently back to plain text.
*   **Test Microsoft Presidio Redaction**:
    *   Mock the Presidio analyzer and anonymizer engines.
    *   Verify that message texts containing PII (e.g. "My name is John Doe, email john@example.com") are scrubbed (e.g. "My name is <PERSON>, email <EMAIL_ADDRESS>") before being saved to `chat_messages.scrubbed_text` or sent to the LangGraph state.
*   **Test Cryptographic Stability of Hash Chain**:
    *   Verify that `sha256_hash` of each audit log row is computed using a PII-scrubbed version of the state snapshot JSON.
    *   Verify that soft-anonymizing the actual `state_snapshot` column during GDPR deletion (which replaces PII with `"Anonymized"`) does not change the pre-computed `sha256_hash` value, leaving the chain integrity intact.
*   **Test Dynamic AI Model Transparency**:
    *   Verify that `GET /api/system/models` returns model details dynamically based on the active `FAST_THINKER_MODEL`, `SLOW_THINKER_MODEL`, and `VISION_MODEL` environment variables.
    *   Verify that changing the environment variable value (e.g. setting `FAST_THINKER_MODEL=qwen2.5:3b-instruct` for Raspberry Pi) dynamically alters the returned model name and parameters in the response payload.

### 1.3 Staging Pipeline & Inventory Lock
*   **Test Image Upload Conversion**:
    *   Verify that the staging endpoint converts uploaded raw images (PNG, HEIC) to WebP format, scaling them to the target specifications.
*   **Test Inventory Modification Lock**:
    *   Verify `POST /api/sessions/{session_id}/assets/stage` and `POST /api/assets/{asset_id}/publish` succeed with `200 OK` when the session status is `'SETUP'`.
    *   Verify both endpoints return `400 Bad Request` when the session status is `'ACTIVE'`, `'LOCKED'`, or `'FINALIZED'`. The lock is keyed on **session status**, not on `invite_token_used`. Testing `invite_token_used` as the trigger condition would produce false positives: the flag only controls the finalization notice-window constraint, not the inventory lock.
    *   Additionally verify `DELETE /api/assets/{asset_id}` and `POST /api/assets/{asset_id}/audio` are also rejected with `400 Bad Request` under the same `'ACTIVE' | 'LOCKED' | 'FINALIZED'` status conditions.

### 1.4 Keepsake PDF Report (ReportLab)
*   **Test Paragraph Wrapping inside Tables**:
    *   Verify the PDF builder wraps long asset descriptions in `Paragraph` flowables inside table cells. Ensure no text overflows off-canvas.
*   **Test Image Downloader & Buffer**:
    *   Mock external network calls. Verify that if `STORAGE_DRIVER=GCS` or `STORAGE_DRIVER=S3` and an asset's image is a remote URL, the PDF builder downloads the bytes into an `io.BytesIO` buffer rather than passing the URL string directly to ReportLab's `Image` class.
*   **Test NumberedCanvas Pagination**:
    *   Verify that `NumberedCanvas` prints the dynamic footer `"Page X of Y"` and background canvas fill on all pages except the cover page (Page 1).
*   **Test PDF Document Content Differentiation**:
    *   Verify that `GET /api/sessions/{session_id}/heirs/{heir_id}/keepsake` generates a Keepsake Memory Book PDF with cover page, mediation summary callout, and allocated assets.
    *   Verify that `GET /api/sessions/{session_id}/keepsake` generates the Final Distribution & Probate Audit Ledger PDF containing Cover Page (Executor details), Registered Beneficiary Table, Proof of Notice Log, Final Asset Allocation Grid, and Admin Intervention Log.

### 1.5 Fair Division Math Solver (`fairpyx`)
*   **Test Maximum Nash Welfare Calculations**:
    *   Pass a preference matrix (e.g. Heir A wants Clock (600) and Ring (400); Heir B wants Clock (500) and Ring (500)) to `fairpyx.divide` using the `MaximumNashWelfare` algorithm. Verify that assets are awarded to maximize welfare (e.g. Clock to A, Ring to B).
    *   Verify that when a deadlock is detected during finalization (`POST /api/sessions/{session_id}/finalize`) (e.g., two heirs tying on their top-valued asset), the transaction updates the session status to `'LOCKED'` and `is_deadlocked = True` in the database, while rolling back any draft asset allocations.
*   **Test Zero-Utility Starvation Bypass**:
    *   Verify that if the number of active heirs who have not been pre-allocated assets exceeds the count of published `'LIVE'` assets, the solver successfully runs and distributes assets without raising a starvation error (bypassing the zero-utility starvation check).
*   **Test Deterministic Tie-Breaking**:
    *   Pass a matrix where two Heirs submit the exact same point allocations for a contested asset. Verify that the asset is awarded to the Heir with the earlier `submitted_at` timestamp.
    *   Pass a matrix where the two Heirs have the same `submitted_at` timestamp (or no timestamp). Verify that the tie-breaker falls back to sorting their user UUID `id` strings alphabetically.
    *   Verify that tie-breaker calculations complete successfully without throwing exceptions when the session `deadline` is `None` / `NULL`.
*   **Test Epsilon Epoch Conversions**:
    *   Verify that tie-breaker math formulas convert all datetime objects (such as `submitted_at` and `paused_at`) to float Unix epochs before subtraction and division to avoid Python `TypeError` and `timedelta` division errors.


### 1.6 System Backup & Restore Verification
*   **Test System Backup Archive Generation**:
    *   Verify `GET /api/system/backup` returns a binary stream of type `application/octet-stream` when requested with Admin credentials.
    *   Verify that the archive can be decrypted using the environment's `ENCRYPTION_KEY`.
    *   Verify that the decrypted archive is a valid `.tar.gz` container holding a SQL database dump and a zipped directory of `static/uploads/`.
*   **Test System Restore Transaction**:
    *   Verify `POST /api/system/restore` restores database schema and rows. Ensure all active tables are replaced and files extracted back to the local volume.
    *   Verify that restoration fails with `400 Bad Request` if the backup archive is corrupted or encrypted with a different key.
    *   Verify that the restore operation is executed as a single transaction: if any table fails to import, the entire database state rolls back to the pre-restore point.

### 1.7 Staging UX, Dynamic Settings, & Dynamic Categories Verification
*   **Test Dynamic Category Management**:
    *   Verify `GET /api/sessions/{session_id}/categories` returns default seeded categories (`'Jewelry'`, `'Furniture'`, `'Art'`, `'Other'`) for a new session.
    *   Verify `POST /api/sessions/{session_id}/categories` successfully creates a new category.
    *   Verify `DELETE /api/sessions/{session_id}/categories/{name}` is rejected with `400 Bad Request` if there are published active assets assigned to that category.
    *   Verify `DELETE /api/sessions/{session_id}/categories/{name}` succeeds and deletes the category if no assets are using it.
*   **Test Multi-Image Staging**:
    *   Verify `POST /api/sessions/{session_id}/assets/stage` accepts multiple image uploads, pre-processes/rescales them, creates an `AssetImage` row for each, and maps the primary flag.
*   **Test Admin Settings Management**:
    *   Verify `GET /api/admin/settings` returns allowed registry keys, masking secrets (`is_set: true/false`).
    *   Verify `POST /api/admin/settings` writes encrypted values to `app_settings` and mirrors them directly into `os.environ` to dynamically update LLM provider and SMTP settings without a restart.
*   **Test WebSocket Connection Routing**:
    *   Verify that active WebSocket sessions receive broadcast notifications for pause states, and that disconnected sockets are cleanly discarded.

---

## 2. System & Integration Tests (E2E Flows)

### 2.1 LangGraph State Machine Tracing
These tests verify the state transition path of the compiled state machine:
*   **Conversational Path (`Intent == CHAT_MEDIATION`)**:
    *   Inject user message. Verify the router routes to `RETRIEVE_RAG` (System 2) $\rightarrow$ `FAST_MEDIATE_NODE` (System 1) $\rightarrow$ `SLOW_CRITIQUE_NODE` (System 2) $\rightarrow$ output.
    *   Verify that `retrieved_context` is successfully populated with matching assets or the empty match string.
    *   Verify that the generated response is checked by the critique node and is written to `chat_messages` only if it contains no financial promises.
    *   Verify the compliance critique retry loop: if `violation == true` and `critique_loopback_count <= 2`, it increments `critique_loopback_count`, writes to `correction_instruction`, and loops back to `FAST_MEDIATE_NODE`.
    *   Verify compliance fallback: if it exceeds 2 retries, it drops the response, sets `critique_loopback_count = 0`, and outputs the pre-defined safety fallback response.
*   **Valuation Path (`Intent == VALUATION_SUBMISSION`)**:
    *   Inject points payload. Verify it routes to `SLOW_REFLECT_NODE` $\rightarrow$ `VALIDATE_NODE`.
    *   **Loopback Test**: Inject an invalid points total (e.g. 950 points). Assert that `loopback_count` increments to `1`, `correction_instruction` is written, and execution loops back to `FAST_MEDIATE_NODE` to prompt the user.
    *   **Sum Validation Hold Escalation Test**: Repeat validation failures. Assert that when `loopback_count > 2`, the graph halts and interrupts execution before entering the `HITL_GUARD` node. Verify that this is treated as a sum validation hold requiring correction rather than a session-wide mathematical deadlock.
    *   **Verify Resubmission Resets**: When the user resubmits corrected points valuations via the UI, verify both `loopback_count` is reset to `0` and `correction_instruction` is cleared to `None` in the graph state.
*   **Admin Override Resumption (HITL)**:
    *   Assert that the graph interrupts before `HITL_GUARD`.
    *   Call `POST /api/sessions/{session_id}/override` to write adjusted points directly into the checkpointer state.
    *   Resume the graph and assert that it skips `HITL_GUARD`, executes `COMMIT_NODE` (writing values to DB and generating SHA-256 hash chains), and exits.

### 2.2 WebSocket Connection & Real-Time Streaming
*   **Test Handshake Cookie Auth**:
    *   Connect to `/api/sessions/{session_id}/ws` without a JWT cookie. Verify connection is rejected.
    *   Connect with a valid Heir JWT cookie. Verify connection is accepted and registered to the heir's thread.
*   **Test Sentence-Chunked Voice Streaming and Critique Cancellation**:
    *   Trigger an LLM stream response over WebSocket. Verify that the client receives consecutive `chat_reply_chunk` frames containing `"is_synthetic": true`, chunked text, and base64-encoded WAV audio bytes.
    *   Verify that if the Slow Critique Node detects a financial promise compliance violation, the backend immediately dispatches a WebSocket frame instructing the client to clear and discard the streamed chunks, loops back for correction, and increments the loopback count.
*   **Test Client-Side Audio Playback Null Guard**:
    *   Verify that if a `chat_reply_chunk` frame contains a null or undefined `audio` payload, the client-side audio playback queue does not crash, ignores the empty audio chunk, and successfully appends the accompanying text to the chat window.
*   **Test Real-Time Broadcasts**:
    *   Trigger a pause or deadlock in the Admin panel. Verify that heirs receive a WebSocket message of type `session_status` containing the updated `status`, `is_paused`, and `is_deadlocked` values.

---

## 3. Frontend Unit & Integration Tests

### 3.1 Zustand Store Action Verification
*   **Verify Slider Point Deductions**:
    *   Verify that adjusting points subtracts the difference from `unallocatedPoints`.
    *   Verify that if `unallocatedPoints == 0`, `updateValuation` blocks slider increases.
    *   Verify `updateValuation` is ignored if `isSubmitted` is `true`.
*   **Verify Submission Action**:
    *   Assert that `submitValuations` sets `isSubmitted = true` on successful API submission.
*   **Verify State Restoration**:
    *   Assert that `loadValuations` retrieves allocations from the backend and correctly populates the local points map and unallocated pool.
*   **Verify Active Abstention**:
    *   Assert that `abstainSession` updates `userStatus = 'ABSTAINED'`.
    *   Verify `downloadWaiverReceipt` fetches the PDF receipt successfully.
*   **Verify Session Resumption Actions**:
    *   Assert that `checkInviteStatus` calls `GET /api/invite/status/{token}` and returns the usage status and username.
    *   Assert that `resumeSession` calls `POST /api/invite/login`, sets `isAuthenticated = true`, triggers `loadProfile`, and redirects to `/dashboard`.
*   **Verify Browser Refresh Restoration Actions**:
    *   Assert that loading `/admin` with empty Zustand state first renders a restoring state, calls `GET /api/auth/me`, restores `isAuthenticated = true` and `userRole = 'ADMIN'` for a valid Admin cookie, reloads the Admin session list, and does not show the login form.
    *   Assert that loading `/admin` with a valid Heir cookie does not render Admin controls and falls through to the Admin login/setup gate.
    *   Assert that loading `/dashboard` with empty Zustand state restores a valid Heir cookie by calling `GET /api/auth/me` followed by `GET /api/heirs/me`, then renders the dashboard.
    *   Assert that Admin logout calls `POST /api/auth/logout`, clears local auth/session state, and removes the saved active Admin console session selection.
*   **Verify Scalable Admin Session Index**:
    *   Seed at least 25 sessions in frontend tests and at least 100 sessions in an E2E/mobile visual test fixture.
    *   Assert that `/admin` renders search, status filter, sort, card/list density controls, and pagination or incremental loading.
    *   Assert that search narrows by estate title/status/id without requiring a full page reload.
    *   Assert that status filtering and sort controls can be combined, and that changing either resets the current page/window to the first result set.
    *   Assert that mobile-width rendering avoids horizontal scrolling, keeps the primary open-session action obvious, and does not repeat oversized full-width destructive buttons for every session row.
*   **Future Verify Federated Login Actions**:
    *   Assert that Admin login renders "Continue with SSO" only when OIDC is enabled.
    *   Assert that invite onboarding does not render durable SSO-linking controls before Executor identity approval.
    *   Assert that the authenticated post-approval Heir settings/dashboard flow can start OIDC linking and returns to the same verified Heir account after callback.

### 3.2 UI Rendering Guards
*   **Test Component Disabling**:
    *   Mock Zustand state with `isPaused: true` or `isSubmitted: true`. Verify that all sliders, input fields, and chat inputs render with `disabled="true"` in the DOM.
*   **Test Decline Consent Redirect**:
    *   Verify that declining the consent card redirects the router to `/opt-out`.
*   **Test Abstention/Expiration Wait Screen Mount**:
    *   Mock Zustand state with `userStatus: 'ABSTAINED'` or `userStatus: 'EXPIRED_NON_PARTICIPATING'`. Verify that the dashboard component is completely unmounted and the `AbstentionWaitScreen` component is rendered.
*   **Test View Finalization Swap**:
    *   Mock Zustand state with `sessionStatus: 'FINALIZED'`. Verify that the dashboard component is completely unmounted and the `KeepsakeMemoryBook` component is rendered.
*   **Test Waiver Signature Middle Name Matching**:
    *   Mock user legal details with a null middle name (`legal_middle_name = null`). Verify that typing exactly `"legal_first_name legal_last_name"` (filtered and joined with a single space) enables the "Sign & Abstain" button in the waiver modal, while typing `"legal_first_name null legal_last_name"` or `"legal_first_name None legal_last_name"` does not enable the button.
*   **Test Session Resumption Card Mount**:
    *   Verify that when routing to `/invite/:token` and the status check returns `"USED"`, the onboarding consent form does not render and the `SessionResumptionCard` is mounted in the DOM.
*   **Test Audio Playback Cleanup**:
    *   Verify that when the dashboard/chat component unmounts, the sequential audio player triggers cleanup: active audio playback is stopped, the queue is emptied, and all generated Blob URLs are revoked using `URL.revokeObjectURL`.
*   **Test Onboarding Profile Input Fields & ID Scanner Location (BUG-61)**:
    *   Verify that routing to the public `/invite/:token` onboarding page renders the Heir's registered legal details (First Name, Middle Name, Last Name, DOB, etc.) as editable text inputs.
    *   Verify that the Government ID Camera Scanner and Drop Slot are not rendered on the `/invite/:token` page.
    *   Verify that the Government ID Camera Scanner and Drop Slot are rendered on the `/dashboard` page only when the Heir is logged in and their status is `'PROFILE_HOLD'`.
