"""
Tests for T05 — Microsoft Presidio PII Scrubbing.

Per specs_testing.md §1.2: Mock the Presidio analyzer and anonymizer engines
to avoid heavy NLP model loading during test execution.

Verifies the app.presidio module:
- Correctly configures all six entity types (Compliance Spec §1.3)
- scrub() calls Presidio with correct entity types and score_threshold
- scrub() returns scrubbed text from the anonymizer
- scrub() returns empty string unchanged
- scrub() returns text unchanged when no PII detected
- get_supported_entities() returns the correct entity list
"""

from unittest import mock

import pytest

from app.presidio import scrub, get_supported_entities


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset the lazy Presidio singleton cache between tests."""
    import app.presidio as mod

    mod._analyzer = None
    mod._anonymizer = None


@pytest.fixture
def mock_presidio():
    """Mock both the AnalyzerEngine and AnonymizerEngine.

    Returns (mock_analyzer, mock_anonymizer, mock_analyzer_cls, mock_anonymizer_cls).
    """
    mock_analyzer = mock.MagicMock()
    mock_anonymizer = mock.MagicMock()

    with mock.patch(
        "app.presidio.AnalyzerEngine", return_value=mock_analyzer
    ) as mock_analyzer_cls, mock.patch(
        "app.presidio.AnonymizerEngine", return_value=mock_anonymizer
    ) as mock_anonymizer_cls:
        yield mock_analyzer, mock_anonymizer, mock_analyzer_cls, mock_anonymizer_cls


# ---------------------------------------------------------------------------
# Unit tests — get_supported_entities
# ---------------------------------------------------------------------------


class TestGetSupportedEntities:
    """T05: Verify the entity type list matches the spec."""

    def test_returns_six_entities(self):
        entities = get_supported_entities()
        assert len(entities) == 6

    def test_includes_all_required_types(self):
        entities = get_supported_entities()
        expected = [
            "PERSON",
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "LOCATION",
            "US_SSN",
            "IP_ADDRESS",
        ]
        for e in expected:
            assert e in entities

    def test_returns_copy_not_reference(self):
        """Modifying the returned list does not modify internal state."""
        entities = get_supported_entities()
        entities.append("FAKE")
        assert len(get_supported_entities()) == 6


# ---------------------------------------------------------------------------
# Unit tests — scrub()
# ---------------------------------------------------------------------------


class TestScrub:
    """T05: Verify scrub() behaviour with mocked Presidio."""

    def test_empty_string_returns_empty(self, mock_presidio):
        mock_analyzer, mock_anonymizer, _, _ = mock_presidio
        result = scrub("")
        assert result == ""
        # Neither engine should be called
        mock_analyzer.analyze.assert_not_called()
        mock_anonymizer.anonymize.assert_not_called()

    def test_falsy_input_returns_unchanged(self, mock_presidio):
        mock_analyzer, mock_anonymizer, _, _ = mock_presidio
        result = scrub(None)
        assert result is None
        mock_analyzer.analyze.assert_not_called()

    def test_no_pii_detected_returns_original_text(self, mock_presidio):
        mock_analyzer, mock_anonymizer, _, _ = mock_presidio
        mock_analyzer.analyze.return_value = []

        result = scrub("Hello, how are you?")
        assert result == "Hello, how are you?"
        mock_anonymizer.anonymize.assert_not_called()

    def test_analyzer_called_with_correct_entity_types(self, mock_presidio):
        mock_analyzer, mock_anonymizer, _, _ = mock_presidio
        # Return a fake detection so anonymizer is invoked
        fake_result = mock.MagicMock()
        fake_result.entity_type = "PERSON"
        mock_analyzer.analyze.return_value = [fake_result]

        fake_response = mock.MagicMock()
        fake_response.text = "Hello <PERSON>"
        mock_anonymizer.anonymize.return_value = fake_response

        scrub("Hello John Doe")

        mock_analyzer.analyze.assert_called_once()
        call_kwargs = mock_analyzer.analyze.call_args.kwargs
        assert call_kwargs["language"] == "en"
        assert call_kwargs["score_threshold"] == 0.5
        assert sorted(call_kwargs["entities"]) == sorted([
            "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER",
            "LOCATION", "US_SSN", "IP_ADDRESS",
        ])

    def test_person_entity_scrubbed(self, mock_presidio):
        mock_analyzer, mock_anonymizer, _, _ = mock_presidio

        fake_result = mock.MagicMock()
        fake_result.entity_type = "PERSON"
        mock_analyzer.analyze.return_value = [fake_result]

        fake_response = mock.MagicMock()
        fake_response.text = "Hello <PERSON>"
        mock_anonymizer.anonymize.return_value = fake_response

        result = scrub("Hello John Doe")
        assert result == "Hello <PERSON>"

    def test_email_address_entity_scrubbed(self, mock_presidio):
        mock_analyzer, mock_anonymizer, _, _ = mock_presidio

        fake_result = mock.MagicMock()
        fake_result.entity_type = "EMAIL_ADDRESS"
        mock_analyzer.analyze.return_value = [fake_result]

        fake_response = mock.MagicMock()
        fake_response.text = "Contact <EMAIL_ADDRESS>"
        mock_anonymizer.anonymize.return_value = fake_response

        result = scrub("Contact john@example.com")
        assert result == "Contact <EMAIL_ADDRESS>"

    def test_multiple_entity_types_scrubbed(self, mock_presidio):
        mock_analyzer, mock_anonymizer, _, _ = mock_presidio

        fake_person = mock.MagicMock()
        fake_person.entity_type = "PERSON"
        fake_email = mock.MagicMock()
        fake_email.entity_type = "EMAIL_ADDRESS"
        mock_analyzer.analyze.return_value = [fake_person, fake_email]

        fake_response = mock.MagicMock()
        fake_response.text = "<PERSON> at <EMAIL_ADDRESS>"
        mock_anonymizer.anonymize.return_value = fake_response

        result = scrub("Alice at alice@example.com")
        assert result == "<PERSON> at <EMAIL_ADDRESS>"

    def test_operator_configs_passed_correctly(self, mock_presidio):
        mock_analyzer, mock_anonymizer, _, _ = mock_presidio

        fake_person = mock.MagicMock()
        fake_person.entity_type = "PERSON"
        fake_ip = mock.MagicMock()
        fake_ip.entity_type = "IP_ADDRESS"
        mock_analyzer.analyze.return_value = [fake_person, fake_ip]

        fake_response = mock.MagicMock()
        fake_response.text = "x"
        mock_anonymizer.anonymize.return_value = fake_response

        scrub("test")

        # Verify anonymizer received OperatorConfig objects
        call_args = mock_anonymizer.anonymize.call_args
        operators = call_args.kwargs["operators"]
        assert "PERSON" in operators
        assert "IP_ADDRESS" in operators
        # Each entry should be an OperatorConfig with "replace"
        from presidio_anonymizer.entities import OperatorConfig

        for op in operators.values():
            assert isinstance(op, OperatorConfig)

    def test_singletons_cached(self, mock_presidio):
        mock_analyzer, mock_anonymizer, mock_cls, mock_anonymizer_cls = mock_presidio

        fake_result = mock.MagicMock()
        fake_result.entity_type = "PERSON"
        mock_analyzer.analyze.return_value = [fake_result]

        fake_response = mock.MagicMock()
        fake_response.text = "x"
        mock_anonymizer.anonymize.return_value = fake_response

        scrub("first call")
        scrub("second call")

        # Engines should be created only once
        mock_cls.assert_called_once()
        mock_anonymizer_cls.assert_called_once()