# The Estate Steward: Progress Log

## Current Task
**T60** — Admin Heir Deletion API (next)

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
[NEXT] T71 — Proof of Notice Log Data Contract — formalize notice_log data structure consumed by PDF builders

## Blockers
None.