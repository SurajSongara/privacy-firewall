# Contributing to Privacy Firewall

Thanks for your interest in improving Privacy Firewall. This document covers how
to set up the project, the conventions the codebase follows, and how changes get
merged.

## Development setup

Python **3.12+** is required (the project also runs on 3.13/3.14).

```bash
git clone https://github.com/SurajSongara/privacy-firewall.git
cd privacy-firewall
pip install -e ".[dev,ui]"      # engine + tests + lint/type tooling + Studio UI
pre-commit install               # optional: run the checks on every commit
```

## The checks (all must pass)

```bash
pytest                      # full test suite
ruff check src/ tests/      # lint
ruff format src/ tests/     # format
mypy src/                   # strict type-checking
python -m benchmarks.precision   # precision/recall vs. the golden corpus
```

CI runs `ruff`, `mypy --strict`, and `pytest` on Python 3.12 and 3.13 for every
pull request; keep all three green.

## Architecture at a glance

The engine is a pipeline of pure stages that exchange **immutable Pydantic v2
models**. The CLI and web UI are thin wrappers with zero business logic.

```
PDFParser -> OCR (optional) -> HybridMerger -> Detectors -> Fusion
   -> RedactionPlanner -> PDFRenderer (new file) -> Verifier -> Certificate
```

See [`AGENTS.md`](AGENTS.md) for the full per-module reference and
[`CLAUDE.md`](CLAUDE.md) for a condensed map.

## Conventions

- **Deterministic before AI.** Regex + validators (checksums, structural rules)
  come first; any ML is optional and lower priority in fusion.
- **The engine has no framework dependencies.** Keep FastAPI/Typer out of
  `engine/`, `detectors/`, `models/`, `parsers/`, and `renderer/`.
- **Detectors are pure functions** `(Document) -> list[Detection]`, testable in
  isolation. Every `Detection` carries evidence (matched text, span, bbox) and a
  confidence score.
- **Never modify the original document.** The renderer always writes to a new
  path.
- **Type everything.** `mypy` runs in strict mode; public functions get
  docstrings (Google style).
- **Only synthetic data in tests and fixtures.** Never commit real PII. PyMuPDF
  (`fitz`) is a *test-only* dependency used to build fixtures and to
  independently verify redaction output — it is never shipped.

## Adding a detector

1. Subclass `BaseDetector` (`detectors/base.py`); implement `name` and `scan`.
2. Validate structurally (checksum where one exists) to keep precision high.
3. When the same value can appear more than once on a page, emit **every**
   occurrence — use `overlaps_taken()` (`detectors/utils.py`) to drop only a
   re-match of the same span, never a genuine repeat elsewhere.
4. Register it in `ALL_DETECTORS` (`detectors/__init__.py`) — the single source
   of truth used by the CLI, pipeline, and verifier.
5. Add unit tests under `tests/detectors/` covering true positives, the false
   positives you deliberately reject, and repeated-value handling.

## Pull requests

- Branch off `main` (or the current integration branch); never push to `main`.
- Keep each PR focused; describe the change and how you verified it.
- Make sure the full check suite passes locally before opening the PR.
- A maintainer reviews and merges — PRs are not self-merged.

Commit messages: a concise imperative subject line, then a body explaining the
*why* when it isn't obvious.
