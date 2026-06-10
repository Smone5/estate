# Phase 4: Probate Keepsakes & Fair Division Math

## Phase Objective
Develop the ReportLab PDF rendering engine, integrate the Fairpyx division solver, and expose the GDPR soft anonymization router. Write incremental unit tests for these foundations. Note: A 2 to 3 business day schedule buffer is explicitly injected between Phase 4 and Phase 5 to allow API contract validation and integration testing before frontend state management consumes Phase 4 endpoints.

## Technical Specifications References
* [Backend System Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_backend.md)
* [Database Schema & Transaction Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_db.md)
* [Legal Estate & Probate Compliance Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_legal.md)
* [Testing & Verification Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_testing.md)

## Detailed Requirements & Architecture
1. **Keepsake PDF Report Engine (ReportLab)**:
   * Program backend routes to compile high-quality PDF files.
   * **NumberedCanvas Pagination**: Write a custom canvas subclassing `canvas.Canvas` to perform a double-pass calculation. Draw page footers in the format `"Page X of Y"` and background canvas assets on all pages except the cover page.
   * **Paragraph Cell Wrapping**: Build tables placing text cells inside ReportLab `Paragraph` flowables. Enforce explicit column widths to prevent descriptions from overflowing.
   * **Dynamic Columns and Landscape Rotation**: For the dynamic heir points matrix table, calculate column widths programmatically (`width_title = 2.5in` and split remaining `4.5in` equally among the $N$ heirs). If $N > 4$, transition the page section template to a Landscape layout to widen printable space to `9.5in` (where `width_title = 3.5in` and remaining `6.0in` is split among heirs).
   * **Cloud Image Buffer**: If `STORAGE_DRIVER=GCS` is enabled, download remote asset image URLs into an `io.BytesIO` buffer rather than passing string URLs to ReportLab.
   * **Output Files**:
     1. *Heir Keepsake Memory Book*: Cover page, division summary, and allocated heir items list.
     2. *Final Distribution & Probate Ledger*: Estate details, beneficiary tables, proof of notice log, final grid, admin intervention log, and monospace cryptographic block hash seal.
   * **Legal Disclaimer Cover Page**: Both PDF document types must include the legal disclaimer on the cover page per Legal Spec §5.
2. **Fairpyx Division Solver & Max Nash Welfare**:
   * Integrate the `fairpyx` library to perform Maximum Nash Welfare (MNW) divisions on live assets using heir points matrices.
   * **Zero-Utility Starvation Check**: Implement a validation check. If the count of active heirs who have not been pre-allocated assets exceeds the count of remaining live assets, automatically bypass the zero-utility starvation exception in the math engine.
   * **Persistent Allocations**: Upon solver completion, iterate through the winning results. Update the asset records: write the winning Heir UUID to `allocated_to_id` and transition status to `'DISTRIBUTED'` in the database.
3. **Deterministic Solver Tie-Breaker**:
   * If heirs bid identical points on a contested asset, resolve the allocation deterministically:
     1. Award to the Heir with the earliest `submitted_at` timestamp.
     2. If timestamps match (or are null), fall back to alphabetical sorting of the heirs' UUID `id` strings.
   * **Datetime Epoch conversion**: Ensure the tie-breaker formula converts all datetime columns (`submitted_at`, `created_at`, `deadline` timestamps) to float Unix epochs before subtraction to avoid Python `TypeError` exceptions.
   * **Epsilon Math Zero Division Guard**: Add check: if $T_{\text{end}} - T_{\text{start}} == 0$, set the time delta epsilon to `0.0` to prevent `ZeroDivisionError` exceptions during calculation.
4. **Finalization API**:
   * Build `POST /api/sessions/{session_id}/finalize` endpoint.
   * Action: Exclude abstained/expired heirs, verify no heirs are on `'PROFILE_HOLD'` or pending submission (unless invitation expired), compute the fair division, and seal the audit log hash chain.
5. **Session Override API**:
   * Build `POST /api/sessions/{session_id}/override` HITL endpoint.
   * **Logic**: The Admin selects a winning Heir for each deadlocked asset and provides a fiduciary reason. The endpoint calls `graph.update_state(config, {"valuations": corrected_valuations}, as_node="HITL_GUARD")` to write corrected allocations directly into the Postgres checkpointer state, then calls `graph.stream(None, config)` to resume execution, skipping the HITL_GUARD node and routing directly to `COMMIT_NODE`.
   * Each override must generate an `'ADMIN_OVERRIDE'` audit log block recording the Executor's decision reason and the affected assets.
   * Returns `400 Bad Request` if session is not in `'LOCKED'` or deadlocked state.
   * **NOTE: Does NOT depend on T63 (Pi 5 memory profiling). The checkpointer state schema used by the override API is defined by T07/T08 code artifacts (the `MediationState` TypedDict), not by which specific model size is selected. T63 was incorrectly listed as a dependency.**
6. **GDPR Soft Anonymization API**:
   * Expose `DELETE /api/heirs/me` soft anonymization logic. Purge PII from `users` (overwrite username/name/contact fields to `"Anonymized"` or `NULL`), cascade delete private chat logs and checkpointer records matching thread `f"{session_id}:{heir_id}"`, delete active ID scan files, and recursively sanitize historical audit log snapshot strings. Handles unsubmitted vs submitted status logic to prevent points pool sum validation errors.
7. **GDPR Data Portability API**:
   * Expose `GET /api/heirs/me/export` data portability logic. Stream a structured JSON payload containing the Heir's personal details, decrypted chat history, point valuations, and open/resolved support requests.

## Phase Checklist & Tasks

### [ ] Task T12: FastAPI Valuation Router
* **Objective**: Expose draft save routes (`PUT .../draft` checking incremental `draft_version` to prevent race conditions) and submission routes (`POST .../submit` checking points total == 1000 and locking values under pessimistic session row locks), checking if the user's LangGraph thread is suspended at `HITL_GUARD`. Pre-fetches the audit log primary key `id` via `SELECT nextval('audit_logs_id_seq')` to calculate the SHA-256 hash before insertion. Triggers check for all heirs submitted to run solver asynchronously. Depends on T02, T07a, T08, T10, T11, T37.
* **Verification**: Verify valuations submission fails if points do not sum to 1000, locks sliders on success, and respects LangGraph workflow gates.

### [ ] Task T71: Proof of Notice Log Data Contract
* **Objective**: Formalize the notice log data structure exposed by T13 and T65, defining invitation timestamps, dispatches, and expiration bounds, which is consumed by the PDF builder (T14). Depends on T13, T65.
* **Verification**: Verify that the notice log data schema is correctly declared and can be populated from users table rows.

### [ ] Task T14: ReportLab PDF Builders
* **Objective**: Write the Keepsake and Probate Ledger PDF generation modules with canvas page numbers, text cell paragraph wrappers, dynamic columns (with programmatic width calculations and transition to Landscape layout if $N > 4$ heirs), an `io.BytesIO` cloud image buffer when GCS is active, and legal disclaimer on cover page per Legal Spec §5. Depends on T02, T03, T71.
* **Verification**: Assert that generated PDFs have cover pages (including legal disclaimer), tabular layouts, and correct page numbers.

### [ ] Task T15: Fairpyx MNW Solver & Tie-Breakers
* **Objective**: Integrate the Fairpyx solver and write the deterministic tie-breaking epoch math (using `submitted_at`, `created_at`, and `deadline`) and zero-utility starvation checks. Depends on T02.
* **Verification**: Mock a tie bid and verify that the solver awards it to the earlier submitter.

### [ ] Task T70: Tie-Breaker Resolution Record in PDF
* **Objective**: Extend the PDF builder (T14) to capture tie-breaking events from the solver (T15) and print a Deterministic Tie-Breaker Resolution Record table. Depends on T14, T15.
* **Verification**: Run solver on tied bids and verify the generated PDF contains the tie-breaker resolution table displaying names, points, and timestamps.

### [ ] Task T16: FastAPI Keepsake & Finalization Router
* **Objective**: Write the finalization endpoints (`POST /api/sessions/{session_id}/finalize`) executing the solver, committing results, and downloading keepsake/ledger files. The finalization transaction must automatically check and transition non-submitting active heirs to `'ABSTAINED'` and un-logged-in expired heirs to `'EXPIRED_NON_PARTICIPATING'` prior to compiling the solver preference matrix. Depends on T12, T14, T15, T65, T70.
* **Verification**: Verify that finalization locks the session and computes allocations, generating a cryptographic hash seal. Verify that non-submitting active heirs are auto-abstained, expired heirs are auto-expired, and both are excluded from the solver matrix.

### [ ] Task T44: Session Override API
* **Objective**: Build `POST /api/sessions/{session_id}/override`. Accept a list of force-allocated asset→heir assignments plus a fiduciary reason. Write corrected valuations into the LangGraph checkpointer state via `graph.update_state()`, resume graph execution via `graph.stream(None, config)`, and write an `'ADMIN_OVERRIDE'` audit log block. Gate on `'LOCKED'` or deadlocked session state. **Must adjust heir points budgets. NOTE: Does NOT depend on T63 — the checkpointer state schema is defined by T07a/T08 code artifacts, not by Pi 5 model size selection.** Depends on T02, T07a, T08, T10, T12.
* **Verification**: Trigger a deadlock scenario. Call the override endpoint with a valid allocation. Assert that the LangGraph resumes to `COMMIT_NODE`, assets are marked `'DISTRIBUTED'`, and the audit log records the override.

### [ ] Task T33: Active Abstention Waiver PDF Receipt & Email
* **Objective**: Implement the `/api/heirs/me/abstain` endpoint (including digital waiver logging, SMTP receipt dispatch, and fallback support ticket creation if SMTP fails) and the `/api/heirs/me/abstain/receipt` endpoint (ReportLab PDF). Depends on T12, T14, T37.
* **Verification**: Verify that calling abstain updates user status to `'ABSTAINED'`, cascade deletes default valuations, and yields a valid downloadable single-page PDF receipt with signature details.

### [ ] Task T55: FastAPI Heir GDPR Erasure Router
* **Objective**: Implement `DELETE /api/heirs/me` soft anonymization (purging chat logs, deleting checkpointer thread states, removing ID scans from disk, and sanitizing historical snapshots in `audit_logs` based on submission status). Depends on T02, T08, T09b, T10, T12, T13, T31.
* **Verification**: Verify that deleting an heir's account purges private chat and checkpointer DB entries, and that it anonymizes audit logs.

### [ ] Task T57: FastAPI GDPR Data Portability API
* **Objective**: Expose `GET /api/heirs/me/export` returning decrypted chat logs, valuations, profile details, and tickets in a structured JSON. Depends on T02, T03, T10, T12, T13, T42.
* **Verification**: Call the export endpoint and assert that a valid JSON object is returned containing matching profile details and decrypted chat logs.

## Phase Dependency Graph
```mermaid
graph TD
    T02[T02: SQLAlchemy Models & Relations] --> T12[T12: FastAPI Valuation Router]
    T07a[T07a: LangGraph State Schema, Nodes & Prompt Templates] --> T12
    T08[T08: LangGraph PostgresSaver Integration] --> T12
    T10[T10: FastAPI Core & Onboarding endpoints] --> T12
    T11[T11: FastAPI Asset Router] --> T12
    T37[T37: FastAPI Session Lifecycle & Announcement API] --> T12
    
    T02 --> T14[T14: ReportLab PDF Builders]
    T03[T03: AES-Fernet Encryption Decorator] --> T14
    T71[T71: Proof of Notice Log Data Contract] --> T14
    
    T13[T13: FastAPI Heir Management & Invitations] --> T71
    T65[T65: Background Invite Expiration Scheduler] --> T71

    T02 --> T15[T15: Fairpyx MNW Solver & Tie-Breakers]
    
    T14 --> T70[T70: Tie-Breaker Resolution Record in PDF]
    T15 --> T70

    T12 --> T16[T16: FastAPI Keepsake & Finalization Router]
    T14 --> T16
    T15 --> T16
    T65[T65: Background Invite Expiration Scheduler] --> T16
    T70 --> T16
    
    T12 --> T33[T33: Active Abstention Waiver PDF Receipt & Email]
    T14 --> T33
    T37 --> T33
 
    T02 --> T44[T44: Session Override API]
    T07a --> T44
    T08 --> T44
    T10 --> T44
    T12 --> T44

    T02 --> T55[T55: FastAPI Heir GDPR Erasure Router]
    T08 --> T55
    T10 --> T55
    T12 --> T55
    T13 --> T55
    T31[T31: Government ID Scan Upload API] --> T55
    T09b[T09b: Image Preprocessing & Concrete Drivers] --> T55

    T02 --> T57[T57: FastAPI GDPR Data Portability API]
    T03 --> T57
    T10 --> T57
    T12 --> T57
    T13 --> T57
    T42[T42: Support Request & Help CRUD API] --> T57