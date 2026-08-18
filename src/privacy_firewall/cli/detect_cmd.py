"""``detect`` CLI command — scan a PDF for PII using configured detectors."""

from pathlib import Path
from typing import Annotated

import typer

from privacy_firewall.cli._pdf import resolve_password
from privacy_firewall.detectors import DetectorRegistry, build_registry
from privacy_firewall.engine.context import ContextScorer
from privacy_firewall.engine.decision import DecisionEngine, file_sha256
from privacy_firewall.engine.fusion import FusionEngine
from privacy_firewall.engine.ocr_pipeline import get_merged_document, get_pipeline_summary
from privacy_firewall.parsers.pdf_open import EncryptedPDFError
from privacy_firewall.policy import DEFAULT_POLICY_NAME, get_policy


def _build_registry(detector_names: list[str] | None) -> DetectorRegistry:
    """Build a DetectorRegistry with the requested (or all) detectors.

    Thin CLI wrapper around :func:`privacy_firewall.detectors.build_registry`
    that surfaces an unknown-name error as a Typer parameter error.

    Args:
        detector_names: List of detector names to include, or ``None`` for all.

    Returns:
        A populated DetectorRegistry.
    """
    try:
        return build_registry(detector_names)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _report_hidden(input_pdf: Path, password: str | None) -> None:
    """Print PII found outside the page content stream, if any.

    Metadata and annotations are invisible on the page but readable, and a
    redaction that only edits drawing commands leaves them behind — so they are
    worth surfacing explicitly during detection.
    """
    from privacy_firewall.engine.hidden_pii import scan_hidden_pii
    from privacy_firewall.parsers.pdf_open import EncryptedPDFError, open_pdf

    try:
        with open_pdf(input_pdf, password=password) as doc:
            findings = scan_hidden_pii(doc)
    except (EncryptedPDFError, OSError, ValueError):
        return  # non-PDF input or unreadable — nothing to add

    if not findings:
        return
    typer.echo(f"\nHidden PII - metadata / annotations ({len(findings)}):")
    typer.echo("  (invisible on the page; removed automatically on redaction)")
    for i, f in enumerate(findings, start=1):
        typer.echo(f"  {i:>3}. {f.detection_type:8s} | {f.value!r:30s} | {f.location}")


def _engine_help() -> str:
    from privacy_firewall.ocr import list_engines

    engines = list_engines()
    default = engines[0] if engines else "(none)"
    return f"OCR engine to use. Available: {', '.join(engines)}. [default: {default}]"


def detect_cmd(
    input_pdf: Annotated[
        Path,
        typer.Argument(help="Path to the PDF file to scan.", exists=True, dir_okay=False),
    ],
    detector: Annotated[
        list[str] | None,
        typer.Option(
            "--detector",
            "-d",
            help="Detector(s) to run (repeatable). Runs all if omitted.",
        ),
    ] = None,
    no_fuse: Annotated[
        bool,
        typer.Option("--no-fuse", help="Skip fusion (show raw detections)."),
    ] = False,
    values_only: Annotated[
        bool,
        typer.Option(
            "--values-only",
            help="Use per-span bounding boxes (shows precise match regions).",
        ),
    ] = False,
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
    plan_out: Annotated[
        Path | None,
        typer.Option(
            "--plan",
            help="Write a review-plan JSON (for `redact --plan` or the review UI).",
        ),
    ] = None,
    policy: Annotated[
        str,
        typer.Option(
            "--policy",
            help="Policy for plan suggestions: builtin name or a YAML/JSON file path.",
        ),
    ] = DEFAULT_POLICY_NAME,
    password: Annotated[
        str | None,
        typer.Option("--password", help="Password for an encrypted (password-protected) PDF."),
    ] = None,
) -> None:
    """Run PII detectors on a PDF and list all detections found."""
    pw = resolve_password(input_pdf, password)
    try:
        document, source = get_merged_document(
            input_pdf,
            force_ocr=ocr,
            auto=auto,
            ocr_provider=ocr_engine,
            password=pw,
        )
    except EncryptedPDFError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    registry = _build_registry(detector)
    result = registry.run_all(document, values_only=values_only)

    detections = ContextScorer().apply(document, result.detections)
    if not no_fuse:
        engine = FusionEngine()
        fused = engine.fuse(detections)
        detections = fused.detections

    typer.echo(f"Pipeline: {get_pipeline_summary(source)}")
    typer.echo(f"Detections ({len(detections)}):")
    for i, d in enumerate(detections, start=1):
        typer.echo(
            f"  {i:>3}. Page {d.page_number} | {d.detection_type:8s} | {d.text!r:30s} "
            f"| confidence={d.confidence:.2f} | detector={d.detector_name}"
        )

    _report_hidden(input_pdf, pw)

    if plan_out is not None:
        try:
            policy_obj = get_policy(policy)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        plan = DecisionEngine().decide(
            detections,
            policy_obj,
            source_path=str(input_pdf),
            source_sha256=file_sha256(input_pdf),
        )
        plan_out.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        counts = plan.counts()
        typer.echo(f"Review plan written to: {plan_out}")
        typer.echo(
            f"  Suggested (policy={policy_obj.name}): "
            f"redact={counts['redact']} ask={counts['ask']} keep={counts['keep']}"
        )
