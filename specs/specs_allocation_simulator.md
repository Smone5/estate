# Full Allocation Rehearsal — Product Specification

## 1. Product decision

The allocation simulation is not a math widget. It is a complete, fictional rehearsal of the heir experience from orientation through final result.

People may be grieving, distrustful of unfamiliar software, unfamiliar with fair-division systems, or anxious about making an irreversible choice. The rehearsal must let them build procedural memory before any real family property appears.

The simulator is a required first-session phase for newly created estates, while remaining explicitly separate from the real estate data:

- It uses only fictional people, stories, and objects.
- It never imports real inventory, heirs, drafts, or chat.
- Practice points are held in component memory and are discarded on restart or exit.
- Executor edits affect the fictional template, not any live mediation.
- The interface repeatedly labels itself as a simulation.
- Completion is recorded against the registered heir, but practice point values are never persisted.

## 2. Primary user journeys

### 2.1 First-time heir

1. Accepts the real estate invitation and signs into their registered heir account.
2. Sees practice as Step 1 while the real session remains in `SETUP`.
3. Arrives from the dashboard, sign-in education link, or FAQ.
4. Learns what the rehearsal includes and how long it takes.
5. Enters a photo-rich fictional household catalog.
6. Opens item details, reads descriptions, estimated values, and family stories.
7. Assigns exactly 1,000 private preference points across 5–10 items.
8. Reviews the complete point sheet and the lock-on-submit explanation.
9. Explicitly acknowledges the fictional submission.
10. Experiences a waiting room showing only participant completion status.
11. Runs the result after the fictional heirs are ready.
12. Reviews each participant’s items, received utility, Nash product, and any tie record.
13. Optionally reveals the fictional heirs’ point sheets for teaching.
14. Completion time is recorded for the registered heir; practice points are discarded.
15. Returns to the estate dashboard and waits for the Executor to launch the real allocation.

### 2.2 Returning or interrupted heir

- The step rail shows the current location.
- Completed steps can be revisited without losing in-memory work.
- Future steps remain locked until reached.
- A persistent restart control is available from every stage.
- Restart requires confirmation once work has begun.
- Browser refresh intentionally starts a clean rehearsal; the simulation does not masquerade as a saved real draft.

### 2.3 Heir who wants to understand a particular object

- Filters the fictional catalog by category.
- Opens a large photograph and full details.
- Sees the item’s story, value range, and current practice points.
- Can jump directly from the detail view to point allocation.

### 2.4 Heir who is unsure how to distribute points

- Reads that there is no correct strategy.
- Can concentrate or spread points.
- Uses “Fill a sample distribution” if they want a starting example.
- Adjusts range or exact numeric controls.
- Cannot exceed 1,000 or submit below 1,000.
- Learns that zero points is an intentional choice.

### 2.5 Heir anxious about privacy

- Sees a persistent “Simulation — no real estate data” indicator.
- Is told that real point sheets remain hidden during allocation.
- In the waiting room, sees only completion states.
- Fictional companion sheets are revealed only after the result and only as an educational disclosure.

### 2.6 Heir encountering a tie

- Receives a deterministic tie record.
- Sees the tied item, participants, point value, and selected participant.
- Learns that real sessions use recorded submission time and a stable fallback, not executor preference.

### 2.7 Heir who wants to restart

- Selects “Restart simulation” from the persistent bar.
- Confirms restart.
- Returns to orientation with zero points, no viewed markers, and no result.
- Can also restart immediately from the completed-result screen.

### 2.8 Executor configuring the rehearsal

1. Creates or opens the real mediation session.
2. Registers the heirs.
3. Opens the session’s “Practice Simulation” tab in the Executor Console.
4. Edits the fictional estate title and welcome message.
5. Enables or disables catalog objects while keeping 5–10 active.
6. Edits item title, category, description, story, value range, and catalog photograph.
7. Adjusts Jordan and Casey’s fictional private points.
8. Sees live totals and balances either fictional sheet to exactly 1,000.
9. Previews the rehearsal in a separate tab.
10. Publishes changes or restores the original fictional template.
11. Monitors each registered heir’s completion status.
12. Launches the real allocation only after all required heirs complete practice, or explicitly marks practice optional for an exception.

### 2.9 First-session launch gate

- New sessions default to `practice_required = true`.
- Existing sessions migrated into the feature remain optional to avoid blocking work already in progress.
- Publishing or changing the practice template clears prior completion timestamps for that session.
- The launch endpoint rejects a required session when the template is unpublished.
- The launch endpoint identifies registered, participating heirs who have not completed practice.
- The Executor may mark practice optional in the session-specific manager for an accessibility or timing exception.
- Once the real session is launched, the practice template is locked.

## 3. Default fictional estate

The default practice estate contains six coherent, photographed household objects:

1. Walnut Mantel Clock
2. Handwritten Recipe Box
3. 35mm Family Camera
4. Pearl Necklace
5. Oak Rocking Chair
6. Harbor Watercolor

Every object includes:

- Original fictional catalog photograph
- Category
- Plain-language description
- Fictional family story
- Estimated monetary range, clearly separate from preference points
- Editable fictional companion preferences

## 4. Experience architecture

### Stage 0 — Orientation

Job: reduce uncertainty and set boundaries.

Required content:

- Complete-process promise
- 8–12 minute estimate
- No real data and nothing submitted
- Five-stage journey preview
- Fictional estate title and item count

### Stage 1 — Catalog exploration

Job: reproduce the real discovery behavior.

Requirements:

- Responsive three-column photo catalog
- Category filters
- Viewed state
- Large detail dialog
- Story and value range
- Zero-point education

### Stage 2 — Private allocation

Job: let the user experience the cognitive work of tradeoffs.

Requirements:

- 1,000-point remaining meter
- Range and exact numeric controls
- No total above 1,000
- Exact total required to continue
- Sample distribution helper
- Point privacy explanation

### Stage 3 — Review and submit

Job: rehearse the irreversible moment without creating real consequences.

Requirements:

- Ranked full point sheet
- Clear lock-on-submit explanation
- Four-rule summary
- Explicit rehearsal acknowledgement
- Back path for changes

### Stage 4 — Waiting room

Job: teach what users see while others finish.

Requirements:

- Submitted status for the user and two fictional heirs
- No companion point values
- Explanation that only completion state is shared
- Explicit action to run the completed practice allocation

### Stage 5 — Result and audit explanation

Job: replace mystery with inspectable reasoning.

Requirements:

- Items grouped by recipient
- Each recipient’s personal utility
- Number of complete distributions considered
- Nash product equation
- Explanation of why isolated highest bids are insufficient
- Expandable fictional companion point sheets
- Deterministic tie record when applicable
- Privacy, balance, and audit summary
- Restart and sign-in actions
- Registered-heir completion receipt and return-to-dashboard action

### Real-experience parity

The rehearsal intentionally mirrors the live interface:

- The same warm archival visual language, image ratios, typography, and action hierarchy.
- Catalog cards open the same kind of item-detail narrative.
- The allocation stage uses the same 1,000-point remaining model, range controls, exact values, and disabled-submit gate.
- The review stage uses the same ranked preference language and locked-submission warning.
- The waiting stage exposes completion status but not other heirs’ points.
- The result uses the same allocation vocabulary, deterministic tie disclosure, and advisory/auditable framing.

The rehearsal remains visually labeled so it cannot be mistaken for the real estate.

## 5. Simulation model

The default rehearsal uses three participants and six items.

Registered heirs run the fictional matrix through the same backend `solve_mnw` function used by real-session finalization. This preserves production allocation and deterministic tie behavior while keeping the data entirely separate from live assets and valuations.

The education explains the conceptual Maximum Nash Welfare comparison:

1. Sum each participant’s preference points for the items assigned to them.
2. Multiply the three participant utilities.
3. Select the assignment with the largest product.
4. Apply the production deterministic tie ordering.
5. Record any tie event returned by the production engine.

The registered-heir endpoint accepts the fictional 1,000-point sheet in memory, combines it with the configured Jordan/Casey sheets, returns the solver result, and does not persist the request. No-account guests retain a client-side exhaustive teaching fallback; it evaluates `3^n` assignments because no authenticated session solver is available.

The education surface explains four concepts before point entry:

1. Private preference sheets.
2. Enumeration of complete distributions.
3. Personal utility as the points attached to received items.
4. The Nash product’s penalty for leaving one participant with very little.

An expandable explanation covers isolated high scores, deterministic ties, and human-review deadlocks.

## 6. Executor configuration and persistence

Configuration is stored per session in the existing encrypted `app_settings` table under the reserved key prefix `__SESSION_SIM_CONFIG__:{session_id}`. It is not mirrored into environment variables and is not exposed through general settings APIs.

Session and heir workflow fields:

- `sessions.practice_required`
- `sessions.simulation_published_at`
- `users.practice_completed_at`

Public endpoint:

- `GET /api/simulation/config`
- Returns only fictional, PII-free content.
- Falls back to the built-in default when no override exists.

Admin endpoints:

- `GET /api/sessions/{session_id}/simulation/status`
- `PUT /api/sessions/{session_id}/simulation/config`
- `POST /api/sessions/{session_id}/simulation/reset`
- Require authenticated executor access.
- Enforce 5–10 enabled items.
- Enforce unique item IDs.
- Enforce exactly 1,000 points for each fictional companion.
- Restrict images to bundled `/simulation/*.webp` assets.
- Reset registered-heir completion after a changed template is published.

Registered-heir endpoints:

- `GET /api/heirs/me/simulation`
- `POST /api/heirs/me/simulation/solve`
- `POST /api/heirs/me/simulation/complete`
- Return only the session’s fictional template and completion metadata.
- Accept fictional points only for the in-memory solver request; never persist them.

## 7. Trust and content rules

Required language:

- “Simulation — no real estate data”
- “Points express relative importance—not price.”
- “Your fictional family members cannot see these choices while allocation is open.”
- “A high point value does not guarantee a particular item.”
- “Unresolvable conflicts pause for documented human review.”

Prohibited language:

- Winner, loser, bid price, purchase
- Guaranteed fair
- Court-approved
- Claims that the rehearsal predicts the real result

## 8. Accessibility and responsive behavior

- Step rail uses `aria-current="step"`.
- Catalog items and filters are keyboard-operable buttons.
- Detail view uses dialog semantics and visible close control.
- Every range and numeric point input has a unique accessible name.
- Progress is represented with text, not color alone.
- Mobile catalog collapses to one column.
- Allocation rows preserve exact numeric entry on small screens.
- Reduced-motion preferences disable transitions.

## 9. Success measures

Recommended product analytics, if privacy-preserving local analytics are later approved:

- Rehearsal completion rate
- Restart rate by stage
- Time spent in catalog and allocation stages
- Use of sample distribution helper
- FAQ opens after rehearsal
- Self-reported confidence before and after

Do not collect point distributions or item-level preferences as analytics.

## 10. Acceptance criteria

- A user can complete orientation, catalog, allocation, review, waiting, and result without authentication.
- The default catalog contains six original photographs and complete details.
- Point allocation cannot exceed or submit below 1,000.
- The result assigns every active fictional object exactly once.
- Three participant utilities and their Nash product are correct.
- The user can restart from every stage.
- The executor can edit and publish the fictional template.
- The Executor can see completion for each registered heir without seeing practice points.
- New sessions cannot launch while required practice is unpublished or incomplete.
- A registered heir completing the result receives a persisted completion timestamp.
- Server validation rejects fewer than 5 or more than 10 enabled objects.
- Server validation rejects fictional companion totals other than 1,000.
- Real estate session data is never read or written.
