"""Shared CLI helpers for password-protected PDFs."""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from privacy_firewall.parsers.pdf_open import is_encrypted


def resolve_password(path: Path, password: str | None) -> str | None:
    """Return the password to use for *path*, prompting if needed.

    If *password* is given it is used as-is. Otherwise, when the file is
    encrypted and the session is interactive, the user is prompted with a
    hidden input. A non-interactive run with no password returns ``None``
    and lets the pipeline raise a clear ``EncryptedPDFError``.

    Args:
        path: The PDF path.
        password: An explicitly provided password, or ``None``.

    Returns:
        The password to authenticate with, or ``None``.
    """
    if password:
        return password
    if is_encrypted(path) and sys.stdin.isatty():
        return str(typer.prompt("PDF is password-protected. Password", hide_input=True))
    return None
