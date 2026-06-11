# The Estate Steward: Progress Log

## Current Task
**T48** — Session Announcement UI Components (next)

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
[NEXT] T48 — Session Announcement UI Components — Admin Announcement Console, Heir sticky Amber-500 alert banner, Heir login modal acknowledgment gate

## Blockers
None.