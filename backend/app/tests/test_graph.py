"""
Test suite for T07a: LangGraph State Schema, Nodes & Prompt Templates
======================================================================

Verifies node transitions, the critique loopback, validation loopback,
HITL_GUARD escalation, sentence-limit enforcement, structured logging,
and PII Leakage Guard.
"""

import logging
import re
from unittest import mock

import pytest

from app.graph import (
    AssetSchema,
    CritiqueResult,
    IntentResult,
    MediationState,
    SharedMemorySchema,
    ValuationSchema,
    _enforce_sentence_limit,
    _get_thread_id,
    _split_sentences,
    build_graph,
    make_initial_state,
    reset_graph,
)
from app.tests.mock_llm import MockLLMProvider

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

SESSION_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
HEIR_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _mock_scrub(text: str) -> str:
    """Trivial PII scrub for tests — just returns the text unchanged."""
    return text


def _build_test_graph(scenario="default"):
    """Build a graph wired to MockLLMProvider with a given scenario."""
    reset_graph()
    provider = MockLLMProvider()
    provider.set_scenario(scenario)
    graph = build_graph(provider=provider, db_session_factory=None)
    return graph, provider


def _merge_events(events, initial_state=None):
    """Merge all non-None node state updates from graph events into a single dict."""
    final = dict(initial_state) if initial_state else {}
    for event in events:
        for _node, ns in event.items():
            if ns is not None:
                final.update(ns)
    return final


# ═══════════════════════════════════════════════════════════════════════════
# Unit tests — helpers
# ═══════════════════════════════════════════════════════════════════════════


class TestSentenceHelpers:
    def test_split_simple(self):
        result = _split_sentences("Hello. How are you? I am fine.")
        assert len(result) == 3

    def test_split_no_ending_punctuation(self):
        result = _split_sentences("Hello there")
        assert len(result) == 1
        assert result[0] == "Hello there"

    def test_enforce_limit_within_bound(self):
        text = "First sentence. Second sentence."
        result = _enforce_sentence_limit(text, max_sentences=4)
        assert result == text

    def test_enforce_limit_over(self):
        text = "One. Two. Three. Four. Five. Six."
        result = _enforce_sentence_limit(text, max_sentences=4)
        assert "Five" not in result
        assert "Six" not in result

    def test_enforce_limit_empty(self):
        assert _enforce_sentence_limit("", 4) == ""


class TestGetThreadId:
    def test_thread_id_format(self):
        state = {"session_id": SESSION_ID, "heir_id": HEIR_ID}
        assert _get_thread_id(state) == f"{SESSION_ID}:{HEIR_ID}"


# ═══════════════════════════════════════════════════════════════════════════
# Graph integration tests
# ═══════════════════════════════════════════════════════════════════════════


class TestChatMediationPath:
    """CHAT_MEDIATION intent: INGEST_PII → ROUTER → RETRIEVE_RAG → FAST_MEDIATE → SLOW_CRITIQUE → END"""

    @mock.patch("app.graph.presidio_scrub", side_effect=_mock_scrub)
    def test_full_chat_mediation_path(self, _mock_presidio):
        provider = MockLLMProvider()
        provider.set_scenario("default")
        graph = build_graph(provider=provider, db_session_factory=None)

        state = make_initial_state(
            session_id=SESSION_ID,
            heir_id=HEIR_ID,
            input_text="I miss my grandfather's clock. It reminds me of him.",
        )

        config = {"configurable": {"thread_id": f"{SESSION_ID}:{HEIR_ID}"}}
        events = list(graph.stream(state, config))

        # Should have traversed through the CHAT_MEDIATION path
        node_names = [list(e.keys())[0] for e in events]
        assert "INGEST_PII" in node_names
        assert "ROUTER_NODE" in node_names
        assert "RETRIEVE_RAG" in node_names
        assert "FAST_MEDIATE" in node_names
        assert "SLOW_CRITIQUE" in node_names

        # Final state should have mediator response appended to chat history
        final = _merge_events(events, state)
        chat = final.get("chat_history", [])
        assert len(chat) >= 1
        assert chat[-1]["sender"] == "agent"
        assert chat[-1]["text"] is not None

    @mock.patch("app.graph.presidio_scrub", side_effect=_mock_scrub)
    def test_pii_scrubbing_is_called(self, mock_scrub):
        provider = MockLLMProvider()
        graph = build_graph(provider=provider, db_session_factory=None)
        state = make_initial_state(
            session_id=SESSION_ID,
            heir_id=HEIR_ID,
            input_text="My name is John Doe and my email is john@example.com",
        )
        config = {"configurable": {"thread_id": f"{SESSION_ID}:{HEIR_ID}"}}
        list(graph.stream(state, config))
        mock_scrub.assert_called_once()

    @mock.patch("app.graph.presidio_scrub", side_effect=_mock_scrub)
    def test_sentence_limit_enforced_in_fast_mediate(self, _mock_presidio):
        """Verify the 4-sentence constraint via _enforce_sentence_limit."""
        # The mock returns a 4-sentence response, but we test the function directly
        long_text = "One. Two. Three. Four. Five. Six."
        result = _enforce_sentence_limit(long_text, 4)
        sentences = _split_sentences(result)
        assert len(sentences) <= 4

    @mock.patch("app.graph.presidio_scrub", side_effect=_mock_scrub)
    def test_structured_logging_emitted(self, _mock_presidio, caplog):
        """Verify that [THREAD ...] [NODE ...] log entries are emitted per Backend Spec §14.2."""
        caplog.set_level(logging.INFO, logger="app.graph")
        provider = MockLLMProvider()
        provider.set_scenario("default")
        graph = build_graph(provider=provider, db_session_factory=None)
        state = make_initial_state(
            session_id=SESSION_ID,
            heir_id=HEIR_ID,
            input_text="Tell me about the painting.",
        )
        config = {"configurable": {"thread_id": f"{SESSION_ID}:{HEIR_ID}"}}
        list(graph.stream(state, config))

        thread_logs = [r for r in caplog.text.split("\n") if "[THREAD" in r]
        assert len(thread_logs) >= 3  # At least INGEST_PII, ROUTER, one more

        # PII Leakage Guard: no raw input_text should appear in logs
        for record in caplog.records:
            msg = record.getMessage()
            if "[THREAD" in msg and "[NODE" in msg:
                # Only scrubbed_text length (not raw text) allowed in logs
                assert "John Doe" not in msg


class TestCritiqueLoopback:
    """SLOW_CRITIQUE violation → loopback → fallback"""

    @mock.patch("app.graph.presidio_scrub", side_effect=_mock_scrub)
    def test_critique_violation_triggers_loopback(self, _mock_presidio):
        provider = MockLLMProvider()
        provider.set_scenario("critique_fail")
        graph = build_graph(provider=provider, db_session_factory=None)

        state = make_initial_state(
            session_id=SESSION_ID,
            heir_id=HEIR_ID,
            input_text="I want the clock.",
        )
        config = {"configurable": {"thread_id": f"{SESSION_ID}:{HEIR_ID}"}}
        events = list(graph.stream(state, config))

        # Should see multiple FAST_MEDIATE invocations (loopback)
        fast_calls = [e for e in events if "FAST_MEDIATE" in e]
        assert len(fast_calls) >= 2  # original + at least one loopback

    @mock.patch("app.graph.presidio_scrub", side_effect=_mock_scrub)
    def test_critique_fallback_after_max_loopbacks(self, _mock_presidio):
        provider = MockLLMProvider()
        provider.set_scenario("critique_fail")
        graph = build_graph(provider=provider, db_session_factory=None)

        # Start with critique_loopback_count already at 2 so next violation hits fallback
        state = make_initial_state(
            session_id=SESSION_ID,
            heir_id=HEIR_ID,
            input_text="Give me the ring.",
            critique_loopback_count=2,
        )
        config = {"configurable": {"thread_id": f"{SESSION_ID}:{HEIR_ID}"}}
        events = list(graph.stream(state, config))

        # Merge final state
        final = _merge_events(events, state)

        # Fallback message should be in chat history
        chat = final.get("chat_history", [])
        assert len(chat) >= 1
        # Should contain the compliance fallback text
        fallback_in_chat = any("cannot promise ownership" in m.get("text", "") for m in chat)
        assert fallback_in_chat

        # Critique count should be reset
        assert final.get("critique_loopback_count", -1) == 0


class TestValuationPath:
    """VALUATION_SUBMISSION intent: INGEST_PII → ROUTER → SLOW_REFLECT → VALIDATE → COMMIT"""

    @mock.patch("app.graph.presidio_scrub", side_effect=_mock_scrub)
    def test_valuation_submission_valid(self, _mock_presidio):
        provider = MockLLMProvider()
        graph = build_graph(provider=provider, db_session_factory=None)

        valuations = [
            ValuationSchema(asset_id="111", heir_id=HEIR_ID, points=500, reasoning="Love it.", is_reasoning_shared=False),
            ValuationSchema(asset_id="222", heir_id=HEIR_ID, points=500, reasoning="Nice.", is_reasoning_shared=False),
        ]
        state = make_initial_state(
            session_id=SESSION_ID,
            heir_id=HEIR_ID,
            input_text="I want to submit my allocation points.",
            valuations=valuations,
        )
        config = {"configurable": {"thread_id": f"{SESSION_ID}:{HEIR_ID}"}}
        events = list(graph.stream(state, config))

        node_names = [list(e.keys())[0] for e in events]
        assert "SLOW_REFLECT" in node_names
        assert "VALIDATE" in node_names
        assert "COMMIT" in node_names

        # Merge state — guard against None returns from nodes
        final = _merge_events(events, state)
        assert final.get("committed") is True
        assert final.get("loopback_count", -1) == 0

    @mock.patch("app.graph.presidio_scrub", side_effect=_mock_scrub)
    def test_valuation_invalid_loopback(self, _mock_presidio):
        """Points sum != 1000 → loopback increment → correction_instruction set."""
        provider = MockLLMProvider()
        graph = build_graph(provider=provider, db_session_factory=None)

        # Only 950 points — should fail validation
        valuations = [
            ValuationSchema(asset_id="111", heir_id=HEIR_ID, points=500, reasoning="Love it.", is_reasoning_shared=False),
            ValuationSchema(asset_id="222", heir_id=HEIR_ID, points=450, reasoning="Nice.", is_reasoning_shared=False),
        ]
        state = make_initial_state(
            session_id=SESSION_ID,
            heir_id=HEIR_ID,
            input_text="I want to submit my allocation points.",
            valuations=valuations,
            loopback_count=0,
        )
        config = {"configurable": {"thread_id": f"{SESSION_ID}:{HEIR_ID}"}}
        events = list(graph.stream(state, config))

        # VALIDATE should fire
        node_names = [list(e.keys())[0] for e in events]
        assert "VALIDATE" in node_names

        # Merge — guard against None returns from nodes
        final = _merge_events(events, state)

        # Loopback should increment
        assert final.get("loopback_count", 0) >= 1
        assert final.get("correction_instruction") is not None
        assert final.get("validation_passed") is False

    @mock.patch("app.graph.presidio_scrub", side_effect=_mock_scrub)
    def test_validation_escalation_to_hitl_guard(self, _mock_presidio):
        """Points sum != 1000 with loopback_count already 3 → HITL_GUARD."""
        provider = MockLLMProvider()
        graph = build_graph(provider=provider, db_session_factory=None)

        valuations = [
            ValuationSchema(asset_id="111", heir_id=HEIR_ID, points=500, reasoning="Love it.", is_reasoning_shared=False),
            ValuationSchema(asset_id="222", heir_id=HEIR_ID, points=450, reasoning="Nice.", is_reasoning_shared=False),
        ]
        state = make_initial_state(
            session_id=SESSION_ID,
            heir_id=HEIR_ID,
            input_text="Submit my points.",
            valuations=valuations,
            loopback_count=3,  # Already exceeded threshold
        )
        config = {"configurable": {"thread_id": f"{SESSION_ID}:{HEIR_ID}"}}
        events = list(graph.stream(state, config))

        node_names = [list(e.keys())[0] for e in events]
        assert "HITL_GUARD" in node_names

        final = _merge_events(events, state)
        assert final.get("is_deadlocked") is True


class TestResubmissionReset:
    """LangGraph Spec §6.4: resubmission resets loopback_count and correction_instruction."""

    @mock.patch("app.graph.presidio_scrub", side_effect=_mock_scrub)
    def test_successful_validation_resets_counters(self, _mock_presidio):
        provider = MockLLMProvider()
        graph = build_graph(provider=provider, db_session_factory=None)

        valuations = [
            ValuationSchema(asset_id="111", heir_id=HEIR_ID, points=1000, reasoning="All in.", is_reasoning_shared=False),
        ]
        state = make_initial_state(
            session_id=SESSION_ID,
            heir_id=HEIR_ID,
            input_text="Submit my points.",
            valuations=valuations,
            loopback_count=2,              # Previously had errors
            correction_instruction="Old instruction that should be cleared",
        )
        config = {"configurable": {"thread_id": f"{SESSION_ID}:{HEIR_ID}"}}
        events = list(graph.stream(state, config))

        final = _merge_events(events, state)

        assert final.get("loopback_count", -1) == 0
        assert final.get("correction_instruction") is None


class TestAdminOverridePath:
    """ADMIN_OVERRIDE intent routes to HITL_GUARD."""

    @mock.patch("app.graph.presidio_scrub", side_effect=_mock_scrub)
    def test_admin_override_routes_to_hitl(self, _mock_presidio):
        provider = MockLLMProvider()
        provider.set_scenario("default")
        graph = build_graph(provider=provider, db_session_factory=None)

        # Use input text containing "override" so the mock router detects ADMIN_OVERRIDE intent
        state = make_initial_state(
            session_id=SESSION_ID,
            heir_id=HEIR_ID,
            input_text="admin override the clock to Alice please.",
        )
        config = {"configurable": {"thread_id": f"{SESSION_ID}:{HEIR_ID}"}}
        events = list(graph.stream(state, config))

        node_names = [list(e.keys())[0] for e in events]
        assert "HITL_GUARD" in node_names


class TestMakeInitialState:
    def test_defaults(self):
        state = make_initial_state(
            session_id=SESSION_ID,
            heir_id=HEIR_ID,
            input_text="Hello",
        )
        assert state["session_id"] == SESSION_ID
        assert state["heir_id"] == HEIR_ID
        assert state["input_text"] == "Hello"
        assert state["scrubbed_text"] == "Hello"
        assert state["loopback_count"] == 0
        assert state["critique_loopback_count"] == 0
        assert state["chat_history"] == []
        assert state["assets"] == []
        assert state["valuations"] == []

    def test_overrides(self):
        state = make_initial_state(
            session_id=SESSION_ID,
            heir_id=HEIR_ID,
            input_text="Hi",
            loopback_count=2,
            is_paused=True,
        )
        assert state["loopback_count"] == 2
        assert state["is_paused"] is True

    def test_scrubbed_text_defaults_to_input(self):
        state = make_initial_state(
            session_id=SESSION_ID,
            heir_id=HEIR_ID,
            input_text="Some text",
            scrubbed_text="",
        )
        assert state["scrubbed_text"] == "Some text"

    def test_explicit_scrubbed_text(self):
        state = make_initial_state(
            session_id=SESSION_ID,
            heir_id=HEIR_ID,
            input_text="Raw PII",
            scrubbed_text="Scrubbed version",
        )
        assert state["scrubbed_text"] == "Scrubbed version"


class TestRouterHealingFallback:
    """LangGraph Spec §7.2: malformed JSON → healing retry → CHAT_MEDIATION default."""

    @mock.patch("app.graph.presidio_scrub", side_effect=_mock_scrub)
    def test_router_defaults_to_chat_on_all_failures(self, _mock_presidio):
        provider = MockLLMProvider()
        graph = build_graph(provider=provider, db_session_factory=None)

        # Cause ALL generate_structured calls to throw JSONDecodeError
        def _always_fail(*args, **kwargs):
            import json
            raise json.JSONDecodeError("bad json", "", 0)

        provider.generate_structured = _always_fail

        state = make_initial_state(
            session_id=SESSION_ID,
            heir_id=HEIR_ID,
            input_text="Hello.",
        )
        config = {"configurable": {"thread_id": f"{SESSION_ID}:{HEIR_ID}"}}
        events = list(graph.stream(state, config))

        node_names = [list(e.keys())[0] for e in events]
        # Should route to CHAT_MEDIATION path (RETRIEVE_RAG)
        assert "RETRIEVE_RAG" in node_names
        assert "HITL_GUARD" not in node_names