# Phase 3: Image Processing & Backend REST API Gateways

## Phase Objective
Construct the image scaling/conversion pipelines and expose authenticated FastAPI endpoints for sessions, staging, and profile updates. Note: A 3 to 5 business day schedule buffer is explicitly injected between Phase 2 and Phase 3 to calibrate local model latency, memory headroom, and resolve connection timeout thresholds. Task T63 (Pi 5 model downscaling & memory profiling) and T28a-2 (Phase 2 test gate) are hard prerequisites — Phase 3 MUST NOT begin until T63 has validated which model profiles fit within the 8GB Raspberry Pi 5 envelope and T28a-2 confirms Phase 2 tests pass. T28a-3 (Phase 3 partial test gate) runs at end of Phase 3 and gates progression to Phase 4.

## Technical Specifications References
* [Backend System Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_backend.md)
* [Database Schema & Transaction Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_db.md)
* [Compliance & Privacy Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_compliance.md)

## Detailed Requirements & Architecture
1. **Image Preprocessing Pipeline**:
   * Integrate `Pillow` and `pillow-heif` to handle image uploads from mobile devices (including HEIC).
   * Image conversion: Convert all incoming photos to WebP format.
   * Compression: Enforce WebP lossy compression with quality set to exactly `80%`.
   * Size Bounds: Scale down large images using aspect-ratio-preserving bounds (`Image.thumbnail`) to fit inside a `1200 x 1200 pixels` bounding box.
   * Pluggable Storage Driver: Develop a storage helper utilizing `STORAGE_DRIVER` environment variable:
     * `STORAGE_DRIVER=LOCAL`: Save WebP files locally to `/app/static/uploads/`.
     * `STORAGE_DRIVER=GCS`: Stream WebP files directly to a Google Cloud Storage bucket.
     * `STORAGE_DRIVER=S3`: Stream WebP files directly to an S3-compatible bucket (MinIO, Cloudflare R2, Backblaze B2, etc.).
2. **Asset Staging & Background OCR API**:
   * Build `POST /api/sessions/{session_id}/assets/stage` endpoint.
   * Actions: Process and save the WebP image, create the database asset record setting status to `'STAGED'` and `ocr_status = 'PROCESSING'`.
   * Background Task: Spawn a background worker thread calling Ollama's `llava:7b` to parse the asset photo. Extract title, category, tags, and description.
   * Broadcast Completion: Once OCR completes, update the asset row and dispatch a WebSocket frame (`asset_ocr_completed`) containing the pre-filled metadata.
3. **Asset Publishing & Auto Seeding API**:
   * Build `POST /api/assets/{asset_id}/publish` endpoint.
   * Actions: Commit metadata edits, call nomic-embed-text to compute the 768-dimensional text vector embedding, and update status to `'LIVE'`.
   * **Asset Lifecycle Validation Gate (DB Spec §2.3)**: Before allowing transition to `'LIVE'`, the gateway MUST validate that `title`, `description`, `category`, `valuation_min`, `valuation_max`, `valuation_source`, and `sentiment_tag` are fully populated and valid. Reject incomplete assets with `400 Bad Request`.
   * **Valuation Matrix Seeding**: On transition to `'LIVE'`, the transaction must seed a default `0`-point valuation row for all active verified heirs in the session (excluding pending or `'PROFILE_HOLD'` users) using an `ON CONFLICT DO NOTHING` clause.
   * **Pre-Allocation Cleanup**: On transition to `'PRE_ALLOCATED'` (`POST /api/assets/{asset_id}/pre-allocate`), the transaction must explicitly delete all existing valuation rows for this asset in the `valuations` table to prevent orphaned valuations from polluting the solver matrix.
4. **FastAPI JWT Onboarding Endpoints**:
   * Build `POST /api/invite/verify` endpoint. Validate token, verify age/GDPR checkboxes, record `consent_timestamp`, set user status to `'PROFILE_HOLD'` (to wait for ID upload and check), and issue a secure, HTTP-only JWT token session cookie. **Rate limiting middleware (T73) MUST be applied to this public endpoint.**
   * Build `POST /api/invite/login` endpoint. Allow already-onboarded heirs with unexpired tokens to log in and receive a session cookie. **Rate limiting middleware (T73) MUST be applied to this public endpoint.**
5. **Profile Correction API**:
   * Build `PUT /api/heirs/me/profile` profile self-correction endpoint. If legal first/middle/last name or DOB is altered, set `identity_verified = False`, transition status to `'PROFILE_HOLD'`, delete the encrypted ID scan file from disk, and reset `id_scan_uri = NULL` to force a new scan. Writes a `'USER_PROFILE_UPDATE'` audit log event block.
6. **Session Lifecycle & Admin Announcement API**:
   * Build `POST /api/sessions/{session_id}/launch` endpoint to transition setup to active, lock inventory, and set session deadline.
   * Build `POST /api/sessions/{session_id}/pause` and `POST /api/sessions/{session_id}/unpause` endpoints. Unpause calculates total pause duration, extends token expiration dates and session deadlines by this duration, and resets pause timestamp.
   * Build `PUT /api/sessions/{session_id}/announcement` to set or clear session-wide announcements and broadcast the change over WebSockets using the websocket_manager utility.
7. **Admin Setup & Session Creation API**:
   * Build `POST /api/setup/admin` first-boot endpoint: detects uninitialized database, creates the Admin account with Argon2-hashed password, generates and returns the 24-word BIP39 mnemonic seed phrase. Must be idempotent (returns error if Admin already exists).
   * Build `POST /api/sessions` for Admin to create a new mediation session (estate name, deadline, configurable notice window).
8. **Asset Deletion API**:
   * Build `DELETE /api/assets/{asset_id}` endpoint. Deletes the asset record, removes the associated image file from storage, and cascades delete all linked valuation rows. Returns `400 Bad Request` if session status is `'ACTIVE'`, `'LOCKED'`, or `'FINALIZED'` (session-status gated, not invite-token gated).
9. **Admin Audio Story Upload & Delete API**:
   * Build `POST /api/assets/{asset_id}/audio` endpoint accepting multipart form data (WebM/MP3/WAV, matching Backend Spec §9.2 which supports all three formats). Saves the audio file to the configured storage driver and updates `assets.audio_uri`. Returns `400 Bad Request` if session is not in `'SETUP'` status.
   * Build `DELETE /api/assets/{asset_id}/audio` endpoint to remove the audio file and nullify `assets.audio_uri`. Gated on `'SETUP'` session status. Audio cleanup cascades on asset deletion (T40).
10. **Support Request & Help CRUD API**:
      * Build `POST /api/sessions/{session_id}/help` — Heir creates a support request. Persists to `support_requests` table and broadcasts an alert to the Admin WebSocket channel. **Routes match Backend Spec §9.4 namespace (not `/api/support`).**
      * Build `GET /api/sessions/{session_id}/help` — Admin fetches all open support requests for the session.
      * Build `POST /api/help/{ticket_id}/resolve` — Admin marks a support request as `RESOLVED`.
11. **Custom FAQ CRUD API**:
      * Build `POST /api/sessions/{session_id}/faqs` — Admin creates a custom FAQ entry (question + answer).
      * Build `PUT /api/sessions/{session_id}/faqs/{faq_id}` — Admin edits an existing FAQ.
      * Build `DELETE /api/sessions/{session_id}/faqs/{faq_id}` — Admin deletes a FAQ.
      * Build `GET /api/sessions/{session_id}/faqs` — Public (Heir-accessible) endpoint returning all FAQs for the session.

> [!NOTE]
> **T34 (Executor ID Verification API) is owned by Phase 3.** Its requirements appear in both Phase 3's checklist and Phase 7's architecture section. Phase 7 listed it for reference only. The canonical implementation task and DAG edge reside here in Phase 3.

## Phase Checklist & Tasks

### [x] Task T09a: Storage Driver Interface & Mock Driver
* **Objective**: Define abstract storage driver base class with `save(path, bytes)`, `get(path)`, and `delete(path)` methods. Implement a Mock driver for unit testing. **This enables all downstream API tasks (T11, T13, T31, T34, T40, T41, T55, T60, T49) to be developed in parallel with concrete storage implementations.**
* **Verification**: Verify that the abstract interface enforces the `delete()` method contract. Verify that the Mock driver saves, retrieves, and deletes byte payloads correctly, and that deleting a nonexistent file does not raise an error (idempotent).

### [x] Task T09b: Image Preprocessing Pipeline & Concrete Storage Drivers
* **Objective**: Write HEIC/PNG to WebP conversion logic with 80% compression, 1200x1200px bounds, and aspect-ratio-preserving scaling using `Image.thumbnail`. Implement LOCAL, GCS, and S3 (MinIO, R2, B2) concrete storage drivers with explicit `delete()` method for file cleanup. The storage driver MUST implement a `delete(path)` method: for LOCAL driver, deletes the file from disk; for GCS driver, calls the bucket API to delete the corresponding blob; for S3 driver, calls the S3 API to delete the corresponding object. **Depends on T09a for the interface contract. Required by T40, T41, T31, T34, T55, T60, T13, T49 for secure deletions.**
* **Verification**: Verify PNG, JPG, and HEIC uploads compile to normalized 1200x1200px WebP files. Verify that calling `delete()` on the LOCAL driver removes the file from the filesystem, on the GCS driver sends a delete request to the bucket, and on the S3 driver sends a delete request to the S3 bucket. Test that deleting a nonexistent file does not raise an error (idempotent).

### [ ] Task T10: FastAPI Core & Onboarding endpoints
* **Objective**: Define core FastAPI routing, Argon2 admin login, invite verification, and secure JWT HTTP-only cookie handlers. **Rate limiting middleware (T73) MUST be applied to all public endpoints implemented in this task.**
* **Verification**: Verify invite verify returns 400 if checkboxes are unchecked, and sets HTTP-only cookies on success. Verify that rate limiting headers are present on all public endpoint responses. Depends on T02, T03, and T73.

### [ ] Task T37: FastAPI Session Lifecycle & Announcement API
* **Objective**: Implement `/launch`, `/pause`, `/unpause`, and `/announcement` endpoints, integrating deadline calculation, dynamic token extension, and WebSocket announcement broadcasts. Depends on T02, T10, and T38.
* **Verification**: Verify that pausing the session freezes mutations, unpausing extends invite token expiration timestamps, and updating announcements broadcasts WebSocket updates.

### [ ] Task T11: FastAPI Asset Router
* **Objective**: Build asset staging, background OCR threads, publishing vector embedding computations, and database valuations seeding. **MUST implement the Asset Lifecycle Validation Gate per DB Spec §2.3: validate that title, description, category, valuation_min, valuation_max, valuation_source, and sentiment_tag are fully populated before allowing transition to LIVE — reject incomplete publish requests with 400 Bad Request.** Depends on T02, T04, T09a, T09b, T10, T38, and T50.
* **Verification**: Verify publishing transitions asset to LIVE and seeds 0-point valuations for active heirs. Verify that attempting to publish an asset with missing required fields (e.g., no valuation source) returns 400 Bad Request with a descriptive error message.

### [ ] Task T13: FastAPI Heir Management & Invitations
* **Objective**: Implement heir creation (`POST /api/sessions/{session_id}/heirs`), invite token generation and renewal (`POST /api/heirs/{heir_id}/invite-token`), asynchronous invitation emails (`POST /api/heirs/{heir_id}/send-invite` using `aiosmtplib` background worker with up to 3 retry attempts using exponential backoff — 1s, 4s, 16s — on connection failures), and profile self-corrections. **Note: The Background Invite Expiration Scheduler (T65) is a dependent task that reads invite tokens created by this API. No backward dependency — T13 does not depend on T65.** Depends on T02, T09b, T10, T37, and T38.
* **Verification**: Verify that adding an heir generates a token and queues SMTP delivery, and that profile self-correction resets identity verification status and deletes previous scan files. Verify that if the SMTP server is unreachable, the background worker retries 3 times with increasing delays before failing.

### [ ] Task T31: Government ID Scan Upload API
* **Objective**: Expose `POST /api/heirs/me/upload-id` endpoint that accepts government ID files, encrypts them using AES-Fernet, and stores them in secure disk storage. Depends on T02, T03, T09b, T10.
* **Verification**: Test that uploading a mock ID file returns 200, saves ciphertext to the file system, and sets user status to `'PROFILE_HOLD'`.

### [ ] Task T34: Executor ID Verification State Transition API
* **Objective**: Implement the `POST /api/heirs/{heir_id}/verify-identity` endpoint for Executor Visual ID Inspection approval/rejection. Approval sets `identity_verified = True`, transitions status to `'ACTIVE'`, queries all currently `'LIVE'` assets (excluding `'PRE_ALLOCATED'`) to seed default 0-point valuations for this newly-active heir, deletes the temporary ID scan file, and logs verification to the audit chain. Depends on T02, T03, T09b, T10, T11, T13, T31, T37.
* **Verification**: Mock an ID scan approve action and assert that user status transitions to `'ACTIVE'`, default valuations are seeded for all published LIVE assets, and the scan file is deleted from disk.

### [ ] Task T39: Admin Setup & Session Creation API
* **Objective**: Build `POST /api/setup/admin` (first-boot admin creation + BIP39 mnemonic generation) and `POST /api/sessions` (new mediation session creation). The setup endpoint must be idempotent and return an error if Admin already exists. Depends on T02, T03, T10.
* **Verification**: Verify setup endpoint fails on second call. Verify session creation returns the session record with a generated ID and default `'SETUP'` status.

### [ ] Task T40: Asset Deletion API
* **Objective**: Build `DELETE /api/assets/{asset_id}`. Delete asset record, linked image file from storage, and cascade-delete all `valuations` rows for this asset. Gate on session status — must return `400 Bad Request` if session is `'ACTIVE'`, `'LOCKED'`, or `'FINALIZED'`. Depends on T02, T10, T11.
* **Verification**: Verify asset deletion succeeds in `'SETUP'` and returns 400 in `'ACTIVE'` status. Confirm image file is removed from disk and linked valuations are deleted.

### [ ] Task T41: Admin Audio Story Upload & Delete API
* **Objective**: Build `POST /api/assets/{asset_id}/audio` accepting multipart audio upload (WebM/MP3/WAV, matching Backend Spec §9.2). Save to the configured storage driver, update `assets.audio_uri`. Also build `DELETE /api/assets/{asset_id}/audio` to remove the audio file and nullify `assets.audio_uri`. Both gate on session status `'SETUP'`. Audio cleanup cascades on asset deletion (T40). Depends on T02, T09b, T10, T11.
* **Verification**: Verify upload returns 200 and `audio_uri` is set on the asset. Verify upload returns 400 if session is `'ACTIVE'`. Verify DELETE returns 200, nullifies `audio_uri`, and removes the audio file from storage.

### [ ] Task T42: Support Request & Help CRUD API
* **Objective**: Build `POST /api/sessions/{session_id}/help` (Heir submits help request, persists to DB, broadcasts WebSocket alert to Admin), `GET /api/sessions/{session_id}/help` (Admin list), and `POST /api/help/{ticket_id}/resolve` (Admin resolves). **Routes match Backend Spec §9.4 namespace.** Depends on T02, T10, T38.
* **Verification**: Submit a help request via Heir token and verify it appears in the Admin list. Resolve it and verify status changes to `'RESOLVED'` in the DB.

### [ ] Task T43: Custom FAQ CRUD API
* **Objective**: Build `POST`, `PUT`, `DELETE /api/sessions/{session_id}/faqs/{faq_id}` for Admin FAQ management, and `GET /api/sessions/{session_id}/faqs` for Heir reading. Updates must broadcast a WebSocket event to refresh Heir dashboards. Depends on T02, T10, T38.
* **Verification**: Create a FAQ as Admin. Verify it is returned in the Heir-accessible GET endpoint. Edit and delete it. Verify updates propagate.

### [ ] Task T64: Asset Pre-Allocation API
* **Objective**: Build `POST /api/assets/{asset_id}/pre-allocate` endpoint. Accepts `{"allocated_to_id": "UUID"}` in the request body. On transition to `'PRE_ALLOCATED'`, the database transaction must explicitly delete all existing valuation rows for this asset in the `valuations` table to prevent orphaned valuations from polluting the solver matrix. Gate on session status — returns `400 Bad Request` if session is `'ACTIVE'`, `'LOCKED'`, or `'FINALIZED'`. Depends on T02, T10, T11.
* **Verification**: Verify pre-allocating an asset sets its status to `'PRE_ALLOCATED'`, sets `allocated_to_id`, and deletes all linked valuation rows for that asset. Verify the endpoint is rejected in `'ACTIVE'` status.

### [ ] Task T65: Background Invite Expiration Scheduler
* **Objective**: Implement a periodic background task that checks for expired invite tokens (`invite_token_expires_at < now()`) where `invite_token_used == False` and transitions those users to `'EXPIRED_NON_PARTICIPATING'`. Runs every 15 minutes. Depends on T02, T13.
* **Verification**: Create an expired token in the database, wait for one scheduler cycle, and assert the user's status transitions to `'EXPIRED_NON_PARTICIPATING'`.

### [ ] Task T60: Admin Heir Deletion API
* **Objective**: Build `DELETE /api/sessions/{session_id}/heirs/{heir_id}` Admin endpoint. Purge Heir PII from users/chat/checkpointers and anonymize audit logs snapshots to preserve chain integrity. Depends on T02, T03, T09b, T10, T11, T13, T31.
* **Verification**: Verify deleting an heir wipes their PII fields, removes their encrypted ID scan from storage, and sanitizes audit logs snapshots without breaking the SHA-256 hash validation.

### [ ] Task T28a-3: Backend Tests — Phase 3 Scope
* **Objective**: Write `pytest` coverage for Argon2 auth, image pipeline, onboarding endpoints (including rate limiting header verification on all public endpoints), asset staging/OCR (including lifecycle validation gate), session lifecycle, heir management, ID upload, support/help APIs, admin/FAQ/deletion APIs, session creation, asset pre-allocation, and rate limiting middleware. **Run at end of Phase 3. Gates progression to Phase 4.** Depends on T09a, T09b, T10, T11, T13, T31, T34, T37, T39, T40, T41, T42, T43, T60, T64, T65, T73.
* **Verification**: Execute `pytest backend/tests/` and verify Phase 3 tests pass, including the asset lifecycle validation gate rejecting incomplete assets and rate limiting header presence on all public endpoints.

## Phase Dependency Graph
```mermaid
graph TD
    T38[T38: WebSocket Connection Manager]
    classDef independent fill:#f0f0f0,stroke:#999,stroke-dasharray: 5 5
    class T38 independent
    T02[T02: SQLAlchemy Models & Relations] --> T10[T10: FastAPI Core & Onboarding endpoints]
    T03[T03: AES-Fernet Encryption Decorator] --> T10
    T73[T73: Rate Limiting Middleware] --> T10
    
    T02 --> T37[T37: FastAPI Session Lifecycle & Announcement API]
    T10 --> T37
    T38 --> T37
    
    T02 --> T11[T11: FastAPI Asset Router]
    T04[T04: Alembic Migrations & pgvector Indexing] --> T11
    T09a[T09a: Storage Driver Interface & Mock Driver] --> T11
    T09a --> T09b[T09b: Image Preprocessing & Concrete Drivers]
    T09b --> T11
    T10 --> T11
    T38 --> T11
    T50[T50: LLM Provider Abstraction & Ollama Health-Check] --> T11
    
    T02 --> T13[T13: FastAPI Heir Management & Invitations]
    T10 --> T13
    T37 --> T13
    T38 --> T13
    T09b --> T13
    
    T02 --> T31[T31: Government ID Scan Upload API]
    T03 --> T31
    T10 --> T31
    T09b --> T31
    
    T02 --> T34[T34: Executor ID Verification State Transition API]
    T03 --> T34
    T10 --> T34
    T11 --> T34
    T13 --> T34
    T31 --> T34
    T37 --> T34
    T09b --> T34

    T02 --> T39[T39: Admin Setup & Session Creation API]
    T03 --> T39
    T10 --> T39
 
    T02 --> T40[T40: Asset Deletion API]
    T10 --> T40
    T11 --> T40

    T02 --> T41[T41: Admin Audio Story Upload & Delete API]
    T09b --> T41
    T10 --> T41
    T11 --> T41

    T02 --> T42[T42: Support Request & Help CRUD API]
    T10 --> T42
    T38 --> T42

    T02 --> T43[T43: Custom FAQ CRUD API]
    T10 --> T43
    T38 --> T43

    T02 --> T60[T60: Admin Heir Deletion API]
    T03 --> T60
    T10 --> T60
    T11 --> T60
    T13 --> T60
    T31 --> T60
    T09b --> T60

    T02 --> T64[T64: Asset Pre-Allocation API]
    T10 --> T64
    T11 --> T64

    T02 --> T65[T65: Background Invite Expiration Scheduler]
    T13 --> T65

    T03[T03: AES-Fernet Encryption Decorator] --> T28a-3[T28a-3: Backend Tests — Phase 3 Scope]
    T04[T04: Alembic Migrations & pgvector Indexing] --> T28a-3
    T09a --> T28a-3
    T09b --> T28a-3
    T10 --> T28a-3
    T11 --> T28a-3
    T13 --> T28a-3
    T31 --> T28a-3
    T34 --> T28a-3
    T37 --> T28a-3
    T38 --> T28a-3
    T39 --> T28a-3
    T40 --> T28a-3
    T41 --> T28a-3
    T42 --> T28a-3
    T43 --> T28a-3
    T60 --> T28a-3
    T64 --> T28a-3
    T65 --> T28a-3
    T73[T73: Rate Limiting Middleware] --> T28a-3