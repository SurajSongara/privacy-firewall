"""OCR pipeline — decides whether to invoke OCR and merges results."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from privacy_firewall.diagnostics import DocumentAnalyzer, PipelineType
from privacy_firewall.engine.hybrid_merger import HybridMerger
from privacy_firewall.models.document import Document
from privacy_firewall.ocr.provider import OCRProvider


def get_merged_document(
    pdf_path: Path,
    *,
    force_ocr: bool = False,
    auto: bool = False,
    native_doc: Document | None = None,
    ocr_provider: str | None = None,
    password: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[Document, str]:
    """Return the best available document for detection.

    Args:
        pdf_path: Path to the PDF file.
        force_ocr: When ``True``, always run OCR and merge with native.
        auto: When ``True``, run diagnostics and decide automatically.
        native_doc: Pre-parsed native document (avoids re-parsing).
        ocr_provider: OCR adapter name.  ``None`` uses the registry default.
        password: Password for an encrypted PDF, if required.
        progress: Optional callback invoked with a short stage label
            (``"parsing"``, ``"analyzing"``, ``"ocr"``, ``"merging"``) as
            the pipeline advances — lets callers report progress.

    Returns:
        A ``(document, source)`` tuple where *source* is one of
        ``"native"``, ``"ocr"``, or ``"hybrid"``.
    """
    from privacy_firewall.parsers.pdf_parser import PDFParser

    def report(stage: str) -> None:
        if progress is not None:
            progress(stage)

    if native_doc is None:
        report("parsing")
        native_doc = PDFParser(pdf_path, password=password).parse()

    if not force_ocr and not auto:
        return native_doc, "native"

    if auto:
        report("analyzing")
        report_result = DocumentAnalyzer(pdf_path, password=password).analyze()
        pipeline = report_result.recommended_pipeline
        if pipeline == PipelineType.NATIVE:
            return native_doc, "native"

    report("ocr")
    ocr_doc = _run_ocr(pdf_path, provider=ocr_provider, password=password)

    if not native_doc.pages or all(
        not any(hasattr(b, "text") and b.text for b in p.blocks) for p in native_doc.pages
    ):
        return ocr_doc, "ocr"

    report("merging")
    merge_result = HybridMerger.merge(native_doc, ocr_doc)
    return merge_result.document, "hybrid"


def _run_ocr(pdf_path: Path, provider: str | None = None, password: str | None = None) -> Document:
    """Run an OCR adapter on a PDF file.

    When no provider is named, engines are tried in registry order
    (default first). An adapter can import fine but still fail at
    runtime — e.g. Tesseract installed without its tessdata — so
    failures fall through to the next engine instead of aborting.

    An encrypted PDF is decrypted once to an in-memory byte stream so the
    OCR adapters (which open a path and know nothing about passwords) can
    process it through their ``process_bytes`` path unchanged.

    Args:
        pdf_path: Path to the PDF.
        provider: OCR adapter name, or ``None`` to try all registered
            engines until one succeeds.
        password: Password for an encrypted PDF, if required.

    Returns:
        A ``Document`` with OCR-extracted blocks.

    Raises:
        RuntimeError: If every registered engine failed.
        ValueError: If a named provider is unknown, or none are registered.
        EncryptedPDFError: If the PDF is locked and no correct password given.
    """
    from privacy_firewall.parsers.pdf_open import decrypted_bytes

    # Only decrypt when a password is supplied: an encrypted file with no
    # password already failed the earlier native-parse step, so reaching OCR
    # with password=None means the file is not encrypted — open it by path.
    data = decrypted_bytes(pdf_path, password) if password else None

    def run(adapter: OCRProvider) -> Document:
        return adapter.process_bytes(data) if data is not None else adapter.process(pdf_path)

    if provider is not None:
        return run(_get_adapter(provider))

    from privacy_firewall.ocr import get_registry

    registry = get_registry()
    names = registry.names
    if not names:
        return run(_get_adapter(None))  # raises the install hint

    if registry.default_name in names:
        names.remove(registry.default_name)
        names.insert(0, registry.default_name)

    errors: list[str] = []
    for name in names:
        try:
            return run(_get_adapter(name))
        except Exception as exc:  # noqa: BLE001 - each engine fails its own way
            errors.append(f"{name}: {exc}")

    msg = "All OCR engines failed:\n" + "\n".join(f"  - {e}" for e in errors)
    raise RuntimeError(msg)


def _get_adapter(name: str | None = None) -> OCRProvider:
    """Look up an OCR adapter from the global registry.

    Args:
        name: Adapter name, or ``None`` for the registry default.

    Returns:
        An ``OCRProvider`` instance.

    Raises:
        ValueError: If the name is unknown or no default is set.
    """
    from privacy_firewall.ocr import get_registry

    registry = get_registry()

    if name is None:
        cls = registry.get_default()
        if cls is None:
            msg = (
                "No OCR engine available. Install one of:\n"
                "  pip install tesserocr   (Tesseract)\n"
                "  pip install paddleocr   (PaddleOCR)"
            )
            raise ValueError(msg)
        return cls()

    cls = registry.get(name)
    if cls is None:
        available = ", ".join(registry.names) or "(none)"
        msg = f"Unknown OCR engine: {name!r}. Available: {available}"
        raise ValueError(msg)
    return cls()


def get_pipeline_summary(source: str) -> str:
    """Return a human-readable summary of the pipeline used.

    Args:
        source: The pipeline source string.

    Returns:
        A descriptive string.
    """
    summaries = {
        "native": "Native text extraction",
        "ocr": "Full OCR processing",
        "hybrid": "Hybrid (native + OCR merge)",
    }
    return summaries.get(source, f"Unknown ({source})")
