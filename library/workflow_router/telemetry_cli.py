"""Command-line validation and explicit reporting for local Router telemetry."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from .telemetry import (
    ContextUsageValidator,
    JsonlContextUsageStore,
    JsonlReceiptUsageEvidenceStore,
    TelemetryReportRequest,
    TelemetryReportStatus,
    generate_telemetry_report,
    render_report_csv,
    render_report_json,
    render_report_table,
    report_bar_chart_data,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Validate one JSONL file, or emit one explicitly requested usage report."""

    parser = argparse.ArgumentParser(
        description="Validate metadata-only Router context-load telemetry."
    )
    parser.add_argument("path", type=Path, help="Ignored local router-usage.jsonl path")
    parser.add_argument(
        "--minimum-reduction-bps",
        type=int,
        default=1,
        help="Required median reduction in basis points; 5000 means 50%%.",
    )
    parser.add_argument(
        "--report-receipt",
        action="append",
        default=None,
        metavar="RECEIPT_REF",
        help="Explicitly request a usage report for this receipt; repeatable.",
    )
    parser.add_argument(
        "--report-format",
        choices=("json", "csv", "table", "bars"),
        default="table",
        help="Export format used only with --report-receipt.",
    )
    arguments = parser.parse_args(argv)
    if arguments.minimum_reduction_bps < 0:
        parser.error("--minimum-reduction-bps must be zero or greater")

    if arguments.report_receipt is not None:
        return _run_explicit_report(
            path=arguments.path,
            receipt_refs=tuple(arguments.report_receipt),
            export_format=arguments.report_format,
        )

    records = JsonlContextUsageStore.read(path=arguments.path)
    report = ContextUsageValidator().validate(
        records=records,
        minimum_reduction_basis_points=arguments.minimum_reduction_bps,
    )
    print(report.model_dump_json(indent=2))
    return 0 if report.reduction_verified else 1


def _run_explicit_report(
    *, path: Path, receipt_refs: tuple[str, ...], export_format: str
) -> int:
    """The CLI invocation itself is the explicit user request; nothing schedules it."""

    try:
        request = TelemetryReportRequest(
            receipt_refs=receipt_refs, explicit_user_request=True
        )
    except ValidationError:
        print('{"status":"BLOCKED","failure":"REQUEST_INVALID"}')
        return 2
    try:
        source = JsonlReceiptUsageEvidenceStore.read(path=path)
    except (OSError, ValueError, ValidationError):
        print('{"status":"BLOCKED","failure":"EVIDENCE_UNAVAILABLE"}')
        return 2
    report = generate_telemetry_report(request, source)
    if report.status is not TelemetryReportStatus.GENERATED:
        print(report.model_dump_json(indent=2))
        return 2
    if export_format == "json":
        print(render_report_json(report))
    elif export_format == "csv":
        print(render_report_csv(report), end="")
    elif export_format == "bars":
        for datum in report_bar_chart_data(report):
            print(datum.model_dump_json())
    else:
        print(render_report_table(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
