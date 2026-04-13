"""
Data models for scanner output.

Represents scanned SAP objects, their dependencies, and scan metadata.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ObjectType(str, Enum):
    """SAP object types that can be scanned."""

    ADSO = "adso"
    COMPOSITE = "composite"
    TRANSFORMATION = "transformation"
    CLASS = "class"
    FM = "fm"
    TABLE = "table"
    DATA_ELEMENT = "data_element"
    DOMAIN = "domain"
    INFOOBJECT = "infoobject"
    PROCESS_CHAIN = "process_chain"
    DATA_SOURCE = "data_source"
    VIEW = "view"
    REPORT = "report"
    OTHER = "other"


class DependencyType(str, Enum):
    """Types of dependencies between objects."""

    READS_FROM = "reads_from"
    WRITES_TO = "writes_to"
    CALLS = "calls"
    REFERENCES = "references"
    CONTAINS = "contains"
    DEPENDS_ON = "depends_on"


class ScannedObject(BaseModel):
    """Represents a scanned SAP object."""

    object_id: str
    object_type: ObjectType
    name: str
    description: str = ""
    package: str = ""
    owner: str = ""
    source_system: str = ""
    technical_name: str = ""
    layer: str = ""
    source_code: str = ""
    metadata: dict = Field(default_factory=dict)
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    content_hash: Optional[str] = None

    def compute_hash(self) -> str:
        """
        Compute SHA-256 hash of object content.

        Hash is based on: object_id, object_type, name, description, source_code, metadata.
        Stores result in content_hash and returns it.
        """
        data = {
            "object_id": self.object_id,
            "object_type": self.object_type.value,
            "name": self.name,
            "description": self.description,
            "source_code": self.source_code,
            "metadata": self.metadata,
        }
        json_str = json.dumps(data, sort_keys=True, separators=(",", ":"))
        hash_val = hashlib.sha256(json_str.encode()).hexdigest()
        self.content_hash = hash_val
        return hash_val


class Dependency(BaseModel):
    """Represents a dependency between two objects."""

    source_id: str
    target_id: str
    dependency_type: DependencyType
    metadata: dict = Field(default_factory=dict)


class ScanResult(BaseModel):
    """Results of a scan operation."""

    source_system: str
    objects: list[ScannedObject] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def get_object(self, object_id: str) -> Optional[ScannedObject]:
        """Get an object by ID. Returns None if not found."""
        for obj in self.objects:
            if obj.object_id == object_id:
                return obj
        return None

    def get_dependencies_of(self, object_id: str) -> list[Dependency]:
        """Get all dependencies where source_id matches the given object_id."""
        return [dep for dep in self.dependencies if dep.source_id == object_id]
