"""``redact-batch`` CLI command — redact every document in a folder."""

from __future__ import annotations

import csv
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import typer

from privacy_firewall.cli.scan_cmd import _safe
from privacy_firewall.engine.redact import redact_document
from privacy_firewall.engine.redaction import RedactionType
from privacy_firewall.engine.verification import certify
from privacy_firewall.models.detection import Detection
from privacy_firewall.parsers.converters import (
    ConversionError,
    convert_to_pdf,
    is_supported,
    needs_conversion,
)

_TYPE_MAP: dict[str, RedactionType] = {
    "replace": RedactionType.REPLACE,
    "black-bar": RedactionType.BLACK_BAR,
    "highlight": RedactionType.HIGHLIGHT,
}


@dataclass
class _Row:
    """One line of the batch summary."""

    file: str
    status: str = "ok"  # ok | error
    redactions: int = 0
    types: dict[str, int] = field(default_factory=dict)
    verified: str = "na"  # na | pass | fail
    output: str = ""
    error: str = ""


def batch_cmd(
    folder: Annotated[
        Path,
        typer.Argument(help="Folder of documents to redact.", exists=True, file_okay=False),
    ],
    out_dir: Annotated[
        Path | None,
        typer.Option("--out", help="Output folder (default: alongside the originals)."),
    ] = None,
    redaction_type: Annotated[
        str,
        typer.Option("--type", "-t", help="Redaction style: replace, black-bar, or highlight."),
    ] = "replace",
    values_only: Annotated[
        bool,
        typer.Option(
            "--values-only/--full-block",
            help="Redact only the matched value (default) or the full block.",
        ),
    ] = True,
    ocr: Annotated[bool, typer.Option("--ocr", help="Run OCR and merge with native text.")] = False,
    auto: Annotated[
        bool, typer.Option("--auto", help="Auto-detect pipeline (native/OCR/hybrid).")
    ] = False,
    ocr_engine: Annotated[
        str | None, typer.Option("--ocr-engine", help="OCR engine to use.")
    ] = None,
    certificate: Annotated[
        bool,
        typer.Option(
            "--certificate",
            help="Verify each output leaks no redacted PII and write a certificate.",
        ),
    ] = False,
    password: Annotated[
        str | None,
        typer.Option(
            "--password",
            help="Password applied to every encrypted PDF in the folder.",
        ),
    ] = None,
) -> None:
    """Redact every supported document in a folder, writing a summary report.

    Originals are never modified. One bad file is reported but does not abort
    the run. Exits non-zero if any file errored or failed verification.
    """
    rtype = _TYPE_MAP.get(redaction_type)
    if rtype is None:
        choices = ", ".join(sorted(_TYPE_MAP))
        raise typer.BadParameter(
            f"Unknown redaction type: {redaction_type!r}. Choose from: {choices}"
        )

    out = out_dir or folder
    out.mkdir(parents=True, exist_ok=True)

    files = _collect(folder)
    if not files:
        typer.echo("No supported documents found in the folder.")
        return

    typer.echo(f"Redacting {len(files)} document(s) into {out}\n")
    rows: list[_Row] = []
    with tempfile.TemporaryDirectory() as tmp:
        for src in files:
            rows.append(
                _process_one(
                    src,
                    out,
                    Path(tmp),
                    rtype=rtype,
                    values_only=values_only,
                    ocr=ocr,
                    auto=auto,
                    ocr_engine=ocr_engine,
                    certificate=certificate,
                    password=password,
                )
            )

    _write_summary(out, rows)
    _echo_totals(out, rows)

    failures = [r for r in rows if r.status == "error" or r.verified == "fail"]
    if failures:
        raise typer.Exit(code=1)


def _collect(folder: Path) -> list[Path]:
    """Supported input documents in *folder*, excluding our own outputs."""
    files: list[Path] = []
    for path in sorted(folder.iterdir()):
        name = path.name.lower()
        if not path.is_file() or name.endswith(".redacted.pdf") or ".certificate." in name:
            continue
        if is_supported(path):
            files.append(path)
    return files


def _process_one(
    src: Path,
    out: Path,
    tmp: Path,
    *,
    rtype: RedactionType,
    values_only: bool,
    ocr: bool,
    auto: bool,
    ocr_engine: str | None,
    certificate: bool,
    password: str | None,
) -> _Row:
    """Redact one document; never raises — records the error on the row."""
    row = _Row(file=src.name)
    try:
        pdf = src
        if needs_conversion(src):
            pdf = tmp / f"{src.name}.pdf"
            convert_to_pdf(src, pdf)

        output = out / f"{src.stem}.redacted.pdf"
        out_path, detections, _ = redact_document(
            pdf,
            output,
            redaction_type=rtype,
            force_ocr=ocr,
            auto=auto,
            ocr_provider=ocr_engine,
            values_only=values_only,
            password=password,
        )
        row.redactions = len(detections)
        row.types = _counts(detections)
        row.output = str(out_path)

        if certificate and rtype is not RedactionType.HIGHLIGHT:
            json_path = out / f"{src.stem}.redacted.certificate.json"
            pdf_path = out / f"{src.stem}.redacted.certificate.pdf"
            cert = certify(pdf, out_path, detections, json_path=json_path, pdf_path=pdf_path)
            row.verified = "pass" if cert.verification_passed else "fail"

        mark = {"pass": " [verified]", "fail": " [VERIFY FAILED]"}.get(row.verified, "")
        typer.echo(f"  OK  {_safe(src.name)} - {row.redactions} redaction(s){mark}")
    except (ConversionError, ValueError, OSError, RuntimeError) as exc:
        row.status = "error"
        row.error = str(exc)
        typer.echo(f"  ERR {_safe(src.name)} - {_safe(str(exc))}", err=True)
    return row


def _counts(detections: list[Detection]) -> dict[str, int]:
    """Count detections by type."""
    counts: dict[str, int] = {}
    for det in detections:
        counts[det.detection_type] = counts.get(det.detection_type, 0) + 1
    return dict(sorted(counts.items()))


def _write_summary(out: Path, rows: list[_Row]) -> None:
    """Write the batch summary as CSV and JSON."""
    csv_path = out / "redaction-summary.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["file", "status", "redactions", "types", "verified", "output", "error"])
        for r in rows:
            types = ";".join(f"{k}:{v}" for k, v in r.types.items())
            writer.writerow([r.file, r.status, r.redactions, types, r.verified, r.output, r.error])

    json_path = out / "redaction-summary.json"
    payload = [
        {
            "file": r.file,
            "status": r.status,
            "redactions": r.redactions,
            "types": r.types,
            "verified": r.verified,
            "output": r.output,
            "error": r.error,
        }
        for r in rows
    ]
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _echo_totals(out: Path, rows: list[_Row]) -> None:
    """Print the run totals."""
    ok = sum(1 for r in rows if r.status == "ok")
    errors = sum(1 for r in rows if r.status == "error")
    redactions = sum(r.redactions for r in rows)
    failed_verify = sum(1 for r in rows if r.verified == "fail")

    typer.echo(f"\nDone: {ok} redacted, {errors} error(s), {redactions} total redaction(s).")
    if failed_verify:
        typer.echo(f"WARNING: {failed_verify} file(s) FAILED verification.", err=True)
    typer.echo(f"Summary: {out / 'redaction-summary.csv'}")
