"""Tests for scanner data models."""

from datetime import datetime, timezone


from sap_doc_agent.scanner.models import (
    Dependency,
    DependencyType,
    ObjectType,
    ScanResult,
    ScannedObject,
)


class TestObjectType:
    """Test ObjectType enum."""

    def test_all_values_present(self):
        """Test that all required object types are defined."""
        required = [
            "adso",
            "composite",
            "transformation",
            "class",
            "fm",
            "table",
            "data_element",
            "domain",
            "infoobject",
            "process_chain",
            "data_source",
            "view",
            "report",
            "other",
        ]
        actual = [t.value for t in ObjectType]
        assert set(actual) == set(required)


class TestDependencyType:
    """Test DependencyType enum."""

    def test_all_values_present(self):
        """Test that all required dependency types are defined."""
        required = [
            "reads_from",
            "writes_to",
            "calls",
            "references",
            "contains",
            "depends_on",
        ]
        actual = [t.value for t in DependencyType]
        assert set(actual) == set(required)


class TestScannedObject:
    """Test ScannedObject model."""

    def test_object_creation(self):
        """Test basic object creation and field access."""
        obj = ScannedObject(
            object_id="Z_ADSO_TEST",
            object_type=ObjectType.ADSO,
            name="Test ADSO",
            description="A test ADSO",
            package="Z_PACKAGE",
            owner="ADMIN",
            source_system="DEV",
            technical_name="Z_ADSO_TEST",
            layer="SEMANTICS",
        )
        assert obj.object_id == "Z_ADSO_TEST"
        assert obj.object_type == ObjectType.ADSO
        assert obj.name == "Test ADSO"
        assert obj.description == "A test ADSO"
        assert obj.package == "Z_PACKAGE"
        assert obj.owner == "ADMIN"
        assert obj.source_system == "DEV"
        assert obj.technical_name == "Z_ADSO_TEST"
        assert obj.layer == "SEMANTICS"

    def test_default_scanned_at(self):
        """Test that scanned_at defaults to current UTC time."""
        before = datetime.now(timezone.utc)
        obj = ScannedObject(object_id="TEST", object_type=ObjectType.TABLE, name="Test Table")
        after = datetime.now(timezone.utc)
        assert before <= obj.scanned_at <= after

    def test_compute_hash_returns_hex(self):
        """Test that compute_hash returns a 64-character hex string."""
        obj = ScannedObject(
            object_id="Z_TEST",
            object_type=ObjectType.TABLE,
            name="Test",
        )
        hash_val = obj.compute_hash()
        assert len(hash_val) == 64
        assert all(c in "0123456789abcdef" for c in hash_val)

    def test_compute_hash_stored_in_content_hash(self):
        """Test that compute_hash stores result in content_hash."""
        obj = ScannedObject(
            object_id="Z_TEST",
            object_type=ObjectType.TABLE,
            name="Test",
        )
        hash_val = obj.compute_hash()
        assert obj.content_hash == hash_val

    def test_identical_objects_same_hash(self):
        """Test that identical objects produce the same hash."""
        obj1 = ScannedObject(
            object_id="Z_TEST",
            object_type=ObjectType.TABLE,
            name="Test",
            description="Desc",
            source_code="SELECT * FROM table",
            metadata={"key": "value"},
        )
        obj2 = ScannedObject(
            object_id="Z_TEST",
            object_type=ObjectType.TABLE,
            name="Test",
            description="Desc",
            source_code="SELECT * FROM table",
            metadata={"key": "value"},
        )
        assert obj1.compute_hash() == obj2.compute_hash()

    def test_different_objects_different_hash(self):
        """Test that different objects produce different hashes."""
        obj1 = ScannedObject(
            object_id="Z_TEST1",
            object_type=ObjectType.TABLE,
            name="Test1",
        )
        obj2 = ScannedObject(
            object_id="Z_TEST2",
            object_type=ObjectType.TABLE,
            name="Test2",
        )
        assert obj1.compute_hash() != obj2.compute_hash()

    def test_default_metadata_empty_dict(self):
        """Test that metadata defaults to empty dict."""
        obj = ScannedObject(
            object_id="Z_TEST",
            object_type=ObjectType.TABLE,
            name="Test",
        )
        assert obj.metadata == {}

    def test_content_hash_initially_none(self):
        """Test that content_hash is None until compute_hash is called."""
        obj = ScannedObject(
            object_id="Z_TEST",
            object_type=ObjectType.TABLE,
            name="Test",
        )
        assert obj.content_hash is None


class TestDependency:
    """Test Dependency model."""

    def test_dependency_creation(self):
        """Test basic dependency creation."""
        dep = Dependency(
            source_id="Z_ADSO_1",
            target_id="Z_ADSO_2",
            dependency_type=DependencyType.READS_FROM,
        )
        assert dep.source_id == "Z_ADSO_1"
        assert dep.target_id == "Z_ADSO_2"
        assert dep.dependency_type == DependencyType.READS_FROM

    def test_dependency_with_metadata(self):
        """Test dependency with metadata."""
        dep = Dependency(
            source_id="Z_ADSO_1",
            target_id="Z_ADSO_2",
            dependency_type=DependencyType.READS_FROM,
            metadata={"field": "value"},
        )
        assert dep.metadata == {"field": "value"}

    def test_default_metadata_empty_dict(self):
        """Test that metadata defaults to empty dict."""
        dep = Dependency(
            source_id="Z_ADSO_1",
            target_id="Z_ADSO_2",
            dependency_type=DependencyType.READS_FROM,
        )
        assert dep.metadata == {}


class TestScanResult:
    """Test ScanResult model."""

    def test_scan_result_creation(self):
        """Test basic ScanResult creation."""
        result = ScanResult(source_system="DEV")
        assert result.source_system == "DEV"
        assert result.objects == []
        assert result.dependencies == []

    def test_scan_result_with_objects_and_deps(self):
        """Test ScanResult with objects and dependencies."""
        obj1 = ScannedObject(
            object_id="Z_ADSO_1",
            object_type=ObjectType.ADSO,
            name="ADSO 1",
        )
        obj2 = ScannedObject(
            object_id="Z_ADSO_2",
            object_type=ObjectType.ADSO,
            name="ADSO 2",
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
        assert len(result.objects) == 2
        assert len(result.dependencies) == 1

    def test_get_object_found(self):
        """Test get_object returns object when found."""
        obj = ScannedObject(
            object_id="Z_TEST",
            object_type=ObjectType.TABLE,
            name="Test",
        )
        result = ScanResult(source_system="DEV", objects=[obj])
        found = result.get_object("Z_TEST")
        assert found is not None
        assert found.object_id == "Z_TEST"

    def test_get_object_not_found(self):
        """Test get_object returns None when not found."""
        result = ScanResult(source_system="DEV")
        found = result.get_object("NONEXISTENT")
        assert found is None

    def test_get_dependencies_of_filters_by_source(self):
        """Test get_dependencies_of filters by source_id."""
        dep1 = Dependency(
            source_id="Z_ADSO_1",
            target_id="Z_ADSO_2",
            dependency_type=DependencyType.READS_FROM,
        )
        dep2 = Dependency(
            source_id="Z_ADSO_1",
            target_id="Z_ADSO_3",
            dependency_type=DependencyType.WRITES_TO,
        )
        dep3 = Dependency(
            source_id="Z_ADSO_2",
            target_id="Z_ADSO_4",
            dependency_type=DependencyType.READS_FROM,
        )
        result = ScanResult(
            source_system="DEV",
            dependencies=[dep1, dep2, dep3],
        )
        deps_of_1 = result.get_dependencies_of("Z_ADSO_1")
        assert len(deps_of_1) == 2
        assert all(d.source_id == "Z_ADSO_1" for d in deps_of_1)
        assert deps_of_1[0].target_id == "Z_ADSO_2"
        assert deps_of_1[1].target_id == "Z_ADSO_3"

    def test_get_dependencies_of_no_matches(self):
        """Test get_dependencies_of returns empty list when no matches."""
        result = ScanResult(source_system="DEV")
        deps = result.get_dependencies_of("NONEXISTENT")
        assert deps == []
