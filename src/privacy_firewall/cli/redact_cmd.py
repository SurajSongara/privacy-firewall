"""``redact`` CLI command — produce a redacted PDF copy."""

from pathlib import Path
from typing import Annotated

import typer

from privacy_firewall.cli._pdf import resolve_password
from privacy_firewall.cli.scan_cmd import _safe
from privacy_firewall.engine.decision import ReviewDecision, ReviewPlan, file_sha256
from privacy_firewall.engine.ocr_pipeline import get_merged_document
from privacy_firewall.engine.redact import redact_document
from privacy_firewall.engine.redaction import RedactionPlanner, RedactionType
from privacy_firewall.engine.verification import certify
from privacy_firewall.models.detection import Detection
from privacy_firewall.parsers.pdf_open import EncryptedPDFError
from privacy_firewall.renderer.pdf_renderer import PDFRenderer


def _engine_help() -> str:
    from privacy_firewall.ocr import list_engines

    engines = list_engines()
    default = engines[0] if engines else "(none)"
    return f"OCR engine to use. Available: {', '.join(engines)}. [default: {default}]"


def redact_cmd(
    input_pdf: Annotated[
        Path,
        typer.Argument(help="Path to the original PDF.", exists=True, dir_okay=False),
    ],
    output_pdf: Annotated[
        Path,
        typer.Argument(help="Path for the redacted PDF."),
    ],
    redaction_type: Annotated[
        str,
        typer.Option(
            "--type",
            "-t",
            help="Redaction style: replace, black-bar, or highlight.",
        ),
    ] = "replace",
    detector: Annotated[
        list[str] | None,
        typer.Option(
            "--detector",
            "-d",
            help="Detector(s) to run (repeatable). Runs all if omitted.",
        ),
    ] = None,
    values_only: Annotated[
        bool,
        typer.Option(
            "--values-only/--full-block",
            help="Redact only the matched value (default) or the full block (--full-block).",
        ),
    ] = True,
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
    plan_path: Annotated[
        Path | None,
        typer.Option(
            "--plan",
            help="Apply a review plan (from `detect --plan`) instead of re-detecting.",
            exists=True,
            dir_okay=False,
        ),
    ] = None,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive",
            help="With --plan: review undecided detections in the terminal.",
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            help="With --plan: accept all suggestions (unresolved 'ask' items are redacted).",
        ),
    ] = False,
    certificate: Annotated[
        bool,
        typer.Option(
            "--certificate",
            help="Verify the output leaks no redacted PII and write an audit certificate.",
        ),
    ] = False,
    password: Annotated[
        str | None,
        typer.Option("--password", help="Password for an encrypted (password-protected) PDF."),
    ] = None,
) -> None:
    """Scan a PDF for PII and produce a redacted copy."""
    type_map: dict[str, RedactionType] = {
        "replace": RedactionType.REPLACE,
        "black-bar": RedactionType.BLACK_BAR,
        "highlight": RedactionType.HIGHLIGHT,
    }
    rtype = type_map.get(redaction_type)
    if rtype is None:
        choices = ", ".join(sorted(type_map))
        msg = f"Unknown redaction type: {redaction_type!r}. Choose from: {choices}"
        raise typer.BadParameter(msg)

    pw = resolve_password(input_pdf, password)
    try:
        if plan_path is not None:
            detections = _resolve_from_plan(plan_path, input_pdf, interactive=interactive, yes=yes)
            document, _ = get_merged_document(input_pdf, password=pw)
            pipeline_note = f"review plan ({plan_path.name})"
            planner = RedactionPlanner()
            plan = planner.plan(document, detections, default_type=rtype)
            out_path = PDFRenderer().render(input_pdf, output_pdf, plan, password=pw)
            redaction_count = plan.total_redactions
        else:
            out_path, detections, pipeline_note = redact_document(
                input_pdf,
                output_pdf,
                redaction_type=rtype,
                force_ocr=ocr,
                auto=auto,
                ocr_provider=ocr_engine,
                detector_names=detector,
                values_only=values_only,
                password=pw,
            )
            redaction_count = len(detections)
    except EncryptedPDFError as exc:
        typer.echo(f"Error: {_safe(str(exc))}", err=True)
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo(f"Pipeline: {pipeline_note}")
    typer.echo(f"Redacted PDF saved to: {out_path}")
    typer.echo(f"Redactions applied: {redaction_count}")

    if certificate:
        if rtype is RedactionType.HIGHLIGHT:
            typer.echo(
                "Skipping certificate: --type highlight is a visual overlay, "
                "not a destructive redaction.",
                err=True,
            )
        else:
            _write_certificate(input_pdf, out_path, detections)


def _write_certificate(input_pdf: Path, out_path: Path, detections: list[Detection]) -> None:
    """Verify the redacted output and write JSON + PDF certificates."""
    json_path = out_path.with_name(f"{out_path.stem}.certificate.json")
    pdf_path = out_path.with_name(f"{out_path.stem}.certificate.pdf")
    cert = certify(input_pdf, out_path, detections, json_path=json_path, pdf_path=pdf_path)
    status = "PASSED" if cert.verification_passed else "FAILED"
    typer.echo(f"Verification: {status} - {_safe(cert.verification_detail)}")
    typer.echo(f"Certificate: {json_path}  /  {pdf_path}")
    if not cert.verification_passed:
        raise typer.Exit(code=1)


def _resolve_from_plan(
    plan_path: Path, input_pdf: Path, *, interactive: bool, yes: bool
) -> list[Detection]:
    """Load a review plan, optionally review it, and resolve the redact list."""
    review_plan = ReviewPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))

    actual_hash = file_sha256(input_pdf)
    if review_plan.source_sha256 != actual_hash:
        msg = (
            f"Plan {plan_path} was created for a different file "
            f"(plan hash {review_plan.source_sha256[:12]}…, "
            f"input hash {actual_hash[:12]}…)"
        )
        raise typer.BadParameter(msg)

    if interactive:
        _review_interactively(review_plan)
        plan_path.write_text(review_plan.model_dump_json(indent=2), encoding="utf-8")
        typer.echo(f"Decisions saved to: {plan_path}")

    try:
        return review_plan.resolve(accept_suggestions=yes or interactive)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        typer.echo(
            "Hint: re-run with --interactive to review the pending items, "
            "or --yes to accept all suggestions.",
            err=True,
        )
        raise typer.Exit(code=1) from exc


def _review_interactively(review_plan: ReviewPlan) -> None:
    """Walk the undecided 'ask' entries and record the user's decisions."""
    pending = review_plan.pending_entries()
    if not pending:
        typer.echo("No detections need review.")
        return

    typer.echo(f"{len(pending)} detection(s) need review:")
    for i, entry in enumerate(pending, start=1):
        d = entry.detection
        typer.echo(
            f"\n[{i}/{len(pending)}] Page {d.page_number} | {d.detection_type} | {_safe(d.text)}"
        )
        typer.echo(f"  confidence={d.confidence:.2f}")
        for reason in d.reasons + entry.suggestion_reasons:
            typer.echo(f"  - {_safe(reason, max_len=100)}")

        choice = typer.prompt("  [r]edact / [k]eep / [R]edact all / [q]uit", default="r").strip()
        if choice == "q":
            break
        if choice == "R":
            for rest in review_plan.pending_entries():
                rest.decision = ReviewDecision.REDACT
            break
        entry.decision = (
            ReviewDecision.KEEP if choice.lower().startswith("k") else ReviewDecision.REDACT
        )
