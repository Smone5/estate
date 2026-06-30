# Phase 2: Local AI Compute & LangGraph Orchestration

## Phase Objective
Build the dual-brain LangGraph state machine, Ollama system integrations, Microsoft Presidio PII redaction pipeline, infrastructure services (Langfuse container setup, rate limiting), and the local Kokoro-82M ONNX speech synthesis engine. Write incremental tests for these nodes. Note: A 3 to 5 business day schedule buffer is explicitly injected between Phase 2 and Phase 3 to calibrate local model latency, memory headroom, and resolve connection timeout thresholds. Task T63 (Pi 5 memory profiling) must complete before Phase 3 begins to validate model selection. Additionally, a 1 business day hardware provisioning and network download buffer is injected prior to Phase 2 to prepare local networks and sequence model weight pulls (~19.5GB total) safely. T28a-2 (Phase 2 partial test gate) runs at end of Phase 2 and gates progression to Phase 3.

## Technical Specifications References
* [LangGraph State Machine Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_langgraph.md)
* [Backend System Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_backend.md)
* [Compliance & Privacy Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_compliance.md)

## Detailed Requirements & Architecture
1. **Microsoft Presidio Scrubbing Engine**:
   * Configure the Microsoft Presidio `AnalyzerEngine` and `AnonymizerEngine` to scrub personally identifiable info (PII) before LLM ingestion.
   * Target Entities: `PERSON`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `LOCATION`, `US_SSN`, and `IP_ADDRESS`.
   * Configure the custom mapping to replace matching segments with generic labels matching Presidio outputs (e.g. `<PERSON>`, `<LOCATION>`).
   * **Node Ingest Contract**: The `INGEST_PII` node must write the raw input text to `chat_messages.message_text` (encrypted at rest via `EncryptedJSON` Fernet decorator) and the anonymized version in plain text to `chat_messages.scrubbed_text` for context indexing.
2. **LangGraph State Schema**:
   * Define the `MediationState` container subclassing `TypedDict` in `app/graph.py` containing:
     * `session_id`, `heir_id`, `input_text`, `scrubbed_text`, `retrieved_context`.
     * `assets` (list, aggregated using `operator.add`), `valuations` (list of Pydantic models).
     * `chat_history` (list of messages), `is_paused`, `is_deadlocked`, `audit_trail`, `loopback_count`, `critique_loopback_count`, `correction_instruction`.
3. **Dual-Brain Model Nodes**:
   * **Smart Routing**: Program the `ROUTER_NODE` using a zero-shot intent classifier template on Ollama's `qwen3:8b` (temperature: 0.0) mapping user intent to `CHAT_MEDIATION`, `VALUATION_SUBMISSION`, or `ADMIN_OVERRIDE`.
   * **RAG Context Retrieval**: Configure `RETRIEVE_RAG` to query the database using cosine vector distances. Find matching live assets, join related shared stories (where `is_reasoning_shared = true` or `heir_id = current_heir_id`), and format them into structured markdown context.
   * **Fast System 1 Mediator**: Build the prompt template for `FAST_MEDIATE_NODE` using `qwen3:8b`. Enforce active listening warmth, reference the RAG context, and forbid ownership promises or financial math commitments.
   * **Slow System 2 Critique Loopback**: Develop `SLOW_CRITIQUE_NODE` using `qwen3:14b` (temperature: 0.0). Audit Fast Mediator responses for promises or math commitments. If compliant, stream output. If a violation is found:
     * If `critique_loopback_count <= 2`: increment the loopback count, write the violation detail into `correction_instruction`, and loopback to `FAST_MEDIATE_NODE`.
     * If `critique_loopback_count > 2`: output a pre-defined compliance fallback message.
4. **Persistent State Checkpointer**:
   * Instantiate the graph using PostgreSQL checkpointer persistence (`PostgresSaver`) to record state histories and resume active threads dynamically.
5. **Rate Limiting Middleware (T73)**:
   * Implement FastAPI rate limiting middleware (using slowapi or similar) and configure Nginx `limit_req` zones per Backend Spec §12.1. Protects all public endpoints against abuse. Required by T72 (unauthenticated restore gate) in Phase 7.

## Phase Checklist & Tasks

### [x] Task T05: Microsoft Presidio PII Scrubbing
* **Objective**: Initialize Presidio engines, add all six entity recognizers, and implement node scrubbing.
* **Verification**: Verify that sentences with names, emails, IPs, or location addresses are correctly scrubbed into generic brackets.

### [x] Task T06a: Ollama Model Downloads (Network-Bound)
* **Objective**: Pull Ollama model weights from the registry: `qwen3:8b` (~5.2GB), `qwen3:14b` (~9.3GB), `qwen3-vl:8b` (~6.1GB), and `nomic-embed-text` (~274MB). Estimated wall time: 30 min–4 hours depending on bandwidth. Run this **first** in Phase 2 so it can execute while T05 and T50 are being developed.
* **Verification**: Run `ollama list` and assert all four models are present.

### [x] Task T06b: Ollama Configuration & Integration
* **Objective**: Configure backend `.env` variables pointing to Ollama endpoint, test model reachability via the Ollama Python client, and verify basic inference responses from each model.
* **Verification**: Send a test prompt to each model and confirm a valid text response is returned within expected timeouts. Depends on T06a.

### [x] Task T21a: Kokoro ONNX Model Download
* **Objective**: Download the Kokoro-82M ONNX model binary (~2.5GB) and `voices.json` from the Hugging Face repository. Configure Docker volume mount to `/app/models/`. **Note: Depend on T06a to force sequential execution and avoid Pi 5 link saturation.**
* **Verification**: Verify that model files exist in the mounted models directory. Depends on T06a.

### [x] Task T21: Kokoro-82M TTS & soundfile WAV Encoder
* **Objective**: Configure the ONNX CPU thread-limited speech runner, soundfile base64 WAV encoder, and configure system-level `libsndfile` dependencies in the backend. Add startup validation guard that verifies model files exist and are readable at boot; if missing, emit critical WARNING log and gracefully degrade (WebSocket audio chunks omitted, text-only chat proceeds). **No database dependency.**
* **Verification**: Verify that calling the helper returns base64-encoded WAV files. Verify that booting with missing model files logs a critical warning and the system starts in text-only degraded mode. Depends on T21a.

### [x] Task T50: LLM Provider Abstraction Layer & Ollama Health-Check
* **Objective**: Implement unified LLM factory (`app/services/llm_provider.py`) abstracting LLM calls to support Ollama, OpenAI, Anthropic, and Google Gemini. Includes Ollama health-check polling with automatic connection retry/probe logic to prevent transient Ollama restarts from crashing the LangGraph workflow. Configure Langfuse/Langtrace self-hosted tracing observability. **NOTE: The former T62 (Ollama Health-Startup Probe) has been consolidated into T50 — the health-check is a sub-feature of the provider factory, not a separate sequential task.** Also strips reasoning/"thinking" tokens (Qwen3 `<think>...</think>`, Gemma `<\|channel>thought...<channel\|>`) from raw model output via a shared `_strip_thinking_tokens()` helper applied uniformly across `generate_text`, `generate_structured`, and `generate_vision`, so thinking-capable model families never leak reasoning text into parsed JSON or chat output. Decouples the LLM and Vision purposes (`LLM_PROVIDER`/`FAST_THINKER_MODEL` vs. `VISION_PROVIDER`/`VISION_MODEL`) so an Executor can point both at the same multimodal model string, or keep a dedicated vision-only model — the abstraction does not assume one or the other.
* **Verification**: Instantiate the service and mock API calls to each provider, verifying text, vision, structured JSON, and embedding outputs under the provider factory. Simulate an Ollama outage and verify that retry logs fire without crashing the provider. Verify thinking tokens are stripped from output across all three generation paths for both Qwen3-style and Gemma-style tag formats.

### [x] Task T50a: Admin LLM Connection Test Endpoint & UI
* **Objective**: Add `POST /api/admin/settings/test-connection` (Admin-only, 10/minute rate limit) letting an Executor fire one minimal real call through `LLMProvider` for a chosen purpose (`fast`/`slow`/`vision`/`embedding`/`pricing`), using unsaved draft provider/model/credential values supplied as temporary `os.environ` overrides — never persisted to `app_settings`, restored in a `finally` block regardless of outcome. Rejects unknown `purpose` values and override keys outside the `llm` section of `SETTINGS_REGISTRY` with `400`. Always returns `200 OK` with `{success, detail/error, elapsed_ms}` — provider/auth/timeout failures are caught and reported in the body, never surfaced as an unhandled `500`. Adds a "Test Connection" button inside each purpose card in `AdminSettingsPanel.jsx`. Depends on T50, T54.
* **Verification**: Assert `400` for an unknown purpose and for a non-`llm` override key. Mock `LLMProvider` and assert a successful test returns `200` with `success: true` and `elapsed_ms` present. Mock a `RuntimeError` from the provider and assert it still returns `200` with `success: false` (not `500`). Assert `os.environ` overrides are restored after the request. In the frontend, assert each purpose card has a "Test Connection" button that sends current draft (not saved) values as overrides and renders the correct ✓/✗ result text.

### [x] Task T50b: Per-Purpose Independent LLM Provider/Model/Credentials
* **Objective**: Extend `llm_provider.py` so every AI purpose (`fast`, `slow`, `vision`, `embedding`, `pricing`) has its own fully independent provider, model, API key, and base URL environment variables (see Backend Spec §2.1.1 for the full env var table). `_provider_for_key(model_key)` dispatches to the right provider per purpose. `_credentials_for_key(model_key)` returns per-purpose `api_key`/`api_base` overrides passed to LiteLLM. Fallbacks: `FAST_PROVIDER`/`SLOW_PROVIDER` fall back to `LLM_PROVIDER`; `PRICING_PROVIDER` falls back to `VISION_PROVIDER`. Add all new keys (`FAST_*`, `SLOW_*`, `PRICING_*`) to `SETTINGS_REGISTRY`; add `PRICING_` to `_LLM_RELOAD_PREFIXES`. Depends on T50.
* **Verification**: Assert that setting `FAST_API_KEY` does not affect vision calls. Assert that omitting `PRICING_PROVIDER` causes pricing calls to use the vision provider. Assert `SETTINGS_REGISTRY` contains all per-purpose key names. Assert `_LLM_RELOAD_PREFIXES` includes `PRICING_`.

### [x] Task T50c: AI Keepsake Detail Generation Endpoint
* **Objective**: Implement `POST /api/assets/{asset_id}/generate-details` (Admin-only). Performs two-step AI generation: (1) vision call with `response_format=AssetListingResponse` (Pydantic model with title, category, item_overview, specifications, condition_report, keywords, sentiment_tags, dimensions), `max_tokens=4096`, using `MODEL_KEY_VISION`; (2) separate pricing-only vision call with `response_format=ValuationEstimate` (valuation_min, valuation_max, valuation_basis), using `MODEL_KEY_PRICING`. Step 2 is non-fatal — if it fails, Step 1 results are still returned with null pricing fields. Endpoint does NOT write to the database. See Backend Spec §9.2 for full contract. Depends on T50b, T11.
* **Verification**: Mock vision provider and assert Step 1 fields are populated in the response. Mock pricing provider to raise an exception and assert the response still returns Step 1 fields with null pricing fields. Assert the endpoint does not write to the `assets` table.

### [x] Task T50d: AI Feedback / Human Verification Endpoint
* **Objective**: Implement `POST /api/assets/{asset_id}/ai-feedback` (Admin-only). Accepts `{rating, comment}`, builds a snapshot of the current asset's title/description/valuation/category, and persists `{rating, comment, submitted_at, snapshot}` as JSON to `assets.ai_feedback` column. Include `ai_feedback` in all asset serialization dicts. See Backend Spec §9.2 for full contract. Depends on T11.
* **Verification**: Assert that calling the endpoint stores a JSON object in `assets.ai_feedback` with the correct fields. Assert that `GET /api/sessions/{session_id}/assets` includes `ai_feedback` for each asset.

### [x] Task T54a: AdminSettingsPanel Grouped Purpose Cards
* **Objective**: Refactor the LLM section of `AdminSettingsPanel.jsx` from a flat field list into one card per purpose (Fast, Slow, Vision, Embedding, Pricing). Each card contains: provider dropdown (with auto-fill of default model on change via `PROVIDER_DEFAULT_MODELS`), model input, API key password input, and base URL input — all in the same card. "Test Connection" button inside each card. "Shared Provider Credentials" card at the bottom for company-level fallback keys. Non-LLM tabs (smtp, storage) keep original layout. `PURPOSE_CREDENTIAL_FIELDS` maps each purpose to its per-purpose key/URL field names. Depends on T54, T50a, T50b.
* **Verification**: Assert each purpose renders as a distinct card with all four fields. Assert provider dropdown change auto-fills model input. Assert "Test Connection" sends current draft values with the correct purpose string. Assert shared credentials card does not show per-purpose key fields.

### [x] Task T52a: Admin Inventory Dashboard — AI Workflow UI
* **Objective**: Add AI generation and human verification workflow to the Edit Keepsake Details drawer in `AdminInventoryDashboard.jsx`. "✨ Generate with AI" button calls generate-details endpoint and populates form fields. `aiGeneratedAssets` Set tracks just-generated assets this session. "✓ Mark as Verified" button calls ai-feedback endpoint; `verifyingAssets` Set tracks in-progress saves. Drawer toolbar left side shows verification status banner; right side shows verify and generate buttons. AI generation failures show a dedicated modal (z-index 1300, above drawer overlay) with error detail and "No fields were changed" note — NOT the shared error state. Verify failures use an error banner rendered INSIDE the drawer toolbar. Asset cards show "✓ Human Verified" (green) or "✨ AI Generated" (amber) badges based on `ai_feedback`. Depends on T52, T50c, T50d.
* **Verification**: Assert AI error modal renders when generate-details returns a non-2xx response. Assert modal does not appear when no error occurs. Assert "✓ Human Verified" badge appears after successful ai-feedback call. Assert verify button shows spinner while verifyingAssets contains the asset ID.

### [x] Task T73: Rate Limiting Middleware
* **Objective**: Implement FastAPI rate limiting middleware (using slowapi or similar) and configure Nginx `limit_req` zones to protect all public endpoints against abuse. Required by T72 (unauthenticated restore gate) in Phase 7 and Backend Spec §12.1.
* **Verification**: Send rapid requests to a public endpoint and verify that rate limit headers are returned and excess requests receive 429 Too Many Requests responses.


### [x] Task T07a: LangGraph State Schema, Nodes & Prompt Templates
* **Objective**: Define the `MediationState` TypedDict and implement all node classes: smart intent router, Fast System 1 conversational node (with 4-sentence constraint enforced by post-generation truncation/validation), Slow System 2 critique node, RETRIEVE_RAG node, SLOW_REFLECT node, VALIDATE node, COMMIT node, and HITL_GUARD node. Compile the graph with retry policies (3 attempts, backoff). **Each node must emit structured logs at entry and exit following Backend Spec §14.2 format: `[THREAD {thread_id}] [NODE {node_name}] - {Action details}`. Implement PII Leakage Guard per Spec §14.5: only `scrubbed_text` length (never raw text) may be written to log streams. This task is model-agnostic — prompt templates and state schema are defined in the specs and do not depend on which model size is selected by T63. NOTE: Does NOT depend on T63 or T62.** Depends on T03, T04, T05, T06b, and T50.
* **Verification**: Feed mock chat messages and assert the graph transitions correctly to mediator or critique nodes. Assert that LangGraph node execution traces are successfully emitted and visible in the Langfuse dashboard. Verify that the 4-sentence constraint is enforced by a post-generation validation check (not just a prompt instruction).

### [ ] Task T07b: LangGraph Model-Specific Tuning & Concurrency Config
* **Objective**: Apply model-specific tunables (token limits, concurrency ceilings, timeout thresholds) based on T63 profiling results. Inject the validated model profile into LangGraph node configuration. **Depends on T07a and T63.**
* **Verification**: Run the graph with the T63-validated model profile and verify that all nodes respect configured token limits and timeout thresholds. Verify that concurrent heir sessions operate within the memory envelope.

### [x] Task T08: LangGraph PostgresSaver Integration
* **Objective**: Configure `PostgresSaver` in `graph.py` to persist active thread states (thread ID: `session_id:heir_id`) in PostgreSQL tables. **Must include a negative test case asserting that SqliteSaver is NOT used — verify that container restarts preserve thread state, per LangGraph Spec §7.3.**
* **Verification**: Verify that executing graph runs writes checkpoints to PostgreSQL. Verify that after a simulated container restart, thread state is recovered from PostgresSaver without data loss.

### [x] Task T63: Pi 5 Model Downscaling & Memory Profiling (CRITICAL PATH — Blocking)
* **Objective**: Evaluate Raspberry Pi 5 (8GB RAM) memory headroom under concurrent heir load. Create alternative downscaled model profiles (Fast: qwen3:1.7b, Slow: qwen3:8b, Vision: qwen3-vl:2b or qwen3-vl:4b Q4). Test Ollama memory usage, Kokoro + Postgres + FastAPI co-tenancy. Document which model combo fits within 8GB envelope. **CRITICAL: T21 (Kokoro engine setup) and T50 (LLM provider abstraction) MUST complete before T63 begins — the co-tenancy benchmark requires the Kokoro engine and LLM provider factory to be operational and loaded into memory to produce a valid memory profile. Without this dependency, the memory profile will be incomplete.** Must complete before Phase 3 begins. This task anchors the critical path between Phase 2 and Phase 3 — the phase buffer (3–5 business days) exists specifically to absorb its findings. Depends on T06b, T21, and T50. **NOTE: T63 does NOT gate T44 (Session Override API) — T44 depends on T07/T08 for the checkpointer state schema, not on the Pi 5 model size selection.**
* **Verification**: Run co-tenancy benchmark with 3 concurrent virtual heirs sending messages. Assert that total memory usage does not exceed 7.2GB (90% of 8GB) and that median inference latency stays under 5 seconds.

### [x] Task T28a-2: Backend Tests — Phase 2 Scope
* **Objective**: Write `pytest` coverage for Presidio scrubbers, Ollama provider (with health-check mock failure simulation), LangGraph nodes/workflow (T07a), PostgresSaver (including negative test that SqliteSaver is NOT used and container restarts preserve thread state, per LangGraph Spec §7.3), Kokoro TTS, LLM provider abstraction, and Pi 5 memory profiling harness. Run at end of Phase 2. **Gates progression to Phase 3.**
* **Verification**: Execute `pytest backend/tests/` and verify Phase 2 tests pass, including the SqliteSaver negative test case.

## Phase Dependency Graph
```mermaid
graph TD
    T03[T03: AES-Fernet Encryption Decorator] --> T07a[T07a: LangGraph State Schema, Nodes & Prompt Templates]
    T04[T04: Alembic Migrations & pgvector Indexing] --> T07a
    T05[T05: Microsoft Presidio PII Scrubbing] --> T07a
    T06a[T06a: Ollama Model Downloads] --> T06b[T06b: Ollama Configuration & Integration]
    T06a --> T21a[T21a: Kokoro ONNX Model Download]
    T21a --> T21[T21: Kokoro-82M TTS & soundfile WAV Encoder]
    T21 --> T63[T63: Pi 5 Model Downscaling & Memory Profiling]
    T06b --> T63
    T06b --> T50[T50: LLM Provider Abstraction & Ollama Health-Check]
    T50 --> T63
    T63 --> T07b[T07b: LangGraph Model-Specific Tuning & Concurrency Config]
    T07a --> T07b
    T06b --> T07a
    T50 --> T07a
    
    T02[T02: SQLAlchemy Models & Relations] --> T08[T08: LangGraph PostgresSaver Integration]
    T07a --> T08
    
    T50 --> T50b[T50b: Per-Purpose Provider/Model/Credentials]
    T50b --> T50a[T50a: Admin LLM Connection Test Endpoint & UI]
    T50b --> T50c[T50c: AI Keepsake Detail Generation Endpoint]
    T50b --> T50d[T50d: AI Feedback / Human Verification Endpoint]
    T50a --> T54a[T54a: AdminSettingsPanel Grouped Purpose Cards]
    T50c --> T52a[T52a: Admin Inventory Dashboard AI Workflow UI]
    T50d --> T52a

    T03 --> T28a-2[T28a-2: Backend Tests — Phase 2 Scope]
    T04 --> T28a-2
    T05 --> T28a-2
    T07a --> T28a-2
    T08 --> T28a-2
    T21 --> T28a-2
    T50 --> T28a-2
    T63 --> T28a-2
    T73[T73: Rate Limiting Middleware] --> T28a-2
    T50b --> T28a-2
    T50c --> T28a-2
    T50d --> T28a-2
