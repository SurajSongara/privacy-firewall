"""``doctor`` CLI command — full document health report."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from privacy_firewall.cli._pdf import resolve_password
from privacy_firewall.diagnostics import DocumentAnalyzer
from privacy_firewall.layout import LayoutAnalyzer
from privacy_firewall.parsers.pdf_parser import PDFParser


def doctor_cmd(
    input_pdf: Annotated[
        Path,
        typer.Argument(help="Path to the PDF file to diagnose.", exists=True, dir_okay=False),
    ],
    password: Annotated[
        str | None,
        typer.Option("--password", help="Password for an encrypted (password-protected) PDF."),
    ] = None,
) -> None:
    """Analyse a PDF and display a comprehensive health report."""
    pw = resolve_password(input_pdf, password)

    # --- Diagnostics ---
    analyzer = DocumentAnalyzer(input_pdf, pw)
    report = analyzer.analyze()
    # The document is locked if it is encrypted and we could read no content.
    locked = report.is_encrypted and not report.has_native_text and report.image_count == 0

    typer.echo("=== Document Diagnostics ===")
    typer.echo(f"File:           {report.file_path}")
    typer.echo(f"Pages:          {report.page_count}")
    typer.echo(f"Images:         {report.image_count}")
    typer.echo(f"Native text:    {'yes' if report.has_native_text else 'no'}")
    typer.echo(f"Encrypted:      {'yes' if report.is_encrypted else 'no'}")
    typer.echo(f"Rotated pages:  {report.rotated_pages or 'none'}")
    typer.echo(f"Estimated scan: {'yes' if report.estimated_scanned else 'no'}")
    typer.echo(f"Pipeline:       {report.recommended_pipeline.value}")

    # --- Text quality ---
    tqr = report.text_quality_report
    if tqr is not None:
        typer.echo("")
        typer.echo("--- Text Quality ---")
        typer.echo(f"  Overall:        {tqr.overall_score:.4f}")
        typer.echo(f"  Printable:      {tqr.printable_ratio:.4f}")
        typer.echo(f"  Replace penalty:{tqr.replace_penalty:.4f}")
        typer.echo(f"  Fragmentation:  {tqr.fragmentation_score:.4f}")
        typer.echo(f"  Token quality:  {tqr.token_quality:.4f}")
        typer.echo(f"  Whitespace:     {tqr.whitespace_ratio:.4f}")
        if tqr.reasons:
            typer.echo(f"  Issues: {', '.join(tqr.reasons)}")

    # --- OCR recommendation ---
    typer.echo("")
    typer.echo("--- OCR Recommendation ---")
    if locked:
        typer.echo("  This PDF is password-protected and could not be read.")
        typer.echo("  Re-run with --password <password> to analyse or redact it.")
    elif report.recommended_pipeline.value == "ocr":
        typer.echo("  This document has little or no extractable text.")
        typer.echo("  Recommendation: run with --ocr to invoke OCR.")
    elif report.recommended_pipeline.value == "hybrid":
        typer.echo("  Text quality is sub-optimal. Hybrid mode recommended.")
    else:
        typer.echo("  Text quality is good. Native extraction should suffice.")

    # --- Layout summary ---
    if locked:
        return
    try:
        parser = PDFParser(input_pdf, pw)
        document = parser.parse()
        layout_results = LayoutAnalyzer.analyze(document)

        typer.echo("")
        typer.echo("--- Layout Summary ---")
        for page_analysis in layout_results:
            counts: dict[str, int] = {}
            for el in page_analysis.elements:
                counts[el.type.value] = counts.get(el.type.value, 0) + 1
            parts = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
            typer.echo(f"  Page {page_analysis.page_number}: {parts or 'no elements'}")
    except Exception:
        typer.echo("  (Layout analysis unavailable — document may be encrypted or empty)")
