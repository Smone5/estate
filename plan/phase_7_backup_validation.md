# Phase 7: System Backup, Compliance & E2E Validation

## Phase Objective
Implement disaster recovery archives, Cloudflare Tunnel public exposure, host hardening, and validate the complete platform compliance against GDPR, CCPA, and California Bot laws. Note: A 2 to 3 business day schedule buffer is injected between Phase 6 and Phase 7 to perform manual audio latency tuning, handle browser AudioContext state transitions, and verify WebSocket socket leakage under load before final E2E compliance validation. Additionally, a 1 to 2 business day schedule buffer is injected between T28c (Phase 6–7 backend tests) and T30 (E2E Compliance Validation) to absorb test remediation before the final compliance gate.

## Technical Specifications References
* [Compliance & Privacy Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_compliance.md)
* [Legal Estate & Probate Compliance Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_legal.md)
* [Testing & Verification Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_testing.md)
* [Backend System Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_backend.md)

## Detailed Requirements & Architecture
1. **AES-Encrypted System Backups**:
   * Build `GET /api/system/backup`. Generate a `.tar.gz` archive containing a postgres database schema/data `pg_dump` and a zipped copy of local uploads. Encrypt the file using the app's AES-Fernet key before sending it as a binary stream.
   * Build `POST /api/system/restore`. Accept an encrypted `.estate.bak` upload and decrypt it using the Fernet engine. Execute schema recovery and files replacement within a single database transaction. Roll back to the pre-restore state if any step fails.
2. **Paper Recovery Mnemonic Key**:
   * Derive a 24-word BIP39 mnemonic key from the active 32-byte `ENCRYPTION_KEY` using standard cryptography libraries.
   * Build the Admin Setup Screen (moved to Phase 5, Task T27).
   * Add a recovery text input field to the Restore panel UI to allow decryption using the seed phrase on fresh system installs (Task T56).
3. **GDPR Account Erasure Soft-Anonymization (Cross-reference - owned by Phase 4, Task T55)**:
   * The soft-anonymization API `DELETE /api/heirs/me` is implemented in Phase 4 (T55). Phase 7 E2E compliance validation (`T30`) conducts final audits verifying that after account deletion, PII is purged and audit hash chain integrity is preserved.
4. **AI Training Data Transparency**:
   * Implement `GET /api/system/models` to satisfy California AB 2013. Read the environment variables `FAST_THINKER_MODEL`, `SLOW_THINKER_MODEL`, and `VISION_MODEL` and return dynamically populated parameters, licenses, and dataset provenance details.
5. **Secure Session Purge**:
   * Build `DELETE /api/sessions/{session_id}` Admin endpoint for permanent post-completion purge.
   * **Sequence**: (1) Verify session is `'FINALIZED'`. (2) Delete all `chat_messages` rows. (3) Delete all `checkpoints` and `checkpoint_writes` rows for all `session_id:*` thread IDs. (4) Hard-delete all associated `users` records (including Anonymized heirs). (5) Delete all session image and audio files from local storage or GCS bucket. (6) Delete the `sessions` row and all FK-cascading `assets`, `valuations`, `audit_logs`, and `support_requests` rows.
6. **Executor ID Verification API** *(Cross-reference — owned by Phase 3, Task T34)*:
   * The `POST /api/heirs/{heir_id}/verify-identity` endpoint is implemented in Phase 3 (T34).
7. **E2E compliance & test suite validation**:
   * Pytest backend and Vitest frontend test files are written and run incrementally *during each respective phase* (from Phase 1 to Phase 6) as features are built. In Phase 7, the E2E compliance validation (`T30`) runs final automated checks verifying CCPA compliance listings, GDPR Article 20 data portability JSON streams, and SHA-256 hash chains across the entire application.
8. **Cloudflare Tunnel & Public Exposure (T74)**:
   * Configure outbound-only Cloudflare Tunnel (or Localtunnel fallback) to expose the local Raspberry Pi 5 securely to the public internet per Backend Spec §12.1. Generate public HTTPS URL, configure DNS, and verify remote heir accessibility.
9. **Host Hardening (T75)**:
   * Disable SSH password logins in favor of SSH key authentication, change all default user credentials, enable automatic security package updates, and verify host firewall rules per Backend Spec §12.1.

## Phase Checklist & Tasks

### [ ] Task T26: pg_dump System Backup & Restore
* **Objective**: Write the backend pg_dump backup zipper, Fernet encryptor, and database restore handler.
* **Verification**: Verify that downloading backup produces an encrypted file, and restoring it recovers data correctly.

### [ ] Task T72: Unauthenticated System Restore Gate Design
* **Objective**: Design and implement the authentication bypass mechanism for `POST /api/system/restore` on fresh (uninitialized) systems. The endpoint must detect whether an admin account exists: if no admin exists, allow unauthenticated restore; if admin exists, require Admin JWT. Must implement rate-limiting (consuming T73 middleware) and CSRF token to prevent abuse.
* **Verification**: Verify that on an uninitialized system, restore can be triggered without headers if a valid recovery key is provided. Verify that once admin exists, unauthenticated restore requests are blocked. Verify that rapid repeated restore attempts trigger rate limiting.

### [ ] Task T61: Nginx & Production Build Setup
* **Objective**: Configure Nginx (`nginx.conf`) static serving with rate limiting zones, WebSocket proxy pass, uploads volume mounting, build the production frontend bundle (`npm run build`), and verify docker-compose static asset routing. Depends on T17, T18, T19, T73.
* **Verification**: Run `npm run build` and assert that `/frontend/dist` directory is populated. Boot system using `docker-compose up` and assert that the application shell and uploaded asset images are served correctly by Nginx on port 80. Verify that rate limiting headers are present on proxied responses.

### [ ] Task T74: Cloudflare Tunnel & Public Exposure Setup
* **Objective**: Configure outbound-only Cloudflare Tunnel (or Localtunnel fallback) to expose the local Raspberry Pi 5 securely to the public internet. Generate public HTTPS URL, configure DNS, and verify remote heir accessibility per Backend Spec §12.1. Depends on T61 (Nginx must be serving before tunnel is established).
* **Verification**: Verify that the public HTTPS URL is accessible from an external network (e.g., mobile device on cellular). Verify that WebSocket connections function through the tunnel. Verify that the tunnel auto-reconnects after a simulated network interruption.

### [ ] Task T75: Host Hardening & SSH Configuration
* **Objective**: Disable SSH password logins in favor of SSH key authentication, change default user credentials, enable automatic security package updates, and verify host firewall rules per Backend Spec §12.1. This is an operations task with no code dependencies — can be executed in parallel with any phase.
* **Verification**: Verify that SSH password authentication is disabled and key-based login succeeds. Verify that `ufw` or equivalent firewall is active with only ports 80/443 exposed. Verify that unattended-upgrades are configured.

### [ ] Task T36: AB 2013 Model Transparency API & Modal
* **Objective**: Expose the dynamic model transparency endpoint `GET /api/system/models` and develop the corresponding frontend Modal accessible from the settings drawer to comply with California AB 2013.
* **Verification**: Test that modifying model environment variables (e.g. `FAST_THINKER_MODEL`) updates the API payload, and verify that the modal displays the parameters and dataset provenance table.

### [ ] Task T28c: Backend Tests — Phase 6–7 Scope
* **Objective**: Write `pytest` coverage for WebSocket server endpoint, Kokoro TTS integration, session backup/restore transactions, Nginx production routing, model transparency API, Cloudflare Tunnel routing, rate limiting middleware, and the unauthenticated restore gate. **Must include SB 942 synthetic audio indicator assertions: verify every `chat_reply_chunk` frame contains `"is_synthetic": true` per Compliance Spec §2.5.** Run at end of Phase 7. **A 1–2 business day buffer is injected between T28c completion and T30 (E2E Compliance Validation) to absorb test remediation before the final compliance gate.** Depends on T21a, T21, T22, T26, T36, T61, T72, T73, T74.
* **Verification**: Execute `pytest backend/tests/` and verify Phase 6–7 tests pass, including SB 942 synthetic audio indicator assertions on all `chat_reply_chunk` frames.

### [ ] Task T29: Frontend Unit & Integration Tests (Incremental)
* **Objective**: Develop Vitest frontend tests incrementally during each phase verifying Zustand sliders, routing redirection rules, audio playback unmount cleanups, ID scan overlays, Admin Force Allocation consoles, the Model Transparency modal, the BIP39 Mnemonic Onboarding Screen, GDPR data portability controls, GDPR account deletion drawers, Active Abstention Waiver UI components, legal disclaimer footer rendering, and Nginx container delivery. **Includes T66, T67, T68, T69, T73_UI components verification.** Depends on T17, T18, T19, T20, T23, T24, T25, T27, T32, T35, T36, T45, T46, T47, T48, T51, T52, T53, T54, T56, T58, T59, T61, T66, T67, T68, T69, T73_UI.
* **Verification**: Run `npm run test` inside the frontend directory and confirm zero failures.

### [ ] Task T30: E2E Compliance Validation
* **Objective**: Write automated validation scripts to test GDPR portability JSON structures, CCPA listings, SB 942 synthetic audio disclosure (verify `is_synthetic: true` on all audio-bearing WebSocket frames end-to-end), and SHA-256 integrity hash chains. Depends on T28a-1, T28a-2, T28a-3, T28b, T28c, T29. **Note: A 1–2 business day schedule buffer is explicitly injected between T28c completion and T30 execution to absorb test remediation before the final compliance gate.**
* **Verification**: Verify that the database checksum verify script confirms a valid hash chain with no breaks. Verify SB 942 synthetic audio labeling end-to-end from server chunk generation through client queue playback.

### [ ] Task T49: Secure Session Purge
* **Objective**: Build `DELETE /api/sessions/{session_id}?confirm=true` Admin endpoint. Execute the 6-step irreversible permanent deletion sequence: chat logs → checkpointer rows → file assets → hard-delete users → session cascade delete. Gate on `'FINALIZED'` session status and `confirm=true` parameter. Depends on T02, T09b, T13, T26, and T55.
* **Verification**: Finalize a test session. Call purge with `confirm=true`. Assert all database rows are deleted, image/audio files are removed from storage, and a subsequent `GET /api/sessions/{session_id}` returns 404.

## Phase Dependency Graph
```mermaid
graph TD
    T02[T02: SQLAlchemy Models & Relations] --> T26[T26: pg_dump System Backup & Restore]
    T03[T03: AES-Fernet Encryption Decorator] --> T26
    
    T18[T18: Zustand store & cache keys] --> T56[T56: BIP39 Mnemonic Restore Panel]
    T26 --> T56
    
    T10[T10: FastAPI Core & Onboarding endpoints] --> T36[T36: AB 2013 Model Transparency API & Modal]
    T18 --> T36
    T20[T20: Heir & Admin Dashboard View Guards] --> T36
    
    T21a[T21a: Kokoro ONNX Model Download] --> T21[T21: Kokoro-82M TTS & soundfile WAV Encoder]
    T21 --> T28c[T28c: Backend Tests — Phase 6-7 Scope]
    T21a --> T28c
    T22[T22: WebSocket Server Endpoint] --> T28c
    T26 --> T28c
    T36 --> T28c
    T61[T61: Nginx & Production Build Setup] --> T28c
    T72[T72: Unauthenticated System Restore Gate Design] --> T28c
    T73[T73: Rate Limiting Middleware] --> T28c
    T74[T74: Cloudflare Tunnel & Public Exposure Setup] --> T28c
    
    T17[T17: Frontend Vite Base & Vanilla CSS] --> T29[T29: Frontend Unit & Integration Tests]
    T18 --> T29
    T19[T19: Client Routing & Onboarding views] --> T29
    T20 --> T29
    T23[T23: WebSocket Client Connection Loop] --> T29
    T24[T24: Web Speech Client Hook] --> T29
    T25[T25: Client Audio Playback Queue] --> T29
    T27[T27: BIP39 Mnemonic Onboarding Screen] --> T29
    T32[T32: Government ID Scanner & File Drop UI] --> T29
    T35[T35: Executor Force Allocation Console UI] --> T29
    T36 --> T29
    T45[T45: Admin Voice Recorder Widget] --> T29
    T46[T46: Semantic Search UI] --> T29
    T47[T47: FAQ/Help UI Components] --> T29
    T48[T48: Session Announcement UI Components] --> T29
    T51[T51: Active Abstention Waiver UI Components] --> T29
    T52[T52: Admin Inventory Dashboard UI] --> T29
    T53[T53: Admin Session Control UI] --> T29
    T54[T54: Admin Onboarding & Credentials Setup UI] --> T29
    T56 --> T29
    T58[T58: GDPR Data Portability UI Button] --> T29
    T59[T59: GDPR Account Deletion UI Drawer] --> T29
    T61 --> T29
    T66[T66: Family Memories & Stories UI Component] --> T29
    T67[T67: Admin "Inspect ID" Modal Component] --> T29
    T68[T68: Heir "Request Help" Modal Component] --> T29
    T69[T69: Auto-Balance Points Button UI] --> T29
    T73_UI[T73_UI: Legal Disclaimer Footer Component] --> T29
    
    T17 --> T61
    T18 --> T61
    T19 --> T61
    T73 --> T61
    
    T61 --> T74
    
    T28a-1[T28a-1: Backend Tests — Phase 1 Scope] --> T30[T30: E2E Compliance Validation]
    T28a-2[T28a-2: Backend Tests — Phase 2 Scope] --> T30
    T28a-3[T28a-3: Backend Tests — Phase 3 Scope] --> T30
    T28b[T28b: Backend Tests — Phases 4-5 Scope] --> T30
    T28c --> T30
    T29 --> T30
 
    T02 --> T49
    T09b[T09b: Image Preprocessing & Concrete Drivers] --> T49
    T13 --> T49
    T26 --> T49
    T55 --> T49
    
    T03 --> T72
    T10 --> T72
    T26 --> T72
    T73 --> T72