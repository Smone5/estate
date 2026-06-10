# Estate Steward: Legal Estate & Probate Compliance Specification (v1.0)

This specification defines the legal compliance boundaries, probate court documentation standards, and evidentiary requirements for **The Estate Steward**. It ensures that the platform's outputs (ledgers, audit trails, and actions) help the Executor (Admin) satisfy their fiduciary duties under the Uniform Probate Code (UPC) and equivalent state-level estate laws.

---

## 1. Fiduciary Duties & System Alignments

To protect the Executor from personal liability, the platform must compile evidence demonstrating that the estate division complied with core fiduciary duties:

### 1.1 Duty of Impartiality (UPC § 3-703)
*   **Legal Rule**: The Executor must treat all heirs and beneficiaries impartially, showing no favoritism or personal bias in asset distribution.
*   **System Alignment**: 
    *   **Algorithmic Neutrality**: The system uses a mathematically defined, peer-reviewed fair-division algorithm (`MaximumNashWelfare` via `fairpyx`) to distribute assets based strictly on the points allocated by the heirs.
    *   **Points Privacy**: Individual point allocations remain private during active mediation, preventing heirs from bidding tactically or reacting to others' bids.
    *   **Deterministic Tie-Breaking**: To prevent arbitrary division and potential Executor bias, if two or more heirs submit identical point allocations for an asset, the system breaks the tie using objective, non-discretionary rules: first, by awarding the asset to the Heir with the earliest submission timestamp (`submitted_at`), and second, falling back to sorting user UUIDs alphabetically.
    *   **Documented Impartiality**: The final ledger details the mathematical formula and preference inputs, proving the distribution was derived objectively.

### 1.2 Duty to Account & Maintain Records (UPC § 3-706)
*   **Legal Rule**: The Executor must compile and maintain a clear, transparent, and accurate inventory and final distribution ledger for probate court filing.
*   **System Alignment**:
    *   **Tamper-Proof Audit Chain**: All events (allocations, edits, overrides) are bound into a cryptographically sealed SHA-256 block-hash ledger. Any manual change by the Executor is permanently recorded with an `ADMIN_OVERRIDE` block.
    *   **Integrity Verification**: If any database row is altered after the session is finalized, the hash chain breaks, providing clear proof of tamper-detection.

---

## 2. Documenting Non-Participation & Abstention (Due Notice)

If an Heir is invited but does not participate, the Executor must be able to prove to the probate court that the Heir was given **Due Notice** and a reasonable opportunity to claim their share, but voluntarily declined or failed to act.

### 2.1 The Due Notice Database Trail
To establish due notice, the database records and logs:
1.  **Creation Timestamp**: The exact UTC time the Heir profile was created.
2.  **Invitation Dispatched Timestamp**: The UTC time the SMTP email server relay confirmed delivery of the invite token.
3.  **Expiration Boundary**: A configurable token expiration limit (default 14 days, adjustable by the Admin during session setup, recorded in `invite_token_expires_at`) indicating the notice window provided.
4.  **Verification Checkpoints**: Records if the invite link was ever accessed (`invite_token_used = False` and `consent_accepted = False` confirms absolute non-participation).

### 2.2 Formal Abstention & Waiver Sequence
The system supports two pathways of non-participation, both formally documented in the final PDF ledger and audit database:

```
[ Heir receives invitation email ]
               |
      +--------+--------+
      |                 |
(No Action)      (Active Abstention)
      |                 |
[Expires after]  [Clicks "Abstain from Division"]
[ Config Window]         |
      |          [Signs Digital Waiver]
      |                 |
      +--------+--------+
               |
               v
[   Admin Finalization Trigger  ]
               |
[ Math Solver Excludes Abstainer ]
               |
[ Ledger logs: "Charlie Abstained" ] ---> [ File PDF with Probate Court ]
```

#### Pathway A: Silent Non-Participation (Expiration)
*   **Sequence**: The Heir receives the email but does not click the link or accept consent within the configured notice window (default 14 days).
*   **Finalization Behavior**: The system automatically marks their status as `'EXPIRED_NON_PARTICIPATING'`.
*   **Ledger Output**: The final audit ledger includes the following entry:
    > *"Heir [Name] ([Email]) was registered on [Date]. Invitation link delivered via SMTP on [Date]. The invitation expired on [Date] with zero logged user activity. Pursuant to estate instructions, Heir [Name] has been marked as Non-Participating and excluded from point-allocation math."*

#### Pathway B: Active Abstention (Waiver of Rights)
*   **Sequence**: The Heir clicks the link, accepts privacy terms, but decides they do not want to claim any physical assets. They click **"Abstain & Waive Allocation Rights"** on their dashboard.
*   **The Waiver Modal**: Opens a legally worded waiver card:
    > *"I, [Heir Name], hereby voluntarily abstain from the points allocation process and waive all rights to claim physical assets through the digital mediation system. I consent to having the remaining assets distributed among the participating heirs."*
    *   Heir must type their full legal name to confirm.
*   **Database Log**: Upon submission, the system writes a signed `'ABSTENTION_WAIVER'` block containing the Heir's IP address, timestamp, and typed signature to `audit_logs` (encrypted at rest), and sets their status to `'ABSTAINED'`.
*   **Record Delivery (E-SIGN/UETA Compliance)**: To satisfy the electronic record delivery rule (15 U.S.C. § 7001(c)), the onboarding flow must present clear consumer disclosures (e.g., electronic delivery consent, hardware/software specs, right to withdraw, right to paper copies) before any action. Upon signing the waiver, the system must immediately dispatch a confirmation email to the Heir's registered email address containing the full signed waiver, timestamp, and IP address, and display a "Download Signed Waiver Receipt (PDF)" button on the opt-out waiting page (which calls `GET /api/heirs/me/abstain/receipt` to download the ReportLab PDF). If SMTP delivery fails, the waiver signature is still committed, but `users.waiver_email_failed` is set to `True` and a system-generated alert support request is created in the database with status `'OPEN'` to notify the Executor in the Admin console that they must physically deliver a printed paper copy of the receipt.
*   **Ledger Output**: The final ledger lists:
    > *"Heir [Name] signed a digital Abstention Waiver on [Date/Time] (IP: [IP]). Excluded from point-allocation math."*

---

## 3. The Court-Admissible Final Ledger Structure

The final printable document (**"Final Distribution & Probate Audit Ledger"**) is structured to serve as a legal accounting document for executors. It must include:

1.  **Session Metadata**: Estate name, Executor name, start date, and closure date.
2.  **Registered Beneficiary Table**:
    *   Lists Heirs, registered emails, participation status (`SUBMITTED` | `ABSTAINED` | `EXPIRED_NON_PARTICIPATING`).
3.  **Proof of Notice Log**: Detailed timestamp logs of invitation emails sent, deliveries confirmed, and expiration bounds.
4.  **Final Asset Allocation Grid**: The final outcome detailing which asset was allocated to whom, and its estimated appraisal range.
5.  **Maximum Nash Welfare Product Display**: A dedicated summary callout box displaying the session's overall Nash welfare product.
6.  **Deterministic Tie-Breaker Resolution Record**: Logs any tie-breaker events applied by the solver, showing which heirs tied, their points, their submission timestamps (`submitted_at`), and the deterministic outcome.
7.  **Admin Intervention Log**: Detailed list of any Executor manual overrides, reasons given, and timestamps.
8.  **Cryptographic Integrity Seal**: The final SHA-256 block hash, printed as a monospace code block, with instructions on how to verify database checksums.

---

## 4. Scope Limitations & Asset Exclusions
To protect the Executor from violating statutory probate procedures, the platform must enforce strict scope boundaries:
*   **Tangible Personal Property Only**: The system is designed exclusively for the division of **tangible personal property** (household chattels, keepsakes, jewelry, furniture, art, tools).
*   **Real and Financial Property Excluded**: The system is legally unsuitable and must **not** be used to divide or allocate:
    1.  **Real Property**: Land, houses, or permanent buildings (which require deeds and formal transfer filings).
    2.  **Financial Assets**: Bank accounts, securities, stock portfolios, retirement accounts, or cash (which require bank administration or brokerage transfers).
    3.  **Titled Vehicles**: Automobiles, boats, or aircraft (which require state-level title registration transfers).
*   **System Enforcement Warning**: The Admin Dashboard asset uploading panel must display a permanent, clear notice: *"This system is strictly for personal property and keepsakes. Do not upload real estate, vehicles, or bank/financial accounts."*
*   **Valuation Source Documentation**: To satisfy executor fiduciary responsibilities under Uniform Probate Code § 3-706 (probate inventory requirements), every asset must have a declared appraisal valuation source (e.g., 'Professional Appraisal', 'Tax Assessment', 'Estate Sale Estimator'). Estimations without a declared source must be flagged in the admin console, and the source must be displayed alongside the appraisal range in the final court ledger.
*   **Will Compliance & Specific Bequests**: To ensure that the platform conforms to the decedent's Will or Trust instructions, the system must support **Pre-Allocated Assets**. If the Will explicitly bequeaths a specific asset to a specific Heir (a specific devise), the Executor must mark this asset as `'PRE_ALLOCATED'` and assign it to that Heir during session setup. These assets must be excluded from point bidding and the Maximum Nash Welfare division math solver, preventing emotional family conflict and preserving legal compliance with the Will.

---

## 5. Fiduciary Disclaimers & Legal Guardrails
*   **No Legal Advice Disclaimer**: The system must display a permanent, clear disclaimer in the footer of all dashboard views and on the cover page of all generated PDF reports:
    > *"Disclaimer: The Estate Steward is a collaborative mediation aid designed to assist executors and heirs in dividing personal property. It does not provide legal advice, estate planning, or tax counsel. Use of this tool does not guarantee probate court approval. Executors are advised to consult with a licensed probate attorney regarding their fiduciary obligations and court filings."*
*   **Advisory Nature of Algorithm**: The Executor must check an acknowledgment during session initialization stating they understand that the Max Nash Welfare algorithm results are advisory and become binding only upon mutual agreement of the heirs or explicit court order.

---

## 6. Mediation Confidentiality vs. Executor Disclosure
To encourage open, honest communication and reduce hostility among grieving heirs:
*   **Transcripts Confidentiality**: Conversation transcripts between an Heir and the AI Mediator are **strictly confidential** to that Heir. The Administrator (Executor) and other heirs are blocked from viewing these transcripts. The API endpoint `GET /api/sessions/{session_id}/heirs/{heir_id}/chat` must restrict access exclusively to the matching Heir (returning `403 Forbidden` for Admin credentials).
*   **Points Privacy**: Individual point valuations must remain confidential during active mediation to prevent strategic bidding or intimidation. The Admin dashboard monitor table displays only checkmarks indicating completion progress.
*   **Grief Pause Token & Deadline Extension**: To ensure "Due Notice" compliance is not compromised, when the Executor triggers a Grief Pause (locking the session), the countdown for all active heir invitation tokens and the session deadline must be paused. The start of the pause is recorded in `sessions.paused_at`. Upon unpausing, the database transaction calculates the elapsed pause duration and dynamically extends the `invite_token_expires_at` timestamps for all heirs (regardless of whether they are pending or have already logged in) whose deadlines are not yet passed and the session `deadline` by this total duration, preventing expirations while mediation is suspended.
*   **Required Disclosures**: The final court-admissible ledger discloses only the finalized allocation mapping, the shared stories (where the heir explicitly checked *"Share this memory with my family"*), and the Admin override log, preserving raw conversation privacy.

---

## 7. Session Retention, GDPR Erasure, & Disaster Recovery

### 7.1 GDPR Right to Erasure vs. Fiduciary Records Retention (Soft Anonymization)
*   **Legal Conflict**: GDPR Article 17 (Right to Erasure) allows users to delete their personal data. However, the Uniform Probate Code (UPC § 3-706) obligates the Executor to preserve all distribution and valuation records for court filings.
*   **System Resolution**: If an Heir requests account deletion (`DELETE /api/heirs/me`) during an active session, the system must perform a **soft anonymization** rather than a hard purge.
    *   **Permanently Deleted**:
        *   All rows in `chat_messages` matching this Heir's ID are permanently purged. Chat transcripts contain raw personal sentiments and PII and are not required for the math solver, the final allocation ledger, or probate court filings.
        *   All LangGraph checkpointer state database records (checkpoints, checkpoint_writes, etc.) matching this Heir's thread ID (`f"{session_id}:{heir_id}"`) are permanently deleted.
        *   The ID scan file at `id_scan_uri` (if still on disk) is permanently deleted from local storage.
    *   **Scrubbed / Anonymized (Fields Overwritten)**:
        *   `username` → `"Anonymized Beneficiary [UUID]"`
        *   `legal_first_name` → `"Anonymized"`, `legal_last_name` → `"Beneficiary [UUID]"`
        *   `legal_middle_name`, `email`, `phone`, `physical_address`, `relationship_to_decedent`, `date_of_birth`, `id_scan_uri`, `invite_token`, `pw_hash` → `NULL`
    *   **Retained Records**: Points allocations in `valuations`, public shared memories (`is_reasoning_shared = true`), consent timestamps, and invitation timestamps are preserved in the database and SHA-256 audit logs to keep the ledger mathematically and legally intact for probate court filing.


### 7.2 Disaster Recovery & Mnemonic Paper Recovery Key
*   **The Vulnerability**: All database columns and audit records are encrypted using the symmetric AES-Fernet key `ENCRYPTION_KEY`. If the host machine experiences a catastrophic hardware crash, the encrypted backups are unrecoverable without the exact key.
*   **System Guard**: During initial Admin setup, the system derives a human-readable **Paper Recovery Key** (a 24-word BIP39 mnemonic seed phrase representing the active 32-byte system `ENCRYPTION_KEY`) and forces the Admin to confirm they have saved/printed it offline before session creation is unlocked.
*   **Restoration Flow**: In a disaster recovery scenario, the Admin can enter this 24-word seed phrase during backup restoration (`POST /api/system/restore`) to decrypt and recover all records.

### 7.3 Session Retention & Data Purging Lifecycle
*   **Local-First Security**: Since all database records are stored locally on the Raspberry Pi host, no data is transmitted to or stored in a public cloud.
*   **Fiduciary Archival Protocol**: The Executor is responsible for preserving probate records for the statutory period (typically 3 to 7 years depending on state laws). Once the finalized PDFs are downloaded and archived physically or in secure files, the Executor should trigger the **"Secure Session Purge"** from the Admin panel.
*   **Purging Action**: The purging protocol permanently deletes the database records for that session (wiping all user entries, encrypted chat logs, and valuation tables) from the Raspberry Pi's local SSD/SD card, satisfying right-to-be-forgotten compliance once the executor's record-keeping duty is transferred to the physical court filing.

### 7.4 Legal Beneficiary Identification & Identity Verification Audit
To ensure the final distribution records and waivers (such as the Abstention Waiver) are legally binding in a probate court, the system collects and audits official identification data while minimizing sensitive data storage:
*   **Collection Bounds**: Heirs must provide their official legal name (First, Middle, Last), Relationship to Decedent, Date of Birth (DOB), and contact details.
*   **The ID Verification Workflow & Read-Only Hold**:
    1.  **Heir Upload & Hold**: During onboarding, the Heir uploads a picture/scan of a government-issued ID (Passport, Driver's License) which is encrypted on-the-fly and stored at `id_scan_uri`. The Heir is locked in a read-only `'PROFILE_HOLD'` status, disabling sliders and chat, to prevent invalid actions on the probate ledger before validation.
    2.  **Executor Inspection**: The Executor accesses the Admin Console to visually inspect the ID image side-by-side with the Heir's declared legal details.
    3.  **Approval & Purge**: Upon confirmation, the Executor clicks "Approve Identity" (`POST /api/heirs/{heir_id}/verify-identity` with `action: approve`). The system updates `identity_verified = True`, transitions user status to `'ACTIVE'`, logs the approval action in the block-chained audit logs, broadcasts a WebSocket alert to unlock the Heir dashboard, and **permanently deletes** the ID scan file from disk, resetting `id_scan_uri = NULL`.
    4.  **Rejection & Purge**: If the ID does not match, the Executor selects "Reject & Flag" with a reason (`POST /api/heirs/{heir_id}/verify-identity` with `action: reject`). The system **immediately purges** the temporary ID scan from disk, resets `id_scan_uri = NULL`, logs the rejection in the audit chain, and sends a WebSocket alert prompting the Heir (remaining in `'PROFILE_HOLD'`) to submit corrected details (via `PUT /api/heirs/me/profile`) and a new ID scan (via `POST /api/heirs/me/upload-id`).
*   **Evidentiary admissibility**: By recording the fact of verification and immediately deleting the high-risk ID scan file, the platform proves to the court that the Executor fulfilled the duty to verify beneficiary identities while protecting the estate and the platform from storing unneeded sensitive PII.
*   **Profile Audit Trail**: Any updates to contact or legal profile fields generate a `USER_PROFILE_UPDATE` event, capturing the old values, new values, editor ID, and timestamp, and appending the record to the SHA-256 tamper-proof hash chain.


