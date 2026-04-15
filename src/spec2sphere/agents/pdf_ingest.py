"""PDF ingestion for document review.

Extracts text content from PDF files so they can be reviewed
against documentation standards. Uses pdfplumber for reliable
text extraction from complex layouts.

Falls back to basic PyPDF2/pypdf if pdfplumber is not available.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class PDFIngestor:
    """Extract text from PDF files."""

    def extract_text(self, path: Path) -> str:
        """Extract all text from a PDF file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {path}")
        if not path.suffix.lower() == ".pdf":
            raise ValueError(f"Not a PDF file: {path}")

        # Try pdfplumber first (best quality)
        try:
            return self._extract_pdfplumber(path)
        except ImportError:
            pass

        # Fallback to pypdf
        try:
            return self._extract_pypdf(path)
        except ImportError:
            pass

        raise ImportError("No PDF library available. Install one of: pip install pdfplumber  OR  pip install pypdf")

    def extract_from_directory(self, directory: Path) -> list[dict]:
        """Extract text from all PDFs in a directory.

        Returns list of {title, content, source_path} dicts.
        """
        directory = Path(directory)
        documents = []
        for pdf_path in sorted(directory.glob("**/*.pdf")):
            try:
                text = self.extract_text(pdf_path)
                documents.append(
                    {
                        "title": pdf_path.stem.replace("_", " ").replace("-", " "),
                        "content": text,
                        "source_path": str(pdf_path),
                        "type": None,  # Will be auto-classified
                    }
                )
                logger.info("Extracted %d chars from %s", len(text), pdf_path.name)
            except Exception as e:
                logger.warning("Failed to extract %s: %s", pdf_path.name, e)
        return documents

    def _extract_pdfplumber(self, path: Path) -> str:
        """Extract using pdfplumber (handles tables and complex layouts)."""
        import pdfplumber

        pages = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
                # Also extract tables
                tables = page.extract_tables()
                for table in tables:
                    if table:
                        for row in table:
                            if row:
                                pages.append(" | ".join(str(cell or "") for cell in row))
        return "\n\n".join(pages)

    def _extract_pypdf(self, path: Path) -> str:
        """Extract using pypdf (simpler, fallback)."""
        from pypdf import PdfReader

        reader = PdfReader(path)
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n\n".join(pages)
