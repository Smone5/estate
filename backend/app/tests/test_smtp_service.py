"""
Tests for T81: SMTP Service & Retry Infrastructure.
"""

import base64
import asyncio
from unittest import mock

import pytest
import aiosmtplib
from app.services.smtp_service import (
    send_email,
    send_email_background,
    Attachment,
    SMTP_SENDER,
    MAX_RETRIES,
    _build_message,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "localhost")
    monkeypatch.setenv("SMTP_PORT", "1025")
    monkeypatch.setenv("SMTP_SENDER", "test@example.com")
    monkeypatch.setenv("SMTP_USE_TLS", "false")


# ---------------------------------------------------------------------------
# send_email — success path
# ---------------------------------------------------------------------------


class TestSendEmailSuccess:

    @pytest.mark.asyncio
    @mock.patch("app.services.smtp_service._dispatch", new_callable=mock.AsyncMock)
    async def test_success_returns_true(self, mock_dispatch):
        result = await send_email(
            to="heir@example.com",
            subject="Welcome",
            body="Hello from the Estate Steward.",
        )
        assert result is True
        mock_dispatch.assert_called_once()

    @pytest.mark.asyncio
    @mock.patch("app.services.smtp_service._dispatch", new_callable=mock.AsyncMock)
    async def test_sends_with_attachments(self, mock_dispatch):
        att = Attachment(
            filename="keepsake.pdf",
            content=b"%PDF-would-be-here",
        )
        result = await send_email(
            to="heir@example.com",
            subject="Your Keepsake",
            body="Here is your keepsake memory book.",
            attachments=[att],
        )
        assert result is True
        mock_dispatch.assert_called_once()

    @pytest.mark.asyncio
    @mock.patch("app.services.smtp_service._dispatch", new_callable=mock.AsyncMock)
    async def test_sends_multiple_attachments(self, mock_dispatch):
        attachments = [
            Attachment(filename="a.pdf", content=b"data1"),
            Attachment(filename="b.pdf", content=b"data2"),
        ]
        result = await send_email(
            to="heir@example.com",
            subject="Docs",
            body="See attached.",
            attachments=attachments,
        )
        assert result is True
        mock_dispatch.assert_called_once()


# ---------------------------------------------------------------------------
# send_email — validation
# ---------------------------------------------------------------------------


class TestSendEmailValidation:

    @pytest.mark.asyncio
    async def test_empty_recipient_raises(self):
        with pytest.raises(ValueError, match="Recipient"):
            await send_email(to="", subject="Test", body="Body")

    @pytest.mark.asyncio
    async def test_empty_subject_raises(self):
        with pytest.raises(ValueError, match="Recipient"):
            await send_email(to="a@b.com", subject="", body="Body")

    @pytest.mark.asyncio
    async def test_empty_body_raises(self):
        with pytest.raises(ValueError, match="Recipient"):
            await send_email(to="a@b.com", subject="Test", body="")


# ---------------------------------------------------------------------------
# send_email — retry & failure
# ---------------------------------------------------------------------------


class TestSendEmailRetry:

    @pytest.mark.asyncio
    @mock.patch("app.services.smtp_service._dispatch", new_callable=mock.AsyncMock)
    @mock.patch("app.services.smtp_service.asyncio.sleep", new_callable=mock.AsyncMock)
    async def test_retry_three_times_then_fail(self, mock_sleep, mock_dispatch):
        mock_dispatch.side_effect = aiosmtplib.SMTPException("Connection refused")

        result = await send_email(
            to="heir@example.com",
            subject="Retry Test",
            body="Will fail.",
        )
        assert result is False
        assert mock_dispatch.call_count == MAX_RETRIES
        assert mock_sleep.call_count == MAX_RETRIES - 1

    @pytest.mark.asyncio
    @mock.patch("app.services.smtp_service._dispatch", new_callable=mock.AsyncMock)
    @mock.patch("app.services.smtp_service.asyncio.sleep", new_callable=mock.AsyncMock)
    async def test_success_after_first_retry(self, mock_sleep, mock_dispatch):
        mock_dispatch.side_effect = [
            aiosmtplib.SMTPException("fail"),
            None,  # Success
        ]

        result = await send_email(
            to="heir@example.com",
            subject="Retry Test",
            body="Will succeed on retry.",
        )
        assert result is True
        assert mock_dispatch.call_count == 2
        assert mock_sleep.call_count == 1

    @pytest.mark.asyncio
    @mock.patch("app.services.smtp_service._dispatch", new_callable=mock.AsyncMock)
    @mock.patch("app.services.smtp_service.asyncio.sleep", new_callable=mock.AsyncMock)
    async def test_backoff_delays_correct(self, mock_sleep, mock_dispatch):
        mock_dispatch.side_effect = [
            aiosmtplib.SMTPException("fail"),
            aiosmtplib.SMTPException("fail"),
            None,  # Success on 3rd attempt
        ]

        await send_email(to="heir@example.com", subject="Test", body="Body")
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1.0)
        mock_sleep.assert_any_call(4.0)


# ---------------------------------------------------------------------------
# send_email_background
# ---------------------------------------------------------------------------


class TestSendEmailBackground:

    @pytest.mark.asyncio
    @mock.patch("app.services.smtp_service.send_email", new_callable=mock.AsyncMock)
    async def test_background_success_logs_nothing_extra(self, mock_send):
        mock_send.return_value = True

        await send_email_background(
            to="heir@example.com",
            subject="Test",
            body="Body",
        )
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    @mock.patch("app.services.smtp_service.send_email", new_callable=mock.AsyncMock)
    async def test_background_failure_logs_warning(self, mock_send, caplog):
        mock_send.return_value = False

        with caplog.at_level("WARNING"):
            await send_email_background(
                to="heir@example.com",
                subject="Test",
                body="Body",
                on_failure_message="PHYSICAL_DELIVERY_REQUIRED",
            )
        assert "PHYSICAL_DELIVERY_REQUIRED" in caplog.text


# ---------------------------------------------------------------------------
# _build_message — correctness
# ---------------------------------------------------------------------------


class TestBuildMessage:

    def test_basic_message_structure(self):
        msg = _build_message(
            to="heir@example.com",
            subject="Welcome",
            body="Hello there.",
        )
        assert msg["From"] == SMTP_SENDER
        assert msg["To"] == "heir@example.com"
        assert msg["Subject"] == "Welcome"
        # Body is base64-encoded in the MIME payload
        payload = msg.as_string()
        expected_b64 = base64.b64encode(b"Hello there.").decode("ascii")
        assert expected_b64 in payload

    def test_message_with_attachment(self):
        att = Attachment(filename="doc.pdf", content=b"PDF_DATA")
        msg = _build_message(
            to="heir@example.com",
            subject="PDF",
            body="See attached.",
            attachments=[att],
        )
        payload = msg.as_string()
        assert "doc.pdf" in payload
        # Attachment content should appear in base64
        assert "UERGX0RBVEE" in payload  # b"PDF_DATA" in base64

    def test_message_content_type(self):
        msg = _build_message(
            to="heir@example.com",
            subject="Test",
            body="Hello",
        )
        assert msg.get_content_type() == "multipart/mixed"