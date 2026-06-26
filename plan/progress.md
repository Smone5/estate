# The Estate Steward: Progress Log

## Current Task
Phase 7: System Backup, Compliance & E2E Validation — T30 E2E Compliance Validation complete

## Completed Tasks
| Task ID | Description | Status |
|---------|-------------|--------|
| T01 | DB Docker Setup & Startup Retry Loop | [x] |
| T02 | SQLAlchemy Models & Relations | [x] |
| T03 | AES-Fernet Encryption Decorator | [x] |
| T04 | Alembic Migrations & pgvector Indexing | [x] |
| T38 | WebSocket Connection Manager | [x] |
| T28a-1 | Backend Tests — Phase 1 Scope | [x] |
| T05 | Microsoft Presidio PII Scrubbing | [x] |
| T06a | Ollama Model Downloads | [x] |
| T06b | Ollama Configuration & Integration | [x] |
| T21a | Kokoro ONNX Model Download | [x] |
| T21 | Kokoro-82M TTS & soundfile WAV Encoder | [x] |
| T50 | LLM Provider Abstraction Layer & Ollama Health-Check | [x] |
| T07a | LangGraph State Schema, Nodes & Prompt Templates | [x] |
| T08 | LangGraph PostgresSaver Integration | [x] |
| T73 | Rate Limiting Middleware | [x] |
| T63 | Pi 5 Model Downscaling & Memory Profiling | [x] |
| T07b | LangGraph Model-Specific Tuning & Concurrency Config | [x] |
| T28a-2 | Backend Tests — Phase 2 Scope | [x] |
| T09a | Storage Driver Interface & Mock Driver | [x] |
| T09b | Image Preprocessing Pipeline & Concrete Storage Drivers | [x] |
| T10 | FastAPI Core & Onboarding endpoints | [x] |
| T37 | FastAPI Session Lifecycle & Announcement API | [x] |
| T11 | FastAPI Asset Router | [x] |
| T81 | SMTP Service & Retry Infrastructure | [x] |
| T13 | FastAPI Heir Management & Invitations | [x] |
| T31 | Government ID Scan Upload API | [x] |

[DONE] T31 — Government ID Scan Upload API — 2026-06-11T01:52
[DONE] T39 — Admin Setup & Session Creation API with BIP39 recovery key — 2026-06-11T07:57
[DONE] T40 — Asset Deletion API with file cleanup and session-status gate — 2026-06-11T08:00
[DONE] T41 — Admin Audio Story Upload & Delete API — 2026-06-11T08:02
[DONE] T42 — Support Request & Help CRUD API with WebSocket alerts — 2026-06-11T08:06
[DONE] T43 — Custom FAQ CRUD API with WebSocket mutation broadcasts — 2026-06-11T08:08
[DONE] T64 — Asset Pre-Allocation API with orphaned valuation cleanup — 2026-06-11T08:10
[DONE] T65 — Background Invite Expiration Scheduler — 2026-06-11T08:11
[DONE] T34 — Executor ID Verification State Transition API — 2026-06-11T08:13
[DONE] T60 — Admin Heir Deletion API — purge PII, delete scan, unlink pre-allocated assets — 2026-06-11T08:24
[DONE] T28a-3 — Backend Tests — Phase 3 Scope (426 tests pass, gates Phase 4) — 2026-06-11T08:27
[DONE] T12 — FastAPI Valuation Router with pessimistic locking, draft version control, HITL_GUARD gate — 2026-06-11T08:31
[DONE] T71 — Proof of Notice Log Data Contract — NoticeLog/NoticeLogEntry/build_notice_log — 2026-06-11T08:34
[DONE] T15 — Fairpyx MNW Solver & Tie-Breakers with iterative maximum matching, deterministic tie-breaking — 2026-06-11T08:41
[DONE] T14 — ReportLab PDF Builders — Keepsake & Probate Ledger with NumberedCanvas, legal disclaimer, dynamic columns, 27 tests — 2026-06-11T08:53
[DONE] T70 — Tie-Breaker Resolution Record in PDF — structured TieBreakerEvent data contract, deterministic resolution table in probate ledger PDF — 2026-06-11T08:57
[DONE] T16 — FastAPI Keepsake & Finalization Router — finalize endpoint, solver execution, status transitions, hash chain sealing, PDF download routes — 2026-06-11T09:02
[DONE] T33 — Active Abstention Waiver PDF Receipt & Email — abstain endpoint, SMTP receipt, fallback support ticket, ReportLab PDF receipt — 2026-06-11T09:08
[DONE] T44 — Session Override API — HITL endpoint, ADMIN_OVERRIDE audit log, corrected allocations in checkpointer, adjusted heir points budgets — 2026-06-11T09:22
[DONE] T55 — FastAPI Heir GDPR Erasure Router — DELETE /api/heirs/me, soft anonymization, chat/checkpointer cleanup, audit PII sanitization — 2026-06-11T09:26
[DONE] T57 — FastAPI GDPR Data Portability API — flattened to Compliance Spec §2.2 schema, 3 tests passing — 2026-06-11T09:41
[DONE] T82 — Hash Chain Verification Tool — GET /api/system/verify-hash-chain, re-computation, break detection, 4 tests — 2026-06-11T09:45
[DONE] T83 — Mediation Chat History API — GET /api/sessions/{session_id}/heirs/{heir_id}/chat, admin-blocked — 2026-06-11T09:46
[DONE] T26 — System Backup & Restore — pg_dump, Fernet-encrypted .estate.bak, BIP39 recovery restore — 2026-06-11T09:49
[DONE] T49 — Secure Session Purge — DELETE /api/sessions/{session_id}?confirm=true, 6-step permanent deletion — 2026-06-11T09:49
[DONE] T17 — Frontend Vite Base & Vanilla CSS — Archival index card design system, @media print, React Router shell, API proxy — 2026-06-11T10:02
[DONE] T18 — Zustand store & cache keys — useMediationStore, points math, debounced draft saving, TanStack Query cache key constants — 2026-06-11T10:04
[DONE] T19 — Client Routing & Onboarding views — legal profile confirmation checkbox, executor ack gate, E-SIGN, consent cards — 2026-06-11T10:13
[DONE] T20 — Heir & Admin Dashboard View Guards — DashboardGuard component, SB 1001 banners, Sum Validation Hold, LegalFooter — 2026-06-11T10:15
[DONE] T73_UI — Legal Disclaimer Footer — LegalFooter component hiding on public paths, visible on dashboard/admin — 2026-06-11T10:15
[DONE] T32 — Government ID Scanner & File Drop UI — HTML5 camera, card-shaped overlay, drag-and-drop, 10MB limit — 2026-06-11T10:17
[DONE] T46 — Semantic Search UI — gallery search bar, filter panel, sorting controls, confidence badge, zero-match fallback — 2026-06-11T14:27
[DONE] T35 — Executor Force Allocation Console UI — view deadlocked items, select beneficiaries, override reasons, POST override — 2026-06-11T14:38
[DONE] T47 — FAQ/Help UI Components — Heir FAQ drawer, Admin Help Portal, scroll tutorial, inline FAQ editor — 2026-06-11T14:43
[DONE] T48 — Session Announcement UI Components — Admin Announcement Console, Heir sticky Amber-500 alert banner, Heir login modal acknowledgment gate — 2026-06-11T15:03
[DONE] T51 — Active Abstention Waiver UI Components — Heir active abstention button, signature verification modal, post-abstention wait screen, expired token gate — 2026-06-11T15:09
[DONE] T52 — Admin Inventory Dashboard UI — staging card, metadata edit form, pre-allocation dropdowns, publish buttons, legal scope notice, 14 tests — 2026-06-11T15:26
[DONE] T27 — BIP39 Mnemonic Onboarding Screen — 24-word grid, warning banner, confirmation checkbox gate, 10 tests — 2026-06-11T15:32
[DONE] T53 — Admin Session Control UI — heir registration, monitor table with checkmarks, invite management, pause/unpause, finalize, 16 tests — 2026-06-11T15:30
[DONE] T54 — Admin Onboarding & Credentials Setup UI — AdminSetupWizard wraps BIP39 screen, POST /api/setup/admin, first-boot gate, 8 tests — 2026-06-11T15:33
[DONE] T56 — BIP39 Mnemonic Restore Panel — backup download, .estate.bak upload with recovery key, word-count validation, 10 tests — 2026-06-11T15:36
[DONE] T58 — GDPR Data Portability UI Button — Export My Data (JSON) button in heir settings drawer, authenticated download, 4 tests — 2026-06-11T15:38
[DONE] T59 — GDPR Account Deletion UI Drawer — slide-out warning with GDPR Art 17, case-sensitive username confirmation, soft anonymization trigger, 8 tests — 2026-06-11T15:39
[DONE] T66 — Family Memories & Stories UI — collapsible shared stories section, edit locked on pause/submit, no reply controls, 8 tests — 2026-06-11T15:41
[DONE] T67 — Admin Inspect ID Modal — split-pane verification, side-by-side legal details, approve with reason/reject, 11 tests — 2026-06-11T15:43
[DONE] T68 — Heir Request Help Modal — slide-up modal, char counter (5–1000), POST help endpoint, confirmation, 6 tests — 2026-06-11T15:44
[DONE] T69 — Auto-Balance Points Button UI — store proportional scaling to 1000, division-by-zero guard, rounding remainder, 6 tests — 2026-06-11T15:45
[DONE] T28b — Backend Tests — Phases 4–5 Scope — 480 tests pass covering solver, PDF, finalization, GDPR erasure/portability, abstention waiver, tie-breaker records, notice log — 2026-06-11T15:47
[DONE] T29 — Frontend Unit & Integration Tests — 151 tests pass (18 test files), all UI components verified — 2026-06-11T12:55
[DONE] T72 — Unauthenticated System Restore Gate — JWT cookie auth on initialized restore, fresh-system bypass preserved, 480 tests pass — 2026-06-11T12:12
[DONE] T61 — Nginx & Production Build Setup — npm run build verified, dist/ populated, nginx static serve configured — 2026-06-11T12:13
[DONE] T74 — Cloudflare Tunnel Service — cloudflared container with profile activation, CLOUDFLARE_TUNNEL_TOKEN, outbound-only tunnel — 2026-06-11T12:15
[DONE] T75 — Host Hardening Script — SSH key-only auth, unattended-upgrades, UFW firewall, dry-run mode — 2026-06-11T12:16
[DONE] T36 — AB 2013 Model Transparency API & Modal — dynamic env var model names, ModelTransparencyModal component, AdminHelpPortal & FAQDrawer trigger links, 9 backend + 10 frontend tests — 2026-06-11T12:44
[DONE] T22 — WebSocket Server Endpoint — JWT cookie auth, HITL_GUARD gate, text-only chat_reply_chunk frames, SB 942 synthetic indicators — 2026-06-11T12:54
[DONE] T23 — WebSocket Client Connection Loop — useWebSocket hook, exponential backoff reconnect, offline queue flush on reconnect — 2026-06-11T12:55
[DONE] T24 — Web Speech Client Hook — useSpeech hook, hold/toggle, HTTPS guard, InvalidStateError handler, AudioContext 'Enable Audio' button — 2026-06-11T12:55
[DONE] T25 — Client Audio Playback Queue — useAudioPlayback hook, sequential playlist, base64 Blob decoder, Blob URL revocation, SB 942 synthetic label, null-audio guard — 2026-06-11T12:55
[DONE] T45 — Admin Voice Recorder Widget — MediaRecorder record/stop/playback/redo, pulsing timer 2:00 max, HTTPS guard, POST audio upload on save, Sage-Green aesthetics — 2026-06-11T12:55
[DONE] T28c — Backend Tests — Phase 6–7 Scope — 527 tests pass — 2026-06-11T16:16
[DONE] T30 — E2E Compliance Validation — GDPR export, CCPA/AB 2013 model listings, SB 942 websocket/audio queue propagation, hash-chain verification; 531 backend + 153 frontend tests pass — 2026-06-11T16:26
[DONE] T76 — Multi-Session Heir Login Disambiguation — Missed requirement: the same email/username can belong to Heir records in multiple estate sessions (e.g. a heir to two different decedents). `POST /api/auth/heir-login` previously resolved this with an unscoped `.first()` query, silently logging the heir into an arbitrary session. Fixed by verifying the password against every matching candidate and returning a `multiple_sessions` picker payload when more than one verifies; `heirPasswordLogin` store action and the `/login` page now support the disambiguation round-trip via `session_id`. Specs updated: specs_backend.md §9.5, specs_frontend.md §2.2/§3, user_journeys.md §1 Step 1 — 2026-06-26
[DONE] T77 — Switch Estate In-Dashboard Picker — Missed requirement: once logged into one estate, a heir onboarded into 2+ sessions had no way to reach the other estate(s) without logging out and re-entering credentials. Added `GET /api/auth/heir-sessions` (lists sibling sessions sharing the heir's email/username) and `POST /api/auth/heir-switch-session` (re-issues the JWT cookie scoped to a sibling session without a password prompt). New `SwitchEstateModal.jsx` component plus `loadHeirSessions`/`switchHeirSession` store actions; "Switch Estate" button added to the dashboard header, visible to heirs only. Specs updated: specs_backend.md §9.5, specs_frontend.md §2.3/§3, user_journeys.md §1 Step 1 point 4 — 2026-06-26

[DONE] T86 — PWA Mobile Distribution Packaging — Missed requirement: neither role should need Apple App Store or Google Play submission to use the app on a phone. Implemented via `vite-plugin-pwa` (manifest.webmanifest + Workbox service worker generated on every `npm run build`, `/api`/`/ws` excluded from caching), `apple-touch-icon`/`theme-color` tags in index.html, and rendered icon-192/512.png assets. Installs via "Add to Home Screen" on iOS Safari/Android Chrome, reusing the existing Cloudflare Tunnel/Nginx origin. Native app wrapper (Capacitor) remains a noted future option only. Build verified: `dist/manifest.webmanifest`, `dist/sw.js` generated correctly. (Re-numbered from the earlier T78 placeholder — T78 was already in use for the OpenAPI Contract Specification task.) Specs updated: specs_frontend.md §7.1, specs.md index — 2026-06-26
[DONE] T87 — `scripts/install_on_phone.sh` One-Command Phone Install — Builds frontend, starts Docker stack, and prints a tappable link + scannable QR code so installing the PWA on a phone needs no manual URL typing. Renders the QR as a real PNG and opens it via macOS `open` rather than terminal ASCII art — ASCII QR codes proved unscannable by phone cameras due to font anti-aliasing distorting the module grid; PNG fixes this. Uses `PUBLIC_BASE_URL`/`CLOUDFLARE_TUNNEL_TOKEN` from `.env` for the real HTTPS path when configured, else auto-detects the host's LAN IP (scans en0–en3, then all interfaces for a private-range address) for same-Wi-Fi HTTP testing. `.qr-install.png` added to .gitignore. Specs updated: specs_frontend.md §7.2. Plan updated: implementation_plan.md T86/T87 entries — 2026-06-26

## Blockers
None.
