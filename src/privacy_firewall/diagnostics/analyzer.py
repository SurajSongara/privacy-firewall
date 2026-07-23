"""PDF document analyser that produces diagnostic reports."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from privacy_firewall.diagnostics.models import DiagnosticReport, PipelineType
from privacy_firewall.diagnostics.pipeline_selector import PipelineSelector
from privacy_firewall.diagnostics.text_quality import TextQualityAnalyzer
from privacy_firewall.parsers.pdf_open import open_pdf


class DocumentAnalyzer:
    """Inspects a PDF file and produces a structured diagnostic report.

    The analyser opens the document, runs a series of checks
    (text presence, image count, rotation, encryption, ...), scores the
    quality of any extractable text, and recommends a processing pipeline.
    """

    def __init__(self, file_path: str | Path, password: str | None = None) -> None:
        """Initialise the analyser with a path to a PDF file.

        Args:
            file_path: Path to the PDF file to analyse.
            password: Password for an encrypted PDF, if available. When a
                correct one is supplied the analyser unlocks the document
                and inspects its content; otherwise it reports encryption
                without crashing.
        """
        self._path = Path(file_path)
        self._password = password

    @staticmethod
    def from_bytes(data: bytes, password: str | None = None) -> DiagnosticReport:
        """Analyse PDF content from raw bytes.

        Args:
            data: Raw PDF bytes.
            password: Password for an encrypted PDF, if available.

        Returns:
            A DiagnosticReport for the supplied content.
        """
        doc = open_pdf(stream=data, password=password, required=False)
        try:
            return DocumentAnalyzer._analyze_doc(doc, file_path="")
        finally:
            doc.close()

    def analyze(self) -> DiagnosticReport:
        """Open the PDF file and produce a diagnostic report.

        Returns:
            A DiagnosticReport with all fields populated.
        """
        doc = open_pdf(self._path, password=self._password, required=False)
        try:
            return self._analyze_doc(doc, file_path=str(self._path.resolve()))
        finally:
            doc.close()

    @staticmethod
    def _analyze_doc(doc: Any, file_path: str) -> DiagnosticReport:
        """Core analysis logic — inspects an open document.

        Args:
            doc: An open document.
            file_path: The file path string (empty for byte input).

        Returns:
            A populated DiagnosticReport.
        """
        page_count = len(doc)
        # ``needs_pass`` is the *locked* state — it is 0 once a correct
        # password has authenticated the document, so an unlocked-but-
        # encrypted file is analysed normally rather than short-circuited.
        locked = bool(doc.needs_pass)
        is_encrypted = locked or bool(doc.is_encrypted)

        if locked or page_count == 0:
            return DiagnosticReport(
                file_path=file_path,
                page_count=page_count,
                is_encrypted=is_encrypted,
                recommended_pipeline=PipelineType.OCR,
            )

        total_images = 0
        has_text = False
        rotated_pages: list[int] = []
        all_text = ""

        for i in range(page_count):
            page = doc[i]
            total_images += len(page.get_images())

            rotation = page.rotation or 0
            if rotation not in (0, 360):
                rotated_pages.append(i + 1)

            page_text = page.get_text("text") or ""
            if page_text.strip():
                has_text = True
                all_text += page_text + "\n"

        if not all_text:
            est_scanned = PipelineSelector.estimate_scanned(
                page_count=page_count, image_count=total_images, text_quality_score=0.0,
            )
            return DiagnosticReport(
                file_path=file_path,
                page_count=page_count,
                image_count=total_images,
                rotated_pages=rotated_pages,
                estimated_scanned=est_scanned,
                recommended_pipeline=PipelineType.OCR,
            )

        tqr = TextQualityAnalyzer.analyze(all_text)
        quality = tqr.overall_score

        est_scanned = PipelineSelector.estimate_scanned(
            page_count=page_count, image_count=total_images, text_quality_score=quality,
        )
        pipeline = PipelineSelector.select(
            is_encrypted=False,
            page_count=page_count,
            has_native_text=has_text,
            estimated_scanned=est_scanned,
            text_quality_score=quality,
        )

        return DiagnosticReport(
            file_path=file_path,
            page_count=page_count,
            image_count=total_images,
            has_native_text=has_text,
            rotated_pages=rotated_pages,
            estimated_scanned=est_scanned,
            text_quality_report=tqr,
            recommended_pipeline=pipeline,
        )
