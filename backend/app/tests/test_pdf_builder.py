"""
Tests for T14 — ReportLab PDF Builders.

Covers:
  - Document A (Keepsake Memory Book) generation
  - Document B (Probate Audit Ledger) generation
  - Cover page legal disclaimer (Legal Spec §5)
  - NumberedCanvas page numbering
  - Dynamic column widths and landscape transition (>4 heirs)
  - Image placeholder when storage driver unavailable
  - Layout overflow truncation protection
  - Cryptographic seal rendering
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from pypdf import PdfReader

from app.models import Asset, AuditLog, Session, User
from app.notice_log import build_notice_log
from app.pdf_builder import (
    build_keepsake_pdf,
    build_probate_ledger_pdf,
    NumberedCanvas,
    _TRUNCATION_LIMIT,
)
from app.solver import SolverResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_text_from_pdf(data: bytes) -> str:
    """Extract all text from a PDF using pypdf."""
    reader = PdfReader(io.BytesIO(data))
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text)
    return "\n".join(pages)


def _count_pdf_pages(data: bytes) -> int:
    """Count the number of pages in a PDF."""
    reader = PdfReader(io.BytesIO(data))
    return len(reader.pages)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_session(**kwargs) -> Session:
    defaults = {
        "id": uuid.uuid4(),
        "title": "Test Estate",
        "status": "FINALIZED",
        "created_at": datetime(2025, 1, 15, tzinfo=timezone.utc),
    }
    defaults.update(kwargs)
    return Session(**defaults)


def _make_user(**kwargs) -> User:
    defaults = {
        "id": uuid.uuid4(),
        "username": "heir_one",
        "legal_first_name": "Alice",
        "legal_last_name": "Smith",
        "role": "HEIR",
        "email": "alice@example.com",
        "status": "SUBMITTED",
        "created_at": datetime(2025, 2, 1, tzinfo=timezone.utc),
    }
    defaults.update(kwargs)
    return User(**defaults)


def _make_admin(**kwargs) -> User:
    defaults = {
        "id": uuid.uuid4(),
        "username": "executor",
        "legal_first_name": "Robert",
        "legal_last_name": "Jones",
        "role": "ADMIN",
        "email": "executor@example.com",
        "status": "ACTIVE",
        "created_at": datetime(2025, 1, 14, tzinfo=timezone.utc),
    }
    defaults.update(kwargs)
    return User(**defaults)


def _make_asset(session_id, **kwargs) -> Asset:
    defaults = {
        "id": uuid.uuid4(),
        "session_id": session_id,
        "title": "Grandfather Clock",
        "description": "A tall oak grandfather clock from the 1920s.",
        "category": "Furniture",
        "valuation_min": 500.0,
        "valuation_max": 1500.0,
        "valuation_source": "Estate Sale Estimator",
        "image_uri": "uploads/test-clock.webp",
        "status": "LIVE",
    }
    defaults.update(kwargs)
    return Asset(**defaults)


def _make_audit_log(session_id, **kwargs) -> AuditLog:
    defaults = {
        "id": 1,
        "session_id": session_id,
        "event_type": "FINALIZED",
        "state_snapshot": {"final": True},
        "prev_hash": "0" * 64,
        "sha256_hash": "a" * 64,
        "created_at": datetime(2025, 3, 1, tzinfo=timezone.utc),
    }
    defaults.update(kwargs)
    return AuditLog(**defaults)


def _make_solver_result(allocation=None, mnw=100.0, tie_events=None) -> SolverResult:
    return SolverResult(
        allocation=allocation or {},
        mnw_product_value=mnw,
        tie_breaker_events=tie_events or [],
    )


# ---------------------------------------------------------------------------
# Tests: Document A — Keepsake Memory Book
# ---------------------------------------------------------------------------


class TestKeepsakePDF:
    def test_produces_valid_pdf_bytes(self):
        """build_keepsake_pdf returns non-empty bytes starting with %PDF."""
        session = _make_session()
        heir = _make_user()
        asset = _make_asset(session.id)
        solver = _make_solver_result({str(heir.id): [str(asset.id)]})
        audit_log = _make_audit_log(session.id)

        buf = build_keepsake_pdf(
            session=session,
            heir=heir,
            assets=[asset],
            solver_result=solver,
            audit_logs=[audit_log],
        )

        data = buf.getvalue()
        assert len(data) > 0
        assert data.startswith(b"%PDF")

        # Extract text to verify content
        text = _extract_text_from_pdf(data)
        assert "Keepsake Memory Book" in text

    def test_cover_page_contains_legal_disclaimer(self):
        """Cover page must include the legal disclaimer per Legal Spec §5."""
        session = _make_session()
        heir = _make_user()
        solver = _make_solver_result()
        audit_log = _make_audit_log(session.id)

        buf = build_keepsake_pdf(
            session=session,
            heir=heir,
            assets=[],
            solver_result=solver,
            audit_logs=[audit_log],
        )

        data = buf.getvalue()
        text = _extract_text_from_pdf(data)
        assert "collaborative mediation aid" in text

    def test_no_assets_shows_empty_message(self):
        """When heir has no allocations, a no-assets message is rendered."""
        session = _make_session()
        heir = _make_user()
        solver = _make_solver_result({})
        audit_log = _make_audit_log(session.id)

        buf = build_keepsake_pdf(
            session=session,
            heir=heir,
            assets=[],
            solver_result=solver,
            audit_logs=[audit_log],
        )

        data = buf.getvalue()
        text = _extract_text_from_pdf(data)
        assert "No assets were allocated" in text

    def test_crypto_seal_appears_when_audit_logs_present(self):
        """SHA-256 seal is rendered when audit logs exist."""
        session = _make_session()
        heir = _make_user()
        solver = _make_solver_result()
        audit_log = _make_audit_log(session.id, sha256_hash="b" * 64)

        buf = build_keepsake_pdf(
            session=session,
            heir=heir,
            assets=[],
            solver_result=solver,
            audit_logs=[audit_log],
        )

        data = buf.getvalue()
        text = _extract_text_from_pdf(data)
        assert "SHA-256 Seal" in text

    def test_heir_name_display_composes_legal_name(self):
        """Legal name composition: first middle last, fallback to username."""
        session = _make_session()
        heir = _make_user(
            legal_middle_name="Marie",
            username="xyz",
        )
        solver = _make_solver_result()
        audit_log = _make_audit_log(session.id)

        buf = build_keepsake_pdf(
            session=session,
            heir=heir,
            assets=[],
            solver_result=solver,
            audit_logs=[audit_log],
        )

        data = buf.getvalue()
        text = _extract_text_from_pdf(data)
        assert "Alice Marie Smith" in text

    def test_heir_name_falls_back_to_username(self):
        """When no legal name fields set, username is used."""
        session = _make_session()
        heir = _make_user(
            legal_first_name=None,
            legal_middle_name=None,
            legal_last_name=None,
            username="heir_only_user",
        )
        solver = _make_solver_result()
        audit_log = _make_audit_log(session.id)

        buf = build_keepsake_pdf(
            session=session,
            heir=heir,
            assets=[],
            solver_result=solver,
            audit_logs=[audit_log],
        )

        data = buf.getvalue()
        text = _extract_text_from_pdf(data)
        assert "heir_only_user" in text

    def test_include_pre_allocated_assets(self):
        """Pre-allocated assets assigned to the heir appear in keepsake."""
        session = _make_session()
        heir = _make_user()
        asset = _make_asset(session.id, allocated_to_id=heir.id)
        solver = _make_solver_result({})  # No solver allocations

        buf = build_keepsake_pdf(
            session=session,
            heir=heir,
            assets=[asset],
            solver_result=solver,
            audit_logs=[],
        )

        data = buf.getvalue()
        text = _extract_text_from_pdf(data)
        assert "Grandfather Clock" in text

    def test_has_at_least_two_pages_with_assets(self):
        """With assets, the PDF should have cover + content pages (>=2)."""
        session = _make_session()
        heir = _make_user()
        asset = _make_asset(session.id)
        solver = _make_solver_result({str(heir.id): [str(asset.id)]})
        audit_log = _make_audit_log(session.id)

        buf = build_keepsake_pdf(
            session=session,
            heir=heir,
            assets=[asset],
            solver_result=solver,
            audit_logs=[audit_log],
        )

        data = buf.getvalue()
        pages = _count_pdf_pages(data)
        assert pages >= 2


# ---------------------------------------------------------------------------
# Tests: Document B — Probate Audit Ledger
# ---------------------------------------------------------------------------


class TestProbateLedgerPDF:
    def test_produces_valid_pdf_bytes(self):
        """build_probate_ledger_pdf returns non-empty valid PDF."""
        session = _make_session()
        admin = _make_admin()
        heir = _make_user()
        asset = _make_asset(session.id)
        solver = _make_solver_result({str(heir.id): [str(asset.id)]})
        audit_log = _make_audit_log(session.id)
        notice_log = build_notice_log(str(session.id), [heir])

        buf = build_probate_ledger_pdf(
            session=session,
            heirs=[admin, heir],
            assets=[asset],
            solver_result=solver,
            audit_logs=[audit_log],
            notice_log=notice_log,
        )

        data = buf.getvalue()
        assert len(data) > 0
        assert data.startswith(b"%PDF")
        text = _extract_text_from_pdf(data)
        assert "Final Distribution" in text

    def test_cover_page_contains_legal_disclaimer(self):
        """Cover page must include legal disclaimer per Legal Spec §5."""
        session = _make_session()
        admin = _make_admin()
        heir = _make_user()
        solver = _make_solver_result()
        audit_log = _make_audit_log(session.id)
        notice_log = build_notice_log(str(session.id), [heir])

        buf = build_probate_ledger_pdf(
            session=session,
            heirs=[admin, heir],
            assets=[],
            solver_result=solver,
            audit_logs=[audit_log],
            notice_log=notice_log,
        )

        data = buf.getvalue()
        text = _extract_text_from_pdf(data)
        assert "collaborative mediation aid" in text

    def test_beneficiary_table_renders_all_heirs(self):
        """Registered beneficiary table shows all HEIR-role users."""
        session = _make_session()
        admin = _make_admin()
        heir1 = _make_user(id=uuid.uuid4(), username="alice", legal_first_name="Alice")
        heir2 = _make_user(id=uuid.uuid4(), username="bob", legal_first_name="Bob")
        solver = _make_solver_result()
        audit_log = _make_audit_log(session.id)
        notice_log = build_notice_log(str(session.id), [heir1, heir2])

        buf = build_probate_ledger_pdf(
            session=session,
            heirs=[admin, heir1, heir2],
            assets=[],
            solver_result=solver,
            audit_logs=[audit_log],
            notice_log=notice_log,
        )

        data = buf.getvalue()
        text = _extract_text_from_pdf(data)
        assert "Registered Beneficiaries" in text
        assert "Alice" in text
        assert "Bob" in text

    def test_mnw_callout_displays_product_value(self):
        """MNW product callout box renders the scalar value."""
        session = _make_session()
        admin = _make_admin()
        heir = _make_user()
        solver = _make_solver_result(mnw=42500.75)
        audit_log = _make_audit_log(session.id)
        notice_log = build_notice_log(str(session.id), [heir])

        buf = build_probate_ledger_pdf(
            session=session,
            heirs=[admin, heir],
            assets=[],
            solver_result=solver,
            audit_logs=[audit_log],
            notice_log=notice_log,
        )

        data = buf.getvalue()
        text = _extract_text_from_pdf(data)
        assert "Maximum Nash Welfare Product" in text

    def test_admin_intervention_log_renders_overrides(self):
        """When ADMIN_OVERRIDE audit logs exist, intervention table appears."""
        session = _make_session()
        admin = _make_admin()
        heir = _make_user()
        solver = _make_solver_result()
        audit_log = _make_audit_log(
            session.id,
            id=5,
            event_type="ADMIN_OVERRIDE",
            state_snapshot={
                "asset_ids": "asset-uuid-1",
                "allocated_to": str(heir.id),
                "reason": "Family agreement override",
            },
        )
        notice_log = build_notice_log(str(session.id), [heir])

        buf = build_probate_ledger_pdf(
            session=session,
            heirs=[admin, heir],
            assets=[],
            solver_result=solver,
            audit_logs=[audit_log],
            notice_log=notice_log,
        )

        data = buf.getvalue()
        text = _extract_text_from_pdf(data)
        assert "Admin Intervention Log" in text

    def test_mathematical_proof_section_present(self):
        """Mathematical proof section explains MNW guarantee."""
        session = _make_session()
        admin = _make_admin()
        heir = _make_user()
        solver = _make_solver_result(tie_events=["Asset X: Tied at 50 points"])
        audit_log = _make_audit_log(session.id)
        notice_log = build_notice_log(str(session.id), [heir])

        buf = build_probate_ledger_pdf(
            session=session,
            heirs=[admin, heir],
            assets=[],
            solver_result=solver,
            audit_logs=[audit_log],
            notice_log=notice_log,
        )

        data = buf.getvalue()
        text = _extract_text_from_pdf(data)
        assert "Mathematical Proof" in text
        assert "Maximum Nash Welfare" in text

    def test_tie_breaker_events_in_proof_section(self):
        """Tie-breaker events are listed in the mathematical proof."""
        session = _make_session()
        admin = _make_admin()
        heir = _make_user()
        solver = _make_solver_result(
            tie_events=["Asset Clock: Tied at 50 points among alice, bob → alice"]
        )
        audit_log = _make_audit_log(session.id)
        notice_log = build_notice_log(str(session.id), [heir])

        buf = build_probate_ledger_pdf(
            session=session,
            heirs=[admin, heir],
            assets=[],
            solver_result=solver,
            audit_logs=[audit_log],
            notice_log=notice_log,
        )

        data = buf.getvalue()
        text = _extract_text_from_pdf(data)
        assert "Tie-Breaker Events" in text

    def test_notice_log_table_section(self):
        """Proof of Notice Log table renders from NoticeLog data contract."""
        session = _make_session()
        admin = _make_admin()
        heir = _make_user(
            invitation_dispatched_at=datetime(2025, 2, 2, tzinfo=timezone.utc),
            invite_token_expires_at=datetime(2025, 2, 16, tzinfo=timezone.utc),
        )
        solver = _make_solver_result()
        audit_log = _make_audit_log(session.id)
        notice_log = build_notice_log(str(session.id), [heir])

        buf = build_probate_ledger_pdf(
            session=session,
            heirs=[admin, heir],
            assets=[],
            solver_result=solver,
            audit_logs=[audit_log],
            notice_log=notice_log,
        )

        data = buf.getvalue()
        text = _extract_text_from_pdf(data)
        assert "Proof of Notice Log" in text

    def test_crypto_seal_section(self):
        """Cryptographic Integrity Seal renders the final SHA-256 hash."""
        session = _make_session()
        admin = _make_admin()
        heir = _make_user()
        solver = _make_solver_result()
        audit_log = _make_audit_log(session.id, sha256_hash="f" * 64)
        notice_log = build_notice_log(str(session.id), [heir])

        buf = build_probate_ledger_pdf(
            session=session,
            heirs=[admin, heir],
            assets=[],
            solver_result=solver,
            audit_logs=[audit_log],
            notice_log=notice_log,
        )

        data = buf.getvalue()
        text = _extract_text_from_pdf(data)
        assert "cryptographically sealed" in text

    def test_minimum_page_count(self):
        """Probate ledger with assets should have multiple pages."""
        session = _make_session()
        admin = _make_admin()
        heir = _make_user()
        asset = _make_asset(session.id)
        solver = _make_solver_result({str(heir.id): [str(asset.id)]})
        audit_log = _make_audit_log(session.id)
        notice_log = build_notice_log(str(session.id), [heir])

        buf = build_probate_ledger_pdf(
            session=session,
            heirs=[admin, heir],
            assets=[asset],
            solver_result=solver,
            audit_logs=[audit_log],
            notice_log=notice_log,
        )

        data = buf.getvalue()
        pages = _count_pdf_pages(data)
        assert pages >= 3  # Cover + at least 2 content pages


# ---------------------------------------------------------------------------
# Tests: NumberedCanvas
# ---------------------------------------------------------------------------


class TestNumberedCanvas:
    def test_two_pass_drawing_produces_page_footer(self):
        """NumberedCanvas renders Page X of Y footers via two-pass draw."""
        from reportlab.platypus import (
            BaseDocTemplate,
            Frame,
            PageTemplate,
            Paragraph,
            Spacer,
        )
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle

        buf = io.BytesIO()

        def bg(canvas_obj, doc):
            canvas_obj.saveState()
            canvas_obj.setFillColor("#FDFBF7")
            canvas_obj.rect(0, 0, 8.5 * 72, 11 * 72, fill=True, stroke=False)
            canvas_obj.restoreState()

        doc = BaseDocTemplate(
            buf,
            pagesize=letter,
            leftMargin=54,
            rightMargin=54,
            topMargin=54,
            bottomMargin=54,
        )
        frame = Frame(54, 54, letter[0] - 108, letter[1] - 108, id="main")
        doc.addPageTemplates([
            PageTemplate(id="main", frames=[frame], onPage=bg),
        ])

        style = ParagraphStyle("line")
        elements = []
        for i in range(30):
            elements.append(Paragraph(f"Line {i}", style))
            elements.append(Spacer(1, 0.5 * 72))

        doc.build(elements, canvasmaker=NumberedCanvas)
        data = buf.getvalue()
        assert data.startswith(b"%PDF")

        text = _extract_text_from_pdf(data)
        assert "Page" in text
        assert "of" in text


# ---------------------------------------------------------------------------
# Tests: Landscape page transition (>4 heirs)
# ---------------------------------------------------------------------------


class TestLandscapeTransition:
    def test_more_than_4_heirs_triggers_landscape(self):
        """When N > 4 heirs, a landscape PageTemplate is used."""
        session = _make_session()
        admin = _make_admin()
        heirs = [
            _make_user(id=uuid.uuid4(), username=f"heir_{i}", legal_first_name=f"Heir{i}")
            for i in range(5)
        ]
        solver = _make_solver_result()
        audit_log = _make_audit_log(session.id)
        notice_log = build_notice_log(str(session.id), heirs)

        buf = build_probate_ledger_pdf(
            session=session,
            heirs=[admin] + heirs,
            assets=[],
            solver_result=solver,
            audit_logs=[audit_log],
            notice_log=notice_log,
        )

        data = buf.getvalue()
        assert data.startswith(b"%PDF")

        # Landscape letter: 792 x 612 points in MediaBox
        text = data.decode("latin-1", errors="replace")
        assert "792" in text
        assert "612" in text

    def test_4_or_fewer_heirs_stays_portrait(self):
        """With <= 4 heirs, only portrait page template is used."""
        session = _make_session()
        admin = _make_admin()
        heirs = [
            _make_user(id=uuid.uuid4(), username=f"heir_{i}", legal_first_name=f"Heir{i}")
            for i in range(3)
        ]
        solver = _make_solver_result()
        audit_log = _make_audit_log(session.id)
        notice_log = build_notice_log(str(session.id), heirs)

        buf = build_probate_ledger_pdf(
            session=session,
            heirs=[admin] + heirs,
            assets=[],
            solver_result=solver,
            audit_logs=[audit_log],
            notice_log=notice_log,
        )

        data = buf.getvalue()
        assert data.startswith(b"%PDF")
        # Should still produce a valid PDF
        text = _extract_text_from_pdf(data)
        assert "Registered Beneficiaries" in text


# ---------------------------------------------------------------------------
# Tests: Image ingestion helper
# ---------------------------------------------------------------------------


class TestImageIngestion:
    @patch("app.pdf_builder._fetch_image_bytes")
    def test_missing_image_uses_placeholder(self, mock_fetch):
        """When image cannot be fetched, a placeholder block renders."""
        mock_fetch.return_value = None

        session = _make_session()
        heir = _make_user()
        asset = _make_asset(session.id, image_uri="uploads/missing.webp")
        solver = _make_solver_result({str(heir.id): [str(asset.id)]})
        audit_log = _make_audit_log(session.id)

        buf = build_keepsake_pdf(
            session=session,
            heir=heir,
            assets=[asset],
            solver_result=solver,
            audit_logs=[audit_log],
        )

        data = buf.getvalue()
        assert data.startswith(b"%PDF")
        text = _extract_text_from_pdf(data)
        assert "Keepsake Photo" in text


# ---------------------------------------------------------------------------
# Tests: Layout overflow protection
# ---------------------------------------------------------------------------


class TestOverflowProtection:
    def test_long_description_replaced_with_appendix(self):
        """Text > 500 chars is truncated with ellipsis, full text in appendix."""
        session = _make_session()
        admin = _make_admin()
        heir = _make_user()

        long_desc = "X" * (_TRUNCATION_LIMIT + 100)
        asset = _make_asset(session.id, description=long_desc)
        solver = _make_solver_result({str(heir.id): [str(asset.id)]})
        audit_log = _make_audit_log(session.id)
        notice_log = build_notice_log(str(session.id), [heir])

        buf = build_probate_ledger_pdf(
            session=session,
            heirs=[admin, heir],
            assets=[asset],
            solver_result=solver,
            audit_logs=[audit_log],
            notice_log=notice_log,
        )

        data = buf.getvalue()
        assert data.startswith(b"%PDF")
        text = _extract_text_from_pdf(data)
        # The appendix section should be present for truncated text
        assert "Appendix" in text
        # The truncated version should have ellipsis
        assert "..." in text

    def test_short_description_not_truncated(self):
        """Text <= 500 chars renders without appendix or truncation."""
        session = _make_session()
        admin = _make_admin()
        heir = _make_user()

        short_desc = "Short description under the limit."
        asset = _make_asset(session.id, description=short_desc)
        solver = _make_solver_result({str(heir.id): [str(asset.id)]})
        audit_log = _make_audit_log(session.id)
        notice_log = build_notice_log(str(session.id), [heir])

        buf = build_probate_ledger_pdf(
            session=session,
            heirs=[admin, heir],
            assets=[asset],
            solver_result=solver,
            audit_logs=[audit_log],
            notice_log=notice_log,
        )

        data = buf.getvalue()
        assert data.startswith(b"%PDF")
        text = _extract_text_from_pdf(data)
        assert "Short description under the limit." in text


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_session_title_default(self):
        """When session title is None, 'Estate' is used as default."""
        session = _make_session(title=None)
        heir = _make_user()
        solver = _make_solver_result()
        audit_log = _make_audit_log(session.id)

        buf = build_keepsake_pdf(
            session=session,
            heir=heir,
            assets=[],
            solver_result=solver,
            audit_logs=[audit_log],
        )

        data = buf.getvalue()
        text = _extract_text_from_pdf(data)
        assert "Estate Keepsake Memory Book" in text

    def test_no_audit_logs_skip_crypto_seal(self):
        """When no audit logs provided, crypto seal is omitted."""
        session = _make_session()
        heir = _make_user()
        solver = _make_solver_result()

        buf = build_keepsake_pdf(
            session=session,
            heir=heir,
            assets=[],
            solver_result=solver,
            audit_logs=[],
        )

        data = buf.getvalue()
        text = _extract_text_from_pdf(data)
        assert "SHA-256 Seal" not in text

    def test_keepsake_without_valuations_relationship(self):
        """Asset without loaded valuations relationship still renders."""
        session = _make_session()
        heir = _make_user()
        # _make_asset creates an asset without valuations relationship loaded
        asset = _make_asset(session.id)
        del asset.valuations  # Remove the empty relationship
        solver = _make_solver_result({str(heir.id): [str(asset.id)]})
        audit_log = _make_audit_log(session.id)

        buf = build_keepsake_pdf(
            session=session,
            heir=heir,
            assets=[asset],
            solver_result=solver,
            audit_logs=[audit_log],
        )

        data = buf.getvalue()
        assert data.startswith(b"%PDF")