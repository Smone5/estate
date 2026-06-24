"""
ReportLab PDF Builders — T14.

Produces two document types per Backend Spec §13.3:
  Document A: Individual Heir's Keepsake Memory Book
  Document B: Final Distribution & Probate Audit Ledger

Consumes:
  - T15 solver.SolverResult (allocation, mnw_product_value, tie_breaker_events)
  - T71 notice_log.NoticeLog / NoticeLogEntry
  - T02 models (Session, User, Asset, Valuation, AuditLog)
  - T03 encryption (decrypted field access is transparent via SQLAlchemy)

Exports:
  - build_keepsake_pdf(session, heir, assets, ...) -> io.BytesIO
  - build_probate_ledger_pdf(session, heirs, assets, solver_result, ...) -> io.BytesIO
"""

from __future__ import annotations

import io
import logging
import os
from html import escape
from datetime import datetime, timezone
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from .models import Asset as AssetModel
from .models import AuditLog as AuditLogModel
from .models import Session as SessionModel
from .models import User as UserModel
from .models import Valuation as ValuationModel
from .notice_log import NoticeLog, NoticeLogEntry
from .services.storage import StorageDriver, get_storage_driver
from .solver import SolverResult, TieBreakerEvent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants (matches Backend Spec §13.1–13.2)
# ---------------------------------------------------------------------------

CREAM_BG = "#FDFBF7"
SLATE_900 = "#1E293B"
MUTED_SLATE = "#64748B"
WARM_GREY = "#E6DFD3"
SAGE_GREEN = "#4A6741"
LIGHT_GREY_BORDER = "#D1D5DB"

LEGAL_DISCLAIMER = (
    "Disclaimer: The Estate Steward is a collaborative mediation aid designed "
    "to assist executors and heirs in dividing personal property. It does not "
    "provide legal advice, estate planning, or tax counsel. Use of this tool "
    "does not guarantee probate court approval. Executors are advised to "
    "consult with a licensed probate attorney regarding their fiduciary "
    "obligations and court filings."
)

# ---------------------------------------------------------------------------
# NumberedCanvas — 2-pass page numbering (Backend Spec §13.1)
# ---------------------------------------------------------------------------


class NumberedCanvas(canvas.Canvas):
    """Custom canvas that performs a two-pass draw for Page X of Y footers.

    MUST exactly match the implementation defined in Backend Spec §13.1
    NumberedCanvas contract.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict] = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def _draw_page_decorations(self, total_pages: int):
        self.saveState()

        if self._pageNumber > 1:
            # Running header
            self.setFont("Helvetica-Oblique", 8)
            self.setFillColor(MUTED_SLATE)
            self.drawString(54, 11 * 72 - 36, "The Estate Steward - Keepsake Ledger")

            self.setStrokeColor(WARM_GREY)
            self.setLineWidth(0.5)
            self.line(54, 11 * 72 - 42, 8.5 * 72 - 54, 11 * 72 - 42)

            # Running footer
            self.line(54, 54, 8.5 * 72 - 54, 54)
            self.setFont("Helvetica", 8)
            self.drawString(54, 42, "CONFIDENTIAL - Family Mediation Record")

            page_string = f"Page {self._pageNumber} of {total_pages}"
            self.drawRightString(8.5 * 72 - 54, 42, page_string)

        self.restoreState()


# ---------------------------------------------------------------------------
# Page background callback
# ---------------------------------------------------------------------------


def _draw_page_background(canvas_obj, doc):
    canvas_obj.saveState()
    canvas_obj.setFillColor(CREAM_BG)
    canvas_obj.rect(0, 0, 8.5 * 72, 11 * 72, fill=True, stroke=False)
    canvas_obj.restoreState()


# ---------------------------------------------------------------------------
# Paragraph styles (Backend Spec §13.2)
# ---------------------------------------------------------------------------

_STYLES = getSampleStyleSheet()


def _build_styles():
    """Return a dict of named ParagraphStyle objects for PDF rendering."""
    return {
        "title": ParagraphStyle(
            "KeepsakeTitle",
            fontName="Times-Bold",
            fontSize=26,
            leading=32,
            textColor=SLATE_900,
            alignment=TA_CENTER,
        ),
        "heading": ParagraphStyle(
            "KeepsakeHeading",
            fontName="Times-Bold",
            fontSize=16,
            leading=20,
            textColor=SLATE_900,
            spaceAfter=12,
        ),
        "body": ParagraphStyle(
            "KeepsakeBody",
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=SLATE_900,
        ),
        "body_center": ParagraphStyle(
            "KeepsakeBodyCenter",
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=SLATE_900,
            alignment=TA_CENTER,
        ),
        "italic_callout": ParagraphStyle(
            "KeepsakeCallout",
            fontName="Times-Roman",
            fontSize=11,
            leading=16,
            textColor=SLATE_900,
            leftIndent=12,
            borderPadding=6,
            borderWidth=0,
            borderColor=SAGE_GREEN,
        ),
        "sentimental": ParagraphStyle(
            "SentimentalMemory",
            fontName="Times-Italic",
            fontSize=9.5,
            leading=13,
            textColor=SLATE_900,
            leftIndent=18,
            rightIndent=18,
        ),
        "badge": ParagraphStyle(
            "CategoryBadge",
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=MUTED_SLATE,
        ),
        "points": ParagraphStyle(
            "PointsValue",
            fontName="Times-Bold",
            fontSize=11,
            textColor=SAGE_GREEN,
        ),
        "disclaimer": ParagraphStyle(
            "LegalDisclaimer",
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=MUTED_SLATE,
            alignment=TA_CENTER,
        ),
        "monospace": ParagraphStyle(
            "MonoSeal",
            fontName="Courier",
            fontSize=8,
            leading=10,
            textColor=SLATE_900,
        ),
        "table_header": ParagraphStyle(
            "TableHeader",
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            textColor=SLATE_900,
        ),
        "table_cell": ParagraphStyle(
            "TableCell",
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=SLATE_900,
        ),
    }


STYLES = _build_styles()

# ---------------------------------------------------------------------------
# Image ingestion helper (cloud buffer per Backend Spec §13.3 Document A Item 3)
# ---------------------------------------------------------------------------

_STORAGE_DRIVER: Optional[StorageDriver] = None


def _get_storage() -> StorageDriver:
    global _STORAGE_DRIVER
    if _STORAGE_DRIVER is None:
        _STORAGE_DRIVER = get_storage_driver()
    return _STORAGE_DRIVER


def _fetch_image_bytes(image_uri: str) -> Optional[io.BytesIO]:
    """Download image from storage into BytesIO buffer for ReportLab.

    Returns None if the file is not found or an error occurs, signaling the
    caller to render a placeholder instead.
    """
    if not image_uri:
        return None
    try:
        storage = _get_storage()
        raw = storage.get(image_uri)
        return io.BytesIO(raw)
    except FileNotFoundError:
        logger.warning("Image not found in storage: %s", image_uri)
        return None
    except Exception:
        logger.exception("Failed to fetch image: %s", image_uri)
        return None


# ---------------------------------------------------------------------------
# Layout overflow protection (Backend Spec §13.3, closing paragraph)
# ---------------------------------------------------------------------------

_TRUNCATION_LIMIT = 500


def _safe_paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    """Create a Paragraph, truncating long text to prevent LayoutError.

    If text exceeds 500 characters, truncates with ellipsis and stores the
    full text in a separate appendix section.
    """
    if len(text) > _TRUNCATION_LIMIT:
        truncated = text[:_TRUNCATION_LIMIT] + "..."
        return Paragraph(truncated, style)
    return Paragraph(text, style)


def _collect_appendix(
    asset_title: str, full_text: str, appendix: list[tuple[str, str]]
) -> None:
    """If text was truncated, add it to the appendix list."""
    if len(full_text) > _TRUNCATION_LIMIT:
        appendix.append((asset_title, full_text))


# ---------------------------------------------------------------------------
# Cover page builder
# ---------------------------------------------------------------------------


def _build_cover(
    title: str,
    subtitle_lines: list[str],
    disclaimer: str = LEGAL_DISCLAIMER,
) -> list:
    """Build flowables for a cover page.

    Args:
        title: Large cover title (e.g., "[Session Title] Keepsake Memory Book").
        subtitle_lines: Metadata lines rendered below the title.
        disclaimer: Legal disclaimer text (from Legal Spec §5).

    Returns:
        List of flowables for the cover page.
    """
    elements: list = []
    elements.append(Spacer(1, 2.0 * inch))
    elements.append(Paragraph(title, STYLES["title"]))
    elements.append(Spacer(1, 0.35 * inch))

    # Horizontal dividing bar in Sage-Green
    bar_data = [[""]]
    bar_table = Table(bar_data, colWidths=[5.5 * inch], rowHeights=[2])
    bar_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SAGE_GREEN),
        ("LINEBELOW", (0, 0), (-1, -1), 0, colors.HexColor(SAGE_GREEN)),
    ]))
    elements.append(bar_table)
    elements.append(Spacer(1, 0.35 * inch))

    for line in subtitle_lines:
        elements.append(Paragraph(line, STYLES["body_center"]))
        elements.append(Spacer(1, 0.1 * inch))

    elements.append(Spacer(1, 1.5 * inch))

    # Legal disclaimer on cover page (Legal Spec §5)
    elements.append(Paragraph(disclaimer, STYLES["disclaimer"]))

    elements.append(PageBreak())
    return elements


# ---------------------------------------------------------------------------
# Document A: Heir Keepsake Memory Book
# ---------------------------------------------------------------------------


def build_keepsake_pdf(
    session: SessionModel,
    heir: UserModel,
    assets: list[AssetModel],
    solver_result: SolverResult,
    audit_logs: list[AuditLogModel],
) -> io.BytesIO:
    """Build the Individual Heir's Keepsake Memory Book PDF (Document A).

    Args:
        session: Session ORM object.
        heir: Heir User ORM object.
        assets: All LIVE/DISTRIBUTED/PRE_ALLOCATED assets for this session.
        solver_result: Output from T15 solve_mnw().
        audit_logs: AuditLog rows for the final SHA-256 seal.

    Returns:
        io.BytesIO buffer containing the complete PDF.
    """
    buf = io.BytesIO()
    elements: list = []

    # --- Cover page ---
    heir_name = (
        " ".join(
            p
            for p in [
                heir.legal_first_name,
                heir.legal_middle_name,
                heir.legal_last_name,
            ]
            if p
        ).strip()
        or heir.username
    )
    now_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    cover_title = f"{session.title or 'Estate'} Keepsake Memory Book"
    subtitle_lines = [
        f"Prepared for: {heir_name}",
        f"Date Generated: {now_str}",
        '"A document of collaborative distribution and shared memory."',
    ]
    elements.extend(_build_cover(cover_title, subtitle_lines))

    # --- Mediation summary ---
    elements.append(Paragraph("Mediation Summary", STYLES["heading"]))
    summary_text = (
        f"This keepsake ledger records the collaborative distribution of "
        f"personal property within the estate of <i>{session.title or 'the decedent'}</i>. "
        f"The allocations reflected herein were determined through the Estate "
        f"Steward's impartial mediation process, governed by a Maximum Nash "
        f"Welfare fair-division algorithm."
    )
    elements.append(_safe_paragraph(summary_text, STYLES["italic_callout"]))
    elements.append(Spacer(1, 0.5 * inch))

    # --- Gridless Keepsake Exhibition ---
    elements.append(Paragraph("Allocated Keepsakes", STYLES["heading"]))
    elements.append(Spacer(1, 0.25 * inch))

    heir_id_str = str(heir.id)
    allocated_asset_ids = solver_result.allocation.get(heir_id_str, [])

    # Separate allocated assets from the full list
    allocated_assets: list[AssetModel] = []
    unallocated_assets: list[AssetModel] = []
    asset_map: dict[str, AssetModel] = {str(a.id): a for a in assets}

    for aid in allocated_asset_ids:
        asset = asset_map.get(aid)
        if asset:
            allocated_assets.append(asset)

    for asset in assets:
        if str(asset.id) not in allocated_asset_ids:
            unallocated_assets.append(asset)

    # Also include pre-allocated assets assigned to this heir
    for asset in assets:
        if (
            asset.allocated_to_id
            and str(asset.allocated_to_id) == heir_id_str
            and str(asset.id) not in allocated_asset_ids
        ):
            allocated_assets.append(asset)

    appendix: list[tuple[str, str]] = []

    if not allocated_assets:
        elements.append(
            Paragraph(
                "<i>No assets were allocated in this distribution.</i>",
                STYLES["body"],
            )
        )
    else:
        for asset in allocated_assets:
            block = _build_keepsake_block(asset, appendix)
            elements.append(KeepTogether(block))
            elements.append(Spacer(1, 0.75 * inch))

    # --- Appendix for truncated descriptions ---
    if appendix:
        elements.append(PageBreak())
        elements.append(Paragraph("Appendix: Full Descriptions", STYLES["heading"]))
        for title, full_text in appendix:
            elements.append(Paragraph(f"<b>{title}</b>", STYLES["body"]))
            elements.append(Paragraph(full_text, STYLES["body"]))
            elements.append(Spacer(1, 0.2 * inch))

    # --- Cryptographic Monospace Seal ---
    if audit_logs:
        elements.append(Spacer(1, 0.5 * inch))
        last_hash = audit_logs[-1].sha256_hash
        seal_text = f"SHA-256 Seal: {last_hash}"
        seal_para = Paragraph(seal_text, STYLES["monospace"])
        seal_table = Table([[seal_para]], colWidths=[6.0 * inch])
        seal_table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(LIGHT_GREY_BORDER)),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(seal_table)

    # --- Build document ---
    doc = BaseDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )

    portrait_frame = Frame(54, 54, letter[0] - 108, letter[1] - 108, id="portrait")
    doc.addPageTemplates([
        PageTemplate(
            id="portrait",
            frames=[portrait_frame],
            onPage=_draw_page_background,
        ),
    ])

    doc.build(elements, canvasmaker=NumberedCanvas)
    buf.seek(0)
    return buf


def _build_keepsake_block(
    asset: AssetModel,
    appendix: list[tuple[str, str]],
) -> list:
    """Build a single asymmetric keepsake entry block.

    Uses an anti-grid, borderless two-column structure:
      Left column (3.2in): scaled keepsake photo
      Right column (3.8in): title, category badge, points, sentimental memory
    """
    elements: list = []

    # Left column: image or placeholder
    image_flowable = _render_keepsake_image(asset)
    left_cell = image_flowable

    # Right column: typographical stack
    right_paragraphs: list = []

    title = asset.title or "Untitled Keepsake"
    right_paragraphs.append(Paragraph(title, STYLES["heading"]))
    right_paragraphs.append(Spacer(1, 0.05 * inch))

    category = asset.category or "Other"
    right_paragraphs.append(
        Paragraph(f"Category: {category}", STYLES["badge"])
    )
    right_paragraphs.append(Spacer(1, 0.1 * inch))

    # Points value — look up from valuations
    points_text = "Allocated via fair division"
    if hasattr(asset, "valuations") and asset.valuations:
        # Use the first valuation as a heuristic
        pts = asset.valuations[0].points if asset.valuations else 0
        points_text = f"Allocated: {pts} Points"
    right_paragraphs.append(Paragraph(points_text, STYLES["points"]))
    right_paragraphs.append(Spacer(1, 0.15 * inch))

    # Sentimental memory / description
    description = asset.description or ""
    sentimental = asset.sentiment_tag or ""
    memory_text = sentimental if sentimental else description
    if memory_text:
        _collect_appendix(title, memory_text, appendix)
        right_paragraphs.append(_safe_paragraph(memory_text, STYLES["sentimental"]))

    # Build the two-column structure using a borderless table
    left_col = [left_cell] if not isinstance(left_cell, list) else left_cell
    right_col = right_paragraphs if right_paragraphs else [Paragraph("", STYLES["body"])]

    # Pad shorter column to match row count
    max_rows = max(len(left_col), len(right_col))
    while len(left_col) < max_rows:
        left_col.append(Paragraph("", STYLES["body"]))
    while len(right_col) < max_rows:
        right_col.append(Paragraph("", STYLES["body"]))

    table_data: list[list] = []
    for i in range(max_rows):
        table_data.append([left_col[i], right_col[i]])

    col_widths = [3.2 * inch, 3.8 * inch]
    block_table = Table(table_data, colWidths=col_widths)
    block_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    return [block_table]


def _render_keepsake_image(asset: AssetModel):
    """Render asset image or placeholder for the keepsake block."""
    if asset.image_uri:
        img_buf = _fetch_image_bytes(asset.image_uri)
        if img_buf:
            try:
                img = Image(img_buf, width=3.0 * inch, height=3.0 * inch)
                # Preserve aspect ratio within bounds
                img.drawWidth = min(img.drawWidth, 3.0 * inch)
                img.drawHeight = min(img.drawHeight, 3.0 * inch)
                return img
            except Exception:
                logger.exception("Failed to decode image for asset %s", asset.id)

    # Placeholder block
    placeholder_data = [["Keepsake Photo"]]
    placeholder = Table(placeholder_data, colWidths=[3.0 * inch], rowHeights=[2.5 * inch])
    placeholder.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#E5E7EB")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), MUTED_SLATE),
    ]))
    return placeholder


# ---------------------------------------------------------------------------
# Document B: Final Distribution & Probate Audit Ledger
# ---------------------------------------------------------------------------


def build_probate_ledger_pdf(
    session: SessionModel,
    heirs: list[UserModel],
    assets: list[AssetModel],
    solver_result: SolverResult,
    audit_logs: list[AuditLogModel],
    notice_log: NoticeLog,
) -> io.BytesIO:
    """Build the Final Distribution & Probate Audit Ledger PDF (Document B).

    Args:
        session: Session ORM object.
        heirs: All Heir User ORM objects for this session.
        assets: All assets for this session.
        solver_result: Output from T15 solve_mnw().
        audit_logs: AuditLog rows for admin intervention log and SHA-256 seal.
        notice_log: T71 NoticeLog data contract for Proof of Notice Log section.

    Returns:
        io.BytesIO buffer containing the complete PDF.
    """
    buf = io.BytesIO()
    elements: list = []

    # --- Cover page ---
    executor_user = _find_admin(heirs)
    now_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    closure_str = now_str
    start_str = (
        session.created_at.strftime("%B %d, %Y")
        if session.created_at
        else "Unknown"
    )

    cover_title = f"{session.title or 'Estate'} Final Distribution & Probate Audit Ledger"
    subtitle_lines = [
        _estate_identity_line(session),
        *_executor_identity_lines(executor_user),
        f"Session Start: {start_str}",
        f"Closure Date: {closure_str}",
        '"Official estate distribution record for probate court filing."',
    ]
    elements.extend(_build_cover(cover_title, subtitle_lines))

    appendix: list[tuple[str, str]] = []

    # --- 2. Registered Beneficiary Table ---
    elements.append(Paragraph("Registered Beneficiaries", STYLES["heading"]))
    elements.append(Spacer(1, 0.15 * inch))
    elements.append(_build_beneficiary_table(heirs))
    elements.append(Spacer(1, 0.4 * inch))

    elements.append(_build_scale_summary(heirs, assets))
    elements.append(Spacer(1, 0.4 * inch))

    # --- 3. Proof of Notice Log ---
    elements.append(Paragraph("Proof of Notice Log", STYLES["heading"]))
    elements.append(Spacer(1, 0.15 * inch))
    elements.append(_build_notice_log_table(notice_log))
    elements.append(Spacer(1, 0.4 * inch))

    # --- 4. Final Asset Allocation Grid ---
    elements.append(Paragraph("Final Asset Allocation Grid", STYLES["heading"]))
    elements.append(Spacer(1, 0.15 * inch))
    elements.append(_build_asset_allocation_grid(assets, heirs, solver_result, appendix))
    elements.append(Spacer(1, 0.4 * inch))

    # --- 4.5 Physical Distribution Responsibility ---
    elements.append(Paragraph("Post-Allocation Distribution Responsibility", STYLES["heading"]))
    elements.append(Spacer(1, 0.15 * inch))
    elements.append(_build_distribution_responsibility_notice())
    elements.append(Spacer(1, 0.4 * inch))

    # --- 5. Maximum Nash Welfare Product Display ---
    elements.append(_build_mnw_callout(solver_result.mnw_product_value))
    elements.append(Spacer(1, 0.4 * inch))

    # --- 6. Deterministic Tie-Breaker Resolution Record (T70) ---
    if solver_result.tie_breaker_events:
        elements.append(Paragraph("Deterministic Tie-Breaker Resolution Record", STYLES["heading"]))
        elements.append(Spacer(1, 0.15 * inch))
        elements.append(_build_tie_breaker_table(solver_result.tie_breaker_events))
        elements.append(Spacer(1, 0.4 * inch))

    # --- 7. Admin Intervention Log (if any) ---
    admin_interventions = [
        al for al in audit_logs if al.event_type == "ADMIN_OVERRIDE"
    ]
    if admin_interventions:
        elements.append(Paragraph("Admin Intervention Log", STYLES["heading"]))
        elements.append(Spacer(1, 0.15 * inch))
        elements.append(_build_intervention_table(admin_interventions))
        elements.append(Spacer(1, 0.4 * inch))

    # --- 7.5 Inventory Modification Log (if any) ---
    inventory_mods = [
        al for al in audit_logs if al.event_type in ("ASSET_CREATED", "ASSET_UPDATED", "ASSET_DELETED")
    ]
    if inventory_mods:
        elements.append(Paragraph("Inventory Modification Log", STYLES["heading"]))
        elements.append(Spacer(1, 0.15 * inch))
        elements.append(_build_inventory_mods_table(inventory_mods))
        elements.append(Spacer(1, 0.4 * inch))

    # --- 7.6 Executor-Heir Communication Log (if any) ---
    communication_events = [
        al for al in audit_logs if al.event_type in (
            "SUPPORT_REQUEST_CREATED",
            "SUPPORT_REPLY_SENT",
            "SUPPORT_REQUEST_RESOLVED",
        )
    ]
    if communication_events:
        elements.append(Paragraph("Executor-Heir Communication Log", STYLES["heading"]))
        elements.append(Spacer(1, 0.15 * inch))
        elements.append(_build_communication_log_table(communication_events))
        elements.append(Spacer(1, 0.4 * inch))

    # --- 7. Points Valuation Matrix ---
    elements.append(Paragraph("Points Valuation Matrix", STYLES["heading"]))
    elements.append(Spacer(1, 0.15 * inch))

    heir_heirs = [h for h in heirs if h.role == "HEIR"]
    num_heirs = len(heir_heirs)

    if num_heirs > 4:
        # Landscape page transition per Backend Spec §13.3 Item 7
        elements.append(NextPageTemplate("landscape"))
        elements.append(PageBreak())
        elements.append(
            _build_valuation_matrix_landscape(assets, heir_heirs, appendix)
        )
        elements.append(NextPageTemplate("portrait"))
    else:
        elements.append(_build_valuation_matrix_portrait(assets, heir_heirs, appendix))
    elements.append(Spacer(1, 0.4 * inch))

    # --- 8. Mathematical Proof ---
    elements.append(Paragraph("Mathematical Proof", STYLES["heading"]))
    elements.append(Spacer(1, 0.15 * inch))
    elements.extend(_build_mathematical_proof(solver_result, heir_heirs))
    elements.append(Spacer(1, 0.4 * inch))

    # --- 9. Cryptographic Integrity Seal ---
    if audit_logs:
        last_hash = audit_logs[-1].sha256_hash
        seal_text = (
            f"SHA-256 Seal: {last_hash}\n\n"
            "This ledger has been cryptographically sealed. Each state change "
            "is recorded in a tamper-proof hash chain. To verify integrity, "
            "re-compute SHA-256 hashes row-by-row from the database and "
            "compare against the stored values. Any break in the chain "
            "indicates tampering."
        )
        seal_para = Paragraph(seal_text.replace("\n", "<br/>"), STYLES["monospace"])
        seal_table = Table([[seal_para]], colWidths=[6.0 * inch])
        seal_table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(LIGHT_GREY_BORDER)),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(seal_table)

    # --- Appendix for truncated descriptions ---
    if appendix:
        elements.append(PageBreak())
        elements.append(Paragraph("Appendix: Full Descriptions", STYLES["heading"]))
        for title, full_text in appendix:
            elements.append(Paragraph(f"<b>{title}</b>", STYLES["body"]))
            elements.append(Paragraph(full_text, STYLES["body"]))
            elements.append(Spacer(1, 0.2 * inch))

    # --- Build document with portrait + optional landscape templates ---
    portrait_frame = Frame(54, 54, letter[0] - 108, letter[1] - 108, id="portrait")
    landscape_frame = Frame(
        54, 54, landscape(letter)[0] - 108, landscape(letter)[1] - 108, id="landscape"
    )

    page_templates = [
        PageTemplate(
            id="portrait",
            frames=[portrait_frame],
            onPage=_draw_page_background,
        ),
    ]

    if num_heirs > 4:
        page_templates.append(
            PageTemplate(
                id="landscape",
                frames=[landscape_frame],
                pagesize=landscape(letter),
                onPage=_draw_page_background,
            )
        )

    doc = BaseDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )
    for pt in page_templates:
        doc.addPageTemplates([pt])

    doc.build(elements, canvasmaker=NumberedCanvas)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Document B — sub-section builders
# ---------------------------------------------------------------------------


def _find_admin(users: list[UserModel]) -> Optional[UserModel]:
    for u in users:
        if u.role == "ADMIN":
            return u
    return None


def _format_pdf_date(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d") if value else "—"


def _format_pdf_datetime(value: datetime | None) -> str:
    if not value:
        return "—"
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%d %H:%M UTC")


def _legal_name(user: UserModel | None) -> str:
    if not user:
        return ""
    return " ".join(
        p
        for p in [user.legal_first_name, user.legal_middle_name, user.legal_last_name]
        if p
    ).strip()


def _estate_identity_line(session: SessionModel) -> str:
    decedent_name = (
        getattr(session, "decedent_legal_name", None)
        or getattr(session, "decedent_name", None)
        or getattr(session, "estate_of", None)
    )
    if decedent_name:
        return f"Estate / Decedent: {escape(str(decedent_name))}"

    session_title = getattr(session, "title", None) or "Untitled session"
    return (
        "Estate / Decedent: Not separately recorded "
        f"(session title: {escape(str(session_title))})"
    )


def _executor_identity_lines(executor_user: UserModel | None) -> list[str]:
    if not executor_user:
        return ["Executor Legal Name: Not recorded", "Executor Account: Not recorded"]

    legal_name = _legal_name(executor_user)
    lines = [
        f"Executor Legal Name: {escape(legal_name) if legal_name else 'Not recorded'}",
    ]
    account_parts = []
    if executor_user.username:
        account_parts.append(f"account {escape(executor_user.username)}")
    if executor_user.email:
        account_parts.append(escape(executor_user.email))
    if account_parts:
        lines.append(f"Executor Account: {'; '.join(account_parts)}")
    return lines


def _build_scale_summary(heirs: list[UserModel], assets: list[AssetModel]) -> Table:
    heir_count = len([h for h in heirs if h.role == "HEIR"])
    asset_count = len(assets)
    beneficiary_label = "beneficiary" if heir_count == 1 else "beneficiaries"
    item_label = "item" if asset_count == 1 else "items"
    scale_text = (
        f"Ledger scale summary: {heir_count} registered {beneficiary_label} "
        f"and {asset_count} catalog {item_label}. Long ledgers are expected for larger "
        "estates; tables repeat headers across pages, and the points valuation "
        "matrix switches to a landscape page layout when more than four "
        "beneficiaries participate."
    )
    table = Table(
        [[Paragraph(scale_text, STYLES["body"])]],
        colWidths=[6.8 * inch],
    )
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(LIGHT_GREY_BORDER)),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAF7")),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def _build_distribution_responsibility_notice() -> Table:
    text = (
        "This ledger records the final allocation decision; it does not by itself "
        "certify that physical possession has transferred. Unless a court order "
        "or estate attorney directs otherwise, the executor/personal representative "
        "should retain custody control until pickup, delivery, shipping, or storage "
        "is documented. Recommended follow-up records include distribution date, "
        "method, receiving beneficiary, pickup/delivery notes, condition at handoff, "
        "and recipient acknowledgment or signature."
    )
    table = Table(
        [[Paragraph(text, STYLES["body"])]],
        colWidths=[6.8 * inch],
    )
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor(SAGE_GREEN)),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F0F5EE")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
    ]))
    return table


def _build_beneficiary_table(heirs: list[UserModel]) -> Table:
    heir_heirs = [h for h in heirs if h.role == "HEIR"]
    header = [
        Paragraph("Name", STYLES["table_header"]),
        Paragraph("Email", STYLES["table_header"]),
        Paragraph("Created", STYLES["table_header"]),
        Paragraph("Submitted", STYLES["table_header"]),
        Paragraph("Status", STYLES["table_header"]),
    ]
    data = [header]

    for h in heir_heirs:
        name = _legal_name(h) or h.username
        email = h.email or "—"
        created = _format_pdf_date(h.created_at)
        submitted = _format_pdf_datetime(getattr(h, "submitted_at", None))
        status = h.status
        data.append([
            Paragraph(name, STYLES["table_cell"]),
            Paragraph(email, STYLES["table_cell"]),
            Paragraph(created, STYLES["table_cell"]),
            Paragraph(submitted, STYLES["table_cell"]),
            Paragraph(status, STYLES["table_cell"]),
        ])

    col_widths = [1.55 * inch, 1.85 * inch, 1.0 * inch, 1.55 * inch, 0.85 * inch]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(CREAM_BG)),
        ("TEXTCOLOR", (0, 0), (-1, 0), SLATE_900),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor(WARM_GREY)),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, colors.HexColor(WARM_GREY)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _build_notice_log_table(notice_log: NoticeLog) -> Table:
    header = [
        Paragraph("Heir", STYLES["table_header"]),
        Paragraph("Email", STYLES["table_header"]),
        Paragraph("Invite Created", STYLES["table_header"]),
        Paragraph("Dispatched", STYLES["table_header"]),
        Paragraph("Expires", STYLES["table_header"]),
        Paragraph("Submitted", STYLES["table_header"]),
        Paragraph("Outcome", STYLES["table_header"]),
    ]
    data = [header]

    for entry in notice_log.entries:
        invite_created = _format_pdf_datetime(entry.invite_created_at)
        dispatched = _format_pdf_datetime(entry.invitation_dispatched_at)
        expires = _format_pdf_datetime(entry.invite_expires_at)
        submitted = _format_pdf_datetime(entry.submitted_at)
        summary = entry.participation_summary
        data.append([
            Paragraph(entry.legal_name or entry.username, STYLES["table_cell"]),
            Paragraph(entry.email or "—", STYLES["table_cell"]),
            Paragraph(invite_created, STYLES["table_cell"]),
            Paragraph(dispatched, STYLES["table_cell"]),
            Paragraph(expires, STYLES["table_cell"]),
            Paragraph(submitted, STYLES["table_cell"]),
            Paragraph(summary, STYLES["table_cell"]),
        ])

    col_widths = [
        1.05 * inch,
        1.15 * inch,
        0.95 * inch,
        0.95 * inch,
        0.95 * inch,
        0.95 * inch,
        0.8 * inch,
    ]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(CREAM_BG)),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor(WARM_GREY)),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, colors.HexColor(WARM_GREY)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _display_user_name(user: UserModel | None, fallback: str = "—") -> str:
    if not user:
        return fallback
    legal_name = " ".join(
        p
        for p in [user.legal_first_name, user.legal_middle_name, user.legal_last_name]
        if p
    ).strip()
    return legal_name or user.username or user.email or fallback


def _valuation_source_label(source: str | None) -> str:
    if not source:
        return "Not declared - executor should document appraisal basis"

    source_text = source.strip()
    lower = source_text.lower()
    if "ai" in lower:
        return f"{source_text} (AI-generated estimate, not a professional appraisal)"
    if "professional" in lower or "certified" in lower or "appraiser" in lower:
        return f"{source_text} (professional appraisal)"
    if "ebay" in lower or "auction" in lower or "comparable" in lower or "market" in lower:
        return f"{source_text} (market comparable estimate)"
    if "estate sale" in lower:
        return f"{source_text} (estate sale estimate)"
    if "personal" in lower:
        return f"{source_text} (executor/family estimate)"
    return source_text


def _build_asset_allocation_grid(
    assets: list[AssetModel],
    heirs: list[UserModel],
    solver_result: SolverResult,
    appendix: list[tuple[str, str]],
) -> Table:
    header = [
        Paragraph("Image", STYLES["table_header"]),
        Paragraph("Title / Description", STYLES["table_header"]),
        Paragraph("Allocated To", STYLES["table_header"]),
        Paragraph("Appraisal Range / Source", STYLES["table_header"]),
    ]
    data = [header]

    allocation = solver_result.allocation
    heir_name_by_id = {str(heir.id): _display_user_name(heir, str(heir.id)) for heir in heirs}
    # Reverse map: asset_id -> heir_id
    asset_to_heir: dict[str, str] = {}
    for heir_id, asset_ids in allocation.items():
        for aid in asset_ids:
            asset_to_heir[aid] = heir_id

    for asset in assets:
        image_cell = _small_image_cell(asset)
        desc = asset.description or ""
        title_text = f"<b>{asset.title or 'Untitled'}</b><br/>{desc}"
        _collect_appendix(asset.title or "Untitled", desc, appendix)
        title_cell = _safe_paragraph(title_text, STYLES["table_cell"])

        allocated_to = "—"
        if asset.allocated_to_id:
            allocated_id = str(asset.allocated_to_id)
            allocated_to = heir_name_by_id.get(
                allocated_id,
                _display_user_name(getattr(asset, "allocated_to", None), allocated_id),
            )
        elif str(asset.id) in asset_to_heir:
            allocated_id = asset_to_heir[str(asset.id)]
            allocated_to = heir_name_by_id.get(allocated_id, allocated_id)

        allocated_cell = Paragraph(allocated_to, STYLES["table_cell"])

        val_min = asset.valuation_min
        val_max = asset.valuation_max
        if val_min is not None and val_max is not None:
            appraisal = f"${val_min:,.0f} – ${val_max:,.0f}"
        elif val_min is not None:
            appraisal = f"${val_min:,.0f}+"
        elif val_max is not None:
            appraisal = f"Up to ${val_max:,.0f}"
        else:
            appraisal = "—"
        source_label = _valuation_source_label(asset.valuation_source)
        appraisal_cell = _safe_paragraph(
            f"<b>{appraisal}</b><br/><i>Source: {escape(source_label)}</i>",
            STYLES["table_cell"],
        )

        data.append([image_cell, title_cell, allocated_cell, appraisal_cell])

    col_widths = [1.2 * inch, 2.8 * inch, 1.8 * inch, 1.2 * inch]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(CREAM_BG)),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor(WARM_GREY)),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, colors.HexColor(WARM_GREY)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _small_image_cell(asset: AssetModel):
    """Render a small 1.2in image cell or placeholder for the allocation grid."""
    if asset.image_uri:
        img_buf = _fetch_image_bytes(asset.image_uri)
        if img_buf:
            try:
                img = Image(img_buf, width=1.0 * inch, height=1.0 * inch)
                return img
            except Exception:
                pass

    placeholder_data = [["Photo"]]
    placeholder = Table(placeholder_data, colWidths=[1.0 * inch], rowHeights=[0.8 * inch])
    placeholder.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#E5E7EB")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("TEXTCOLOR", (0, 0), (-1, -1), MUTED_SLATE),
    ]))
    return placeholder


def _build_mnw_callout(mnw_product_value: float) -> Table:
    """Build a centered MNW product callout box per Spec §13.3 Item 5."""
    if mnw_product_value > 0:
        text = f"Maximum Nash Welfare Product: {mnw_product_value:,.2f}"
    else:
        text = (
            "Maximum Nash Welfare Product: 0.00<br/>"
            "<font size='9'>Review note: zero usually means no positive submitted points were available, "
            "no eligible valued assets were allocated, or this was a one-participant/no-bid test.</font>"
        )
    para = Paragraph(text, STYLES["heading"])
    table = Table([[para]], colWidths=[5.0 * inch])
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor(SAGE_GREEN)),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F0F5EE")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def _build_intervention_table(audit_logs: list[AuditLogModel]) -> Table:
    header = [
        Paragraph("Timestamp", STYLES["table_header"]),
        Paragraph("Asset(s)", STYLES["table_header"]),
        Paragraph("Allocated To", STYLES["table_header"]),
        Paragraph("Reason", STYLES["table_header"]),
    ]
    data = [header]

    for al in audit_logs:
        ts = (
            al.created_at.strftime("%Y-%m-%d %H:%M:%S")
            if al.created_at
            else "—"
        )
        snapshot = al.state_snapshot or {}
        assets_str = str(snapshot.get("asset_ids", "—"))
        allocated_str = str(snapshot.get("allocated_to", "—"))
        reason_str = str(snapshot.get("reason", "—"))

        data.append([
            Paragraph(ts, STYLES["table_cell"]),
            Paragraph(assets_str, STYLES["table_cell"]),
            Paragraph(allocated_str, STYLES["table_cell"]),
            Paragraph(reason_str, STYLES["table_cell"]),
        ])

    col_widths = [1.3 * inch, 1.5 * inch, 1.5 * inch, 2.7 * inch]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(CREAM_BG)),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor(WARM_GREY)),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, colors.HexColor(WARM_GREY)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _build_inventory_mods_table(audit_logs: list[AuditLogModel]) -> Table:
    header = [
        Paragraph("Timestamp", STYLES["table_header"]),
        Paragraph("Asset", STYLES["table_header"]),
        Paragraph("Change Details", STYLES["table_header"]),
        Paragraph("Classification", STYLES["table_header"]),
        Paragraph("Reason", STYLES["table_header"]),
    ]
    data = [header]

    for al in audit_logs:
        ts = (
            al.created_at.strftime("%Y-%m-%d %H:%M:%S")
            if al.created_at
            else "—"
        )
        snapshot = al.state_snapshot or {}
        asset_title = str(snapshot.get("asset_title") or "Unnamed Asset")
        evt = snapshot.get("event")
        classification = str(snapshot.get("classification") or "MINOR")
        reason = str(snapshot.get("reason") or "—")

        # Format details
        if evt == "ASSET_CREATED":
            details = f"Asset staged in category: {snapshot.get('category', '—')}"
        elif evt == "ASSET_DELETED":
            details = "Asset deleted from inventory."
        elif evt == "ASSET_UPDATED":
            chg = snapshot.get("changes", {})
            if "status" in chg and chg["status"].get("new") == "LIVE":
                details = f"Asset published as LIVE (Valuation: ${chg.get('valuation_min', {}).get('new', 0)} – ${chg.get('valuation_max', {}).get('new', 0)})"
            else:
                field_changes = []
                for k, v in chg.items():
                    field_changes.append(f"{k}: '{v.get('old')}' -> '{v.get('new')}'")
                details = "Modified: " + ", ".join(field_changes)
        else:
            details = f"Unknown event: {evt}"

        data.append([
            Paragraph(ts, STYLES["table_cell"]),
            Paragraph(asset_title, STYLES["table_cell"]),
            Paragraph(details, STYLES["table_cell"]),
            Paragraph(classification, STYLES["table_cell"]),
            Paragraph(reason, STYLES["table_cell"]),
        ])

    col_widths = [1.2 * inch, 1.3 * inch, 2.3 * inch, 1.0 * inch, 1.2 * inch]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(CREAM_BG)),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor(WARM_GREY)),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, colors.HexColor(WARM_GREY)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _build_communication_log_table(audit_logs: list[AuditLogModel]) -> Table:
    header = [
        Paragraph("Timestamp", STYLES["table_header"]),
        Paragraph("Event", STYLES["table_header"]),
        Paragraph("Heir", STYLES["table_header"]),
        Paragraph("Record Summary", STYLES["table_header"]),
    ]
    data = [header]

    event_labels = {
        "SUPPORT_REQUEST_CREATED": "Request",
        "SUPPORT_REPLY_SENT": "Executor Reply",
        "SUPPORT_REQUEST_RESOLVED": "Resolved",
    }

    for al in audit_logs:
        ts = (
            al.created_at.strftime("%Y-%m-%d %H:%M:%S")
            if al.created_at
            else "—"
        )
        snapshot = al.state_snapshot or {}
        event = event_labels.get(al.event_type, al.event_type)
        heir = str(snapshot.get("heir_username") or snapshot.get("heir_id") or "—")

        if al.event_type == "SUPPORT_REQUEST_CREATED":
            details = f"Request: {snapshot.get('message', '—')}"
        elif al.event_type == "SUPPORT_REPLY_SENT":
            details = (
                f"Original: {snapshot.get('original_message', '—')}\n"
                f"Reply: {snapshot.get('admin_response', '—')}"
            )
        elif al.event_type == "SUPPORT_REQUEST_RESOLVED":
            details = (
                f"Support request {snapshot.get('support_request_id', '—')} resolved "
                f"by {snapshot.get('resolved_by_username', 'Executor')}"
            )
        else:
            details = str(snapshot)

        data.append([
            Paragraph(ts, STYLES["table_cell"]),
            Paragraph(event, STYLES["table_cell"]),
            Paragraph(heir, STYLES["table_cell"]),
            _safe_paragraph(escape(details).replace("\n", "<br/>"), STYLES["table_cell"]),
        ])

    col_widths = [1.3 * inch, 1.1 * inch, 1.3 * inch, 3.3 * inch]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(CREAM_BG)),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor(WARM_GREY)),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, colors.HexColor(WARM_GREY)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _build_valuation_matrix_portrait(
    assets: list[AssetModel],
    heirs: list[UserModel],
    appendix: list[tuple[str, str]],
) -> Table:
    """Build points valuation matrix in portrait orientation."""
    num_heirs = len(heirs)
    if num_heirs == 0:
        return Table([["No heirs."]], colWidths=[7.0 * inch])

    # Column widths: 2.5in for title, remaining 4.5in split among heirs
    title_width = 2.5 * inch
    heir_width = (4.5 * inch) / num_heirs if num_heirs > 0 else 0

    col_widths = [title_width] + [heir_width] * num_heirs

    header: list = [Paragraph("Asset", STYLES["table_header"])]
    for h in heirs:
        name = h.legal_first_name or h.username
        header.append(Paragraph(name, STYLES["table_header"]))

    data = [header]

    for asset in assets:
        title = asset.title or "Untitled"
        row: list = [Paragraph(title, STYLES["table_cell"])]
        for h in heirs:
            pts = 0
            if hasattr(asset, "valuations") and asset.valuations:
                for v in asset.valuations:
                    if str(v.heir_id) == str(h.id):
                        pts = v.points
                        break
            row.append(Paragraph(str(pts), STYLES["table_cell"]))
        data.append(row)

    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(CREAM_BG)),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor(WARM_GREY)),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, colors.HexColor(WARM_GREY)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
    ]))
    return table


def _build_valuation_matrix_landscape(
    assets: list[AssetModel],
    heirs: list[UserModel],
    appendix: list[tuple[str, str]],
) -> Table:
    """Build points valuation matrix in landscape orientation (>4 heirs)."""
    num_heirs = len(heirs)
    if num_heirs == 0:
        return Table([["No heirs."]], colWidths=[9.5 * inch])

    # Column widths: 3.5in for title, remaining 6.0in split among heirs
    title_width = 3.5 * inch
    heir_width = (6.0 * inch) / num_heirs if num_heirs > 0 else 0

    col_widths = [title_width] + [heir_width] * num_heirs

    header: list = [Paragraph("Asset", STYLES["table_header"])]
    for h in heirs:
        name = h.legal_first_name or h.username
        header.append(Paragraph(name, STYLES["table_header"]))

    data = [header]

    for asset in assets:
        title = asset.title or "Untitled"
        row: list = [Paragraph(title, STYLES["table_cell"])]
        for h in heirs:
            pts = 0
            if hasattr(asset, "valuations") and asset.valuations:
                for v in asset.valuations:
                    if str(v.heir_id) == str(h.id):
                        pts = v.points
                        break
            row.append(Paragraph(str(pts), STYLES["table_cell"]))
        data.append(row)

    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(CREAM_BG)),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor(WARM_GREY)),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, colors.HexColor(WARM_GREY)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
    ]))
    return table


def _build_tie_breaker_table(events: list[TieBreakerEvent]) -> Table:
    """Build the Deterministic Tie-Breaker Resolution Record table (T70).

    Per Legal Spec §3 Item 6: shows which heirs tied, their points,
    submission timestamps, and the deterministic outcome.
    """
    header = [
        Paragraph("Asset", STYLES["table_header"]),
        Paragraph("Tied Heirs", STYLES["table_header"]),
        Paragraph("Points", STYLES["table_header"]),
        Paragraph("Winner", STYLES["table_header"]),
        Paragraph("Rule Applied", STYLES["table_header"]),
    ]
    data = [header]

    for event in events:
        data.append([
            Paragraph(event.asset_id, STYLES["table_cell"]),
            Paragraph(", ".join(event.tied_heir_ids), STYLES["table_cell"]),
            Paragraph(str(event.points), STYLES["table_cell"]),
            Paragraph(event.winner_heir_id, STYLES["table_cell"]),
            Paragraph(event.reason, STYLES["table_cell"]),
        ])

    col_widths = [1.2 * inch, 2.2 * inch, 0.7 * inch, 1.3 * inch, 1.6 * inch]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(CREAM_BG)),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor(WARM_GREY)),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, colors.HexColor(WARM_GREY)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ALIGN", (2, 0), (2, -1), "CENTER"),
    ]))
    return table


def _build_mathematical_proof(
    solver_result: SolverResult,
    heirs: list[UserModel],
) -> list:
    """Build the mathematical proof section (Backend Spec §13.3 Item 8)."""
    elements: list = []

    proof_text = (
        "The allocations in this ledger were determined using the Maximum Nash "
        "Welfare (MNW) fair-division algorithm. The MNW algorithm selects an "
        "allocation that maximizes the product of individual utilities:"
    )
    elements.append(Paragraph(proof_text, STYLES["body"]))
    elements.append(Spacer(1, 0.1 * inch))

    formula = (
        "<b>max ∏<sub>i</sub> u<sub>i</sub>(A<sub>i</sub>)</b> "
        "subject to each asset being assigned to exactly one heir, where "
        "u<sub>i</sub>(A<sub>i</sub>) is the sum of points heir i allocated to "
        "the assets assigned to them."
    )
    elements.append(Paragraph(formula, STYLES["body"]))
    elements.append(Spacer(1, 0.15 * inch))

    if solver_result.mnw_product_value > 0:
        guarantee_text = (
            f"The computed Maximum Nash Welfare Product for this session is "
            f"<b>{solver_result.mnw_product_value:,.2f}</b>. No alternative "
            "division of these assets yields a higher Nash product without "
            "reducing the utility of at least one participant. This guarantee "
            "holds under the standard MNW optimality criterion."
        )
    else:
        guarantee_text = (
            "The computed Maximum Nash Welfare Product for this session is "
            "<b>0.00</b>. This does not necessarily indicate a software error: "
            "it can occur in a one-participant systems test, when no positive "
            "point valuations were submitted, or when a participating heir "
            "receives no positively valued assets. For real multi-heir estates, "
            "a zero product should be reviewed before relying on the ledger."
        )
    elements.append(Paragraph(guarantee_text, STYLES["body"]))

    if solver_result.tie_breaker_events:
        elements.append(Spacer(1, 0.15 * inch))
        elements.append(
            Paragraph(
                "A full record of deterministic tie-breaker resolutions is provided in "
                "the Deterministic Tie-Breaker Resolution Record section above.",
                STYLES["body"],
            )
        )

    return elements


# ---------------------------------------------------------------------------
# T33 — Active Abstention Waiver PDF Receipt
# ---------------------------------------------------------------------------


def _wrap_text(text: str, canvas_obj, max_width: float) -> list[str]:
    """Wrap a text string to fit within a given width on a ReportLab canvas."""
    words = text.split()
    lines: list[str] = []
    current_line = ""
    for word in words:
        test_line = f"{current_line} {word}".strip()
        if canvas_obj.stringWidth(test_line, "Times-Roman", 11) <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    return lines if lines else [text]


def build_waiver_receipt_pdf(
    session: SessionModel,
    heir: UserModel,
    legal_name_signature: str,
    ip_address: str,
    timestamp_utc: datetime,
    sha256_hash: str,
) -> io.BytesIO:
    """Build a single-page waiver receipt PDF per Backend Spec §9.5.

    Contains the E-SIGN disclosure, signed waiver text, Heir's legal name,
    IP address, timestamp, and SHA-256 block hash seal.
    """
    buf = io.BytesIO()

    c = NumberedCanvas(buf, pagesize=letter)
    c.setTitle(f"Abstention Waiver Receipt — {heir.username}")

    # Cream background
    c.setFillColor(CREAM_BG)
    c.rect(0, 0, 8.5 * 72, 11 * 72, fill=True, stroke=False)

    y = 10.25 * inch  # Starting Y position from top

    # Title
    c.setFont("Times-Bold", 24)
    c.setFillColor(SLATE_900)
    c.drawCentredString(4.25 * inch, y, "Abstention Waiver Receipt")
    y -= 0.5 * inch

    # Horizontal rule
    c.setStrokeColor(WARM_GREY)
    c.setLineWidth(1)
    c.line(1.0 * inch, y, 7.5 * inch, y)
    y -= 0.35 * inch

    # Session info
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(SLATE_900)
    c.drawString(1.0 * inch, y, f"Session: {session.title or session.id}")
    y -= 0.22 * inch
    c.setFont("Helvetica", 10)
    c.setFillColor(MUTED_SLATE)
    c.drawString(1.0 * inch, y, f"Session ID: {session.id}")
    y -= 0.35 * inch

    # Heir info section
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(SLATE_900)
    c.setStrokeColor(WARM_GREY)
    c.setLineWidth(0.5)
    c.line(1.0 * inch, y, 7.5 * inch, y)
    y -= 0.28 * inch
    c.drawString(1.0 * inch, y, "Participant Information")
    y -= 0.28 * inch
    c.setFont("Helvetica", 10)
    full_name = " ".join(
        p for p in [heir.legal_first_name, heir.legal_middle_name, heir.legal_last_name] if p
    ) or heir.username
    c.drawString(1.0 * inch, y, f"Legal Name: {full_name}")
    y -= 0.20 * inch
    if heir.email:
        c.drawString(1.0 * inch, y, f"Email: {heir.email}")
        y -= 0.20 * inch
    c.drawString(1.0 * inch, y, f"Participant ID: {heir.id}")
    y -= 0.35 * inch

    # Waiver declaration
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(SLATE_900)
    c.line(1.0 * inch, y, 7.5 * inch, y)
    y -= 0.28 * inch
    c.drawString(1.0 * inch, y, "Waiver Declaration")
    y -= 0.30 * inch
    c.setFont("Times-Roman", 11)
    c.setFillColor(SLATE_900)

    waiver_text = (
        f'I, {full_name}, hereby voluntarily abstain from all asset distribution '
        f'proceedings for session "{session.title or session.id}". '
        f'I understand that this waiver is binding and irrevocable under the '
        f'Electronic Signatures in Global and National Commerce Act (E-SIGN, 15 U.S.C. § 7001) '
        f'and the Uniform Electronic Transactions Act (UETA). I acknowledge that by '
        f'providing my legal name signature below, I am signing this waiver electronically '
        f'with the same legal effect as a handwritten signature.'
    )
    waiver_lines = _wrap_text(waiver_text, c, 6.5 * inch)
    for line in waiver_lines:
        c.drawString(1.0 * inch, y, line)
        y -= 0.18 * inch

    y -= 0.15 * inch

    # Digital signature block
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(SLATE_900)
    c.line(1.0 * inch, y, 7.5 * inch, y)
    y -= 0.28 * inch
    c.drawString(1.0 * inch, y, "Digital Signature")
    y -= 0.28 * inch
    c.setFont("Helvetica", 10)
    c.drawString(1.0 * inch, y, f"Signed: {legal_name_signature}")
    y -= 0.22 * inch
    timestamp_str = timestamp_utc.strftime("%B %d, %Y at %H:%M UTC")
    c.drawString(1.0 * inch, y, f"Date: {timestamp_str}")
    y -= 0.22 * inch
    c.drawString(1.0 * inch, y, f"IP Address: {ip_address}")
    y -= 0.35 * inch

    # E-SIGN disclosure
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(SLATE_900)
    c.line(1.0 * inch, y, 7.5 * inch, y)
    y -= 0.28 * inch
    c.drawString(1.0 * inch, y, "E-SIGN / UETA Disclosure")
    y -= 0.30 * inch
    c.setFont("Helvetica", 9)
    c.setFillColor(MUTED_SLATE)

    disclosure_text = (
        "This document serves as your official receipt confirming that you have "
        "electronically signed an abstention waiver under the Electronic Signatures "
        "in Global and National Commerce Act (E-SIGN, 15 U.S.C. § 7001 et seq.) and "
        "the Uniform Electronic Transactions Act (UETA). Your electronic signature "
        "carries the same legal weight and enforceability as a handwritten signature "
        "on paper. Retain this PDF for your records. If you believe this abstention "
        "was recorded in error, contact the Executor immediately via the Help/Support "
        "system."
    )
    disclosure_lines = _wrap_text(disclosure_text, c, 6.5 * inch)
    for line in disclosure_lines:
        c.drawString(1.0 * inch, y, line)
        y -= 0.16 * inch

    y -= 0.25 * inch

    # Hash seal
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(SLATE_900)
    c.line(1.0 * inch, y, 7.5 * inch, y)
    y -= 0.28 * inch
    c.drawString(1.0 * inch, y, "Tamper-Proof Audit Seal")
    y -= 0.28 * inch
    c.setFont("Courier", 7)
    c.setFillColor(MUTED_SLATE)
    c.drawString(1.0 * inch, y, f"SHA-256: {sha256_hash}")
    y -= 0.40 * inch

    # Legal disclaimer at bottom
    c.setFont("Helvetica-Oblique", 8)
    c.setFillColor(MUTED_SLATE)
    disc_lines = _wrap_text(LEGAL_DISCLAIMER, c, 6.5 * inch)
    for line in disc_lines:
        c.drawString(1.0 * inch, y, line)
        y -= 0.14 * inch

    c.showPage()
    c.save()

    buf.seek(0)
    return buf
