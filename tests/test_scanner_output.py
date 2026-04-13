"""Tests for scanner output writer."""

import json
from pathlib import Path

import yaml

from sap_doc_agent.scanner.models import (
    Dependency,
    DependencyType,
    ObjectType,
    ScanResult,
    ScannedObject,
)
from sap_doc_agent.scanner.output import render_object_markdown, write_scan_output


class TestRenderObjectMarkdown:
    """Test render_object_markdown function."""

    def test_basic_markdown_structure(self):
        """Test that markdown has expected sections."""
        obj = ScannedObject(
            object_id="Z_TEST",
            object_type=ObjectType.TABLE,
            name="Test Table",
        )
        md = render_object_markdown(obj)
        assert "---" in md
        assert "# Test Table" in md
        assert "## Details" in md

    def test_yaml_frontmatter_parseable(self):
        """Test that YAML frontmatter can be parsed."""
        obj = ScannedObject(
            object_id="Z_TEST",
            object_type=ObjectType.ADSO,
            name="Test ADSO",
            source_system="DEV",
            package="Z_PKG",
        )
        md = render_object_markdown(obj)
        lines = md.split("\n")
        # Find frontmatter
        start = lines.index("---")
        end = lines.index("---", start + 1)
        fm_lines = lines[start + 1 : end]
        fm_text = "\n".join(fm_lines)
        fm = yaml.safe_load(fm_text)
        assert fm["object_id"] == "Z_TEST"
        assert fm["object_type"] == "adso"
        assert fm["name"] == "Test ADSO"

    def test_frontmatter_includes_required_fields(self):
        """Test that frontmatter includes all required fields."""
        obj = ScannedObject(
            object_id="Z_TEST",
            object_type=ObjectType.TABLE,
            name="Test",
            source_system="DEV",
            package="PKG",
            owner="ADMIN",
            layer="LAYER",
            technical_name="TECH_NAME",
        )
        md = render_object_markdown(obj)
        lines = md.split("\n")
        start = lines.index("---")
        end = lines.index("---", start + 1)
        fm_text = "\n".join(lines[start + 1 : end])
        assert "object_id:" in fm_text
        assert "object_type:" in fm_text
        assert "name:" in fm_text
        assert "source_system:" in fm_text
        assert "package:" in fm_text
        assert "owner:" in fm_text
        assert "layer:" in fm_text
        assert "technical_name:" in fm_text
        assert "scanned_at:" in fm_text

    def test_frontmatter_includes_content_hash_if_set(self):
        """Test that content_hash appears in frontmatter when set."""
        obj = ScannedObject(
            object_id="Z_TEST",
            object_type=ObjectType.TABLE,
            name="Test",
        )
        obj.compute_hash()
        md = render_object_markdown(obj)
        assert "content_hash:" in md

    def test_frontmatter_omits_content_hash_if_not_set(self):
        """Test that content_hash is omitted when None."""
        obj = ScannedObject(
            object_id="Z_TEST",
            object_type=ObjectType.TABLE,
            name="Test",
        )
        # Don't call compute_hash
        md = render_object_markdown(obj)
        lines = md.split("\n")
        start = lines.index("---")
        end = lines.index("---", start + 1)
        fm_text = "\n".join(lines[start + 1 : end])
        assert "content_hash:" not in fm_text

    def test_frontmatter_includes_metadata_if_set(self):
        """Test that metadata appears in frontmatter when non-empty."""
        obj = ScannedObject(
            object_id="Z_TEST",
            object_type=ObjectType.TABLE,
            name="Test",
            metadata={"key": "value"},
        )
        md = render_object_markdown(obj)
        assert "metadata:" in md

    def test_frontmatter_omits_metadata_if_empty(self):
        """Test that metadata is omitted when empty."""
        obj = ScannedObject(
            object_id="Z_TEST",
            object_type=ObjectType.TABLE,
            name="Test",
        )
        md = render_object_markdown(obj)
        lines = md.split("\n")
        start = lines.index("---")
        end = lines.index("---", start + 1)
        fm_text = "\n".join(lines[start + 1 : end])
        assert "metadata:" not in fm_text

    def test_heading_with_name(self):
        """Test that markdown includes heading with object name."""
        obj = ScannedObject(
            object_id="Z_TEST",
            object_type=ObjectType.TABLE,
            name="My Test Object",
        )
        md = render_object_markdown(obj)
        assert "# My Test Object" in md

    def test_description_included(self):
        """Test that description is included in markdown."""
        obj = ScannedObject(
            object_id="Z_TEST",
            object_type=ObjectType.TABLE,
            name="Test",
            description="This is a test object",
        )
        md = render_object_markdown(obj)
        assert "This is a test object" in md

    def test_description_omitted_if_empty(self):
        """Test that empty description is not included."""
        obj = ScannedObject(
            object_id="Z_TEST",
            object_type=ObjectType.TABLE,
            name="Test",
            description="",
        )
        md = render_object_markdown(obj)
        # Should only have the heading and details, not a bare description line
        lines = md.split("\n")
        # After frontmatter and heading, next non-empty should be "## Details"
        # Filter out frontmatter markers and content
        in_frontmatter = False
        relevant = []
        for l in lines:
            if l.strip() == "---":
                in_frontmatter = not in_frontmatter
            elif not in_frontmatter and l.strip():
                relevant.append(l)
        assert relevant[0] == "# Test"
        assert relevant[1] == "## Details"

    def test_details_section_has_bullets(self):
        """Test that Details section has bullet points."""
        obj = ScannedObject(
            object_id="Z_TEST",
            object_type=ObjectType.TABLE,
            name="Test",
            package="PKG",
            owner="ADMIN",
            layer="LAYER",
            source_system="DEV",
        )
        md = render_object_markdown(obj)
        assert "- **Type**:" in md
        assert "- **Package**:" in md
        assert "- **Owner**:" in md
        assert "- **Layer**:" in md
        assert "- **Source System**:" in md

    def test_source_code_section_with_abap_block(self):
        """Test that source code is included in ```abap block."""
        obj = ScannedObject(
            object_id="Z_TEST",
            object_type=ObjectType.CLASS,
            name="Test Class",
            source_code="CLASS z_test.\nENDCLASS.",
        )
        md = render_object_markdown(obj)
        assert "## Source Code" in md
        assert "```abap" in md
        assert "CLASS z_test." in md
        assert "ENDCLASS." in md
        assert "```" in md

    def test_source_code_section_omitted_if_empty(self):
        """Test that Source Code section is omitted if source_code is empty."""
        obj = ScannedObject(
            object_id="Z_TEST",
            object_type=ObjectType.TABLE,
            name="Test",
            source_code="",
        )
        md = render_object_markdown(obj)
        assert "## Source Code" not in md


class TestWriteScanOutput:
    """Test write_scan_output function."""

    def test_creates_output_directory(self, tmp_path: Path):
        """Test that output directory is created."""
        result = ScanResult(source_system="DEV")
        output_dir = tmp_path / "output"
        write_scan_output(result, output_dir)
        assert output_dir.exists()

    def test_creates_objects_subdirectory(self, tmp_path: Path):
        """Test that objects subdirectory is created."""
        result = ScanResult(source_system="DEV")
        output_dir = tmp_path / "output"
        write_scan_output(result, output_dir)
        assert (output_dir / "objects").exists()

    def test_creates_markdown_files_by_type(self, tmp_path: Path):
        """Test that markdown files are created in type-specific directories."""
        obj1 = ScannedObject(
            object_id="Z_ADSO_1",
            object_type=ObjectType.ADSO,
            name="ADSO 1",
        )
        obj2 = ScannedObject(
            object_id="Z_TABLE_1",
            object_type=ObjectType.TABLE,
            name="Table 1",
        )
        result = ScanResult(source_system="DEV", objects=[obj1, obj2])
        output_dir = tmp_path / "output"
        write_scan_output(result, output_dir)
        assert (output_dir / "objects" / "adso" / "Z_ADSO_1.md").exists()
        assert (output_dir / "objects" / "table" / "Z_TABLE_1.md").exists()

    def test_markdown_content_is_valid(self, tmp_path: Path):
        """Test that generated markdown files contain valid content."""
        obj = ScannedObject(
            object_id="Z_TEST",
            object_type=ObjectType.TABLE,
            name="Test Table",
            description="Test description",
        )
        result = ScanResult(source_system="DEV", objects=[obj])
        output_dir = tmp_path / "output"
        write_scan_output(result, output_dir)
        md_file = output_dir / "objects" / "table" / "Z_TEST.md"
        content = md_file.read_text()
        assert "# Test Table" in content
        assert "Test description" in content

    def test_creates_graph_json(self, tmp_path: Path):
        """Test that graph.json is created."""
        result = ScanResult(source_system="DEV")
        output_dir = tmp_path / "output"
        write_scan_output(result, output_dir)
        assert (output_dir / "graph.json").exists()

    def test_graph_json_structure(self, tmp_path: Path):
        """Test that graph.json has correct structure."""
        obj1 = ScannedObject(
            object_id="Z_ADSO_1",
            object_type=ObjectType.ADSO,
            name="ADSO 1",
            source_system="DEV",
            layer="SEMANTICS",
            package="PKG",
        )
        obj2 = ScannedObject(
            object_id="Z_ADSO_2",
            object_type=ObjectType.ADSO,
            name="ADSO 2",
            source_system="DEV",
            layer="SEMANTICS",
            package="PKG",
        )
        dep = Dependency(
            source_id="Z_ADSO_1",
            target_id="Z_ADSO_2",
            dependency_type=DependencyType.READS_FROM,
        )
        result = ScanResult(
            source_system="DEV",
            objects=[obj1, obj2],
            dependencies=[dep],
        )
        output_dir = tmp_path / "output"
        write_scan_output(result, output_dir)
        graph_file = output_dir / "graph.json"
        graph = json.loads(graph_file.read_text())
        assert "source_system" in graph
        assert "scanned_at" in graph
        assert "nodes" in graph
        assert "edges" in graph

    def test_graph_json_nodes_have_required_fields(self, tmp_path: Path):
        """Test that graph nodes have required fields."""
        obj = ScannedObject(
            object_id="Z_TEST",
            object_type=ObjectType.TABLE,
            name="Test Table",
            source_system="DEV",
            layer="PRESENTATION",
            package="PKG",
        )
        result = ScanResult(source_system="DEV", objects=[obj])
        output_dir = tmp_path / "output"
        write_scan_output(result, output_dir)
        graph = json.loads((output_dir / "graph.json").read_text())
        assert len(graph["nodes"]) == 1
        node = graph["nodes"][0]
        assert node["id"] == "Z_TEST"
        assert node["name"] == "Test Table"
        assert node["type"] == "table"
        assert node["source_system"] == "DEV"
        assert "layer" in node
        assert "package" in node

    def test_graph_json_edges_have_required_fields(self, tmp_path: Path):
        """Test that graph edges have required fields."""
        obj1 = ScannedObject(
            object_id="Z_A",
            object_type=ObjectType.TABLE,
            name="A",
        )
        obj2 = ScannedObject(
            object_id="Z_B",
            object_type=ObjectType.TABLE,
            name="B",
        )
        dep = Dependency(
            source_id="Z_A",
            target_id="Z_B",
            dependency_type=DependencyType.READS_FROM,
        )
        result = ScanResult(
            source_system="DEV",
            objects=[obj1, obj2],
            dependencies=[dep],
        )
        output_dir = tmp_path / "output"
        write_scan_output(result, output_dir)
        graph = json.loads((output_dir / "graph.json").read_text())
        assert len(graph["edges"]) == 1
        edge = graph["edges"][0]
        assert edge["source"] == "Z_A"
        assert edge["target"] == "Z_B"
        assert edge["type"] == "reads_from"

    def test_compute_hash_called_before_write(self, tmp_path: Path):
        """Test that compute_hash is called for each object."""
        obj = ScannedObject(
            object_id="Z_TEST",
            object_type=ObjectType.TABLE,
            name="Test",
        )
        # content_hash should be None before writing
        assert obj.content_hash is None
        result = ScanResult(source_system="DEV", objects=[obj])
        output_dir = tmp_path / "output"
        write_scan_output(result, output_dir)
        # After write_scan_output, hash should be set
        assert obj.content_hash is not None
        assert len(obj.content_hash) == 64

    def test_multiple_objects_same_type(self, tmp_path: Path):
        """Test writing multiple objects of the same type."""
        obj1 = ScannedObject(
            object_id="Z_TABLE_1",
            object_type=ObjectType.TABLE,
            name="Table 1",
        )
        obj2 = ScannedObject(
            object_id="Z_TABLE_2",
            object_type=ObjectType.TABLE,
            name="Table 2",
        )
        result = ScanResult(source_system="DEV", objects=[obj1, obj2])
        output_dir = tmp_path / "output"
        write_scan_output(result, output_dir)
        assert (output_dir / "objects" / "table" / "Z_TABLE_1.md").exists()
        assert (output_dir / "objects" / "table" / "Z_TABLE_2.md").exists()
        graph = json.loads((output_dir / "graph.json").read_text())
        assert len(graph["nodes"]) == 2

    def test_empty_result(self, tmp_path: Path):
        """Test writing an empty scan result."""
        result = ScanResult(source_system="DEV")
        output_dir = tmp_path / "output"
        write_scan_output(result, output_dir)
        graph = json.loads((output_dir / "graph.json").read_text())
        assert graph["source_system"] == "DEV"
        assert graph["nodes"] == []
        assert graph["edges"] == []
