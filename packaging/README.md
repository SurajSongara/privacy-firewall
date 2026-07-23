# Packaging — desktop installers

Builds Privacy Firewall into a double-click desktop app so users never need
Python or a terminal. The `pip install` path is unaffected by anything here.

| Platform | Artifact | Packager |
|---|---|---|
| Windows | `PrivacyFirewall-Setup-<version>.exe` | [Inno Setup 6](https://jrsoftware.org/isdl.php) |
| macOS | `PrivacyFirewall-<version>.dmg` | `hdiutil` |
| Linux | `PrivacyFirewall-<version>-linux-x86_64.tar.gz` | `tar` |

**There is no universal binary.** PyInstaller cannot cross-compile, so each
artifact must be built *on* its own OS. `.github/workflows/build-installers.yml`
does this with a three-OS matrix; pushing a `v*` tag also attaches the artifacts
to a **draft** GitHub Release for a human to review and publish.

## Files

| File | Purpose |
|---|---|
| `privacy_firewall.spec` | PyInstaller recipe — one spec, all three OSes |
| `launcher.py` | Frozen entry point (Studio on double-click, CLI with args) |
| `smoke_test.py` | Drives the built binary against synthetic documents |
| `make_icons.py` | Regenerates `icon.{png,ico,icns}` (only when the design changes) |
| `windows/installer.iss` | Inno Setup script |
| `SOURCE_OFFER.txt` | AGPL source-availability notice shipped with every build |

## Building locally

```bash
pip install ".[ui,ocr-lite,docx]" pyinstaller
pyinstaller --clean --noconfirm packaging/privacy_firewall.spec
```

The bundle lands in `dist/PrivacyFirewall/`. Smoke-test it before packaging:

```bash
# Windows
python packaging/smoke_test.py dist/PrivacyFirewall/PrivacyFirewall.exe
# macOS / Linux
python packaging/smoke_test.py dist/PrivacyFirewall/PrivacyFirewall
```

Then wrap it:

```bash
# Windows (Inno Setup on PATH)
iscc /DAppVersion=0.1.0 packaging\windows\installer.iss

# macOS
hdiutil create -volname "Privacy Firewall" -srcfolder dist/PrivacyFirewall.app \
  -ov -format UDZO dist/installer/PrivacyFirewall-0.1.0.dmg

# Linux
tar -czf dist/installer/PrivacyFirewall-0.1.0-linux-x86_64.tar.gz -C dist PrivacyFirewall
```

## Design notes

**onedir, not onefile.** onefile unpacks to a temp directory on every launch,
which is slow with a bundle this size and is a well-known trigger for Windows
antivirus false positives. The installer hides the folder from the user anyway.

**The console window stays.** `run_studio()` prints the local URL to stdout and
raises `SystemExit` with a readable message when the port is taken. Building
`--windowed` would hide both, leaving a user with a silent no-op. A tray icon
with a Stop item is the eventual fix; until then the console *is* the UI for
"it's running, here's the address".

**Double-click workspace.** A double-launched app inherits a useless working
directory (often `C:\Windows\System32`), so `launcher.py` defaults the workspace
to `~/Documents/PrivacyFirewall` and creates it on first run. Passing any
argument bypasses this and runs the normal Typer CLI.

### Bundling gotchas the spec handles

These all fail *silently at build time* and only surface at runtime:

- **`copy_metadata("privacy-firewall")`** — `__main__.py` resolves `--version`
  through `importlib.metadata`. Frozen bundles drop `dist-info`, so without this
  `--version` raises `PackageNotFoundError`.
- **`collect_submodules("uvicorn")`** — uvicorn lazy-imports its loop, protocol
  and lifespan backends; nothing in the import graph references them.
- **`collect_data_files("rapidocr_onnxruntime")` + `collect_dynamic_libs("onnxruntime")`**
  — the OCR models/configs are package *data* and the inference engine is a
  native library. This is the most fragile part of the build, which is why
  `smoke_test.py` forces an actual `--ocr` run.
- **`collect_submodules("privacy_firewall")`** — detectors and OCR adapters are
  resolved through registries at runtime, not by static import.

No UI templates are collected: the Studio and review HTML/JS are Python string
constants in `src/privacy_firewall/ui/html.py`.

### Bundle size

A verified Windows build was **~314 MB** on disk (roughly 120 MB compressed into
the installer) with the PyMuPDF backend. Swapping to pypdfium2 removes ~30 MB;
re-measure on the next CI build and update this figure. The `EXCLUDES` list in the spec is what keeps it there: without
it, a developer machine with a rich `site-packages` produced **587 MB** by
dragging in SciPy, pandas, scikit-learn and `imageio_ffmpeg` through the OCR
dependency graph. Every exclusion was validated by re-running `smoke_test.py`.

Remaining large components, and why they stay:

| Component | Size | Why |
|---|---|---|
| `cv2` | 137 MB | OpenCV, required by RapidOCR |
| `pypdfium2` | 8 MB | The PDF engine (was `pymupdf`, 38 MB) |
| `onnxruntime` | 34 MB | OCR inference |
| `numpy.libs` + `numpy` | 28 MB | Required by OpenCV/RapidOCR |

**Known further optimisation (untested):** RapidOCR depends on `opencv-python`,
but only uses array operations — never the GUI functions. Forcing
`opencv-python-headless` in its place should cut roughly 40 MB. Try it by
installing the headless variant after the project install, then re-run
`smoke_test.py`; if OCR still passes, the saving is free.

## Licensing

**No copyleft component is bundled.** The PDF engine is PDFium (BSD-3-Clause)
via pypdfium2; Pillow is MIT-CMU; RapidOCR/ONNX Runtime are Apache-2.0; the web
stack is MIT/BSD. Privacy Firewall's own source is AGPL-3.0 by choice, not by
obligation inherited from a dependency — so relicensing under permissive terms
(or shipping proprietary builds) is a decision the maintainers can now make
freely.

`PyMuPDF is a test-only dependency` and is listed in the spec's `EXCLUDES`:
bundling it would re-attach the AGPL obligation this backend removed. If you
change the spec, keep that exclusion.

`LICENSE` and `SOURCE_OFFER.txt` are still installed alongside the app on all
three platforms, and Inno Setup shows the licence during installation. If you
fork or rebrand this, keep both files.

## Code signing

CI builds **unsigned**. Consequences:

- **Windows** — SmartScreen shows "unrecognised app" until the installer earns
  reputation or is signed with an OV/EV certificate.
- **macOS** — Gatekeeper blocks the app; users must right-click → Open. Proper
  distribution needs an Apple Developer account (~$99/yr) for signing plus
  notarization.

Signing is deliberately left as a later, secrets-gated addition so the pipeline
works today without credentials.
