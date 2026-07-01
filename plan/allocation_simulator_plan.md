# Full Allocation Rehearsal — Implementation Plan

## Delivered foundation

### Product and content

- Expanded the feature from a three-item math demonstration into a complete six-stage rehearsal.
- Documented first-time, returning, privacy-anxious, tie, restart, and executor-management journeys.
- Added clear separation between fictional practice and real mediation.

### Fictional catalog

- Generated six original, coherent estate-catalog photographs.
- Optimized project assets to 960px WebP.
- Added description, story, category, estimated range, and companion preferences for every item.

### Heir rehearsal

- Orientation with journey preview.
- Photo catalog with categories, viewed state, and detail dialog.
- Full 1,000-point allocation workspace.
- Ranked review and explicit practice submission acknowledgement.
- Waiting room that exposes progress but not preferences.
- Three-person exhaustive Maximum Nash Welfare teaching result.
- Companion preference reveal, Nash proof, tie record, and learning summary.
- Persistent restart and step navigation.

### Executor management

- Added “Practice Simulation” to the Executor Console.
- Added editable title, welcome content, item metadata, photograph selection, enable state, and fictional companion points.
- Added live validation and companion-point balancing.
- Added publish, preview, and restore-default controls.
- Scoped every template to a selected real mediation session.
- Added registered-heir completion monitoring and a required/optional launch policy.

### Backend

- Added public fictional configuration read endpoint.
- Added authenticated executor update/reset endpoints.
- Reused encrypted `app_settings` persistence with an internal reserved key.
- Added 5–10 item, unique ID, image-path, and 1,000-point validation.
- Added `practice_required`, `simulation_published_at`, and `practice_completed_at` workflow fields.
- Added registered-heir context/completion endpoints and a real-session launch gate.
- Kept migrated existing sessions optional while making newly created sessions require practice by default.

## Verification plan

1. Backend unit tests
   - Default public configuration.
   - Admin authentication.
   - Valid update round trip.
   - 4-item and 11-item rejection.
   - Companion total rejection.
   - Reset to defaults.
2. Frontend unit tests
   - Generic three-person allocation exhaustiveness.
   - Catalog-to-allocation navigation.
   - Exact 1,000-point gate.
   - Review acknowledgement gate.
   - Waiting-to-result transition.
   - Restart confirmation.
   - Admin count and companion-total validation.
   - Registered-heir completion receipt.
   - Executor registered-heir progress list.
3. Build and visual QA
   - Production build.
   - Desktop catalog/detail/allocation/result.
   - 390px mobile catalog and allocation controls.
   - Console errors and broken image checks.
4. Product UAT
   - First-time heir completes without coaching.
   - Heir can explain why highest isolated points are not the whole rule.
   - Heir can identify what remains private.
   - Executor can change a story and see it in a new rehearsal.
   - Launch is blocked until every required registered heir completes practice.
   - The real allocation opens after practice without carrying over fictional points.

## Follow-on work

- Optional spoken fictional stories using bundled audio.
- Confidence check before and after rehearsal.
- Local-only completion receipt shown on the real dashboard.
- Executor-selectable teaching scenarios for ties and deadlocks.
- Translated practice templates.
- Usability testing with people who have never participated in estate allocation.
