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
   * **Smart Routing**: Program the `ROUTER_NODE` using a zero-shot intent classifier template on Ollama's `qwen2.5:8b-instruct` (temperature: 0.0) mapping user intent to `CHAT_MEDIATION`, `VALUATION_SUBMISSION`, or `ADMIN_OVERRIDE`.
   * **RAG Context Retrieval**: Configure `RETRIEVE_RAG` to query the database using cosine vector distances. Find matching live assets, join related shared stories (where `is_reasoning_shared = true` or `heir_id = current_heir_id`), and format them into structured markdown context.
   * **Fast System 1 Mediator**: Build the prompt template for `FAST_MEDIATE_NODE` using `qwen2.5:8b-instruct`. Enforce active listening warmth, reference the RAG context, and forbid ownership promises or financial math commitments.
   * **Slow System 2 Critique Loopback**: Develop `SLOW_CRITIQUE_NODE` using `qwen2.5:14b-instruct` (temperature: 0.0). Audit Fast Mediator responses for promises or math commitments. If compliant, stream output. If a violation is found:
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
* **Objective**: Pull Ollama model weights from the registry: `qwen2.5:8b-instruct` (~4.7GB), `qwen2.5:14b-instruct` (~8.2GB), `llava:7b` (~3.9GB), and `nomic-embed-text` (~274MB). Estimated wall time: 30 min–4 hours depending on bandwidth. Run this **first** in Phase 2 so it can execute while T05 and T50 are being developed.
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
* **Objective**: Implement unified LLM factory (`app/services/llm_provider.py`) abstracting LLM calls to support Ollama, OpenAI, Anthropic, and Google Gemini. Includes Ollama health-check polling with automatic connection retry/probe logic to prevent transient Ollama restarts from crashing the LangGraph workflow. Configure Langfuse/Langtrace self-hosted tracing observability. **NOTE: The former T62 (Ollama Health-Startup Probe) has been consolidated into T50 — the health-check is a sub-feature of the provider factory, not a separate sequential task.**
* **Verification**: Instantiate the service and mock API calls to each provider, verifying text, vision, structured JSON, and embedding outputs under the provider factory. Simulate an Ollama outage and verify that retry logs fire without crashing the provider.

### [ ] Task T73: Rate Limiting Middleware
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

### [ ] Task T63: Pi 5 Model Downscaling & Memory Profiling (CRITICAL PATH — Blocking)
* **Objective**: Evaluate Raspberry Pi 5 (8GB RAM) memory headroom under concurrent heir load. Create alternative downscaled model profiles (Fast: qwen2.5:3b-instruct, Slow: qwen2.5:8b-instruct, Vision: moondream or llava:7b Q4). Test Ollama memory usage, Kokoro + Postgres + FastAPI co-tenancy. Document which model combo fits within 8GB envelope. **CRITICAL: T21 (Kokoro engine setup) and T50 (LLM provider abstraction) MUST complete before T63 begins — the co-tenancy benchmark requires the Kokoro engine and LLM provider factory to be operational and loaded into memory to produce a valid memory profile. Without this dependency, the memory profile will be incomplete.** Must complete before Phase 3 begins. This task anchors the critical path between Phase 2 and Phase 3 — the phase buffer (3–5 business days) exists specifically to absorb its findings. Depends on T06b, T21, and T50. **NOTE: T63 does NOT gate T44 (Session Override API) — T44 depends on T07/T08 for the checkpointer state schema, not on the Pi 5 model size selection.**
* **Verification**: Run co-tenancy benchmark with 3 concurrent virtual heirs sending messages. Assert that total memory usage does not exceed 7.2GB (90% of 8GB) and that median inference latency stays under 5 seconds.

### [ ] Task T28a-2: Backend Tests — Phase 2 Scope
* **Objective**: Write `pytest` coverage for Presidio scrubbers, Ollama provider (with health-check mock failure simulation), LangGraph nodes/workflow (T07a), PostgresSaver (including negative test that SqliteSaver is NOT used and container restarts preserve thread state), Kokoro TTS, LLM provider abstraction, and Pi 5 memory profiling harness. Run at end of Phase 2. **Gates progression to Phase 3.**
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
    
    T03 --> T28a-2[T28a-2: Backend Tests — Phase 2 Scope]
    T04 --> T28a-2
    T05 --> T28a-2
    T07a --> T28a-2
    T08 --> T28a-2
    T21 --> T28a-2
    T50 --> T28a-2
    T63 --> T28a-2
    T73[T73: Rate Limiting Middleware] --> T28a-2
