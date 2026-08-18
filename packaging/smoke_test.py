"""Smoke-test a frozen (PyInstaller) build by driving the packaged binary.

This is the check that catches the bundling failures static analysis cannot:
missing dist metadata (``--version``), missing uvicorn/onnxruntime pieces, and
OCR models that were not collected into the bundle. It runs the *real* binary
as a subprocess, so it proves the shipped artifact works rather than the
developer's importable source tree.

    python packaging/smoke_test.py dist/PrivacyFirewall/PrivacyFirewall.exe

Fixtures are generated with PyMuPDF from the *host* environment (not the
bundle) and every value in them is synthetic.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import fitz

# Entirely fabricated values — a valid-format PAN and a plausible statement line.
SAMPLE_LINES = [
    "ACME CONSULTING - STATEMENT",
    "Customer: Ramesh Kumar",
    "PAN: ABCPE1234F",
    "Email: ramesh@example.com",
    "Phone: 9876543210",
]

failures: list[str] = []


def run(binary: Path, *args: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    """Run the packaged binary with *args* and capture its output."""
    return subprocess.run(
        [str(binary), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


def check(name: str, condition: bool, detail: str = "") -> None:
    """Record a pass/fail line for *name*."""
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}")
        if detail:
            print(f"        {detail.strip()[:800]}")
        failures.append(name)


def make_text_pdf(path: Path) -> None:
    """Write a synthetic text-layer statement."""
    doc = fitz.open()
    page = doc.new_page()
    y = 100
    for line in SAMPLE_LINES:
        page.insert_text((60, y), line, fontsize=13)
        y += 30
    doc.save(str(path))
    doc.close()


def make_scanned_pdf(source: Path, path: Path) -> None:
    """Rasterise *source* into an image-only PDF (no text layer) for the OCR path."""
    src = fitz.open(str(source))
    pix = src[0].get_pixmap(dpi=200)
    src.close()
    doc = fitz.open()
    page = doc.new_page(width=pix.width, height=pix.height)
    page.insert_image(fitz.Rect(0, 0, pix.width, pix.height), pixmap=pix)
    doc.save(str(path))
    doc.close()


def _free_port() -> int:
    """Grab an OS-assigned free port, then release it for the child to bind."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def check_studio(binary: Path, workspace: Path) -> None:
    """Launch the Studio web server from the frozen bundle and hit it over HTTP.

    This is the check that would catch a missing web dependency (e.g.
    python-multipart, which Starlette imports lazily for the UploadFile upload
    route). Such a failure raises at app-creation time, so the process exits
    before the port ever opens -- which this check detects as a timeout.
    """
    port = _free_port()
    url = f"http://127.0.0.1:{port}/"
    proc = subprocess.Popen(
        [str(binary), "--workspace", str(workspace), "--port", str(port), "--no-browser"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        deadline = time.monotonic() + 60
        status = 0
        while time.monotonic() < deadline:
            if proc.poll() is not None:  # server died during startup
                break
            try:
                with urllib.request.urlopen(url, timeout=2) as resp:
                    status = resp.status
                break
            except (urllib.error.URLError, ConnectionError, OSError):
                time.sleep(0.5)
        detail = ""
        if status != 200:
            if proc.poll() is not None and proc.stdout is not None:
                detail = proc.stdout.read()
            else:
                detail = f"server did not answer on {url} within timeout"
        check("Studio server starts and serves the dashboard", status == 200, detail)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    """Run every smoke check; return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path, help="Path to the frozen executable")
    parser.add_argument("--skip-ocr", action="store_true", help="Skip the OCR bundling check")
    args = parser.parse_args()

    binary: Path = args.binary
    if not binary.exists():
        print(f"ERROR: no such binary: {binary}")
        return 2

    print(f"Smoke-testing {binary}\n")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        doc_pdf = work / "statement.pdf"
        make_text_pdf(doc_pdf)

        # 1. Dist metadata survived freezing (copy_metadata in the spec).
        proc = run(binary, "--version")
        check(
            "--version reports a version",
            proc.returncode == 0 and proc.stdout.strip() != "",
            proc.stderr or proc.stdout,
        )

        # 2. Core engine: parser + detectors + fusion.
        proc = run(binary, "detect", str(doc_pdf))
        check(
            "detect finds the synthetic PAN",
            proc.returncode == 0 and "ABCPE1234F" in proc.stdout,
            proc.stderr or proc.stdout,
        )

        # 3. Renderer + verification/certificate path.
        out_pdf = work / "out.pdf"
        proc = run(binary, "redact", str(doc_pdf), str(out_pdf), "--certificate")
        cert = out_pdf.with_suffix(".certificate.json")
        check(
            "redact --certificate writes a redacted PDF",
            proc.returncode == 0 and out_pdf.exists(),
            proc.stderr or proc.stdout,
        )
        check("certificate JSON was written", cert.exists(), proc.stdout)
        if cert.exists():
            data = json.loads(cert.read_text(encoding="utf-8"))
            check(
                "certificate reports a passing verification",
                json.dumps(data).upper().count("FAIL") == 0,
                json.dumps(data)[:400],
            )

        # 4. The PAN must be gone from the output text layer.
        if out_pdf.exists():
            with fitz.open(str(out_pdf)) as doc:
                text = "".join(page.get_text() for page in doc)
            check("redacted output no longer contains the PAN", "ABCPE1234F" not in text)

        # 5. Studio web server: proves the UI extra (fastapi/uvicorn/
        #    python-multipart) is fully bundled and the app actually serves.
        check_studio(binary, work)

        # 6. OCR: proves rapidocr models + onnxruntime natives were bundled.
        if args.skip_ocr:
            print("  SKIP  OCR bundling check (--skip-ocr)")
        else:
            scan_pdf = work / "scan.pdf"
            make_scanned_pdf(doc_pdf, scan_pdf)
            proc = run(binary, "detect", str(scan_pdf), "--ocr", timeout=900)
            check(
                "OCR pipeline runs in the frozen bundle",
                proc.returncode == 0 and "Detections (" in proc.stdout,
                proc.stderr or proc.stdout,
            )

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
