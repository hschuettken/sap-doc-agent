# Plan B: Scanners — ABAP + DSP + Orchestrator

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the SAP extraction layer — ABAP scanner programs for BW/4HANA, a Python DSP scanner using the Datasphere REST API, a unified output format, and a Scanner Orchestrator that merges and deduplicates results from both sources.

**Architecture:** ABAP programs scan BW/4HANA and push structured files to Git. The DSP scanner calls the Datasphere REST API (same endpoints as sap-datasphere-mcp). The Scanner Orchestrator merges output from both, deduplicates objects, builds the dependency graph, and writes the final output.

**Tech Stack:** ABAP (BW/4HANA programs), Python 3.12, httpx (DSP REST API), pydantic (output models), pytest

**Note:** ABAP programs are written as `.abap` files in the repo. They cannot be tested locally — they'll be imported into the demo BW system later. The DSP scanner and orchestrator are fully testable Python.

---

## File Structure

```
sap-doc-agent/
├── setup/
│   └── abap/
│       ├── z_doc_agent_setup.abap       # Creates config + result tables
│       ├── z_doc_agent_scan.abap        # Dependency crawler
│       └── README.md                    # Installation instructions
│
├── src/sap_doc_agent/
│   ├── scanner/
│   │   ├── __init__.py
│   │   ├── models.py                    # ScannedObject, Dependency, ScanResult
│   │   ├── output.py                    # Write markdown + graph.json
│   │   ├── dsp_scanner.py               # Datasphere REST API scanner
│   │   ├── dsp_auth.py                  # OAuth 2.0 client credentials
│   │   └── orchestrator.py              # Merge BW + DSP, deduplicate
│   ...
│
├── tests/
│   ├── test_scanner_models.py
│   ├── test_scanner_output.py
│   ├── test_dsp_auth.py
│   ├── test_dsp_scanner.py
│   └── test_orchestrator.py
│
└── output/                              # Scanner writes here
    ├── objects/
    │   ├── adso/
    │   ├── transformation/
    │   ├── class/
    │   └── ...
    └── graph.json
```

---

### Task 1: Scanner data models

**Files:**
- Create: `src/sap_doc_agent/scanner/__init__.py`
- Create: `src/sap_doc_agent/scanner/models.py`
- Create: `tests/test_scanner_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scanner_models.py
import pytest
from datetime import datetime, timezone
from sap_doc_agent.scanner.models import (
    ScannedObject, Dependency, ScanResult, ObjectType, DependencyType,
)


def test_scanned_object_creation():
    obj = ScannedObject(
        object_id="ADSO_SALES",
        object_type=ObjectType.ADSO,
        name="ADSO_SALES",
        description="Sales data store",
        package="ZSALES",
        owner="DEVELOPER1",
        source_system="Horvath BW/4",
        technical_name="ADSO_SALES",
        layer="raw",
        source_code="",
        metadata={"rows": 1000000},
    )
    assert obj.object_id == "ADSO_SALES"
    assert obj.object_type == ObjectType.ADSO
    assert obj.content_hash is None


def test_scanned_object_compute_hash():
    obj = ScannedObject(
        object_id="ADSO_SALES",
        object_type=ObjectType.ADSO,
        name="ADSO_SALES",
        description="Sales data store",
        source_system="BW4",
    )
    h = obj.compute_hash()
    assert h is not None
    assert len(h) == 64  # SHA-256 hex
    assert obj.content_hash == h
    # Same content = same hash
    obj2 = ScannedObject(
        object_id="ADSO_SALES",
        object_type=ObjectType.ADSO,
        name="ADSO_SALES",
        description="Sales data store",
        source_system="BW4",
    )
    assert obj2.compute_hash() == h


def test_dependency_creation():
    dep = Dependency(
        source_id="TRFN_001",
        target_id="ADSO_SALES",
        dependency_type=DependencyType.READS_FROM,
    )
    assert dep.source_id == "TRFN_001"
    assert dep.dependency_type == DependencyType.READS_FROM


def test_scan_result():
    obj1 = ScannedObject(
        object_id="ADSO_SALES", object_type=ObjectType.ADSO,
        name="ADSO_SALES", source_system="BW4",
    )
    obj2 = ScannedObject(
        object_id="TRFN_001", object_type=ObjectType.TRANSFORMATION,
        name="TRFN_001", source_system="BW4",
    )
    dep = Dependency(source_id="TRFN_001", target_id="ADSO_SALES",
                     dependency_type=DependencyType.WRITES_TO)
    result = ScanResult(
        source_system="Horvath BW/4",
        objects=[obj1, obj2],
        dependencies=[dep],
    )
    assert len(result.objects) == 2
    assert len(result.dependencies) == 1


def test_scan_result_get_object():
    obj = ScannedObject(
        object_id="ADSO_SALES", object_type=ObjectType.ADSO,
        name="ADSO_SALES", source_system="BW4",
    )
    result = ScanResult(source_system="BW4", objects=[obj], dependencies=[])
    assert result.get_object("ADSO_SALES") == obj
    assert result.get_object("NONEXISTENT") is None


def test_scan_result_get_dependencies_of():
    dep1 = Dependency(source_id="TRFN_001", target_id="ADSO_SALES",
                      dependency_type=DependencyType.WRITES_TO)
    dep2 = Dependency(source_id="TRFN_001", target_id="ZCL_HELPER",
                      dependency_type=DependencyType.CALLS)
    dep3 = Dependency(source_id="ADSO_SALES", target_id="CP_REVENUE",
                      dependency_type=DependencyType.READS_FROM)
    result = ScanResult(source_system="BW4", objects=[], dependencies=[dep1, dep2, dep3])
    trfn_deps = result.get_dependencies_of("TRFN_001")
    assert len(trfn_deps) == 2


def test_object_types_cover_spec():
    expected = {"adso", "composite", "transformation", "class", "fm",
                "table", "data_element", "domain", "infoobject",
                "process_chain", "data_source", "view", "report", "other"}
    actual = {t.value for t in ObjectType}
    assert expected.issubset(actual)


def test_dependency_types():
    expected = {"reads_from", "writes_to", "calls", "references", "contains", "depends_on"}
    actual = {t.value for t in DependencyType}
    assert expected.issubset(actual)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/test_scanner_models.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement models.py**

```python
# src/sap_doc_agent/scanner/models.py
"""Data models for scanner output.

These models represent the objects and dependencies discovered by both
the BW/4HANA ABAP scanner and the Datasphere MCP scanner. They are the
common data format that the Scanner Orchestrator works with.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ObjectType(str, Enum):
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
    READS_FROM = "reads_from"
    WRITES_TO = "writes_to"
    CALLS = "calls"
    REFERENCES = "references"
    CONTAINS = "contains"
    DEPENDS_ON = "depends_on"


class ScannedObject(BaseModel):
    """A single SAP object discovered by a scanner."""
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
    metadata: dict[str, Any] = Field(default_factory=dict)
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    content_hash: Optional[str] = None

    def compute_hash(self) -> str:
        """Compute SHA-256 hash of content for change detection."""
        content = json.dumps({
            "object_id": self.object_id,
            "object_type": self.object_type.value,
            "name": self.name,
            "description": self.description,
            "source_code": self.source_code,
            "metadata": self.metadata,
        }, sort_keys=True)
        self.content_hash = hashlib.sha256(content.encode()).hexdigest()
        return self.content_hash


class Dependency(BaseModel):
    """A dependency relationship between two objects."""
    source_id: str
    target_id: str
    dependency_type: DependencyType
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScanResult(BaseModel):
    """Complete result of a scan run."""
    source_system: str
    objects: list[ScannedObject] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def get_object(self, object_id: str) -> Optional[ScannedObject]:
        for obj in self.objects:
            if obj.object_id == object_id:
                return obj
        return None

    def get_dependencies_of(self, object_id: str) -> list[Dependency]:
        return [d for d in self.dependencies if d.source_id == object_id]
```

- [ ] **Step 4: Create empty __init__.py**

```python
# src/sap_doc_agent/scanner/__init__.py
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_scanner_models.py -v`
Expected: All 8 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/sap_doc_agent/scanner/ tests/test_scanner_models.py
git commit -m "feat: scanner data models (ScannedObject, Dependency, ScanResult)"
```

---

### Task 2: Scanner output writer (Markdown + graph.json)

**Files:**
- Create: `src/sap_doc_agent/scanner/output.py`
- Create: `tests/test_scanner_output.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scanner_output.py
import json
import pytest
from pathlib import Path
from sap_doc_agent.scanner.models import (
    ScannedObject, Dependency, ScanResult, ObjectType, DependencyType,
)
from sap_doc_agent.scanner.output import write_scan_output, render_object_markdown


@pytest.fixture
def sample_result():
    obj1 = ScannedObject(
        object_id="ADSO_SALES", object_type=ObjectType.ADSO,
        name="ADSO_SALES", description="Sales actuals data store",
        package="ZSALES", owner="DEV1", source_system="BW4",
        technical_name="ADSO_SALES", layer="raw",
    )
    obj2 = ScannedObject(
        object_id="TRFN_SALES_LOAD", object_type=ObjectType.TRANSFORMATION,
        name="Load Sales", description="Loads sales from source",
        package="ZSALES", owner="DEV1", source_system="BW4",
        source_code="SELECT * FROM /BIC/ASALES00.",
    )
    dep = Dependency(
        source_id="TRFN_SALES_LOAD", target_id="ADSO_SALES",
        dependency_type=DependencyType.WRITES_TO,
    )
    return ScanResult(source_system="Horvath BW/4", objects=[obj1, obj2], dependencies=[dep])


def test_render_object_markdown():
    obj = ScannedObject(
        object_id="ADSO_SALES", object_type=ObjectType.ADSO,
        name="ADSO_SALES", description="Sales actuals",
        package="ZSALES", owner="DEV1", source_system="BW4",
        layer="raw", metadata={"rows": 1000000},
    )
    md = render_object_markdown(obj)
    assert "# ADSO_SALES" in md
    assert "object_id: ADSO_SALES" in md  # YAML frontmatter
    assert "object_type: adso" in md
    assert "Sales actuals" in md
    assert "ZSALES" in md


def test_render_object_with_source_code():
    obj = ScannedObject(
        object_id="TRFN_001", object_type=ObjectType.TRANSFORMATION,
        name="Load Sales", source_system="BW4",
        source_code="SELECT * FROM sales_table.",
    )
    md = render_object_markdown(obj)
    assert "```abap" in md
    assert "SELECT * FROM sales_table." in md


def test_write_scan_output_creates_files(tmp_path: Path, sample_result):
    write_scan_output(sample_result, output_dir=tmp_path)
    # Check object files
    adso_file = tmp_path / "objects" / "adso" / "ADSO_SALES.md"
    assert adso_file.exists()
    assert "ADSO_SALES" in adso_file.read_text()
    trfn_file = tmp_path / "objects" / "transformation" / "TRFN_SALES_LOAD.md"
    assert trfn_file.exists()


def test_write_scan_output_creates_graph(tmp_path: Path, sample_result):
    write_scan_output(sample_result, output_dir=tmp_path)
    graph_file = tmp_path / "graph.json"
    assert graph_file.exists()
    graph = json.loads(graph_file.read_text())
    assert "nodes" in graph
    assert "edges" in graph
    assert len(graph["nodes"]) == 2
    assert len(graph["edges"]) == 1
    # Check edge structure
    edge = graph["edges"][0]
    assert edge["source"] == "TRFN_SALES_LOAD"
    assert edge["target"] == "ADSO_SALES"
    assert edge["type"] == "writes_to"


def test_write_scan_output_node_has_metadata(tmp_path: Path, sample_result):
    write_scan_output(sample_result, output_dir=tmp_path)
    graph = json.loads((tmp_path / "graph.json").read_text())
    node = next(n for n in graph["nodes"] if n["id"] == "ADSO_SALES")
    assert node["type"] == "adso"
    assert node["name"] == "ADSO_SALES"
    assert node["source_system"] == "BW4"


def test_markdown_frontmatter_is_valid_yaml():
    import yaml
    obj = ScannedObject(
        object_id="TEST_OBJ", object_type=ObjectType.TABLE,
        name="Test Table", description="A test", source_system="BW4",
    )
    md = render_object_markdown(obj)
    # Extract frontmatter between --- markers
    parts = md.split("---")
    assert len(parts) >= 3, "Missing YAML frontmatter delimiters"
    frontmatter = yaml.safe_load(parts[1])
    assert frontmatter["object_id"] == "TEST_OBJ"
    assert frontmatter["object_type"] == "table"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scanner_output.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement output.py**

```python
# src/sap_doc_agent/scanner/output.py
"""Write scanner results to structured markdown files and graph.json.

Output format:
- One .md file per object in output/objects/<type>/<id>.md
- YAML frontmatter with structured metadata
- graph.json with nodes and edges for the dependency graph
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from sap_doc_agent.scanner.models import ScanResult, ScannedObject


def render_object_markdown(obj: ScannedObject) -> str:
    """Render a scanned object as a markdown document with YAML frontmatter."""
    frontmatter = {
        "object_id": obj.object_id,
        "object_type": obj.object_type.value,
        "name": obj.name,
        "source_system": obj.source_system,
        "package": obj.package,
        "owner": obj.owner,
        "layer": obj.layer,
        "technical_name": obj.technical_name,
        "scanned_at": obj.scanned_at.isoformat(),
    }
    if obj.content_hash:
        frontmatter["content_hash"] = obj.content_hash
    if obj.metadata:
        frontmatter["metadata"] = obj.metadata

    parts = [
        "---",
        yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True).strip(),
        "---",
        "",
        f"# {obj.name}",
        "",
    ]

    if obj.description:
        parts.extend([obj.description, ""])

    parts.extend([
        "## Details",
        "",
        f"- **Type:** {obj.object_type.value}",
        f"- **Package:** {obj.package}" if obj.package else "",
        f"- **Owner:** {obj.owner}" if obj.owner else "",
        f"- **Layer:** {obj.layer}" if obj.layer else "",
        f"- **Source System:** {obj.source_system}",
        "",
    ])

    if obj.source_code:
        parts.extend([
            "## Source Code",
            "",
            "```abap",
            obj.source_code,
            "```",
            "",
        ])

    # Filter empty lines from conditional fields
    return "\n".join(line for line in parts if line is not None)


def write_scan_output(result: ScanResult, output_dir: Path) -> None:
    """Write scan results to output directory.

    Creates:
    - output_dir/objects/<type>/<id>.md for each object
    - output_dir/graph.json with the dependency graph
    """
    output_dir = Path(output_dir)
    objects_dir = output_dir / "objects"

    # Write object markdown files
    for obj in result.objects:
        obj.compute_hash()
        type_dir = objects_dir / obj.object_type.value
        type_dir.mkdir(parents=True, exist_ok=True)
        md = render_object_markdown(obj)
        (type_dir / f"{obj.object_id}.md").write_text(md)

    # Write dependency graph
    graph = {
        "source_system": result.source_system,
        "scanned_at": result.scanned_at.isoformat(),
        "nodes": [
            {
                "id": obj.object_id,
                "name": obj.name,
                "type": obj.object_type.value,
                "source_system": obj.source_system,
                "layer": obj.layer,
                "package": obj.package,
            }
            for obj in result.objects
        ],
        "edges": [
            {
                "source": dep.source_id,
                "target": dep.target_id,
                "type": dep.dependency_type.value,
            }
            for dep in result.dependencies
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "graph.json").write_text(json.dumps(graph, indent=2))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scanner_output.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/sap_doc_agent/scanner/output.py tests/test_scanner_output.py
git commit -m "feat: scanner output writer (markdown + graph.json)"
```

---

### Task 3: DSP OAuth 2.0 authentication

**Files:**
- Create: `src/sap_doc_agent/scanner/dsp_auth.py`
- Create: `tests/test_dsp_auth.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dsp_auth.py
import pytest
import httpx
import respx
import time
from sap_doc_agent.scanner.dsp_auth import DSPAuth


@pytest.fixture
def auth():
    return DSPAuth(
        client_id="test-client-id",
        client_secret="test-client-secret",
        token_url="http://test-dsp/oauth/token",
    )


@pytest.mark.asyncio
@respx.mock
async def test_get_token(auth):
    respx.post("http://test-dsp/oauth/token").mock(
        return_value=httpx.Response(200, json={
            "access_token": "test-access-token-123",
            "token_type": "bearer",
            "expires_in": 3600,
        })
    )
    token = await auth.get_token()
    assert token == "test-access-token-123"


@pytest.mark.asyncio
@respx.mock
async def test_token_is_cached(auth):
    respx.post("http://test-dsp/oauth/token").mock(
        return_value=httpx.Response(200, json={
            "access_token": "cached-token",
            "token_type": "bearer",
            "expires_in": 3600,
        })
    )
    token1 = await auth.get_token()
    token2 = await auth.get_token()
    assert token1 == token2
    assert respx.calls.call_count == 1  # Only one HTTP call


@pytest.mark.asyncio
@respx.mock
async def test_token_refresh_on_expiry(auth):
    call_count = 0
    def handler(request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={
            "access_token": f"token-{call_count}",
            "token_type": "bearer",
            "expires_in": 0,  # Immediately expired
        })
    respx.post("http://test-dsp/oauth/token").mock(side_effect=handler)
    token1 = await auth.get_token()
    # Force expiry
    auth._expires_at = time.time() - 1
    token2 = await auth.get_token()
    assert token1 != token2
    assert call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_auth_failure_raises(auth):
    respx.post("http://test-dsp/oauth/token").mock(
        return_value=httpx.Response(401, json={"error": "invalid_client"})
    )
    with pytest.raises(Exception, match="OAuth"):
        await auth.get_token()


@pytest.mark.asyncio
@respx.mock
async def test_get_headers(auth):
    respx.post("http://test-dsp/oauth/token").mock(
        return_value=httpx.Response(200, json={
            "access_token": "header-token",
            "token_type": "bearer",
            "expires_in": 3600,
        })
    )
    headers = await auth.get_headers()
    assert headers["Authorization"] == "Bearer header-token"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dsp_auth.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement dsp_auth.py**

```python
# src/sap_doc_agent/scanner/dsp_auth.py
"""OAuth 2.0 client credentials authentication for SAP Datasphere.

Handles token acquisition, caching, and automatic refresh.
Same auth flow as sap-datasphere-mcp.
"""
from __future__ import annotations

import base64
import logging
import time

import httpx

logger = logging.getLogger(__name__)

# Refresh 5 minutes before expiry
REFRESH_BUFFER_SECONDS = 300


class DSPAuth:
    """OAuth 2.0 client credentials flow for SAP Datasphere."""

    def __init__(self, client_id: str, client_secret: str, token_url: str, timeout: float = 30.0):
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_url = token_url
        self._timeout = timeout
        self._access_token: str | None = None
        self._expires_at: float = 0

    async def get_token(self) -> str:
        """Get a valid access token, refreshing if needed."""
        if self._access_token and time.time() < self._expires_at:
            return self._access_token
        await self._refresh_token()
        return self._access_token

    async def get_headers(self) -> dict[str, str]:
        """Get HTTP headers with Bearer token."""
        token = await self.get_token()
        return {"Authorization": f"Bearer {token}"}

    async def _refresh_token(self) -> None:
        """Request a new token from the OAuth endpoint."""
        credentials = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                self._token_url,
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "client_credentials"},
            )
            if resp.status_code != 200:
                raise RuntimeError(f"OAuth token request failed ({resp.status_code}): {resp.text}")

            data = resp.json()
            self._access_token = data["access_token"]
            expires_in = data.get("expires_in", 3600)
            self._expires_at = time.time() + expires_in - REFRESH_BUFFER_SECONDS
            logger.info("DSP OAuth token acquired, expires in %ds", expires_in)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dsp_auth.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/sap_doc_agent/scanner/dsp_auth.py tests/test_dsp_auth.py
git commit -m "feat: DSP OAuth 2.0 client credentials authentication"
```

---

### Task 4: DSP Scanner

**Files:**
- Create: `src/sap_doc_agent/scanner/dsp_scanner.py`
- Create: `tests/test_dsp_scanner.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dsp_scanner.py
import pytest
import httpx
import respx
from sap_doc_agent.scanner.dsp_scanner import DSPScanner
from sap_doc_agent.scanner.dsp_auth import DSPAuth
from sap_doc_agent.scanner.models import ObjectType


@pytest.fixture
def auth():
    return DSPAuth(
        client_id="test-id",
        client_secret="test-secret",
        token_url="http://test-dsp/oauth/token",
    )


@pytest.fixture
def scanner(auth):
    return DSPScanner(
        base_url="http://test-dsp.cloud.sap",
        auth=auth,
        spaces=["SAC_PLANNING"],
    )


@respx.mock
def _mock_token():
    """Helper to mock OAuth token endpoint."""
    respx.post("http://test-dsp/oauth/token").mock(
        return_value=httpx.Response(200, json={
            "access_token": "test-token",
            "token_type": "bearer",
            "expires_in": 3600,
        })
    )


@pytest.mark.asyncio
@respx.mock
async def test_list_spaces(scanner):
    _mock_token()
    respx.get("http://test-dsp.cloud.sap/api/v1/dwc/catalog/spaces").mock(
        return_value=httpx.Response(200, json={
            "value": [
                {"Name": "SAC_PLANNING", "Description": "Planning space"},
                {"Name": "SAP_ADMIN", "Description": "Admin space"},
            ]
        })
    )
    spaces = await scanner.list_spaces()
    assert len(spaces) == 2
    assert spaces[0]["Name"] == "SAC_PLANNING"


@pytest.mark.asyncio
@respx.mock
async def test_get_space_objects(scanner):
    _mock_token()
    respx.get("http://test-dsp.cloud.sap/api/v1/dwc/catalog/assets").mock(
        return_value=httpx.Response(200, json={
            "value": [
                {
                    "Name": "V_SALES_RAW",
                    "Type": "VIEW",
                    "Description": "Raw sales view",
                    "SpaceName": "SAC_PLANNING",
                    "CreatedBy": "DEV1",
                },
                {
                    "Name": "T_CUSTOMERS",
                    "Type": "LOCAL_TABLE",
                    "Description": "Customer master",
                    "SpaceName": "SAC_PLANNING",
                    "CreatedBy": "DEV1",
                },
            ]
        })
    )
    objects = await scanner.get_space_objects("SAC_PLANNING")
    assert len(objects) == 2


@pytest.mark.asyncio
@respx.mock
async def test_scan_produces_result(scanner):
    _mock_token()
    respx.get("http://test-dsp.cloud.sap/api/v1/dwc/catalog/assets").mock(
        return_value=httpx.Response(200, json={
            "value": [
                {
                    "Name": "V_SALES_RAW",
                    "Type": "VIEW",
                    "Description": "Raw sales",
                    "SpaceName": "SAC_PLANNING",
                    "CreatedBy": "DEV1",
                },
            ]
        })
    )
    result = await scanner.scan()
    assert result.source_system == "DSP"
    assert len(result.objects) == 1
    assert result.objects[0].object_type == ObjectType.VIEW
    assert result.objects[0].name == "V_SALES_RAW"


@pytest.mark.asyncio
@respx.mock
async def test_scan_filters_namespace(scanner):
    scanner._namespace_filter = ["V_*"]
    _mock_token()
    respx.get("http://test-dsp.cloud.sap/api/v1/dwc/catalog/assets").mock(
        return_value=httpx.Response(200, json={
            "value": [
                {"Name": "V_SALES", "Type": "VIEW", "Description": "", "SpaceName": "SAC_PLANNING", "CreatedBy": ""},
                {"Name": "SAP_STANDARD_VIEW", "Type": "VIEW", "Description": "", "SpaceName": "SAC_PLANNING", "CreatedBy": ""},
            ]
        })
    )
    result = await scanner.scan()
    assert len(result.objects) == 1
    assert result.objects[0].name == "V_SALES"


@pytest.mark.asyncio
@respx.mock
async def test_dsp_type_mapping(scanner):
    _mock_token()
    respx.get("http://test-dsp.cloud.sap/api/v1/dwc/catalog/assets").mock(
        return_value=httpx.Response(200, json={
            "value": [
                {"Name": "V_1", "Type": "VIEW", "Description": "", "SpaceName": "SAC_PLANNING", "CreatedBy": ""},
                {"Name": "T_1", "Type": "LOCAL_TABLE", "Description": "", "SpaceName": "SAC_PLANNING", "CreatedBy": ""},
                {"Name": "RF_1", "Type": "REPLICATION_FLOW", "Description": "", "SpaceName": "SAC_PLANNING", "CreatedBy": ""},
            ]
        })
    )
    result = await scanner.scan()
    types = {o.name: o.object_type for o in result.objects}
    assert types["V_1"] == ObjectType.VIEW
    assert types["T_1"] == ObjectType.TABLE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dsp_scanner.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement dsp_scanner.py**

```python
# src/sap_doc_agent/scanner/dsp_scanner.py
"""SAP Datasphere scanner.

Scans Datasphere spaces via the REST API (same endpoints as sap-datasphere-mcp).
Discovers views, tables, data flows, and their metadata.
"""
from __future__ import annotations

import fnmatch
import logging
from typing import Any

import httpx

from sap_doc_agent.scanner.dsp_auth import DSPAuth
from sap_doc_agent.scanner.models import (
    Dependency, DependencyType, ObjectType, ScanResult, ScannedObject,
)

logger = logging.getLogger(__name__)

# Map DSP asset types to our ObjectType enum
DSP_TYPE_MAP = {
    "VIEW": ObjectType.VIEW,
    "SQL_VIEW": ObjectType.VIEW,
    "GRAPHICAL_VIEW": ObjectType.VIEW,
    "LOCAL_TABLE": ObjectType.TABLE,
    "REMOTE_TABLE": ObjectType.TABLE,
    "REPLICATION_FLOW": ObjectType.DATA_SOURCE,
    "DATA_FLOW": ObjectType.TRANSFORMATION,
    "TRANSFORMATION_FLOW": ObjectType.TRANSFORMATION,
    "ANALYTIC_MODEL": ObjectType.VIEW,
    "TASK_CHAIN": ObjectType.PROCESS_CHAIN,
}


class DSPScanner:
    """Scans SAP Datasphere via REST API."""

    def __init__(
        self,
        base_url: str,
        auth: DSPAuth,
        spaces: list[str],
        namespace_filter: list[str] | None = None,
        timeout: float = 30.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._auth = auth
        self._spaces = spaces
        self._namespace_filter = namespace_filter
        self._timeout = timeout

    async def list_spaces(self) -> list[dict[str, Any]]:
        """List all available spaces."""
        data = await self._get("/api/v1/dwc/catalog/spaces")
        return data.get("value", [])

    async def get_space_objects(self, space: str) -> list[dict[str, Any]]:
        """Get all objects in a space."""
        data = await self._get(
            "/api/v1/dwc/catalog/assets",
            params={"$filter": f"SpaceName eq '{space}'"},
        )
        return data.get("value", [])

    async def scan(self) -> ScanResult:
        """Run full scan across configured spaces."""
        all_objects: list[ScannedObject] = []
        all_deps: list[Dependency] = []

        for space in self._spaces:
            logger.info("Scanning DSP space: %s", space)
            raw_objects = await self.get_space_objects(space)

            for raw in raw_objects:
                name = raw.get("Name", "")

                # Apply namespace filter
                if self._namespace_filter and not any(
                    fnmatch.fnmatch(name, pattern) for pattern in self._namespace_filter
                ):
                    continue

                dsp_type = raw.get("Type", "OTHER")
                obj_type = DSP_TYPE_MAP.get(dsp_type, ObjectType.OTHER)

                obj = ScannedObject(
                    object_id=f"{space}.{name}",
                    object_type=obj_type,
                    name=name,
                    description=raw.get("Description", ""),
                    owner=raw.get("CreatedBy", ""),
                    source_system="DSP",
                    technical_name=name,
                    layer=self._infer_layer(name),
                    metadata={
                        "dsp_type": dsp_type,
                        "space": space,
                    },
                )
                all_objects.append(obj)

        return ScanResult(
            source_system="DSP",
            objects=all_objects,
            dependencies=all_deps,
        )

    def _infer_layer(self, name: str) -> str:
        """Infer architecture layer from naming convention."""
        if name.startswith("01_") or name.startswith("RAW_"):
            return "raw"
        if name.startswith("02_") or name.startswith("HARM_"):
            return "harmonized"
        if name.startswith("03_") or name.startswith("MART_"):
            return "mart"
        return ""

    async def _get(self, path: str, params: dict | None = None) -> dict:
        """Make an authenticated GET request to the DSP API."""
        headers = await self._auth.get_headers()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base_url}{path}",
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            return resp.json()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dsp_scanner.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/sap_doc_agent/scanner/dsp_scanner.py tests/test_dsp_scanner.py
git commit -m "feat: DSP scanner — Datasphere REST API scanner with type mapping"
```

---

### Task 5: Scanner Orchestrator

**Files:**
- Create: `src/sap_doc_agent/scanner/orchestrator.py`
- Create: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orchestrator.py
import pytest
from pathlib import Path
from sap_doc_agent.scanner.models import (
    ScannedObject, Dependency, ScanResult, ObjectType, DependencyType,
)
from sap_doc_agent.scanner.orchestrator import ScannerOrchestrator


@pytest.fixture
def bw_result():
    return ScanResult(
        source_system="BW4",
        objects=[
            ScannedObject(object_id="ADSO_SALES", object_type=ObjectType.ADSO,
                         name="ADSO_SALES", description="Sales from BW", source_system="BW4"),
            ScannedObject(object_id="ZCL_HELPER", object_type=ObjectType.CLASS,
                         name="ZCL_HELPER", description="Shared helper class", source_system="BW4"),
        ],
        dependencies=[
            Dependency(source_id="ADSO_SALES", target_id="ZCL_HELPER",
                      dependency_type=DependencyType.REFERENCES),
        ],
    )


@pytest.fixture
def dsp_result():
    return ScanResult(
        source_system="DSP",
        objects=[
            ScannedObject(object_id="SAC.V_SALES_MART", object_type=ObjectType.VIEW,
                         name="V_SALES_MART", description="Sales mart view", source_system="DSP"),
            ScannedObject(object_id="SAC.ZCL_HELPER", object_type=ObjectType.CLASS,
                         name="ZCL_HELPER", description="Shared helper (DSP ref)", source_system="DSP"),
        ],
        dependencies=[
            Dependency(source_id="SAC.V_SALES_MART", target_id="SAC.ZCL_HELPER",
                      dependency_type=DependencyType.REFERENCES),
        ],
    )


def test_merge_without_dedup(bw_result):
    orch = ScannerOrchestrator()
    merged = orch.merge([bw_result])
    assert len(merged.objects) == 2
    assert len(merged.dependencies) == 1
    assert merged.source_system == "merged"


def test_merge_two_sources(bw_result, dsp_result):
    orch = ScannerOrchestrator()
    merged = orch.merge([bw_result, dsp_result])
    assert len(merged.objects) == 4  # Before dedup
    assert len(merged.dependencies) == 2


def test_deduplicate_by_name(bw_result, dsp_result):
    orch = ScannerOrchestrator()
    merged = orch.merge([bw_result, dsp_result])
    deduped = orch.deduplicate(merged)
    # ZCL_HELPER appears in both — should be deduped to 1
    helper_objs = [o for o in deduped.objects if o.name == "ZCL_HELPER"]
    assert len(helper_objs) == 1
    assert len(deduped.objects) == 3  # ADSO_SALES, ZCL_HELPER, V_SALES_MART


def test_deduplicate_preserves_richer_description(bw_result, dsp_result):
    orch = ScannerOrchestrator()
    merged = orch.merge([bw_result, dsp_result])
    deduped = orch.deduplicate(merged)
    helper = next(o for o in deduped.objects if o.name == "ZCL_HELPER")
    # Should keep the richer description
    assert helper.description == "Shared helper class"


def test_deduplicate_remaps_dependencies(bw_result, dsp_result):
    orch = ScannerOrchestrator()
    merged = orch.merge([bw_result, dsp_result])
    deduped = orch.deduplicate(merged)
    # Dependency from DSP's V_SALES_MART -> ZCL_HELPER should be remapped
    target_ids = {d.target_id for d in deduped.dependencies}
    # All deps should reference existing object IDs
    obj_ids = {o.object_id for o in deduped.objects}
    for dep in deduped.dependencies:
        assert dep.source_id in obj_ids, f"Orphan source: {dep.source_id}"
        assert dep.target_id in obj_ids, f"Orphan target: {dep.target_id}"


def test_full_pipeline(bw_result, dsp_result, tmp_path: Path):
    orch = ScannerOrchestrator()
    merged = orch.merge([bw_result, dsp_result])
    deduped = orch.deduplicate(merged)
    from sap_doc_agent.scanner.output import write_scan_output
    write_scan_output(deduped, output_dir=tmp_path)
    assert (tmp_path / "graph.json").exists()
    assert (tmp_path / "objects" / "adso" / "ADSO_SALES.md").exists()
    assert (tmp_path / "objects" / "view" / "SAC.V_SALES_MART.md").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement orchestrator.py**

```python
# src/sap_doc_agent/scanner/orchestrator.py
"""Scanner Orchestrator — merges and deduplicates results from multiple scanners.

Takes ScanResults from BW/4HANA (via Git/file) and Datasphere (via API),
merges them into a unified object graph, deduplicates objects that appear
in both systems, and remaps dependency links.
"""
from __future__ import annotations

import logging

from sap_doc_agent.scanner.models import Dependency, ScanResult, ScannedObject

logger = logging.getLogger(__name__)


class ScannerOrchestrator:
    """Merges and deduplicates scan results from multiple sources."""

    def merge(self, results: list[ScanResult]) -> ScanResult:
        """Merge multiple scan results into one."""
        all_objects: list[ScannedObject] = []
        all_deps: list[Dependency] = []
        for r in results:
            all_objects.extend(r.objects)
            all_deps.extend(r.dependencies)
        return ScanResult(
            source_system="merged",
            objects=all_objects,
            dependencies=all_deps,
        )

    def deduplicate(self, result: ScanResult) -> ScanResult:
        """Deduplicate objects by name, keeping the richer version.

        When the same object name appears from multiple sources:
        1. Keep the one with the longer description (richer documentation)
        2. Remap all dependencies to use the surviving object's ID
        3. Remove duplicate dependencies
        """
        # Group objects by name
        by_name: dict[str, list[ScannedObject]] = {}
        for obj in result.objects:
            by_name.setdefault(obj.name, []).append(obj)

        # Pick the best version of each object and build ID remap
        deduped_objects: list[ScannedObject] = []
        id_remap: dict[str, str] = {}  # old_id -> surviving_id

        for name, versions in by_name.items():
            # Sort by description length (descending) to keep richest
            versions.sort(key=lambda o: len(o.description), reverse=True)
            winner = versions[0]
            deduped_objects.append(winner)

            # Map all other IDs to the winner
            for v in versions[1:]:
                id_remap[v.object_id] = winner.object_id
                logger.debug("Dedup: %s -> %s (kept %s)", v.object_id, winner.object_id, winner.source_system)

        # Remap dependencies
        deduped_deps: list[Dependency] = []
        seen_deps: set[tuple[str, str, str]] = set()
        for dep in result.dependencies:
            source = id_remap.get(dep.source_id, dep.source_id)
            target = id_remap.get(dep.target_id, dep.target_id)
            key = (source, target, dep.dependency_type.value)
            if key not in seen_deps:
                seen_deps.add(key)
                deduped_deps.append(Dependency(
                    source_id=source,
                    target_id=target,
                    dependency_type=dep.dependency_type,
                    metadata=dep.metadata,
                ))

        return ScanResult(
            source_system="merged",
            objects=deduped_objects,
            dependencies=deduped_deps,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_orchestrator.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest -v`
Expected: All tests pass (~80 total)

- [ ] **Step 6: Commit**

```bash
git add src/sap_doc_agent/scanner/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: scanner orchestrator — merge and deduplicate multi-source results"
```

---

### Task 6: ABAP scanner programs

**Files:**
- Create: `setup/abap/z_doc_agent_setup.abap`
- Create: `setup/abap/z_doc_agent_scan.abap`
- Create: `setup/abap/README.md`

Note: These are ABAP source files for import into a BW/4HANA system via SE38 or ADT. They cannot be tested locally. The ABAP follows standard patterns and references real SAP BW/4HANA tables.

- [ ] **Step 1: Create Z_DOC_AGENT_SETUP.abap**

Write an ABAP program that:
- Creates transparent table `ZDOC_AGENT_CFG` (transport backend, Git URL, auth token, scan scope)
- Creates transparent table `ZDOC_AGENT_SCAN` (object_key, object_type, description, last_scan, content_hash)
- Creates transparent table `ZDOC_AGENT_DEPS` (source_key, target_key, dep_type)
- Uses `CL_ABAP_DBI_UTILITIES` or standard DDL to check if tables exist before creating
- Idempotent: re-runnable without data loss
- Selection screen for: transport backend (abapgit/api/filedrop), Git URL, API token
- Stores config in ZDOC_AGENT_CFG

- [ ] **Step 2: Create Z_DOC_AGENT_SCAN.abap**

Write an ABAP program that:
- Selection screen: top-level provider names (SELECT-OPTIONS), max depth
- Crawl algorithm:
  1. Start with selected providers
  2. For each object: check ZDOC_AGENT_SCAN for existing hash, skip if unchanged
  3. Extract metadata from BW tables (RSOADSO/RSOADSOT for ADSOs, RSDCUBE/RSDCUBET for CompositeProviders, RSTRAN for transformations, etc.)
  4. Extract source code for transformations (RSAABAP or generated includes)
  5. Query TADIR for package, CROSS/WBCROSSGT for where-used
  6. Store in ZDOC_AGENT_SCAN and ZDOC_AGENT_DEPS
  7. Add referenced Z*/Y* objects to crawl queue
  8. Filter SAP standard by namespace
- Output: generates JSON via ABAP string operations, pushes via configured backend
- Three transport backends implemented as local classes:
  - LCL_TRANSPORT_API: uses CL_HTTP_CLIENT to POST to GitHub/Gitea API
  - LCL_TRANSPORT_FILE: writes to AL11 path
  - LCL_TRANSPORT_ABAPGIT: (stub) delegates to abapGit

- [ ] **Step 3: Create README.md**

Document:
- Prerequisites (BW/4HANA system, developer key, transport request)
- Installation steps (create via SE38 or import via ADT)
- Configuration (run Z_DOC_AGENT_SETUP first)
- Running the scanner (Z_DOC_AGENT_SCAN, selection screen options)
- Transport backend setup per option
- Known limitations

- [ ] **Step 4: Commit**

```bash
git add setup/abap/
git commit -m "feat: ABAP scanner programs for BW/4HANA (setup + scan + docs)"
```

---

### Task 7: Push and verify

- [ ] **Step 1: Run full test suite**

```bash
source .venv/bin/activate
pytest -v --tb=short
```

Expected: All tests pass

- [ ] **Step 2: Push to Gitea**

```bash
git push origin main
```

Gitea mirror will sync to GitHub automatically.
