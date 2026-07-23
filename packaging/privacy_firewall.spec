# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build recipe for the Privacy Firewall desktop app.

One spec drives all three desktops; the platform-specific bits (icon format,
macOS .app bundle) branch on ``sys.platform``. Build with:

    pyinstaller --clean --noconfirm packaging/privacy_firewall.spec

Produces a *onedir* bundle at ``dist/PrivacyFirewall/``. onedir (not onefile)
is deliberate: it avoids the onefile temp-extraction startup lag and draws
markedly fewer Windows antivirus false positives. The native installer hides
the folder from the user anyway.

Names like ``Analysis``, ``PYZ``, ``EXE``, ``COLLECT``, ``BUNDLE`` and
``SPECPATH`` are injected by PyInstaller when it executes this file.
Targets PyInstaller >= 6 (the ``cipher`` argument was removed in 6.0).
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

APP_NAME = "PrivacyFirewall"
HERE = Path(SPECPATH)  # noqa: F821 - injected by PyInstaller

datas = []
binaries = []
hiddenimports = []


def optional(label, fn, *args):
    """Run a collector, tolerating a dependency that isn't installed locally.

    CI installs the full extras so nothing is skipped there; this only keeps a
    developer's partial environment from failing the whole build.
    """
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 - a missing extra must not abort the build
        print(f"[spec] WARNING: skipping {label}: {exc}")
        return []


# --- Package metadata -------------------------------------------------------
# __main__.py resolves --version via importlib.metadata.version("privacy_firewall").
# Frozen bundles drop dist-info by default, which would make --version crash.
datas += copy_metadata("privacy-firewall")

# --- Web UI -----------------------------------------------------------------
# uvicorn lazy-imports its loop/protocol/lifespan backends, so static analysis
# never sees them. The Studio HTML/JS is a Python string in ui/html.py, so
# there are no template data files to collect.
hiddenimports += collect_submodules("uvicorn")

# python-multipart backs UploadFile in studio.py's /api/upload route. Starlette
# imports it lazily (as "multipart" on older releases, "python_multipart" on
# newer ones), so it is invisible to the import graph. Collect both names.
hiddenimports += optional("multipart submodules", collect_submodules, "multipart")
hiddenimports += optional("python_multipart submodules", collect_submodules, "python_multipart")

# --- OCR --------------------------------------------------------------------
# The most failure-prone dependency: the ONNX models and YAML configs ship as
# package *data*, and onnxruntime's inference engine is a native library.
# Both are invisible to PyInstaller's import graph.
datas += optional("rapidocr data files", collect_data_files, "rapidocr_onnxruntime")
hiddenimports += optional("rapidocr submodules", collect_submodules, "rapidocr_onnxruntime")
binaries += optional("onnxruntime libraries", collect_dynamic_libs, "onnxruntime")

# --- Engine -----------------------------------------------------------------
# Detectors/adapters are resolved through registries, so pull the whole package
# in rather than relying on the static import graph. The Tesseract/Paddle OCR
# adapters are deliberately left out (see EXCLUDES): the registry in
# ocr/__init__.py registers adapters behind try/except ImportError, so the
# bundle degrades cleanly to the RapidOCR backend it actually ships.
hiddenimports += [
    m
    for m in collect_submodules("privacy_firewall")
    if not m.startswith(("privacy_firewall.ocr.adapters.tesseract", "privacy_firewall.ocr.adapters.paddle"))
]

# Heavyweight packages that are reachable from an OCR/ML dependency graph but
# that this app never uses. Without these, a developer machine with a rich
# site-packages produces a bundle hundreds of MB larger than CI's. Each entry
# was confirmed unnecessary by re-running packaging/smoke_test.py.
EXCLUDES = [
    # Dev tooling
    "pytest", "mypy", "ruff", "pre_commit", "IPython", "notebook",
    # GUI toolkit the app never uses (Studio is a browser UI)
    "tkinter",
    # Scientific stack pulled in transitively but unused by the RapidOCR path
    "scipy", "pandas", "sklearn", "matplotlib", "sympy",
    # Media/ML stacks that are not part of the redaction pipeline
    "imageio", "imageio_ffmpeg", "torch", "transformers", "tokenizers", "hf_xet",
    # Alternative OCR backends we do not ship (registry falls back to rapidocr)
    "tesserocr", "paddleocr", "paddle", "paddlepaddle",
    # Alternative PDF backends -- pypdfium2 is the one in use. PyMuPDF is a
    # test-only dependency (the independent verifier) and must never be bundled:
    # shipping it would re-attach the AGPL obligation this backend removed.
    "fitz", "pymupdf",
]

# --- Icon -------------------------------------------------------------------
if sys.platform == "win32":
    icon_path = HERE / "icon.ico"
elif sys.platform == "darwin":
    icon_path = HERE / "icon.icns"
else:
    icon_path = None
icon = str(icon_path) if icon_path and icon_path.exists() else None


a = Analysis(  # noqa: F821
    [str(HERE / "launcher.py")],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Console stays visible: run_studio prints the local URL here, and it is
    # where a "port already in use" failure becomes readable.
    console=True,
    disable_windowed_traceback=False,
    icon=icon,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name=f"{APP_NAME}.app",
        icon=icon,
        bundle_identifier="com.privacyfirewall.studio",
    )
