"""``scan`` CLI command — parse a PDF and list its pages and blocks."""

from pathlib import Path
from typing import Annotated

import typer

from privacy_firewall.engine.ocr_pipeline import get_merged_document, get_pipeline_summary
from privacy_firewall.models.blocks import ImageBlock, TextBlock
from privacy_firewall.parsers.pdf_open import EncryptedPDFError


def _safe(text: str, max_len: int = 60) -> str:
    """Return a sanitised, truncated preview safe for the terminal."""
    import sys

    preview = text[:max_len] + "..." if len(text) > max_len else text
    enc = sys.stdout.encoding or "utf-8"
    return preview.encode(enc, errors="replace").decode(enc)


def _engine_help() -> str:
    from privacy_firewall.ocr import list_engines

    engines = list_engines()
    default = engines[0] if engines else "(none)"
    return f"OCR engine to use. Available: {', '.join(engines)}. [default: {default}]"


def scan_cmd(
    input_pdf: Annotated[
        Path,
        typer.Argument(help="Path to the PDF file to scan.", exists=True, dir_okay=False),
    ],
    ocr: Annotated[
        bool,
        typer.Option("--ocr", help="Run OCR and merge with native text."),
    ] = False,
    auto: Annotated[
        bool,
        typer.Option("--auto", help="Auto-detect pipeline (native/OCR/hybrid)."),
    ] = False,
    ocr_engine: Annotated[
        str | None,
        typer.Option("--ocr-engine", help=_engine_help()),
    ] = None,
    password: Annotated[
        str | None,
        typer.Option("--password", help="Password for an encrypted (password-protected) PDF."),
    ] = None,
) -> None:
    """Parse a PDF and display its structure (pages, blocks, text previews)."""
    from privacy_firewall.cli._pdf import resolve_password

    pw = resolve_password(input_pdf, password)
    try:
        document, source = get_merged_document(
            input_pdf, force_ocr=ocr, auto=auto, ocr_provider=ocr_engine, password=pw,
        )
    except EncryptedPDFError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Pipeline: {get_pipeline_summary(source)}")
    typer.echo(f"Pages: {len(document.pages)}")
    for page in document.pages:
        typer.echo(f"Page {page.page_number} ({page.width:.0f} x {page.height:.0f}):")
        for block in page.blocks:
            if isinstance(block, TextBlock):
                typer.echo(f"  [TextBlock]  bbox=({block.bbox}) {_safe(block.text)!r}")
            elif isinstance(block, ImageBlock):
                size = len(block.image_data) if block.image_data else 0
                typer.echo(f"  [ImageBlock] bbox=({block.bbox}) {size} bytes")
