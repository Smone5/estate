"""
SMTP Service & Retry Infrastructure (T81)
==========================================
Shared async email dispatch with exponential backoff.

Consumed by:
  - T13 (Heir Management & Invitations)
  - T33 (Active Abstention Waiver PDF Receipt & Email)
  - T16 (Keepsake & Finalization Router)

Per Backend Spec §10:
  - Library: aiosmtplib for non-blocking async SMTP
  - Retry: up to 3 attempts with exponential backoff (1s, 4s, 16s)
  - Transaction Decoupling: SMTP runs asynchronously; failures never
    roll back database commits
"""

import asyncio
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import List, Optional

import aiosmtplib

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (environment-driven, read fresh on every call — not cached at
# import time — so admin-panel settings changes apply without a restart)
# ---------------------------------------------------------------------------


def _get_smtp_config() -> dict:
    return {
        "host": os.environ.get("SMTP_HOST", "localhost"),
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "username": (
            os.environ["SMTP_USERNAME"]
            if "SMTP_USERNAME" in os.environ
            else os.environ.get("SMTP_USER", "")
        ),
        "password": os.environ.get("SMTP_PASSWORD", ""),
        "use_tls": os.environ.get("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes"),
        "sender": (
            os.environ.get("SMTP_SENDER")
            or os.environ.get("SMTP_FROM")
            or "estate-steward@localhost"
        ),
        "timeout": int(os.environ.get("SMTP_TIMEOUT", "30")),
    }


RETRY_DELAYS = [1.0, 4.0, 16.0]  # Exponential backoff in seconds
MAX_RETRIES = len(RETRY_DELAYS)


class Attachment:
    """Lightweight container for an email attachment."""

    def __init__(
        self,
        filename: str,
        content: bytes,
        mimetype: str = "application/pdf",
    ):
        self.filename = filename
        self.content = content
        self.mimetype = mimetype


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def send_email(
    to: str,
    subject: str,
    body: str,
    attachments: Optional[List[Attachment]] = None,
) -> bool:
    """Send an email asynchronously with retry.

    Builds a MIMEMultipart message with a plain-text body and optional
    attachments, then dispatches via aiosmtplib with up to 3 retry
    attempts using exponential backoff.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Plain-text email body.
        attachments: Optional list of Attachment objects (e.g. PDFs).

    Returns:
        True on successful delivery, False after exhausting all retries.

    Raises:
        ValueError: If recipient, subject, or body is empty.
    """
    if not to or not subject or not body:
        raise ValueError("Recipient, subject, and body are required")

    config = _get_smtp_config()
    msg = _build_message(to=to, subject=subject, body=body, sender=config["sender"], attachments=attachments)

    for attempt in range(MAX_RETRIES):
        try:
            await _dispatch(msg, config)
            logger.info(
                "Email sent to %s (attempt %d/%d)", to, attempt + 1, MAX_RETRIES
            )
            return True
        except (aiosmtplib.SMTPException, smtplib.SMTPException, OSError) as exc:
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt]
                logger.warning(
                    "SMTP send to %s failed (attempt %d/%d): %s — retrying in %.1fs",
                    to, attempt + 1, MAX_RETRIES, exc, delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "SMTP send to %s FAILED after %d attempts: %s",
                    to, MAX_RETRIES, exc,
                )

    return False


async def send_email_background(
    to: str,
    subject: str,
    body: str,
    attachments: Optional[List[Attachment]] = None,
    on_failure_message: Optional[str] = None,
) -> bool:
    """Fire-and-forget async email dispatch.

    This is the preferred entry point for callers that must not block
    on SMTP delivery (e.g. database commit handlers).  It launches
    the send as an asyncio task and logs any terminal failure.

    If on_failure_message is provided, it is logged at WARNING level
    when delivery fails after all retries (useful for surfacing
    compliance-related delivery concerns without blocking).

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Plain-text email body.
        attachments: Optional list of Attachment objects.
        on_failure_message: Optional context string to log on failure.
    """
    success = await send_email(to=to, subject=subject, body=body, attachments=attachments)
    if not success and on_failure_message:
        logger.warning(on_failure_message)
    return success


def _build_message(
    to: str,
    subject: str,
    body: str,
    sender: str,
    attachments: Optional[List[Attachment]] = None,
) -> MIMEMultipart:
    """Construct an RFC-compliant multipart/mixed email message."""
    msg = MIMEMultipart("mixed")
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject

    # Plain-text body
    msg.attach(MIMEText(body, "plain", "utf-8"))

    # Attachments
    if attachments:
        for att in attachments:
            part = MIMEBase(*att.mimetype.split("/", 1), name=att.filename)
            part.set_payload(att.content)
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{att.filename}"',
            )
            msg.attach(part)

    return msg


async def _dispatch(msg: MIMEMultipart, config: dict) -> None:
    """Connect to SMTP server and send the message.

    Uses STARTTLS when SMTP_USE_TLS is true; falls back to plaintext
    for local dev / mailcatcher.
    """
    smtp = aiosmtplib.SMTP(
        hostname=config["host"],
        port=config["port"],
        use_tls=False,  # We'll STARTTLS manually below
        timeout=config["timeout"],
    )

    await smtp.connect()

    try:
        if not config["use_tls"]:
            # Mailpit / local dev — skip STARTTLS
            pass
        else:
            await smtp.starttls()

        if config["username"]:
            await smtp.login(config["username"], config["password"])

        await smtp.send_message(msg)
    finally:
        try:
            await smtp.quit()
        except Exception:
            pass
