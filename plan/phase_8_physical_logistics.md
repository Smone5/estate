# Physical Distribution & AI-Driven Logistics Copilot

This plan details the implementation of a physical asset distribution module, handoff tracking system, and AI-driven logistics assistant. The module transitions the application from a paper-only allocation solver into a comprehensive, end-to-end estate distribution system.

---

## Aligned Design Decisions

During our `/grill-me` alignment, the following design decisions were solidified:
1. **Receipt Flow**: Box-by-box/batch sign-off. Heirs sign a single receipt for a box of items, with individual checkboxes to flag items as damaged or missing.
2. **Item Grouping**: AI auto-groups items into boxes based on dimensions, weight, and fragility. The Executor can adjust these groupings in a drag-and-drop UI.
3. **Damage Auditing**: On packing day, the AI compares catalog and packing photos. If a mismatch is found, it issues a warning; the Executor inputs an override note and continues, logging the dispute to the audit trail.
4. **Communication & Scheduling**: Heirs receive a link via email/SMS that launches a friendly AI chat helper inside their dashboard to guide them through address verification and calendar scheduling.
5. **Post-Finalization Swaps**: Heirs can trade or gift allocated items. The Executor initiates the swap in the console, and both heirs must approve it in their dashboards to commit and log it.
6. **Unclaimed Items**: If the statutory pickup deadline passes, the system prompts the Executor to re-route the items to `UNCLAIMED_STORAGE`, logging the physical address of the storage facility.
7. **Shipping & Postage (Hybrid Model)**:
   * **Open-Source Core**: Standard formatted address printing, return address slips, packaging lists, and QR label sheets.
   * **Optional Plugins**: Support for Shippo/EasyPost integration via custom API keys so Executors can choose to purchase postage directly in-app.
   * **Manual Fallback**: Always allows manual entry of carrier, tracking, and receipts.
8. **QR Code Security**: Magic Tokens. QR codes contain cryptographically signed tokens (`/api/unboxing?token=xxxx`) signed with the existing AES-Fernet encryption key containing the `package_id` and `heir_id`, with a short-lived expiration (e.g. 7 days or single-use validation tracked in the database) granting passwordless access to review memories and sign receipts.
9. **Heir disputes**: Structured disputes. Unchecking an item prompts the Heir to write a quick note and upload a photo of the damage, setting status to `DISPUTED`.
10. **Dispute Resolution**: Resolution Action Board. The Executor reviews disputes in a panel and resolves them via paths (e.g. `INSURANCE_CLAIM`, `CASH_ADJUSTMENT`, `OFFLINE_AGREEMENT`), logging the result to the audit ledger. For pre-shipment rejections, the Executor can resolve them by: (a) re-allocating the item via a cash offset, (b) marking it for disposal/donation and offset the Heir, or (c) manually resolving offline with a custom note.
11. **Scheduling Slots Config**: Custom App Schedule. The Executor sets recurring availability windows (e.g., *Saturdays 10 AM - 4 PM* or custom dates) directly in the console, keeping the app self-contained and free from third-party calendar OAuth requirements.
12. **Pre-Shipment Approvals**: Pre-Shipment Notification. If the Executor logs a condition override on packing day, the Heir is instantly notified to review the photo and accept the updated condition *before* shipment, heading off disputes.
13. **Unallocated Asset Logistics**: Estate Disposal & Liquidation Checklist. Unallocated items are placed in a 'Disposal Queue'. The AI suggests paths (estate sale, charity, recycling), and the Executor logs dates and uploads disposal receipts to prove clean estate winding-down to the probate court.
14. **Purge Safety Gates**: Block Purge with Active Handoffs & Disputes. The system disables the "Secure Session Purge" action until all allocated items are fully marked as `COMPLETED`, `RESOLVED`, or `UNCLAIMED_STORAGE`. Purging is blocked until all package disputes (including `LOST_IN_TRANSIT`) are resolved and their status transitions to `RESOLVED`, ensuring all physical logistics are fully resolved and recorded in the final archived ledger.
15. **Offline Payment Logs**: The AI Logistics Agent estimates shipping cost ranges. The Heir can log that they sent payment (e.g. via Venmo, check, or bank transfer), and the Executor confirms receipt in the Logistics Console before dispatching.
16. **Printable AI Pack-Out Slip**: Generates formatted, printable packing slips for each box, displaying estimated box dimensions, material guidelines (bubble wrap/padding), 3D packing order (heavy items first), and the item checklist.
17. **Event-Driven Alerts**: Automatically dispatches email/SMS notifications when handoff is set up, a damage override is logged (pre-shipment approval), payment is confirmed, or a pickup is scheduled/reminded. If messaging services are unconfigured or fail, the system quietly logs a warning, appends a copyable link/note to the dashboard, and does not crash the request flow.
18. **Dynamic Keepsake PDF updates**: Mutual swaps automatically trigger backend regeneration flags for the affected heirs' Keepsake Memory Books, ensuring updated allocations are reflected in their PDF downloads.
19. **Pre-Shipment Rejections**: If the Heir rejects a condition override, the item immediately transitions to `DISPUTED`, the containing package's shipment is paused by default, and the dispute is routed to the Resolution Action Board. The Executor has the option to split the disputed item out into its own package in the console, freeing the remaining undamaged items in the original package to be shipped immediately.
20. **Split Asset Handoff & Partial Dispute**: If a package arrives with both accepted and damaged/missing items, the undamaged items transition to `COMPLETED` immediately, and the flagged items transition to `DISPUTED` (spawning a `DisputeRecord`). The overall package status transitions to `DISPUTED` until all item disputes in it are resolved.
21. **Automatic Timezone Translation**: Available scheduling slots are stored in UTC. The Heir's portal automatically translates and displays these times converted to the Heir's local browser timezone, while clearly indicating the Executor's local timezone.
22. **AI Insurance Suggestions**: The AI automatically aggregates the appraised valuation range (valuation_min/max) of all items grouped in a specific package and prints a recommended 'Declared Value Insurance' amount on the logistics packing slip.
23. **Category Weight Heuristics**: The app maps asset categories (e.g. Glassware, Books, Jewelry) to default weight/fragility constants. The AI combines these to estimate package weight and dimensions, allowing the Executor to refine the numbers in the UI.
24. **Shipping Address Override**: Heirs can input a custom shipping address in their logistics dashboard. Doing so logs a `'SHIPPING_ADDRESS_OVERRIDE'` event in the audit trail, protecting the Executor from liability by proving the Heir authorized the destination.
25. **Configurable Booking Buffer**: Prevents last-minute schedule bookings. The Executor configures a minimum notice window (e.g., 24 or 48 hours). The AI Scheduling Assistant hides any availability slots falling within this buffer.
26. **Custom Slot Locations**: The Executor can assign a custom address to specific pickup slots (e.g., a storage locker or bank lobby). The address is displayed to the Heir during booking and printed on their receipt.
27. **AI Damage Audit Triage**: If an Heir submits a damage photo during unboxing, the AI compares it to the Executor's packing-day condition photo, providing a comparison summary (e.g., *"Confirmed mismatch - new structural crack detected"*) in the Executor's Resolution Board to support insurance claims.
28. **Dual Label Printing Support**: The app formats labels for standard 4x6 thermal printer layouts as well as standard Letter Avery 5164 sheets (six 3.33" x 4" labels per page), accommodating home and professional setups.
29. **Copy Link Fallback**: If email/SMS setups are not configured, the app displays a "Copy Link" option in the console, enabling manual sharing of magic links.
30. **Configurable Storage Provider**: Images are stored locally on the server filesystem by default (local self-hosting) but can seamlessly toggle to S3 or Cloudinary using environment variables for cloud hosting.
31. **Swap Locking Boundaries**: Heirs can initiate and approve trades/swaps as long as the package containing the assets is in `PENDING` status. Once the package transitions to `READY_FOR_PICKUP` or `SHIPPED`, those assets are locked and can no longer be swapped.
32. **Automatic Re-packing**: Committing a swap automatically triggers the AI to recalculate the box groupings, weight heuristics, and shipping cost estimates for both affected heirs, updating their logistics dashboards.
33. **Swap Damage Approval Reset**: If an item with a logged condition override is swapped to a new heir, the custom override notes remain attached to the asset, but the heir-approval flag is reset to `false`. The new Heir must review and accept the condition before it can be shipped.
34. **Voice-to-Text Condition Notes**: The Executor can click a microphone icon when packing an item to record a short voice description. The system transcribes it on-the-fly via the AI speech-to-text pipeline and logs it to the HandoffRecord's notes.
35. **Configurable Audio File Retention**: A global settings toggle allows the Executor to choose between deleting the raw audio file immediately after successful transcription (saving disk space) or permanently archiving the `.wav` file linked to the package records.
36. **In-Person QR Handoff Verification**: For in-person deliveries, the Heir displays a unique 'Receipt Verification QR Code' on their mobile phone, which the Executor scans with their phone camera to instantly verify the Heir's presence and close the handoff.
37. **Pre-Cached PIN & Paper Fallback**: If offline during a handover, the Heir's portal displays a 6-digit PIN (pre-cached when the Heir was online and generated on the server using a time-based TOTP secret specific to that package with a 5-minute time-step to tolerate time drift and a 10-minute validity window) which the Executor enters in-app (if the Executor's device is connected to the local server). If both Heir and Executor are offline, they fall back to the signed paper receipt photo upload.
38. **Multi-Package Relational Model**: The one-to-one HandoffRecord is replaced with a `Package` entity. The `Asset` table gets a nullable `package_id` foreign key. Heirs can receive multiple packages via different delivery methods, and each package has its own shipping/pickup details, status, and signature receipts.
39. **Individual Disposal Records**: Unallocated items are tracked individually in the `DisposalRecord` table, since disposal methods and dates vary item-by-item (e.g. donating one sofa vs. recycling a TV).
40. **Fiduciary Cash Payout Offset**: The Executor can record a cash value offset (e.g., a $250 offset for a broken antique vase) saved to the `DisputeRecord`. The final PDF ledger prints a distinct table showing all `DisputeRecord` entries, their resolution paths, and cash offsets, adding or subtracting them from the Heirs' net allocation valuations for court audit transparency, without performing actual bank transfers.
41. **Cron-Scheduled Reminders**: The system registers automated background timers. A scheduler task runs daily, sending follow-up email/SMS alerts to Heirs: (a) if their package has been ready for pickup for over 7 days without a booked slot, (b) 24 hours prior to the scheduled slot time, and (c) a final reminder 48 hours before the statutory pickup deadline. Automated reminders are limited to a maximum of 3 per package to prevent spamming.
42. **Mutually Notified Rescheduling**: The Executor can cancel a scheduled pickup slot in-app with a quick note. The system automatically notifies the Heir, frees the calendar availability slot, and resets the Heir's portal scheduling widget to select a new slot.
43. **Flat-Rate Box Mapping**: The AI Pack-Out Planner matches package dimensions and volume against standard carrier flat-rate dimensions (USPS Flat Rate: Small, Medium 1, Medium 2, Large; FedEx Express: S, M, L) and suggests them on the printable pack-out slip. These are kept as pre-defined constants in the code, and the Executor can also manually input custom dimensions for non-standard boxes.
44. **Address Lock on Dispatch**: The Heir's ability to edit their shipping address is locked automatically once a Package status changes to `SHIPPED` or `COMPLETED`.
45. **Shipping Exception Workflows**: The Executor can flag a shipped package as `RETURNED_TO_SENDER` (which resets the status to `PENDING` and unlocks the Heir's address editing fields) or `LOST_IN_TRANSIT` (which auto-spawns an insurance claim entry on the Dispute Resolution Board).
46. **Heir Rescheduling with Cutoff**: The Heir can reschedule or cancel a booked pickup slot in their dashboard up to the booking buffer deadline (e.g., 24 hours prior). Inside this window, the cancel/reschedule buttons are disabled, displaying a message instructing the Heir to contact the Executor directly.
47. **Consolidated Bookings**: When booking a pickup slot, the Heir can select which packages (one, some, or all of their pending local pickup items) they want to collect. The booked slot remains linked only to the selected packages, allowing the Heir to schedule separate slots for any remaining unbooked packages.
48. **Storage Retrieval Request**: If a package is marked `UNCLAIMED_STORAGE`, the Heir's portal shows its storage location and enables a "Request Retrieval" button. If the Heir requests retrieval, the Executor is notified in the console and must approve the request, resetting the package status to `PENDING` or `READY_FOR_PICKUP` to reschedule collection.
49. **AI Claim Packager**: If the Executor selects the `INSURANCE_CLAIM` resolution path on the Dispute Board, the AI Logistics Agent automatically compiles a complete audit package (original catalog image, packing-day audit image, Heir-uploaded damage photo, appraisal records, shipping/tracking history, and signed delivery receipt logs) into a single printable "Insurance Claim Evidence PDF" to submit directly to the carrier.
50. **Configurable Slot Duration Generator**: The Executor inputs a default slot duration (e.g. 30 minutes, 1 hour) and buffer gap. The app auto-populates slots in the setup console, allowing the Executor to customize, delete, or add specific times individually.
51. **Immutable Swap History**: Every swap request, trade, approval, or rejection is permanently recorded in the `AssetSwapRequest` table and printed on the final Probate Audit Ledger (Document B) to provide a transparent, legally admissible chain of custody.
52. **Fiduciary Disclaimers in UI**: The UI displays permanent fiduciary disclaimers (warning the Executor that digital receipts do not replace statutory court documents or courier carrier policies) as a prominent notice banner at the top of the Logistics Console (Executor view) and at the bottom of the unboxing and receipt-signing pages (Heir view).
53. **Disposal Receipt Storage**: Receipt images uploaded by the Executor for unallocated assets are stored in the configured storage provider (Local, GCS, or S3) via the abstract `StorageDriver` and their file paths/URIs saved in the `DisposalRecord.receipt_uri` column, supporting secure deletion and cleanups.
54. **Cancelled Pickup Slot Behavior**: If a pickup slot is cancelled by the Executor, the system dispatches email/SMS alerts to the Heir, releases the `PickupSlot` status (sets `is_booked` to false), deletes the relationship from the package, and resets the Heir's scheduling widget to allow re-booking.

---

## Detailed User Journeys

### Journey A: The Executor (Pack-Out & Shipping Phase)
1. **Launch**: Executor finalizes the session. The dashboard transitions to the *Logistics Launchpad*, showing consolidated counts (e.g., *"12 items to ship, 33 local pickup"*).
2. **Setup**: The Executor runs the **AI Pack-Out Planner**. The AI returns box groupings and a supplies shopping list (e.g., *"Need 4 medium boxes, 1 roll of bubble wrap"*).
3. **Packing & Visual Audit**:
   - The Executor packs Box #1 (represented as a `Package` entity in the database) for Heir *Sarah*. 
   - They click *"Pack Antique Vase"*, opening their camera.
   - They snap a photo. The AI compares it to the original catalog image. 
   - If a new scratch is found, it flags it. The Executor records a quick voice memo (*"Small hairline crack on base"*). The app transcribes it instantly to notes.
   - This triggers an instant **Pre-Shipment approval alert** to Sarah. She logs in, sees the photo, and approves the scratch.
   - The Executor prints a label. The label contains a **Keepsake QR Code** representing the Package ID.
4. **Dispatch**: The Executor ships the package and logs the tracking number, or uses an optional Shippo/EasyPost plugin to purchase postage in-app.
5. **Disposal**: For unallocated items, the Executor reviews the *Disposal Queue*, takes items to Goodwill, and uploads the donation receipt.

### Journey B: The Heir (The "Memory Unboxing" & Signing Phase)
1. **Scheduling**: Sarah receives an email/SMS link. Clicking it opens her dashboard. An AI chat assistant confirms her mailing address and asks her to book a local pickup date if needed.
2. **Delivery & Scan**: Sarah receives the package. On the side is the label: *"Scan to Open Your Keepsakes"*.
3. **The Magic Moment**: Sarah scans the QR code with her mobile phone:
   - A clean, mobile web page loads (secured by a single-use token).
   - It displays a video/photo carousel of the items in the box.
   - It plays the family's recorded voice memories and sentimental stories.
4. **Sign-Off & Dispute**: Below the memories, Sarah reviews the checklist of items in the package.
   - If an item is shattered, she unchecks it. 
   - The app prompts her for a description and a quick photo upload.
   - She signs for the rest of the package.
5. **Resolution**: The dispute appears on the Executor's *Resolution Action Board*. The Executor inputs the USPS insurance claim ID and marks the dispute as resolved, logging it to the ledger.

---

## Proposed Changes

### 1. Database Schema

#### [MODIFY] [models.py](file:///Users/amelton/Library/Mobile%20Documents/com~apple%20CloudDocs/estate_agent/backend/app/models.py)
* Add `sessions.statutory_pickup_days`: `Integer` (Default: 30)
* Add `sessions.booking_buffer_hours`: `Integer` (Default: 24)
* Add `sessions.retain_logistics_audio`: `Boolean` (Default: `false`, configuration for archiving voice notes)
* Modify `User` model:
  * Add `keepsake_regenerate_required`: `Boolean` (Default: `false`)
* Modify `Asset` model:
  * Add `package_id` column: `UUID` (Foreign Key -> `packages.id`, Nullable, ondelete="SET NULL")
* Create `PickupSlot` table:
  * `id`: `UUID` (Primary Key)
  * `session_id`: `UUID` (Foreign Key -> `sessions.id`, cascade delete)
  * `timestamp_utc`: `TIMESTAMP(timezone=True)`
  * `address_override`: `VARCHAR(255)` (Nullable)
  * `is_booked`: `BOOLEAN` (Default: `false`)
  * `created_at`: `TIMESTAMP(timezone=True)`
* Create `Package` table:
  * `id`: `UUID` (Primary Key)
  * `session_id`: `UUID` (Foreign Key -> `sessions.id`, cascade delete)
  * `heir_id`: `UUID` (Foreign Key -> `users.id`, cascade delete)
  * `handoff_status`: `VARCHAR(30)` (Check constraint: `PENDING`, `READY_FOR_PICKUP`, `SHIPPED`, `RETURNED_TO_SENDER`, `LOST_IN_TRANSIT`, `COMPLETED`, `DISPUTED`, `UNCLAIMED_STORAGE`)
  * `handoff_method`: `VARCHAR(30)` (Check constraint: `LOCAL_PICKUP`, `SHIPPING`, `EXECUTOR_DELIVERY`, `COMMERCIAL_STORAGE`, `DONATION_LIQUIDATION`)
  * `tracking_number`: `VARCHAR(100)` (Nullable)
  * `shipping_carrier`: `VARCHAR(50)` (Nullable)
  * `estimated_shipping_cost`: `FLOAT` (Nullable)
  * `heir_payment_logged`: `BOOLEAN` (Default: `false`)
  * `heir_payment_method`: `VARCHAR(50)` (Nullable)
  * `executor_payment_confirmed`: `BOOLEAN` (Default: `false`)
  * `actual_handoff_date`: `TIMESTAMP(timezone=True)` (Nullable)
  * `scheduled_pickup_slot_id`: `UUID` (Foreign Key -> `pickup_slots.id`, Nullable, ondelete="SET NULL")
  * `recipient_signature_name`: `VARCHAR(150)` (Nullable)
  * `recipient_signature_blob`: `TEXT` (Encrypted base64 signature stroke coordinates)
  * `photo_proof_uri`: `VARCHAR(255)` (Nullable)
  * `pre_shipping_condition_photo_uri`: `VARCHAR(255)` (Nullable)
  * `pre_shipping_condition_audio_uri`: `VARCHAR(255)` (Nullable)
  * `pre_shipping_audit_passed`: `BOOLEAN` (Default: `true`)
  * `pre_shipping_heir_accepted`: `BOOLEAN` (Default: `true`)
  * `offline_verification_seed`: `VARCHAR(64)` (Nullable)
  * `paper_fallback_recipient_name`: `VARCHAR(150)` (Nullable)
  * `paper_fallback_logged_at`: `TIMESTAMP(timezone=True)` (Nullable)
  * `notes`: `TEXT` (Nullable)
* Create `DisputeRecord` table:
  * `id`: `UUID` (Primary Key)
  * `package_id`: `UUID` (Foreign Key -> `packages.id`, cascade delete)
  * `heir_id`: `UUID` (Foreign Key)
  * `disputed_asset_id`: `UUID` (Foreign Key)
  * `issue_description`: `TEXT`
  * `damage_photo_uri`: `VARCHAR(255)` (Nullable)
  * `ai_triage_analysis`: `TEXT` (Nullable)
  * `resolution_path`: `VARCHAR(50)` (Nullable - e.g., `INSURANCE_CLAIM`, `CASH_ADJUSTMENT`, `OFFLINE_AGREEMENT`)
  * `resolution_notes`: `TEXT` (Nullable)
  * `resolution_receipt_uri`: `VARCHAR(255)` (Nullable)
  * `resolved_at`: `TIMESTAMP(timezone=True)` (Nullable)
  * `created_at`: `TIMESTAMP(timezone=True)`
* Create `AssetSwapRequest` table (for mutual consent swaps):
  * `id`: `UUID` (Primary Key)
  * `session_id`: `UUID` (Foreign Key)
  * `proposer_heir_id`: `UUID` (Foreign Key)
  * `receiver_heir_id`: `UUID` (Foreign Key)
  * `proposer_asset_id`: `UUID` (Foreign Key)
  * `receiver_asset_id`: `UUID` (Foreign Key)
  * `status`: `VARCHAR(20)` (Check constraint: `PENDING`, `APPROVED`, `REJECTED`)
  * `created_at`: `TIMESTAMP(timezone=True)`
* Create `DisposalRecord` table (for unallocated assets):
  * `id`: `UUID` (Primary Key)
  * `session_id`: `UUID` (Foreign Key)
  * `asset_id`: `UUID` (Foreign Key)
  * `disposal_method`: `VARCHAR(30)` (e.g., `DONATION`, `LIQUIDATION_SALE`, `RECYCLING`)
  * `disposal_date`: `DATE` (Nullable)
  * `disposal_recipient`: `VARCHAR(255)` (Nullable)
  * `cash_value_received`: `FLOAT` (Nullable)
  * `receipt_uri`: `VARCHAR(255)` (Nullable)
  * `notes`: `TEXT` (Nullable)
  * `created_at`: `TIMESTAMP(timezone=True)`

---

### 2. Backend API Endpoints

#### [MODIFY] [main.py](file:///Users/amelton/Library/Mobile%20Documents/com~apple%20CloudDocs/estate_agent/backend/app/main.py)
* **`GET /api/sessions/{session_id}/logistics`**: Returns allocated items, packaging groups, and handoff statuses grouped by Heir.
* **`POST /api/packages/create`**: Executor groups multiple assets into a new Package.
* **`POST /api/packages/{package_id}/handoff-setup`**: Sets carrier, tracking, or scheduled dates for the package.
* **`POST /api/packages/{package_id}/damage-audit`**: Uploads packing photo and runs visual condition comparison.
* **`POST /api/packages/{package_id}/pre-ship-approve`**: Heir accepts package condition before shipping.
* **`POST /api/packages/{package_id}/log-payment`**: Heir submits shipping payment confirmation.
* **`POST /api/packages/{package_id}/confirm-payment`**: Executor verifies receipt of shipping fee.
* **`POST /api/packages/{package_id}/receipt-sign`**: Commits signature, checkboxes, and delivery confirmation photo, shifting package status to `COMPLETED` or `DISPUTED`.
* **`POST /api/packages/{package_id}/verify-offline-pin`**: Validates a typed 6-digit offline handoff PIN using a TOTP algorithm.
* **`POST /api/packages/{package_id}/exception`**: Executor flags package as `RETURNED_TO_SENDER` or `LOST_IN_TRANSIT`.
* **`POST /api/packages/{package_id}/retrieval-request`**: Heir requests storage retrieval pickup.
* **`POST /api/packages/{package_id}/retrieval-approve`**: Executor approves storage retrieval, resetting status.
* **`POST /api/disputes/{dispute_id}/resolve`**: Executor submits resolution path and logs the `'DISPUTE_RESOLVED'` event.
* **`POST /api/swaps/initiate`**: Executor triggers a swap request.
* **`POST /api/swaps/{swap_id}/respond`**: Heir approves or rejects a swap request.
* **`POST /api/disposal/log`**: Executor registers a completed disposal record for an unallocated asset.
* **`GET /api/disputes/{dispute_id}/insurance-packet`**: Compiles and downloads the AI-generated Insurance Claim Evidence PDF.
* **`DELETE /api/heirs/me` (GDPR Erasure)**: Blocks erasure if the Heir has any active package in a state other than `COMPLETED`, `RESOLVED`, or `UNCLAIMED_STORAGE`. Once finalized, redacts names/emails/addresses from users, packages, and audit logs.

---

### 3. AI Logistics Engine

#### [NEW] [logistics_agent.py](file:///Users/amelton/Library/Mobile%20Documents/com~apple%20CloudDocs/estate_agent/backend/app/services/logistics_agent.py)
* **`generate_packout_plan(session_id)`**: AI analyzes allocations to calculate:
  * Consolidations: grouping small objects into single boxes.
  * Supply List: totals of small/medium/large boxes and packing tape.
  * Loading order for local vehicle pickups.
* **`audit_item_condition(catalog_image_bytes, handoff_image_bytes)`**: Computer vision comparison using LLMs to identify damage, tears, or scratches.
* **`run_scheduling_chat(heir_id, message_text)`**: Conversational flow inside the dashboard chat widget to confirm addresses and schedule pickup times.

---

### 4. Frontend UI Components

#### [NEW] [LogisticsConsole.jsx](file:///Users/amelton/Library/Mobile%20Documents/com~apple%20CloudDocs/estate_agent/frontend/src/components/LogisticsConsole.jsx)
* **Executor View**:
  * **Interactive Packing Checklist**: Shows photos of items, suggests box sizing, and displays packing checklists. Supports drag-and-drop to adjust items between boxes.
  * **Resolution Action Board**: Lists active disputes, allows uploading files/receipts, and selecting resolution pathways. Enables downloading the AI-compiled Insurance PDF.
  * **Disposal Board**: Shows a queue of unallocated assets, recommends local charities/liquidation channels, and logs disposal dates and receipts.
  * **Camera & Voice Capture Input**: Triggers physical device camera to capture "packing day" photos and records audio voice notes (which auto-transcribes and links).
  * **Print Packing Slips & QR Labels**: Formats printable sheets with address labels and keepsake QR codes.
  * **Swap Initiator**: Modal to choose two items/heirs and propose a swap.
  * **Offline PIN Verifier**: Small input modal to type the Heir's 6-digit PIN or upload a photo of the paper receipt.
* **Heir View**:
  * Dashboard chat helper to answer scheduling questions.
  * Interactive map/calendar scheduling page.
  * Stylus-friendly handwritten signature canvas widget for physical handoffs.
  * **Receipt QR & Offline PIN Display**: Generates the QR code for Executor scanning or the pre-cached 6-digit PIN fallback.
  * **Storage Card**: Shows storage address and enables 'Request Retrieval' action button.

---

### 5. PDF Ledger Reports

#### [MODIFY] [pdf_builder.py](file:///Users/amelton/Library/Mobile%20Documents/com~apple%20CloudDocs/estate_agent/backend/app/pdf_builder.py)
* Add a **"Physical Handoff Status & Delivery Log"** appendix to `build_probate_ledger_pdf` (which generates the Executor's Final Probate Audit Ledger, Document B). Displays the chronological progression of handoffs, matching signatures, and delivery status logs, allowing the printable PDF ledger to remain accurate and updateable post-finalization without breaking the sealed mathematical outcomes. This logistics log is explicitly excluded from the Heir's Keepsake Memory Book PDF to preserve its character as a personal, sentimental keepsake.

---

## Verification Plan

### Automated Tests
* Create `backend/app/tests/test_physical_logistics.py` to cover:
  1. Creating packages, assigning assets to packages, and testing state updates.
  2. Mocking the AI visual audit endpoint with matching vs. altered photos, verifying damage warnings and flags.
  3. Testing QR code unboxing endpoint and ensuring it properly retrieves sentiment tags and audio files.
  4. Initiating and completing an asset swap, verifying package updates and automatic re-packing calculation.
  5. Submitting a structured dispute with photo upload, checking the transition to `DISPUTED`, and executing a resolution route via the Action Board.
  6. Logging an unallocated asset disposal and attempting a secure database purge (verifying it is blocked until active handoffs/disposals are resolved).
  7. Offline PIN generation and API validation, confirming correct local matching without network reliance.
  8. Voiding packages, processing `RETURNED_TO_SENDER` resets (address unlock verification), and logging `LOST_IN_TRANSIT` claims.
  9. Submitting and approving a storage retrieval request.
  10. Generating the AI compiled insurance packet PDF.

* Run test suite:
  ```bash
  poetry run pytest backend/app/tests/test_physical_logistics.py
  ```

### Manual Verification
* Finalize a mock session.
* Load the **Logistics Console** and request packing recommendations. Verify the shipping checklist groups items.
* Upload a "damaged" picture of a plate to simulate packing day, and check that the AI detects structural/visual deviations and prompts the Executor to accept liability.
* Scan a generated QR code and verify it displays the media player for keepsake audio and sentimental notes.
