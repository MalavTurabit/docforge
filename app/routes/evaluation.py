"""
app/routes/evaluation.py

POST /evaluation/report  — generate a PDF report from RAGAS evaluation results
"""

import io
from datetime import datetime
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/evaluation", tags=["Evaluation"])


class EvalPairResult(BaseModel):
    question:     str
    ground_truth: str
    answer:       str
    scores:       Optional[dict] = None
    status:       str = "ok"


class EvalReportRequest(BaseModel):
    results:    list[EvalPairResult]
    generated_at: Optional[str] = None


@router.post("/report")
def generate_report(req: EvalReportRequest):
    """
    Generate a downloadable PDF evaluation report from RAGAS results.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        HRFlowable, PageBreak,
    )
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    buffer = io.BytesIO()
    doc    = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm,
        topMargin=2*cm,   bottomMargin=2*cm,
    )

    styles = getSampleStyleSheet()
    W = A4[0] - 4*cm   # usable width

    # ── Custom styles ─────────────────────────────────────────
    title_style = ParagraphStyle(
        "ReportTitle",
        parent    = styles["Title"],
        fontSize  = 20,
        textColor = colors.HexColor("#1a1a2e"),
        spaceAfter= 4,
        alignment = TA_CENTER,
    )
    subtitle_style = ParagraphStyle(
        "Subtitle",
        parent    = styles["Normal"],
        fontSize  = 10,
        textColor = colors.HexColor("#666666"),
        alignment = TA_CENTER,
        spaceAfter= 16,
    )
    section_style = ParagraphStyle(
        "Section",
        parent    = styles["Heading2"],
        fontSize  = 13,
        textColor = colors.HexColor("#1a1a2e"),
        spaceBefore=12,
        spaceAfter= 6,
    )
    label_style = ParagraphStyle(
        "Label",
        parent    = styles["Normal"],
        fontSize  = 8,
        textColor = colors.HexColor("#888888"),
        spaceAfter= 1,
    )
    body_style = ParagraphStyle(
        "Body",
        parent    = styles["Normal"],
        fontSize  = 9,
        textColor = colors.HexColor("#333333"),
        spaceAfter= 6,
        leading   = 13,
    )
    small_style = ParagraphStyle(
        "Small",
        parent    = styles["Normal"],
        fontSize  = 8,
        textColor = colors.HexColor("#555555"),
        leading   = 11,
    )

    # ── Helpers ───────────────────────────────────────────────
    def _score_label(v):
        if v is None: return "N/A"
        return f"{v:.3f}"

    def _score_color(v):
        if v is None: return colors.HexColor("#cccccc")
        if v >= 0.8:  return colors.HexColor("#22c55e")
        if v >= 0.6:  return colors.HexColor("#f59e0b")
        return colors.HexColor("#ef4444")

    def _avg(key):
        vals = [
            r.scores.get(key) for r in req.results
            if r.scores and r.scores.get(key) is not None
        ]
        return round(sum(vals)/len(vals), 3) if vals else None

    # ── Build story ───────────────────────────────────────────
    story = []
    generated_at = req.generated_at or datetime.now().strftime("%B %d, %Y at %H:%M")

    # Title
    story.append(Paragraph("CiteRAG Evaluation Report", title_style))
    story.append(Paragraph(
        f"Generated on {generated_at}  ·  {len(req.results)} question pairs evaluated",
        subtitle_style,
    ))
    story.append(HRFlowable(width=W, thickness=1, color=colors.HexColor("#e5e7eb")))
    story.append(Spacer(1, 12))

    # ── Aggregate scores table ────────────────────────────────
    story.append(Paragraph("Aggregate RAGAS Scores", section_style))

    metrics = [
        ("Faithfulness",      "faithfulness"),
        ("Answer Relevancy",  "answer_relevancy"),
        ("Context Precision", "context_precision"),
        ("Context Recall",    "context_recall"),
    ]

    agg_data = [["Metric", "Score", "Rating"]]
    for name, key in metrics:
        val = _avg(key)
        rating = "Excellent" if val and val >= 0.8 else \
                 "Good"      if val and val >= 0.6 else \
                 "Needs Work" if val else "N/A"
        agg_data.append([name, _score_label(val), rating])

    agg_table = Table(agg_data, colWidths=[W*0.5, W*0.25, W*0.25])
    agg_table.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0),  colors.HexColor("#1a1a2e")),
        ("TEXTCOLOR",    (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",     (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, 0),  10),
        ("FONTSIZE",     (0, 1), (-1, -1), 10),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f9fafb"), colors.white]),
        ("GRID",         (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("ALIGN",        (1, 0), (-1, -1), "CENTER"),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",   (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 8),
        ("LEFTPADDING",  (0, 0), (-1, -1), 10),
    ]))

    # Colour score cells
    for row_idx, (_, key) in enumerate(metrics, 1):
        val = _avg(key)
        agg_table.setStyle(TableStyle([
            ("TEXTCOLOR", (1, row_idx), (1, row_idx), _score_color(val)),
            ("FONTNAME",  (1, row_idx), (1, row_idx), "Helvetica-Bold"),
        ]))

    story.append(agg_table)
    story.append(Spacer(1, 20))

    # ── Per-question results ──────────────────────────────────
    story.append(HRFlowable(width=W, thickness=1, color=colors.HexColor("#e5e7eb")))
    story.append(Paragraph("Per-Question Results", section_style))

    for i, r in enumerate(req.results):
        scores = r.scores or {}

        # Question header
        story.append(Paragraph(
            f"Q{i+1}",
            ParagraphStyle("QNum", parent=styles["Normal"],
                           fontSize=9, textColor=colors.HexColor("#6366f1"),
                           fontName="Helvetica-Bold", spaceAfter=2)
        ))
        story.append(Paragraph(r.question, ParagraphStyle(
            "QText", parent=styles["Normal"],
            fontSize=10, textColor=colors.HexColor("#1a1a2e"),
            fontName="Helvetica-Bold", spaceAfter=4,
        )))

        # Scores row
        score_data = [["Faithfulness", "Answer Relevancy", "Context Precision", "Context Recall"]]
        score_vals = [
            _score_label(scores.get("faithfulness")),
            _score_label(scores.get("answer_relevancy")),
            _score_label(scores.get("context_precision")),
            _score_label(scores.get("context_recall")),
        ]
        score_data.append(score_vals)

        score_table = Table(score_data, colWidths=[W/4]*4)
        score_style = [
            ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#f3f4f6")),
            ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 8),
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("GRID",          (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("FONTNAME",      (0, 1), (-1, 1),  "Helvetica-Bold"),
        ]
        # Colour score values
        metric_keys = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
        for col_idx, key in enumerate(metric_keys):
            val = scores.get(key)
            score_style.append(("TEXTCOLOR", (col_idx, 1), (col_idx, 1), _score_color(val)))
        score_table.setStyle(TableStyle(score_style))
        story.append(score_table)
        story.append(Spacer(1, 6))

        # Ground truth + answer
        story.append(Paragraph("Ground Truth:", label_style))
        story.append(Paragraph(r.ground_truth[:400] + ("…" if len(r.ground_truth) > 400 else ""), small_style))
        story.append(Spacer(1, 4))
        story.append(Paragraph("Generated Answer:", label_style))
        story.append(Paragraph(r.answer[:400] + ("…" if len(r.answer) > 400 else ""), small_style))
        story.append(Spacer(1, 12))

        if r.status == "error":
            story.append(Paragraph("⚠ Evaluation failed for this pair.", ParagraphStyle(
                "Err", parent=styles["Normal"],
                fontSize=8, textColor=colors.HexColor("#ef4444"),
            )))

        # Divider between questions (not after last)
        if i < len(req.results) - 1:
            story.append(HRFlowable(width=W, thickness=0.5, color=colors.HexColor("#e5e7eb")))
            story.append(Spacer(1, 8))

    # Build PDF
    doc.build(story)
    buffer.seek(0)

    filename = f"citerag_eval_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )