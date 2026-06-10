# Estate Steward: Compliance & Privacy Specification (v1.0)

This specification defines the complete compliance, privacy, and data security architecture of **The Estate Steward**. It aggregates specifications for GDPR, CCPA/CPRA, and California AI and age-related consumer protection laws.

---

## 1. Relational Database Alignment (Consent & Audit Trail)

To satisfy the data consent requirements of GDPR Article 7 and CCPA, the system must record and persist explicit heir consent. 

### 1.1 `users` Table Compliance Fields
*   `consent_accepted`: `BOOLEAN` (Not Null, Default: `false`). Indicates if the heir accepted the privacy policies, PII scrubbing, and local AI processing.
*   `age_verified`: `BOOLEAN` (Not Null, Default: `false`). Indicates if the heir confirmed they are 18 years of age or older (or have guardian consent).
*   `consent_timestamp`: `TIMESTAMP` (Nullable). Records the exact UTC timestamp when the Heir accepted onboarding terms.
*   `is_submitted`: `BOOLEAN` (Not Null, Default: `false`). Records if the Heir has finalized and submitted their 1000 point allocations.
*   `submitted_at`: `TIMESTAMP` (Nullable). Records the exact UTC timestamp when the Heir finalized and submitted their points, used for auditing. Cleared on deletion.
*   `legal_first_name`, `legal_middle_name`, `legal_last_name`: `VARCHAR` (Null or cleared on deletion). Legal names collected to match government ID scans.
*   `relationship_to_decedent`: `VARCHAR` (Null or cleared on deletion). Relationship to decedent for probate/heir verification.
*   `date_of_birth`: `DATE` (Null or cleared on deletion). Date of birth to verify age and identity.
*   `identity_verified`: `BOOLEAN` (Not Null, Default: `false`). Set to `true` when the Executor approves the Heir's Government ID scan.
*   `id_scan_uri`: `VARCHAR` (Nullable, cleared on verification/deletion). Local filepath of the uploaded, AES-encrypted ID scan document. Must be permanently deleted and set to `NULL` immediately upon verification or rejection.
*   `draft_version`: `INTEGER` (Not Null, Default: `0`). Version counter checked upon saving draft points to prevent out-of-order race condition updates.
*   `status`: CHECK constraint updated to `PENDING | PROFILE_HOLD | ACTIVE | SUBMITTED | ABSTAINED | EXPIRED_NON_PARTICIPATING`. When set to `'PROFILE_HOLD'`, the Heir's user interface is locked in a read-only state (disabling sliders and chat) to prevent invalid cryptographic signatures on the ledger before identity validation.

### 1.2 Cryptographic At-Rest Encryption
*   **Target Fields**: `chat_messages.message_text` and any user-supplied sentiment reasons.
*   **Mechanism**: Symmetric encryption using AES-256 (Fernet) via the Python `cryptography` package.
*   **Key Storage**: The encryption key is sourced from the `ENCRYPTION_KEY` environment variable. It is decrypted on-the-fly inside the SQLAlchemy database decoration layer and is never written to log files.

### 1.3 Presidio PII Filtering
*   Before any message text from the `chat_messages` table is ingested by the Fast (System 1) or Slow (System 2) LLM pipelines, it must pass through the Microsoft Presidio Engine to filter/redact personally identifiable information (PII).
*   Scrubbed entities: `PERSON`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `LOCATION`, `US_SSN`, `IP_ADDRESS`.
    *   **Note**: `LOCATION` (previously listed only in the backend and LangGraph specs) and `IP_ADDRESS` (previously listed only here) must **both** be redacted. `LOCATION` protects physical addresses from LLM context leakage; `IP_ADDRESS` protects network identity data from being logged or reflected in the `scrubbed_text` column. The `AnalyzerEngine` must be configured with all six entity types. Any spec showing a subset of this list is incorrect.


---

## 2. API Schema Alignment

Compliance actions are backed by the following specific endpoints in the REST API and WebSocket framing protocol.

### 2.1 `POST /api/invite/verify`
*   **Purpose**: Validates the invitation token and records onboarding consent.
*   **Request Payload**:
    ```json
    {
      "token": "UUID4",
      "consent_accepted": true,
      "age_verified": true,
      "legal_first_name": "string",
      "legal_middle_name": "string (optional)",
      "legal_last_name": "string",
      "relationship_to_decedent": "string",
      "date_of_birth": "YYYY-MM-DD"
    }
    ```
    The legal profile fields are pre-populated from the Executor's registration entry and may be edited by the Heir during the consent flow if they spot a typo, ensuring that any corrections are persisted atomically alongside the consent record.
*   **Backend Logic**: Returns a `400 Bad Request` if either compliance flag is `false`. Otherwise, updates the matching user record, set `invite_token_used = True`, sets the consent flags, records `consent_timestamp`, and issues the secure HTTP-only JWT token.

### 2.2 `GET /api/heirs/me/export` (GDPR Article 20 - Data Portability)
*   **Purpose**: Allows heirs to download their active data records.
*   **Response**: A structured JSON attachment streaming:
    ```json
    {
      "heir_id": "UUID",
      "username": "display_name",
      "legal_first_name": "First",
      "legal_middle_name": "Middle",
      "legal_last_name": "Last",
      "relationship_to_decedent": "Son",
      "date_of_birth": "YYYY-MM-DD",
      "identity_verified": true,
      "email": "user@example.com",
      "phone": "123-456-7890",
      "physical_address": "123 Main St, Anytown, USA",
      "consent_accepted": true,
      "age_verified": true,
      "consent_timestamp": "ISO-8601-String",
      "is_submitted": false,
      "valuations": [
        { 
          "asset_id": "UUID", 
          "points": 450, 
          "reasoning": "Belonged to Grandfather and represents family railway service history.", 
          "is_reasoning_shared": true 
        }
      ],
      "chat_history": [
        { "timestamp": "ISO-8601-String", "sender": "heir", "text": "Decrypted message text" }
      ],
      "support_tickets": [
        { "id": "UUID", "message": "Help details", "status": "RESOLVED" }
      ]
    }
    ```

### 2.3 `DELETE /api/heirs/me` (GDPR Article 17 - Right to Erasure / Soft Anonymization)
*   **Purpose**: Fulfills GDPR Right to Erasure while preserving the Executor's fiduciary records under the Uniform Probate Code.
*   **Logic**: Wipes the Heir's PII (display name, email address, phone number, physical mailing address, password hashes, IP addresses, credentials) from the active user table, replacing their identifier with `"Anonymized Beneficiary [UUID]"` (enlarged to `VARCHAR(100)`). The database **permanently deletes** all private chat transcripts matching this Heir's ID in the `chat_messages` table and all corresponding LangGraph checkpointer state records (from checkpoints/checkpoint_writes tables) matching their thread ID (`f"{session_id}:{heir_id}"`) to ensure conversational PII and intermediate execution history are entirely purged. Additionally, the backend queries all `audit_logs` records for the session, decrypts their `state_snapshot` values, replaces any occurrences of the Heir's PII (legal names, contact details, edit snapshots) with `"Anonymized"`, re-encrypts the snapshots, and commits the updates. Because the `sha256_hash` of each audit log row is computed over a PII-scrubbed JSON copy of the state snapshot (where sensitive details are replaced by `"Anonymized"`), subsequent erasures and anonymizations of the actual encrypted `state_snapshot` column will not alter the input string used to compute the `sha256_hash` field, thereby preserving the cryptographic integrity of the historical hash chain without any breaks.
    *   **Incomplete Submission Handling**:
        *   **If Heir is Unsubmitted (`is_submitted = False`)**: The backend updates their user status to `'ABSTAINED'` and cascade deletes all of their default `0`-point valuations. This prevents points pool sum validation errors from stalling session finalization.
        *   **If Heir is Submitted (`is_submitted = True`)**: The backend preserves their status as `'SUBMITTED'` and retains their point allocations, public shared memories, and consent timestamps to protect the Executor's record-keeping obligations and keep the math solver preferences matrix complete.
*   **Constraint**: Returns `400 Bad Request` if the mediation session status is `'LOCKED'` or `'FINALIZED'` to preserve the completed division ledger.
*   **Response**: `{"status": "success", "message": "Personal identification purged; account records soft-anonymized and checkpointer states cleared for probate record-keeping."}`

### 2.3b `PUT /api/heirs/me/profile` (Heir Profile Self-Correction & Audit Log)
*   **Purpose**: Allows heirs to correct typos in their name, date of birth, relationship to decedent, or contact info to ensure the final probate audit ledger matches official documents, while automatically enforcing fresh identity inspection.
*   **Logic**:
    1. If the Heir changes `legal_first_name`, `legal_middle_name`, `legal_last_name`, or `date_of_birth`, the backend resets `identity_verified = False`, updates the Heir's status to `'PROFILE_HOLD'`, and—if an ID scan document is present in storage—permanently deletes the encrypted scan file from disk and sets `id_scan_uri = NULL` to force a fresh ID scan upload matching the corrected legal profile.
    2. Writes a `'USER_PROFILE_UPDATE'` audit log event, capturing a JSON snapshot of the changed keys, old values, and new values, encrypted at rest using AES-Fernet.
*   **Constraint**: Returns `400 Bad Request` if the session is locked or finalized, or if the Heir's status is `'ABSTAINED'` or `'EXPIRED_NON_PARTICIPATING'`.


### 2.4 `GET /api/system/models` (California AB 2013 - AI Training Data Transparency)
*   **Purpose**: Returns metadata outlining the local model parameters, licensing, and training provenance.
*   **Logic**: The endpoint must dynamically query the active models running in the environment (reading from environment variables `FAST_THINKER_MODEL`, `SLOW_THINKER_MODEL`, and `VISION_MODEL`). It returns corresponding parameters, licensing, and training provenance matching the active model names, falling back to the standard Qwen-2.5-8B/14B defaults if not overridden.
*   **Response**:
    ```json
    {
      "models": [
        {
          "component": "Fast Mediator (System 1)",
          "name": "Qwen-2.5-8B-Instruct",
          "parameters": "8.0B",
          "license": "Apache-2.0",
          "provenance": "Pretrained on Qwen open training datasets; fine-tuned for instruction-following."
        },
        {
          "component": "Slow Critic (System 2)",
          "name": "Qwen-2.5-14B-Instruct",
          "parameters": "14.2B",
          "license": "Apache-2.0",
          "provenance": "Pretrained and post-trained by Alibaba Cloud; optimized for reasoning and logical validation."
        },
        {
          "component": "Vision OCR Engine",
          "name": "Llava-1.5",
          "parameters": "7.0B",
          "license": "Apache-2.0",
          "provenance": "CLIP ViT-L/14 visual encoder and Llama-2; trained on public multi-modal datasets."
        },
        {
          "component": "Local Speech Synthesis (TTS)",
          "name": "Kokoro-82M ONNX",
          "parameters": "82M",
          "license": "Apache-2.0 / Custom Research",
          "provenance": "Trained on public domain and CC-licensed audio datasets. Runs locally on CPU."
        },
        {
          "component": "Semantic Search & RAG Embedding Engine",
          "name": "nomic-embed-text",
          "parameters": "137M",
          "license": "Apache-2.0",
          "provenance": "Trained by Nomic AI on public web text. Generates 768-dimensional dense vectors for estate asset similarity search and RAG context retrieval."
        }
      ]
    }
    ```

### 2.5 WebSocket synthetic audio indicator (California SB 942)
*   The `chat_reply_chunk` frame contains the `"is_synthetic": true` field:
    ```json
    {
      "type": "chat_reply_chunk",
      "text": "Sentence text",
      "sender": "agent",
      "audio": "BASE64_WAV_BYTES",
      "is_synthetic": true,
      "is_final": false
    }
    ```

---

## 3. UI/UX Interface Requirements

The frontend implementation must render explicit compliance controls to satisfy user rights and disclosure laws.

### 3.1 Onboarding Consent Card, Age Gate, & E-SIGN Act Disclosure
*   **Location**: Pre-registration workspace landing page (`/invite/:token`).
*   **Layout**: Centered Warm Archival Index Card (`var(--color-card-bg)` on `var(--color-bg)`).
*   **Privacy Text**: Playfair Display header. Explains data collections (chat logs, points), storage security (AES-256), Presidio sanitization, and rights to export/delete data.
*   **CCPA Notice**: *"We do not sell, share, or monetize your personal information. All data is processed locally on our self-hosted platform."*
*   **E-SIGN Act Consumer Disclosure Banner**: Integrates clear disclosures informing the user:
    1.  **Electronic Delivery Consent**: All notifications, keepsakes, and legal waivers (including the Abstention Waiver) will be delivered electronically.
    2.  **Right to Withdraw Consent**: Heirs may withdraw electronic consent at any time without fees, but doing so will require physical service of notices and paper ledger filings.
    3.  **Hardware & Software Specs**: Client requires a modern browser (Chrome, Firefox, Safari) and PDF reader.
    4.  **Right to Paper Records**: Heirs have the right to request paper copies of all files from the Executor free of charge.
*   **Legal Profile & Contact Confirmation**: Displays a single, clean summary card of the Heir's pre-filled legal details (Legal Name, DOB, Relationship, Email, Phone, Address) pre-populated by the Executor. Rather than typing in multiple fields, the Heir reviews their details and checks a confirmation box: *"These details are correct and match my official identity documents."* If a typo exists, the Heir can edit their details directly using the profile editor (which updates their details, resets identity verification, and places them on `'PROFILE_HOLD'`).
*   **Government ID Scan (Mobile-First Capture)**: Eliminates file manager uploads for mobile users. Tapping *"Scan ID"* opens the device camera directly within a clean card-shaped overlay guide, letting Heirs capture their Driver's License or Passport in one tap. For desktop users, a simple drag-and-drop slot is provided. **Security & Deletion Policy & Profile Hold**: The scan is encrypted immediately on-the-fly and stored locally. To prevent unverified modifications or submissions, Heirs are locked in a read-only `'PROFILE_HOLD'` status (which freezes sliders and chat) while their verification is pending. Upon approval (or rejection) by the Executor, the temporary ID scan file is permanently purged from disk storage immediately and `id_scan_uri` is set to `NULL` to minimize PII retention.
*   **Age Checkbox**: Mandatory check box: *"I confirm that I am at least 18 years of age, verify that my legal profile is correct, and explicitly agree to the Privacy Policy and E-SIGN Electronic Records Disclosure."*
*   **Action Buttons**:
    1.  **Confirm & Enter Workspace** (Sage Green fill). Disabled until the Age Checkbox is checked. Triggers backend verification and saves updated contact info.
    2.  **Decline & Exit** (Muted grey border). Redirects to the `/opt-out` exit page.

### 3.2 AI Bot Disclosure (California SB 1001)
*   **Mediation Panel (Mobile)**: Permanent banner at the top of the chat page: **"Chatting with AI Mediator"** (low contrast, Slate-900).
*   **Mediation Panel (Desktop)**: Permanent header title inside the right-hand chat window: **"AI Mediator Agent"** (highly visible).

### 3.3 synthetic Voice metadata disclosure (California SB 942)
*   A persistent text note or status label must be placed beneath the voice play/mic buttons: *"Synthesized AI Voice"*.
*   The frontend audio player must parse the WebSocket chunk and confirm that the incoming stream carries the `is_synthetic` signature, ensuring that synthesized audio is labeled in the client state.

### 3.4 Data Portability Trigger (GDPR Article 20)
*   **UI Trigger**: *"Export My Data (JSON)"* button in the settings/help drawer.
*   **Action**: Performs an authenticated GET fetch to `/api/heirs/me/export` and downloads the structured JSON payload.

### 3.5 Account Deletion Drawer (GDPR Article 17 / Soft Anonymization)
*   **UI Trigger**: *"Delete My Account & Personal Data"* link in red text.
*   **Confirmation Dialog**: Slide-up warning modal. Warns that their display name, email, and private chat transcripts will be permanently purged, and their account details will be soft-anonymized for the court probate records.
*   **Safety Gate**: Requires the user to type their username (case-sensitive) to enable the confirmation action.
*   **Action**: Calls `DELETE /api/heirs/me`, clears local client state, and redirects the browser to `/`.

### 3.6 AI Model Transparency & Provenance Modal (California AB 2013)
*   **UI Trigger**: *"AI Model Details & Training Transparency"* link in help drawer.
*   **Action**: Opens a modal displaying the model details retrieved from `/api/system/models` in a structured table.
