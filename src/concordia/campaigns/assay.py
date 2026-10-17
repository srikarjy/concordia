"""Strict, provenance-preserving CSV import for campaign assay results."""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass

from concordia.campaigns.schema import AssayStatus
from concordia.campaigns.service import RecordMeasurementRequest

MAX_ASSAY_CSV_BYTES = 2_000_000
MAX_ASSAY_ROWS = 100_000
REQUIRED_COLUMNS = frozenset(
    {"candidate_id", "metric", "value", "unit", "method", "status", "replicate"}
)
OPTIONAL_COLUMNS = frozenset({"source_artifact_digest"})


@dataclass(frozen=True)
class AssayImportError:
    row: int | None
    field: str | None
    message: str


@dataclass(frozen=True)
class AssayImportReport:
    rows: tuple[RecordMeasurementRequest, ...]
    errors: tuple[AssayImportError, ...]

    @property
    def accepted_count(self) -> int:
        return len(self.rows)

    @property
    def valid(self) -> bool:
        return not self.errors


def parse_assay_csv(csv_text: str) -> AssayImportReport:
    """Parse an assay file without silently coercing failed or censored results.

    Parsing is intentionally independent of persistence. Callers can inspect the
    report and only write rows when ``valid`` is true, keeping partial imports out
    of a campaign round.
    """

    if not isinstance(csv_text, str):
        return AssayImportReport((), (AssayImportError(None, None, "CSV body must be text"),))
    if len(csv_text.encode("utf-8")) > MAX_ASSAY_CSV_BYTES:
        return AssayImportReport(
            (), (AssayImportError(None, None, "CSV body exceeds the 2 MB limit"),)
        )

    reader = csv.DictReader(io.StringIO(csv_text, newline=""))
    if reader.fieldnames is None:
        return AssayImportReport((), (AssayImportError(1, None, "CSV header is required"),))
    fields = {field.strip() for field in reader.fieldnames if field is not None}
    missing = sorted(REQUIRED_COLUMNS - fields)
    unknown = sorted(fields - REQUIRED_COLUMNS - OPTIONAL_COLUMNS)
    errors: list[AssayImportError] = []
    if missing:
        errors.append(AssayImportError(1, None, f"missing required columns: {', '.join(missing)}"))
    if unknown:
        errors.append(AssayImportError(1, None, f"unknown columns: {', '.join(unknown)}"))
    if errors:
        return AssayImportReport((), tuple(errors))

    rows: list[RecordMeasurementRequest] = []
    seen: set[tuple[str, str, int]] = set()
    for row_number, raw in enumerate(reader, start=2):
        if row_number - 1 > MAX_ASSAY_ROWS:
            errors.append(AssayImportError(row_number, None, "CSV exceeds the 100,000 row limit"))
            break
        row = {str(key).strip(): (value or "").strip() for key, value in raw.items() if key}
        candidate_id = row.get("candidate_id", "")
        metric = row.get("metric", "")
        method = row.get("method", "")
        if not candidate_id:
            errors.append(AssayImportError(row_number, "candidate_id", "candidate_id is required"))
        if not metric:
            errors.append(AssayImportError(row_number, "metric", "metric is required"))
        if not method:
            errors.append(AssayImportError(row_number, "method", "method is required"))

        status_text = row.get("status", "").lower()
        try:
            status = AssayStatus(status_text)
        except ValueError:
            errors.append(AssayImportError(row_number, "status", "unknown assay status"))
            status = None

        replicate_text = row.get("replicate", "")
        try:
            replicate = int(replicate_text)
            if replicate < 1:
                raise ValueError
        except ValueError:
            errors.append(
                AssayImportError(row_number, "replicate", "replicate must be a positive integer")
            )
            replicate = 1

        value_text = row.get("value", "")
        value: float | None = None
        if value_text:
            try:
                value = float(value_text)
                if not math.isfinite(value):
                    raise ValueError
            except ValueError:
                errors.append(
                    AssayImportError(row_number, "value", "value must be a finite number")
                )
        if (
            status
            in {
                AssayStatus.MEASURED,
                AssayStatus.BELOW_DETECTION,
                AssayStatus.ABOVE_DETECTION,
            }
            and value is None
        ):
            errors.append(
                AssayImportError(row_number, "value", f"value is required for {status.value}")
            )
        key = (candidate_id, metric, replicate)
        if key in seen:
            errors.append(
                AssayImportError(row_number, None, "duplicate candidate/metric/replicate")
            )
        seen.add(key)
        if (
            status is None
            or not candidate_id
            or not metric
            or not method
            or (
                status
                in {
                    AssayStatus.MEASURED,
                    AssayStatus.BELOW_DETECTION,
                    AssayStatus.ABOVE_DETECTION,
                }
                and value is None
            )
        ):
            continue
        rows.append(
            RecordMeasurementRequest(
                candidate_id=candidate_id,
                metric=metric,
                value=value,
                unit=row.get("unit") or None,
                method=method,
                status=status,
                replicate=replicate,
                source_artifact_digest=row.get("source_artifact_digest") or None,
            )
        )
    return AssayImportReport(tuple(rows), tuple(errors))


__all__ = ["AssayImportError", "AssayImportReport", "parse_assay_csv"]
