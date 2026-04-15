import pytest
from spec2sphere.agents.pdf_ingest import PDFIngestor


@pytest.fixture
def ingestor():
    return PDFIngestor()


def test_nonexistent_file_raises(ingestor, tmp_path):
    with pytest.raises(FileNotFoundError):
        ingestor.extract_text(tmp_path / "nonexistent.pdf")


def test_non_pdf_raises(ingestor, tmp_path):
    txt = tmp_path / "test.txt"
    txt.write_text("not a pdf")
    with pytest.raises(ValueError, match="Not a PDF"):
        ingestor.extract_text(txt)


def test_extract_from_empty_directory(ingestor, tmp_path):
    docs = ingestor.extract_from_directory(tmp_path)
    assert docs == []


def test_extract_from_directory_with_non_pdf(ingestor, tmp_path):
    (tmp_path / "readme.txt").write_text("not a pdf")
    docs = ingestor.extract_from_directory(tmp_path)
    assert docs == []
