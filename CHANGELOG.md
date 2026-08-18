# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Hidden-surface PII scanning.** Detects PII stamped into document metadata
  (Title/Author/Subject/Keywords) and annotations/form-field values, and strips
  it on redaction. Verification re-scans these surfaces so a leak there fails the
  certificate.
- **Verifiable redaction (`--certificate`).** Re-parses the output, proves no
  redacted value survives on the page, in metadata, or in annotations, and emits
  a one-page audit certificate (input/output hashes, counts by type, PASS/FAIL)
  that contains no raw PII.
- **Batch redaction (`redact-batch`).** Redacts a whole folder in one run with a
  CSV/JSON summary and per-file verification.
- **GSTIN detector** with base-36 check-digit validation.
- **Password-protected (encrypted) PDFs** supported across the CLI and Studio;
  passwords are held in memory only and the redacted output is written
  unencrypted.
- **One-click desktop installers** for Windows, macOS, and Linux built by a CI
  matrix (PyInstaller + Inno Setup), bundling Python, the engine, and OCR.
- **Packaging metadata**: `readme`, `authors`, `keywords`, `classifiers`, and
  `[project.urls]`; module docstrings across the detector and model packages.

### Changed
- **Replaced PyMuPDF (AGPL) with PDFium via `pypdfium2` (BSD/Apache)** across the
  engine. PyMuPDF is retained as a *test-only* independent verifier and is
  excluded from packaged builds, so the distributable links no copyleft code.
- Renamed the repository to **`privacy-firewall`** (dropped "starter-kit").

### Fixed
- **Repeated-value redaction leak.** The Aadhaar, phone, account, IFSC, and UPI
  detectors de-duplicated by *value* across the whole document, so a value that
  appeared twice (e.g. an account number in the header and footer, or an Aadhaar
  written plainly and in canonical spaced form) was redacted only once and the
  second occurrence survived in the output. De-duplication is now location-aware:
  every on-page occurrence is detected and redacted.

### Security
- The redaction verifier now covers hidden surfaces (metadata/annotations) in
  addition to the page text layer, and fails loudly on any residual leak. See
  [`SECURITY.md`](SECURITY.md) for the full guarantees and known limitations.

## [0.1.0]

- Initial engine: PDF parsing, OCR (RapidOCR/Tesseract/PaddleOCR) with automatic
  pipeline selection, nine PII detectors with checksum/structural validation,
  context scoring, fusion, policy-driven decisions, destructive redaction, and
  the local Studio review UI.

[Unreleased]: https://github.com/SurajSongara/privacy-firewall/commits/main
[0.1.0]: https://github.com/SurajSongara/privacy-firewall/releases/tag/v0.1.0
