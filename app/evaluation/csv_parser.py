"""
Parses and validates a batch evaluation CSV.

Supported columns: question, ai_response (required), reference_answer,
source_document (optional). Column matching is case-insensitive and
whitespace-tolerant. A row missing a required field is reported as
invalid rather than aborting the whole file; a missing required COLUMN
in the header is a file-level error since no row could ever be evaluated.
"""
import csv
import io

from app.models.schemas import EvaluationRequest
from app.models.batch_schemas import BatchRowError

REQUIRED_COLUMNS = {"question", "ai_response"}


def parse_batch_csv(raw_bytes: bytes) -> tuple[list[tuple[int, EvaluationRequest]], list[BatchRowError], str | None]:
    """
    Returns (valid_rows, invalid_rows, header_error).

    valid_rows: list of (row_number, EvaluationRequest); row_number is
        1-indexed against the data rows (excluding the header).
    invalid_rows: rows that failed validation but didn't invalidate the file.
    header_error: set when the file itself can't be used at all (bad
        encoding, unparseable, or missing a required column) — in this
        case valid_rows/invalid_rows are both empty and the caller should
        reject the whole upload.
    """
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], [], "File is not valid UTF-8 text. Please upload a plain CSV file."

    try:
        reader = csv.DictReader(io.StringIO(text))
    except Exception as exc:
        return [], [], f"Could not parse file as CSV: {exc}"

    if reader.fieldnames is None:
        return [], [], "CSV file has no header row."

    field_map = {h.strip().lower(): h for h in reader.fieldnames if h}
    missing_required = REQUIRED_COLUMNS - set(field_map.keys())
    if missing_required:
        return [], [], f"Missing required column(s): {', '.join(sorted(missing_required))}"

    def get(raw_row: dict, col: str) -> str:
        key = field_map.get(col)
        if key is None:
            return ""
        val = raw_row.get(key)
        return val.strip() if isinstance(val, str) else ""

    valid_rows: list[tuple[int, EvaluationRequest]] = []
    invalid_rows: list[BatchRowError] = []

    for i, raw_row in enumerate(reader, start=1):
        # A fully blank line (e.g. a trailing newline) isn't a real record — skip silently.
        if not any((v or "").strip() if isinstance(v, str) else False for v in raw_row.values()):
            continue

        question = get(raw_row, "question")
        ai_response = get(raw_row, "ai_response")
        reference_answer = get(raw_row, "reference_answer") or None
        source_document = get(raw_row, "source_document") or None

        missing_fields = []
        if not question:
            missing_fields.append("question")
        if not ai_response:
            missing_fields.append("ai_response")

        if missing_fields:
            invalid_rows.append(BatchRowError(
                row_number=i,
                reason=f"Missing required field(s): {', '.join(missing_fields)}",
            ))
            continue

        try:
            request = EvaluationRequest(
                question=question,
                ai_response=ai_response,
                reference_answer=reference_answer,
                source_document=source_document,
            )
        except Exception as exc:
            invalid_rows.append(BatchRowError(row_number=i, reason=f"Invalid row: {exc}"))
            continue

        valid_rows.append((i, request))

    return valid_rows, invalid_rows, None
