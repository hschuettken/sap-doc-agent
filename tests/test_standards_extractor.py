import pytest

from sap_doc_agent.standards.extractor import UnsupportedFileType, extract_text


def test_extract_yaml_text():
    yaml_bytes = b"name: test\nrules:\n  - rule1\n"
    result = extract_text(yaml_bytes, "text/yaml")
    assert "name: test" in result


def test_extract_plain_text():
    text_bytes = b"This is a documentation standard."
    result = extract_text(text_bytes, "text/plain")
    assert "documentation standard" in result


def test_extract_markdown():
    md_bytes = b"# Standard\n\n## Rules\n- Rule 1\n"
    result = extract_text(md_bytes, "text/markdown")
    assert "Standard" in result


def test_unsupported_type_raises():
    with pytest.raises(UnsupportedFileType):
        extract_text(b"\x00\x01\x02", "image/jpeg")


def test_extract_utf8_decode_failure():
    with pytest.raises(UnsupportedFileType):
        extract_text(b"\xff\xfe\xfd\xfc", "application/octet-stream")
