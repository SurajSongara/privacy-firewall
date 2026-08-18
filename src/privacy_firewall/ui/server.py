"""FastAPI server for the local review UI.

Requires the ``ui`` extra (``pip install privacy-firewall[ui]``).
The server binds to 127.0.0.1 only — nothing leaves the machine.
"""

from __future__ import annotations

import socket
import threading
import webbrowser
from pathlib import Path

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, HTMLResponse, Response
    from pydantic import BaseModel
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    msg = "The review UI requires the 'ui' extra: pip install privacy-firewall[ui]"
    raise ImportError(msg) from exc

from privacy_firewall.engine.redaction import RedactionType
from privacy_firewall.policy.models import Policy
from privacy_firewall.ui.html import PAGE_HTML
from privacy_firewall.ui.session import ReviewSession


class DecisionRequest(BaseModel):
    """A decision toggle from the UI."""

    detection_id: str
    decision: str | None = None


class ApplyRequest(BaseModel):
    """Apply request; output path and redaction style are optional."""

    output_path: str | None = None
    redaction_type: str | None = None


class RerunRequest(BaseModel):
    """Re-run the pipeline (forcing OCR) from the UI."""

    ocr_engine: str | None = None


class UnlockRequest(BaseModel):
    """Supply a password to unlock an encrypted PDF."""

    password: str


class MarkRequest(BaseModel):
    """Mark every instance of a text selection as PII."""

    text: str
    label: str
    case_sensitive: bool = False
    remember: bool = False
    """Also remember the term for every document in the workspace."""


class RemoveRequest(BaseModel):
    """Remove a manually marked entry."""

    detection_id: str


def create_app(session: ReviewSession) -> FastAPI:
    """Build the review app around one ReviewSession.

    Args:
        session: The session holding the document, plan, and page images.

    Returns:
        The configured FastAPI application.
    """
    app = FastAPI(title="Privacy Firewall Review", docs_url=None, redoc_url=None)
    rerun_lock = threading.Lock()
    # Sync endpoints run in a threadpool; every access to the mutable
    # plan is serialised so concurrent mark/decide/apply calls can't
    # corrupt the entries list mid-iteration.
    plan_lock = threading.RLock()

    def ensure_ready() -> None:
        """Reject data requests until the pipeline has finished."""
        if not session.is_ready:
            raise HTTPException(status_code=425, detail=session.status_payload())

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return PAGE_HTML

    @app.get("/api/status")
    def status() -> dict:  # type: ignore[type-arg]
        return session.status_payload()

    @app.post("/api/rerun")
    def rerun(request: RerunRequest) -> dict:  # type: ignore[type-arg]
        with rerun_lock:
            if session.status not in ("ready", "error"):
                raise HTTPException(status_code=409, detail="pipeline is already running")
            session.status = "parsing"  # claim before the thread starts

        def worker() -> None:
            try:
                session.rerun(force_ocr=True, ocr_provider=request.ocr_engine)
            except Exception:  # noqa: BLE001 - status/error already recorded
                pass

        threading.Thread(target=worker, daemon=True).start()
        return session.status_payload()

    @app.post("/api/unlock")
    def unlock(request: UnlockRequest) -> dict:  # type: ignore[type-arg]
        with rerun_lock:
            if session.status not in ("error", "ready"):
                raise HTTPException(status_code=409, detail="pipeline is already running")
            session.status = "parsing"  # claim before the thread starts

        def worker() -> None:
            try:
                session.unlock(request.password)
            except Exception:  # noqa: BLE001 - status/error already recorded
                pass

        threading.Thread(target=worker, daemon=True).start()
        return session.status_payload()

    @app.get("/api/pages")
    def pages() -> dict:  # type: ignore[type-arg]
        # Deliberately no ensure_ready(): page geometry comes straight
        # from the PDF so the UI can render pages during a long OCR run.
        try:
            return {"pages": session.page_dimensions()}
        except Exception as exc:  # noqa: BLE001 - unreadable/corrupt file
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/plan")
    def plan() -> dict:  # type: ignore[type-arg]
        ensure_ready()
        with plan_lock:
            # Terms remembered in a sibling document since this session's
            # pipeline ran surface on the next plan read (idempotent).
            session.sync_remembered_terms()
            return session.summary()

    @app.get("/api/page/{page_number}")
    def page_png(page_number: int) -> Response:
        try:
            png = session.page_png(page_number)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(content=png, media_type="image/png")

    @app.get("/api/preview/{page_number}")
    def preview_png(page_number: int) -> Response:
        ensure_ready()
        try:
            with plan_lock:
                png = session.preview_page_png(page_number)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(content=png, media_type="image/png")

    @app.get("/api/text/{page_number}")
    def page_text(page_number: int) -> dict:  # type: ignore[type-arg]
        ensure_ready()
        try:
            words = session.page_words(page_number)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"words": words}

    @app.post("/api/mark")
    def mark(request: MarkRequest) -> dict:  # type: ignore[type-arg]
        ensure_ready()
        try:
            with plan_lock:
                result = session.mark_text(
                    request.text, request.label, case_sensitive=request.case_sensitive
                )
                remembered = request.remember and session.remember_text(
                    request.text, request.label, case_sensitive=request.case_sensitive
                )
                return {
                    "added": len(result.added),
                    "skipped": result.skipped,
                    "remembered": remembered,
                    "entries": [session.entry_dict(e) for e in result.added],
                    "counts": session.plan.counts(),
                }
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/remove")
    def remove(request: RemoveRequest) -> dict:  # type: ignore[type-arg]
        ensure_ready()
        with plan_lock:
            if not session.remove_manual_entry(request.detection_id) and not session.forget_term(
                request.detection_id
            ):
                raise HTTPException(status_code=404, detail="unknown or non-manual detection_id")
            return {"ok": True, "counts": session.plan.counts()}

    @app.post("/api/decision")
    def decision(request: DecisionRequest) -> dict:  # type: ignore[type-arg]
        ensure_ready()
        if request.decision not in (None, "redact", "keep"):
            raise HTTPException(status_code=422, detail="decision must be redact/keep/null")
        with plan_lock:
            if not session.set_decision(request.detection_id, request.decision):
                raise HTTPException(status_code=404, detail="unknown detection_id")
            return {"ok": True, "counts": session.plan.counts()}

    @app.post("/api/apply")
    def apply(request: ApplyRequest) -> dict:  # type: ignore[type-arg]
        ensure_ready()
        redaction_type = RedactionType.REPLACE
        if request.redaction_type is not None:
            try:
                redaction_type = RedactionType(request.redaction_type)
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail="redaction_type must be replace/black_bar/highlight",
                ) from exc
        output = Path(request.output_path) if request.output_path else None
        with plan_lock:
            out_path, count = session.apply(output, redaction_type=redaction_type)
        return {
            "output_path": str(out_path),
            "redactions": count,
            "plan_path": str(session.plan_file_path),
        }

    @app.post("/api/save")
    def save() -> dict:  # type: ignore[type-arg]
        ensure_ready()
        with plan_lock:
            return {"plan_path": str(session.save_plan())}

    @app.get("/api/output")
    def output() -> FileResponse:
        path = session.last_output_path
        if path is None or not path.exists():
            raise HTTPException(status_code=404, detail="no redacted output yet — apply first")
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=path.name,
            content_disposition_type="inline",
        )

    return app


def _free_port() -> int:
    """Ask the OS for an available localhost port."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run_review(
    pdf_path: Path,
    policy: Policy,
    *,
    port: int | None = None,
    open_browser: bool = True,
    force_ocr: bool = False,
    auto: bool = False,
    ocr_provider: str | None = None,
    password: str | None = None,
) -> None:
    """Serve the review UI immediately; the pipeline runs in the background.

    The browser shows a progress screen (via ``/api/status``) while the
    document is parsed, OCR'd, and scanned. Blocks until Ctrl+C.

    Args:
        pdf_path: The PDF to review.
        policy: Policy for the suggested actions.
        port: Fixed port, or ``None`` for an OS-assigned free port.
        open_browser: Open the default browser once the server starts.
        force_ocr: Force the OCR pipeline.
        auto: Let diagnostics choose the pipeline.
        ocr_provider: Specific OCR engine name.
        password: Password for an encrypted PDF (else the browser prompts).
    """
    import uvicorn

    session = ReviewSession(
        pdf_path,
        policy,
        force_ocr=force_ocr,
        auto=auto,
        ocr_provider=ocr_provider,
        lazy=True,
        password=password,
    )
    app = create_app(session)

    def pipeline_worker() -> None:
        try:
            session.run()
        except Exception as exc:  # noqa: BLE001 - surfaced via /api/status
            print(f"Pipeline failed: {exc}")

    threading.Thread(target=pipeline_worker, daemon=True).start()

    chosen_port = port if port is not None else _free_port()
    url = f"http://127.0.0.1:{chosen_port}"
    print(f"Review UI: {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.8, webbrowser.open, args=(url,)).start()

    uvicorn.run(app, host="127.0.0.1", port=chosen_port, log_level="warning")
