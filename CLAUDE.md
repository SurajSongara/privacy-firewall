# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (editable, with dev extras)
pip install -e ".[dev]"

# Run the CLI (Typer app, entry point in src/privacy_firewall/__main__.py)
python -m privacy_firewall scan   TestFiles/sbi_statement.pdf
python -m privacy_firewall detect TestFiles/statement1-5.pdf --ocr
python -m privacy_firewall redact input.pdf out.pdf --values-only
python -m privacy_firewall redact input.pdf out.pdf --certificate  # verify + audit certificate
python -m privacy_firewall redact-batch ./folder --out ./redacted  # whole-folder redaction + summary
python -m privacy_firewall doctor  TestFiles/statement1-5.pdf     # combined diagnostics + layout + OCR recommendation
python -m privacy_firewall diagnostics <pdf>                       # DocumentAnalyzer only

# Tests (pytest is configured with pythonpath=["src"], testpaths=["tests"])
pytest                                                  # full suite
pytest tests/detectors/test_pan_detector.py -v          # single file
pytest tests/detectors/test_pan_detector.py::test_x -v  # single test
pytest --cov                                            # coverage (source = privacy_firewall)

# Lint / format / type-check
ruff check src/ tests/
ruff format src/ tests/
mypy src/                                               # strict mode, pydantic plugin enabled
```

Python `>=3.12` is required (project runs on 3.14). CLI script entry point is `privacy-firewall = "privacy_firewall.__main__:entry_point"`.

## Workflow rules

- Work on a feature branch off `dev` — never push directly to `main`.
- Every task ships as a PR; do **not** merge without explicit user approval.
- If a force push closes an existing PR, open a new one.

## Engine rules

- Deterministic before AI; regex beats LLM; LLM is optional.
- Engine has no framework dependencies — CLI is a thin wrapper around engine components (zero business logic in `cli/`).
- Detection, planning, and rendering are separated (see pipeline below).
- Every `Detection` carries evidence (matched text, span, bbox) and a confidence score.
- Never modify original documents — renderer writes to a new output path.

## Architecture

Pipeline (each stage returns immutable Pydantic v2 models):

```
PDFParser.parse()          → Document (Page[Block[...]])
OCRProvider.process()      → Document                          # optional
HybridMerger.merge()       → Document                          # IoU=0.5 dedup of native+OCR
DetectorRegistry.run_all() → DetectionResult                   # list[Detection] + per-detector timing
FusionEngine.fuse()        → FusionResult                      # overlap resolution by priority tier + confidence
RedactionPlanner.plan()    → RedactionPlan                     # list[Redaction] (REPLACE | BLACK_BAR | HIGHLIGHT)
PDFRenderer.render()       → new PDF file                      # destructive: apply_redactions() strips text/images
```

Central orchestrator: `engine/ocr_pipeline.py::get_merged_document()` decides between native / OCR-only / hybrid based on `DocumentAnalyzer` diagnostics (used by the `--auto` CLI flag).

Module map (see `AGENTS.md` for the full per-file reference — it is the source of truth for design details):

- `models/` — frozen Pydantic dataclasses: `BoundingBox`, `Span`, `TextBlock`/`ImageBlock`/`TableBlock`, `Detection`, `Document`. Universal vocabulary — every other module depends on it.
- `parsers/pdf_parser.py` — groups per-word `TextSpan`s from `get_text("words")` under blocks from `get_text("dict")`, both served by `parsers/pdfium_compat.py`.
- `parsers/pdfium_compat.py` — the PDFium-backed read API (page geometry, `get_text` in `text`/`words`/`dict`/`rawdict` shapes, image listing, rasterisation, search). Flips PDFium's bottom-left coordinates to the engine's top-left space **once**, using the *unrotated mediabox* height. Blocks follow the page's own text objects, matching what PyMuPDF derived from the content stream. Indexes characters by char index, never by position in `get_text_range()` — PDFium counts unmapped glyphs but omits them from that string.
- `renderer/pdfium_draw.py` — the PDFium write API: `PageWriter.insert_text`/`draw_rect`/`text_width`/`remove_text_in`/`clear_image_pixels`. `text_width` sums `FPDFFont_GetGlyphWidth` advances and matches `fitz.get_text_length` exactly.
- `ocr/` — `OCRProvider` ABC + `OCRProviderRegistry` singleton in `ocr/__init__.py` that auto-registers adapters at import time via try/except ImportError. Adapters: `TesseractOCRAdapter` (default), `PaddleOCRAdapter`, plus `rapid.py` and additional `tesseract.py` variants under `adapters/`.
- `detectors/` — `BaseDetector` ABC + `DetectorRegistry`. Each detector: `PAN`, `Aadhaar`, `Email`, `Phone`, `UPI`, `IFSC`, `Account`, `Name`, `GSTIN`. `ALL_DETECTORS` + `build_registry()` in `detectors/__init__.py` are the single source of truth for the detector set (used by CLI, pipeline, and verifier). Deduplication helpers in `detectors/utils.py` (`is_exact_duplicate`, `is_containment_duplicate`). Detectors are pure: `(Document) → list[Detection]`; testable in isolation.
- `engine/fusion.py` — priority tiers `regex=5 > validator=4 > heuristic=3 > ner=2 > llm=1`; groups by `(page, detection_type)`, sorts by `(span.start, -priority, -confidence)`, merges overlapping neighbours.
- `engine/redaction.py` — `RedactionType.{REPLACE, BLACK_BAR, HIGHLIGHT}`. REPLACE/BLACK_BAR use `page.add_redact_annot()` + `page.apply_redactions()` (physically strips from the content stream); HIGHLIGHT is a visual overlay only.
- `engine/redact.py` — `detect_document()` / `redact_document()`: the detect→redact pipeline in one place, reused by `redact` and `redact-batch` (CLI stays a thin wrapper).
- `engine/hidden_pii.py` — `scan_hidden_pii()`: runs the detector registry over the surfaces plain text extraction misses — the Info-dict metadata (Title/Author/Subject/Keywords), annotations (comments/notes), and form-field (widget) values — via synthetic one-block documents, returning `HiddenFinding`s. `detect` reports them; redaction removes them wholesale (`PdfiumDocument.sanitize()` + the fresh-doc copy in `save()` drops metadata), so the shareable output carries none. `pdfium_compat` exposes `PdfiumDocument.metadata()` and `PdfiumPage.annotations()`.
- `engine/verification.py` — post-redaction proof: re-parses the output, asserts no redacted value is still extractable and no detector re-fires, **and re-scans the output's metadata/annotations so a leak there fails the certificate** (`VerificationResult.hidden_leaks`). Emits a `Certificate` (JSON + one-page PDF, no raw PII). `--certificate` on `redact`/`redact-batch`.
- `parsers/pdf_open.py` — `open_pdf()` / `decrypted_bytes()` / `EncryptedPDFError`: single choke-point for opening (and authenticating) PDFs. Every consumer (parser, OCR, renderer, page images, diagnostics, UI session) opens through it. On successful auth it round-trips through decrypted bytes so downstream sees a reliably-unlocked doc (PDFium reports a locked file and a corrupt file through the same exception, so the message is the discriminator). `--password` is wired through the CLI; Studio surfaces a `needs_password` status and a `POST /api/unlock` endpoint (in-memory only). Redacted output of an encrypted source is written unencrypted.
- `engine/hybrid_merger.py` — merges native + OCR `Document`s, preferring native and adding OCR blocks whose bbox has IoU ≤ 0.5 with any native block.
- `diagnostics/` — `DocumentAnalyzer` produces a `DiagnosticReport` with a weighted `TextQualityReport` (printable ratio 0.30, replacement chars 0.20, fragmentation 0.15, long tokens 0.20, whitespace 0.15) and a `PipelineSelector` decision (NATIVE / OCR / HYBRID).
- `layout/analyzer.py` — classifies blocks into HEADER/FOOTER/PAGE_NUMBER/paragraphs by page position + vertical gap threshold.
- `bank_profiler/` — per-bank profilers (SBI, HDFC, ICICI, Axis, Generic) matched by IFSC prefix + account-number regex; registry returns highest-confidence match.
- `cli/` — one file per subcommand (`scan_cmd`, `detect_cmd`, `redact_cmd`, `diagnostics_cmd`, `doctor_cmd`); wired in `__main__.py`. `_safe()` helper sanitises Unicode for the Windows cp1252 console.

## Common flags

- `--ocr` / `--auto` / `--ocr-engine <name>` on `scan`/`detect`/`redact` — force OCR, let the diagnostics recommend, or pick a specific engine from the OCR registry.
- `--values-only` (redact) — redact only the PII value while keeping surrounding labels.
- `--type replace|black-bar|highlight` (redact) — redaction visual mode.
- `--detector <name>` / `--no-fuse` (detect) — filter to one detector or skip fusion.

## Notes for future sessions

- `AGENTS.md` is a hand-maintained deep-dive reference generated from the source; consult it before changing architecture but assume drift is possible — verify against code.
- Known false positives on synthetic corpora: the Aadhaar (Verhoeff + first-digit) and Email (TLD allowlist) FP classes are fixed; the remaining known one is Phone catching 10-digit UTR/bank refs (~75% precision on adversarial inputs).
- Default OCR engine is resolved deterministically in `ocr/__init__.py`: the `PRIVACY_FIREWALL_OCR_ENGINE` env var wins, else preference order `rapidocr > tesseract > paddleocr`, skipping engines whose `is_available()` backend check fails. `paddlepaddle` has no wheel for Python 3.14, so `paddleocr` registers but reports unavailable. The `ocr-lite` extra installs `rapidocr-onnxruntime` (pure wheels, models bundled) — the recommended backend for packaged builds.
