from __future__ import annotations

import os
from io import BytesIO

from flask import current_app, make_response

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import (
        Image,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
except Exception:  # pragma: no cover - dependency may be installed later
    colors = None
    A4 = None
    ParagraphStyle = None
    getSampleStyleSheet = None
    inch = None
    ImageReader = None
    Image = None
    Paragraph = None
    SimpleDocTemplate = None
    Spacer = None
    Table = None
    TableStyle = None

try:
    from pypdf import PdfWriter
except Exception:  # pragma: no cover - dependency may be installed later
    PdfWriter = None


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
PDF_EXTENSION = ".pdf"


def _styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="SectionHeading",
            parent=styles["Heading3"],
            textColor=colors.HexColor("#1f6fff"),
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="MutedText",
            parent=styles["BodyText"],
            textColor=colors.HexColor("#5d6f91"),
            fontSize=10,
        )
    )
    return styles


def _kv_table(rows):
    table = Table(rows, colWidths=[1.85 * inch, 4.95 * inch], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef5ff")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#1f2d4d")),
                ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#d8e4f7")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8e4f7")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def _format_amount(value) -> str:
    return f"{float(value or 0):.2f}"


def _format_date(value) -> str:
    if not value:
        return "-"
    return value.strftime("%d %b %Y")


def _safe_user_label(user) -> str:
    if not user:
        return "-"
    return user.display_name or user.email or "-"


def _safe_company_code(company) -> str:
    if not company or not getattr(company, "code", None):
        return "ATIKES"
    return company.code.replace(" ", "-").upper()


def _company_address_html(company) -> str:
    if not company or not getattr(company, "address", None):
        return "-"
    return "<br/>".join(company.address.splitlines())


def _attachment_absolute_path(relative_path: str) -> str:
    return os.path.join(current_app.static_folder, relative_path)


def _collect_attachment_pdf_paths(attachments):
    pdf_paths = []
    for attachment in attachments or []:
        extension = os.path.splitext(attachment.file_path or "")[1].lower()
        absolute_path = _attachment_absolute_path(attachment.file_path)
        if extension == PDF_EXTENSION and os.path.exists(absolute_path):
            pdf_paths.append(absolute_path)
    return pdf_paths


def _merge_summary_with_attachment_pdfs(summary_pdf_data: bytes, attachment_pdf_paths):
    if not attachment_pdf_paths or not PdfWriter:
        return summary_pdf_data

    merged_pdf = BytesIO()
    writer = PdfWriter()
    writer.append(BytesIO(summary_pdf_data))

    for pdf_path in attachment_pdf_paths:
        try:
            writer.append(pdf_path)
        except Exception:
            continue

    writer.write(merged_pdf)
    return merged_pdf.getvalue()


def _append_attachment_previews(story, reimbursement, styles):
    story.append(Paragraph("Attachments", styles["SectionHeading"]))
    if not reimbursement.attachments:
        story.append(Paragraph("No attachments uploaded.", styles["BodyText"]))
        return

    for attachment in reimbursement.attachments:
        story.append(Paragraph(attachment.file_name, styles["BodyText"]))
        extension = os.path.splitext(attachment.file_path or "")[1].lower()
        absolute_path = _attachment_absolute_path(attachment.file_path)

        if extension in IMAGE_EXTENSIONS and os.path.exists(absolute_path):
            try:
                image_reader = ImageReader(absolute_path)
                image_width, image_height = image_reader.getSize()
                max_width = 6.7 * inch
                max_height = 5.8 * inch
                scale = min(max_width / image_width, max_height / image_height, 1)
                preview = Image(
                    absolute_path,
                    width=image_width * scale,
                    height=image_height * scale,
                )
                preview.hAlign = "LEFT"
                story.append(Spacer(1, 4))
                story.append(preview)
            except Exception:
                story.append(Paragraph("Preview unavailable for this attachment.", styles["MutedText"]))
        elif extension == PDF_EXTENSION:
            story.append(Paragraph("Attached PDF will be appended after this summary.", styles["MutedText"]))
        else:
            story.append(Paragraph("Preview unavailable in PDF for this file type.", styles["MutedText"]))

        story.append(Spacer(1, 12))


def render_reimbursement_pdf(request_obj, viewer_role: str):
    if not SimpleDocTemplate:
        response = make_response(
            "PDF generation is not available yet. Please install the updated requirements and restart the server."
        )
        response.status_code = 503
        response.headers["Content-Type"] = "text/plain; charset=utf-8"
        return response

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    styles = _styles()
    story = []

    company = getattr(request_obj, "company", None)

    story.append(Paragraph(company.legal_name if company else "ATIKES", styles["Title"]))
    story.append(Paragraph("Reimbursement Summary", styles["Heading2"]))
    story.append(
        Paragraph(
            f"{request_obj.request_no} | Generated for {viewer_role.replace('_', ' ').title()}",
            styles["MutedText"],
        )
    )
    story.append(Spacer(1, 10))
    story.append(
        _kv_table(
            [
                ["Company", company.legal_name if company else "-"],
                ["GST", company.gst_number if company else "-"],
                ["Address", Paragraph(_company_address_html(company), styles["BodyText"])],
            ]
        )
    )
    story.append(Spacer(1, 16))

    summary_rows = [
        ["Company Code", _safe_company_code(company)],
        ["Employee", f"{request_obj.employee.first_name} {request_obj.employee.last_name}"],
        ["Employee Code", request_obj.employee.emp_code],
        ["Type", request_obj.reimbursement_type.name if request_obj.reimbursement_type else "-"],
        ["Bill Date", _format_date(request_obj.bill_date)],
        ["Payment Date", _format_date(request_obj.payment_date)],
        ["Requested Amount", _format_amount(request_obj.requested_amount)],
        ["Manager Approved Amount", _format_amount(request_obj.manager_approved_amount)],
        ["Finance Approved Amount", _format_amount(request_obj.finance_approved_amount)],
        ["Final Amount", _format_amount(request_obj.final_amount)],
        ["Status", request_obj.status.replace("_", " ").title()],
        ["Description", request_obj.description or "-"],
    ]
    story.append(_kv_table(summary_rows))
    story.append(Spacer(1, 14))

    story.append(Paragraph("Manager Decision", styles["SectionHeading"]))
    story.append(
        _kv_table(
            [
                ["Approver", _safe_user_label(request_obj.manager_approver)],
                ["Comments", request_obj.manager_comments or "-"],
            ]
        )
    )
    story.append(Spacer(1, 14))

    story.append(Paragraph("Payment Details", styles["SectionHeading"]))
    story.append(
        _kv_table(
            [
                ["Payment Date", _format_date(request_obj.payment_date)],
                ["Payment Reference", request_obj.payment_reference or "-"],
            ]
        )
    )
    story.append(Spacer(1, 14))

    story.append(Paragraph("Finance Decision", styles["SectionHeading"]))
    story.append(
        _kv_table(
            [
                ["Approver", _safe_user_label(request_obj.finance_approver)],
                ["Comments", request_obj.finance_comments or "-"],
            ]
        )
    )
    story.append(Spacer(1, 14))

    _append_attachment_previews(story, request_obj, styles)
    attachment_pdf_paths = _collect_attachment_pdf_paths(request_obj.attachments)

    doc.build(story)
    pdf_data = buffer.getvalue()
    buffer.close()
    pdf_data = _merge_summary_with_attachment_pdfs(pdf_data, attachment_pdf_paths)

    response = make_response(pdf_data)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = (
        f"attachment; filename={_safe_company_code(company).lower()}-{request_obj.request_no.lower()}-summary.pdf"
    )
    return response
