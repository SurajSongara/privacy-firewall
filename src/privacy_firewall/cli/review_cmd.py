"""``review`` CLI command — local web UI for reviewing detections."""

from pathlib import Path
from typing import Annotated

import typer

from privacy_firewall.policy import DEFAULT_POLICY_NAME, get_policy


def review_cmd(
    input_pdf: Annotated[
        Path,
        typer.Argument(help="Path to the PDF to review.", exists=True, dir_okay=False),
    ],
    policy: Annotated[
        str,
        typer.Option(
            "--policy",
            help="Policy for suggestions: builtin name or a YAML/JSON file path.",
        ),
    ] = DEFAULT_POLICY_NAME,
    port: Annotated[
        int | None,
        typer.Option("--port", help="Port for the local server (default: auto)."),
    ] = None,
    no_browser: Annotated[
        bool,
        typer.Option("--no-browser", help="Don't open the browser automatically."),
    ] = False,
    ocr: Annotated[
        bool,
        typer.Option("--ocr", help="Force OCR and merge with native text."),
    ] = False,
    auto: Annotated[
        bool,
        typer.Option(
            "--auto/--no-auto",
            help="Let diagnostics pick the pipeline (default: on, so scanned PDFs get OCR).",
        ),
    ] = True,
    ocr_engine: Annotated[
        str | None,
        typer.Option("--ocr-engine", help="OCR engine to use."),
    ] = None,
    password: Annotated[
        str | None,
        typer.Option(
            "--password",
            help="Password for an encrypted PDF (you can also enter it in the browser).",
        ),
    ] = None,
) -> None:
    """Review detections in a local web UI, then export the redacted PDF."""
    try:
        from privacy_firewall.ui.server import run_review
    except ImportError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        policy_obj = get_policy(policy)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo(f"Analysing {input_pdf} with policy '{policy_obj.name}'…")
    run_review(
        input_pdf,
        policy_obj,
        port=port,
        open_browser=not no_browser,
        force_ocr=ocr,
        auto=auto and not ocr,
        ocr_provider=ocr_engine,
        password=password,
    )
