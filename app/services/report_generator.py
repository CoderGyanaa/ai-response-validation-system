"""
Evaluation Report Export (M4.2).

Generates a structured PDF summarizing a batch evaluation run. Reads
exclusively from ResultsStore — the same persisted data the M4.1 dashboard
reads from — so the PDF and the dashboard are always consistent with each
other and with the underlying evaluation records.

Uses reportlab's Platypus API (flowables: Paragraph, Table, Spacer) rather
than manual canvas coordinates, so long reasoning text, evidence, and claims
wrap and paginate automatically instead of overlapping or getting cut off.
"""
import io
from datetime import datetime, timezone
from xml.sax.saxutils import escape as _escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, HRFlowable, ListFlowable, ListItem,
)

from app.services.results_store import ResultsStore

VERDICT_HEX = {"PASS": "#1E8A5F", "PARTIAL": "#B8860B", "FAIL": "#B23A2E"}


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", fontSize=22, leading=26, spaceAfter=6, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="ReportSubtitle", fontSize=11, leading=14, textColor=colors.HexColor("#555555")))
    styles.add(ParagraphStyle(name="SectionHeading", fontSize=15, leading=18, spaceBefore=18, spaceAfter=8, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="SubHeading", fontSize=12.5, leading=15, spaceBefore=10, spaceAfter=4, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="Body", fontSize=9.5, leading=13))
    styles.add(ParagraphStyle(name="BodySmall", fontSize=8.5, leading=12, textColor=colors.HexColor("#444444")))
    styles.add(ParagraphStyle(name="Label", fontSize=8, leading=10, textColor=colors.HexColor("#777777"), fontName="Helvetica-Bold"))
    return styles


def _verdict_chip_html(verdict_label: str, verdict: str) -> str:
    hex_color = VERDICT_HEX.get(verdict, "#666666")
    return f'<font color="{hex_color}"><b>{verdict_label}</b></font>'


def _e(text) -> str:
    """Escape user/LLM-generated text before embedding it in reportlab's XML-subset markup."""
    if text is None:
        return "—"
    return _escape(str(text))


def _record_section(record: dict, styles) -> list:
    full = record["full_result"]
    flow = []

    flow.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#DDDDDD"), spaceBefore=10, spaceAfter=10))

    header = "Record"
    if record.get("row_number") is not None:
        header += f" #{record['row_number']}"
    flow.append(Paragraph(header, styles["SubHeading"]))

    flow.append(Paragraph("<b>Question:</b> " + _e(full["question"]), styles["Body"]))
    flow.append(Paragraph("<b>AI response:</b> " + _e(full["ai_response"]), styles["Body"]))
    flow.append(Spacer(1, 6))

    # Per-dimension score table
    rel, acc, hal, comp = full["relevance"], full["accuracy"], full["hallucination"], full["completeness"]
    score_table_data = [
        ["Dimension", "Score", "Category / Status"],
        ["Relevance", f"{rel['score']:.2f}", _e(rel.get("category")) if rel.get("category") else "—"],
        ["Accuracy", f"{acc['score']:.2f}", _e(acc.get("category")) if acc.get("category") else "—"],
        ["Hallucination", f"{hal['score']:.2f}", _e(hal.get("hallucination_status", "—"))],
        ["Completeness", f"{comp['score']:.2f}", _e(comp.get("category")) if comp.get("category") else "—"],
    ]
    t = Table(score_table_data, colWidths=[1.6 * inch, 0.9 * inch, 2.5 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFEFEF")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    flow.append(t)
    flow.append(Spacer(1, 6))

    verdict_html = _verdict_chip_html(_e(full.get("verdict_label", full["verdict"])), full["verdict"])
    flow.append(Paragraph(f"<b>Overall score:</b> {full['overall_score']:.2f} — <b>Verdict:</b> {verdict_html}", styles["Body"]))
    flow.append(Spacer(1, 4))

    # Reasoning per dimension
    flow.append(Paragraph("<b>Relevance reasoning:</b> " + _e(rel.get("reason")), styles["BodySmall"]))
    flow.append(Paragraph("<b>Accuracy reasoning:</b> " + _e(acc.get("reason")), styles["BodySmall"]))
    if acc.get("evidence"):
        flow.append(Paragraph("<b>Accuracy evidence:</b>", styles["BodySmall"]))
        flow.append(ListFlowable(
            [ListItem(Paragraph(_e(e), styles["BodySmall"])) for e in acc["evidence"]],
            bulletType="bullet", leftIndent=14,
        ))

    flow.append(Paragraph(f"<b>Hallucination reasoning:</b> {_e(hal.get('reason'))}", styles["BodySmall"]))
    claim_evidence = hal.get("claim_evidence") or []
    if claim_evidence:
        flow.append(Paragraph("<b>Flagged claims:</b>", styles["BodySmall"]))
        for c in claim_evidence:
            flow.append(Paragraph(f"&bull; <b>Claim:</b> \u201c{_e(c['claim'])}\u201d", styles["BodySmall"]))
            if c.get("evidence"):
                flow.append(Paragraph("&nbsp;&nbsp;<b>Evidence:</b> " + _e("; ".join(c["evidence"])), styles["BodySmall"]))
            flow.append(Paragraph("&nbsp;&nbsp;<b>Reason:</b> " + _e(c.get("reason")), styles["BodySmall"]))
    else:
        flow.append(Paragraph("No unsupported claims detected.", styles["BodySmall"]))

    flow.append(Paragraph(f"<b>Completeness reasoning:</b> {_e(comp.get('reason'))}", styles["BodySmall"]))
    if comp.get("addressed_aspects"):
        flow.append(Paragraph("<b>Addressed aspects:</b> " + _e("; ".join(comp["addressed_aspects"])), styles["BodySmall"]))
    if comp.get("missing_aspects"):
        flow.append(Paragraph(
            '<font color="#B8860B"><b>Missing aspects:</b> ' + _e("; ".join(comp["missing_aspects"])) + "</font>",
            styles["BodySmall"],
        ))

    if full.get("consolidated_summary"):
        flow.append(Spacer(1, 4))
        flow.append(Paragraph("<b>Consolidated summary:</b> " + _e(full["consolidated_summary"]), styles["BodySmall"]))

    return flow


def _recommendations_from_top_issues(top_issues: list[dict], total: int) -> list[str]:
    """Turns the same top_issues data the dashboard shows into plain-language recommendations."""
    messages = {
        "Low accuracy": "Verify factual claims against reliable reference material before responding.",
        "Low relevance": "Ensure responses directly address every part of the question asked.",
        "Hallucinated claims": "Cross-check claims against retrieved evidence before including them in a response.",
        "Incomplete response": "Review the full scope of each question to avoid omitting requested information.",
    }
    recs = []
    for issue in top_issues:
        pct = round(100 * issue["count"] / total, 1) if total else 0
        note = messages.get(issue["issue"], "Review responses affected by this issue.")
        recs.append(f"{issue['issue']} occurred in {issue['count']} of {total} responses ({pct}%). {note}")
    return recs


def generate_batch_report_pdf(batch_id: str, store: ResultsStore) -> bytes:
    """Builds the full PDF report for a batch and returns it as bytes."""
    records = store.list_records(batch_id=batch_id, limit=100000)
    records.sort(key=lambda r: (r.get("row_number") is None, r.get("row_number") or 0))
    stats = store.compute_stats(batch_id=batch_id)

    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch, topMargin=0.75 * inch, bottomMargin=0.75 * inch,
    )
    story = []

    # ---- Title / metadata ----
    story.append(Paragraph("AI Response Validation System", styles["ReportSubtitle"]))
    story.append(Paragraph("Batch Evaluation Report", styles["ReportTitle"]))
    story.append(Paragraph(f"Batch ID: {batch_id}", styles["Body"]))
    story.append(Paragraph(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", styles["Body"]))
    story.append(Paragraph(f"Records included: {len(records)}", styles["Body"]))

    # ---- Batch summary ----
    story.append(Paragraph("Batch Summary", styles["SectionHeading"]))
    summary_data = [
        ["Metric", "Value"],
        ["Total records evaluated", str(stats["total_records"])],
        ["Pass", f"{stats['pass_count']} ({stats['pass_pct']}%)"],
        ["Needs Improvement", f"{stats['needs_improvement_count']} ({stats['needs_improvement_pct']}%)"],
        ["Fail", f"{stats['fail_count']} ({stats['fail_pct']}%)"],
        ["Average Relevance", f"{stats['average_relevance']:.2f}"],
        ["Average Accuracy", f"{stats['average_accuracy']:.2f}"],
        ["Average Hallucination", f"{stats['average_hallucination']:.2f}"],
        ["Average Completeness", f"{stats['average_completeness']:.2f}"],
        ["Average Overall Score", f"{stats['average_overall']:.2f}"],
        ["Hallucination frequency", f"{stats['hallucination_frequency'] * 100:.1f}%"],
        ["Incomplete-response frequency", f"{stats['missing_aspects_frequency'] * 100:.1f}%"],
    ]
    summary_table = Table(summary_data, colWidths=[2.8 * inch, 2.2 * inch])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#222222")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F7F7")]),
    ]))
    story.append(summary_table)

    # ---- Recommendations ----
    story.append(Paragraph("Improvement Recommendations", styles["SectionHeading"]))
    recommendations = _recommendations_from_top_issues(stats["top_issues"], stats["total_records"])
    if recommendations:
        story.append(ListFlowable(
            [ListItem(Paragraph(r, styles["Body"])) for r in recommendations],
            bulletType="bullet", leftIndent=14,
        ))
    else:
        story.append(Paragraph("No recurring issues were identified across this batch.", styles["Body"]))

    # ---- Per-response detail ----
    if records:
        story.append(PageBreak())
        story.append(Paragraph("Individual Evaluation Results", styles["SectionHeading"]))
        for record in records:
            story.extend(_record_section(record, styles))

    doc.build(story)
    return buffer.getvalue()
