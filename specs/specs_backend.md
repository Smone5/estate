# Estate Steward: Backend System Specification (v4.1)

This document contains the backend-specific engineering specifications, database definitions, logic state workflows, and security layers.

---

## 1. System Philosophy (The Dual-Brain Architecture)

We employ a Kahneman-inspired System 1 / System 2 architecture to balance responsiveness with rigor:

*   **System 1 (Fast Thinker)**: Handles real-time, low-latency mediation chat. Empathic, conversational, and lightweight.
    *   **Model**: Qwen-2.5-8B-Instruct (Quantized GGUF hosted on Ollama).
    *   **Focus**: Latency, Sentiment Analysis, Active Listening.
*   **System 2 (Slow Thinker)**: Handles complex logic, math validation, audit generation, and RAG retrieval.
    *   **Model**: Qwen-2.5-14B-Instruct (`qwen2.5:14b-instruct` hosted on Ollama).
    *   **Focus**: Fairness constraints, Hash-chaining, PII scrubbing verification, Conflict resolution.

---

## 2. Technology Stack (Backend & FOSS)

### 2.0 Python Environment Setup (uv)

The backend uses `uv` as its Python package manager. Before any development, initialize the environment:

```bash
cd backend
uv sync
source .venv/bin/activate
```

The `uv sync` command reads `backend/pyproject.toml` and installs all declared dependencies into an isolated `.venv` directory. This must be done before running any backend tests, starting the FastAPI server, or executing any Python scripts.

| Layer | Technology | Role |
| :--- | :--- | :--- |
| **Logic Orchestration** | LangGraph | Orchestrates the state machine between Fast/Slow thinkers. |
| **LLM Abstraction Layer** | Custom Factory (`app/services/llm_provider.py`) | Decouples prompts and logic from LLM backends to support Ollama, OpenAI, Anthropic, or Google. |
| **Fast Thinker** | Ollama/Qwen-2.5-8B (Local fallback) | Real-time chat (Sub-500ms token generation). |
| **Slow Thinker** | Ollama/Qwen-2.5-14B (Local fallback) | Complex reasoning, Math, and Audit verification. |
| **Backend API Gateway** | FastAPI | Async Python orchestrator and WebSocket router. |
| **Database** | Postgres + pgvector | Primary database supporting vector search; sensitive fields encrypted via SQLAlchemy field encryption. |
| **Vision & RAG** | Ollama (llava, nomic-embed-text) (Local fallback) | Vision OCR for asset uploads (`llava`) and embedding for RAG search (`nomic-embed-text`). |
| **Observability** | Langfuse / Langtrace | Self-hosted tracing (Langfuse) and OpenTelemetry SDK (Langtrace) to monitor LangGraph. |
| **Privacy / PII** | Microsoft Presidio | Context-aware PII scrubbing middleware. |
| **Fair Division Math** | Fairpyx | Fair division logic utilizing Maximum Nash Welfare (MNW) scoring. |
| **Email Deliverability** | Python standard / aiosmtplib | Async SMTP relay for emailing PDF reports. |
| **Mnemonic Phrase Key** | `mnemonic` (Python package) | Derives and validates BIP39 seed phrases for encryption key recovery. |

### 2.1 Configurable LLM Abstraction Layer

To enable seamless switching between open-source local-first compute and cloud LLM APIs, all node prompts, vision extractions, and embedding computations are routed through a unified LLM service factory (`app/services/llm_provider.py`). The active provider is loaded from environment variables on startup:

1.  **Supported Providers**:
    *   `LLM_PROVIDER`: `'ollama'` (default) | `'openai'` | `'anthropic'` | `'google'` (Vertex AI / Google AI Studio).
    *   `EMBEDDING_PROVIDER`: `'ollama'` (default) | `'openai'` | `'google'`.
    *   `VISION_PROVIDER`: `'ollama'` (default) | `'openai'` | `'google'` | `'anthropic'`.
2.  **Configured Models**:
    *   `FAST_THINKER_MODEL`: e.g. `qwen2.5:8b-instruct` (Ollama), `gpt-4o-mini` (OpenAI), `claude-3-5-haiku` (Anthropic), `gemini-2.5-flash` (Google).
    *   `SLOW_THINKER_MODEL`: e.g. `qwen2.5:14b-instruct` (Ollama), `gpt-4o` (OpenAI), `claude-3-5-sonnet` (Anthropic), `gemini-2.5-pro` (Google).
    *   `VISION_MODEL`: e.g. `llava:7b` (Ollama), `gpt-4o-mini` (OpenAI), `claude-3-5-sonnet` (Anthropic), `gemini-2.5-flash` (Google).
    *   `EMBEDDING_MODEL`: e.g. `nomic-embed-text` (Ollama), `text-embedding-3-small` (OpenAI), `text-embedding-004` (Google).
3.  **Unified API Interface**:
    *   `generate_text(model_key, system_prompt, user_input, temperature, history=None) -> str`
    *   `generate_structured(model_key, system_prompt, user_input, response_model, temperature) -> BaseModel` (uses Pydantic schema schemas to force JSON schemas).
    *   `generate_vision(model_key, image_bytes, prompt) -> str` (OCR extractions).
    *   `get_embeddings(model_key, text) -> List[float]` (returns dense vector matching the active model's dimension size).

4.  **Local-First / Cost-Saving Fallback**:
    If external API credentials are omitted or `LLM_PROVIDER=ollama`, the backend defaults to local Ollama endpoints (`OLLAMA_BASE_URL`). When switching to external APIs, the host must configure the matching provider API keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GEMINI_API_KEY`).


---

## 3. Data Architecture (Database Schema & Transactions)

The system database architecture, entity-relationship tables, pgvector similarity indices, transparent field-level encryption, and pessimistic concurrency controls are documented in:

*   ### [Database Schema & Transaction Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_db.md)

Refer to the linked specification for complete database definitions, columns, constraints, indexing, and transaction rules.

---

## 4. Logic & Data Contracts (Pydantic / TypedDict)

All backend LLM inputs and outputs are strictly validated via Pydantic schemas to prevent hallucination.

```python
import operator
from typing import List, Annotated, TypedDict, Optional, Dict
from pydantic import BaseModel, Field

class JWTPayload(BaseModel):
    user_id: str
    username: str
    role: str = Field(..., pattern="^(ADMIN|HEIR)$")
    session_id: Optional[str] = None  # None for Admins
    exp: int

class SharedMemorySchema(BaseModel):
    heir_username: str
    reasoning: str

class AssetSchema(BaseModel):
    id: str
    session_id: str
    title: str = Field(..., max_length=150)
    description: str
    category: str = Field(..., pattern="^(Jewelry|Furniture|Art|Other)$")
    valuation_min: float
    valuation_max: float
    valuation_source: Optional[str] = None
    sentiment_tag: str
    image_uri: str
    audio_uri: Optional[str] = None
    status: str = Field(..., pattern="^(STAGED|LIVE|PRE_ALLOCATED|DISTRIBUTED)$")
    ocr_status: Optional[str] = Field(None, pattern="^(PROCESSING|COMPLETED|FAILED)$")
    description_json: Optional[Dict[str, str]] = None
    allocated_to_id: Optional[str] = None
    shared_memories: List[SharedMemorySchema] = []

class ValuationSchema(BaseModel):
    asset_id: str
    heir_id: str
    points: int = Field(..., ge=0, le=1000)
    reasoning: Optional[str] = None
    is_reasoning_shared: bool = False

class ChatMessageSchema(BaseModel):
    id: str
    session_id: str
    heir_id: str
    sender: str = Field(..., pattern="^(heir|agent)$")
    message_text: str
    scrubbed_text: str
    created_at: str

class SupportRequestCreate(BaseModel):
    message: str = Field(..., min_length=5, max_length=1000, description="Heir support or assistance text")

class SupportRequestResponse(BaseModel):
    id: str
    username: str
    message: str
    status: str = Field(..., pattern="^(OPEN|RESOLVED)$")
    created_at: str

class AdminOverrideRequest(BaseModel):
    asset_id: str
    allocated_to_id: str
    reason: str = Field(..., min_length=5, max_length=250, description="Executor's reason/fiduciary basis for override")

class FAQSchema(BaseModel):
    id: str
    question: str
    answer: str

class CustomFAQSchema(BaseModel):
    id: str
    session_id: str
    question: str
    answer: str
    created_at: str

class SessionResponse(BaseModel):
    id: str
    title: str
    status: str = Field(..., pattern="^(SETUP|ACTIVE|LOCKED|FINALIZED)$")
    is_paused: bool
    paused_at: Optional[str] = None
    is_deadlocked: bool
    announcement: Optional[str] = None
    announcement_updated_at: Optional[str] = None
    deadline: Optional[str] = None
    created_at: str

class HeirResponse(BaseModel):
    id: str
    username: str
    legal_first_name: Optional[str] = None
    legal_middle_name: Optional[str] = None
    legal_last_name: Optional[str] = None
    relationship_to_decedent: Optional[str] = None
    date_of_birth: Optional[str] = None
    identity_verified: bool
    id_scan_uri: Optional[str] = None
    role: str = Field(..., pattern="^(HEIR)$")
    email: Optional[str] = None
    phone: Optional[str] = None
    physical_address: Optional[str] = None
    invite_token: Optional[str] = None
    invite_token_expires_at: Optional[str] = None
    invite_token_used: bool
    consent_accepted: bool
    age_verified: bool
    consent_timestamp: Optional[str] = None
    is_submitted: bool
    submitted_at: Optional[str] = None
    draft_version: int
    status: str = Field(..., pattern="^(PENDING|PROFILE_HOLD|ACTIVE|SUBMITTED|ABSTAINED|EXPIRED_NON_PARTICIPATING)$")
    created_at: str
    invitation_dispatched_at: Optional[str] = None

class ValuationDraftSchema(BaseModel):
    asset_id: str
    points: int = Field(..., ge=0, le=1000)
    reasoning: Optional[str] = None
    is_reasoning_shared: bool = False

class ValuationSubmitRequest(BaseModel):
    valuations: List[ValuationDraftSchema]

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=100)

class HeirCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    legal_first_name: str = Field(..., min_length=1, max_length=50)
    legal_middle_name: Optional[str] = None
    legal_last_name: str = Field(..., min_length=1, max_length=100)
    relationship_to_decedent: Optional[str] = None
    date_of_birth: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    physical_address: Optional[str] = None
    expiration_days: Optional[int] = 14

class AnnouncementRequest(BaseModel):
    announcement: Optional[str] = None

class InviteTokenRenewRequest(BaseModel):
    expiration_days: Optional[int] = 14

class KeepsakeEmailRequest(BaseModel):
    heir_id: Optional[str] = None

class HeirProfileUpdate(BaseModel):
    legal_first_name: str = Field(..., min_length=1, max_length=50)
    legal_middle_name: Optional[str] = None
    legal_last_name: str = Field(..., min_length=1, max_length=100)
    relationship_to_decedent: str = Field(..., min_length=1, max_length=50)
    date_of_birth: str = Field(..., pattern="^\\d{4}-\\d{2}-\\d{2}$")
    email: Optional[str] = None
    phone: Optional[str] = None
    physical_address: Optional[str] = None

class InviteVerifyRequest(BaseModel):
    token: str
    consent_accepted: bool
    age_verified: bool
    legal_first_name: str = Field(..., min_length=1, max_length=50)
    legal_middle_name: Optional[str] = None
    legal_last_name: str = Field(..., min_length=1, max_length=100)
    relationship_to_decedent: str = Field(..., min_length=1, max_length=50)
    date_of_birth: str = Field(..., pattern="^\\d{4}-\\d{2}-\\d{2}$")

class AbstainRequest(BaseModel):
    legal_name_signature: str = Field(..., min_length=3, max_length=200)

class VerifyIdentityRequest(BaseModel):
    action: str = Field(..., pattern="^(approve|reject)$")
    rejection_reason: Optional[str] = Field(None, min_length=3, max_length=250)

class FAQCreate(BaseModel):
    question: str = Field(..., min_length=5)
    answer: str = Field(..., min_length=5)

class InviteLoginRequest(BaseModel):
    token: str

class AssetPreAllocateRequest(BaseModel):
    allocated_to_id: str

class MediationState(TypedDict):
    session_id: str
    heir_id: str
    input_text: str
    scrubbed_text: str
    retrieved_context: Optional[str]
    assets: Annotated[List[AssetSchema], operator.add]
    valuations: List[ValuationSchema]
    chat_history: List[Dict[str, str]]
    is_paused: bool
    is_deadlocked: bool
    audit_trail: List[str]
    loopback_count: int
    correction_instruction: Optional[str]
```

---

## 5. Operational Workflow (LangGraph State Machine)

The backend state machine nodes, routing rules, state schema, voice transcription ingestion flow, and Human-in-the-Loop (HITL) interrupt logic are modularized into a dedicated specification document:

*   ### [LangGraph State Machine Specification](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_langgraph.md)

Refer to the linked document for the complete definition of operational states, retry loopbacks, and resumption overrides.

---

## 6. Security & Integrity Layer

### 6.1 Tamper-Proof Hash Chaining
```python
import hashlib

def generate_hash(row_id: int, event_type: str, scrubbed_snapshot_json: str, prev_hash: str) -> str:
    # Concatenate the fields deterministically using a colon delimiter
    raw_data = f"{row_id}:{event_type}:{scrubbed_snapshot_json}:{prev_hash}"
    return hashlib.sha256(raw_data.encode()).hexdigest()
```
* Genesis hash for the initial record: `0` repeated 64 times.

*   **Cryptographic Stability**: The `scrubbed_snapshot_json` is a serialized, key-sorted, compact JSON representation of the `state_snapshot` where all user PII fields (such as names, emails, addresses, phones, and IP addresses) are scrubbed and replaced with static `"Anonymized"` placeholders. This guarantees that subsequent GDPR Article 17 account erasures of PII from the stored `state_snapshot` do not alter the hash inputs or break the validation chain.

### 6.2 PII Scrubbing (Presidio)
*   **Scrubbed Entities**: `PERSON`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `LOCATION`, `US_SSN`, `IP_ADDRESS`. See Compliance Spec §1.3 for the canonical full entity list and rationale.

*   **Anonymizer Rule**: Text inputs are intercepted and scrubbed before sending to Ollama. Detected entities are replaced with plain bracketed type tags, e.g., `<PERSON>`, `<EMAIL_ADDRESS>`, `<PHONE_NUMBER>` — matching Microsoft Presidio's default `EntityRecognizer` output format. Do NOT prefix with `REDACTED_`; the Presidio anonymizer returns the entity type name only.

### 6.3 Authentication & Session Management
* Admins use Argon2 credentials. Heirs authenticate via a single-use UUID invite link `/invite/{token}` that grants an HTTP-only JWT cookie.

### 6.4 BIP39 Encryption Key Recovery (Paper Recovery Key)

To ensure that encrypted database backups can be restored without the original environment (`ENCRYPTION_KEY`), the system derives a **24-word BIP39 mnemonic seed phrase** from the active encryption key. This phrase serves as the offline Paper Recovery Key.

#### 6.4.1 Key Derivation Contract

The derivation uses the `mnemonic` Python library (BIP39 standard):

```python
import hashlib
from mnemonic import Mnemonic

def encryption_key_to_bip39(encryption_key_hex: str) -> str:
    """
    Convert a 32-byte (64 hex char) AES-Fernet encryption key 
    into a BIP39 mnemonic seed phrase.
    
    Args:
        encryption_key_hex: 64-character hex string from ENCRYPTION_KEY env var.
    
    Returns:
        24-word BIP39 mnemonic string (space-separated).
    """
    mnemo = Mnemonic("english")
    # BIP39 entropy for 24 words = 256 bits (32 bytes)
    key_bytes = bytes.fromhex(encryption_key_hex)
    # Validate length: Fernet keys are 32 base64-encoded bytes = 43 chars;
    # the underlying 32-byte raw key is what we pass here.
    return mnemo.to_mnemonic(key_bytes)

def bip39_to_encryption_key(mnemonic_phrase: str) -> bytes:
    """
    Recover a 32-byte AES key from a BIP39 mnemonic seed phrase.
    
    Args:
        mnemonic_phrase: 24-word BIP39 mnemonic string.
    
    Returns:
        32-byte raw key (bytes), suitable for Fernet.
    """
    mnemo = Mnemonic("english")
    if not mnemo.check(mnemonic_phrase):
        raise ValueError("Invalid BIP39 mnemonic phrase")
    # to_entropy() returns the original entropy bytes
    return mnemo.to_entropy(mnemonic_phrase)
```

**Contract Rules**:
1. **ENCRYPTION_KEY Format**: The environment variable `ENCRYPTION_KEY` must be a 43-character base64-encoded Fernet key (as generated by `cryptography.fernet.Fernet.generate_key()`). The raw 32-byte value underlying this key is what enters the BIP39 derivation.
2. **Mnemonic Generation**: Performed once at first-boot admin setup (`POST /api/setup/admin`). The 24-word phrase is displayed to the Admin and must be written down on paper to enable offline database recovery.
3. **Mnemonic Validation**: The BIP39 library's `check()` method validates the phrase (including the embedded checksum word) when recovering a backup.
4. **Backup Restoration**: During `POST /api/system/restore`, if the `ENCRYPTION_KEY` environment variable is unavailable or mismatched, the Admin can supply the 24-word recovery key to decrypt the backup archive (see Backend Spec §9.5).

#### 6.4.2 Plan Cross-Reference
- **Task T39** (Admin Setup & Session Creation API): Implements the first-boot admin route that generates and returns the BIP39 mnemonic.
- **Task T27** (BIP39 Mnemonic Onboarding Screen): Implements the UI for displaying the 24-word seed phrase.
- **Task T56** (BIP39 Mnemonic Restore Panel): Implements the recovery seed input fields for backup decryption.
- **Task T26** (pg_dump System Backup & Restore): Implements the encrypted archive creation and restoration logic that consumes the mnemonic for key recovery.
- **Spec Reference**: See DB Spec §7 (Data Safety & Redundancy Strategy) for backup/restore lifecycle requirements.

### 6.5 Phase Integration Buffer

A **3-to-5 business day schedule buffer** is explicitly injected between Phase 2 (Local AI Compute & LangGraph Orchestration) and Phase 3 (Image Processing & Backend REST API Gateways) in the implementation plan. This buffer exists because:

1. **Latency Calibration**: Phase 2 introduces Ollama model inference and Presidio scrubbing — both of which require empirical latency measurement under load on the target hardware (Raspberry Pi 5 or equivalent).
2. **Memory Headroom Testing**: The dual-brain LangGraph state machine consumes significant RAM during concurrent heir sessions. The buffer provides time to tune `MAX_WORKER_THREADS`, Kokoro thread limits, and ONNX session options to prevent OOM crashes.
3. **Connection Timeout Tuning**: Presidio's Analyzer engine and Ollama's HTTP gateway both have configurable timeout thresholds that must be validated against real-world network and hardware conditions before Phase 3 routes depend on them.
4. **No Spec Impact**: This buffer is a project scheduling measure only — it does not change any API contract, database schema, or functional requirement defined in these specifications.

**Plan Cross-Reference**: This buffer is documented in the Phase 2 plan index (`plan/phase_2_ai_orchestration.md`) and the master implementation plan (`plan/implementation_plan.md` Step 2, Phase 2 deliverables).

---

## 7. Local Text-to-Speech Voice Synthesis (Kokoro-82M)

To deliver a warm, empathic, non-robotic voice for the Mediator Agent while running 100% locally on CPU, the backend integrates the **Kokoro-82M** speech synthesis engine.

### 7.0 Model Download & File Mount Contract

The Kokoro-82M ONNX model binary (~2.5GB) and its companion voice mapping JSON are **not bundled** in the Docker image. They must be downloaded separately and mounted at runtime:

1. **Download Source**: The model file `kokoro-v0.19.onnx` and `voices.json` are available from the [Kokoro-82M Hugging Face repository](https://huggingface.co/rerender-ai/kokoro-onnx).
2. **Expected Paths** (configurable via environment variables):
   - `KOKORO_MODEL_PATH` (default: `app/models/kokoro-v0.19.onnx`)
   - `KOKORO_VOICES_PATH` (default: `app/models/voices.json`)
3. **Docker Volume Mount**: The host directory containing the downloaded ONNX binary and voices file must be bind-mounted to `/app/models/` in the backend container:
   ```yaml
   services:
     app:
       volumes:
         - ./models/kokoro:/app/models
   ```
4. **Startup Validation**: On application boot, the Kokoro service must verify that both files exist and are readable. If either is missing, a critical `WARNING` log must be emitted and the TTS service gracefully degrades (WebSocket audio chunks are omitted; text-only chat proceeds).
5. **CPU Runtime**: The ONNX model runs entirely on CPU using `onnxruntime` with `intra_op_num_threads=2` and `inter_op_num_threads=1` to prevent starvation on Raspberry Pi 5 (see §12.2).
6. **System Dependency**: The `libsndfile` system library is required by `soundfile` for WAV encoding. This must be installed in the backend Docker image (e.g. `apt-get install -y libsndfile1` in the `Dockerfile`).

**Plan Cross-Reference**: This download and configuration is tracked as **Task T21** (Kokoro-82M TTS & soundfile WAV Encoder) in the Implementation Plan. The model binary download is a network-bound step estimated at 15-45 minutes on typical broadband; the task register marks it as `High (Duration)`.

### 7.1 Library & Initialization
*   The service imports `kokoro_onnx` and utilizes an ONNX model file and its companion voice mapping JSON (e.g., `app/models/kokoro-v0.19.onnx` and `app/models/voices.json`).
*   The session configuration restricts inference threads to prevent CPU starvation:
    ```python
    import asyncio
    import onnxruntime as ort
    from kokoro_onnx import Kokoro

    sess_options = ort.SessionOptions()
    # Restrict CPU execution to 2 threads max to preserve Pi 5 database headroom
    sess_options.intra_op_num_threads = 2 
    sess_options.inter_op_num_threads = 1

    kokoro = Kokoro(
        model_path="app/models/kokoro-v0.19.onnx",
        voices_path="app/models/voices.json",
        session_options=sess_options
    )

    # Global semaphore to serialize ONNX CPU execution and prevent starvation
    tts_semaphore = asyncio.Semaphore(1)
    ```

### 7.2 Voice Configuration
*   **Calming Tone**: The mediator synthesizes speech using the `af_bella` voice (female, comforting, clear tone) or `am_adam` (male, gentle, warm).
*   **Speech Tempo**: Set to `speed = 0.95` (slightly slowed down from default to support clarity and emotional digestion).

### 7.3 WAV Encoding & Serialization
*   ONNX generates raw float32 samples at 24kHz.
*   The backend writes the samples into an in-memory WAV file buffer using the `soundfile` library:
    ```python
    import io
    import soundfile as sf
    import base64

    # Generate audio
    samples, sample_rate = kokoro.create(
        text=reply_text,
        voice="af_bella",
        speed=0.95
    )

    # Write to in-memory WAV buffer
    wav_buffer = io.BytesIO()
    sf.write(wav_buffer, samples, sample_rate, format='WAV', subtype='PCM_16')
    wav_data = wav_buffer.getvalue()

    # Convert to Base64 to transport in JSON WebSocket frame
    b64_audio = base64.b64encode(wav_data).decode('utf-8')
    ```

---

## 8. Image Preprocessing & Normalization Pipeline

To ensure the system works seamlessly with various mobile camera uploads (which are often heavy or in Apple's proprietary HEIC format) without slowing down the local Raspberry Pi 5 server, the backend employs an image normalization pipeline:

### 8.1 Library Dependencies
*   `Pillow` (PIL) for image operations.
*   `pillow-heif` to decode and convert Apple iOS HEIC/HEIF images.
*   `mnemonic` (Python library) to derive and validate 24-word BIP39 paper recovery seed phrases.
*   `google-cloud-storage` (Python GCS client) to stream and purge files when GCS storage driver is active.

### 8.2 Processing Rules
1.  **Format Conversion**: All incoming uploads (JPEG, PNG, HEIC, WebP, etc.) are decoded and converted to standard **WebP** format. HEIC images are decoded using `pillow-heif` and converted.
2.  **Strict Dimension Constraints (No Distortion)**:
    *   Large photos are scaled down to fit inside a maximum bounding box of **1200 x 1200 pixels**.
    *   The aspect ratio is strictly preserved (using Pillow's `Image.thumbnail` function), preventing the image from stretching, squishing, or cropping visual elements.
3.  **File Size Compression**:
    *   Images are saved using WebP lossy compression with a quality setting of **80%**.
    *   This reduces average file size from 5-12MB mobile capture files to 150-300KB WebP images, speeding up Nginx network load times.
4.  **Storage & Cloud Readiness (Abstracted Storage Driver)**:
    *   To support serverless stateless deployment (like Google Cloud Run or AWS Fargate) without code modifications, file storage is managed by a pluggable driver class toggled via the `STORAGE_DRIVER` environment variable:
        *   `STORAGE_DRIVER=LOCAL` (Default for Raspberry Pi): Files are saved locally to `static/uploads/` (mounted as a Docker volume) and served via Nginx.
        *   `STORAGE_DRIVER=GCS` (For Cloud Run): Files are streamed directly to a secure **Google Cloud Storage (GCS)** bucket.
    *   In both cases, files are renamed to a secure UUID (e.g. `c7b74e89-1384-4861-abdf-c6a6f1d2c673.webp`) and the database's `image_uri` stores the accessible public HTTP URL or local static path.
5.  **Pluggable Deletion Support**:
    *   To prevent orphaned file accumulation and comply with PII/security purges, the pluggable driver must implement file deletion methods:
        *   `STORAGE_DRIVER=LOCAL`: Deletes the target file from the local `/app/static/uploads/` path.
        *   `STORAGE_DRIVER=GCS`: Calls the Google Cloud Storage bucket API to delete the corresponding blob object.


---

## 9. FastAPI REST API Catalog

All administrative, session management, and verification actions are executed via strict, validated REST endpoints:

### 9.1 Session Management
*   **`POST /api/sessions`**
    *   **Access**: Admin credentials required.
    *   **Request Body**: `{"title": "string"}`
    *   **Logic**: Creates a new estate mediation session. Registers a new unique session UUID.
    *   **Response**: `{"session_id": "UUID", "title": "...", "status": "SETUP", "is_paused": false, "deadline": "ISO-8601-String"}`
*   **`GET /api/sessions/{session_id}`**
    *   **Access**: Protected (Heir or Admin).
    *   **Description**: Retrieves the active metadata and current lock/pause/deadlock status flags of the mediation session.
    *   **Response**: `SessionResponse`
*   **`GET /api/sessions/{session_id}/heirs`**
    *   **Access**: Admin credentials required.
    *   **Description**: Lists all Heirs currently registered in the session and their compliance/verification/submission statuses.
    *   **Response**: `List[HeirResponse]`
*   **`POST /api/sessions/{session_id}/heirs`**
    *   **Access**: Admin credentials required.
    *   **Request Body**: `HeirCreate`
    *   **Description**: Creates an Heir user with their display name, full legal name, relationship, date of birth, email, phone number, and physical mailing address. Generates the invitation token and sets `invite_token_expires_at` to the configured number of days from now (defaults to 14 days). If SMTP is configured, queues a background email task and sets `invitation_dispatched_at` on success.
    *   **Constraint**: Returns `400 Bad Request` if the session's status is `'LOCKED'` or `'FINALIZED'` to preserve the audit trail and prevent matrix modifications.
    *   **Response**: `{"invite_token": "UUID", "invite_url": "https://...", "username": "Heir Name"}`
*   **`POST /api/heirs/{heir_id}/invite-token`**
    *   **Access**: Admin credentials required.
    *   **Request Body**: `InviteTokenRenewRequest`
    *   **Description**: Regenerates a fresh, single-use UUID invite token for an existing Heir, resetting `invite_token_used = False` and the expiration timestamp to the configured number of days from now (defaults to 14 days). If SMTP is configured, queues a background email task and sets `invitation_dispatched_at` on success.
    *   **Constraint**: Returns `400 Bad Request` if the session's status is `'LOCKED'` or `'FINALIZED'`.
    *   **Response**: `{"invite_token": "UUID", "invite_url": "https://..."}`
*   **`POST /api/heirs/{heir_id}/send-invite`**
    *   **Access**: Admin credentials required.
    *   **Description**: Triggers a background worker to send the invitation link email to the Heir's registered email address using `aiosmtplib`.
    *   **Logic**: Sends the email asynchronously. Upon successful SMTP relay, updates the database column `invitation_dispatched_at` to the current UTC timestamp.
    *   **Constraint**: Returns `400 Bad Request` if the session's status is `'LOCKED'` or `'FINALIZED'`.
    *   **Response**: `{"status": "success", "message": "Invitation email dispatched"}`
*   **`DELETE /api/sessions/{session_id}/heirs/{heir_id}`**
    *   **Access**: Admin credentials required.
    *   **Description**: Removes the specified Heir from the session. Wipes their database entries and files.
    *   **Logic**:
        1. Queries the database for any assets in the session with `allocated_to_id == heir_id` and `status == 'PRE_ALLOCATED'`. Resets their `allocated_to_id = NULL` and transitions their status back to `'LIVE'` to prevent check constraint violations.
        2. Checks if the Heir has an active file path in `id_scan_uri`. If present, deletes the encrypted ID scan file permanently from `/app/static/uploads/identities/` disk storage.
        3. Erases all LangGraph checkpointer state database records (checkpoints, checkpoint_writes, etc.) matching this Heir's thread ID (`f"{session_id}:{heir_id}"`) to prevent orphaned PII records.
        4. Cascade deletes their row in the `users` table, erasing their chat logs, support tickets, and points valuations.
        5. Queries the `audit_logs` table for the active session. Decrypts each `state_snapshot`, identifies any nested keys or values matching the deleted Heir's `heir_id` or original legal names/contact details, replaces those values with `"Anonymized"`, re-encrypts the snapshot, and commits the updated rows to prevent historical data leakage.
    *   **Constraint**: Returns `400 Bad Request` if the session's status is `'LOCKED'` or `'FINALIZED'` to preserve the audit trail.
    *   **Response**: `{"status": "success", "message": "Heir removed, associated ID scan files deleted, checkpointer states cleared, and data cascade-deleted"}`
*   **`POST /api/sessions/{session_id}/pause`**
    *   **Access**: Admin credentials required.
    *   **Logic**: Transitions the session status column to `'LOCKED'`, sets `is_paused = True`, and updates the `paused_at` column to the current UTC timestamp in the database, freezing active points sliders and chat mediation interfaces for all heirs.
    *   **Response**: `{"session_id": "UUID", "is_paused": true}`
*   **`POST /api/sessions/{session_id}/unpause`**
    *   **Access**: Admin credentials required.
    *   **Logic**: Transitions the session status column to `'ACTIVE'`, sets `is_paused = False` in the database, and calculates the total pause duration as `current_utc_time - paused_at`. It dynamically extends both the `invite_token_expires_at` timestamp for all heirs in the session (regardless of whether they are pending or have already verified/logged in) whose deadlines are not yet passed and the session `deadline` by this total duration, ensuring no active participant has their notice window cut short by a system pause. Finally, it sets `paused_at = NULL` and commits, restoring sliders and chat interfaces.
    *   **Response**: `{"session_id": "UUID", "is_paused": false}`
*   **`POST /api/sessions/{session_id}/finalize`**
    *   **Access**: Admin credentials required.
    *   **Description**: Halts the session, triggers the `fairpyx` solver matrix calculation (excluding abstained/expired users), saves the allocation results, and seals the audit block.
        *   **Zero-Utility Starvation Bypass**: If the number of active, non-abstained Heirs who have not been assigned any `'PRE_ALLOCATED'` assets is greater than the number of published `'LIVE'` assets, the backend must dynamically disable the "Zero-Utility Starvation" check (as it is mathematically impossible for all remaining heirs to receive an asset in this scenario).
        *   **Allocation Persistence**: Upon successful solver execution, the backend must iterate through all allocated assets. For each asset, it updates the `allocated_to_id` column in the `assets` table with the winning Heir's ID, and updates the asset's `status` to `'DISTRIBUTED'`, persisting these results in the database.
    *   **Constraint (Verification Hold)**: Returns `400 Bad Request` if any registered Heir is currently in the `'PROFILE_HOLD'` state. All heirs must be verified (`ACTIVE` / `SUBMITTED`), deleted, or marked as silent non-participants before finalization to ensure probate audit admissibility.
    *   **Constraint (Notice Window)**: Returns `400 Bad Request` if there are any heirs who have not submitted (`is_submitted = False`), have not explicitly abstained (`status != 'ABSTAINED'`), and whose `invite_token_expires_at` has not yet passed. This prevents premature finalization that would bypass the legal notice period required for beneficiary participation.
    *   **Response**: `{"session_id": "UUID", "status": "FINALIZED", "audit_chain_hash": "SHA256"}`
*   **`POST /api/sessions/{session_id}/launch`**
    *   **Access**: Admin credentials required.
    *   **Description**: Transitions the session status from `'SETUP'` to `'ACTIVE'`. This permanently locks the inventory catalog from further uploads/updates, unlocks points sliders and chat mediation interfaces for all heirs, sets the session `deadline` to 14 days from the launch timestamp (or the configured lifespan duration), and triggers a WebSocket broadcast of the updated status.
    *   **Constraint**: Returns `400 Bad Request` if there are no published assets (either `'LIVE'` or `'PRE_ALLOCATED'`) in the database for this session.
    *   **Response**: `{"session_id": "UUID", "status": "ACTIVE"}`
*   **`PUT /api/sessions/{session_id}/announcement`**
    *   **Access**: Admin credentials required.
    *   **Request Body**: `AnnouncementRequest`
    *   **Description**: Sets, updates, or clears a session-wide announcement from the Executor. Updates the `announcement` and `announcement_updated_at` fields in the session.
    *   **Logic**: Updates the session in the database and triggers a WebSocket broadcast of type `"announcement_updated"` to all connected user connections in this session, containing the new announcement text (or null) and updated timestamp.
    *   **Constraint**: Returns `400 Bad Request` if the session's status is `'FINALIZED'`.
    *   **Response**: `{"session_id": "UUID", "announcement": "string", "announcement_updated_at": "ISO-8601-String"}`
*   **`GET /api/invite/status/{token}`**
    *   **Access**: Public.
    *   **Description**: Checks the usage status of the token.
    *   **Response**: `{"status": "NEW" | "USED" | "EXPIRED", "username": "string | null"}`
*   **`POST /api/invite/login`**
    *   **Access**: Public.
    *   **Request Body**: `{"token": "UUID"}`
    *   **Description**: Re-issues a session cookie for already-onboarded heirs.
    *   **Logic**: Verifies that the token matches a user, is `invite_token_used == True`, and is not expired (`invite_token_expires_at > current_time`). If valid, returns a secure HTTP-only JWT token session cookie.
    *   **Response**: `{"status": "success", "session_id": "UUID", "heir_id": "UUID", "user_status": "ACTIVE | PROFILE_HOLD | SUBMITTED"}`

### 9.2 Asset Staging & Visual Publishing
*   **`POST /api/sessions/{session_id}/assets/stage`**
    *   **Access**: Admin credentials required.
    *   **Request Body**: `multipart/form-data` containing the file upload.
    *   **Logic**: 
        1. Preprocesses the image (HEIC conversion, WebP scaling) and saves the WebP image in `/app/static/uploads/`.
        2. Creates an asset row in the database, setting `ocr_status = 'PROCESSING'` and `status = 'STAGED'`.
        3. Fires the `llava` visual OCR model asynchronously as a background worker thread.
        4. Once the background worker completes extraction, it updates the asset row with the extracted metadata (title, category, tags, description) and updates `ocr_status = 'COMPLETED'` (or `'FAILED'` on error).
        5. The backend immediately dispatches a WebSocket frame of type `"asset_ocr_completed"` to the Admin broadcast channel containing the pre-filled asset payload and its UUID, notifying the UI that the metadata is ready for edit.
    *   **Constraint (Inventory Lock)**: Disables and returns `400 Bad Request` if the session status is `'ACTIVE'`, `'LOCKED'`, or `'FINALIZED'`.
    *   **Response**: `AssetStagedResponse` (containing the new asset's UUID and `'PROCESSING'` status).
*   **`POST /api/assets/{asset_id}/publish`**
    *   **Access**: Admin credentials required.
    *   **Request Body**: `AssetSchema`
    *   **Description**: Commits edited asset details to the database, generates its search vector, and shifts status to `'LIVE'`.
    *   **Embedding Generation**:
        *   The backend compiles the text representation of the asset as:
            `text_to_embed = f"Title: {title}\nCategory: {category}\nDescription: {description}\nTags: {sentiment_tag}"`
        *   It sends a request to the configured embedding provider (specified by `EMBEDDING_PROVIDER` and `EMBEDDING_MODEL` environment variables) via the LLM Abstraction Layer to compute the 768-dimensional embedding.
        *   The resulting float vector is persisted in the asset's `embedding` column.

    *   **Automatic Matrix Seeding**: This database transaction must automatically insert a default `0`-point valuation row for all currently active/verified Heirs in that session whose status is **not** in `('PENDING', 'PROFILE_HOLD', 'EXPIRED_NON_PARTICIPATING')`, using an `ON CONFLICT (asset_id, heir_id) DO NOTHING` clause to prevent unique constraint violations. See [DB Spec §2.4 Valuation Matrix Seeding Contract](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_db.md) for the full seeding rules.
    *   **Constraint (Inventory Lock)**: Disables and returns `400 Bad Request` if the session status is `'ACTIVE'`, `'LOCKED'`, or `'FINALIZED'`.
    *   **Response**: `{"asset_id": "UUID", "status": "LIVE"}`
*   **`DELETE /api/assets/{asset_id}`**
    *   **Access**: Admin credentials required.
    *   **Description**: Permanently deletes an asset (either staged or published) to resolve accidental PII uploads or inventory errors before mediation begins.
    *   **Constraint (Inventory Lock)**: Disables and returns `400 Bad Request` if the session status is `'ACTIVE'`, `'LOCKED'`, or `'FINALIZED'`. Assets can only be deleted during the `'SETUP'` phase.
    *   **Response**: `{"status": "success", "message": "Asset and associated files deleted"}`
*   **`POST /api/assets/{asset_id}/audio`**
    *   **Access**: Admin credentials required.
    *   **Request Body**: `multipart/form-data` containing the recorded audio file (`file` key, supporting WebM/MP3/WAV up to 10MB).
    *   **Description**: Uploads a recorded voice memo/story from the Admin for the specified asset. Saves the compressed audio file to the local persistent volume `/app/static/uploads/` and updates the asset's `audio_uri`.
    *   **Constraint (Inventory Lock)**: Disables and returns `400 Bad Request` if the session status is `'ACTIVE'`, `'LOCKED'`, or `'FINALIZED'`. Voice stories can only be added or modified during the `'SETUP'` phase.
    *   **Response**: `{"status": "success", "audio_uri": "static/uploads/audio_file.webm"}`
*   **`DELETE /api/assets/{asset_id}/audio`**
    *   **Access**: Admin credentials required.
    *   **Description**: Deletes the Admin's recorded voice story for the asset. Removes the file from the local storage volume and resets the asset's `audio_uri` to `NULL`.
    *   **Constraint (Inventory Lock)**: Disables and returns `400 Bad Request` if the session status is `'ACTIVE'`, `'LOCKED'`, or `'FINALIZED'`.
    *   **Response**: `{"status": "success", "message": "Asset voice recording deleted"}`
*   **`POST /api/assets/{asset_id}/pre-allocate`**
    *   **Access**: Admin credentials required.
    *   **Request Body**: `{"allocated_to_id": "UUID"}`
    *   **Description**: Pre-allocates a staged/live asset to an Heir during the setup phase (representing a specific devise in a Will).
    *   **Logic**: Updates the asset row in the database, setting `allocated_to_id` to the requested beneficiary ID, and transitions its status to `'PRE_ALLOCATED'`. No default valuation matrix seeding is performed. The database transaction must explicitly delete all existing valuation rows for this asset in the `valuations` table to prevent orphaned valuations from polluting the solver matrix.
    *   **Constraint (Inventory Lock)**: Disables and returns `400 Bad Request` if the session status is `'ACTIVE'`, `'LOCKED'`, or `'FINALIZED'`. Pre-allocations can only be configured during the `'SETUP'` phase.
    *   **Response**: `{"status": "success", "asset_id": "UUID", "allocated_to_id": "UUID"}`
*   **`GET /api/sessions/{session_id}/assets`**
    *   **Access**: Protected (Heir or Admin).
    *   **Query Params**:
        *   `q`: Optional search string.
        *   `category`: Optional comma-separated list of categories (e.g., `Jewelry,Furniture`).
        *   `has_audio`: Optional boolean (filters by `audio_uri IS NOT NULL`).
        *   `has_shared_stories`: Optional boolean (filters by shared heir stories presence).
        *   `allocation_status`: Optional allocation filter (`'allocated' | 'unallocated' | 'pre_allocated' | 'all'`).
        *   `sort_by`: Optional sorting column (`'relevance' | 'points' | 'title' | 'category'`).
        *   `sort_order`: Optional sort direction (`'asc' | 'desc'`, defaults to `'asc'`).
    *   **Description**: Retrieves, filters, and sorts the estate assets:
        1.  **Hybrid Search**: If `q` is provided, performs a vector search on `assets.embedding` merged with `ILIKE` matches on title and descriptions.
        2.  **Category & Spoken Provenance Filters**: Restricts assets by category list and `audio_uri` presence.
        3.  **Allocation Filters**: If filtered by points allocation status, joins `valuations` for the requesting Heir to filter by `points > 0` or `points == 0`.
        4.  **Sorting**: Sorts results by title, category, relevance match, or points allocated by the calling Heir.
    *   **Response**: `List[AssetSchema]` (deduplicated and sorted, with vector matches prioritized).

### 9.3 Valuations, Overrides & Keepsakes
*   **`POST /api/sessions/{session_id}/valuations/submit`**
    *   **Access**: Protected (Heir JWT session cookie).
    *   **Request Body**: `ValuationSubmitRequest`
    *   **Description**: Acquires a pessimistic database row lock (using an exclusive lock `FOR UPDATE` on the Session row, and exclusive write locks on the User and Valuation rows) and submits the heir's completed points valuations matrix.
    *   **Logic**:
        1. Checks that the Heir is in `'ACTIVE'` status (not `'PROFILE_HOLD'`, `'SUBMITTED'`, or `'ABSTAINED'`).
        2. Validates that the sum of all submitted points is exactly `1000`.
        3. Upserts all points and reasoning texts from the `ValuationSubmitRequest` payload into the `valuations` table in the database, verifying the totals.
        4. Updates the Heir's database record: sets `is_submitted = True`, `submitted_at = current_utc_time`, and updates `status = 'SUBMITTED'`.
        5. Broadcasts a WebSocket status update frame to the session channels.
    *   **Automatic All-Submitted Check**: After successfully committing the submission, queries the count of all heirs in the session whose status is in `('PENDING', 'PROFILE_HOLD', 'ACTIVE')` (i.e., heirs who have not yet submitted, abstained, or expired). If the count is `0` (all eligible heirs have submitted or been resolved), triggers the deadlock detection and solver execution logic defined in §11.1 as an asynchronous background task. If a deadlock is detected, transitions the session to `'LOCKED'` with `is_deadlocked = True` and broadcasts the status via WebSocket. If no deadlock is detected, the session remains `'ACTIVE'` — the Admin must still explicitly finalize via `POST .../finalize`.
    *   **Constraint**: Returns `400 Bad Request` if the session is `'LOCKED'` or `'FINALIZED'`. Returns `403 Forbidden` if the Heir is in `'PROFILE_HOLD'`.
    *   **Response**: `{"status": "submitted", "submitted_at": "ISO-8601-String"}`
*   **`GET /api/sessions/{session_id}/heirs/{heir_id}/valuations`**
    *   **Access**: Protected (Heir JWT cookie matching `heir_id`, or Admin credentials).
    *   **Description**: Retrieves the existing point allocations and reasoning text submitted by the specified Heir, allowing the frontend to rebuild the slider state.
    *   **Response**: `List[ValuationSchema]`
*   **`PUT /api/sessions/{session_id}/valuations/draft`**
    *   **Access**: Protected (Heir JWT session cookie).
    *   **Request Body**: `{"draft_version": int, "valuations": List[ValuationDraftSchema]}` (list of asset UUIDs, points, reasoning text, and is_reasoning_shared flags).
    *   **Description**: Saves the Heir's draft point allocations and reasoning texts to the database. Updates existing rows in `valuations` composite-key matching the asset and calling Heir.
    *   **Logic**:
        1. Acquires a pessimistic shared read lock (`FOR SHARE` / `with_for_update(read=True)`) on the Session row and exclusive locks on the user/valuation records to allow concurrent heir draft savings.
        2. Query the Heir's current `draft_version` from the database.
        3. If the incoming `draft_version` is less than or equal to the stored value, return `409 Conflict` (indicating an out-of-order race condition request is discarded).
        4. Otherwise, execute a bulk database upsert in a single transaction, update the Heir's `draft_version` column to the new version, and commit.
    *   **Constraint (Session Lock)**: Returns `400 Bad Request` if the session status is `'LOCKED'` or `'FINALIZED'`. Returns `403 Forbidden` if the Heir is in `'PROFILE_HOLD'`.
    *   **Response**: `{"status": "success", "message": "Draft allocations saved", "draft_version": int}`
*   **`POST /api/sessions/{session_id}/override`**
    *   **Access**: Admin credentials required.
    *   **Request Body**: `List[AdminOverrideRequest]`
    *   **Description**: Admin overrides division deadlocks by directly forcing the allocation of specific contested assets.
    *   **Logic**:
        1. For each `AdminOverrideRequest`, the backend updates the matching asset in the database: sets `allocated_to_id` to the requested beneficiary, and updates status to `'PRE_ALLOCATED'` (bypassing the solver for this asset).
        2. Writes a corresponding `'ADMIN_OVERRIDE'` block to the tamper-proof `audit_logs` (capturing the event, timestamp, and fiduciary `reason` justifying the decision).
        3. During solver execution, for any assets that have been overridden, the points allocated by heirs to those assets are subtracted from their respective 1000-point budgets. The `fairpyx` solver is then run on all remaining active `'LIVE'` assets with the heirs' adjusted point budgets.
        4. Feeds the override state directly into the LangGraph state machine, clears the `is_deadlocked` flag, and signals thread execution resumption.
        5. After committing overrides and clearing `is_deadlocked`, if `is_paused` is `False`, transitions `sessions.status` back to `'ACTIVE'`.
    *   **Response**: `{"status": "resolved"}`
*   **`GET /api/sessions/{session_id}/keepsake`**
    *   **Access**: Protected (Heir JWT or Admin credentials).
    *   **Description**: Generates and returns the Final Distribution & Probate Audit Ledger PDF file stream for the session (built using the ReportLab layout defined in Section 13), containing the cover page, registered beneficiary table, proof of notice log, final asset allocations grid, and admin intervention/override ledger.
    *   **Response**: `application/pdf` binary stream.
*   **`GET /api/sessions/{session_id}/heirs/{heir_id}/keepsake`**
    *   **Access**: Protected (Heir JWT cookie matching `heir_id`, or Admin credentials).
    *   **Description**: Generates and returns the individual Heir's Keepsake Memory Book PDF file stream (built using the ReportLab layout defined in Section 13).
    *   **Response**: `application/pdf` binary stream.
*   **`POST /api/sessions/{session_id}/keepsake/email`**
    *   **Access**: Protected (Heir JWT or Admin credentials).
    *   **Request Body**: `KeepsakeEmailRequest`
    *   **Description**: Triggers a background worker to format the Heir's Keepsake Memory Book PDF and dispatch it to their registered email address using `aiosmtplib`.
    *   **Logic**:
        1. If called by an Heir (authenticated via Heir JWT cookie), the backend automatically formats and emails the Keepsake PDF to the calling Heir's registered email address. The `heir_id` in `KeepsakeEmailRequest` is ignored.
        2. If called by an Admin/Executor, the backend:
           * If `heir_id` is supplied in the request body, formats and emails that specific Heir's Keepsake Memory Book.
           * If `heir_id` is `None` or omitted, queues background tasks to format and email the respective Keepsake Memory Books to *all* registered active/submitted heirs in the session.
    *   **Response**: `{"status": "queued"}`
*   **`GET /api/sessions/{session_id}/heirs/{heir_id}/chat`**
    *   **Access**: Protected (Heir JWT cookie matching `{heir_id}` only. Admin credentials are blocked with `403 Forbidden` to guarantee mediation confidentiality).
    *   **Description**: Retrieves the persisted conversation history from the `chat_messages` database table, sorted chronologically.
    *   **Response**: `List[ChatMessageSchema]`

### 9.4 Heir Assistance & Support Tickets
*   **`POST /api/sessions/{session_id}/help`**
    *   **Access**: Protected (Heir JWT session cookie).
    *   **Request Body**: `SupportRequestCreate` (`{"message": "description of issue"}`)
    *   **Description**: Submits a help ticket to the Executor.
    *   **Response**: `{"status": "submitted"}`
*   **`GET /api/sessions/{session_id}/help`**
    *   **Access**: Admin credentials required.
    *   **Description**: Lists all help request tickets for the session, resolving Heir usernames via database joins.
    *   **Response**: `List[SupportRequestResponse]`
*   **`GET /api/sessions/{session_id}/faqs`**
    *   **Access**: Protected (Heir or Admin).
    *   **Description**: Retrieves the dynamic FAQ accordion items for this session, combining the static general system FAQs with the custom estate-specific FAQs added by the Admin.
    *   **Response**: `{"system_faqs": List[FAQSchema], "custom_faqs": List[CustomFAQSchema]}`
*   **`POST /api/sessions/{session_id}/faqs`**
    *   **Access**: Admin credentials required.
    *   **Request Body**: `FAQCreate`
    *   **Description**: Creates a new custom estate-specific FAQ.
    *   **Response**: `{"id": "UUID", "question": "...", "answer": "..."}`
*   **`PUT /api/sessions/{session_id}/faqs/{faq_id}`**
    *   **Access**: Admin credentials required.
    *   **Request Body**: `FAQCreate`
    *   **Description**: Updates the text of a custom estate-specific FAQ.
    *   **Response**: `{"id": "UUID", "question": "...", "answer": "..."}`
*   **`DELETE /api/sessions/{session_id}/faqs/{faq_id}`**
    *   **Access**: Admin credentials required.
    *   **Description**: Permanently deletes a custom estate-specific FAQ.
    *   **Response**: `{"status": "success", "message": "Custom FAQ deleted"}`
*   **`POST /api/help/{ticket_id}/resolve`**
    *   **Access**: Admin credentials required.
    *   **Description**: Toggles support request ticket status to `'RESOLVED'`.
    *   **Response**: `{"status": "resolved"}`

### 9.5 Authentication & Setup
*   **`POST /api/auth/login`**
    *   **Access**: Public.
    *   **Request Body**: `{"username": "admin_username", "password": "admin_password"}`
    *   **Logic**: Verifies the admin password hash against the database using Argon2. On success, generates a JWT token and returns it in a secure, HTTP-only cookie.
    *   **Response**: `{"status": "authenticated", "role": "ADMIN"}`
*   **`GET /api/heirs/me`**
    *   **Access**: Protected (Heir JWT session cookie).
    *   **Description**: Retrieves the profile details and lifecycle status of the currently logged-in Heir.
    *   **Response**: `HeirResponse`
*   **`DELETE /api/heirs/me`**
    *   **Access**: Protected (Heir JWT session cookie).
    *   **Description**: Wipes personal records for the calling Heir (GDPR Right to Erasure / Soft Anonymization).
    *   **Logic**:
        1. Overwrites the Heir's display name with `"Anonymized Beneficiary [UUID]"`, `legal_first_name` with `"Anonymized"`, `legal_last_name` with `"Beneficiary [UUID]"`, and sets `legal_middle_name`, `email`, `phone`, `physical_address`, `relationship_to_decedent`, `date_of_birth`, and `id_scan_uri` to `NULL`.
        2. If an ID scan file exists in the filesystem, it is deleted from `/app/static/uploads/identities/` disk storage.
        3. Clears invite tokens, IP addresses, and session cookies.
        4. Permanently deletes all private chat transcripts matching this Heir's ID in the `chat_messages` table to ensure PII conversational logs are completely erased.
        5. Permanently deletes all database records in the LangGraph checkpointer tables (checkpoints, checkpoint_writes, etc.) matching this Heir's thread ID (`f"{session_id}:{heir_id}"`) to prevent orphaned PII state storage.
        6. **Submission Status Separation**:
           * **If Heir is Unsubmitted (`is_submitted = False`)**: The backend updates their user status to `'ABSTAINED'` and cascade deletes all of their default `0`-point valuations. This prevents points pool sum validation errors from stalling session finalization.
           * **If Heir is Submitted (`is_submitted = True`)**: The backend preserves their status as `'SUBMITTED'` and retains their point allocations, public shared memories (`valuations.reasoning` where `is_reasoning_shared = true`), and consent timestamps, but explicitly overwrites private reasoning text (`valuations.reasoning` where `is_reasoning_shared = false`) with `NULL` to prevent private PII leakage.
        7. Queries the `audit_logs` table for the active session. Decrypts each `state_snapshot`, identifies any nested keys or values matching the deleted Heir's `heir_id` or original legal names/contact details, replaces those values with `"Anonymized"`, re-encrypts the snapshot, and commits the updated rows to prevent historical data leakage.
    *   **Response**: `{"status": "success", "message": "Personal identification purged; account records soft-anonymized and checkpointer states cleared for probate record-keeping."}`
*   **`POST /api/heirs/me/abstain`**
    *   **Access**: Protected (Heir JWT session cookie).
    *   **Request Body**: `AbstainRequest`
    *   **Description**: Active Abstention / Waiver of Rights. Registers the Heir's voluntary decision to abstain from asset distribution.
    *   **Logic**:
        1. Verifies the Heir's current status is `'ACTIVE'` **or** `'SUBMITTED'`. Both are valid abstention candidates: an `'ACTIVE'` heir has not yet submitted, while a `'SUBMITTED'` heir may have changed their mind after submitting and wishes to waive all claims. Heirs in `'PROFILE_HOLD'`, `'ABSTAINED'`, or `'EXPIRED_NON_PARTICIPATING'` are rejected with `400 Bad Request`.
        2. Logs an `'ABSTENTION_WAIVER'` event block in `audit_logs` (storing the IP, timestamp, and signature).
        3. Updates their status in `users` to `'ABSTAINED'`, cascade deletes their default `0`-point valuations to avoid preferences matrix pollution. If the Heir was `'SUBMITTED'`, also deletes any non-zero valuations to fully remove their preference data from the solver matrix.
        4. **E-SIGN/UETA Compliance Receipt**: Queues an asynchronous background task to send an email confirmation containing the signed waiver text, timestamp, and IP to the Heir's registered email address (if SMTP is configured). If this email dispatch fails completely after retries, updates `users.waiver_email_failed = True` and auto-generates a system support request in `support_requests` with status `'OPEN'` and message:
           > *"SYSTEM WARNING: Electronic waiver confirmation email to [Heir Email] failed to deliver. Executor must physically deliver a printed copy of the signed waiver receipt to satisfy E-SIGN/UETA regulations."*
        5. Broadcasts a WebSocket status frame.
    *   **Response**: `{"status": "success", "message": "Waiver signed and abstention registered"}`
*   **`GET /api/heirs/me/abstain/receipt`**
    *   **Access**: Protected (Heir JWT session cookie).
    *   **Description**: Generates and downloads a single-page ReportLab PDF receipt containing the full E-SIGN disclosure, signed waiver text, Heir's legal name, IP address, timestamp, and database SHA-256 block hash seal.
    *   **Response**: `application/pdf` binary stream.
*   **`GET /api/heirs/me/export`**
    *   **Access**: Protected (Heir JWT session cookie).
    *   **Description**: Data Portability endpoint (GDPR Article 20). Decrypts and packages all of the Heir's personal records in a structured JSON download. For the returned JSON schema, see [Compliance Spec Section 2.2](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_compliance.md#22-get-apiheirsmeexport-gdpr-article-20---data-portability).
    *   **Response**: `application/json` file stream attachment.
*   **`POST /api/heirs/me/upload-id`**
    *   **Access**: Protected (Heir JWT session cookie).
    *   **Request Body**: `multipart/form-data` containing image/pdf document in `file` key (up to 10MB).
    *   **Description**: Allows Heirs to upload a scanned image or photo of their Government ID during onboarding. 
    *   **Logic**:
        1. Encrypts the uploaded file bytes using standard AES-Fernet with the system's active `ENCRYPTION_KEY`.
        2. Saves the encrypted file to `/app/static/uploads/identities/` with a random secure UUID filename.
        3. Updates the Heir's `id_scan_uri` column with the file path.
        4. Toggles `identity_verified = False` to enforce a fresh visual inspection by the Executor.
    *   **Response**: `{"status": "success", "message": "ID document uploaded and encrypted successfully"}`
*   **`PUT /api/heirs/me/profile`**
    *   **Access**: Protected (Heir JWT session cookie).
    *   **Request Body**: `HeirProfileUpdate`
    *   **Description**: Allows the calling Heir to update their contact details (email, phone, address) or correct errors in their legal identification parameters (e.g. typos in legal names or birth date).
    *   **Logic**:
        1. Verifies that the session is not locked or finalized. If the session is locked or finalized, returns `400 Bad Request`.
        2. Verifies that the Heir's current status is not `'ABSTAINED'` or `'EXPIRED_NON_PARTICIPATING'`. If it is, returns `400 Bad Request`.
        3. Compares the request body legal fields (`legal_first_name`, `legal_middle_name`, `legal_last_name`, `date_of_birth`) with the values currently in the database:
           - If any of these legal identity fields have changed, checks if `id_scan_uri` is not null. If it is not null, permanently deletes the associated encrypted ID scan image file from `/app/static/uploads/identities/` disk storage, sets `id_scan_uri = NULL` in the database, resets `identity_verified = False`, and updates the Heir's status to `'PROFILE_HOLD'`.
        4. Saves all updated fields (`legal_first_name`, `legal_middle_name`, `legal_last_name`, `relationship_to_decedent`, `date_of_birth`, `email`, `phone`, `physical_address`) to the database.
        5. Logs a `'USER_PROFILE_UPDATE'` event in the `audit_logs` table. The event audit snapshot captures the changed fields along with their pre-update and post-update values, tagged with the calling Heir's user ID as the editor.
        6. Broadcasts a WebSocket status frame to notify the Executor that a profile update has occurred and a new verification is pending.
    *   **Response**: `{"status": "success", "message": "Heir profile updated successfully.", "identity_verified": false}`
*   **`POST /api/heirs/{heir_id}/verify-identity`**
    *   **Access**: Admin credentials required.
    *   **Request Body**: `VerifyIdentityRequest`
    *   **Description**: Executor visually inspects the ID scan and approves or rejects the Heir profile.
    *   **Logic**:
        1. If `action == "approve"`:
           * Updates the Heir's record setting `identity_verified = True` and transitions status from `'PROFILE_HOLD'` to `'ACTIVE'`.
           * **Automatic Matrix Seeding**: Queries all existing `'LIVE'` assets in the session and inserts a default `0`-point valuation row for this newly-active Heir using `ON CONFLICT (asset_id, heir_id) DO NOTHING` to prevent unique constraint violations if a race condition occurs. This is the correct time to seed since the Heir's status is now `'ACTIVE'`, satisfying the DB Seeding Contract (see DB Spec §2.4).
           * Retrieves the file path from `id_scan_uri`, deletes the encrypted temporary file from `/app/static/uploads/identities/` disk storage, and sets `id_scan_uri = NULL`.
           * Logs a `'BENEFICIARY_IDENTITY_APPROVED'` event in the tamper-proof `audit_logs` chain.
           * Sends a WebSocket broadcast to notify the Heir that their profile is approved and active.
        2. If `action == "reject"`:
           * Retrieves the file path from `id_scan_uri`, deletes the encrypted temporary file from disk storage, and sets `id_scan_uri = NULL` (enforcing immediate erasure of unverified ID records).
           * Logs a `'BENEFICIARY_IDENTITY_REJECTED'` event in the audit chain with the rejection reason.
           * Sends a WebSocket broadcast to notify the Heir's dashboard of the rejection reason and prompts them to re-upload their ID scan.
    *   **Response**: `{"status": "success", "message": "Verification action processed successfully."}`
*   **`POST /api/invite/verify`**
    *   **Access**: Public.
    *   **Request Body**: `InviteVerifyRequest`
    *   **Logic**:
        1. Looks up the invitation token. Verifies if `invite_token_used` is already `True` or if the current UTC time is past `invite_token_expires_at` (i.e. the token is expired) in the database. If so, immediately aborts and returns `400 Bad Request` with payload: `{"error": "This invitation link has expired or has already been used. Please contact the Executor."}`.
        2. Validates age/consent flags, records the consent timestamp, updates profile details if the Heir requested edits during verification, and sets the invitation token as used (`invite_token_used = True`).
        3. Sets the Heir's status in `users` to `'PROFILE_HOLD'`.
        4. Returns a secure HTTP-only JWT token session cookie.
        5. **Holding Gate Restriction**: 
           * While the Heir has status `'PROFILE_HOLD'`, the backend gateways for draft valuations (`PUT .../draft`), submissions (`POST .../submit`), and WebSocket mediation chats (`ws://...`) must return `403 Forbidden` with error payload: `"Profile pending Executor identity verification. Bidding and mediation chat are locked."` Heirs are permitted to view the read-only catalog but cannot allocate points or interact.
           * While the Heir's LangGraph thread is currently suspended at `HITL_GUARD` (due to repeating validation failures), the backend gateways for final submissions (`POST .../submit`) and WebSocket mediation chats (`ws://...`) must return `403 Forbidden` with error payload: `"Points submission suspended. Your allocations require review and correction by the Executor."` This prevents incoming user messages from resuming the LangGraph validation thread and bypassing the validation checks before corrections are applied. Note: The draft saving gateway (`PUT .../draft`) remains **accessible** during this suspension to allow Heirs to adjust and correct their point allocations to sum to 1000.
    *   **Response**: `{"status": "success", "session_id": "UUID", "heir_id": "UUID", "user_status": "PROFILE_HOLD"}`
    *   **Note on Matrix Seeding**: Automatic valuation matrix seeding (default `0`-point rows for all `'LIVE'` assets) is **NOT** performed here. At this point the Heir is in `'PROFILE_HOLD'` status, which is excluded from the seeding contract (see DB Spec §2.4). Seeding is deferred to the `POST /api/heirs/{heir_id}/verify-identity` `approve` path, when the Heir first transitions to `'ACTIVE'`.)
*   **`POST /api/setup/admin`**
    *   **Access**: Public (Active only on empty database tables).
    *   **Request Body**: `UserCreate` (username, password).
    *   **Logic**: Seed route to initialize the first Administrator account. Reads the system's active `ENCRYPTION_KEY` environment variable (32-byte AES key), converts it into a 24-word BIP39 mnemonic Paper Recovery Key, saves the hashed representation of the admin user credentials, and returns the mnemonic phrase to the admin to write down as their Paper Recovery Key. This ensures that the Paper Recovery Key is a direct representation of the system encryption key, enabling full database recovery from backups.
    *   **Response**: `{"status": "created", "username": "admin_username", "paper_recovery_key": "24-word mnemonic phrase here"}`
*   **`GET /api/system/models`**
    *   **Access**: Public.
    *   **Description**: Exposes model transparency metadata to comply with California AB 2013 (AI Training Data Transparency). For the active model metadata and JSON format, see [Compliance Spec Section 2.4](file:///Users/amelton/Library/Mobile%20Documents/com~apple~CloudDocs/estate_agent/specs/specs_compliance.md#24-get-apisystemmodels-california-ab-2013---ai-training-data-transparency).
    *   **Response**: `application/json` (List of models, licenses, and training dataset provenance).
*   **`GET /api/system/backup`**
    *   **Access**: Admin credentials required.
    *   **Description**: Generates an encrypted backup payload of the entire estate database and media directory.
    *   **Logic**:
        1. Generates a PostgreSQL SQL dump of all estate mediation sessions, users, assets, valuations, support tickets, and audit tables.
        2. Compresses the SQL dump together with the `static/uploads/` directory contents into a single `.tar.gz` archive.
        3. Encrypts the archive using the application's AES-Fernet encryption key (`ENCRYPTION_KEY`).
    *   **Response**: `application/octet-stream` (binary file transfer of the `.estate.bak` archive).
*   **`POST /api/system/restore`**
    *   **Access**: Admin credentials required, **OR Public if the database contains zero registered users**.
    *   **Request Body**: Multipart form data with key `backup_file`, and optional string `recovery_key`.
    *   **Logic**:
        1. If the database contains zero registered users (bare-metal uninitialized state), the endpoint permits public uploads but enforces that the request must contain the valid 24-word recovery key mnemonic to decrypt the backup archive.
        2. Decrypts the incoming file stream using either the environment's `ENCRYPTION_KEY` or the user-provided `recovery_key` (converted back to the 32-byte AES key).
        2. Unpacks the archive and validates the database schema and version signature.
        3. Executes the SQL recovery script inside a database transaction, overwriting active tables.
        4. Extracts and restores the media files to the local `static/uploads/` directory volume, resetting file permissions to owner read/write (644) and directory permissions to search/read (755).
    *   **Response**: `{"status": "success", "message": "System database and media restored successfully"}`


### 9.6 WebSocket Frame Protocol (`/api/sessions/{session_id}/ws`)
The persistent WebSocket connection is established per-session.

#### Handshake Authentication Protocol
1.  **Request URL**: `ws://<host>/api/sessions/{session_id}/ws`
2.  **Authentication**: The server extracts and decodes the HTTP-only JWT token cookie during the initial WebSocket handshake request.
    *   **If Heir**: The server verifies `role == 'HEIR'` and validates that the token's `session_id` matches the path variable `{session_id}`. The socket is registered to a private thread (`session_id:heir_id`).
    *   **If Admin**: The server verifies `role == 'ADMIN'` and registers the socket to the session's broadcast channel to receive real-time support alerts and state updates.

#### 1. Client-to-Server Frames
*   **Chat Message**:
    ```json
    {
      "type": "chat_message",
      "text": "User typed message or spoken transcript",
      "metadata": { "input_method": "text" }
    }
    ```
*   **Heartbeat Ping**:
    ```json
    { "type": "ping" }
    ```

#### 2. Server-to-Client Frames

*   **Chat Reply Chunk (Real-Time Audio Stream)**:
    To guarantee 100% compliance auditing before delivery, the backend does not stream LLM tokens as they are generated by System 1. Instead, the response from `FAST_MEDIATE_NODE` is fully generated first (restricted to under 4 sentences to keep latency low), and is immediately sent to `SLOW_CRITIQUE_NODE` for a safety check. If compliant, the backend then streams the completed text sentence chunks and synthesizes the audio chunks sequentially via Kokoro-82M, sending each chunk as a WebSocket frame. This pipeline ensures complete safety auditing while maintaining a Time-To-First-Audio under 2.5 seconds on local hardware.
    ```json
    {
      "type": "chat_reply_chunk",
      "text": "The completed sentence text.",
      "sender": "agent",
      "audio": "BASE64_ENCODED_WAV_BYTES_STRING", // Audio chunk for this sentence
      "is_synthetic": true,                       // For SB 942 requirements, see Compliance Spec Section 2.5
      "is_final": false                           // Set to true on the very last sentence chunk of the reply
    }
    ```
*   **Support Ticket Alert** (Broadcasted to connected Admins):
    ```json
    {
      "type": "support_alert",
      "ticket_id": "UUID",
      "heir_name": "John Doe",
      "message": "Heir help text",
      "timestamp": "ISO-8601-String"
    }
    ```
*   **Session State Update**:
    ```json
    {
      "type": "session_status",
      "status": "ACTIVE | LOCKED | FINALIZED",
      "is_paused": false,
      "is_deadlocked": false
    }
    ```
*   **Announcement Update** (Broadcasted to connected Heirs and Admins):
    ```json
    {
      "type": "announcement_updated",
      "announcement": "Important text here or null",
      "announcement_updated_at": "ISO-8601-String or null"
    }
    ```
*   **Error Warning**:
    ```json
    {
      "type": "error",
      "message": "Error description text"
    }
    ```

---

## 10. SMTP Service Configuration
*   **Library**: `aiosmtplib` for non-blocking asynchronous SMTP execution.
*   **Payload**: Uses Python's `email.mime.multipart.MIMEMultipart` (type `multipart/mixed`) containing a plain text body and the Keepsake PDF attached as `application/pdf`.
*   **Retry Policy**: Delivers background emails with up to 3 retry attempts using exponential backoff (1s, 4s, 16s) on connection failures.
*   **Transaction Decoupling**: SMTP dispatch must run asynchronously (e.g. as a FastAPI background task) and is strictly decoupled from database commits. If an email dispatch fails completely after retries, the error is logged as a warning, but the transaction committing the final asset allocations, audit logs, and SHA-256 block hashes remains committed and fully successful.

---

## 11. Fair Division Math Solver (Fairpyx)
Valuations from the database are transformed into a nested dictionary to serve as the standard preferences matrix for the `fairpyx` solver:
```python
# Valuation table records are mapped to:
preferences = {
    "heir_user_id_1": {"asset_uuid_a": 400, "asset_uuid_b": 600},
    "heir_user_id_2": {"asset_uuid_a": 500, "asset_uuid_b": 500}
}
# Resolved using:
# allocation = fairpyx.divide(
#     preferences=preferences, 
#     items=asset_ids, 
#     algorithm=fairpyx.algorithms.MaximumNashWelfare
# )
```

### 11.0 Handling Non-Participating & Abstaining Heirs
If an Heir is invited but does not participate (e.g., they refuse to log in or walk away without submitting):
1.  **Administrative Deletion**: The Admin can delete the Heir from the session via `DELETE /api/sessions/{session_id}/heirs/{heir_id}` at any time prior to finalization, which cascade-deletes their default valuations and references.
2.  **User Status Transitions at Finalization**: During session finalization (`POST /api/sessions/{session_id}/finalize`), the system automatically checks and updates non-submitting Heirs:
    *   **Silent Non-Participation**: If `invite_token_used == False` and the current UTC time is past `invite_token_expires_at` (configured notice window, default 14 days), the Heir's status is updated to `'EXPIRED_NON_PARTICIPATING'`.
    *   **Active Abstention**: If the Heir explicitly clicked "Abstain from Division" (sending a signed waiver via `POST /api/heirs/me/abstain`), their status is already `'ABSTAINED'`.
    *   **Automatic Abstention**: If the Heir has logged in but has not submitted valuations (`invite_token_used == True` and `is_submitted == False`) and has not explicitly abstained, they are automatically marked as `'ABSTAINED'`.
3.  **Solver Exclusion**: The backend compiler **must** exclude all Heirs with status `'ABSTAINED'` or `'EXPIRED_NON_PARTICIPATING'` from the preference matrix passed to the `fairpyx.divide` solver. They receive no assets and are omitted from all deadlock and "Zero-Utility Starvation" checks so their inactivity does not freeze the division for participating family members.

### 11.1 Global Deadlock Checking Sequence
When the Admin invokes the finalization endpoint (`POST /api/sessions/{session_id}/finalize`) or when all registered heirs have successfully submitted, the backend compiles the full preferences matrix and executes the division math. The session is flagged as deadlocked (database status transitions to `'LOCKED'` and `is_deadlocked` is set to `True`) if any of the following criteria match:
1.  **Mutually Exclusive Maximum Priority**: Two or more heirs allocate exactly `1000` points (their entire valuation pool) to the same asset, making a fair mathematical split impossible.
2.  **Zero-Utility Starvation**: The `fairpyx.divide` allocation results in one or more heirs receiving `0` assets, despite having submitted active, positive valuations. **Starvation Bypass Rule**: This starvation check is dynamically bypassed if the number of active, non-abstained Heirs who do not have any `'PRE_ALLOCATED'` assets is greater than the number of available `'LIVE'` assets.
3.  **Valuation Parity Conflict**: Two heirs submit the exact same point value (tie) on an asset that is the highest-valued item for both, and there are no other assets of equal value to balance the Nash welfare product.

### 11.2 Resolution Execution
If a deadlock is detected:
*   The active database transaction's solver allocation writes are rolled back. 
*   A new, separate database transaction is immediately opened to update the session record, setting `status = 'LOCKED'` and `is_deadlocked = True` in the database, and is committed. This guarantees the deadlock state is saved, while preventing uncommitted asset allocations from leaking. All active heirs receive a WebSocket status broadcast.
*   The Admin uses the **Force Allocation Console** to manually distribute contested assets, sending the overrides via `POST /api/sessions/{session_id}/override`.
*   The manual overrides are written to the database state, bypassing the `fairpyx` solver checks, allowing the finalization transaction to commit and seal the ledger.

### 11.3 Deterministic Tie-Breaking Protocol
To satisfy the Duty of Impartiality (UPC § 3-703) and ensure 100% reproducible and auditable results, the solver must break ties (where two or more heirs have identical point valuations for a contested asset) using a strict, deterministic rule sequence:
1.  **First Tie-Breaker (Submission Order)**: Award the item to the Heir who has the earliest `submitted_at` timestamp in the database (favoring early participation).
2.  **Second Tie-Breaker (Alphabetical UUID Fallback)**: If both Heirs submitted at the exact same microsecond (or are non-submitting/abstained and are being processed under defaults), award the item to the Heir whose `id` UUID string is alphabetically smaller (lexicographical sorting).

**Technical Implementation Contract (Preference Matrix Epsilon Seeding)**:
To implement this protocol natively within the `fairpyx` solver without modifying the core division algorithm, the backend must apply a tiny fractional delta (epsilon) to the preference matrix values prior to running `fairpyx.divide`.
*   Let $p_{ij}$ be the points allocated by Heir $i$ to Asset $j$.
*   Let $T_{\text{start}}$ be the Unix epoch timestamp (float value) of the session `created_at` record (calculated using `.timestamp()` in Python).
*   Let $T_{\text{end}}$ be the Unix epoch timestamp (float value) of the session `deadline` record. If `deadline` is `NULL`, $T_{\text{end}}$ defaults to the Unix epoch of $T_{\text{start}} + \text{14 days}$.
*   Let $T_i$ be the Unix epoch timestamp (float value) of Heir $i$'s submission. If Heir $i$ did not submit or has been soft-anonymized, $T_i$ defaults to $T_{\text{end}}$.
*   The normalized time delta is calculated as: $\epsilon_{\text{time}, i} = (1 - \frac{T_i - T_{\text{start}}}{T_{\text{end}} - T_{\text{start}}}) \times 10^{-6}$. **Safety Guard**: If $T_{\text{end}} - T_{\text{start}} == 0$, then $\epsilon_{\text{time}, i} = 0.0$ to prevent `ZeroDivisionError` exceptions.
*   Let $U_i$ be the alphabetical rank of Heir $i$'s user UUID string among all heirs in the session (e.g. 1 to $N$): $\epsilon_{\text{uuid}, i} = (1 - \frac{U_i}{N}) \times 10^{-8}$.
*   The adjusted points score passed to `fairpyx.divide` is:
    $$p'_{ij} = p_{ij} + \epsilon_{\text{time}, i} + \epsilon_{\text{uuid}, i}$$
*   Because the sum of all epsilons is less than $10^{-5}$, they do not affect solver outcomes for non-tied allocations, but they guarantee that tied bids are resolved deterministically and objectively within the Max Nash Welfare product calculation.

---

## 12. Deployment Configuration (Docker-Compose)

```yaml
version: '3.8'
services:
  app:
    build: ./backend
    environment:
      - ENCRYPTION_KEY=${ENCRYPTION_KEY}
      - STORAGE_DRIVER=${STORAGE_DRIVER:-LOCAL}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
      - DB_ECHO=${DB_ECHO:-False}
      - LLM_PROVIDER=${LLM_PROVIDER:-ollama}
      - EMBEDDING_PROVIDER=${EMBEDDING_PROVIDER:-ollama}
      - VISION_PROVIDER=${VISION_PROVIDER:-ollama}
      - FAST_THINKER_MODEL=${FAST_THINKER_MODEL:-qwen2.5:8b-instruct}
      - SLOW_THINKER_MODEL=${SLOW_THINKER_MODEL:-qwen2.5:14b-instruct}
      - VISION_MODEL=${VISION_MODEL:-llava:7b}
      - EMBEDDING_MODEL=${EMBEDDING_MODEL:-nomic-embed-text}
      - OLLAMA_BASE_URL=${OLLAMA_BASE_URL:-http://localhost:11434}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - DB_URL=postgresql+psycopg2://user:pass@db:5432/estate
      - SMTP_HOST=${SMTP_HOST}
      - SMTP_PORT=${SMTP_PORT}
      - SMTP_USER=${SMTP_USER}
      - SMTP_PASSWORD=${SMTP_PASSWORD}

    volumes:
      - uploads_data:/app/static/uploads
    ports:
      - "8000:8000"
  db:
    image: postgres:15
    command: ["postgres", "-c", "shared_preload_libraries=pgvector"]
    environment:
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
      - POSTGRES_DB=estate
    volumes:
      # Named Docker volume — decouples DB data lifecycle from host directory structure.
      # Do NOT use a bind-mount (./pgdata) here; see Data Safety spec in specs_db.md §7.
      - pgdata:/var/lib/postgresql/data
  langfuse:
    image: langfuse/langfuse:latest
    ports:
      - "3000:3000"
  nginx:
    image: nginx:alpine
    volumes:
      - ./frontend/dist:/usr/share/nginx/html
      - ./nginx.conf:/etc/nginx/nginx.conf
      - uploads_data:/app/static/uploads:ro
    ports:
      - "80:80"

volumes:
  pgdata:
  uploads_data:
```

### 12.1 Network Exposure & Security Safeguards (Exposing Local Server)
When running the application on a local computer or Raspberry Pi 5 where heirs are located on separate, external networks, the local server must be exposed to the public internet securely:
*   **Outbound-Only Tunneling (Recommended)**: To prevent exposing the local network, the server should be exposed using a secure, outbound-only tunnel provider (such as **Cloudflare Tunnels** or **Localtunnel**). These tunnels establish an outbound link to the tunnel provider's proxy servers, generating a public HTTPS URL (e.g., `https://estate.yourdomain.com`). This ensures that no ports are opened on the router, keeping the home network's firewall completely intact and safe from external port scanners.
*   **Port Forwarding Warn/Constraint**: Standard port forwarding on routers (exposing ports directly to the public internet) is discouraged as it invites automated scanning attacks. If port forwarding is used, Nginx must be configured to enforce strict rate limiting and SSL/TLS certificate constraints.
*   **Internal Service Binding**: To protect internal subsystems, database ports (`5432` for PostgreSQL) and LLM endpoints (`11434` for Ollama) must bind strictly to `127.0.0.1` (localhost) inside the docker network configurations. Only Nginx (ports `80`/`443`) is permitted to listen to external connections.
*   **Host Hardening Rules**: The host operating system (e.g. Raspberry Pi OS) must disable SSH password logins in favor of SSH key authentication, change all default user credentials, and keep packages updated to secure local vulnerabilities.

### 12.2 Raspberry Pi 5 LLM Memory Optimization & Scaling
When deploying this System 1 / System 2 double-brain architecture on a hardware-constrained device like a Raspberry Pi 5 (which is limited to 8GB of RAM), the following model size constraints must be applied to prevent Out-of-Memory (OOM) crashes and high latency swapping:
*   **Fast Mediator Model (System 1)**: Scale down to **`qwen2.5:1.5b-instruct`** or **`qwen2.5:3b-instruct`** (quantized to Q4_K_M). These require less than 2.5GB of RAM, enabling fast, real-time streaming chat generation (30+ tokens/sec).
*   **Slow Critic Model (System 2)**: Scale down to **`qwen2.5:7b-instruct`** or **`qwen2.5:8b-instruct`** (quantized to Q4_K_M). Since System 2 processes validations and mathematical proofs sequentially, memory allocation can be managed dynamically by Ollama, staying within the 8GB RAM boundary.
*   **Vision Model**: Use **`moondream:latest`** or **`llava:7b`** (Q4) for image uploads.
*   **Embeddings**: Use **`nomic-embed-text`** for lightweight, localized RAG retrieval.

---


---

## 13. Keepsake PDF Document Design & Layout (ReportLab)

The backend PDF generation service (`GET /api/sessions/{session_id}/keepsake`) uses the **ReportLab** library to render a high-quality, print-ready document. The layout must be structured as follows:

### 13.1 Canvas Setup & Page Templates
*   **Dimensions**: Standard Letter size (`8.5 x 11` inches), portrait.
*   **Margins**: 0.75-inch (54 points) on all sides.
*   **Page Background**: The background cream fill (`#FDFBF7`) must be drawn *first* on every page by registering an `onPage` callback on the page template of the `SimpleDocTemplate` (or `BaseDocTemplate`) before any flowable elements are placed. This ensures the background color rests underneath the text, tables, and images, rather than covering them.
    ```python
    def draw_page_background(canvas, doc):
        canvas.saveState()
        canvas.setFillColor("#FDFBF7")
        canvas.rect(0, 0, 8.5 * 72, 11 * 72, fill=True, stroke=False)
        canvas.restoreState()
    ```
*   **Headers & Footers**: Every page (excluding the cover page) must render a running header (`"The Estate Steward - Keepsake Ledger"`) and a running footer (`"Page X of Y"`) in Helvetica 8pt muted grey text.
*   **Two-Pass Canvas Execution**: Because the total page count is unknown during sequential flowable rendering, the PDF builder must subclass ReportLab's standard canvas helper to perform a two-pass draw. Below is the mandatory python implementation for the custom canvas class (which delegates the running headers, running footers, and border lines to the second pass):

```python
import io
from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        # Save page state dictionary for the second rendering pass
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, total_pages):
        self.saveState()
        
        # Do not draw headers/footers on the cover page (Page 1)
        if self._pageNumber > 1:
            # 2. Running Header (Line and Muted Text)
            self.setFont("Helvetica-Oblique", 8)
            self.setFillColor("#64748B") # Muted Slate
            self.drawString(54, 11 * 72 - 36, "The Estate Steward - Keepsake Ledger")
            
            self.setStrokeColor("#E6DFD3") # Warm-Grey Token
            self.setLineWidth(0.5)
            self.line(54, 11 * 72 - 42, 8.5 * 72 - 54, 11 * 72 - 42)
            
            # 3. Running Footer (Line and Page X of Y)
            self.line(54, 54, 8.5 * 72 - 54, 54)
            self.setFont("Helvetica", 8)
            self.drawString(54, 42, "CONFIDENTIAL - Family Mediation Record")
            
            page_string = f"Page {self._pageNumber} of {total_pages}"
            self.drawRightString(8.5 * 72 - 54, 42, page_string)
            
        self.restoreState()
```


### 13.2 Typography Styles (ParagraphStyle)
*   **Title/Header Font**: Times-Bold (to emulate the editorial *Playfair Display* style). Title size is 26pt with 32pt leading; headings are 16pt.
*   **Body Font**: Helvetica, size 10pt with 14pt leading.
*   **Colors**: Primary text uses Slate-900 (`#1E293B`); secondary text and borders use Warm-Grey (`#E6DFD3`); action highlights use Sage-Green (`#4A6741`).

### 13.3 Content Flow & Layout Grid
The PDF generation service compiles two distinct documents based on the calling route:

#### Document A: The Individual Heir's Keepsake Memory Book PDF (`GET /api/sessions/{session_id}/heirs/{heir_id}/keepsake`)
1.  **Cover Page**:
    *   Large Title: `[Session Title] Keepsake Memory Book`.
    *   Sub-metadata: Heir name, date generated, and statement: *"A document of collaborative distribution and shared memory."*
    *   A horizontal dividing bar in Sage-Green (2pt thickness).
    *   `PageBreak()` to start content on Page 2.
2.  **Mediation Summary**:
    *   A brief, readable paragraph summarizing their dialogue with the Mediator.
    *   Uses Times-Roman 11pt, italic, inside a callout box with a Sage-Green left border.
3.  **Gridless Keepsake Exhibition (Asymmetric Editorial Layout)**:
    *   **Anti-Grid Design**: Ditch all table grid borders and lines completely to create a clean, museum-catalog feel.
    *   **Asymmetric Flow Layout (KeepTogether)**: Each keepsake is rendered as a unified flowable block containing a two-column structure (using a borderless, padding-free table layout for structure):
        *   **Left Column (3.2in width)**: Displays the scaled WebP keepsake photo (up to 3.0in width, strictly preserving aspect ratio).
        *   **Right Column (3.8in width)**: Displays a clean typographical stack:
            *   *Title*: Times-Bold (Playfair Display) 14pt in Slate-900, left-aligned.
            *   *Category Badge*: Helvetica-Bold 8pt, muted Warm-Grey text.
            *   *Points Value*: Sage-Green Times-Bold 11pt (e.g., *"Allocated: 250 Points"*).
            *   *Sentimental Memory*: Times-Italic 9.5pt with 13pt leading, set inside an asymmetric indented block (restricting margins to give breathing room).
    *   **Image Ingestion Guard**: If the `image_uri` points to a remote URL (e.g. GCS), the PDF worker downloads the image bytes into an `io.BytesIO` buffer. If remote download fails or the image file does not exist, substitute with a styled default placeholder block (a flat light-grey rectangle containing the text "Keepsake Photo" in Helvetica).
    *   **Separation Spacing**: Separated by a `0.75in` vertical spacer between blocks. `KeepTogether` constraints ensure that no keepsake entry is awkwardly split across pages.
4.  **Cryptographic Monospace Seal**:
    *   Positioned at the end of the document inside a single-cell Table flowable with a light grey border.
    *   Renders the final SHA-256 block hash from `audit_logs` in `Courier` 8pt:
        `SHA-256 Seal: [hash]`
    *   This establishes a verifiable physical link to the tamper-proof ledger.

#### Document B: The Final Distribution & Probate Audit Ledger PDF (`GET /api/sessions/{session_id}/keepsake`)
1.  **Cover Page**:
    *   Large Title: `[Session Title] Final Distribution & Probate Audit Ledger`.
    *   Sub-metadata: Executor Name, Start Date, Closure Date, and statement: *"Official estate distribution record for probate court filing."*
    *   A horizontal dividing bar in Sage-Green (2pt thickness).
    *   `PageBreak()` to start content on Page 2.
2.  **Registered Beneficiary Table**:
    *   A Table flowable detailing all registered heirs. Columns: Name, Registered Email, Profile Created Date (`created_at`), and Participation Status (`SUBMITTED` | `ABSTAINED` | `EXPIRED_NON_PARTICIPATING`).
3.  **Proof of Notice Log**:
    *   A chronological list or table proving due notice was dispatched. Displays when invitation tokens were created, when the SMTP dispatches completed (`invitation_dispatched_at`), and the expiration boundaries (`invite_token_expires_at`).
4.  **Final Asset Allocation Grid**:
    *   A comprehensive Table flowable listing each asset in the session. Columns: Image (`1.2in`), Title/Description/Valuation Source (`2.8in`), Allocated Beneficiary (`1.8in`), and Appraisal Range & Valuation Source (`1.2in`). (Sum: 7.0in).
5.  **Maximum Nash Welfare Product Display**:
    *   Render the Maximum Nash Welfare Product of the session as a centered metadata callout box (styled in Sage-Green with a light border) immediately *above* or *below* the Asset Allocation Grid, rather than as a column in the table.
6.  **Admin Intervention Log**:
    *   A Table listing all Executor manual overrides query-extracted from `audit_logs` where `event_type == 'ADMIN_OVERRIDE'`. Columns: Timestamp, Contested Asset, Allocated Beneficiary, and Fiduciary Basis/Reason (`AdminOverrideRequest.reason`).
7.  **Points Valuation Matrix**:
    *   A grid Table flowable displaying the complete preference matrix, showing all assets (rows) and the points allocated by each Heir (columns) to provide full transparency to the court. Columns: Asset Title, Beneficiary A Points, Beneficiary B Points...
    *   **Dynamic Column Sizing**: Because the number of heirs $N$ is dynamic, column widths must be calculated programmatically: set the `Asset Title` column to `2.5in`, and split the remaining `4.5in` printable width equally among the $N$ heirs (`4.5 / N` inches per column).
    *   **Landscape Page Transition**: If the session contains more than 4 registered heirs, the document generator must dynamically rotate the Points Valuation Matrix section template to Landscape orientation. This extends the printable table width to `9.5in` (where `Asset Title` width is `3.5in` and the remaining `6.0in` is split equally among the $N$ heirs).
8.  **Mathematical Proof**:
    *   A brief, structured text explanation of the Max Nash Welfare algorithm's optimization proof, detailing that no alternative division yields a higher Nash product without starving a participant.
9.  **Cryptographic Integrity Seal**:
    *   Renders the final SHA-256 block hash in Courier 8pt with explicit instructions explaining that the ledger has been cryptographically sealed, and how to verify the SHA-256 database row checksums.

*   **ReportLab Layout Overflow Protection**: To prevent ReportLab from throwing a `LayoutError` ("Flowable too large") and crashing the compilation thread when rendering exceptionally long description texts or sentimental stories (up to 1000 characters), all table cells must use explicit column widths, and text inside `Paragraph` flowables must have dynamic row-splitting enabled. If a single table row still exceeds page capacity, the generator must truncate the text block to 500 characters and append an ellipsis ("..."), with the full un-truncated text printed in a separate appendix section at the end of the document.

---

## 14. System Logging & Debugging Standards

To ensure the production platform is fully supportable, diagnosable, and secure when running inside Docker containers on Raspberry Pi hardware, developers must enforce the following logging criteria:

### 14.1 Logger Setup & Format
*   **Engine**: Standard Python `logging` module. Output directed exclusively to `sys.stdout` and `sys.stderr` to allow standard Docker log drivers to collect and aggregate them.
*   **Format String**:
    `[%(asctime)s] [%(levelname)s] [%(name)s] [%(filename)s:%(lineno)d]: %(message)s`
*   **Level Control**: Sourced from the `LOG_LEVEL` environment variable. Defaults to `INFO`, toggleable to `DEBUG` for verbose trace output.

### 14.2 LangGraph Node Lifecycle Tracing
Every node execution inside `graph.py` must emit structured logs at the beginning and end of its execution phase:
*   **Format**: `[THREAD {thread_id}] [NODE {node_name}] - {Action details}`
*   **Examples**:
    *   `[THREAD 12-34:56-78] [NODE INGEST_PII] - Incoming raw text (Length: 148 bytes) received.`
    *   `[THREAD 12-34:56-78] [NODE FAST_MEDIATE] - Generating active listening chunk. Instruction correction flag: None.`
    *   `[THREAD 12-34:56-78] [NODE VALIDATE] - Math check: Total point allocations = 1000. Verification: SUCCESS.`
    *   `[THREAD 12-34:56-78] [NODE VALIDATE] - Math check: Total point allocations = 950. Verification: FAILED. Incrementing loopback counter to 1.`

### 14.3 Database Transaction & SQL Logging
*   **SQLAlchemy Echo**: Sourced from the `DB_ECHO` environment variable (`True` / `False`). If set to `True`, SQLAlchemy prints all raw SQL queries to stdout.
*   **Critical Points**: Developers must debug database concurrency by logging when pessimistic locks are acquired and released:
    *   `[DB_TX] - Initiating SELECT FOR UPDATE on valuations (heir_id={heir_id}). acquiring pessimistic lock.`
    *   `[DB_TX] - Commit successful. Pessimistic lock released.`

### 14.4 WebSocket Session Logs
*   **Details**: Log handshake success, JWT authentication matches, socket connection opens, close codes, and socket reconnection events.
*   **Offline Queue Logs**: Emits logs when transient messages are pushed to or flushed from the client queue.

### 14.5 PII Leakage Guard
*   **CRITICAL RULE**: Raw, un-scrubbed user text (`input_text` state variable) is **FORBIDDEN** from ever being written to standard log streams. Logs must only print the length of the string, or print the PII-scrubbed version (`scrubbed_text` populated by Microsoft Presidio). Any violation of this rule compromises user privacy.

