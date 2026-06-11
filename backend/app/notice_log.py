"""
Proof of Notice Log Data Contract — T71.

Formalizes the cross-task data structure consumed by T14's ReportLab PDF
builder when rendering the "Proof of Notice Log" section in Document B
(Final Distribution & Probate Audit Ledger).

Populated by:
  - T13: invitation dispatch timestamps (invitation_dispatched_at,
    invite_token_expires_at, created_at)
  - T65: expiration transitions (status = 'EXPIRED_NON_PARTICIPATING')

Consumed by:
  - T14: PDF builder renders Notice Log table in final probate ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class NoticeLogEntry:
    """A single row in the Proof of Notice Log table.

    Captures one Heir's invitation and participation timeline for probate
    court admissibility.
    """

    username: str
    legal_name: str
    relationship: str | None
    email: str | None
    invite_created_at: datetime | None
    invite_expires_at: datetime | None
    invitation_dispatched_at: datetime | None
    consent_timestamp: datetime | None
    status: str
    is_submitted: bool
    submitted_at: datetime | None

    @property
    def participation_summary(self) -> str:
        """Human-readable summary of the Heir's participation outcome."""
        if self.status == "SUBMITTED":
            return "Submitted points"
        elif self.status == "ABSTAINED":
            return "Actively abstained"
        elif self.status == "EXPIRED_NON_PARTICIPATING":
            return "Invitation expired — did not participate"
        elif self.status == "PROFILE_HOLD":
            return "Identity verification pending at time of finalization"
        elif self.is_submitted:
            return "Submitted points"
        return "Did not participate"


@dataclass(frozen=True)
class NoticeLog:
    """Aggregated proof-of-notice record for one session.

    Contains all NoticeLogEntry rows for the session, sorted by username.
    """

    session_id: str
    entries: list[NoticeLogEntry] = field(default_factory=list)

    @property
    def total_invited(self) -> int:
        return len(self.entries)

    @property
    def total_dispatched(self) -> int:
        return sum(1 for e in self.entries if e.invitation_dispatched_at is not None)

    @property
    def total_submitted(self) -> int:
        return sum(1 for e in self.entries if e.is_submitted)

    @property
    def total_abstained(self) -> int:
        return sum(1 for e in self.entries if e.status == "ABSTAINED")

    @property
    def total_expired(self) -> int:
        return sum(
            1 for e in self.entries if e.status == "EXPIRED_NON_PARTICIPATING"
        )


def build_notice_log(session_id: str, heirs: list) -> NoticeLog:
    """Build a NoticeLog from a list of User ORM objects (HEIR role).

    Extracts the invitation timeline fields defined by T13 (create, dispatch,
    expiration) and T65 (expiration transitions), normalizing into the
    NoticeLogEntry data contract consumed by T14.

    Args:
        session_id: UUID string of the session.
        heirs: List of User ORM objects where role == 'HEIR'.

    Returns:
        A NoticeLog dataclass ready for PDF table rendering.
    """
    entries: list[NoticeLogEntry] = []

    for heir in heirs:
        legal_name_parts = [
            heir.legal_first_name or "",
            heir.legal_middle_name or "",
            heir.legal_last_name or "",
        ]
        legal_name = " ".join(p for p in legal_name_parts if p).strip()

        if not legal_name:
            legal_name = heir.username or "Unknown"

        entries.append(NoticeLogEntry(
            username=heir.username,
            legal_name=legal_name,
            relationship=getattr(heir, "relationship_to_decedent", None),
            email=getattr(heir, "email", None),
            invite_created_at=getattr(heir, "created_at", None),
            invite_expires_at=getattr(heir, "invite_token_expires_at", None),
            invitation_dispatched_at=getattr(heir, "invitation_dispatched_at", None),
            consent_timestamp=getattr(heir, "consent_timestamp", None),
            status=heir.status,
            is_submitted=heir.is_submitted if hasattr(heir, "is_submitted") else False,
            submitted_at=getattr(heir, "submitted_at", None),
        ))

    # Sort by username for deterministic rendering
    entries.sort(key=lambda e: e.username.lower())

    return NoticeLog(session_id=session_id, entries=entries)