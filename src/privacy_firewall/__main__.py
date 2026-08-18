"""Entry-point module for the privacy-firewall CLI."""

from pathlib import Path
from typing import Annotated

import typer

from privacy_firewall.cli import (
    batch_cmd,
    detect_cmd,
    diagnostics_cmd,
    doctor_cmd,
    redact_cmd,
    review_cmd,
    scan_cmd,
)

app = typer.Typer(
    name="privacy-firewall",
    help="Offline-first PII Detection & Redaction Engine",
    pretty_exceptions_enable=False,
)

app.command(name="scan")(scan_cmd)
app.command(name="detect")(detect_cmd)
app.command(name="redact")(redact_cmd)
app.command(name="redact-batch")(batch_cmd)
app.command(name="diagnostics")(diagnostics_cmd)
app.command(name="doctor")(doctor_cmd)
app.command(name="review")(review_cmd)


@app.callback(invoke_without_command=True)
def callback(
    ctx: typer.Context,
    version_flag: Annotated[  # noqa: FBT001
        bool, typer.Option("--version", help="Show the version and exit.")
    ] = False,
    workspace: Annotated[
        Path,
        typer.Option(
            "--workspace",
            help=(
                "Folder scanned for documents (PDF, images, txt, md, docx) "
                "and used to store uploads (default: current directory)."
            ),
        ),
    ] = Path.cwd(),
    port: Annotated[
        int | None,
        typer.Option("--port", help="Port for the local server (default: auto)."),
    ] = None,
    no_browser: Annotated[
        bool,
        typer.Option("--no-browser", help="Don't open the browser automatically."),
    ] = False,
) -> None:
    """CLI callback: launch the local Studio dashboard with no arguments.

    Args:
        ctx: The Typer context.
        version_flag: When True, prints the installed package version and exits.
        workspace: Folder scanned for documents and used to store uploads.
        port: Fixed port, or ``None`` for an OS-assigned free port.
        no_browser: When True, don't open the browser automatically.
    """
    if version_flag:
        from importlib.metadata import version

        typer.echo(version("privacy_firewall"))
        raise typer.Exit()
    if ctx.invoked_subcommand is not None:
        return
    try:
        from privacy_firewall.ui.studio import run_studio
    except ImportError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    run_studio(workspace, port=port, open_browser=not no_browser)


def entry_point() -> None:
    """Console-script entry point that runs the Typer application."""
    app()


if __name__ == "__main__":
    entry_point()
