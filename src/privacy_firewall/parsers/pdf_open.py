"""Password-aware PDF opening.

Every component that opens a PDF (parser, OCR, renderer, page images,
diagnostics, UI session) goes through :func:`open_pdf` so encrypted files
are authenticated in one place and fail with a single clear error instead
of PDFium's generic ``Failed to load document``.
"""

from __future__ import annotations

from pathlib import Path

from privacy_firewall.parsers.pdfium_compat import PdfiumDocument, open_document


class EncryptedPDFError(ValueError):
    """A PDF is password-protected and no (or an incorrect) password was given."""


def open_pdf(
    path: str | Path | None = None,
    *,
    stream: bytes | None = None,
    password: str | None = None,
    required: bool = True,
) -> PdfiumDocument:
    """Open a PDF, authenticating it when it is password-protected.

    Args:
        path: Path to the PDF (mutually exclusive with *stream*).
        stream: Raw PDF bytes (mutually exclusive with *path*).
        password: Password to unlock the document, if it needs one.
        required: When ``True`` (the default), raise if the document is
            still locked after the password attempt. When ``False``, a
            locked document is returned as-is so the caller can inspect
            ``doc.needs_pass`` (used by diagnostics, which must report
            encryption rather than crash).

    Returns:
        An open document.

    Raises:
        EncryptedPDFError: If the document is locked and *required* is
            ``True`` and no correct password was supplied.
    """
    doc = open_document(path, stream=stream, password=password)
    if doc.needs_pass:
        if password:
            doc.close()
            raise EncryptedPDFError("Incorrect password for this PDF.")
        if required:
            doc.close()
            raise EncryptedPDFError(
                "This PDF is password-protected. Provide the password to open it."
            )
    return doc


def is_encrypted(path: str | Path) -> bool:
    """Whether the PDF at *path* is locked (needs a password to open)."""
    doc = open_document(path)
    try:
        return doc.needs_pass
    finally:
        doc.close()


def decrypted_bytes(path: str | Path, password: str | None = None) -> bytes | None:
    """Return decrypted PDF bytes if *path* is encrypted, else ``None``.

    Lets components that only accept a byte stream (e.g. the OCR adapters)
    process an encrypted file without each learning about passwords: the
    caller decrypts once and hands over the plain bytes.

    Args:
        path: Path to the PDF.
        password: Password to unlock it, if needed.

    Returns:
        Decrypted PDF bytes when the file was encrypted, or ``None`` when
        it was not (so the caller can keep using the path directly).

    Raises:
        EncryptedPDFError: If the file is locked and no correct password
            was supplied.
    """
    if not is_encrypted(path):
        return None
    if not password:
        raise EncryptedPDFError("This PDF is password-protected. Provide the password to open it.")
    doc = open_document(path, password=password)
    try:
        if doc.needs_pass:
            raise EncryptedPDFError("Incorrect password for this PDF.")
        return doc.tobytes()
    finally:
        doc.close()
