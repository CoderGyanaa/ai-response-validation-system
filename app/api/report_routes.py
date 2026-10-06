"""
Evaluation Report Export API (M4.2).

Kept in its own router, consistent with the pattern used for the batch and
dashboard endpoints. Generates the PDF on-demand from ResultsStore data —
nothing is pre-rendered or cached, so the report always reflects the current
state of the stored evaluation records.
"""
import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.services.results_store import ResultsStore
from app.services.report_generator import generate_batch_report_pdf

router = APIRouter()
results_store = ResultsStore()


@router.get("/reports/batch/{batch_id}/pdf")
def export_batch_report(batch_id: str):
    records = results_store.list_records(batch_id=batch_id, limit=1)
    if not records:
        raise HTTPException(status_code=404, detail="No evaluation records found for this batch ID.")

    pdf_bytes = generate_batch_report_pdf(batch_id, results_store)
    filename = f"evaluation-report-{batch_id[:8]}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
