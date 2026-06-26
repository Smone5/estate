# The Estate Steward: Master Specification Index (v4.1)

Welcome to the specification suite for **The Estate Steward**, an open-source, grief-informed estate mediation platform. 

To help human developers, AI code agents, and testing pipelines, the system specifications are modularized:

---

## 1. Modular Specifications

*   ### [Backend Specification](specs_backend.md)
    *   System Philosophy (Dual-Brain Architecture with Fast/Slow thinkers).
    *   Technology Stack (FastAPI, Postgres, pgvector, Ollama, LangGraph, Presidio).
    *   REST API Catalog (admin endpoints, support tickets, setup routes, WebSocket JSON framing protocols).
    *   Image Preprocessing & Normalization Pipeline (Pillow, pillow-heif, WebP scaling).
    *   Integrity and Security helper services (SMTP Async dispatch, Presidio PII scrubbing config).
    *   Docker-Compose deployment configuration.
    *   Keepsake PDF Document Design & Layout (ReportLab page templates, table formatting, and styling).

*   ### [Database Schema & Transaction Specification](specs_db.md)
    *   Entity-Relationship model and schemas (`users`, `assets`, `valuations`, `audit_logs`, `support_requests`).
    *   Database indexing strategies (pgvector HNSW cosine distance indexes).
    *   SQLAlchemy models, relationship structures, and transactional pessimistic read/write row locking (`with_for_update`).
    *   Transparent cryptographic JSON field decorations (AES-Fernet via cryptography package).

*   ### [LangGraph State Machine Specification](specs_langgraph.md)
    *   Shared `MediationState` context variables and schema types.
    *   LangGraph workflow diagram and operational node logic (`INGEST_PII`, `FAST_MEDIATE`, `SLOW_REFLECT`, `VALIDATE`, `COMMIT`, etc.).
    *   Speech recognition text ingestion interface.
    *   Manual session locks (Grief Locks) and mathematical deadlock interrupts using checkpointers and Human-in-the-Loop (`HITL_GUARD`) overrides.

*   ### [Frontend Technical Specification](specs_frontend.md)
    *   Codebase and directory architecture (Vite, React, custom hooks/stores).
    *   Client-side routing table definitions (`/invite/:token`, `/dashboard`, `/admin`).
    *   Zustand store hook schemas (active valuations, unallocated points calculations, offline message buffer queues).
    *   TanStack query caching and WebSocket reconnect lifecycle loops.
    *   Mobile Distribution Strategy: PWA install (Add to Home Screen) instead of Apple/Google marketplace submission, with native app wrapper noted as a future option.

*   ### [UI/UX Component & Layout Specification](specs_ui.md)
    *   Grief-Informed design tokens (hex variables), typography (Playfair Display / Inter), and 300ms transitions.
    *   Responsive layouts (mobile bottom navigation tabs vs desktop multi-pane split-screens).
    *   Visual cards (Warm Archival Index styling), categorization badges, and semantic search thresholds.
    *   Speech API voice capture interactions (touch hold vs mouse click-to-toggle) and HTML5 environmental rear camera upload.
    *   Heir and Admin UI state transition matrices, help modals, and CSS Print styles (`@media print`) for ledger printing.

*   ### [Compliance & Privacy Specification](specs_compliance.md)
    *   Relational database alignment (consent and age-gate columns, audit trail persistence).
    *   At-rest symmetric Fernet encryption and Microsoft Presidio PII scrubbing.
    *   FastAPI endpoints for consent verification, GDPR Right to Erasure, and Article 20 Data Portability.
    *   California BOT Act (SB 1001), synthetic voice metadata disclosures (SB 942), and training dataset transparency (AB 2013).

*   ### [Testing & Verification Specification](specs_testing.md)
    *   Backend unit tests (`pytest`) covering authentication, GDPR erasure, PII scrubbing, encryption, staging pipeline, ReportLab PDF generation, and fair division math.
    *   System and integration tests for LangGraph state machine tracing, WebSocket connections, and synthetic voice streaming.
    *   Frontend unit and integration tests for Zustand stores and UI rendering guards.

*   ### [User Acceptance Testing (UAT) Specification](specs_uat.md)
    *   Manual verification scenarios and step-by-step user journeys.
    *   Testing guidelines for consent mechanisms, PII scrubbing, voice-activated semantic search, grief pause controls, deadlock resolutions, and keepsake document prints.

*   ### [Legal Estate & Probate Compliance Specification](specs_legal.md)
    *   Fiduciary duty alignment guidelines (impartiality under Uniform Probate Code § 3-703, transparent record-keeping).
    *   Provisions for documenting non-participation, silent expirations, and active digital waivers.
    *   Evidentiary requirements for court-admissible final ledgers and audit hash chains.

*   ### [Help, FAQ, & Quick-Start Specification](specs_help_faq.md)
    *   Heir FAQ copy (points calculations, privacy rules, AI mediator privacy).
    *   Executor Quick-Start onboarding steps (mnemonic setup, mobile staging, manual/voice desc uploads, will devises).
    *   UI drawer placement triggers and accordion layout definitions.

---

## 2. Interactive Workflows

*   ### [User Journeys & State Workflows](user_journeys.md)
    *   Step-by-step description of the **Heir Journey** (authentication, detail exploration, mediation chat, points allocation, local Zustand locks).
    *   Step-by-step description of the **Admin Journey** (asset uploading/indexing, session monitoring, deadlock overrides, hash sealing, report generation).
    *   Interactive PDF keepsake generation and SMTP email deliverability triggers.

---

## 3. Project Blueprints & Plans

*   ### [Development Blueprint](../DEVELOPMENT_BLUEPRINT.md)
    *   Master technical architecture reference, system diagrams, and integration guide.
*   ### [Implementation Plan](../plan/implementation_plan.md)
    *   Step-by-step checklists for the infrastructure deployment, logic bridge, frontend creation, and security audit phase.
