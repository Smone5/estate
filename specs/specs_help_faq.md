# Estate Steward: Help, FAQ, & Quick-Start Tutorial Specification (v1.0)

This specification defines the copy, layout, and content for the in-app **Help & FAQ Center** and onboarding tutorials. It is written in simple, empathetic, and clear language to assist grieving families and executors navigating the digital mediation space.

---

## 1. Heir FAQ (Frequently Asked Questions)

This content is rendered inside the Heir Help drawer (`/dashboard?help=true`) and in the printable Keepsake appendices.

### 1.1 How does the point allocation system work?
* **Answer**: You are given a pool of **1,000 points** to distribute across the active estate catalog. 
  * Points represent your personal preference and sentimental attachment to items.
  * You can assign all 1,000 points to a single highly desired keepsake (e.g., grandfather clock), spread them evenly across many small items, or leave items at 0 points if you do not want them.
  * Your total allocated points must equal **exactly 1,000** before you can submit.

### 1.2 Are my points visible to my family members?
* **Answer**: **No.** Individual point allocations are kept **strictly private** during the active mediation phase. This prevents tactical bidding, pressure, or conflict. Family members can only see progress checkmarks (indicating whether you have submitted), never your actual points.

### 1.3 Can I change my selections after adjusting the sliders?
* **Answer**: Yes. Your slider adjustments are automatically saved as **drafts** as you work. You can close your browser and return on any device without losing progress. However, once you click the final **"Submit Valuations"** button, your selections are locked and submitted to the division solver.

### 1.4 What is the AI Mediator and what does it do?
* **Answer**: The AI Mediator is a local, secure assistant designed to guide you through asset catalog details, answer questions about item histories, and provide a quiet space to discuss sentimental stories.
  * The Mediator is an automated AI assistant.
  * Your chat transcripts are **completely confidential** to you; they are blocked from the Executor and other heirs to ensure a safe space.
  * The Mediator has no authority to distribute items; its role is strictly supportive.

### 1.5 What is a "Grief Pause"?
* **Answer**: Mediation can be emotionally overwhelming. If you or another heir clicks the *"Request Help"* button and requests a break, the Executor can trigger a **Grief Pause**. This freezes all points sliders and chat inputs globally, allowing the family to take a step back, rest, and communicate offline. Pending invitation countdowns are automatically extended for the duration of the pause.

### 1.6 How does the system decide who gets what?
* **Answer**: Once everyone submits, the system runs a fair-division algorithm called **Maximum Nash Welfare (MNW)**. 
  * The math aims to maximize the collective happiness of the family.
  * Unlike auction systems where one person wins everything, MNW balances allocations so that every heir receives a fair, high-sentiment share based on their points, minimizing situations where someone receives nothing.
  * **Resolving Ties**: If two or more heirs allocate the exact same points to an item and the system needs to break a tie, the item is awarded to the heir who finalized and submitted their choices first. If both heirs submitted at the exact same time, the system resolves it alphabetically by their user identifier. This ensures a deterministic, completely impartial outcome with no executor favoritism.

### 1.7 Why do I need to verify my legal name, relationship, DOB, and upload an ID?
* **Answer**: Because this system compiles the **Final Probate Audit Ledger** and legal waivers (like the Abstention Waiver) to be formally filed with a probate court, the Executor has a fiduciary duty to confirm that allocations and waivers are executed by the actual, verified beneficiaries.
  * **The Verification Hold**: While your ID verification is pending or if a correction is requested, your dashboard is placed on a read-only **"Profile Hold"** state. During this time, you can browse assets but cannot adjust points sliders or use the mediator chat, preventing invalid entries from being signed on the ledger.
  * **Privacy Protections**: Your uploaded ID document is encrypted immediately with a local AES-256 key. It is temporarily stored on the local Raspberry Pi server and is **permanently deleted** (purged entirely from the filesystem) as soon as the Executor either approves or rejects your profile. The system is local-first, runs entirely offline, and never sends your ID to the cloud.

---

## 2. Executor (Admin) Quick-Start Tutorial

This tutorial is rendered as a step-by-step onboarding walkthrough when the Executor initializes the estate session.

```
[ Step 1: Secure Key Setup ] ---> [ Step 2: Stage & Snap Assets ] ---> [ Step 3: Specific Bequests ]
                                                                                   |
[ Step 5: Finalize & File  ] <--- [ Step 4: Launch Active Session ] <--- [ Step 3.5: Verify Heirs ]
```

### Step 1: Secure Key Setup & Offline Mnemonic
Upon creation of the Administrator account, the system generates a 24-word **Paper Recovery Key** (representing your encryption secret).
* **Action**: Write down these 24 words on physical paper and store them in a secure physical location (e.g., a home safe).
* **Warning**: Since the database is encrypted locally for privacy, if your Raspberry Pi experiences hardware failure, this paper key is the **only way** to restore and decrypt your backups.

### Step 2: Staging & Snapping Assets
To build the estate catalog:
1. Open the Admin Console on your phone or tablet and tap **"Capture Asset"**.
2. Snap a photo of the keepsake using your device camera.
3. The system will upload the image and automatically run a local AI visual scan (OCR) to pre-fill the item's Title, Description, and Category.
4. **Voice Story Dictation**: Tap the microphone icon next to the description box to speak and record the history of the item (e.g., *"Grandfather's silver watch from the railway service"*). The speech will transcribe directly into the text field.
5. **Admin Spoken Story Recording**: Use the voice recorder panel to record your actual voice talking about the keepsake. Heirs will be able to click and listen to your voice recording when reviewing the catalog.
6. Verify and edit details, input an appraisal valuation range and its **Valuation Source** (e.g., 'Professional Appraisal' or 'Tax Assessment'), and tap **"Publish Live"**.

### Step 3: Will Compliance & Pre-Allocated Assets
If the decedent’s Will explicitly bequeaths a specific keepsake to a specific beneficiary (a specific devise):
* **Action**: Locate the published asset, click **"Edit / Pre-Allocate"**, select the designated Heir, and save.
* **Result**: The asset status transitions to `'PRE_ALLOCATED'`. It is locked to that Heir and automatically excluded from the points allocation pool and Nash welfare math, ensuring strict compliance with the Will.

### Step 3.5: Heir Registration & Visual Identity Verification
To prepare heirs for points allocation and comply with probate court auditing rules:
1. Register each beneficiary on the dashboard with their email, phone, physical address, legal name, relationship to the decedent, and DOB.
2. The system generates unique, single-use invite links. Send these links to the heirs.
3. Upon first login, heirs will review their legal profile and upload a photo/scan of their government-issued ID. They are automatically placed in a read-only `'PROFILE_HOLD'` state.
4. **Action**: Open the Session Monitor Table on your Admin Dashboard, click **"Inspect ID"** next to any unverified Heir.
   * If details match, click **"Approve Identity"**. The Heir transitions to `'ACTIVE'`, and their temporary ID scan file is **permanently deleted** from disk.
   * If details do not match, click **"Reject & Flag"** and enter the correction reason. The uploaded ID scan file is **immediately purged** from disk storage, and the Heir is prompted via WebSocket to correct their details and upload a new scan.
5. **Result**: Verified heirs are fully authorized to participate (sliders and chat unlock). Unverified ID scan files are never retained in storage.

### Step 4: Launching the Active Mediation
Once your asset catalog is fully published and all heirs have been registered:
1. Tap **"Launch Session"** on your dashboard (requires at least one published live asset). This locks the catalog from further uploads/edits to prevent bidding on moving targets, and unlocks the points sliders and AI Mediator chat for all verified (`'ACTIVE'`) heirs.
2. **Note on invite links**: Invitation links were already generated and can be emailed during Step 3.5 when heirs were registered — heirs can accept their invitation and complete ID verification while the session is still in `'SETUP'` mode. You do **not** need to wait until launch to send invite links; sending them early lets heirs get verified before mediation begins, avoiding Profile Hold delays during the active session.
3. The heirs can now log in (if not already done), accept disclosures, chat with the AI Mediator, listen to your spoken stories, and allocate their 1,000 points.


### Step 5: Handling Deadlocks & Finalization
Once all heirs submit, or the notice period expires, review the session:
* **Automatic Tie-Breaking**: Standard point ties (where heirs put the same points on an asset) are resolved automatically by the solver based on submission order (earliest submitter wins) and alphabetical UUID fallback, requiring no Executor intervention.
* **Deadlock Alerts**: If two heirs put 1000 points on the same item, or if the solver results in an heir receiving 0 items (Zero-Utility Starvation), the system flags a **Deadlock**.
* **Resolution**: Use the **Force Allocation Console** to manually distribute the contested assets. You must input a fiduciary reason (e.g., *" decedent will instructions"* or *"mutual heir agreement"*) to justify the override in the audit log.
* **Cryptographic Sealing**: Click **"Finalize Session"**. The system runs the math, registers the final distributions, generates the Keepsake PDF books for the heirs, and outputs a cryptographically sealed **Final Probate Audit Ledger (PDF)**.
* **Court Filing**: Download the sealed ledger and file it physically or electronically with the local probate court to fulfill your fiduciary records obligations.

---

## 3. UI Placement & Triggers

To make these help resources easily accessible:

### 3.1 Heir FAQ Drawer
* **Access**: A small question mark icon `(?)` styled in Slate-600 is rendered in the global Heir Header bar.
* **Interaction**: Clicking it slides open a right-hand drawer listing the categorized FAQs in an accordion format (expanding/collapsing categories on tap).
* **Estate Specific FAQs**: A dedicated top-level category labeled **"Estate Specific Guidelines"** is dynamically populated from the database. It displays custom instructions and rules written by the Executor (e.g., shipping costs, pickup dates, house rules).

### 3.2 Admin Help Portal
* **Access**: A *"Quick-Start & FAQ Guide"* link is placed at the top of the Admin Console navigation sidebar.
* **Interaction**: Opens a full-screen modal showing a single, scrolling narrative tutorial:
  * **Section 1: Snap & Catalog Guide**: Directions for camera captures, visual OCR editing, and voice-transcribed stories.
  * **Section 2: Disaster Recovery & Backups**: Secure offline mnemonic keys instructions and recovery restoration console.
  * **Section 3: Probate & Fiduciary Compliance**: UPC legal rules, specific devise pre-allocations, and E-SIGN compliance.
  * **Section 4: System Diagnostics**: Local service status monitors (Ollama, Kokoro on CPU).
  * **Section 5: Estate FAQ Editor**: Manager interface to add, edit, or delete custom estate FAQ items (Question & Answer fields) which dynamically sync to Heir dashboards.
