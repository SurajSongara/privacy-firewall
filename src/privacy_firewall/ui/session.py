"""Review session: engine orchestration behind the review UI.

Pure engine code — no web-framework imports — so the session is fully
testable without the ``ui`` extra installed.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from privacy_firewall.detectors import (
    AadhaarDetector,
    AccountDetector,
    DetectorRegistry,
    EmailDetector,
    IFSCDetector,
    NameDetector,
    PANDetector,
    PhoneDetector,
    UpiDetector,
)
from privacy_firewall.engine.context import ContextScorer
from privacy_firewall.engine.decision import (
    DecisionEngine,
    ReviewDecision,
    ReviewEntry,
    ReviewPlan,
    SuggestedAction,
    file_sha256,
)
from privacy_firewall.engine.fusion import FusionEngine
from privacy_firewall.engine.ocr_pipeline import get_merged_document, get_pipeline_summary
from privacy_firewall.engine.redaction import RedactionPlanner, RedactionType
from privacy_firewall.models.blocks import TextBlock
from privacy_firewall.models.detection import Detection
from privacy_firewall.models.document import Document
from privacy_firewall.models.geometry import BoundingBox, Span
from privacy_firewall.parsers.pdf_open import EncryptedPDFError, decrypted_bytes, open_pdf
from privacy_firewall.policy.models import Policy, PolicyAction
from privacy_firewall.renderer.page_images import (
    DEFAULT_DPI,
    render_page_image,
    render_page_image_bytes,
)
from privacy_firewall.renderer.pdf_renderer import PDFRenderer
from privacy_firewall.ui.terms import TermsStore


def _bbox_iou(a: BoundingBox, b: BoundingBox) -> float:
    """Intersection-over-union of two bounding boxes."""
    ix0, iy0 = max(a.x0, b.x0), max(a.y0, b.y0)
    ix1, iy1 = min(a.x1, b.x1), min(a.y1, b.y1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    union = (a.x1 - a.x0) * (a.y1 - a.y0) + (b.x1 - b.x0) * (b.y1 - b.y0) - inter
    return inter / union if union > 0 else 0.0


def _split_span_words(text: str, bbox: BoundingBox) -> list[tuple[str, BoundingBox]]:
    """Split a span into whitespace-delimited words with proportional boxes.

    Native spans are already single words and pass through with their
    exact bbox; OCR adapters emit line-level spans ("SURAJ SONGARA" in
    one span), which must be split so the text layer is word-granular
    and native/OCR twins can be deduplicated word against word.
    """
    total = len(text)
    if total == 0:
        return []
    width = bbox.x1 - bbox.x0
    return [
        (
            match.group(),
            BoundingBox(
                x0=bbox.x0 + match.start() / total * width,
                y0=bbox.y0,
                x1=bbox.x0 + match.end() / total * width,
                y1=bbox.y1,
            ),
        )
        for match in re.finditer(r"\S+", text)
    ]


def _dedupe_twin_words(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop words that duplicate an earlier word's text and position.

    Hybrid documents carry both the native and the OCR reading of the
    same region (the merger keeps OCR blocks below the block-level IoU
    threshold), so the same word can appear twice at nearly identical
    coordinates. In the UI text layer those twins stack: a drag selects
    both and the selection text doubles ("PAN PAN"), which then matches
    nothing. Keep the first occurrence (native blocks precede OCR ones).
    """
    kept: list[dict[str, Any]] = []
    by_text: dict[str, list[dict[str, Any]]] = {}
    for word in words:
        duplicate = False
        for prior in by_text.get(word["text"], ()):
            ix0 = max(prior["x0"], word["x0"])
            iy0 = max(prior["y0"], word["y0"])
            ix1 = min(prior["x1"], word["x1"])
            iy1 = min(prior["y1"], word["y1"])
            inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
            area_a = (word["x1"] - word["x0"]) * (word["y1"] - word["y0"])
            area_b = (prior["x1"] - prior["x0"]) * (prior["y1"] - prior["y0"])
            union = area_a + area_b - inter
            if union > 0 and inter / union > 0.5:
                duplicate = True
                break
        if duplicate:
            continue
        kept.append(word)
        by_text.setdefault(word["text"], []).append(word)
    return kept


@dataclass(frozen=True)
class MarkResult:
    """Outcome of a :meth:`ReviewSession.mark_text` call.

    Attributes:
        added: The newly created review entries.
        skipped: Matches that were found but already in the plan.
    """

    added: list[ReviewEntry]
    skipped: int


class ReviewSession:
    """One review of one PDF: pipeline results plus mutable decisions."""

    def __init__(
        self,
        pdf_path: Path,
        policy: Policy,
        *,
        force_ocr: bool = False,
        auto: bool = False,
        ocr_provider: str | None = None,
        dpi: int = DEFAULT_DPI,
        lazy: bool = False,
        terms_store: TermsStore | None = None,
        password: str | None = None,
    ) -> None:
        """Set up the session and (unless *lazy*) run the pipeline.

        Args:
            pdf_path: The PDF under review.
            policy: Policy providing the suggested actions.
            force_ocr: Force the OCR pipeline.
            auto: Let diagnostics choose the pipeline.
            ocr_provider: Specific OCR engine name.
            dpi: Page-image render resolution.
            lazy: Skip the pipeline; the caller invokes :meth:`run` later
                (e.g. in a background thread while the server starts).
            terms_store: Workspace terms remembered across documents;
                their instances are pre-suggested (never pre-decided).
            password: Password for an encrypted PDF, if required. Kept in
                memory for the session only — never written to disk.
        """
        self.pdf_path = Path(pdf_path)
        self.policy = policy
        self.dpi = dpi
        self.force_ocr = force_ocr
        self.auto = auto
        self.ocr_provider = ocr_provider
        self.password = password
        self.terms_store = terms_store
        self._applied_term_keys: set[tuple[str, str]] = set()
        self._page_dims: list[dict[str, Any]] | None = None
        self._page_cache: OrderedDict[int, bytes] = OrderedDict()
        self._char_words_cache: dict[int, dict[str, list[dict[str, Any]]]] = {}
        self._preview_pdf: bytes | None = None
        self._preview_key: int | None = None
        self._document: Document | None = None
        self._plan: ReviewPlan | None = None
        self.source = ""
        self.status = "starting"
        self.error: str | None = None
        self.needs_password = False
        self.restored_decisions = 0
        self.restored_manual = 0
        self.last_output_path: Path | None = None

        if not lazy:
            self.run()

    @property
    def document(self) -> Document:
        """The parsed document (raises until the pipeline has finished)."""
        if self._document is None:
            msg = "review pipeline has not finished"
            raise RuntimeError(msg)
        return self._document

    @property
    def plan(self) -> ReviewPlan:
        """The review plan (raises until the pipeline has finished)."""
        if self._plan is None:
            msg = "review pipeline has not finished"
            raise RuntimeError(msg)
        return self._plan

    @property
    def is_ready(self) -> bool:
        """Whether the pipeline finished and the plan is available."""
        return self.status == "ready"

    def status_payload(self) -> dict[str, Any]:
        """JSON-friendly pipeline status for the UI loading screen."""
        return {
            "status": self.status,
            "detail": self.error or "",
            "needs_password": self.needs_password,
        }

    def run(self) -> None:
        """Execute the detection pipeline (blocking).

        Updates :attr:`status` as stages advance; on failure the status
        becomes ``"error"`` with the message in :attr:`error`, and the
        exception is re-raised for eager (constructor) callers.
        """
        try:
            self._run_pipeline(force_ocr=self.force_ocr, auto=self.auto)
        except EncryptedPDFError as exc:
            self.status = "error"
            self.error = str(exc)
            self.needs_password = True
            raise
        except Exception as exc:
            self.status = "error"
            self.error = str(exc)
            raise

    def unlock(self, password: str) -> None:
        """Supply a password for an encrypted PDF and re-run the pipeline.

        The password is held in memory for this session only. Cached page
        images and geometry (rendered while locked) are cleared so they are
        rebuilt from the now-readable document.

        Args:
            password: The password to unlock the document.
        """
        self.password = password
        self.needs_password = False
        self.error = None
        self._preview_pdf = None
        self._preview_key = None
        self._page_dims = None
        self._page_cache.clear()
        self._char_words_cache.clear()
        try:
            self._run_pipeline(force_ocr=self.force_ocr, auto=self.auto)
        except EncryptedPDFError as exc:
            self.status = "error"
            self.error = str(exc)
            self.needs_password = True
            raise
        except Exception as exc:
            self.status = "error"
            self.error = str(exc)
            raise

    def rerun(self, *, force_ocr: bool = True, ocr_provider: str | None = None) -> None:
        """Re-run the pipeline (typically forcing OCR), discarding decisions.

        Callers must ensure no other pipeline run is in flight (the
        server serialises reruns behind a lock).

        Args:
            force_ocr: Force the OCR pipeline on this run.
            ocr_provider: Specific OCR engine name.
        """
        self.error = None
        self.ocr_provider = ocr_provider or self.ocr_provider
        self._preview_pdf = None
        self._preview_key = None
        try:
            self._run_pipeline(force_ocr=force_ocr, auto=False, restore=False)
        except Exception as exc:
            self.status = "error"
            self.error = str(exc)
            raise

    def _run_pipeline(self, *, force_ocr: bool, auto: bool, restore: bool = True) -> None:
        """Parse, detect, decide — then optionally restore saved decisions."""
        self.status = "parsing"
        document, self.source = get_merged_document(
            self.pdf_path,
            force_ocr=force_ocr,
            auto=auto,
            ocr_provider=self.ocr_provider,
            password=self.password,
            progress=self._set_stage,
        )

        self.status = "detecting"
        registry = DetectorRegistry()
        for detector in (
            PANDetector(),
            AadhaarDetector(),
            EmailDetector(),
            PhoneDetector(),
            UpiDetector(),
            IFSCDetector(),
            AccountDetector(),
            NameDetector(),
        ):
            registry.register(detector)

        detections = registry.run_all(document, values_only=True).detections
        detections = ContextScorer().apply(document, detections)
        detections = FusionEngine().fuse(detections).detections

        plan = DecisionEngine().decide(
            detections,
            self.policy,
            source_path=str(self.pdf_path),
            source_sha256=file_sha256(self.pdf_path),
        )
        self.restored_decisions = 0
        self.restored_manual = 0
        if restore:
            self._restore_saved_plan(plan)

        self._document = document
        self._plan = plan
        self._applied_term_keys.clear()
        self.sync_remembered_terms()
        self.status = "ready"

    def _set_stage(self, stage: str) -> None:
        """Progress callback for :func:`get_merged_document`."""
        self.status = stage

    def _restore_saved_plan(self, plan: ReviewPlan) -> None:
        """Merge a previously saved review plan into a fresh one.

        Restores user decisions (matched by detection id) and manual
        marks from ``<name>.review.json`` when the file exists and its
        recorded document hash matches — so closing and reopening a
        review resumes where it left off.
        """
        path = self.plan_file_path
        if not path.exists():
            return
        try:
            saved = ReviewPlan.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return  # unreadable/corrupt plan — start fresh
        if saved.source_sha256 != plan.source_sha256:
            return

        for saved_entry in saved.entries:
            if saved_entry.detection.detector_name == "manual":
                if plan.entry_by_id(saved_entry.detection_id) is None:
                    plan.entries.append(saved_entry)
                    self.restored_manual += 1
            elif saved_entry.decision is not None:
                entry = plan.entry_by_id(saved_entry.detection_id)
                if entry is not None and entry.decision is None:
                    entry.decision = saved_entry.decision
                    self.restored_decisions += 1

        if self.restored_manual:
            plan.entries.sort(
                key=lambda e: (
                    e.detection.page_number,
                    e.detection.span.start,
                    e.detection.detection_type,
                )
            )

    @property
    def plan_file_path(self) -> Path:
        """Where the review plan is persisted (next to the source PDF)."""
        return self.pdf_path.with_suffix(".review.json")

    def summary(self) -> dict[str, Any]:
        """Everything the UI needs to render, as JSON-friendly data."""
        return {
            "source": str(self.pdf_path),
            "policy": self.policy.name,
            "pipeline": get_pipeline_summary(self.source),
            "counts": self.plan.counts(),
            "restored": {
                "decisions": self.restored_decisions,
                "manual": self.restored_manual,
            },
            "workspace_terms": self.terms_store is not None,
            "pages": [
                {"page_number": p.page_number, "width": p.width, "height": p.height}
                for p in self.document.pages
            ],
            "entries": [self.entry_dict(e) for e in self.plan.entries],
        }

    @staticmethod
    def entry_dict(entry: ReviewEntry) -> dict[str, Any]:
        """JSON-friendly representation of one review entry."""
        return {
            "detection_id": entry.detection_id,
            "type": entry.detection.detection_type,
            "detector": entry.detection.detector_name,
            "text": entry.detection.text,
            "page_number": entry.detection.page_number,
            "confidence": entry.detection.confidence,
            "bbox": entry.detection.bbox.model_dump(),
            "reasons": list(entry.detection.reasons) + list(entry.suggestion_reasons),
            "suggested_action": entry.suggested_action.value,
            "decision": entry.decision.value if entry.decision else None,
            "effective_action": entry.effective_action.value,
        }

    def set_decision(self, detection_id: str, decision: str | None) -> bool:
        """Record a user decision (``"redact"``, ``"keep"``, or ``None``).

        Args:
            detection_id: Stable id of the detection.
            decision: The decision value, or ``None`` to clear it.

        Returns:
            ``True`` if the entry was found and updated.
        """
        entry = self.plan.entry_by_id(detection_id)
        if entry is None:
            return False
        entry.decision = ReviewDecision(decision) if decision else None
        return True

    def page_words(self, page_number: int) -> list[dict[str, Any]]:
        """Word-level text geometry for one page (drives the UI text layer).

        Args:
            page_number: The 1-based page number.

        Returns:
            One dict per word: ``{"text", "x0", "y0", "x1", "y1"}`` in
            PDF coordinates, plus ``"cx"`` — the ``len(text) + 1``
            character boundary x-positions — when the word could be
            matched to the PDF's own text layer (native text; OCR words
            have no reliable per-character geometry).

        Raises:
            ValueError: If the page does not exist.
        """
        for page in self.document.pages:
            if page.page_number != page_number:
                continue
            words: list[dict[str, Any]] = []
            for block in page.blocks:
                if not isinstance(block, TextBlock):
                    continue
                for span in block.spans:
                    for word_text, word_bbox in _split_span_words(span.text, span.bbox):
                        word: dict[str, Any] = {"text": word_text, **word_bbox.model_dump()}
                        boundaries = self._char_boundaries(page_number, word_text, word_bbox)
                        if boundaries is not None:
                            word["cx"] = boundaries
                        words.append(word)
            return _dedupe_twin_words(words)
        msg = f"page {page_number} not found"
        raise ValueError(msg)

    def mark_text(self, text: str, label: str, *, case_sensitive: bool = False) -> MarkResult:
        """Mark every instance of *text* in the document as PII.

        Each occurrence becomes a manual ``Detection`` (detector name
        ``"manual"``, confidence 1.0) with the given label as its
        detection type and an explicit *redact* decision — the reviewer
        can still flip individual instances to *keep* afterwards.

        Whitespace in *text* is treated flexibly (any run of whitespace
        matches any other), so selections spanning line wraps still match.

        Args:
            text: The text to search for (as selected by the reviewer).
            label: Detection-type label for the new entries (e.g. ``NAME``).
            case_sensitive: Require an exact-case match.

        Returns:
            A :class:`MarkResult` with the newly added entries and the
            count of matches skipped because they were already marked —
            so the caller can tell "nothing found" from "all already
            marked".

        Raises:
            ValueError: If *text* or *label* is blank.
        """
        return self._mark_instances(
            text,
            label,
            case_sensitive=case_sensitive,
            detector_name="manual",
            detection_reason="marked as PII by the reviewer",
            suggested=SuggestedAction.REDACT,
            suggestion_reason="manually marked during review",
            decision=ReviewDecision.REDACT,
        )

    def remember_text(self, text: str, label: str, *, case_sensitive: bool = False) -> bool:
        """Add a term to the workspace store (no-op without a store).

        Returns:
            ``True`` if the term was newly remembered.
        """
        if self.terms_store is None:
            return False
        return self.terms_store.add(
            text,
            "_".join(label.split()).upper(),
            case_sensitive=case_sensitive,
            added_from=self.pdf_path.name,
        )

    def sync_remembered_terms(self) -> int:
        """Apply workspace terms not yet suggested in this session.

        Each active term's instances are added like :meth:`mark_text`
        but with detector name ``"remembered"``, the *policy's* action
        as the suggestion, and **no** decision — remembered terms are
        suggestions the reviewer confirms. Idempotent; safe to call on
        every plan read so terms remembered in one document surface in
        the others without a restart.

        Returns:
            The number of entries added by this call.
        """
        if self.terms_store is None or self._plan is None:
            return 0
        added = 0
        suggested_for = {
            PolicyAction.REDACT: SuggestedAction.REDACT,
            PolicyAction.KEEP: SuggestedAction.KEEP,
            PolicyAction.ASK: SuggestedAction.ASK,
        }
        for term in self.terms_store.active_terms():
            if term.key in self._applied_term_keys:
                continue
            self._applied_term_keys.add(term.key)
            origin = f" (from {term.added_from})" if term.added_from else ""
            result = self._mark_instances(
                term.text,
                term.label,
                case_sensitive=term.case_sensitive,
                detector_name="remembered",
                detection_reason=f"remembered workspace term{origin}",
                suggested=suggested_for[self.policy.type_policy(term.label).action],
                suggestion_reason="suggested from workspace memory",
                decision=None,
            )
            added += len(result.added)
        return added

    def forget_term(self, detection_id: str) -> bool:
        """Forget the workspace term behind a remembered entry.

        Removes the term from the store and every entry it produced in
        this session (the term would otherwise resurface on the next
        sync).

        Args:
            detection_id: Id of any entry the term produced.

        Returns:
            ``True`` if the entry was a remembered one and was removed.
        """
        entry = self.plan.entry_by_id(detection_id)
        if entry is None or entry.detection.detector_name != "remembered":
            return False
        text = entry.detection.text
        label = entry.detection.detection_type
        key = (text.casefold(), label)
        self.plan.entries = [
            e
            for e in self.plan.entries
            if not (
                e.detection.detector_name == "remembered"
                and (e.detection.text.casefold(), e.detection.detection_type) == key
            )
        ]
        self._applied_term_keys.discard(key)
        if self.terms_store is not None:
            self.terms_store.remove(text, label)
        return True

    def _mark_instances(
        self,
        text: str,
        label: str,
        *,
        case_sensitive: bool,
        detector_name: str,
        detection_reason: str,
        suggested: SuggestedAction,
        suggestion_reason: str,
        decision: ReviewDecision | None,
    ) -> MarkResult:
        """Add one entry per instance of *text* in the document."""
        tokens = text.split()
        if not tokens:
            msg = "text to mark must not be blank"
            raise ValueError(msg)
        normalized_label = "_".join(label.split()).upper()
        if not normalized_label:
            msg = "label must not be blank"
            raise ValueError(msg)

        pattern = re.compile(
            r"\s+".join(re.escape(token) for token in tokens),
            0 if case_sensitive else re.IGNORECASE,
        )
        known_ids = {entry.detection_id for entry in self.plan.entries}
        # Same-text entries already in the plan, for position-level dedup:
        # hybrid documents carry native + OCR twins of the same region in
        # separate blocks, which would otherwise mark every instance twice.
        norm = " ".join(text.split()).casefold()
        seen_boxes: list[tuple[int, BoundingBox, ReviewEntry | None]] = [
            (e.detection.page_number, e.detection.bbox, e)
            for e in self.plan.entries
            if " ".join(e.detection.text.split()).casefold() == norm
        ]
        added: list[ReviewEntry] = []
        skipped = 0

        for page in self.document.pages:
            # Spans are offset into a page-level concatenation of block
            # texts so the same text at the same block-relative offset in
            # two blocks still yields distinct detection ids.
            page_offset = 0
            for block in page.blocks:
                if not isinstance(block, TextBlock):
                    continue
                base = page_offset
                page_offset += len(block.text) + 1
                for match in pattern.finditer(block.text):
                    detection = Detection(
                        detector_name=detector_name,
                        detection_type=normalized_label,
                        text=match.group(),
                        span=Span(start=base + match.start(), end=base + match.end()),
                        bbox=self._char_range_bbox(
                            page.page_number, block, match.start(), match.end()
                        ),
                        page_number=page.page_number,
                        confidence=1.0,
                        reasons=(detection_reason,),
                    )
                    if detection.detection_id in known_ids:
                        skipped += 1
                        continue
                    twin_hit = False
                    for page_no, box, existing in seen_boxes:
                        if page_no != detection.page_number:
                            continue
                        if _bbox_iou(box, detection.bbox) <= 0.5:
                            continue
                        # Native/OCR twin, or an entry already covering
                        # this spot — marking it means "redact", so
                        # confirm the existing entry rather than
                        # duplicating it.
                        twin_hit = True
                        if existing is not None and decision is not None:
                            if existing.decision is None:
                                existing.decision = decision
                        break
                    if twin_hit:
                        skipped += 1
                        continue
                    known_ids.add(detection.detection_id)
                    seen_boxes.append((detection.page_number, detection.bbox, None))
                    entry = ReviewEntry(
                        detection=detection,
                        suggested_action=suggested,
                        suggestion_reasons=(suggestion_reason,),
                        decision=decision,
                    )
                    self.plan.entries.append(entry)
                    added.append(entry)

        if added:
            self.plan.entries.sort(
                key=lambda e: (
                    e.detection.page_number,
                    e.detection.span.start,
                    e.detection.detection_type,
                )
            )
        return MarkResult(added=added, skipped=skipped)

    def remove_manual_entry(self, detection_id: str) -> bool:
        """Remove a manually marked entry from the plan.

        Only entries created by :meth:`mark_text` can be removed —
        detector-produced entries are kept as the audit trail (use a
        *keep* decision to exclude them instead). For entries produced
        by a workspace term, use :meth:`forget_term`.

        Args:
            detection_id: Id of the manual entry to remove.

        Returns:
            ``True`` if the entry existed, was manual, and was removed.
        """
        entry = self.plan.entry_by_id(detection_id)
        if entry is None or entry.detection.detector_name != "manual":
            return False
        self.plan.entries.remove(entry)
        return True

    def _char_range_bbox(
        self, page_number: int, block: TextBlock, start: int, end: int
    ) -> BoundingBox:
        """Bounding box for a character range of ``block.text``.

        Unlike :meth:`TextBlock.bbox_for_span`, offsets are aligned to
        ``block.text`` (which joins words with separators) by locating
        each word in the text. Partially covered words are clipped at
        real glyph boundaries from the PDF's text layer when available,
        falling back to proportional interpolation (exact only for
        monospace) when the word has no per-character geometry (OCR).
        """
        if not block.spans:
            return block.bbox

        x0 = y0 = float("inf")
        x1 = y1 = float("-inf")
        found = False
        pos = 0
        for span in block.spans:
            if not span.text:
                continue
            offset = block.text.find(span.text, pos)
            if offset < 0:
                offset = pos
            pos = offset + len(span.text)
            overlap_start = max(start, offset)
            overlap_end = min(end, offset + len(span.text))
            if overlap_start >= overlap_end:
                continue
            found = True
            rel_start = overlap_start - offset
            rel_end = overlap_end - offset
            boundaries = self._char_boundaries(page_number, span.text, span.bbox)
            if boundaries is not None:
                x0 = min(x0, boundaries[rel_start])
                x1 = max(x1, boundaries[rel_end])
            else:
                width = span.bbox.x1 - span.bbox.x0
                x0 = min(x0, span.bbox.x0 + rel_start / len(span.text) * width)
                x1 = max(x1, span.bbox.x0 + rel_end / len(span.text) * width)
            y0 = min(y0, span.bbox.y0)
            y1 = max(y1, span.bbox.y1)

        if not found:
            return block.bbox
        return BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)

    def _char_boundaries(
        self, page_number: int, text: str, bbox: BoundingBox
    ) -> list[float] | None:
        """Character boundary x-positions for one word, if the PDF knows them.

        Matches the word against the PDF text layer's per-character
        geometry by text and position. Returns ``len(text) + 1``
        ascending x-values (glyph left edges plus the final right edge),
        or ``None`` for words the text layer cannot vouch for (OCR
        words, or ligature/encoding mismatches).
        """
        candidates = self._page_char_words(page_number).get(text)
        if not candidates:
            return None
        for entry in candidates:
            if abs(entry["x0"] - bbox.x0) <= 2.0 and abs(entry["y0"] - bbox.y0) <= 2.0:
                boundaries: list[float] = entry["cx"]
                if len(boundaries) == len(text) + 1:
                    return boundaries
        return None

    def _page_char_words(self, page_number: int) -> dict[str, list[dict[str, Any]]]:
        """Whitespace-delimited words with per-char geometry, keyed by text.

        Built once per page from the ``rawdict`` of the source PDF
        (same extraction family as ``get_text("words")``, so word texts
        line up with the parser's spans on native documents).
        """
        cached = self._char_words_cache.get(page_number)
        if cached is not None:
            return cached

        index: dict[str, list[dict[str, Any]]] = {}
        try:
            with open_pdf(self.pdf_path, password=self.password) as doc:
                raw = doc[page_number - 1].get_text("rawdict")
        except Exception:  # noqa: BLE001 - char geometry is best-effort
            self._char_words_cache[page_number] = index
            return index

        def flush(chars: list[tuple[str, tuple[float, float, float, float]]]) -> None:
            if not chars:
                return
            word_text = "".join(c for c, _ in chars)
            rects = [r for _, r in chars]
            entry = {
                "x0": min(r[0] for r in rects),
                "y0": min(r[1] for r in rects),
                "cx": [r[0] for r in rects] + [max(r[2] for r in rects)],
            }
            index.setdefault(word_text, []).append(entry)

        for raw_block in raw.get("blocks", []):
            if raw_block.get("type") != 0:
                continue
            for line in raw_block.get("lines", []):
                for raw_span in line.get("spans", []):
                    pending: list[tuple[str, tuple[float, float, float, float]]] = []
                    for char in raw_span.get("chars", []):
                        c = char.get("c", "")
                        if not c or c.isspace():
                            flush(pending)
                            pending = []
                            continue
                        pending.append((c, tuple(char["bbox"])))
                    flush(pending)

        self._char_words_cache[page_number] = index
        return index

    def page_dimensions(self) -> list[dict[str, Any]]:
        """Page numbers and sizes straight from the PDF (cached).

        Unlike :attr:`document`, this works while the pipeline is still
        running, so the UI can show the pages during a long OCR pass.
        """
        if self._page_dims is None:
            with open_pdf(self.pdf_path, password=self.password) as doc:
                self._page_dims = [
                    {
                        "page_number": i + 1,
                        "width": page.rect.width,
                        "height": page.rect.height,
                    }
                    for i, page in enumerate(doc)
                ]
        return self._page_dims

    PAGE_CACHE_PAGES = 24
    """Rendered page PNGs kept per session (LRU) — a large scanned
    document would otherwise pin tens of MB per mounted session."""

    def page_png(self, page_number: int) -> bytes:
        """Rendered PNG for a page (bounded LRU cache per session)."""
        cached = self._page_cache.get(page_number)
        if cached is not None:
            self._page_cache.move_to_end(page_number)
            return cached
        image = render_page_image(self.pdf_path, page_number, dpi=self.dpi, password=self.password)
        self._page_cache[page_number] = image.png_bytes
        while len(self._page_cache) > self.PAGE_CACHE_PAGES:
            self._page_cache.popitem(last=False)
        return image.png_bytes

    def preview_page_png(
        self,
        page_number: int,
        *,
        redaction_type: RedactionType = RedactionType.REPLACE,
    ) -> bytes:
        """Rendered PNG of a page with the current plan's redactions applied.

        Applies the plan to an in-memory copy (undecided entries follow
        their suggestion, like :meth:`apply`) so the reviewer sees exactly
        what the export will look like — the source PDF is untouched.

        The redacted PDF is cached and rebuilt only when a decision or
        mark changes between requests.

        Args:
            page_number: 1-based page number.
            redaction_type: Visual redaction style to preview.

        Returns:
            PNG bytes of the previewed page.

        Raises:
            ValueError: If *page_number* is out of range.
        """
        key = hash(
            (
                redaction_type.value,
                tuple(
                    (e.detection_id, e.decision.value if e.decision else "")
                    for e in self.plan.entries
                ),
            )
        )
        if self._preview_pdf is None or self._preview_key != key:
            detections = self.plan.resolve(accept_suggestions=True)
            redaction_plan = RedactionPlanner().plan(
                self.document, detections, default_type=redaction_type
            )
            source_bytes = (
                decrypted_bytes(self.pdf_path, self.password) or self.pdf_path.read_bytes()
            )
            self._preview_pdf = PDFRenderer.render_bytes(source_bytes, redaction_plan)
            self._preview_key = key
        return render_page_image_bytes(self._preview_pdf, page_number, dpi=self.dpi).png_bytes

    def save_plan(self) -> Path:
        """Persist the review plan (with decisions) next to the PDF."""
        self.plan_file_path.write_text(self.plan.model_dump_json(indent=2), encoding="utf-8")
        return self.plan_file_path

    def apply(
        self,
        output_path: Path | None = None,
        *,
        redaction_type: RedactionType = RedactionType.REPLACE,
    ) -> tuple[Path, int]:
        """Apply the reviewed plan and render the redacted PDF.

        Undecided entries follow their suggestion; unresolved *ask*
        entries are redacted (privacy-first). The plan (with decisions)
        is saved alongside as the audit record.

        Args:
            output_path: Target path; defaults to ``<name>.redacted.pdf``.
            redaction_type: Visual redaction style.

        Returns:
            ``(output_path, redaction_count)``.
        """
        if output_path is None:
            output_path = self.pdf_path.with_name(f"{self.pdf_path.stem}.redacted.pdf")

        detections = self.plan.resolve(accept_suggestions=True)
        redaction_plan = RedactionPlanner().plan(
            self.document, detections, default_type=redaction_type
        )
        out = PDFRenderer().render(
            self.pdf_path, output_path, redaction_plan, password=self.password
        )
        self.save_plan()
        self.last_output_path = Path(out)
        return Path(out), redaction_plan.total_redactions
