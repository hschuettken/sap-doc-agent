"""Text extraction from PDF, Word, YAML, and Markdown files."""

from __future__ import annotations

import io


class UnsupportedFileType(Exception):
    pass


def extract_text(file_data: bytes, content_type: str) -> str:
    """Extract text from file bytes. Raises UnsupportedFileType for unknown types."""
    ct = content_type.lower()

    if "pdf" in ct:
        return _extract_pdf(file_data)
    elif "word" in ct or "docx" in ct or "officedocument.wordprocessingml" in ct:
        return _extract_docx(file_data)
    elif ct in ("text/yaml", "application/yaml", "text/plain", "text/markdown"):
        return file_data.decode("utf-8", errors="replace")
    elif ct in ("application/octet-stream",):
        # Try UTF-8 decode as fallback
        try:
            return file_data.decode("utf-8")
        except UnicodeDecodeError:
            raise UnsupportedFileType(f"Cannot decode binary file with content_type: {content_type}")
    else:
        raise UnsupportedFileType(f"Unsupported content_type: {content_type}")


def _extract_pdf(data: bytes) -> str:
    try:
        import pdfplumber
    except ImportError:
        raise UnsupportedFileType("pdfplumber not installed; cannot extract PDF text")
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(pages)


def _extract_docx(data: bytes) -> str:
    try:
        import docx
    except ImportError:
        raise UnsupportedFileType("python-docx not installed; cannot extract Word text")
    doc = docx.Document(io.BytesIO(data))
    return "\n".join(para.text for para in doc.paragraphs if para.text.strip())
