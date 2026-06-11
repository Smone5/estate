"""
Microsoft Presidio PII scrubbing engine for The Estate Steward.

Per Compliance Spec §1.3 and LangGraph Spec §4.1:
  - Configured to detect and redact six entity types:
    PERSON, EMAIL_ADDRESS, PHONE_NUMBER, LOCATION, US_SSN, IP_ADDRESS
  - Provides a single scrub() entry point consumed by the INGEST_PII
    LangGraph node.
"""

import logging

from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Recognized entity types (Compliance Spec §1.3)
# ---------------------------------------------------------------------------
_ENTITY_TYPES = [
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "LOCATION",
    "US_SSN",
    "IP_ADDRESS",
]

# ---------------------------------------------------------------------------
# Presidio engines — lazy-initialised to defer NLP model loading
# ---------------------------------------------------------------------------
_analyzer: AnalyzerEngine | None = None
_anonymizer: AnonymizerEngine | None = None


def _get_analyzer() -> AnalyzerEngine:
    """Return the singleton AnalyzerEngine, creating it on first call."""
    global _analyzer
    if _analyzer is None:
        _analyzer = AnalyzerEngine()
    return _analyzer


def _get_anonymizer() -> AnonymizerEngine:
    """Return the singleton AnonymizerEngine."""
    global _anonymizer
    if _anonymizer is None:
        _anonymizer = AnonymizerEngine()
    return _anonymizer


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scrub(text: str) -> str:
    """Detect and redact PII from *text*, returning a scrubbed copy.

    All six entity types (PERSON, EMAIL_ADDRESS, PHONE_NUMBER, LOCATION,
    US_SSN, IP_ADDRESS) are detected and replaced with their entity-type
    label in angle brackets (e.g. '<PERSON>', '<LOCATION>').

    If *text* is empty or falsy it is returned unchanged.
    """
    if not text:
        return text

    analyzer = _get_analyzer()
    anonymizer = _get_anonymizer()

    results = analyzer.analyze(
        text=text,
        language="en",
        entities=_ENTITY_TYPES,
        score_threshold=0.5,
    )

    if not results:
        return text

    # Build an anonymizer OperatorConfig dict keyed by entity_type.
    # Each entity is replaced with its own type label — Presidio's
    # default 'replace' operator uses the entity_type name.
    operators = {}
    for result in results:
        etype = result.entity_type
        if etype not in operators:
            operators[etype] = OperatorConfig("replace")

    anonymized = anonymizer.anonymize(
        text=text,
        analyzer_results=results,
        operators=operators,
    )

    return anonymized.text


def get_supported_entities() -> list[str]:
    """Return the list of entity types this module is configured to scrub."""
    return list(_ENTITY_TYPES)