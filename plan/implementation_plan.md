# The Estate Steward: Master Development Implementation Plan Index

## Step 0: Prerequisite — uv Virtual Environment Setup
Before any development begins, the backend Python environment must be initialized using `uv` (the project's Python package manager):

```bash
# Navigate to the backend directory
cd backend

# Create a uv virtual environment and install all dependencies
uv sync

# Activate the virtual environment
source .venv/bin/activate
```

This must be done before running any backend tests, starting the FastAPI server, or executing any Python scripts. The `uv sync` command reads `backend/pyproject.toml` and installs all declared dependencies (FastAPI, SQLAlchemy, LangGraph, Presidio, Kokoro-ONNX, etc.) into an isolated `.venv` directory.

## Step 1: Logical Reasoning (Chain of Thought)
Analyzing the critical path for the Estate Steward platform reveals that the core database tables, schema relations, and pessimistic concurrency controls represent the primary engineering dependencies. Without the database schema, unique composite indexing, and the custom AES-Fernet encryption decorators (`EncryptedJSON`), subsequent backend systems cannot store user profiles, assets, valuations, or audit log snapshots. The highest-risk technical bottleneck is the LangGraph dual-brain workflow state machine coupled with Microsoft Presidio PII scrubbing and Kokoro-82M ONNX speech synthesis. Since Presidio determines what is scrubbed from the state history, and Kokoro processes audio chunks for real-time WebSocket communication, these systems must be engineered and validated before the client-side React views, global Zustand stores, and Web Speech API hooks are implemented. Consequently, the project sequence begins with the schema and security foundations, proceeds through state machine routing, builds the REST API, integrates the math solvers, and finishes with the frontend layouts, real-time voice streaming queue, and GDPR-compliant erasure scripts.

## Step 2: Phase Breakdown

This implementation plan is split into seven distinct development phases. Each phase is detailed in its own specification index file:

1. **[Phase 1: Database & Core Security Foundation](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/plan/phase_1_database_security.md)**
   * **Phase Objective**: Define the relational schema, composite unique constraints, startup connection pool retries, and symmetric field-level encryption. Write incremental unit tests for these foundations.
   * **Deliverables**: Relational models, connection retry loops, pgvector migrations, Fernet text decorators, and incremental test suite.
   * **Note**: A 1 to 2 business day schedule buffer is explicitly injected between Phase 1 and Phase 2 to verify pgvector compilation on target ARM64 architecture and Docker volume permission bindings on Linux. T28a-1 (Phase 1 partial test gate) runs at end of Phase 1.
2. **[Phase 2: Local AI Compute & LangGraph Orchestration](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/plan/phase_2_ai_orchestration.md)**
    * **Phase Objective**: Build the dual-brain LangGraph state machine, Ollama system integrations, Microsoft Presidio PII redaction pipeline, infrastructure services (Langfuse container setup, rate limiting), and the local Kokoro ONNX speech synthesis engine. Write incremental tests for these nodes. Note: A 3 to 5 business day schedule buffer is explicitly injected between Phase 2 and Phase 3 to calibrate local model latency, memory headroom, and resolve connection timeout thresholds. Additionally, a 1 business day hardware provisioning and network download buffer is injected prior to Phase 2 to prepare local networks and sequence model weight pulls (~19.5GB total) safely. T28a-2 (Phase 2 partial test gate) runs at end of Phase 2.
    * **Deliverables**: Presidio scrubbing settings, zero-shot routers, Fast/Slow mediator and critique loopback nodes, PostgresSaver checkpointers, Kokoro ONNX CPU thread-limited TTS workers, soundfile WAV encoders, Langfuse observability container, rate limiting middleware, and incremental test coverage.
3. **[Phase 3: Image Processing & Backend REST API Gateways](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/plan/phase_3_image_api.md)**
   * **Phase Objective**: Construct the image scaling/conversion pipelines and expose authenticated FastAPI endpoints for sessions, staging, and heir onboarding profiles. Write incremental tests.
   * **Deliverables**: Storage driver interface with mock driver, HEIC to WebP normalizers, GCS and S3 bucket drivers, Llava visual OCR pipelines, Heir management, Admin Heir Deletion API (T60), invite routes, support/help API, and incremental test coverage. T28a-3 (Phase 3 partial test gate) runs at end of Phase 3.
   * **Note**: A 2 business day schedule buffer is injected between Phase 3 and Phase 4 to align API contracts and database relations before math solver integration.
4. **[Phase 4: Probate Keepsakes & Fair Division Math](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/plan/phase_4_keepsakes_math.md)**
   * **Phase Objective**: Develop the ReportLab PDF rendering engine, integrate the Fairpyx division solver, and expose the GDPR soft anonymization router. Write incremental tests.
   * **Deliverables**: Keepsakes and Probate Ledgers PDF NumberedCanvas structures, Fairpyx Maximum Nash Welfare solver, tie-breaker Unix epoch calculations, GDPR soft anonymization endpoints (T55), and incremental test coverage.
   * **Note**: A 3 to 5 business day schedule buffer is injected between Phase 4 and Phase 5 to allow visual PDF output inspection (text overflow, pagination, image rendering), API contract validation, and integration testing before frontend state management consumes Phase 4 endpoints.
5. **[Phase 5: Frontend Architecture, Zustand, & Routing](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/plan/phase_5_frontend_architecture.md)**
   * **Phase Objective**: Structure the React Vite application shell, Zustand global stores, custom client routing guards, legal disclaimer footers, and Admin configuration/setup panels. Write incremental tests.
   * **Deliverables**: Archival theme CSS styles, client router maps, Zustand stores, Admin Setup (T54), Inventory (T52), Session Control (T53) dashboards, BIP39 Mnemonic Restore Panel (T56), Legal Disclaimer Footer (T73), and incremental test coverage.
   * **Note**: A 2 to 3 business day schedule buffer is injected between Phase 5 (frontend) and Phase 6 (WebSocket audio) to allow the frontend test suite (T29) to stabilize and resolve cross-browser rendering issues before audio pipeline integration begins. This prevents cascading rework from audio UI bugs being masked by incomplete frontend state.
6. **[Phase 6: Audio Speech & Real-Time Communications](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/plan/phase_6_audio_websockets.md)**
   * **Phase Objective**: Configure real-time WebSocket communication, client transcription workflows, and play queues. Write incremental tests.
   * **Deliverables**: WebSocket chat chunk servers, Web Speech client hooks, sequential audio queues, Admin Voice Recorder widget, and incremental test coverage.
   * **Note**: A 2 to 3 business day schedule buffer is injected between Phase 6 and Phase 7 to perform manual audio latency tuning, handle browser AudioContext state transitions, and verify WebSocket socket leakage under load before final E2E compliance validation.
7. **[Phase 7: System Backup, Compliance & E2E Validation](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/plan/phase_7_backup_validation.md)**
   * **Phase Objective**: Implement disaster recovery archives, Cloudflare Tunnel public exposure, host hardening, and execute final E2E validation scripts verifying GDPR, CCPA, and California Bot laws.
   * **Deliverables**: Decrypted tar.gz backups, Nginx & Production Build Setup (T61), Cloudflare Tunnel Setup (T74), Host Hardening (T75), GDPR/CCPA erasure audit checks, Unauthenticated System Restore Gate (T72), and final E2E testing runs.
   * **Note**: A 1 to 2 business day schedule buffer is injected between T28c (Phase 6–7 backend tests) and T30 (E2E Compliance Validation) to absorb test remediation before the final compliance gate.

---

## Step 3: Task & Dependency Register

| Task ID | Task Name | Description | Dependencies | Estimated Effort |
| :--- | :--- | :--- | :--- | :--- |
| **T01** | DB Docker Setup & Startup Retry Loop | Set up PostgreSQL Docker container with volume persistency (pgdata named volume), configure standard pgvector extensions, and write the application startup connection verification retry logic (5 attempts, 2-second delay). | None | Low |
| **T02** | SQLAlchemy Models & Relations | Define core database models (`users`, `sessions`, `assets`, `valuations`, `audit_logs`, `chat_messages`, `support_requests`, `custom_faqs`) and relationships. | T01 | Medium |
| **T03** | AES-Fernet Encryption Decorator | Implement custom `EncryptedJSON` decorator for database columns `audit_logs.state_snapshot`, `chat_messages.message_text`, and `valuations.reasoning`. | T02 | Medium |
| **T04** | Alembic Migrations & pgvector Indexing | Create migration scripts initializing the pgvector extension and configuring cosine similarity HNSW vector indexes. **Must include migration verification for ALL 8 tables including `custom_faqs`.** | T02, T03 | Low |
| **T05** | Microsoft Presidio PII Scrubbing | Configure Presidio Analyzer and Anonymizer engines to redact PERSON, EMAIL_ADDRESS, PHONE_NUMBER, LOCATION, US_SSN, and IP_ADDRESS. | None | Medium |
| **T06a** | Ollama Model Downloads (Network-Bound) | Pull Ollama model weights (~21GB total): qwen3:8b, qwen3:14b, qwen3-vl:8b, nomic-embed-text. Start first in Phase 2 to run while T05/T50 are developed. **Note: T21a (Kokoro ONNX ~2.5GB) downloads over the same network interface — T21a depends on T06a to force sequential execution on a Pi 5 to avoid saturating the link.** | None | High (Duration — 1–5 hours wall time) |
| **T06b** | Ollama Configuration & Integration | Configure Ollama endpoint, test model reachability and basic inference responses. | T06a | Low |
| **T21a** | Kokoro ONNX Model Download | Download the Kokoro-82M ONNX model binary (~2.5GB) and `voices.json` from the Hugging Face repository. Configure Docker volume mount to `/app/models/`. **Note: Depend on T06a to force sequential execution and avoid Pi 5 link saturation. Combined network time with T06a: 1–6 hours wall time.** | T06a | High (Duration — ~30–90 min wall time) |
| **T21** | Kokoro-82M TTS & soundfile WAV Encoder | Set up local ONNX CPU speech engine with max 2 threads, WAV soundfile byte array conversion, and configure system-level `libsndfile` dependencies in the backend app environment. Add startup validation guard that verifies model files exist and are readable at boot; if missing, emit critical WARNING log and gracefully degrade (WebSocket audio chunks omitted, text-only chat proceeds). **Owns the graceful degradation contract — T21a is pure download, T21 implements the application-level startup guard. Scheduled in Phase 2 to support co-tenancy memory profiling (T63).** | T21a | High (Duration) |
| **T63** | Pi 5 Model Downscaling & Memory Profiling | Evaluate Raspberry Pi 5 (8GB RAM) memory headroom under concurrent heir load. Create alternative downscaled model profiles (Fast: qwen3:1.7b, Slow: qwen3:8b, Vision: qwen3-vl:2b or qwen3-vl:4b Q4). Test Ollama memory usage, Kokoro + Postgres + FastAPI co-tenancy. Document which model combo fits within 8GB envelope. **CRITICAL: T21 (Kokoro engine setup) and T50 (LLM provider abstraction) MUST complete before T63 begins — the co-tenancy benchmark requires the Kokoro engine and LLM provider factory to be operational and loaded into memory to produce a valid memory profile. Without this dependency, the memory profile will be incomplete and may invalidate downstream model sizing decisions. This task anchors the critical path between Phase 2 and Phase 3 — the phase buffer (3–5 business days) exists specifically to absorb its findings. NOTE: T63 does NOT gate T44 (Session Override API) — T44 depends on T07a/T08 for the checkpointer state schema, not on the Pi 5 model size selection. Expected wall time: 1–3 days of iterative benchmarking.** | T06b, T21, T50 | High (Duration — blocking) |
| **T50** | LLM Provider Abstraction Layer & Ollama Health-Check | Implement unified LLM factory (`app/services/llm_provider.py`) abstracting LLM calls to support Ollama, OpenAI, Anthropic, and Google. Includes Ollama health-check polling with automatic connection retry/probe logic to prevent transient Ollama restarts from crashing the LangGraph workflow. Integrate Langfuse/Langtrace self-hosted tracing observability. **Verification must include asserting that mock LLM, vision, and embedding calls succeed under the provider abstraction factory, and that a simulated Ollama outage triggers retry logs without crashing the provider. Must also strip reasoning/"thinking" tokens (e.g. Qwen3 `<think>...</think>`, Gemma `<\|channel>thought...<channel\|>`) from raw model output uniformly across `generate_text`, `generate_structured`, and `generate_vision` before returning to the caller, so thinking-capable model families don't leak reasoning text into parsed JSON or chat output.** | T06b | Medium |
| **T50a** | Admin LLM Connection Test Endpoint & UI | Add `POST /api/admin/settings/test-connection` (Admin-only, 10/minute rate limit) letting an Executor fire one minimal real call through the `LLMProvider` abstraction for a chosen purpose (`fast`/`slow`/`vision`/`embedding`/`pricing`), using unsaved draft provider/model/credential values supplied as temporary `os.environ` overrides (never persisted, restored in a `finally` block). Validates `purpose` and rejects override keys outside the `llm` section of `SETTINGS_REGISTRY`. Always returns `200 OK` with `{success, detail/error, elapsed_ms}` — provider/auth/timeout failures are caught and reported in the body, never surfaced as a `500`. Add a "Test Connection" button inside each purpose card in `AdminSettingsPanel.jsx`, showing `✓ {detail} ({elapsed_ms}ms)` or `✗ {error}` inline. **[COMPLETED]** | T50, T54 | Medium |
| **T50b** | Per-Purpose Independent LLM Provider/Model/Credentials | Extend `llm_provider.py` so every AI purpose (fast, slow, vision, embedding, pricing) has its own fully independent `PROVIDER`, `MODEL`, `API_KEY`, and `BASE_URL` environment variables. Implement `_provider_for_key(model_key)` and `_credentials_for_key(model_key)` dispatch helpers. Fallbacks: FAST/SLOW fall back to `LLM_PROVIDER`; PRICING falls back to `VISION_PROVIDER`. Add all new keys to `SETTINGS_REGISTRY`; add `PRICING_` to `_LLM_RELOAD_PREFIXES`. Per-purpose `api_key`/`api_base` are passed directly to LiteLLM kwargs. **[COMPLETED]** | T50 | Medium |
| **T50c** | AI Keepsake Detail Generation Endpoint (`generate-details`) | Implement `POST /api/assets/{asset_id}/generate-details` (Admin-only). Two-step pipeline: (1) vision call with `response_format=AssetListingResponse` Pydantic model (title, category, item_overview, specifications, condition_report, keywords, sentiment_tags, dimensions), `max_tokens=4096`, using `MODEL_KEY_VISION`; (2) separate pricing-only vision call with `response_format=ValuationEstimate` (valuation_min, valuation_max, valuation_basis) using `MODEL_KEY_PRICING`. Step 2 is non-fatal. Endpoint does NOT write to the database. **[COMPLETED]** | T50b, T11 | Medium |
| **T50d** | AI Feedback / Human Verification Endpoint (`ai-feedback`) | Implement `POST /api/assets/{asset_id}/ai-feedback` (Admin-only). Accepts `{rating, comment}`, snapshots current asset listing fields, persists `{rating, comment, submitted_at, snapshot}` JSON to `assets.ai_feedback`. Include `ai_feedback` in all asset serialization dicts. **[COMPLETED]** | T11 | Low |
| **T54a** | AdminSettingsPanel Grouped Purpose Cards | Refactor LLM section of `AdminSettingsPanel.jsx` into one card per purpose (Fast, Slow, Vision, Embedding, Pricing). Each card: provider dropdown with auto-fill of default model on change, model input, per-purpose API key password input, per-purpose base URL input, and "Test Connection" button. "Shared Provider Credentials" card at bottom for company-level fallback keys. `PURPOSE_CREDENTIAL_FIELDS` and `PROVIDER_DEFAULT_MODELS` constants. Non-LLM tabs keep flat layout. **[COMPLETED]** | T54, T50a, T50b | Medium |
| **T52a** | Admin Inventory Dashboard AI Workflow UI | Add AI generation and human verification to Edit Keepsake Details drawer. "✨ Generate with AI" calls generate-details and populates form fields. `aiGeneratedAssets` Set tracks generated assets this session. "✓ Mark as Verified" calls ai-feedback; `verifyingAssets` Set tracks in-progress saves. Drawer toolbar: left status banner (verified/AI-generated/pending), right buttons (verify + generate). AI error modal (z-index 1300, separate from shared error state). Verify errors render inside drawer toolbar. Asset cards show "✓ Human Verified" (green) or "✨ AI Generated" (amber) badges. **[COMPLETED]** | T52, T50c, T50d | Medium |
| **T52b** | Admin Inventory Dashboard — Local State Sync & Review Filter | (1) After `handleGenerateDetails` succeeds, clear `ai_feedback: null` and update `category` in `setInternalAssets` so "Needs Review" badge and category field update without a page refresh. (2) Add "Review" filter dropdown to the inventory filter bar with options: All Items, Human Verified, Needs Review (filters by `JSON.parse(asset.ai_feedback)?.rating === 'thumbs_up'`). **[COMPLETED]** | T52a | Low |
| **T54b** | Admin Tab Persistence Across Refresh | Initialize `activeTab` in `AdminDashboard.jsx` from `localStorage.getItem('admin_active_tab')`. Add `setActiveTabPersisted` wrapper that saves to `localStorage` on every tab change, so hard browser refreshes restore the previously active tab. **[COMPLETED]** | T54 | Low |
| **T54c** | AdminSettingsPanel Base URL Visibility & Test Connection Secret-Skipping | (1) Hide the Base URL input field in each LLM purpose card when the selected provider is `openai`, `anthropic`, or `google` — only show it for `ollama`, `openrouter`, `nvidia`. (2) In `handleTestConnection`, skip any secret credential field from the `overrides` payload if the admin has not typed a new value this session, preventing empty-string overrides from wiping saved credentials. **[COMPLETED]** | T54a | Low |
| **T50e** | LiteLLM Unicode/ASCII Environment Hardening | Set `litellm.success_callback = []` and `litellm.failure_callback = []` at module load in `llm_provider.py`. Add `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` to `backend/Dockerfile` ENV and `docker-compose.yml` app environment. Pin `litellm>=1.90.1` in `requirements.txt`, relax `importlib-metadata>=4.0.0`. Sanitize test-connection error messages with `.encode("ascii", errors="replace").decode("ascii")[:500]`. **[COMPLETED]** | T50a | Low |
| **T50f** | AI Category Assignment in generate-details | Before the vision call in `generate-details`, fetch existing session category names from the DB and include them in the prompt so the AI picks from existing categories. `AssetListingResponse` gains `category_is_new: bool = False`. Post-parse: auto-create in `categories` table if AI proposed a new name AND `category_is_new=True`; fall back to first existing category if `category_is_new=False`. Do not return `category_is_new` in the API response. **[COMPLETED]** | T50c | Low |
| **T07a** | LangGraph State Schema, Nodes & Prompt Templates | Define the `MediationState` TypedDict and implement all node classes: smart intent router, Fast System 1 conversational node (with 4-sentence constraint), Slow System 2 critique node, RETRIEVE_RAG node, SLOW_REFLECT node, VALIDATE node, COMMIT node, and HITL_GUARD node. Compile the graph with retry policies (3 attempts, backoff). **Each node must emit structured logs at entry and exit following Backend Spec §14.2 format. Implement PII Leakage Guard per Spec §14.5. This task is model-agnostic — prompt templates and state schema are defined in the specs and do not depend on which model size is selected by T63. NOTE: Does NOT depend on T63 or T62.** | T03, T04, T05, T06b, T50 | High |
| **T07b** | LangGraph Model-Specific Tuning & Concurrency Config | Apply model-specific tunables (token limits, concurrency ceilings, timeout thresholds) based on T63 profiling results. Inject the validated model profile into LangGraph node configuration. **Depends on T63.** | T07a, T63 | Low |
| **T08** | LangGraph PostgresSaver Integration | Integrate persistent PostgreSQL Saver checkpointer to store thread states in the relational database. **Must validate that SqliteSaver is NOT used — a negative test case must assert that container restarts preserve thread state, per LangGraph Spec §7.3.** | T02, T07a | Medium |
| **T09a** | Storage Driver Interface & Mock Driver | Define abstract storage driver base class with `save(path, bytes)`, `get(path)`, and `delete(path)` methods. Implement a Mock driver for unit testing. **This enables all downstream API tasks to be developed in parallel with concrete storage implementations.** | None | Low |
| **T09b** | Image Preprocessing Pipeline & Concrete Storage Drivers | Develop HEIC/PNG to WebP conversion logic with 80% compression, 1200x1200px bounds. Implement LOCAL, GCS, and S3 concrete storage drivers with explicit `delete()` method for file cleanup. **Depends on T09a for the interface contract. Required by T40, T41, T31, T34, T55, T60, T13, T49 for secure deletions.** | T09a | Medium |
| **T10** | FastAPI Core & Onboarding endpoints | Expose admin login/setup, invitation verification (`POST /api/invite/verify`), JWT session cookie issuance, cookie introspection (`GET /api/auth/me`), and logout cookie clearing (`POST /api/auth/logout`). `GET /api/auth/me` is required for hard-refresh restoration on both `/admin` and `/dashboard`; it must return the authenticated role and session scope without allowing a Heir cookie to open Admin routes or an Admin cookie to open Heir routes. **Note: JWT/Argon2 endpoints are model-agnostic. Rate limiting middleware (T73) MUST be applied to all public endpoints implemented in this task.** | T02, T03, T73 | Medium |
| **T37** | FastAPI Session Lifecycle & Announcement API | Expose session launch, pause, unpause, and announcement endpoints, implementing dynamic token/deadline extensions and WebSocket updates. | T02, T10, T38 | Medium |
| **T11** | FastAPI Asset Router | Expose asset staging (`POST .../stage`), background Llava OCR, WebSocket completion notifications, and asset publishing with automatic matrix seeding and pre-allocation valuations cleanup. **MUST validate that title, description, category, valuation_min, valuation_max, valuation_source, and sentiment_tag are fully populated before allowing transition to LIVE (per DB Spec §2.3). NOTE: Does NOT depend on T63 — the pipeline graph shows T63 depends on T50 (T06b→T50, T06b→T63, T50→T63); T11 depends on T50 but NOT on T63. T63 is downstream of T50, not upstream.** | T02, T04, T09a, T09b, T10, T38, T50 | Medium |
| **T12** | FastAPI Valuation Router | Implement valuation draft saving (`PUT .../draft` with concurrency versions) and submission under strict locking hierarchies, HITL_GUARD locks, and LangGraph audits (pre-fetching audit log primary key `id` via `SELECT nextval('audit_logs_id_seq')` to calculate SHA-256 hash). **Must return 403 Forbidden with message `"Points submission suspended. Your allocations require review and correction by the Executor."` if the LangGraph thread is suspended at HITL_GUARD. WARNING: This is an 'Extreme' complexity endpoint — requires 3-tier pessimistic locking, points sum validation, deadlock detection broadcast, and concurrency version handling. The pessimistic lock ordering contract (Session→User→Valuations) is unforgiving — one ordering mistake causes production deadlocks under concurrent heirs.** | T02, T07a, T08, T10, T11, T37 | Extreme |
| **T81** | SMTP Service & Retry Infrastructure | Implement a shared `app/services/smtp_service.py` with `send_email(to, subject, body, attachments)` using `aiosmtplib`. Encapsulates the retry policy (up to 3 attempts, exponential backoff: 1s, 4s, 16s) and async background task dispatch. Transaction decoupling: SMTP dispatch must run asynchronously and must not roll back database commits on failure. Consumed by T13, T33, and T16. | T02, T10 | Low |

| **T13** | FastAPI Heir Management & Invitations | Create heir creation, invite token generation/renewal, async invitation emails using the shared SMTP service (T81) with up to 3 retry attempts using exponential backoff — 1s, 4s, 16s — on connection failures, and profile self-correction endpoints. **Depends on T09b to support ID scan deletion on legal name updates.** | T02, T09b, T10, T37, T38, T81 | Medium |
| **T84** | Optional OIDC/SSO Foundation | Add generic OpenID Connect Authorization Code + PKCE support, encrypted OIDC settings, and `external_identities` links keyed by `issuer + subject`. Local Argon2 Admin login remains the bootstrap/recovery path. Recommended open-source brokers: Keycloak or Authentik. | T02, T03, T10 | Medium |
| **T85** | Admin and Heir Federated Login UX | Add optional "Continue with SSO" flows for Admin login and post-approval Heir identity linking. Heir SSO linking must be unavailable during invite acceptance and `PROFILE_HOLD`; it becomes available only after Executor identity approval. Admin SSO linking must require an authenticated Admin session and preserve at least one usable Admin login method. | T19, T84 | Medium |
| **T71** | Proof of Notice Log Data Contract | Formalize the cross-task data contract between T13 (invitation dispatch timestamps), T65 (expiration transitions), and T14 (PDF rendering). T13/T65 must expose a `notice_log` data structure consumed by T14's Document B "Proof of Notice Log" section. | T13, T65 | Low |
| **T14** | ReportLab PDF Builders | Construct Keepsake Memory Book and Final Distribution Ledger templates with NumberedCanvas pagination, table cell paragraph wrapping, dynamic columns (with programmatic width calculations and transition to Landscape layout if $N > 4$ heirs), cloud GCS or S3 image buffer, and legal disclaimer on cover page per Legal Spec §5. **Also generates the Mathematical Proof section (Backend Spec §13.3 Item 8) — a structured text explanation of the Max Nash Welfare optimization guarantee. Consumes `mnw_product_value` scalar and solver allocation results from T15 via formal data contracts. Depends on T71 notice log data contract structure. NOTE: PDF layout debugging requires visual inspection — budget 1–2 weeks for iterative tuning of table cell wrapping, pagination, and overflow protection.** | T02, T03, T15, T71 | Extreme |
| **T15** | Fairpyx MNW Solver & Tie-Breakers | Integrate Fairpyx solver with tie-breaking logic based on float Unix epochs of `submitted_at`, `created_at`, and `deadline` timestamps, and user UUIDs fallback. **Must include Zero-Utility Starvation Bypass check. Must expose a `mnw_product_value` scalar (float) and solver allocation results consumed by T14 (PDF builder), and a `tie_breaker_events` list consumed by T70 (tie-breaker PDF record).** | T02 | High |
| **T70** | Tie-Breaker Resolution Record in PDF | Extend the ReportLab PDF builder (T14) to capture deterministic tie-breaking events from the solver (T15). Render a "Deterministic Tie-Breaker Resolution Record" table showing which heirs tied, their points, submission timestamps, and the deterministic outcome. **Data contract: T15 must expose a `tie_breaker_events` list consumed by T14.** | T14, T15 | Medium |

| **T82** | Hash Chain Verification Tool | Build a standalone `GET /api/system/verify-hash-chain` endpoint (or CLI script) that allows an auditor/executor to independently verify the SHA-256 tamper-proof audit chain by re-computing hashes from database rows and comparing against the stored `sha256_hash` values. Returns verification result with per-row validation status and any breaks found. | T02, T03 | Low |

| **T83** | Mediation Chat History API | Build `GET /api/sessions/{session_id}/heirs/{heir_id}/chat` endpoint returning persisted chronologically-sorted conversation history from `chat_messages`. **Access: Heir JWT cookie matching `{heir_id}` only. Admin credentials MUST be rejected with `403 Forbidden` per Legal Spec §6.** | T02, T03, T08, T10 | Low |
| **T16** | FastAPI Keepsake & Finalization Router | Expose endpoints for `/api/sessions/{session_id}/finalize` (running solver, updating statuses, and sealing audit hash chains), automatically checking and transitioning non-submitting active heirs to `'ABSTAINED'` and un-logged-in expired heirs to `'EXPIRED_NON_PARTICIPATING'` prior to solver execution, and keepsakes downloading/emailing via T81 SMTP service. | T12, T14, T15, T65, T70, T81 | Medium |
| **T17** | Frontend Vite Base & Vanilla CSS | Initialize React SPA shell and implement Vanilla CSS design system tokens matching the Archival Index Card styling. **Must include `@media print` CSS rules for printable paper records per DB Spec §7.** | None | Medium |
| **T18** | Zustand store & cache keys | Setup global stores (`useMediationStore`) and TanStack Query cache keys for assets, sessions, and valuations, including tracking the `is_hitl_suspended` boolean state variable. Store actions must support cookie-based rehydration after hard refresh for both Admin and Heir users, and explicit logout must clear auth/session state without defaulting the role back to Heir. | T17 | Medium |
| **T19** | Client Routing & Onboarding views | Implement React Router paths, onboarding checkbox gates, consent cards, E-SIGN Act Consumer Disclosure Banners, and the **pre-filled legal profile summary card (rendered as editable text inputs to support typo correction) with confirmation checkbox** per Compliance Spec §3.1. Also implements the **Executor acknowledgment checkbox** during session initialization confirming the advisory nature of algorithm results per Legal Spec §5. | T17, T18 | Medium |
| **T20** | Heir & Admin Dashboard View Guards | Implement UI locks, SB 1001 AI Mediator banners, and **the Sum Validation Hold Lock view guard (which disables points sliders, numerical input boxes, and chat panel when `is_hitl_suspended` is true and renders the required explanation banner, while keeping draft saving enabled)**. **(Note: SB 942 synthetic voice label ownership moved to T25 — only T25 should manage dynamic 'Synthesized AI Voice' labels based on the `is_synthetic` flag.)** | T18, T19 | High |
| **T22** | WebSocket Server Endpoint | Create FastAPI WebSocket controller. The router must inspect the user's thread state via PostgresSaver. If suspended at HITL_GUARD, reject incoming client message frames with error type `'error'` and message `'Points submission suspended. Your allocations require review and correction by the Executor.'` while keeping the socket open for status broadcast frames. **Note: T21 (Kokoro TTS) is a SOFT dependency — T22 MUST be built and tested with text-only WebSocket frames (audio: null) before T21 is complete. Per the T21 graceful degradation contract, the WebSocket server functions correctly with text-only chat when Kokoro is unavailable.** | T07a, T08, T10, T38 | High |
| **T23** | WebSocket Client Connection Loop | Establish client-side dashboard WebSockets with reconnect handlers, backoff, and offline message queue buffering. | T18, T22 | Medium |
| **T24** | Web Speech Client Hook | Implement browser speech-to-text hook with HTTPS guards, hold/toggle, parsing WebSocket synthetic voice markers, and **the 'Enable Audio' speaker button on dashboard mount that resumes the suspended AudioContext per Frontend Spec §5.5 (hidden after first successful gesture).** | T17, T23 | Medium |
| **T25** | Client Audio Playback Queue | Create sequential audio play queue, base64 Blob decoder, unmount URL revokers, and parsing synthetic voice markers. **Consolidates SB 942 synthetic voice label ownership — dynamically updates the audio player status label ('Synthesized AI Voice') based on the `is_synthetic` flag in WebSocket chunk frames.** | T18, T23 | Medium |
| **T26** | pg_dump System Backup & Restore | Expose admin endpoints for symmetric AES-Fernet encrypted tar.gz database backups and transaction-safe restores. | T02, T03 | Medium |
| **T27** | BIP39 Mnemonic Onboarding Screen | Create 24-word paper recovery seed phrase display screen for onboarding setup confirmation. | T18, T39 | Medium |
| **T31** | Government ID Scan Upload API | Expose `POST /api/heirs/me/upload-id` endpoint supporting encrypted government ID image/PDF uploads. **Depends on T09b for file storage.** | T02, T03, T09b, T10 | Medium |
| **T32** | Government ID Scanner & File Drop UI | Build HTML5 camera scanner overlay card and drag-and-drop file slot on `/dashboard` during hold status. | T17, T18, T19, T31 | High |
| **T33** | Active Abstention Waiver PDF Receipt & Email | Build `/api/heirs/me/abstain` endpoint (waiver, SMTP receipt via T81, ticket, auto-generating an `'OPEN'` support request on email failure) and `/api/heirs/me/abstain/receipt` (ReportLab PDF). **Must pre-fetch audit log primary key `id` via `SELECT nextval('audit_logs_id_seq')` before INSERTing the `'ABSTENTION_WAIVER'` event to compute the SHA-256 hash chain link.** | T12, T14, T37, T81 | Medium |
| **T34** | Executor ID Verification State Transition API | Build endpoint for Executor visual ID inspection, database seeding for LIVE assets, and temporary scan purge. **Depends on T09b to purge scan files.** | T02, T03, T09b, T10, T11, T13, T31, T37 | Medium |
| **T35** | Executor Force Allocation Console UI | Build Admin dashboard interface to view deadlocked items, select beneficiaries, and submit overrides via `/api/sessions/{session_id}/override`. | T18, T20, T44 | Medium |
| **T36** | AB 2013 Model Transparency API & Modal | Expose `GET /api/system/models` transparency endpoint and the help drawer model transparency display modal. | T10, T18, T20 | Low |
| **T38** | WebSocket Connection Manager | Implement `app/websocket_manager.py` shared singleton with `connect`, `disconnect`, and broadcast helper methods. **⚠ No database dependency — T38 is an in-memory connection registry singleton.** | None | Low |
| **T39** | Admin Setup & Session Creation API | Build `POST /api/setup/admin` (first-boot admin creation + BIP39 mnemonic, idempotent) and `POST /api/sessions` (new mediation session). | T02, T03, T10 | Medium |
| **T40** | Asset Deletion API | Build `DELETE /api/assets/{asset_id}`. Cascade-delete valuations and image file. Gate on session status — returns 400 if session is `'ACTIVE'`, `'LOCKED'`, or `'FINALIZED'`. | T02, T10, T11 | Low |
| **T41** | Admin Audio Story Upload & Delete API | Build `POST /api/assets/{asset_id}/audio` accepting multipart audio (WebM/MP3/WAV, matching Backend Spec §9.2) and `DELETE /api/assets/{asset_id}/audio` to remove the audio file and nullify `assets.audio_uri`. Both gate on `'SETUP'` session status. Audio file cleanup cascades on asset deletion (T40). | T02, T09b, T10, T11 | Low |
| **T42** | Support Request & Help CRUD API | Build `POST /api/sessions/{session_id}/help` (Heir submits, WebSocket alert to Admin), `GET /api/sessions/{session_id}/help` (Admin list), `POST /api/help/{ticket_id}/resolve` (Admin resolves). **Routes match Backend Spec §9.4 namespace.** | T02, T10, T38 | Medium |
| **T43** | Custom FAQ CRUD API | Build `POST/PUT/DELETE /api/sessions/{session_id}/faqs/{faq_id}` (Admin management) and `GET /api/sessions/{session_id}/faqs` (Heir read). Broadcasts WebSocket event on mutation. | T02, T10, T38 | Low |
| **T44** | Session Override API | Build `POST /api/sessions/{session_id}/override` HITL endpoint. Writes corrected allocations into LangGraph checkpointer state, resumes graph, and writes `'ADMIN_OVERRIDE'` audit log block (pre-fetching audit log primary key `id` via `SELECT nextval('audit_logs_id_seq')` to calculate SHA-256 hash). **Must adjust heir points budgets. NOTE: Does NOT depend on T63 — the checkpointer state schema is defined by T07a/T08 code artifacts, not by Pi 5 model size selection.** | T02, T07a, T08, T10, T12 | Medium |
| **T45** | Admin Voice Recorder Widget | Build `MediaRecorder`-based voice story recording panel on the Admin asset staging card: record/stop/playback/redo/save controls, 2-min timer, HTTPS guard. Uploads blob via T41 on publish. | T17, T18, T41 | Medium |
| **T46** | Semantic Search UI | Build asset gallery search bar, filter panel (category, allocation, provenance, shared stories), sorting controls, confidence badge (≥75% match), and zero-match fallback with "Ask the Mediator" chat injection. **Every gallery card must be clickable/keyboard-activatable to open the Asset Detail Pane modal (full image gallery, description, structured details, valuation, sentiment tags, audio) per UI Spec §3.1 Card Interaction. This click-to-detail path is a hard requirement, not an optional polish item — it must work identically inside the Finalized Keepsake Layout (T16/DashboardGuard's `FINALIZED` branch), since that layout reuses this component's card list. Verify explicitly after building any new dashboard layout that swaps in this grid.** | T17, T18 | Medium |
| **T47** | FAQ/Help UI Components | Build Heir FAQ accordion drawer (dynamic estate FAQs from API) and Admin Help Portal full-screen modal with 5-section tutorial and inline FAQ editor wired to T43 endpoints. | T17, T18, T43 | Medium |
| **T48** | Session Announcement UI Components | Build Admin Announcement Console (broadcast/clear inputs), Heir sticky Amber-500 banner, and Heir login modal acknowledgment gate. | T17, T18, T37 | Medium |
| **T51** | Active Abstention Waiver UI Components | Build Heir Active Abstention Waiver button, legal name signature verification modal, and post-abstention wait screen with PDF receipt download trigger. **Renders wait screen for ABSTAINED/EXPIRED_NON_PARTICIPATING status.** | T17, T18, T20, T33 | Medium |
| **T49** | Secure Session Purge | Build `DELETE /api/sessions/{session_id}?confirm=true`. 6-step irreversible permanent deletion: chat logs → checkpointer rows → files → hard-delete users → session cascade. Gates on `'FINALIZED'` status + `confirm=true`. **Depends on T09b to delete files.** | T02, T09b, T13, T26, T55 | Medium |
| **T52** | Admin Inventory Dashboard UI | Build the Admin inventory setup and editing card UI, including file upload trigger, Llava OCR metadata edit fields, valuation source selection, pre-allocation overrides, and publish live button. **Includes permanent notice: "This system is strictly for personal property and keepsakes. Do not upload real estate, vehicles, or bank/financial accounts." per Legal Spec §4.** | T17, T18, T11 | High |
| **T53** | Admin Session Control UI | Build the Executor dashboard panel to manage heir profiles, send invitation emails, track progress with checkmark status tables, pause/unpause sessions, and trigger the finalization solver. | T17, T18, T13, T34, T37, T16 | High |
| **T54** | Admin Onboarding & Credentials Setup UI | Build the first-boot interface displaying the 24-word BIP39 paper recovery seed phrase and requiring confirmation before enabling session creation. The Admin route must attempt `GET /api/auth/me` restoration before showing first-boot setup or login, render a restoring state during that check, preserve valid Admin sessions across browser hard refresh, and call `POST /api/auth/logout` on logout. The post-login Admin landing view must scale beyond demo data: provide a searchable/filterable/sortable session index with card/list density controls, summary chips, and pagination or incremental loading so desktop and mobile Admins can manage dozens/hundreds of estate sessions without one long unbounded scroll. | T17, T18, T39, T27 | Medium |
| **T55** | FastAPI Heir GDPR Erasure Router | Implement `DELETE /api/heirs/me` soft anonymization (purging chat logs, deleting checkpointer thread states, removing ID scans from disk, and sanitizing historical snapshots in `audit_logs` based on submission status). **Depends on T09b to delete scan files.** | T02, T08, T09b, T10, T12, T13, T31 | High |
| **T56** | BIP39 Mnemonic Restore Panel | Create the recovery seed input fields on the Admin Restore panel UI for backup decryption. | T18, T26 | Medium |
| **T57** | FastAPI GDPR Data Portability API | Expose `GET /api/heirs/me/export` returning decrypted chat logs, valuations, profile details, and tickets in a structured JSON. | T02, T03, T10, T12, T13, T42 | Medium |
| **T58** | GDPR Data Portability UI Button | Build "Export My Data (JSON)" button in the settings/help drawer. | T17, T18, T57 | Low |
| **T59** | GDPR Account Deletion UI Drawer | Build the slide-out account deletion drawer, warnings, case-sensitive username confirmation input, and action triggers. | T17, T18, T55 | Medium |
| **T60** | Admin Heir Deletion API | Build `DELETE /api/sessions/{session_id}/heirs/{heir_id}` Admin endpoint. Purge Heir PII from users/chat/checkpointers and anonymize audit logs snapshots. **Depends on T09b to purge scans.** | T02, T03, T09b, T10, T11, T13, T31 | Medium |
| **T64** | Asset Pre-Allocation API | Build `POST /api/assets/{asset_id}/pre-allocate` endpoint. On transition to `'PRE_ALLOCATED'`, deletes all existing valuation rows for this asset in the `valuations` table to prevent orphaned valuations from polluting the solver matrix. Gate on `'SETUP'` session status. | T02, T10, T11 | Low |
| **T65** | Background Invite Expiration Scheduler | Implement a periodic background task that checks for expired invite tokens where `invite_token_used == False` and transitions those users to `'EXPIRED_NON_PARTICIPATING'`. Runs every 15 minutes. | T02, T13 | Low |
| **T66** | Family Memories & Stories UI Component | Build the read-only collapsible "Family Memories & Stories" section in the asset detail container. Render shared stories (where `is_reasoning_shared == true`) with no reply fields, no like buttons, no timestamps. Show the memory textbox and sharing checkbox only during active editing sessions (not paused/submitted). | T17, T18 | Medium |
| **T67** | Admin "Inspect ID" Modal Component | Build the split-pane modal for Executor ID verification: left pane shows the decrypted ID image in a scrollable/zoomable canvas; right pane shows heir's legal details side-by-side. Wire approve/reject actions to T34 endpoint. | T17, T18, T34 | Medium |
| **T68** | Heir "Request Help" Modal Component | Build the Heir-side support request modal: "Need assistance? Contact the Executor." trigger link, warm-white index card modal with text field (min 5, max 1000 chars), character counter, confirmation feedback. Wire to T42 help/support creation endpoint. | T17, T18, T42 | Low |
| **T69** | Auto-Balance Points Button UI | Build the "Auto-Balance Points" button in the valuation sliders panel. Implement proportional scaling algorithm that distributes remaining unallocated points across all assets. **Must include Division-by-Zero Guard: disabled if sum of all allocated points == 0.** Visual feedback showing the scaled distribution animation. | T17, T18 | Low |
| **T72** | Unauthenticated System Restore Gate Design | Design and implement the authentication bypass mechanism for `POST /api/system/restore` on fresh (uninitialized) systems. The endpoint must detect whether an admin account exists: if no admin exists, allow unauthenticated restore; if admin exists, require Admin JWT. Must implement rate-limiting and CSRF token to prevent abuse. **Consumes T73 for rate limiting middleware.** | T03, T10, T26, T73 | Medium |
| **T73** | Rate Limiting Middleware | Implement FastAPI rate limiting middleware (using slowapi or similar) and configure Nginx `limit_req` zones to protect all public endpoints against abuse. Required by T72 (unauthenticated restore gate) and Backend Spec §12.1. **MUST be applied to all public endpoints implemented in T10 (onboarding, invite verify, login). T73 is an independent middleware factory — T10 depends on T73, not the reverse. The Mermaid graph correctly shows T73 → T10 (T10 depends on T73).** | None | Low |
| **T61** | Nginx & Production Build Setup | Configure Nginx (`nginx.conf`) static serving with rate limiting zones, WebSocket proxy pass, uploads volume mounting, build the production frontend bundle (`npm run build`), and verify docker-compose static asset routing. | T17, T18, T19, T73 | Medium |
| **T74** | Cloudflare Tunnel & Public Exposure Setup | Configure outbound-only Cloudflare Tunnel (or Localtunnel fallback) to expose the local Raspberry Pi 5 securely to the public internet. Generate public HTTPS URL, configure DNS, and verify remote heir accessibility per Backend Spec §12.1. | T61 | Medium |
| **T75** | Host Hardening & SSH Configuration | Disable SSH password logins in favor of SSH key authentication, change default user credentials, enable automatic security package updates, and verify host firewall rules per Backend Spec §12.1. | None | Low |
| **T76** | Foundation Assets — Dependency Lockfiles & .env.example | Create `.env.example` template with all required environment variables documented. Pin `requirements.txt` to exact versions (replace `>=` with `==`) matching the local runtime. Verify `package.json` versions are pinned. These assets prevent LLM hallucinations from introducing incompatible library versions. | None | Low |
| **T77** | Foundation Assets — Model Download Automation Script | Create `scripts/download_models.py` to automate pulling Ollama weights (qwen3:8b/14b, qwen3-vl:8b, nomic-embed-text) and downloading the Kokoro-82M ONNX binary + `voices.json` to `/app/models/`. Supports `--dry-run`, `--skip-ollama`, `--skip-kokoro`, and `--ollama-only` flags. | None | Low |
| **T78** | Foundation Assets — OpenAPI Contract Specification | Create `openapi.json` (OpenAPI 3.1) defining all REST API paths, request/response schemas, WebSocket frame contracts, and error codes. Serves as the single source of truth for frontend Zustand stores and backend FastAPI routers to agree on naming conventions, payload shapes, and datetime formats. | None | Low |
| **T79** | Foundation Assets — Seed Data & Solver Test Fixtures | Create `backend/app/tests/fixtures.py` with realistic probate datasets: valid allocation matrices (3 heirs × 3 assets, each summing to 1000), tied-bid scenarios for deterministic tie-breaker testing, deadlocked allocation scenarios, starvation bypass scenarios (more heirs than assets), full heir status lifecycle scenarios, and OCR-staged asset validation gate test cases. | None | Low |
| **T80** | Foundation Assets — Mock Services for CI/CD | Create `backend/app/tests/mock_llm.py` (MockLLMProvider with scenario control: default, critique_fail, ollama_down, timeout) and `backend/app/tests/mock_kokoro.py` (MockKokoroTTS returning silent WAV buffers). Enables offline test execution in CI/CD with zero model loading — consumed by T28a-2 and T28c test gates. | None | Low |
| **T28a-1** | Backend Tests — Phase 1 Scope | Write `pytest` coverage for DB models/encryption (including `custom_faqs` table verification), Alembic migrations, pgvector indexing, and WebSocket connection manager. **Run at end of Phase 1.** | T02, T03, T04, T38 | Medium |
| **T28a-2** | Backend Tests — Phase 2 Scope | Write `pytest` coverage for Presidio scrubbers, Ollama provider (with health-check mock), LangGraph nodes/workflow, PostgresSaver (including negative test that SqliteSaver is NOT used), Kokoro TTS, LLM provider abstraction, and Pi 5 memory profiling harness. **Run at end of Phase 2. Gates Phase 3.** | T05, T07a, T08, T21, T50, T63 | High |
| **T28a-3** | Backend Tests — Phase 3 Scope | Write `pytest` coverage for Argon2 auth, image pipeline, onboarding endpoints (including rate limiting header verification on all public endpoints), asset staging/OCR (including lifecycle validation gate), session lifecycle, heir management, ID upload, support/help APIs, admin/FAQ/deletion APIs, session creation, and asset pre-allocation. **Run at end of Phase 3. Gates Phase 4.** | T09a, T09b, T10, T11, T13, T31, T34, T37, T39, T40, T41, T42, T43, T60, T64, T65, T73 | High |
| **T28b** | Backend Tests — Phases 4–5 Scope | Write `pytest` coverage for fairpyx solver tie-breakers, ReportLab PDF layouts (including visual output inspection for text overflow and pagination correctness, and **explicit Landscape page rotation trigger test when $N > 4$ heirs per Backend Spec §13.3 Item 7**), finalization router, valuation submission locking, GDPR erasure router, GDPR data portability, active abstention waiver, tie-breaker records, and proof of notice log contracts. **Run at end of Phase 5.** | T12, T14, T15, T16, T33, T55, T57, T70, T71 | High |
| **T28c** | Backend Tests — Phase 6–7 Scope | Write `pytest` coverage for WebSocket server endpoint, Kokoro TTS integration, session backup/restore transactions (T26), Nginx production routing, model transparency API, Cloudflare Tunnel routing, rate limiting middleware, and unauthenticated restore gate. **Must include SB 942 synthetic audio indicator assertions: verify every `chat_reply_chunk` frame contains `"is_synthetic": true` per Compliance Spec §2.5.** Run at end of Phase 7. | T21a, T21, T22, T26, T36, T61, T72, T73, T74 | High |
| **T29** | Frontend Unit & Integration Tests (Incremental) | Write and run client tests incrementally during each phase checking Zustand rebalances, router redirects, signature name match filters, unmount audio cleaners, legal disclaimer rendering, scalable Admin list behavior, and all new UI components. **Includes T54 session-index search/filter/sort/pagination verification and T66, T67, T68, T69, T73_UI components verification.** | T17, T18, T19, T20, T23, T24, T25, T27, T32, T35, T36, T45, T46, T47, T48, T51, T52, T53, T54, T56, T58, T59, T61, T66, T67, T68, T69 | High |
| **T73_UI** | Legal Disclaimer Footer Component | Build the permanent legal disclaimer footer component rendered on all dashboard views. Displays: *"Disclaimer: The Estate Steward is a collaborative mediation aid...does not provide legal advice..."* per Legal Spec §5. | T17, T18 | Low |
| **T30** | E2E Compliance Validation | Execute comprehensive automated scripts confirming GDPR portability, CCPA transparency listings, SB 942 synthetic audio disclosure, and SHA-256 integrity hash verification. | T28a-1, T28a-2, T28a-3, T28b, T28c, T29 | Medium |
| **T86** | PWA Mobile Distribution Packaging | **Missed requirement, added post-launch-planning**: Admin needs a phone in-hand to photograph inventory and monitor/communicate anywhere; Heirs need a single-phone experience for the full review/allocation process — neither role should require Apple App Store or Google Play submission. Implemented via `vite-plugin-pwa` in `frontend/vite.config.js` (generates `manifest.webmanifest` + Workbox service worker on every build, `NetworkOnly` for `/api`/`/ws` so mediation state is never served stale), `apple-touch-icon`/`theme-color`/`apple-mobile-web-app-*` tags in `frontend/index.html`, and rendered icons in `frontend/public/`. Installs via "Add to Home Screen" on iOS Safari and Android Chrome, served from the existing Cloudflare Tunnel/Nginx origin (T61, T74). Document iOS web-push limitations (16.4+ only, unreliable) and confirm the WebSocket reconnect loop (T23) + SMTP dispatch (T81) remain the real-time/fallback alert channels until/unless a native wrapper (Capacitor) is built. See Frontend Spec §7.1. | T61, T74, T23 | Medium |
| **T87** | `scripts/install_on_phone.sh` — One-Command Phone Install | Builds the frontend, starts the Docker stack, and prints a tappable link plus a scannable QR code (rendered as a real PNG and opened via `open`, since terminal ASCII-art QR codes are unreliable for camera scanning) so installing the PWA on a physical phone requires no manual URL typing. Uses `PUBLIC_BASE_URL`/`CLOUDFLARE_TUNNEL_TOKEN` from `.env` for the real HTTPS install path (full service worker support) when configured, else falls back to auto-detecting the host's LAN IP for same-Wi-Fi HTTP testing (icon-only install, no offline caching). See Frontend Spec §7.2. | T86 | Low |


## Step 4: Mermaid.js Dependency Graph

```mermaid
graph TD
    classDef independent fill:#f0f0f0,stroke:#999,stroke-dasharray: 5 5
    
    T01[T01: DB Docker Setup & Startup Retry Loop] --> T02[T02: SQLAlchemy Models & Relations]
    T02 --> T03[T03: AES-Fernet Encryption Decorator]
    T02 --> T04[T04: Alembic Migrations & pgvector Indexing]
    T03 --> T04
    T38[T38: WebSocket Connection Manager]:::independent
    
    T76[T76: Foundation Assets — Dependency Lockfiles & .env.example]:::independent
    T77[T77: Foundation Assets — Model Download Automation Script]:::independent
    T78[T78: Foundation Assets — OpenAPI Contract Specification]:::independent
    T79[T79: Foundation Assets — Seed Data & Solver Test Fixtures]:::independent
    T80[T80: Foundation Assets — Mock Services for CI/CD]:::independent
    
    T80 --> T28a-2[T28a-2: Backend Tests — Phase 2 Scope]
    T80 --> T28c[T28c: Backend Tests — Phase 6-7 Scope]
    T79 --> T28a-3[T28a-3: Backend Tests — Phase 3 Scope]
    T78 --> T29[T29: Frontend Unit & Integration Tests]
    
    T28a-1[T28a-1: Backend Tests — Phase 1 Scope] --> T05[T05: Microsoft Presidio PII Scrubbing]
    T28a-1 --> T06a[T06a: Ollama Model Downloads]
    T28a-1 --> T50[T50: LLM Provider Abstraction & Ollama Health-Check]
    T28a-1 --> T73[T73: Rate Limiting Middleware]
    T28a-1 --> T21a[T21a: Kokoro ONNX Model Download]
    
    T04 --> T07a[T07a: LangGraph State Schema, Nodes & Prompt Templates]
    T03 --> T07a
    T05 --> T07a
    T06a --> T06b[T06b: Ollama Configuration & Integration]
    T06a --> T21a
    T21a --> T21[T21: Kokoro-82M TTS & soundfile WAV Encoder]
    T21 --> T63[T63: Pi 5 Model Downscaling & Memory Profiling]
    T06b --> T63
    T06b --> T50
    T50 --> T63
    T63 --> T07b[T07b: LangGraph Model-Specific Tuning]
    T07a --> T07b
    T06b --> T07a
    T50 --> T07a
    
    T02 --> T08[T08: LangGraph PostgresSaver Integration]
    T07a --> T08
    
    T02 --> T10[T10: FastAPI Core & Onboarding endpoints]
    T03 --> T10
    T73[T73: Rate Limiting Middleware] --> T10
    
    T02 --> T37[T37: FastAPI Session Lifecycle & Announcement API]
    T10 --> T37
    T38 --> T37
    
    T02 --> T11[T11: FastAPI Asset Router]
    T04 --> T11
    T09a[T09a: Storage Driver Interface & Mock Driver] --> T11
    T09a --> T09b[T09b: Image Preprocessing & Concrete Drivers]
    T09b --> T11
    T10 --> T11
    T38 --> T11
    T50 --> T11
    
    T02 --> T12[T12: FastAPI Valuation Router]
    T07a --> T12
    T08 --> T12
    T10 --> T12
    T11 --> T12
    T37 --> T12
    
    T02 --> T81[T81: SMTP Service & Retry Infrastructure]
    T10 --> T81
    
    T02 --> T13[T13: FastAPI Heir Management & Invitations]
    T10 --> T13
    T37 --> T13
    T38 --> T13
    T09b --> T13
    T81 --> T13
    
    T02 --> T14[T14: ReportLab PDF Builders]
    T03 --> T14
    T15[T15: Fairpyx MNW Solver & Tie-Breakers] --> T14
    T71[T71: Proof of Notice Log Data Contract] --> T14
    
    T02 --> T15
    
    T12 --> T16[T16: FastAPI Keepsake & Finalization Router]
    T14 --> T16
    T15 --> T16
    T65[T65: Background Invite Expiration Scheduler] --> T16
    T70[T70: Tie-Breaker Resolution Record in PDF] --> T16
    
    T17[T17: Frontend Vite Base & Vanilla CSS] --> T18[T18: Zustand store & cache keys]
    T18 --> T19[T19: Client Routing & Onboarding views]
    T17 --> T19
    T18 --> T20[T20: Heir & Admin Dashboard View Guards]
    T19 --> T20
    
    T17 --> T73_UI[T73_UI: Legal Disclaimer Footer Component]
    T18 --> T73_UI
    
    T17 --> T32[T32: Government ID Scanner & File Drop UI]
    T18 --> T32
    T19 --> T32
    T31[T31: Government ID Scan Upload API] --> T32
    
    T07a --> T22[T22: WebSocket Server Endpoint]
    T08 --> T22
    T10 --> T22
    T38 --> T22
    
    T18 --> T23[T23: WebSocket Client Connection Loop]
    T22 --> T23
    
    T17 --> T24[T24: Web Speech Client Hook]
    T23 --> T24
    
    T18 --> T25[T25: Client Audio Playback Queue]
    T23 --> T25
    
    T02 --> T26[T26: pg_dump System Backup & Restore]
    T03 --> T26
    
    T18 --> T27[T27: BIP39 Mnemonic Onboarding Screen]
    T39 --> T27
    
    T02 --> T31
    T03 --> T31
    T10 --> T31
    T09b --> T31
    
    T81 --> T33[T33: Active Abstention Waiver PDF Receipt & Email]
    T12 --> T33
    T14 --> T33
    T37 --> T33
    
    T81 --> T16[T16: FastAPI Keepsake & Finalization Router]
    
    T02 --> T82[T82: Hash Chain Verification Tool]
    T03 --> T82
    
    T02 --> T83[T83: Mediation Chat History API]
    T03 --> T83
    T08 --> T83
    T10 --> T83
    
    T02 --> T34[T34: Executor ID Verification State Transition API]
    T03 --> T34
    T10 --> T34
    T11 --> T34
    T13 --> T34
    T31 --> T34
    T37 --> T34
    T09b --> T34
    
    T18 --> T35[T35: Executor Force Allocation Console UI]
    T20 --> T35
    T44[T44: Session Override API] --> T35
    
    T10 --> T36[T36: AB 2013 Model Transparency API & Modal]
    T18 --> T36
    T20 --> T36

    T02 --> T39[T39: Admin Setup & Session Creation API]
    T03 --> T39
    T10 --> T39

    T02 --> T40[T40: Asset Deletion API]
    T10 --> T40
    T11 --> T40

    T02 --> T41[T41: Admin Audio Story Upload & Delete API]
    T09b --> T41
    T10 --> T41
    T11 --> T41

    T02 --> T42[T42: Support Request & Help CRUD API]
    T10 --> T42
    T38 --> T42

    T02 --> T43[T43: Custom FAQ CRUD API]
    T10 --> T43
    T38 --> T43

    T02 --> T44
    T07a --> T44
    T08 --> T44
    T10 --> T44
    T12 --> T44

    T17 --> T45[T45: Admin Voice Recorder Widget]
    T18 --> T45
    T41 --> T45

    T17 --> T46[T46: Semantic Search UI]
    T18 --> T46

    T17 --> T47[T47: FAQ/Help UI Components]
    T18 --> T47
    T43 --> T47

    T17 --> T48[T48: Session Announcement UI Components]
    T18 --> T48
    T37 --> T48

    T17 --> T51[T51: Active Abstention Waiver UI Components]
    T18 --> T51
    T20 --> T51
    T33 --> T51

    T02 --> T49[T49: Secure Session Purge]
    T13 --> T49
    T26 --> T49
    T55 --> T49
    T09b --> T49

    T17 --> T52[T52: Admin Inventory Dashboard UI]
    T18 --> T52
    T11 --> T52

    T17 --> T53[T53: Admin Session Control UI]
    T18 --> T53
    T13 --> T53
    T34 --> T53
    T37 --> T53
    T16 --> T53

    T17 --> T54[T54: Admin Onboarding & Credentials Setup UI]
    T18 --> T54
    T39 --> T54
    T27 --> T54

    T02 --> T55[T55: FastAPI Heir GDPR Erasure Router]
    T08 --> T55
    T10 --> T55
    T12 --> T55
    T13 --> T55
    T31 --> T55
    T09b --> T55

    T18 --> T56[T56: BIP39 Mnemonic Restore Panel]
    T26 --> T56

    T02 --> T57[T57: FastAPI GDPR Data Portability API]
    T03 --> T57
    T10 --> T57
    T12 --> T57
    T13 --> T57
    T42 --> T57

    T17 --> T58[T58: GDPR Data Portability UI Button]
    T18 --> T58
    T57 --> T58

    T17 --> T59[T59: GDPR Account Deletion UI Drawer]
    T18 --> T59
    T55 --> T59

    T02 --> T60[T60: Admin Heir Deletion API]
    T03 --> T60
    T10 --> T60
    T11 --> T60
    T13 --> T60
    T31 --> T60
    T09b --> T60

    T02 --> T64[T64: Asset Pre-Allocation API]
    T10 --> T64
    T11 --> T64

    T02 --> T65[T65: Background Invite Expiration Scheduler]
    T13 --> T65

    T17 --> T61[T61: Nginx & Production Build Setup]
    T18 --> T61
    T19 --> T61
    T73 --> T61
    
    T61 --> T74[T74: Cloudflare Tunnel & Public Exposure Setup]

    T02 --> T28a-1[T28a-1: Backend Tests — Phase 1 Scope]
    T03 --> T28a-1
    T04 --> T28a-1
    T38 --> T28a-1
    
    T28a-1 --> T28a-2[T28a-2: Backend Tests — Phase 2 Scope]
    T05 --> T28a-2
    T07a --> T28a-2
    T08 --> T28a-2
    T21 --> T28a-2
    T50 --> T28a-2
    T63 --> T28a-2
    
    T28a-2 --> T28a-3[T28a-3: Backend Tests — Phase 3 Scope]
    T09a --> T28a-3
    T09b --> T28a-3
    T10 --> T28a-3
    T11 --> T28a-3
    T13 --> T28a-3
    T31 --> T28a-3
    T34 --> T28a-3
    T37 --> T28a-3
    T39 --> T28a-3
    T40 --> T28a-3
    T41 --> T28a-3
    T42 --> T28a-3
    T43 --> T28a-3
    T60 --> T28a-3
    T64 --> T28a-3
    T65 --> T28a-3
    T73 --> T28a-3

    T12 --> T28b[T28b: Backend Tests — Phases 4-5 Scope]
    T14 --> T28b
    T15 --> T28b
    T16 --> T28b
    T33 --> T28b
    T55 --> T28b
    T57 --> T28b
    T70 --> T28b
    T71 --> T28b

    T21a --> T28c[T28c: Backend Tests — Phase 6-7 Scope]
    T21 --> T28c
    T22 --> T28c
    T26 --> T28c
    T36 --> T28c
    T61 --> T28c
    T72[T72: Unauthenticated System Restore Gate Design] --> T28c
    T73 --> T28c
    T74 --> T28c
    
    T17 --> T29[T29: Frontend Unit & Integration Tests]
    T18 --> T29
    T19 --> T29
    T20 --> T29
    T23 --> T29
    T24 --> T29
    T25 --> T29
    T27 --> T29
    T32 --> T29
    T35 --> T29
    T36 --> T29
    T45 --> T29
    T46 --> T29
    T47 --> T29
    T48 --> T29
    T51 --> T29
    T52 --> T29
    T53 --> T29
    T54 --> T29
    T56 --> T29
    T58 --> T29
    T59 --> T29
    T66[T66: Family Memories & Stories UI Component] --> T29
    T67[T67: Admin "Inspect ID" Modal Component] --> T29
    T68[T68: Heir "Request Help" Modal Component] --> T29
    T69[T69: Auto-Balance Points Button UI] --> T29
    T73_UI --> T29

    T17 --> T66
    T18 --> T66
    
    T17 --> T67
    T18 --> T67
    T34 --> T67
    
    T17 --> T68
    T18 --> T68
    T42 --> T68
    
    T17 --> T69
    T18 --> T69

    T14 --> T70
    T15 --> T70

    T13 --> T71
    T65 --> T71

    T03 --> T72
    T10 --> T72
    T26 --> T72
    T73 --> T72
    
    T28a-1 --> T30[T30: E2E Compliance Validation]
    T28a-2 --> T30
    T28a-3 --> T30
    T28b --> T30
    T28c --> T30
    T29 --> T30
