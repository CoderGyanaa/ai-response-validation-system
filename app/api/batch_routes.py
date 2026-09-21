"""
Batch Evaluation Module API (M3.4) — kept in its own router, separate
from app/api/routes.py, per the requirement that batch processing stay
separate from the existing single-evaluation endpoint.

Streams newline-delimited JSON (NDJSON) so the frontend can show real,
incremental progress as each row is actually evaluated, rather than
faking a progress bar while waiting for one big response.
"""
import json
import logging

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse

from app.evaluation.csv_parser import parse_batch_csv
from app.evaluation.batch_service import BatchEvaluationService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/evaluate/batch")
async def evaluate_batch(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a .csv file.")

    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    valid_rows, invalid_rows, header_error = parse_batch_csv(raw_bytes)
    if header_error:
        raise HTTPException(status_code=400, detail=header_error)

    total_records = len(valid_rows) + len(invalid_rows)
    service = BatchEvaluationService()

    def stream():
        yield json.dumps({
            "type": "init",
            "total_records": total_records,
            "valid_records": len(valid_rows),
            "invalid_records": len(invalid_rows),
            "invalid_rows": [r.model_dump() for r in invalid_rows],
        }) + "\n"

        completed = 0
        records = []
        for record in service.evaluate_rows(valid_rows):
            completed += 1
            records.append(record)
            yield json.dumps({
                "type": "progress",
                "completed": completed,
                "total": len(valid_rows),
                "record": record.model_dump(),
            }) + "\n"

        summary = service.compute_summary(records, total_records, len(invalid_rows))
        yield json.dumps({"type": "summary", "summary": summary.model_dump()}) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")
