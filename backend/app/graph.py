"""
LangGraph State Machine — Mediation Graph (T07a)
=================================================
Defines the MediationState TypedDict, all nine operational nodes, prompt
templates, and the compiled StateGraph with retry policies.

Spec references:
  - LangGraph Spec §2–§7
  - Backend Spec §14.2 (structured logging)
  - Backend Spec §14.5 (PII Leakage Guard)
"""

import json
import logging
import operator
import re
from typing import Annotated, Any, Callable, Dict, List, Literal, Optional, Type

import httpx
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.pregel._retry import RetryPolicy
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field, ValidationError
from typing_extensions import TypedDict

from .database import DB_URL
from .presidio import scrub as presidio_scrub
from .services.llm_provider import (
    LLMProvider,
    MODEL_KEY_EMBEDDING,
    MODEL_KEY_FAST,
    MODEL_KEY_SLOW,
    get_provider,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic schemas for structured LLM outputs
# ═══════════════════════════════════════════════════════════════════════════════


class IntentResult(BaseModel):
    intent: Literal["CHAT_MEDIATION", "VALUATION_SUBMISSION", "ADMIN_OVERRIDE"]


class CritiqueResult(BaseModel):
    violation: bool
    reason: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# MediationState — authoritative TypedDict (LangGraph Spec §2)
# ═══════════════════════════════════════════════════════════════════════════════


class SharedMemorySchema(BaseModel):
    heir_username: str
    reasoning: str


class AssetSchema(BaseModel):
    id: str
    session_id: str
    title: str = Field(..., max_length=150)
    description: str
    category: str = Field(..., pattern=r"^(Jewelry|Furniture|Art|Other)$")
    valuation_min: float
    valuation_max: float
    valuation_source: Optional[str] = None
    sentiment_tag: str
    image_uri: str
    audio_uri: Optional[str] = None
    status: str = Field(..., pattern=r"^(STAGED|LIVE|PRE_ALLOCATED|DISTRIBUTED)$")
    ocr_status: Optional[str] = Field(None, pattern=r"^(PROCESSING|COMPLETED|FAILED)$")
    description_json: Optional[Dict[str, str]] = None
    allocated_to_id: Optional[str] = None
    shared_memories: List[SharedMemorySchema] = []


class ValuationSchema(BaseModel):
    asset_id: str
    heir_id: str
    points: int = Field(..., ge=0, le=1000)
    reasoning: Optional[str] = None
    is_reasoning_shared: bool = False


class MediationState(TypedDict, total=False):
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
    critique_loopback_count: int
    correction_instruction: Optional[str]
    # ── Transient fields for intra-graph routing (not persisted) ──
    routing_intent: str
    critique_passed: bool
    validation_passed: bool
    mediator_response: str
    committed: bool
    hitl_triggered: bool


# ═══════════════════════════════════════════════════════════════════════════════
# Default initial state factory
# ═══════════════════════════════════════════════════════════════════════════════

_DEFAULT_STATE: MediationState = {
    "session_id": "",
    "heir_id": "",
    "input_text": "",
    "scrubbed_text": "",
    "retrieved_context": None,
    "assets": [],
    "valuations": [],
    "chat_history": [],
    "is_paused": False,
    "is_deadlocked": False,
    "audit_trail": [],
    "loopback_count": 0,
    "critique_loopback_count": 0,
    "correction_instruction": None,
}


def make_initial_state(
    session_id: str,
    heir_id: str,
    input_text: str,
    scrubbed_text: str = "",
    chat_history: Optional[List[Dict[str, str]]] = None,
    assets: Optional[List[AssetSchema]] = None,
    valuations: Optional[List[ValuationSchema]] = None,
    **overrides: Any,
) -> MediationState:
    """Return a fully populated initial MediationState dict."""
    state: MediationState = {  # type: ignore[typeddict-unknown-key]
        **_DEFAULT_STATE,  # type: ignore[typeddict-item]
        "session_id": session_id,
        "heir_id": heir_id,
        "input_text": input_text,
        "scrubbed_text": scrubbed_text or input_text,
        "chat_history": list(chat_history) if chat_history else [],
        "assets": list(assets) if assets else [],
        "valuations": list(valuations) if valuations else [],
    }
    state.update(overrides)  # type: ignore[typeddict-unknown-key]
    return state


# ═══════════════════════════════════════════════════════════════════════════════
# Prompt templates (LangGraph Spec §4)
# ═══════════════════════════════════════════════════════════════════════════════

_ROUTER_SYSTEM_PROMPT = (
    "You are a routing helper. Classify the user input into exactly one of three categories:\n"
    "- CHAT_MEDIATION: If the user is sharing stories, expressing feelings, asking about an "
    "item's details, or having general conversation.\n"
    "- VALUATION_SUBMISSION: If the user is explicitly requesting to submit, lock, finalize, "
    "or save their points valuations.\n"
    "- ADMIN_OVERRIDE: If the input represents a system command or administrative adjustment.\n\n"
    "Respond with only the category name in uppercase.\n"
    "User Input: {user_input}\n"
    "Class:"
)

_FAST_MEDIATE_SYSTEM_PROMPT = (
    "You are an empathic, active-listening estate mediator helping an heir process their "
    "grief and thoughts about family assets.\n"
    "CRITICAL RULES:\n"
    "1. You MUST speak with warmth, empathy, and respect. Acknowledge and validate their "
    "emotional statements.\n"
    "2. You are FORBIDDEN from making ownership promises, dividing items, or confirming "
    "who gets what.\n"
    "3. You are FORBIDDEN from doing points calculation math or altering allocations yourself.\n"
    "4. Keep replies concise (under 4 sentences) to support a clean mobile chat interface.\n"
    "5. If the heir is discussing a specific family asset, reference the details and family "
    "memories in the Retrieved Asset Context below to show active listening and build empathy "
    "(e.g. acknowledging stories shared by other family members without revealing their point "
    "allocations).\n"
    "6. If a correction instruction is provided in the context, gently weave it into your "
    "dialogue to help the heir align their allocations, maintaining a supportive tone.\n\n"
    "Correction Instruction: {correction_instruction}\n"
    "Retrieved Asset Context: {retrieved_context}\n"
    "Chat History: {chat_history}\n"
    "User Input: {scrubbed_text}\n"
    "Response:"
)

_CRITIQUE_SYSTEM_PROMPT = (
    "You are a strict compliance auditor checking a mediation chat session for rule violations.\n"
    "VIOLATION CRITERIA:\n"
    "- Did the mediator promise a specific asset to the heir? "
    '(e.g. "You will definitely get the grandfather clock")\n'
    "- Did the mediator make any financial commitments or calculations?\n\n"
    "Review the latest interaction:\n"
    "Mediator Response: {mediator_response}\n\n"
    "Output a JSON block:\n"
    '{{"violation": true/false, "reason": "description of violation if any, otherwise empty"}}'
)

_COMPLIANCE_FALLBACK = (
    "I am here to listen and help you catalog your feelings and stories about the estate, "
    "but I cannot promise ownership or make financial allocations. "
    "Let's focus on what this keepsake means to you."
)

# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

# Simple sentence-splitting regex: matches sentence-ending punctuation followed
# by whitespace or end-of-string.
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> List[str]:
    """Split *text* into a list of individual sentences."""
    raw = _SENTENCE_RE.split(text.strip())
    if not raw:
        return []
    # Filter out empty strings and strip each
    return [s.strip() for s in raw if s.strip()]


def _enforce_sentence_limit(text: str, max_sentences: int = 4) -> str:
    """Post-generation truncation enforcing the 4-sentence constraint."""
    sentences = _split_sentences(text)
    if len(sentences) <= max_sentences:
        return text
    truncated = " ".join(sentences[:max_sentences])
    logger.debug(
        "[MEDIATION_GRAPH] Sentence limit enforced: %d → %d sentences",
        len(sentences),
        max_sentences,
    )
    return truncated


def _format_chat_history_for_prompt(chat_history: List[Dict[str, str]]) -> str:
    """Format chat history as a text block for the LLM prompt."""
    if not chat_history:
        return "(No prior conversation)"
    lines: List[str] = []
    for msg in chat_history:
        sender = msg.get("sender", "unknown")
        text = msg.get("text", "")
        lines.append(f"[{sender}]: {text}")
    return "\n".join(lines)


def _thread_log(thread_id: str, node_name: str, action: str) -> None:
    """Emit a structured lifecycle log entry per Backend Spec §14.2."""
    logger.info(
        "[THREAD %s] [NODE %s] - %s",
        thread_id,
        node_name,
        action,
    )


def _pii_safe_log(thread_id: str, node_name: str, scrubbed_text: str) -> None:
    """Log only scrubbed text length — PII Leakage Guard per Backend Spec §14.5."""
    logger.info(
        "[THREAD %s] [NODE %s] - Scrubbed text length: %d bytes",
        thread_id,
        node_name,
        len(scrubbed_text),
    )


def _get_thread_id(state: MediationState) -> str:
    return f"{state.get('session_id', '')}:{state.get('heir_id', '')}"


# ═══════════════════════════════════════════════════════════════════════════════
# JSON self-correction loop (LangGraph Spec §7.2)
# ═══════════════════════════════════════════════════════════════════════════════

_MAX_JSON_RETRIES = 2


def _generate_structured_with_healing(
    provider: LLMProvider,
    model_key: str,
    system_prompt: str,
    user_input: str,
    response_model: Type[BaseModel],
    temperature: float,
    thread_id: str,
    node_name: str,
) -> BaseModel:
    """Call provider.generate_structured with automatic JSON healing."""
    for attempt in range(_MAX_JSON_RETRIES + 1):
        try:
            return provider.generate_structured(
                model_key=model_key,
                system_prompt=system_prompt,
                user_input=user_input,
                response_model=response_model,
                temperature=temperature,
            )
        except (json.JSONDecodeError, ValidationError) as exc:
            if attempt < _MAX_JSON_RETRIES:
                logger.warning(
                    "[THREAD %s] [NODE %s] - JSON parse error (attempt %d/%d): %s. Retrying.",
                    thread_id,
                    node_name,
                    attempt + 1,
                    _MAX_JSON_RETRIES + 1,
                    exc,
                )
                # Append the error context to the user input for the retry
                user_input = (
                    f"{user_input}\n\n"
                    f"Your previous output was malformed: {exc}. "
                    f"Please rewrite the response and output ONLY valid JSON "
                    f"matching the schema."
                )
            else:
                logger.error(
                    "[THREAD %s] [NODE %s] - JSON healing exhausted after %d attempts",
                    thread_id,
                    node_name,
                    _MAX_JSON_RETRIES + 1,
                )
                raise


# ═══════════════════════════════════════════════════════════════════════════════
# Graph builder
# ═══════════════════════════════════════════════════════════════════════════════


def build_graph(
    provider: Optional[LLMProvider] = None,
    db_session_factory: Optional[Callable[[], Any]] = None,
    checkpointer: Optional[Any] = None,
) -> CompiledStateGraph:
    """Build and compile the LangGraph mediation state machine.

    Parameters
    ----------
    provider:
        LLMProvider instance.  If *None*, uses the module-level singleton.
    db_session_factory:
        Optional callable returning a SQLAlchemy Session for RAG queries.
        If *None*, the RETRIEVE_RAG node will set ``retrieved_context``
        to a placeholder string.
    """
    if provider is None:
        provider = get_provider()

    # ──────────────────────────────────────────────────────────────────
    # Node implementations
    # ──────────────────────────────────────────────────────────────────

    def _ingest_pii(state: MediationState) -> MediationState:
        """INGEST_PII Node — System 2 Gateway (LangGraph Spec §4.1)."""
        thread_id = _get_thread_id(state)
        node_name = "INGEST_PII"
        raw_text = state.get("input_text", "")
        _thread_log(thread_id, node_name, f"Incoming raw text (Length: {len(raw_text)} bytes) received.")
        scrubbed = presidio_scrub(raw_text) if raw_text else ""
        _pii_safe_log(thread_id, node_name, scrubbed)
        _thread_log(thread_id, node_name, "Scrubbing complete. State updated.")
        return {  # type: ignore[return-value]
            "scrubbed_text": scrubbed,
        }

    def _router_node(state: MediationState) -> MediationState:
        """ROUTER_NODE — Smart Intent Router (LangGraph Spec §4.2)."""
        thread_id = _get_thread_id(state)
        node_name = "ROUTER_NODE"
        _thread_log(thread_id, node_name, "Classifying user intent.")
        scrubbed = state.get("scrubbed_text", "")
        _pii_safe_log(thread_id, node_name, scrubbed)

        # Format the prompt with the scrubbed text
        user_input = _ROUTER_SYSTEM_PROMPT.format(user_input=scrubbed)

        try:
            result = _generate_structured_with_healing(
                provider=provider,
                model_key=MODEL_KEY_FAST,
                system_prompt="",
                user_input=user_input,
                response_model=IntentResult,
                temperature=0.0,
                thread_id=thread_id,
                node_name=node_name,
            )
            intent = result.intent
        except Exception:
            logger.warning(
                "[THREAD %s] [NODE %s] - Router JSON healing exhausted. Defaulting to CHAT_MEDIATION.",
                thread_id,
                node_name,
            )
            intent = "CHAT_MEDIATION"

        _thread_log(thread_id, node_name, f"Classified intent: {intent}")
        # Store intent as an audit trail entry for routing decisions
        audit = list(state.get("audit_trail", []))
        audit.append(f"ROUTER: {intent}")
        return {  # type: ignore[return-value]
            "audit_trail": audit,
            "routing_intent": intent,  # transient; used only by conditional edges
        }

    def _retrieve_rag(state: MediationState) -> MediationState:
        """RETRIEVE_RAG Node — System 2 Retrieval Gateway (LangGraph Spec §4.2b)."""
        thread_id = _get_thread_id(state)
        node_name = "RETRIEVE_RAG"
        _thread_log(thread_id, node_name, "Querying vector store for relevant asset context.")
        scrubbed = state.get("scrubbed_text", "")
        session_id = state.get("session_id", "")
        heir_id = state.get("heir_id", "")

        if db_session_factory is None or not scrubbed or not session_id:
            _thread_log(thread_id, node_name, "No DB session factory or empty query — skipping RAG.")
            return {  # type: ignore[return-value]
                "retrieved_context": "No specific asset matches found in query.",
            }

        db = db_session_factory()
        try:
            from sqlalchemy import text

            # 1. Get embedding vector for the scrubbed query
            embedding = provider.get_embeddings(MODEL_KEY_EMBEDDING, scrubbed)

            # 2. Query assets via pgvector cosine distance
            rows = db.execute(
                text(
                    """
                    SELECT id, title, description, category, sentiment_tag
                    FROM assets
                    WHERE session_id = :session_id AND status = 'LIVE'
                    ORDER BY embedding <=> :query_vector
                    LIMIT 2
                    """
                ),
                {
                    "session_id": session_id,
                    "query_vector": embedding,
                },
            ).fetchall()

            if not rows:
                _thread_log(thread_id, node_name, "No matching assets found.")
                return {  # type: ignore[return-value]
                    "retrieved_context": "No specific asset matches found in query.",
                }

            # 3. For each asset, fetch related shared memories
            context_parts: List[str] = ["Retrieved Asset Context:"]
            for row in rows:
                asset_id = row[0]
                title = row[1]
                desc = row[2]
                category = row[3]
                sentiment = row[4]
                context_parts.append(
                    f"- Asset: {title} (Category: {category})\n"
                    f"  Description: {desc}\n"
                    f"  Sentiment: {sentiment}"
                )

                # 3b. Query shared memories
                mem_rows = db.execute(
                    text(
                        """
                        SELECT u.username, v.reasoning
                        FROM valuations v
                        JOIN users u ON v.heir_id = u.id
                        WHERE v.asset_id = :asset_id
                          AND v.reasoning IS NOT NULL
                          AND (v.is_reasoning_shared = true OR v.heir_id = :current_heir_id)
                        """
                    ),
                    {"asset_id": asset_id, "current_heir_id": heir_id},
                ).fetchall()

                if mem_rows:
                    context_parts.append("  Family Memories:")
                    for mem in mem_rows:
                        context_parts.append(f'    * {mem[0]}: "{mem[1]}"')

            full_context = "\n".join(context_parts)
            _thread_log(thread_id, node_name, f"RAG returned {len(rows)} asset(s).")
            return {  # type: ignore[return-value]
                "retrieved_context": full_context,
            }
        except Exception as exc:
            logger.error(
                "[THREAD %s] [NODE %s] - RAG query failed: %s",
                thread_id,
                node_name,
                exc,
            )
            return {  # type: ignore[return-value]
                "retrieved_context": "No specific asset matches found in query.",
            }
        finally:
            db.close()

    def _fast_mediate_node(state: MediationState) -> MediationState:
        """FAST_MEDIATE_NODE — System 1 Conversation (LangGraph Spec §4.3)."""
        thread_id = _get_thread_id(state)
        node_name = "FAST_MEDIATE"
        correction = state.get("correction_instruction") or "None"
        _thread_log(
            thread_id,
            node_name,
            f"Generating active listening chunk. Instruction correction flag: {correction}.",
        )

        scrubbed = state.get("scrubbed_text", "")
        retrieved = state.get("retrieved_context") or "No specific asset matches found in query."
        chat_history = state.get("chat_history", [])
        hist_str = _format_chat_history_for_prompt(chat_history)

        user_input = _FAST_MEDIATE_SYSTEM_PROMPT.format(
            correction_instruction=correction,
            retrieved_context=retrieved,
            chat_history=hist_str,
            scrubbed_text=scrubbed,
        )

        raw_response = provider.generate_text(
            model_key=MODEL_KEY_FAST,
            system_prompt="",
            user_input=user_input,
            temperature=0.5,
            history=None,
        )

        # Post-generation 4-sentence enforcement
        truncated = _enforce_sentence_limit(raw_response, max_sentences=4)

        _thread_log(thread_id, node_name, f"Response generated ({len(truncated)} chars).")
        _pii_safe_log(thread_id, node_name, truncated)
        return {  # type: ignore[return-value]
            "mediator_response": truncated,  # transient — consumed by critique node
        }

    def _slow_critique_node(state: MediationState) -> MediationState:
        """SLOW_CRITIQUE_NODE — System 2 Chat Audit (LangGraph Spec §4.4)."""
        thread_id = _get_thread_id(state)
        node_name = "SLOW_CRITIQUE"
        _thread_log(thread_id, node_name, "Auditing mediator response for compliance violations.")

        mediator_response = state.get("mediator_response", "")
        critique_count = state.get("critique_loopback_count", 0)

        user_input = _CRITIQUE_SYSTEM_PROMPT.format(mediator_response=mediator_response)

        try:
            result = _generate_structured_with_healing(
                provider=provider,
                model_key=MODEL_KEY_SLOW,
                system_prompt="",
                user_input=user_input,
                response_model=CritiqueResult,
                temperature=0.0,
                thread_id=thread_id,
                node_name=node_name,
            )
        except Exception:
            logger.warning(
                "[THREAD %s] [NODE %s] - Critique JSON healing exhausted. Defaulting to violation=true.",
                thread_id,
                node_name,
            )
            result = CritiqueResult(violation=True, reason="Critique node JSON parsing exhausted — safety fallback.")

        if not result.violation:
            _thread_log(thread_id, node_name, "Compliance check: PASSED. Resetting critique counter.")
            # Append mediator response to chat history
            chat = list(state.get("chat_history", []))
            chat.append({"sender": "agent", "text": mediator_response})
            return {  # type: ignore[return-value]
                "chat_history": chat,
                "critique_loopback_count": 0,
                "critique_passed": True,
            }

        # Violation detected
        if critique_count <= 2:
            _thread_log(
                thread_id,
                node_name,
                f"Compliance check: VIOLATION (attempt {critique_count + 1}/3). "
                f"Reason: {result.reason}. Looping back to FAST_MEDIATE.",
            )
            return {  # type: ignore[return-value]
                "critique_loopback_count": critique_count + 1,
                "correction_instruction": result.reason,
                "critique_passed": False,
            }

        # Exceeded max loopbacks — fallback
        _thread_log(
            thread_id,
            node_name,
            f"Compliance check: VIOLATION (attempt {critique_count + 1}/3). "
            "Max retries exceeded. Using fallback response.",
        )
        chat = list(state.get("chat_history", []))
        chat.append({"sender": "agent", "text": _COMPLIANCE_FALLBACK})
        return {  # type: ignore[return-value]
            "chat_history": chat,
            "critique_loopback_count": 0,
            "mediator_response": _COMPLIANCE_FALLBACK,
            "critique_passed": True,
        }

    def _slow_reflect_node(state: MediationState) -> MediationState:
        """SLOW_REFLECT_NODE — System 2 Valuation Audit (LangGraph Spec §4.4b)."""
        thread_id = _get_thread_id(state)
        node_name = "SLOW_REFLECT"
        _thread_log(thread_id, node_name, "Auditing valuations against user sentiment.")
        # For T07a, this node prepares the valuations for validation.
        # The actual sentiment cross-check is model-dependent and will be
        # finalized in T07b with the T63 model profile.
        _thread_log(thread_id, node_name, "Valuation audit complete (pass-through for T07a).")
        return {}  # type: ignore[return-value]

    def _validate_node(state: MediationState) -> MediationState:
        """VALIDATE_NODE — Mathematical Constraints (LangGraph Spec §4.5)."""
        thread_id = _get_thread_id(state)
        node_name = "VALIDATE"
        valuations = state.get("valuations", [])
        total = sum(v.points if isinstance(v, dict) else getattr(v, "points", 0) for v in valuations)
        loopback = state.get("loopback_count", 0)

        if total == 1000:
            _thread_log(thread_id, node_name, f"Math check: Total point allocations = {total}. Verification: SUCCESS.")
            return {  # type: ignore[return-value]
                "loopback_count": 0,
                "correction_instruction": None,
                "validation_passed": True,
            }

        if loopback <= 2:
            _thread_log(
                thread_id,
                node_name,
                f"Math check: Total point allocations = {total}. Verification: FAILED. "
                f"Incrementing loopback counter to {loopback + 1}.",
            )
            instruction = (
                f"Your total points ({total}) do not sum to the required 1000. "
                f"Please adjust your allocations so they total exactly 1000 points."
            )
            return {  # type: ignore[return-value]
                "loopback_count": loopback + 1,
                "correction_instruction": instruction,
                "validation_passed": False,
            }

        # Escalation — exceeds max loopbacks
        _thread_log(
            thread_id,
            node_name,
            f"Math check: Total point allocations = {total}. Verification: FAILED. "
            f"Loopback count {loopback} > 2. Escalating to HITL_GUARD.",
        )
        return {  # type: ignore[return-value]
            "loopback_count": loopback + 1,
            "correction_instruction": (
                f"Points sum validation failed after {loopback} attempts. "
                f"Executor assistance required to correct allocations."
            ),
            "validation_passed": False,
        }

    def _commit_node(state: MediationState) -> MediationState:
        """COMMIT_NODE — Data Persistence & Seal (LangGraph Spec §4.6)."""
        thread_id = _get_thread_id(state)
        node_name = "COMMIT"
        _thread_log(thread_id, node_name, "Persisting validated state and generating audit hash.")
        # T07a: The actual DB persistence and SHA-256 hashing are handled by
        # the FastAPI router that invokes the graph. This node resets loopback
        # counters per LangGraph Spec §6.4.
        audit = list(state.get("audit_trail", []))
        audit.append("COMMIT: valuations persisted")
        return {  # type: ignore[return-value]
            "audit_trail": audit,
            "loopback_count": 0,
            "critique_loopback_count": 0,
            "correction_instruction": None,
            "committed": True,
        }

    def _hitl_guard_node(state: MediationState) -> MediationState:
        """HITL_GUARD — Human-in-the-Loop Executor Console (LangGraph Spec §4.7)."""
        thread_id = _get_thread_id(state)
        node_name = "HITL_GUARD"
        _thread_log(thread_id, node_name, "Execution halted — awaiting Executor intervention.")
        return {  # type: ignore[return-value]
            "is_deadlocked": True,
            "hitl_triggered": True,
        }

    # ──────────────────────────────────────────────────────────────────
    # Conditional routing functions
    # ──────────────────────────────────────────────────────────────────

    def _route_intent(state: MediationState) -> str:
        """After ROUTER_NODE: route based on classified intent."""
        intent = state.get("routing_intent", "CHAT_MEDIATION")
        if intent == "VALUATION_SUBMISSION":
            return "SLOW_REFLECT"
        elif intent == "ADMIN_OVERRIDE":
            return "HITL_GUARD"
        return "RETRIEVE_RAG"  # CHAT_MEDIATION (default)

    def _route_after_critique(state: MediationState) -> str:
        """After SLOW_CRITIQUE: route to END or loop back."""
        if state.get("critique_passed"):
            return END
        return "FAST_MEDIATE"

    def _route_after_validate(state: MediationState) -> str:
        """After VALIDATE: route to COMMIT, RETRIEVE_RAG, or HITL_GUARD."""
        if state.get("validation_passed"):
            return "COMMIT"
        loopback = state.get("loopback_count", 0)
        if loopback > 2:
            return "HITL_GUARD"
        return "RETRIEVE_RAG"

    # ──────────────────────────────────────────────────────────────────
    # Build & compile the graph
    # ──────────────────────────────────────────────────────────────────

    builder = StateGraph(MediationState)

    # Retry policy applied to LLM-dependent nodes per LangGraph Spec §7.1
    llm_retry_policy = RetryPolicy(
        max_attempts=3,
        initial_interval=1.0,
        backoff_factor=2.0,
        retry_on=(httpx.ConnectTimeout, httpx.ReadTimeout, httpx.HTTPStatusError),
    )

    # Add nodes — retry policy only on LLM-dependent nodes
    builder.add_node("INGEST_PII", _ingest_pii)
    builder.add_node("ROUTER_NODE", _router_node, retry_policy=llm_retry_policy)
    builder.add_node("RETRIEVE_RAG", _retrieve_rag)
    builder.add_node("FAST_MEDIATE", _fast_mediate_node, retry_policy=llm_retry_policy)
    builder.add_node("SLOW_CRITIQUE", _slow_critique_node, retry_policy=llm_retry_policy)
    builder.add_node("SLOW_REFLECT", _slow_reflect_node, retry_policy=llm_retry_policy)
    builder.add_node("VALIDATE", _validate_node)
    builder.add_node("COMMIT", _commit_node)
    builder.add_node("HITL_GUARD", _hitl_guard_node)

    # Edges — primary flow
    builder.set_entry_point("INGEST_PII")
    builder.add_edge("INGEST_PII", "ROUTER_NODE")

    builder.add_conditional_edges(
        "ROUTER_NODE",
        _route_intent,
        {
            "RETRIEVE_RAG": "RETRIEVE_RAG",
            "SLOW_REFLECT": "SLOW_REFLECT",
            "HITL_GUARD": "HITL_GUARD",
        },
    )

    # CHAT_MEDIATION path
    builder.add_edge("RETRIEVE_RAG", "FAST_MEDIATE")
    builder.add_edge("FAST_MEDIATE", "SLOW_CRITIQUE")
    builder.add_conditional_edges(
        "SLOW_CRITIQUE",
        _route_after_critique,
        {
            "FAST_MEDIATE": "FAST_MEDIATE",
            END: END,
        },
    )

    # VALUATION_SUBMISSION path
    builder.add_edge("SLOW_REFLECT", "VALIDATE")
    builder.add_conditional_edges(
        "VALIDATE",
        _route_after_validate,
        {
            "COMMIT": "COMMIT",
            "RETRIEVE_RAG": "RETRIEVE_RAG",
            "HITL_GUARD": "HITL_GUARD",
        },
    )

    builder.add_edge("COMMIT", END)
    builder.add_edge("HITL_GUARD", END)

    if checkpointer is not None:
        graph = builder.compile(
            checkpointer=checkpointer,
            interrupt_before=["HITL_GUARD"],
        )
    else:
        graph = builder.compile()

    return graph


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level convenience — default compiled graph instance
# ═══════════════════════════════════════════════════════════════════════════════

_default_graph: Optional[CompiledStateGraph] = None
_pool: Optional[ConnectionPool] = None
_checkpointer: Optional[PostgresSaver] = None


def get_postgres_checkpointer() -> PostgresSaver:
    """Initialize and return the persistent PostgreSQL checkpointer."""
    global _pool, _checkpointer
    if _checkpointer is None:
        # Convert SQLAlchemy connection URL to standard PostgreSQL URI for psycopg
        conn_info = DB_URL.replace("postgresql+psycopg2://", "postgresql://")
        _pool = ConnectionPool(
            conninfo=conn_info,
            max_size=10,
            kwargs={
                "autocommit": True,
                "row_factory": dict_row,
            },
        )
        _checkpointer = PostgresSaver(_pool)
        _checkpointer.setup()
    return _checkpointer


def reset_postgres_checkpointer() -> None:
    """Close the connection pool and reset the checkpointer singleton."""
    global _pool, _checkpointer
    if _pool is not None:
        try:
            _pool.close()
        except Exception:
            pass
        _pool = None
    _checkpointer = None


def get_graph(
    provider: Optional[LLMProvider] = None,
    db_session_factory: Optional[Callable[[], Any]] = None,
) -> CompiledStateGraph:
    """Return the default compiled mediation graph (lazy singleton)."""
    global _default_graph
    if _default_graph is None:
        checkpointer = get_postgres_checkpointer()
        _default_graph = build_graph(
            provider=provider,
            db_session_factory=db_session_factory,
            checkpointer=checkpointer,
        )
    return _default_graph


def reset_graph() -> None:
    """Reset the cached graph instance (useful in tests)."""
    global _default_graph
    _default_graph = None
    reset_postgres_checkpointer()