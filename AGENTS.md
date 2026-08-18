# Privacy Firewall — Complete Design & Implementation Reference

> Single-source context file for any AI agent or chat session working on this codebase.
> Generated from the actual source code. Last updated: 2026-07-06.

---

## 1. Project Identity

| Field | Value |
|-------|-------|
| **Name** | `privacy-firewall` |
| **Version** | `0.1.0` |
| **Python** | `>=3.12` (running on 3.14.3) |
| **Description** | Offline-first PII Detection & Redaction Engine for PDF documents |
| **Entry Point** | `privacy-firewall = "privacy_firewall.__main__:entry_point"` |
| **Source Layout** | `src/privacy_firewall/` (PEP 621 src-layout) |
| **License** | Not specified |

### Core Dependencies
```
pydantic>=2        — Frozen data models
pypdfium2>=5       — PDF parsing, rendering, destructive redaction (PDFium)
pillow>=10         — Raster decode/encode for page images and scans
typer>=0.12        — CLI framework
```

### Optional Dependencies
```
[ocr]
paddleocr>=2.8     — PaddleOCR engine (requires paddlepaddle)

[dev]
pytest>=8, pytest-cov>=5, ruff>=0.6, mypy>=1.11, pre-commit>=3.8
```

### Runtime Dependencies (installed manually)
```
tesserocr          — Tesseract OCR Python bindings (pre-built wheel for Py3.14)
Pillow             — Image handling for Tesseract adapter
```

---

## 2. Architecture Overview

```
PDF IN
  │
  ├─ Native text ──┐
  │                 ├─▶ Document ──▶ Detectors ──▶ Fusion ──▶ Plan ──▶ Redacted PDF OUT
  └─ OCR text ─────┘
```

### Pipeline Modes
1. **Native** — PDFium extracts text directly from PDF content stream
2. **OCR** — Render pages to images, run Tesseract/PaddleOCR
3. **Hybrid** — Native + OCR merged (IoU deduplication)

### Data Flow
```
PDFParser.parse()          → Document (pages with TextBlock/ImageBlock)
OCRProvider.process()      → Document (OCR-extracted blocks)
HybridMerger.merge()       → Document (deduplicated native+OCR)
DetectorRegistry.run_all() → DetectionResult (list[Detection])
FusionEngine.fuse()        → FusionResult (deduplicated overlapping detections)
RedactionPlanner.plan()    → RedactionPlan (list[Redaction])
PDFRenderer.render()       → Redacted PDF file
```

---

## 3. Directory Structure

```
src/privacy_firewall/
├── __init__.py                 — Package init (empty)
├── __main__.py                 — CLI entry point (Typer app)
├── models/
│   ├── geometry.py             — BoundingBox, Span
│   ├── blocks.py               — Block, TextBlock, TextSpan, ImageBlock, TableBlock
│   ├── detection.py            — Detection
│   └── document.py             — Page, Document
├── parsers/
│   ├── pdf_parser.py           — PDFParser (PDFium via pdfium_compat)
│   └── pdfium_compat.py        — PDFium read API + coordinate flip
├── ocr/
│   ├── __init__.py             — Registry singleton, auto-registration
│   ├── provider.py             — OCRProvider ABC
│   ├── registry.py             — OCRProviderRegistry
│   └── adapters/
│       ├── __init__.py         — Exports both adapters
│       ├── tesseract.py        — TesseractOCRAdapter (tesserocr + PDFium)
│       └── paddle.py           — PaddleOCRAdapter (paddleocr + PDFium)
├── detectors/
│   ├── __init__.py             — Exports all detectors + registry
│   ├── base.py                 — BaseDetector ABC
│   ├── registry.py             — DetectorRegistry
│   ├── result.py               — DetectionResult, DetectorRun, timed_scan
│   ├── utils.py                — is_exact_duplicate, is_containment_duplicate
│   ├── pan_detector.py         — PANDetector
│   ├── aadhaar_detector.py     — AadhaarDetector
│   ├── email_detector.py       — EmailDetector
│   ├── phone_detector.py       — PhoneDetector
│   ├── upi_detector.py         — UpiDetector
│   └── regex_detector.py       — RegexDetector (generic)
├── engine/
│   ├── __init__.py             — Exports engine components
│   ├── fusion.py               — FusionEngine, priority tiers
│   ├── redaction.py            — RedactionPlanner, RedactionType
│   ├── hybrid_merger.py        — HybridMerger, BlockProvenance
│   └── ocr_pipeline.py         — get_merged_document (orchestrator)
├── renderer/
│   └── pdf_renderer.py         — PDFRenderer (destructive redaction)
├── diagnostics/
│   ├── __init__.py             — Exports diagnostics components
│   ├── models.py               — PipelineType, TextQualityReport, DiagnosticReport
│   ├── text_quality.py         — TextQualityAnalyzer
│   ├── pipeline_selector.py    — PipelineSelector
│   └── analyzer.py             — DocumentAnalyzer
├── layout/
│   ├── __init__.py             — Exports layout components
│   ├── models.py               — LayoutElementType, LayoutElement, LayoutAnalysis
│   └── analyzer.py             — LayoutAnalyzer
├── bank_profiler/
│   ├── __init__.py             — Exports profiler components
│   ├── models.py               — BankName, BankProfile, shared regex
│   ├── provider.py             — BankProfiler ABC
│   ├── registry.py             — BankProfilerRegistry
│   ├── _helpers.py             — extract_all_text, find_ifsc, find_account_number, etc.
│   └── adapters/
│       ├── __init__.py         — Exports all profilers
│       ├── _base_profiler.py   — _BaseBankProfiler
│       ├── _patterns.py        — Bank-specific regex patterns
│       ├── sbi.py              — SBIProfiler
│       ├── hdfc.py             — HDFCProfiler
│       ├── icici.py            — ICICIProfiler
│       ├── axis.py             — AxisProfiler
│       └── generic.py          — GenericProfiler
└── cli/
    ├── __init__.py             — Exports CLI commands
    ├── scan_cmd.py             — `scan` command
    ├── detect_cmd.py           — `detect` command
    ├── redact_cmd.py           — `redact` command
    ├── diagnostics_cmd.py      — `diagnostics` command
    └── doctor_cmd.py           — `doctor` command
```

---

## 4. Models Layer (`models/`)

All models use `ConfigDict(frozen=True)` — immutable Pydantic v2 dataclasses.

### BoundingBox (`models/geometry.py:12`)
```python
class BoundingBox(BaseModel):
    x0: float  # left
    y0: float  # top
    x1: float  # right (validated: x1 > x0)
    y1: float  # bottom (validated: y1 > y0)
```

### Span (`models/geometry.py:45`)
```python
class Span(BaseModel):
    start: int  # 0-based, validated >= 0
    end: int    # exclusive, validated > start
```

### Block Types (`models/blocks.py`)
```
Block (base)
├── TextBlock    — text: str, spans: list[TextSpan]
├── ImageBlock   — image_data: bytes | None, mime_type: str | None
└── TableBlock   — rows: list[list[str]]
```

**TextBlock.bbox_for_span(start, end)** — Computes union bounding box for a character range by walking per-word TextSpan geometry. Returns block bbox if no spans available.

### Detection (`models/detection.py`)
```python
class Detection(BaseModel):
    detector_name: str     # e.g. "pan", "aadhaar"
    detection_type: str    # e.g. "PAN", "AADHAAR"
    text: str              # matched text
    span: Span             # character offsets
    bbox: BoundingBox      # region on page
    page_number: int       # 1-based
    confidence: float      # 0.0–1.0
```

### Document (`models/document.py`)
```
Document
└── pages: list[Page]
     └── Page
          ├── page_number: int
          ├── width: float
          ├── height: float
          └── blocks: list[Block]
```

---

## 5. PDF Parser (`parsers/pdf_parser.py`)

```python
class PDFParser:
    def __init__(self, file_path: str | Path)
    def parse() -> Document
    @staticmethod
    def parse_bytes(data: bytes) -> Document
```

**Strategy:**
- Uses `open_pdf()` (PDFium via `pdfium_compat`)
- `page.get_text("dict")` for block-level structure
- `page.get_text("words")` for per-word bounding boxes
- Groups words by `block_no` → creates `TextSpan` per word
- Image blocks extracted from type==1 blocks

---

## 6. OCR Layer (`ocr/`)

### OCRProvider ABC (`ocr/provider.py`)
```python
class OCRProvider(ABC):
    name: str = ""  # Must be non-empty (enforced by __init_subclass__)

    @abstractmethod
    def process(self, path: str | Path) -> Document: ...

    @abstractmethod
    def process_bytes(self, data: bytes) -> Document: ...
```

### OCRProviderRegistry (`ocr/registry.py`)
```python
class OCRProviderRegistry:
    def register(self, provider: type[OCRProvider], *, default: bool = False)
    def get(self, name: str) -> type[OCRProvider] | None
    def get_default(self) -> type[OCRProvider] | None
    @property
    def names(self) -> list[str]
```

### Auto-Registration (`ocr/__init__.py`)
```python
_registry = OCRProviderRegistry()  # Module-level singleton

def _register_builtins():
    try: _registry.register(TesseractOCRAdapter, default=True)
    except ImportError: pass
    try: _registry.register(PaddleOCRAdapter)
    except ImportError: pass
```

### TesseractOCRAdapter (`ocr/adapters/tesseract.py`)
```python
class TesseractOCRAdapter(OCRProvider):
    name = "tesseract"

    def __init__(self, dpi=200, lang="eng", tessdata_path=None)
    # Uses tesserocr.PyTessBaseAPI + PDFium for PDF→image→OCR
    # DPI 200 default, coordinate scaling: pixel / (dpi/72.0)
    # Confidence normalized from 0-100 to 0-1
```

**Key implementation details:**
- `open_pdf()` → `page.get_pixmap(dpi=…)` (PDFium shim in `pdfium_compat`) → PIL image → `engine.SetImage()` → `engine.Recognize()`
- `engine.GetIterator()` → `GetUTF8Text(RIL.TEXTLINE)` per line
- `BoundingBox()` returns `(x1, y1, x2, y2)` in pixel coords
- Scale factor: `dpi / 72.0` (PDF points vs pixels)
- Clamped to page boundaries

### PaddleOCRAdapter (`ocr/adapters/paddle.py`)
```python
class PaddleOCRAdapter(OCRProvider):
    name = "paddleocr"

    def __init__(self, dpi=200, lang="en", use_angle_cls=True)
    # Uses paddleocr.PaddleOCR + PDFium
    # Returns bounding quadrilaterals → axis-aligned BoundingBox
```

**Key implementation details:**
- `engine.ocr(img_bytes)` returns `[[bbox_quad, (text, confidence)], ...]`
- Quadrilateral → `min(xs)/scale, min(ys)/scale, max(xs)/scale, max(ys)/scale`

---

## 7. Detectors Layer (`detectors/`)

### BaseDetector ABC (`detectors/base.py`)
```python
class BaseDetector(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def scan(self, document: Document, *, values_only: bool = False) -> list[Detection]: ...
```

### DetectorRegistry (`detectors/registry.py`)
```python
class DetectorRegistry:
    def register(self, detector: BaseDetector)
    def run_all(self, document, *, values_only=False) -> DetectionResult
    def run(self, document, name) -> DetectionResult | None
```

### DetectionResult (`detectors/result.py`)
```python
@dataclass
class DetectionResult:
    detections: list[Detection]
    runs: list[DetectorRun]

    def merge(self, other: DetectionResult)
    @property
    def total_detections(self) -> int
```

### Concrete Detectors

| Detector | File | `name` | `detection_type` | Pattern | Confidence |
|----------|------|--------|-------------------|---------|------------|
| `PANDetector` | `pan_detector.py` | `"pan"` | `"PAN"` | `[A-Z]{5}[0-9]{4}[A-Z]` + status code validation | 0.95 |
| `AadhaarDetector` | `aadhaar_detector.py` | `"aadhaar"` | `"AADHAAR"` | `\d{12}` (continuous) + `\d{4}[\s-]?\d{4}[\s-]?\d{4}` (formatted) | 0.95 |
| `EmailDetector` | `email_detector.py` | `"email"` | `"EMAIL"` | RFC 5322 simplified | 0.9 |
| `PhoneDetector` | `phone_detector.py` | `"phone"` | `"PHONE"` | 6 patterns (intl, national, formatted) | 0.7–0.9 |
| `UpiDetector` | `upi_detector.py` | `"upi"` | `"UPI"` | `[local@handle]` | 0.7 or 0.95 (known handle) |

### Shared Utilities (`detectors/utils.py`)
- `is_exact_duplicate(detections, text)` — exact text match
- `is_containment_duplicate(detections, normalized)` — digits-only containment (handles `+91-` variants)

---

## 8. Engine Layer (`engine/`)

### FusionEngine (`engine/fusion.py`)
```python
PRIORITY_TIERS = {"regex": 5, "validator": 4, "heuristic": 3, "ner": 2, "llm": 1}
DETECTOR_TIERS = {"pan": "regex", "aadhaar": "regex", "email": "regex", "phone": "regex", "upi": "regex"}

class FusionEngine:
    def fuse(self, detections: list[Detection]) -> FusionResult
```

**Strategy:**
1. Group detections by `(page_number, detection_type)`
2. Sort each group by `(span.start, -priority, -confidence)`
3. Merge overlapping neighbors: higher priority wins, ties broken by confidence
4. Log every merge as `MergeRecord`

### RedactionPlanner (`engine/redaction.py`)
```python
class RedactionType(Enum):
    REPLACE = "replace"      # [REDACTED] placeholder
    BLACK_BAR = "black_bar"  # Solid black overlay
    HIGHLIGHT = "highlight"  # Yellow highlight (visual only)

class RedactionPlanner:
    def plan(self, document, detections, *, default_type) -> RedactionPlan
    @staticmethod
    def plan_with_replacement(...) -> RedactionPlan
    @staticmethod
    def plan_with_black_bar(...) -> RedactionPlan
    @staticmethod
    def plan_with_highlight(...) -> RedactionPlan
```

### HybridMerger (`engine/hybrid_merger.py`)
```python
class HybridMerger:
    OVERLAP_THRESHOLD = 0.5  # IoU ratio

    @classmethod
    def merge(cls, native: Document, ocr: Document) -> MergeResult
```

**Strategy per page:**
1. Keep all native blocks (provenance = NATIVE)
2. Add OCR blocks whose bbox doesn't significantly overlap native (IoU ≤ 0.5)
3. Native blocks ordered first, then OCR fill-ins

### OCR Pipeline Orchestrator (`engine/ocr_pipeline.py`)
```python
def get_merged_document(
    pdf_path: Path,
    *,
    force_ocr: bool = False,
    auto: bool = False,
    native_doc: Document | None = None,
    ocr_provider: str | None = None,
) -> tuple[Document, str]:  # Returns (document, "native"|"ocr"|"hybrid")
```

**Decision logic:**
1. Parse native if not provided
2. If no OCR requested → return native
3. If auto → run DocumentAnalyzer diagnostics → if recommended=NATIVE → return native
4. Run OCR
5. If native has no text → return OCR-only
6. Else → hybrid merge

---

## 9. Renderer Layer (`renderer/`)

### PDFRenderer (`renderer/pdf_renderer.py`)
```python
class PDFRenderer:
    BLACK_BAR_COLOR = (0.0, 0.0, 0.0)    # RGB black
    HIGHLIGHT_COLOR = (1.0, 1.0, 0.0)    # RGB yellow
    HIGHLIGHT_OPACITY = 0.3

    def render(self, input_path, output_path, plan) -> Path
    @staticmethod
    def render_bytes(data: bytes, plan) -> bytes
```

**Redaction strategy:**
- `REPLACE` / `BLACK_BAR`: `page.add_redact_annot()` + `page.apply_redactions()` — **physically strips** text/images from content stream
- `HIGHLIGHT`: `page.draw_rect()` — visual overlay only (no content removal)

---

## 10. Diagnostics Layer (`diagnostics/`)

### DocumentAnalyzer (`diagnostics/analyzer.py`)
```python
class DocumentAnalyzer:
    def __init__(self, pdf_path: Path)
    def analyze(self) -> DiagnosticReport
```

**Produces:** `DiagnosticReport` with:
- `page_count`, `image_count`, `has_native_text`, `is_encrypted`, `rotated_pages`
- `estimated_scanned: bool`
- `text_quality_report: TextQualityReport`
- `recommended_pipeline: PipelineType` (NATIVE | OCR | HYBRID)

### TextQualityAnalyzer (`diagnostics/text_quality.py`)
Weighted heuristics (total score 0.0–1.0):
- Printable ratio (0.30)
- Replacement char penalty (0.20)
- Fragmentation/short words (0.15)
- Long token penalty (0.20)
- Whitespace ratio (0.15)

### PipelineSelector (`diagnostics/pipeline_selector.py`)
Decision tree:
- Encrypted/empty → OCR
- Scanned → OCR
- No text → OCR
- Low quality (<0.3) → OCR
- Medium quality (<0.7) → Hybrid
- Else → Native

---

## 11. Layout Layer (`layout/`)

### LayoutAnalyzer (`layout/analyzer.py`)
```python
class LayoutAnalyzer:
    def analyze(self, document: Document) -> list[LayoutAnalysis]
```

**Classification:**
- Top 10% → HEADER
- Bottom 10% → FOOTER / PAGE_NUMBER
- Tables/Images → direct mapping
- Remaining text → merged into paragraphs (15pt vertical gap threshold)
- Reading order: top-to-bottom, left-to-right

---

## 12. Bank Profiler (`bank_profiler/`)

### BankProfiler ABC
```python
class BankProfiler(ABC):
    name: str
    def profile(self, document: Document) -> BankProfile
```

### Concrete Profilers

| Bank | IFSC Prefixes | Account Pattern | Name Aliases |
|------|---------------|-----------------|--------------|
| SBI | `SBIN` | 11 or 15 digits | `sbi`, `state bank` |
| HDFC | `HDFC` | 14 digits | `hdfc` |
| ICICI | `ICIC` | 12 or 15 digits | `icici` |
| Axis | `UTIB`, `AXIS` | 15 digits | `axis` |
| Generic | — | — | Fallback |

### BankProfilerRegistry
```python
class BankProfilerRegistry:
    def profile(self, document: Document) -> BankProfile
    # Runs all profilers, returns highest confidence match
```

---

## 13. CLI Commands (`cli/`)

All commands are thin wrappers — zero business logic. Each delegates to engine components.

### `scan <pdf> [--ocr] [--auto] [--ocr-engine]`
- Parses PDF (native/OCR/hybrid)
- Displays page structure with text previews and image sizes
- `_safe()` helper sanitizes Unicode for Windows cp1252 console

### `detect <pdf> [--detector] [--no-fuse] [--values-only] [--ocr] [--auto] [--ocr-engine]`
- Runs PII detectors (all or filtered by `--detector`)
- Fuses results (unless `--no-fuse`)
- Displays detections with type/text/confidence

### `redact <in> <out> [--type] [--detector] [--values-only] [--ocr] [--auto] [--ocr-engine]`
- Full pipeline: parse → detect → fuse → plan → render
- `--type`: replace (default), black-bar, highlight

### `diagnostics <pdf>`
- Runs DocumentAnalyzer
- Displays page/image counts, text quality breakdown, recommended pipeline

### `doctor <pdf>`
- Combines diagnostics + text quality + OCR recommendation + layout analysis

### `--ocr-engine` flag
- Available engines listed dynamically from OCR registry
- Defaults to Tesseract if available

---

## 14. CLI Entry Point (`__main__.py`)

```python
app = typer.Typer(name="privacy-firewall", help="Offline-first PII Detection & Redaction Engine")

app.command(name="scan")(scan_cmd)
app.command(name="detect")(detect_cmd)
app.command(name="redact")(redact_cmd)
app.command(name="diagnostics")(diagnostics_cmd)
app.command(name="doctor")(doctor_cmd)

def entry_point():
    app()
```

---

## 15. Test Suite

```
tests/
├── models/          — test_blocks, test_detection, test_document, test_geometry
├── parsers/         — test_pdf_parser
├── detectors/       — test_pan, test_aadhaar, test_email, test_phone, test_upi, test_regex, test_base, test_registry, test_result
├── engine/          — test_fusion, test_redaction, test_hybrid_merger, test_ocr_pipeline
├── renderer/        — test_pdf_renderer
├── ocr/             — test_provider, adapters/test_paddle
├── diagnostics/     — test_analyzer, test_text_quality, test_pipeline_selector
├── layout/          — test_analyzer
├── bank_profiler/   — test_helpers, test_models, test_profilers
├── benchmarks/      — test_regression
└── test_cli.py
```

**Run tests:** `pytest` (uses `pythonpath = ["src"]`)
**Lint:** `ruff check src/ tests/`
**Type check:** `mypy src/`

---

## 16. Known Issues & Technical Debt

### PaddleOCR (P0)
- `paddlepaddle` has no wheel for Python 3.14 → `PaddleOCR()` init fails
- **Workaround:** Tesseract is fully functional as default engine

### False Positives on `statement1-5.pdf`
- Aadhaar detector catches 12-digit UPI txn refs (`/DR/387696619190/`)
- Phone detector catches 10-digit bank refs (`/CNRB/9179083184/`)
- Email detector catches OCR artifacts (`30524@sbi.coin`)
- **Fix needed:** Verhoeff checksum for Aadhaar, structural filtering for phone/Aadhaar in refs

### OCR Adapter Complexity
- Current `OCRProvider` ABC requires adapters to handle PDF→image conversion, coordinate transforms, and Document model wrapping
- **Proposed:** `SimpleOCRProvider` base class that handles boilerplate, subclasses only implement `ocr_image(image) -> list[OcrResult]`

### Unicode on Windows
- `codegraphcontext config show` crashes with UnicodeEncodeError on cp1252
- `_safe()` helper in CLI sanitizes output

### Test Count
- 723 tests, all passing (`pytest`); strict `mypy` and `ruff` clean

---

## 17. Key Integration Points

1. **`engine/ocr_pipeline.py`** — Central orchestrator connecting parsers, diagnostics, OCR, and hybrid merger
2. **`cli/*_cmd.py`** — Commands compose: `parsers` + `ocr` + `detectors` + `engine` + `renderer`
3. **`models/`** — Universal vocabulary — every module depends on it
4. **`detectors/`** — Pure: read `Document`, produce `Detection` list (independently testable)
5. **`ocr/__init__.py`** — Singleton registry, auto-registers adapters at import time

---

## 18. Configuration Files

| File | Purpose |
|------|---------|
| `pyproject.toml` | Package config, dependencies, tools |
| `C:\Users\suraj\.config\opencode\opencode.jsonc` | opencode MCP servers (playwright, overleaf, codegraphcontext) |
| `C:\Users\suraj\.codegraphcontext\.env` | CGC config (ladybugdb backend) |
| `.cgcignore` | Files excluded from CGC indexing |

---

## 19. Development Commands

```bash
# Run CLI
privacy-firewall scan TestFiles/sbi_statement.pdf
privacy-firewall detect TestFiles/statement1-5.pdf --ocr
privacy-firewall redact TestFiles/statement1-5.pdf out.pdf --ocr

# Test
pytest
pytest tests/detectors/test_pan_detector.py -v

# Lint
ruff check src/ tests/
ruff format src/ tests/

# Type check
mypy src/

# Index for CodeGraphContext
codegraphcontext index .
codegraphcontext list
```
