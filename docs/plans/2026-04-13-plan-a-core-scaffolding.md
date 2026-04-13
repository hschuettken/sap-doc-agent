# Plan A: Core Framework & Scaffolding

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold the sap-doc-agent repository with config framework, LLM provider abstraction, doc platform adapters, Git backend adapters, and seeded knowledge base — producing a runnable foundation that all subsequent plans build on.

**Architecture:** Plugin-based adapters behind abstract interfaces. Config drives everything via `config.yaml`. Each adapter (doc platform, git backend, LLM provider) is a thin wrapper around a vendor SDK/API. The core framework is vendor-agnostic; the demo config points at Henning's homelab (BookStack :8253, LLM Router :8070, personal GitHub).

**Tech Stack:** Python 3.12, pydantic 2.x (config validation), httpx (async HTTP), atlassian-python-api (Confluence), PyGithub (GitHub), pytest, pyyaml

---

## File Structure

```
sap-doc-agent/
├── pyproject.toml                        # Project metadata, dependencies, scripts
├── config.example.yaml                   # Annotated reference config
├── config.yaml                           # Ignored by git, deployment-specific
├── .gitignore
├── SPEC.md                               # Already committed
├── README.md
│
├── src/
│   └── sap_doc_agent/
│       ├── __init__.py
│       ├── config.py                     # Pydantic config models, YAML loader
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── base.py                   # LLMProvider ABC
│       │   ├── noop.py                   # Mode: none — skips LLM, returns None
│       │   ├── passthrough.py            # Mode: copilot_passthrough — writes prompts to file
│       │   └── direct.py                 # Mode: direct — calls OpenAI-compatible API
│       ├── doc_platform/
│       │   ├── __init__.py
│       │   ├── base.py                   # DocPlatformAdapter ABC
│       │   ├── bookstack.py              # BookStack REST adapter
│       │   ├── outline.py                # Outline REST adapter
│       │   └── confluence.py             # Confluence adapter via atlassian-python-api
│       ├── git_backend/
│       │   ├── __init__.py
│       │   ├── base.py                   # GitBackend ABC
│       │   └── github_backend.py         # GitHub adapter via PyGithub
│       └── knowledge/
│           ├── __init__.py
│           └── seed.py                   # Seeds knowledge/ from sap_dev files
│
├── knowledge/
│   ├── shared/
│   │   ├── dsp_quirks.md
│   │   ├── hana_sql.md
│   │   ├── cdp_playbook.md
│   │   ├── ui_mapping.md
│   │   └── best_practices.md
│   └── tenants/
│       └── .gitkeep
│
├── standards/
│   ├── horvath/
│   │   └── .gitkeep                      # Content in Plan D
│   └── client/
│       └── .gitkeep
│
├── brs/
│   └── .gitkeep
│
├── output/
│   ├── objects/
│   │   └── .gitkeep
│   └── .gitkeep
│
├── reports/
│   └── .gitkeep
│
└── tests/
    ├── __init__.py
    ├── conftest.py                       # Shared fixtures (config, mock adapters)
    ├── test_config.py
    ├── test_llm_noop.py
    ├── test_llm_direct.py
    ├── test_doc_bookstack.py
    ├── test_doc_outline.py
    ├── test_doc_confluence.py
    ├── test_git_github.py
    └── test_knowledge_seed.py
```

---

### Task 1: Repository scaffolding + pyproject.toml

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `README.md`
- Create: `src/sap_doc_agent/__init__.py`
- Create: all `.gitkeep` files and empty `__init__.py` files
- Create: `tests/__init__.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "sap-doc-agent"
version = "0.1.0"
description = "Automated SAP BW/4HANA and Datasphere documentation, quality assurance, and code audit"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "httpx>=0.27",
    "atlassian-python-api>=3.41",
    "PyGithub>=2.3",
    "openai>=1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-httpx>=0.30",
    "respx>=0.21",
    "ruff>=0.4",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends._legacy:_Backend"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
target-version = "py312"
line-length = 120
```

- [ ] **Step 2: Create .gitignore**

```gitignore
__pycache__/
*.pyc
.venv/
venv/
*.egg-info/
dist/
build/
config.yaml
.env
output/objects/*.md
output/graph.json
reports/*.html
reports/*.pdf
.pytest_cache/
.ruff_cache/
```

- [ ] **Step 3: Create README.md**

```markdown
# SAP Documentation Agent

Automated documentation, quality assurance, and code audit for SAP BW/4HANA and Datasphere.

See [SPEC.md](SPEC.md) for the full design specification.

## Quick Start

\`\`\`bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp config.example.yaml config.yaml
# Edit config.yaml for your environment
pytest
\`\`\`
```

- [ ] **Step 4: Create directory structure with init files**

Create all directories and placeholder files:
- `src/sap_doc_agent/__init__.py` (empty)
- `src/sap_doc_agent/llm/__init__.py` (empty)
- `src/sap_doc_agent/doc_platform/__init__.py` (empty)
- `src/sap_doc_agent/git_backend/__init__.py` (empty)
- `src/sap_doc_agent/knowledge/__init__.py` (empty)
- `tests/__init__.py` (empty)
- `knowledge/shared/.gitkeep`
- `knowledge/tenants/.gitkeep`
- `standards/horvath/.gitkeep`
- `standards/client/.gitkeep`
- `brs/.gitkeep`
- `output/objects/.gitkeep`
- `output/.gitkeep`
- `reports/.gitkeep`
- `docs/plans/.gitkeep` (already exists for this plan)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "scaffold: repo structure, pyproject.toml, gitignore, readme"
```

---

### Task 2: Config framework

**Files:**
- Create: `src/sap_doc_agent/config.py`
- Create: `config.example.yaml`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import pytest
from pathlib import Path
from sap_doc_agent.config import load_config, AppConfig


MINIMAL_YAML = """\
sap_systems:
  - name: "Test BW"
    type: bw4hana
    transport: api
    scan_scope:
      top_level_providers: ["ADSO_TEST"]
      namespace_filter: ["Z*"]
      object_types: [adso, transformation]

doc_platform:
  type: bookstack
  url: "http://localhost:8253"
  auth:
    type: api_token
    token_env: BOOKSTACK_TOKEN

git:
  type: github
  url_env: GIT_REPO_URL
  token_env: GIT_TOKEN

llm:
  mode: none

standards:
  - horvath/doc_standard.yaml
"""


def test_load_minimal_config(tmp_path: Path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(MINIMAL_YAML)
    cfg = load_config(cfg_file)
    assert isinstance(cfg, AppConfig)
    assert cfg.sap_systems[0].name == "Test BW"
    assert cfg.sap_systems[0].type == "bw4hana"
    assert cfg.doc_platform.type == "bookstack"
    assert cfg.llm.mode == "none"
    assert len(cfg.standards) == 1


def test_config_validates_sap_type(tmp_path: Path):
    bad = MINIMAL_YAML.replace("bw4hana", "invalid_type")
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(bad)
    with pytest.raises(Exception):
        load_config(cfg_file)


def test_config_validates_llm_mode(tmp_path: Path):
    bad = MINIMAL_YAML.replace("mode: none", "mode: imaginary")
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(bad)
    with pytest.raises(Exception):
        load_config(cfg_file)


def test_config_datasphere_system(tmp_path: Path):
    dsp_yaml = MINIMAL_YAML + """\
  - name: "Test DSP"
    type: datasphere
    mcp_server: sap-datasphere-mcp
    oauth:
      client_id_env: DSP_CLIENT_ID
      client_secret_env: DSP_CLIENT_SECRET
      token_url_env: DSP_TOKEN_URL
    spaces: ["SPACE_A"]
"""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(dsp_yaml)
    cfg = load_config(cfg_file)
    assert len(cfg.sap_systems) == 2
    assert cfg.sap_systems[1].type == "datasphere"
    assert cfg.sap_systems[1].spaces == ["SPACE_A"]


def test_config_full_with_direct_llm(tmp_path: Path):
    full = MINIMAL_YAML.replace("mode: none", """mode: direct
  provider: openai_compatible
  base_url_env: LLM_BASE_URL
  api_key_env: LLM_API_KEY
  model: qwen2.5:14b""")
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(full)
    cfg = load_config(cfg_file)
    assert cfg.llm.mode == "direct"
    assert cfg.llm.model == "qwen2.5:14b"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/hesch/dev/projects/sap-doc-agent && pip install -e ".[dev]" && pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sap_doc_agent.config'`

- [ ] **Step 3: Implement config.py**

```python
# src/sap_doc_agent/config.py
"""
Configuration framework for SAP Doc Agent.

All settings loaded from config.yaml. Environment variable references
(fields ending in _env) are resolved at adapter initialization time,
not at config load time — this keeps config portable across environments.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, field_validator


class ScanScope(BaseModel):
    top_level_providers: list[str] = []
    namespace_filter: list[str] = ["Z*", "Y*"]
    object_types: list[str] = [
        "adso", "composite", "transformation", "class",
        "fm", "table", "data_element", "domain",
        "infoobject", "process_chain", "data_source",
    ]
    max_depth: int | Literal["unlimited"] = "unlimited"


class OAuthConfig(BaseModel):
    client_id_env: str
    client_secret_env: str
    token_url_env: str


class SAPSystem(BaseModel):
    name: str
    type: Literal["bw4hana", "datasphere"]
    # BW/4HANA fields
    transport: Optional[Literal["abapgit", "api", "filedrop"]] = None
    scan_scope: Optional[ScanScope] = None
    # Datasphere fields
    mcp_server: Optional[str] = None
    oauth: Optional[OAuthConfig] = None
    spaces: Optional[list[str]] = None

    @field_validator("transport")
    @classmethod
    def bw_needs_transport(cls, v, info):
        if info.data.get("type") == "bw4hana" and v is None:
            raise ValueError("BW/4HANA systems require a transport backend")
        return v


class AuthConfig(BaseModel):
    type: Literal["api_token", "basic", "oauth"]
    token_env: Optional[str] = None
    username_env: Optional[str] = None
    password_env: Optional[str] = None


class DocPlatformConfig(BaseModel):
    type: Literal["bookstack", "outline", "confluence"]
    url: str
    auth: AuthConfig
    space_key: Optional[str] = None


class GitConfig(BaseModel):
    type: Literal["github", "gitea", "gitlab", "azure_devops"]
    url_env: str
    token_env: str


class LLMConfig(BaseModel):
    mode: Literal["none", "copilot_passthrough", "direct"]
    provider: Optional[str] = None
    base_url_env: Optional[str] = None
    api_key_env: Optional[str] = None
    model: Optional[str] = None


class ReportingConfig(BaseModel):
    formats: list[Literal["html", "pdf", "markdown"]] = ["html", "markdown"]
    sitemap: bool = True
    schedule: Optional[str] = None


class AppConfig(BaseModel):
    sap_systems: list[SAPSystem]
    doc_platform: DocPlatformConfig
    git: GitConfig
    llm: LLMConfig
    standards: list[str] = []
    reporting: ReportingConfig = ReportingConfig()


def load_config(path: Path | str) -> AppConfig:
    """Load and validate config from a YAML file."""
    path = Path(path)
    with open(path) as f:
        raw = yaml.safe_load(f)
    return AppConfig.model_validate(raw)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Create config.example.yaml**

```yaml
# SAP Documentation Agent — Configuration
# Copy to config.yaml and edit for your environment.

sap_systems:
  # BW/4HANA system (requires ABAP scanner installed)
  - name: "Horvath BW/4 Demo"
    type: bw4hana
    transport: api                  # abapgit | api | filedrop
    scan_scope:
      top_level_providers: []       # e.g. ["ADSO_SALES", "CP_REVENUE"]
      namespace_filter: ["Z*", "Y*"]
      object_types:
        - adso
        - composite
        - transformation
        - class
        - fm
        - table
        - data_element
        - domain
        - infoobject
        - process_chain
        - data_source
      max_depth: unlimited

  # Datasphere system (API-based, no ABAP needed)
  # - name: "Horvath DSP"
  #   type: datasphere
  #   mcp_server: sap-datasphere-mcp
  #   oauth:
  #     client_id_env: DATASPHERE_CLIENT_ID
  #     client_secret_env: DATASPHERE_CLIENT_SECRET
  #     token_url_env: DATASPHERE_TOKEN_URL
  #   spaces: ["SAC_PLANNING"]

doc_platform:
  type: bookstack                   # bookstack | outline | confluence
  url: "http://192.168.0.50:8253"
  auth:
    type: api_token
    token_env: BOOKSTACK_TOKEN
  # space_key: "SAP_DOC"            # Confluence only

git:
  type: github                      # github | gitea | gitlab | azure_devops
  url_env: GIT_REPO_URL             # Full repo URL
  token_env: GIT_TOKEN              # Personal access token

llm:
  mode: direct                      # none | copilot_passthrough | direct
  provider: openai_compatible
  base_url_env: LLM_BASE_URL       # e.g. http://192.168.0.50:8070/v1
  api_key_env: LLM_API_KEY         # Required even if dummy for local models
  model: qwen2.5:14b

standards:
  - horvath/doc_standard.yaml
  # - client/acme_doc_standard.yaml

reporting:
  formats: [html, markdown]
  sitemap: true
  # schedule: weekly
```

- [ ] **Step 6: Commit**

```bash
git add src/sap_doc_agent/config.py config.example.yaml tests/test_config.py
git commit -m "feat: config framework with Pydantic validation and YAML loader"
```

---

### Task 3: LLM provider — base + noop

**Files:**
- Create: `src/sap_doc_agent/llm/base.py`
- Create: `src/sap_doc_agent/llm/noop.py`
- Create: `tests/test_llm_noop.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_noop.py
import pytest
from sap_doc_agent.llm.base import LLMProvider
from sap_doc_agent.llm.noop import NoopLLMProvider


def test_noop_is_llm_provider():
    provider = NoopLLMProvider()
    assert isinstance(provider, LLMProvider)


@pytest.mark.asyncio
async def test_noop_generate_returns_none():
    provider = NoopLLMProvider()
    result = await provider.generate("Describe this ADSO")
    assert result is None


@pytest.mark.asyncio
async def test_noop_generate_json_returns_none():
    provider = NoopLLMProvider()
    result = await provider.generate_json("Analyze this code", schema={"type": "object"})
    assert result is None


def test_noop_is_available_returns_false():
    provider = NoopLLMProvider()
    assert provider.is_available() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_noop.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement base.py and noop.py**

```python
# src/sap_doc_agent/llm/base.py
"""Abstract base for LLM providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class LLMProvider(ABC):
    """Interface for LLM providers. All agents call this — the implementation
    decides whether to skip (noop), generate a prompt file (passthrough),
    or call an API (direct)."""

    @abstractmethod
    async def generate(self, prompt: str, system: str = "") -> Optional[str]:
        """Generate a text completion. Returns None if LLM is unavailable."""

    @abstractmethod
    async def generate_json(self, prompt: str, schema: dict[str, Any], system: str = "") -> Optional[dict]:
        """Generate a structured JSON response. Returns None if LLM is unavailable."""

    @abstractmethod
    def is_available(self) -> bool:
        """Whether this provider can actually call an LLM."""
```

```python
# src/sap_doc_agent/llm/noop.py
"""Noop LLM provider — rule-based mode, no LLM calls."""
from __future__ import annotations

from typing import Any, Optional

from sap_doc_agent.llm.base import LLMProvider


class NoopLLMProvider(LLMProvider):
    """Returns None for all LLM calls. Agents check is_available()
    or the return value and skip LLM-dependent steps."""

    async def generate(self, prompt: str, system: str = "") -> Optional[str]:
        return None

    async def generate_json(self, prompt: str, schema: dict[str, Any], system: str = "") -> Optional[dict]:
        return None

    def is_available(self) -> bool:
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm_noop.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/sap_doc_agent/llm/base.py src/sap_doc_agent/llm/noop.py tests/test_llm_noop.py
git commit -m "feat: LLM provider base + noop (rule-based mode)"
```

---

### Task 4: LLM provider — direct (OpenAI-compatible)

**Files:**
- Create: `src/sap_doc_agent/llm/direct.py`
- Create: `tests/test_llm_direct.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_direct.py
import json
import pytest
import httpx
import respx
from sap_doc_agent.llm.direct import DirectLLMProvider


@pytest.fixture
def provider():
    return DirectLLMProvider(
        base_url="http://test-llm:8070/v1",
        api_key="test-key",
        model="test-model",
    )


def test_direct_is_available(provider):
    assert provider.is_available() is True


@pytest.mark.asyncio
@respx.mock
async def test_direct_generate(provider):
    respx.post("http://test-llm:8070/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "This ADSO stores sales data."}}]
        })
    )
    result = await provider.generate("Describe this ADSO")
    assert result == "This ADSO stores sales data."


@pytest.mark.asyncio
@respx.mock
async def test_direct_generate_json(provider):
    respx.post("http://test-llm:8070/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": '{"quality": "good", "score": 85}'}}]
        })
    )
    result = await provider.generate_json(
        "Rate this documentation",
        schema={"type": "object", "properties": {"quality": {"type": "string"}, "score": {"type": "integer"}}},
    )
    assert result == {"quality": "good", "score": 85}


@pytest.mark.asyncio
@respx.mock
async def test_direct_generate_json_handles_malformed(provider):
    respx.post("http://test-llm:8070/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "not json at all"}}]
        })
    )
    result = await provider.generate_json("Rate this", schema={"type": "object"})
    assert result is None


@pytest.mark.asyncio
@respx.mock
async def test_direct_generate_handles_api_error(provider):
    respx.post("http://test-llm:8070/v1/chat/completions").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )
    result = await provider.generate("Test prompt")
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_direct.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement direct.py**

```python
# src/sap_doc_agent/llm/direct.py
"""Direct LLM provider — calls any OpenAI-compatible API."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

from sap_doc_agent.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class DirectLLMProvider(LLMProvider):
    """Calls an OpenAI-compatible chat/completions endpoint.

    Works with: OpenAI, Azure OpenAI, LLM Router, Ollama (with openai compat),
    vLLM, LiteLLM, or any endpoint that speaks the OpenAI chat format.
    """

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    async def generate(self, prompt: str, system: str = "") -> Optional[str]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return await self._chat(messages)

    async def generate_json(self, prompt: str, schema: dict[str, Any], system: str = "") -> Optional[dict]:
        system_msg = system or "You are a structured data extraction assistant."
        system_msg += f"\n\nRespond with valid JSON matching this schema:\n{json.dumps(schema, indent=2)}"
        raw = await self.generate(prompt, system=system_msg)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("LLM returned non-JSON response, skipping: %s", raw[:200])
            return None

    def is_available(self) -> bool:
        return True

    async def _chat(self, messages: list[dict]) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"model": self._model, "messages": messages},
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            logger.warning("LLM API call failed: %s", exc)
            return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm_direct.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/sap_doc_agent/llm/direct.py tests/test_llm_direct.py
git commit -m "feat: direct LLM provider (OpenAI-compatible API)"
```

---

### Task 5: LLM provider — copilot passthrough

**Files:**
- Create: `src/sap_doc_agent/llm/passthrough.py`
- Create: `tests/test_llm_passthrough.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_passthrough.py
import pytest
from pathlib import Path
from sap_doc_agent.llm.passthrough import CopilotPassthroughProvider


@pytest.fixture
def provider(tmp_path: Path):
    return CopilotPassthroughProvider(output_dir=tmp_path)


def test_passthrough_is_not_available(provider):
    # It doesn't call an LLM — it's a prompt generator
    assert provider.is_available() is False


@pytest.mark.asyncio
async def test_passthrough_generate_writes_prompt_file(provider, tmp_path: Path):
    result = await provider.generate("Describe the ADSO_SALES object")
    assert result is None
    prompt_files = list(tmp_path.glob("prompt_*.md"))
    assert len(prompt_files) == 1
    content = prompt_files[0].read_text()
    assert "Describe the ADSO_SALES object" in content


@pytest.mark.asyncio
async def test_passthrough_generate_json_writes_prompt_with_schema(provider, tmp_path: Path):
    schema = {"type": "object", "properties": {"score": {"type": "integer"}}}
    result = await provider.generate_json("Rate this doc", schema=schema)
    assert result is None
    prompt_files = list(tmp_path.glob("prompt_*.md"))
    assert len(prompt_files) == 1
    content = prompt_files[0].read_text()
    assert "Rate this doc" in content
    assert '"score"' in content


@pytest.mark.asyncio
async def test_passthrough_includes_system_prompt(provider, tmp_path: Path):
    await provider.generate("user prompt", system="You are an SAP expert")
    content = list(tmp_path.glob("prompt_*.md"))[0].read_text()
    assert "You are an SAP expert" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_passthrough.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement passthrough.py**

```python
# src/sap_doc_agent/llm/passthrough.py
"""Copilot passthrough LLM provider — writes structured prompts to files.

In this mode, the agent generates a prompt file that the user can paste
into M365 Copilot (or any chat UI). The user then pastes the response
back, or the agent proceeds without it.

This mode is for enterprises where M365 Copilot is the only approved LLM.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sap_doc_agent.llm.base import LLMProvider


class CopilotPassthroughProvider(LLMProvider):

    def __init__(self, output_dir: Path):
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    async def generate(self, prompt: str, system: str = "") -> Optional[str]:
        self._write_prompt(prompt, system=system)
        return None

    async def generate_json(self, prompt: str, schema: dict[str, Any], system: str = "") -> Optional[dict]:
        full_prompt = f"{prompt}\n\nRespond with JSON matching this schema:\n```json\n{json.dumps(schema, indent=2)}\n```"
        self._write_prompt(full_prompt, system=system)
        return None

    def is_available(self) -> bool:
        return False

    def _write_prompt(self, prompt: str, system: str = "") -> Path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        path = self._output_dir / f"prompt_{ts}.md"
        parts = ["# Copilot Prompt\n"]
        parts.append(f"Generated: {datetime.now(timezone.utc).isoformat()}\n")
        if system:
            parts.append(f"## System Context\n\n{system}\n")
        parts.append(f"## Prompt\n\n{prompt}\n")
        parts.append("## Instructions\n\nPaste the above into M365 Copilot and save the response.\n")
        path.write_text("\n".join(parts))
        return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm_passthrough.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/sap_doc_agent/llm/passthrough.py tests/test_llm_passthrough.py
git commit -m "feat: copilot passthrough LLM provider (prompt file generator)"
```

---

### Task 6: LLM provider factory + __init__

**Files:**
- Modify: `src/sap_doc_agent/llm/__init__.py`
- Create: `tests/test_llm_factory.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_factory.py
import os
import pytest
from pathlib import Path
from sap_doc_agent.config import LLMConfig
from sap_doc_agent.llm import create_llm_provider
from sap_doc_agent.llm.noop import NoopLLMProvider
from sap_doc_agent.llm.passthrough import CopilotPassthroughProvider
from sap_doc_agent.llm.direct import DirectLLMProvider


def test_create_noop():
    cfg = LLMConfig(mode="none")
    provider = create_llm_provider(cfg)
    assert isinstance(provider, NoopLLMProvider)


def test_create_passthrough(tmp_path: Path):
    cfg = LLMConfig(mode="copilot_passthrough")
    provider = create_llm_provider(cfg, output_dir=tmp_path)
    assert isinstance(provider, CopilotPassthroughProvider)


def test_create_direct(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:8070/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    cfg = LLMConfig(
        mode="direct",
        provider="openai_compatible",
        base_url_env="LLM_BASE_URL",
        api_key_env="LLM_API_KEY",
        model="test-model",
    )
    provider = create_llm_provider(cfg)
    assert isinstance(provider, DirectLLMProvider)


def test_create_direct_missing_env_raises():
    cfg = LLMConfig(
        mode="direct",
        provider="openai_compatible",
        base_url_env="NONEXISTENT_URL",
        api_key_env="NONEXISTENT_KEY",
        model="test-model",
    )
    with pytest.raises(ValueError, match="environment variable"):
        create_llm_provider(cfg)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_factory.py -v`
Expected: FAIL — `ImportError: cannot import name 'create_llm_provider'`

- [ ] **Step 3: Implement __init__.py factory**

```python
# src/sap_doc_agent/llm/__init__.py
"""LLM provider factory."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from sap_doc_agent.config import LLMConfig
from sap_doc_agent.llm.base import LLMProvider
from sap_doc_agent.llm.noop import NoopLLMProvider
from sap_doc_agent.llm.passthrough import CopilotPassthroughProvider
from sap_doc_agent.llm.direct import DirectLLMProvider


def _resolve_env(env_name: str) -> str:
    val = os.environ.get(env_name)
    if val is None:
        raise ValueError(f"Required environment variable '{env_name}' is not set")
    return val


def create_llm_provider(
    cfg: LLMConfig,
    output_dir: Optional[Path] = None,
) -> LLMProvider:
    """Create the appropriate LLM provider based on config."""
    if cfg.mode == "none":
        return NoopLLMProvider()

    if cfg.mode == "copilot_passthrough":
        return CopilotPassthroughProvider(output_dir=output_dir or Path("reports/prompts"))

    if cfg.mode == "direct":
        base_url = _resolve_env(cfg.base_url_env)
        api_key = _resolve_env(cfg.api_key_env)
        return DirectLLMProvider(
            base_url=base_url,
            api_key=api_key,
            model=cfg.model or "gpt-4",
        )

    raise ValueError(f"Unknown LLM mode: {cfg.mode}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm_factory.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/sap_doc_agent/llm/__init__.py tests/test_llm_factory.py
git commit -m "feat: LLM provider factory — creates provider from config"
```

---

### Task 7: Doc platform adapter — base + BookStack

**Files:**
- Create: `src/sap_doc_agent/doc_platform/base.py`
- Create: `src/sap_doc_agent/doc_platform/bookstack.py`
- Create: `tests/test_doc_bookstack.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doc_bookstack.py
import pytest
import httpx
import respx
from sap_doc_agent.doc_platform.base import DocPlatformAdapter, Page, Space
from sap_doc_agent.doc_platform.bookstack import BookStackAdapter


@pytest.fixture
def adapter():
    return BookStackAdapter(base_url="http://test-bookstack:8253", token_id="1", token_secret="abc123")


def test_bookstack_is_adapter(adapter):
    assert isinstance(adapter, DocPlatformAdapter)


@pytest.mark.asyncio
@respx.mock
async def test_create_book(adapter):
    respx.post("http://test-bookstack:8253/api/books").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "Horvath BW/4", "slug": "horvath-bw4"})
    )
    space = await adapter.create_space("Horvath BW/4", "BW/4HANA documentation")
    assert space.id == "1"
    assert space.name == "Horvath BW/4"


@pytest.mark.asyncio
@respx.mock
async def test_create_chapter(adapter):
    respx.post("http://test-bookstack:8253/api/chapters").mock(
        return_value=httpx.Response(200, json={"id": 10, "name": "RAW Layer", "book_id": 1})
    )
    page = await adapter.create_page(
        space_id="1", title="RAW Layer", content="", parent_id=None, is_chapter=True
    )
    assert page.id == "10"


@pytest.mark.asyncio
@respx.mock
async def test_create_page(adapter):
    respx.post("http://test-bookstack:8253/api/pages").mock(
        return_value=httpx.Response(200, json={"id": 100, "name": "ADSO_SALES", "chapter_id": 10})
    )
    page = await adapter.create_page(
        space_id="1", title="ADSO_SALES", content="# ADSO_SALES\n\nSales data store.", parent_id="10"
    )
    assert page.id == "100"
    assert page.title == "ADSO_SALES"


@pytest.mark.asyncio
@respx.mock
async def test_update_page(adapter):
    respx.put("http://test-bookstack:8253/api/pages/100").mock(
        return_value=httpx.Response(200, json={"id": 100, "name": "ADSO_SALES"})
    )
    await adapter.update_page("100", content="# Updated content")


@pytest.mark.asyncio
@respx.mock
async def test_get_page(adapter):
    respx.get("http://test-bookstack:8253/api/pages/100").mock(
        return_value=httpx.Response(200, json={
            "id": 100, "name": "ADSO_SALES", "markdown": "# ADSO_SALES",
            "tags": [{"name": "layer", "value": "raw"}],
        })
    )
    page = await adapter.get_page("100")
    assert page.id == "100"
    assert page.title == "ADSO_SALES"
    assert "ADSO_SALES" in page.content


@pytest.mark.asyncio
@respx.mock
async def test_search(adapter):
    respx.get("http://test-bookstack:8253/api/search").mock(
        return_value=httpx.Response(200, json={
            "data": [
                {"id": 100, "name": "ADSO_SALES", "type": "page", "preview": {"content": "Sales data"}},
            ],
            "total": 1,
        })
    )
    results = await adapter.search("ADSO_SALES")
    assert len(results) == 1
    assert results[0].title == "ADSO_SALES"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_doc_bookstack.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement base.py**

```python
# src/sap_doc_agent/doc_platform/base.py
"""Abstract base for documentation platform adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Page:
    id: str
    title: str
    content: str = ""
    parent_id: Optional[str] = None
    labels: dict[str, str] = field(default_factory=dict)
    url: Optional[str] = None


@dataclass
class Space:
    id: str
    name: str
    url: Optional[str] = None


class DocPlatformAdapter(ABC):
    """Interface for documentation platforms (BookStack, Outline, Confluence)."""

    @abstractmethod
    async def create_space(self, name: str, description: str = "") -> Space:
        """Create a top-level space/book."""

    @abstractmethod
    async def create_page(
        self,
        space_id: str,
        title: str,
        content: str,
        parent_id: Optional[str] = None,
        is_chapter: bool = False,
    ) -> Page:
        """Create a page (or chapter in BookStack)."""

    @abstractmethod
    async def update_page(self, page_id: str, content: str, title: Optional[str] = None) -> None:
        """Update page content."""

    @abstractmethod
    async def get_page(self, page_id: str) -> Page:
        """Get a page by ID."""

    @abstractmethod
    async def search(self, query: str) -> list[Page]:
        """Search for pages."""

    @abstractmethod
    async def delete_page(self, page_id: str) -> None:
        """Delete a page."""
```

- [ ] **Step 4: Implement bookstack.py**

```python
# src/sap_doc_agent/doc_platform/bookstack.py
"""BookStack documentation platform adapter."""
from __future__ import annotations

from typing import Optional

import httpx

from sap_doc_agent.doc_platform.base import DocPlatformAdapter, Page, Space


class BookStackAdapter(DocPlatformAdapter):
    """BookStack REST API adapter.

    BookStack hierarchy: Book (space) -> Chapter (group) -> Page (document).
    Auth via token ID + token secret, sent as headers.
    """

    def __init__(self, base_url: str, token_id: str, token_secret: str, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Token {token_id}:{token_secret}",
            "Content-Type": "application/json",
        }
        self._timeout = timeout

    async def create_space(self, name: str, description: str = "") -> Space:
        data = {"name": name, "description": description}
        resp = await self._request("POST", "/api/books", json=data)
        return Space(id=str(resp["id"]), name=resp["name"])

    async def create_page(
        self,
        space_id: str,
        title: str,
        content: str,
        parent_id: Optional[str] = None,
        is_chapter: bool = False,
    ) -> Page:
        if is_chapter:
            data = {"book_id": int(space_id), "name": title}
            resp = await self._request("POST", "/api/chapters", json=data)
            return Page(id=str(resp["id"]), title=resp["name"])

        data: dict = {"name": title, "markdown": content}
        if parent_id:
            data["chapter_id"] = int(parent_id)
        else:
            data["book_id"] = int(space_id)
        resp = await self._request("POST", "/api/pages", json=data)
        return Page(id=str(resp["id"]), title=resp["name"], content=content)

    async def update_page(self, page_id: str, content: str, title: Optional[str] = None) -> None:
        data: dict = {"markdown": content}
        if title:
            data["name"] = title
        await self._request("PUT", f"/api/pages/{page_id}", json=data)

    async def get_page(self, page_id: str) -> Page:
        resp = await self._request("GET", f"/api/pages/{page_id}")
        labels = {}
        for tag in resp.get("tags", []):
            labels[tag["name"]] = tag.get("value", "")
        return Page(
            id=str(resp["id"]),
            title=resp["name"],
            content=resp.get("markdown", resp.get("html", "")),
            labels=labels,
        )

    async def search(self, query: str) -> list[Page]:
        resp = await self._request("GET", "/api/search", params={"query": query})
        results = []
        for item in resp.get("data", []):
            results.append(Page(
                id=str(item["id"]),
                title=item["name"],
                content=item.get("preview", {}).get("content", ""),
            ))
        return results

    async def delete_page(self, page_id: str) -> None:
        await self._request("DELETE", f"/api/pages/{page_id}")

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.request(
                method,
                f"{self._base_url}{path}",
                headers=self._headers,
                **kwargs,
            )
            resp.raise_for_status()
            if resp.status_code == 204:
                return {}
            return resp.json()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_doc_bookstack.py -v`
Expected: All 6 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/sap_doc_agent/doc_platform/base.py src/sap_doc_agent/doc_platform/bookstack.py tests/test_doc_bookstack.py
git commit -m "feat: doc platform base + BookStack adapter"
```

---

### Task 8: Doc platform adapter — Confluence

**Files:**
- Create: `src/sap_doc_agent/doc_platform/confluence.py`
- Create: `tests/test_doc_confluence.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doc_confluence.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sap_doc_agent.doc_platform.base import DocPlatformAdapter, Page, Space
from sap_doc_agent.doc_platform.confluence import ConfluenceAdapter


@pytest.fixture
def mock_confluence():
    mock = MagicMock()
    mock.create_space.return_value = {"id": 123, "key": "SAP", "name": "SAP Docs"}
    mock.create_page.return_value = {"id": 456, "title": "ADSO_SALES"}
    mock.update_page.return_value = {"id": 456, "title": "ADSO_SALES"}
    mock.get_page_by_id.return_value = {
        "id": 456, "title": "ADSO_SALES",
        "body": {"storage": {"value": "<h1>ADSO_SALES</h1>"}},
        "metadata": {"labels": {"results": [{"name": "raw-layer"}]}},
    }
    mock.cql.return_value = {
        "results": [{"content": {"id": 789, "title": "ADSO_REVENUE"}}]
    }
    return mock


@pytest.fixture
def adapter(mock_confluence):
    with patch("sap_doc_agent.doc_platform.confluence.Confluence", return_value=mock_confluence):
        return ConfluenceAdapter(url="https://confluence.test.com", token="test-token")


def test_confluence_is_adapter(adapter):
    assert isinstance(adapter, DocPlatformAdapter)


@pytest.mark.asyncio
async def test_create_space(adapter, mock_confluence):
    space = await adapter.create_space("SAP Docs")
    assert space.id == "SAP"
    mock_confluence.create_space.assert_called_once()


@pytest.mark.asyncio
async def test_create_page(adapter, mock_confluence):
    page = await adapter.create_page("SAP", "ADSO_SALES", "<h1>ADSO_SALES</h1>")
    assert page.id == "456"
    assert page.title == "ADSO_SALES"


@pytest.mark.asyncio
async def test_get_page(adapter, mock_confluence):
    page = await adapter.get_page("456")
    assert page.id == "456"
    assert "ADSO_SALES" in page.content


@pytest.mark.asyncio
async def test_search(adapter, mock_confluence):
    results = await adapter.search("ADSO_REVENUE")
    assert len(results) == 1
    assert results[0].title == "ADSO_REVENUE"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_doc_confluence.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement confluence.py**

```python
# src/sap_doc_agent/doc_platform/confluence.py
"""Confluence documentation platform adapter.

Uses atlassian-python-api which supports both Cloud and Server/Data Center.
The SDK is synchronous, so we wrap calls for the async interface.
"""
from __future__ import annotations

import asyncio
from functools import partial
from typing import Optional

from atlassian import Confluence

from sap_doc_agent.doc_platform.base import DocPlatformAdapter, Page, Space


class ConfluenceAdapter(DocPlatformAdapter):
    """Confluence REST API adapter.

    Confluence hierarchy: Space -> Page (with parent pages for nesting).
    Chapters are represented as parent pages with children.
    """

    def __init__(
        self,
        url: str,
        token: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        kwargs: dict = {"url": url}
        if token:
            kwargs["token"] = token
        elif username and password:
            kwargs["username"] = username
            kwargs["password"] = password
        self._client = Confluence(**kwargs)

    async def _run_sync(self, func, *args, **kwargs):
        """Run a synchronous atlassian-python-api call in a thread."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))

    async def create_space(self, name: str, description: str = "") -> Space:
        key = name.upper().replace(" ", "_")[:10]
        resp = await self._run_sync(
            self._client.create_space, key, name, description
        )
        return Space(id=resp["key"], name=resp["name"])

    async def create_page(
        self,
        space_id: str,
        title: str,
        content: str,
        parent_id: Optional[str] = None,
        is_chapter: bool = False,
    ) -> Page:
        kwargs: dict = {
            "space": space_id,
            "title": title,
            "body": content,
            "type": "page",
        }
        if parent_id:
            kwargs["parent_id"] = parent_id
        resp = await self._run_sync(self._client.create_page, **kwargs)
        return Page(id=str(resp["id"]), title=resp["title"], content=content)

    async def update_page(self, page_id: str, content: str, title: Optional[str] = None) -> None:
        current = await self._run_sync(self._client.get_page_by_id, page_id)
        await self._run_sync(
            self._client.update_page,
            page_id,
            title or current["title"],
            content,
        )

    async def get_page(self, page_id: str) -> Page:
        resp = await self._run_sync(
            self._client.get_page_by_id,
            page_id,
            expand="body.storage,metadata.labels",
        )
        labels = {}
        for label in resp.get("metadata", {}).get("labels", {}).get("results", []):
            labels[label["name"]] = ""
        return Page(
            id=str(resp["id"]),
            title=resp["title"],
            content=resp.get("body", {}).get("storage", {}).get("value", ""),
            labels=labels,
        )

    async def search(self, query: str) -> list[Page]:
        resp = await self._run_sync(self._client.cql, f'text ~ "{query}"')
        results = []
        for item in resp.get("results", []):
            c = item.get("content", item)
            results.append(Page(
                id=str(c["id"]),
                title=c["title"],
            ))
        return results

    async def delete_page(self, page_id: str) -> None:
        await self._run_sync(self._client.remove_page, page_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_doc_confluence.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/sap_doc_agent/doc_platform/confluence.py tests/test_doc_confluence.py
git commit -m "feat: Confluence doc platform adapter"
```

---

### Task 9: Doc platform adapter — Outline

**Files:**
- Create: `src/sap_doc_agent/doc_platform/outline.py`
- Create: `tests/test_doc_outline.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doc_outline.py
import pytest
import httpx
import respx
from sap_doc_agent.doc_platform.base import DocPlatformAdapter, Page, Space
from sap_doc_agent.doc_platform.outline import OutlineAdapter


@pytest.fixture
def adapter():
    return OutlineAdapter(base_url="http://test-outline:8250", api_key="test-key")


def test_outline_is_adapter(adapter):
    assert isinstance(adapter, DocPlatformAdapter)


@pytest.mark.asyncio
@respx.mock
async def test_create_collection(adapter):
    respx.post("http://test-outline:8250/api/collections.create").mock(
        return_value=httpx.Response(200, json={
            "data": {"id": "col-1", "name": "Horvath BW/4"}
        })
    )
    space = await adapter.create_space("Horvath BW/4", "BW docs")
    assert space.id == "col-1"
    assert space.name == "Horvath BW/4"


@pytest.mark.asyncio
@respx.mock
async def test_create_document(adapter):
    respx.post("http://test-outline:8250/api/documents.create").mock(
        return_value=httpx.Response(200, json={
            "data": {"id": "doc-1", "title": "ADSO_SALES", "text": "# ADSO_SALES"}
        })
    )
    page = await adapter.create_page("col-1", "ADSO_SALES", "# ADSO_SALES")
    assert page.id == "doc-1"
    assert page.title == "ADSO_SALES"


@pytest.mark.asyncio
@respx.mock
async def test_get_document(adapter):
    respx.post("http://test-outline:8250/api/documents.info").mock(
        return_value=httpx.Response(200, json={
            "data": {"id": "doc-1", "title": "ADSO_SALES", "text": "# ADSO_SALES\n\nSales data."}
        })
    )
    page = await adapter.get_page("doc-1")
    assert page.title == "ADSO_SALES"
    assert "Sales data" in page.content


@pytest.mark.asyncio
@respx.mock
async def test_search_documents(adapter):
    respx.post("http://test-outline:8250/api/documents.search").mock(
        return_value=httpx.Response(200, json={
            "data": [
                {"document": {"id": "doc-1", "title": "ADSO_SALES", "text": "Sales"}}
            ],
            "pagination": {"total": 1},
        })
    )
    results = await adapter.search("ADSO_SALES")
    assert len(results) == 1
    assert results[0].title == "ADSO_SALES"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_doc_outline.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement outline.py**

```python
# src/sap_doc_agent/doc_platform/outline.py
"""Outline documentation platform adapter.

Outline is markdown-native, which makes it a natural fit for our
scanner output. API is JSON POST-based (not REST-style).
"""
from __future__ import annotations

from typing import Optional

import httpx

from sap_doc_agent.doc_platform.base import DocPlatformAdapter, Page, Space


class OutlineAdapter(DocPlatformAdapter):
    """Outline REST API adapter.

    Outline hierarchy: Collection (space) -> Document (page).
    Documents can be nested via parentDocumentId.
    All API calls are POST with JSON body.
    """

    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self._timeout = timeout

    async def create_space(self, name: str, description: str = "") -> Space:
        resp = await self._request("collections.create", {"name": name, "description": description})
        data = resp["data"]
        return Space(id=data["id"], name=data["name"])

    async def create_page(
        self,
        space_id: str,
        title: str,
        content: str,
        parent_id: Optional[str] = None,
        is_chapter: bool = False,
    ) -> Page:
        body: dict = {"collectionId": space_id, "title": title, "text": content, "publish": True}
        if parent_id:
            body["parentDocumentId"] = parent_id
        resp = await self._request("documents.create", body)
        data = resp["data"]
        return Page(id=data["id"], title=data["title"], content=data.get("text", ""))

    async def update_page(self, page_id: str, content: str, title: Optional[str] = None) -> None:
        body: dict = {"id": page_id, "text": content}
        if title:
            body["title"] = title
        await self._request("documents.update", body)

    async def get_page(self, page_id: str) -> Page:
        resp = await self._request("documents.info", {"id": page_id})
        data = resp["data"]
        return Page(id=data["id"], title=data["title"], content=data.get("text", ""))

    async def search(self, query: str) -> list[Page]:
        resp = await self._request("documents.search", {"query": query})
        results = []
        for item in resp.get("data", []):
            doc = item.get("document", item)
            results.append(Page(id=doc["id"], title=doc["title"], content=doc.get("text", "")))
        return results

    async def delete_page(self, page_id: str) -> None:
        await self._request("documents.delete", {"id": page_id})

    async def _request(self, endpoint: str, body: dict) -> dict:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/api/{endpoint}",
                headers=self._headers,
                json=body,
            )
            resp.raise_for_status()
            return resp.json()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_doc_outline.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/sap_doc_agent/doc_platform/outline.py tests/test_doc_outline.py
git commit -m "feat: Outline doc platform adapter"
```

---

### Task 10: Doc platform factory

**Files:**
- Modify: `src/sap_doc_agent/doc_platform/__init__.py`
- Create: `tests/test_doc_factory.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doc_factory.py
import pytest
from unittest.mock import patch
from sap_doc_agent.config import DocPlatformConfig, AuthConfig
from sap_doc_agent.doc_platform import create_doc_adapter
from sap_doc_agent.doc_platform.bookstack import BookStackAdapter
from sap_doc_agent.doc_platform.outline import OutlineAdapter
from sap_doc_agent.doc_platform.confluence import ConfluenceAdapter


def test_create_bookstack(monkeypatch):
    monkeypatch.setenv("BOOKSTACK_TOKEN", "1:secret123")
    cfg = DocPlatformConfig(
        type="bookstack",
        url="http://localhost:8253",
        auth=AuthConfig(type="api_token", token_env="BOOKSTACK_TOKEN"),
    )
    adapter = create_doc_adapter(cfg)
    assert isinstance(adapter, BookStackAdapter)


def test_create_outline(monkeypatch):
    monkeypatch.setenv("OUTLINE_TOKEN", "ol_api_abc123")
    cfg = DocPlatformConfig(
        type="outline",
        url="http://localhost:8250",
        auth=AuthConfig(type="api_token", token_env="OUTLINE_TOKEN"),
    )
    adapter = create_doc_adapter(cfg)
    assert isinstance(adapter, OutlineAdapter)


def test_create_confluence(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_TOKEN", "conf_token_abc")
    cfg = DocPlatformConfig(
        type="confluence",
        url="https://confluence.test.com",
        auth=AuthConfig(type="api_token", token_env="CONFLUENCE_TOKEN"),
    )
    with patch("sap_doc_agent.doc_platform.confluence.Confluence"):
        adapter = create_doc_adapter(cfg)
    assert isinstance(adapter, ConfluenceAdapter)


def test_missing_token_raises(monkeypatch):
    monkeypatch.delenv("BOOKSTACK_TOKEN", raising=False)
    cfg = DocPlatformConfig(
        type="bookstack",
        url="http://localhost:8253",
        auth=AuthConfig(type="api_token", token_env="BOOKSTACK_TOKEN"),
    )
    with pytest.raises(ValueError, match="environment variable"):
        create_doc_adapter(cfg)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_doc_factory.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement __init__.py factory**

```python
# src/sap_doc_agent/doc_platform/__init__.py
"""Doc platform adapter factory."""
from __future__ import annotations

import os

from sap_doc_agent.config import DocPlatformConfig
from sap_doc_agent.doc_platform.base import DocPlatformAdapter


def _resolve_env(env_name: str) -> str:
    val = os.environ.get(env_name)
    if val is None:
        raise ValueError(f"Required environment variable '{env_name}' is not set")
    return val


def create_doc_adapter(cfg: DocPlatformConfig) -> DocPlatformAdapter:
    """Create the appropriate doc platform adapter from config."""
    if cfg.type == "bookstack":
        from sap_doc_agent.doc_platform.bookstack import BookStackAdapter
        token = _resolve_env(cfg.auth.token_env)
        # BookStack tokens are "id:secret" format
        parts = token.split(":", 1)
        token_id = parts[0]
        token_secret = parts[1] if len(parts) > 1 else parts[0]
        return BookStackAdapter(base_url=cfg.url, token_id=token_id, token_secret=token_secret)

    if cfg.type == "outline":
        from sap_doc_agent.doc_platform.outline import OutlineAdapter
        api_key = _resolve_env(cfg.auth.token_env)
        return OutlineAdapter(base_url=cfg.url, api_key=api_key)

    if cfg.type == "confluence":
        from sap_doc_agent.doc_platform.confluence import ConfluenceAdapter
        if cfg.auth.type == "api_token":
            token = _resolve_env(cfg.auth.token_env)
            return ConfluenceAdapter(url=cfg.url, token=token)
        elif cfg.auth.type == "basic":
            username = _resolve_env(cfg.auth.username_env)
            password = _resolve_env(cfg.auth.password_env)
            return ConfluenceAdapter(url=cfg.url, username=username, password=password)

    raise ValueError(f"Unknown doc platform type: {cfg.type}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_doc_factory.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/sap_doc_agent/doc_platform/__init__.py tests/test_doc_factory.py
git commit -m "feat: doc platform factory — creates adapter from config"
```

---

### Task 11: Git backend — base + GitHub

**Files:**
- Create: `src/sap_doc_agent/git_backend/base.py`
- Create: `src/sap_doc_agent/git_backend/github_backend.py`
- Create: `tests/test_git_github.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_git_github.py
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from sap_doc_agent.git_backend.base import GitBackend
from sap_doc_agent.git_backend.github_backend import GitHubBackend


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    # get_contents returns a mock file
    content = MagicMock()
    content.sha = "abc123"
    content.decoded_content = b"# Old content"
    repo.get_contents.return_value = content
    # create_file / update_file return commit info
    repo.create_file.return_value = {"commit": MagicMock(sha="new123")}
    repo.update_file.return_value = {"commit": MagicMock(sha="upd123")}
    return repo


@pytest.fixture
def backend(mock_repo):
    with patch("sap_doc_agent.git_backend.github_backend.Github") as mock_gh:
        mock_gh.return_value.get_repo.return_value = mock_repo
        return GitHubBackend(token="test-token", repo_name="user/sap-docs")


def test_github_is_backend(backend):
    assert isinstance(backend, GitBackend)


def test_write_file_creates_new(backend, mock_repo):
    from github import GithubException
    mock_repo.get_contents.side_effect = GithubException(404, {}, {})
    backend.write_file("objects/adso/ADSO_SALES.md", "# ADSO_SALES", "Add ADSO_SALES")
    mock_repo.create_file.assert_called_once()


def test_write_file_updates_existing(backend, mock_repo):
    backend.write_file("objects/adso/ADSO_SALES.md", "# Updated", "Update ADSO_SALES")
    mock_repo.update_file.assert_called_once()


def test_read_file(backend, mock_repo):
    content = backend.read_file("objects/adso/ADSO_SALES.md")
    assert content == "# Old content"


def test_read_file_not_found(backend, mock_repo):
    from github import GithubException
    mock_repo.get_contents.side_effect = GithubException(404, {}, {})
    content = backend.read_file("nonexistent.md")
    assert content is None


def test_list_files(backend, mock_repo):
    f1 = MagicMock()
    f1.path = "objects/adso/ADSO_SALES.md"
    f1.type = "file"
    f2 = MagicMock()
    f2.path = "objects/adso/ADSO_REVENUE.md"
    f2.type = "file"
    mock_repo.get_contents.return_value = [f1, f2]
    files = backend.list_files("objects/adso")
    assert len(files) == 2
    assert "objects/adso/ADSO_SALES.md" in files
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_git_github.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement base.py and github_backend.py**

```python
# src/sap_doc_agent/git_backend/base.py
"""Abstract base for Git backend adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class GitBackend(ABC):
    """Interface for Git hosting platforms."""

    @abstractmethod
    def write_file(self, path: str, content: str, commit_message: str) -> None:
        """Create or update a file in the repo."""

    @abstractmethod
    def read_file(self, path: str) -> Optional[str]:
        """Read a file. Returns None if not found."""

    @abstractmethod
    def list_files(self, path: str) -> list[str]:
        """List files in a directory."""

    @abstractmethod
    def delete_file(self, path: str, commit_message: str) -> None:
        """Delete a file from the repo."""
```

```python
# src/sap_doc_agent/git_backend/github_backend.py
"""GitHub Git backend adapter."""
from __future__ import annotations

from typing import Optional

from github import Github, GithubException

from sap_doc_agent.git_backend.base import GitBackend


class GitHubBackend(GitBackend):
    """GitHub REST API adapter via PyGithub.

    Works with github.com and GitHub Enterprise (pass base_url for GHE).
    """

    def __init__(self, token: str, repo_name: str, branch: str = "main", base_url: Optional[str] = None):
        kwargs = {"login_or_token": token}
        if base_url:
            kwargs["base_url"] = base_url
        self._gh = Github(**kwargs)
        self._repo = self._gh.get_repo(repo_name)
        self._branch = branch

    def write_file(self, path: str, content: str, commit_message: str) -> None:
        try:
            existing = self._repo.get_contents(path, ref=self._branch)
            self._repo.update_file(
                path, commit_message, content, existing.sha, branch=self._branch
            )
        except GithubException as e:
            if e.status == 404:
                self._repo.create_file(path, commit_message, content, branch=self._branch)
            else:
                raise

    def read_file(self, path: str) -> Optional[str]:
        try:
            content = self._repo.get_contents(path, ref=self._branch)
            return content.decoded_content.decode("utf-8")
        except GithubException as e:
            if e.status == 404:
                return None
            raise

    def list_files(self, path: str) -> list[str]:
        try:
            contents = self._repo.get_contents(path, ref=self._branch)
            if not isinstance(contents, list):
                contents = [contents]
            return [c.path for c in contents if c.type == "file"]
        except GithubException as e:
            if e.status == 404:
                return []
            raise

    def delete_file(self, path: str, commit_message: str) -> None:
        try:
            existing = self._repo.get_contents(path, ref=self._branch)
            self._repo.delete_file(path, commit_message, existing.sha, branch=self._branch)
        except GithubException as e:
            if e.status == 404:
                return
            raise
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_git_github.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/sap_doc_agent/git_backend/base.py src/sap_doc_agent/git_backend/github_backend.py tests/test_git_github.py
git commit -m "feat: Git backend base + GitHub adapter"
```

---

### Task 12: Git backend factory

**Files:**
- Modify: `src/sap_doc_agent/git_backend/__init__.py`
- Create: `tests/test_git_factory.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_git_factory.py
import pytest
from unittest.mock import patch
from sap_doc_agent.config import GitConfig
from sap_doc_agent.git_backend import create_git_backend
from sap_doc_agent.git_backend.github_backend import GitHubBackend


def test_create_github(monkeypatch):
    monkeypatch.setenv("GIT_REPO_URL", "user/sap-docs")
    monkeypatch.setenv("GIT_TOKEN", "ghp_test123")
    cfg = GitConfig(type="github", url_env="GIT_REPO_URL", token_env="GIT_TOKEN")
    with patch("sap_doc_agent.git_backend.github_backend.Github"):
        backend = create_git_backend(cfg)
    assert isinstance(backend, GitHubBackend)


def test_missing_env_raises(monkeypatch):
    monkeypatch.delenv("GIT_TOKEN", raising=False)
    cfg = GitConfig(type="github", url_env="GIT_REPO_URL", token_env="GIT_TOKEN")
    with pytest.raises(ValueError, match="environment variable"):
        create_git_backend(cfg)


def test_unsupported_type_raises(monkeypatch):
    monkeypatch.setenv("GIT_REPO_URL", "user/repo")
    monkeypatch.setenv("GIT_TOKEN", "tok")
    cfg = GitConfig(type="gitlab", url_env="GIT_REPO_URL", token_env="GIT_TOKEN")
    with pytest.raises(ValueError, match="not yet implemented"):
        create_git_backend(cfg)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_git_factory.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement __init__.py factory**

```python
# src/sap_doc_agent/git_backend/__init__.py
"""Git backend factory."""
from __future__ import annotations

import os

from sap_doc_agent.config import GitConfig
from sap_doc_agent.git_backend.base import GitBackend


def _resolve_env(env_name: str) -> str:
    val = os.environ.get(env_name)
    if val is None:
        raise ValueError(f"Required environment variable '{env_name}' is not set")
    return val


def create_git_backend(cfg: GitConfig) -> GitBackend:
    """Create the appropriate Git backend from config."""
    token = _resolve_env(cfg.token_env)
    repo_url = _resolve_env(cfg.url_env)

    if cfg.type == "github":
        from sap_doc_agent.git_backend.github_backend import GitHubBackend
        return GitHubBackend(token=token, repo_name=repo_url)

    if cfg.type == "gitea":
        # Gitea uses the same API as GitHub with a different base_url
        from sap_doc_agent.git_backend.github_backend import GitHubBackend
        # repo_url for Gitea should be "org/repo", base extracted from env
        base = os.environ.get("GITEA_BASE_URL", "http://192.168.0.64:3000/api/v1")
        return GitHubBackend(token=token, repo_name=repo_url, base_url=base)

    raise ValueError(f"Git backend type '{cfg.type}' not yet implemented. Supported: github, gitea")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_git_factory.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/sap_doc_agent/git_backend/__init__.py tests/test_git_factory.py
git commit -m "feat: Git backend factory — GitHub + Gitea support"
```

---

### Task 13: Knowledge base seeding

**Files:**
- Create: `src/sap_doc_agent/knowledge/seed.py`
- Create: `tests/test_knowledge_seed.py`
- Create: seeded `knowledge/shared/*.md` files

- [ ] **Step 1: Write the failing test**

```python
# tests/test_knowledge_seed.py
import pytest
from pathlib import Path
from sap_doc_agent.knowledge.seed import seed_knowledge, SEED_FILES


def test_seed_creates_files(tmp_path: Path):
    seed_knowledge(target_dir=tmp_path)
    shared = tmp_path / "shared"
    assert shared.exists()
    for filename in SEED_FILES:
        f = shared / filename
        assert f.exists(), f"Missing: {filename}"
        assert f.stat().st_size > 100, f"Too small: {filename}"


def test_seed_is_idempotent(tmp_path: Path):
    seed_knowledge(target_dir=tmp_path)
    # Modify a file
    f = tmp_path / "shared" / "hana_sql.md"
    original = f.read_text()
    f.write_text("custom override")
    # Re-seed should NOT overwrite existing files
    seed_knowledge(target_dir=tmp_path)
    assert f.read_text() == "custom override"


def test_seed_force_overwrites(tmp_path: Path):
    seed_knowledge(target_dir=tmp_path)
    f = tmp_path / "shared" / "hana_sql.md"
    f.write_text("custom override")
    seed_knowledge(target_dir=tmp_path, force=True)
    assert f.read_text() != "custom override"


def test_seed_creates_tenants_dir(tmp_path: Path):
    seed_knowledge(target_dir=tmp_path)
    assert (tmp_path / "tenants").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_knowledge_seed.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement seed.py**

```python
# src/sap_doc_agent/knowledge/seed.py
"""Seed the knowledge base with shared SAP knowledge.

Content is extracted from the sap_dev workspace knowledge base and
hardcoded here so the product is self-contained (no dependency on
the homelab file system).
"""
from __future__ import annotations

from pathlib import Path

SEED_FILES = [
    "dsp_quirks.md",
    "hana_sql.md",
    "cdp_playbook.md",
    "ui_mapping.md",
    "best_practices.md",
]

_CONTENT = {
    "dsp_quirks.md": """\
# SAP Datasphere — Known Quirks & Gotchas

## Ace Editor Changes Don't Trigger Save
Setting values via `session.setValue()` in the Ace editor doesn't trigger DSP's
UI5 change tracking. Use keyboard input or Deploy directly (no separate Save needed
in newer DSP versions).

## Cross-Space View Access
Views are only accessible from another space if explicitly shared in Space Management.
A 404 on cross-space access means not shared, not a SQL error.

## Graphical Views Expose Business Names
Graphical views expose DSP business names (often German at client sites), not technical
column names. In SQL, use the quoted business name: `"GTS fakturiert"`.

## Data Viewer Limitations
Virtual scrolling: only ~12 rows visible in the DOM at a time. Don't preview heavy
queries — skip Data Viewer on anything joining large fact tables.

## SELECT * Fails on Cross-Space Joins
Always use explicit column names when referencing views from another space.

## Programmatic Changes Need Deploy, Not Save
In newer DSP versions, clicking Deploy is sufficient — no separate Save step needed.
This is different from older versions where Save was required first.
""",

    "hana_sql.md": """\
# HANA SQL — Non-Obvious Behaviors

## LIMIT Inside UNION ALL — Wrap in Parentheses
```sql
-- Wrong: Missing ')', '*', '+', '-', '/', '||', 'offset' before 'union'
SELECT col FROM t1 LIMIT 1 UNION ALL SELECT col FROM t2 LIMIT 1

-- Correct:
(SELECT col FROM t1 LIMIT 1) UNION ALL (SELECT col FROM t2 LIMIT 1)
```

## UNION ALL — Alias Required on EVERY Leg
Every SELECT in a UNION ALL needs `AS "colname"` on every column, not just the first leg.

## DATAB / DATBI Are VARCHAR, Not DATE
SAP stores dates as VARCHAR 'YYYYMMDD'. Compare as strings:
```sql
WHERE DATAB <= '20260101' AND DATBI >= '20260101'
-- '99991231' = open-ended (no expiry)
```

## No Implicit Type Coercion
HANA is strict about types. `WHERE int_col = '123'` may fail — cast explicitly.

## CASE Expressions Need Explicit Types
All branches of a CASE must return the same type. Mix of VARCHAR and INTEGER causes errors.
""",

    "cdp_playbook.md": """\
# CDP Playbook — SAP Datasphere UI Automation

## Golden Rules
1. **Always screenshot before and after UI actions** to verify state
2. **Use Playwright for navigation** — it handles beforeunload dialogs that CDP cannot see
3. **Never use cdp_navigate on a tab with unsaved changes** — triggers a beforeunload dialog
   that locks the renderer. Use Playwright's browser_navigate instead.
4. **Wait for selectors before clicking** — DSP UI loads asynchronously
5. **Use cdp_wait_for_selector or browser_wait_for** before any interaction

## Tool Selection
- **Playwright (default for new work)**: navigation, multi-step interactions, dialog handling,
  accessibility-tree clicking, screenshots
- **sap-cdp (one-shots and fallback)**: quick cdp_eval, attaching to specific targets,
  checking URL when renderer is dead

## Recovery Techniques
- If automation is stuck: check cdp_status, try Playwright as fallback
- If renderer is dead: cdp_get_url still works (uses HTTP not WebSocket)
- If beforeunload dialog locks tab: handle via Playwright's browser_handle_dialog
""",

    "ui_mapping.md": """\
# DSP UI Mapping — CSS Selectors & Patterns

## General Patterns
- UI5 controls: `[id*="container-"][id$="--controlId"]`
- Buttons: `button[id*="buttonId"]` or `[data-sap-ui*="buttonId"]`
- Input fields: `input[id*="inputId"]`
- Toolbar items: `.sapMTB .sapMBtn`

## Key Navigation Elements
- Side navigation: `.sapTntNavLI`
- Repository browser: `[id*="repositoryBrowser"]`
- SQL editor (Ace): `.ace_editor`
- Data builder canvas: `[id*="dataBuilder"]`

## Tips
- DSP uses UI5 which generates long, composite IDs
- IDs change between versions — prefer data-* attributes or structural selectors
- Always verify selectors with cdp_query_selector before building automation
- Document new selectors in tenant-specific knowledge when discovered
""",

    "best_practices.md": """\
# SAP Datasphere — Best Practices

## 4-Layer Architecture
| Layer | Purpose | Prefix |
|-------|---------|--------|
| RAW (01_) | Replicated/remote tables, no transformation | 01_LT_, 01_RT_, 01_RF_ |
| HARMONIZED (02_) | Integration, cleansing, joins | 02_RV_, 02_FV_, 02_MD_, 02_HV_ |
| MART (03_) | Business-ready facts and dimensions | 03_FV_, 03_HV_, 03_MD_ |
| CONSUMPTION | Exposed to SAC/external tools | Via Spaces sharing |

## Naming Conventions
- Views: `V_` prefix (or layer prefix as above)
- Tables: `T_` prefix
- Cross-space references: include space prefix
- Use descriptive German or English names consistently per project

## Persistence Strategy
- Views are virtual by default (computed on read)
- Use Replication Flow for persisted copies of remote tables
- Persist intermediate views only when performance requires it
- Monitor persistence cost vs. query performance

## Space Design
- One space per business domain or project
- Share finished views between spaces, not intermediate ones
- Use SAP_ADMIN for cross-cutting system views
- Person-specific spaces (50_Name, 51_Name) for development/testing

## Performance
- Avoid joining more than 5-6 tables in a single view
- Filter early (push WHERE clauses to lowest possible view)
- Use analytic models for aggregation instead of SQL GROUP BY
- Don't preview large fact tables in Data Viewer
""",
}


def seed_knowledge(target_dir: Path, force: bool = False) -> None:
    """Seed the knowledge base with shared SAP knowledge.

    Args:
        target_dir: Root knowledge directory (contains shared/ and tenants/)
        force: If True, overwrite existing files. Default: skip existing.
    """
    shared = target_dir / "shared"
    shared.mkdir(parents=True, exist_ok=True)
    (target_dir / "tenants").mkdir(parents=True, exist_ok=True)

    for filename, content in _CONTENT.items():
        path = shared / filename
        if path.exists() and not force:
            continue
        path.write_text(content)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_knowledge_seed.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Actually seed the knowledge files into the repo**

```python
# Run once to populate knowledge/shared/
from sap_doc_agent.knowledge.seed import seed_knowledge
from pathlib import Path
seed_knowledge(Path("knowledge"))
```

Run: `cd /home/hesch/dev/projects/sap-doc-agent && python -c "from sap_doc_agent.knowledge.seed import seed_knowledge; from pathlib import Path; seed_knowledge(Path('knowledge'))"`

- [ ] **Step 6: Commit**

```bash
git add src/sap_doc_agent/knowledge/seed.py tests/test_knowledge_seed.py knowledge/shared/
git commit -m "feat: knowledge base seeding with shared SAP DSP knowledge"
```

---

### Task 14: Top-level app initialization + conftest

**Files:**
- Create: `src/sap_doc_agent/app.py`
- Create: `tests/conftest.py`
- Create: `tests/test_app.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_app.py
import pytest
from pathlib import Path
from unittest.mock import patch
from sap_doc_agent.app import SAPDocAgent
from sap_doc_agent.llm.noop import NoopLLMProvider


MINIMAL_YAML = """\
sap_systems:
  - name: "Test BW"
    type: bw4hana
    transport: api
    scan_scope:
      top_level_providers: ["ADSO_TEST"]
      namespace_filter: ["Z*"]
      object_types: [adso]

doc_platform:
  type: bookstack
  url: "http://localhost:8253"
  auth:
    type: api_token
    token_env: BOOKSTACK_TOKEN

git:
  type: github
  url_env: GIT_REPO_URL
  token_env: GIT_TOKEN

llm:
  mode: none

standards: []
"""


def test_create_agent_noop_llm(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BOOKSTACK_TOKEN", "1:secret")
    monkeypatch.setenv("GIT_REPO_URL", "user/repo")
    monkeypatch.setenv("GIT_TOKEN", "ghp_test")
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(MINIMAL_YAML)
    with patch("sap_doc_agent.git_backend.github_backend.Github"):
        agent = SAPDocAgent.from_config(cfg_file)
    assert isinstance(agent.llm, NoopLLMProvider)
    assert agent.config.sap_systems[0].name == "Test BW"


def test_agent_has_all_components(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BOOKSTACK_TOKEN", "1:secret")
    monkeypatch.setenv("GIT_REPO_URL", "user/repo")
    monkeypatch.setenv("GIT_TOKEN", "ghp_test")
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(MINIMAL_YAML)
    with patch("sap_doc_agent.git_backend.github_backend.Github"):
        agent = SAPDocAgent.from_config(cfg_file)
    assert agent.llm is not None
    assert agent.doc_platform is not None
    assert agent.git is not None
    assert agent.config is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_app.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement app.py**

```python
# src/sap_doc_agent/app.py
"""Top-level application entry point."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sap_doc_agent.config import AppConfig, load_config
from sap_doc_agent.doc_platform import create_doc_adapter
from sap_doc_agent.doc_platform.base import DocPlatformAdapter
from sap_doc_agent.git_backend import create_git_backend
from sap_doc_agent.git_backend.base import GitBackend
from sap_doc_agent.llm import create_llm_provider
from sap_doc_agent.llm.base import LLMProvider


@dataclass
class SAPDocAgent:
    """Main application container. Holds all initialized components."""

    config: AppConfig
    llm: LLMProvider
    doc_platform: DocPlatformAdapter
    git: GitBackend

    @classmethod
    def from_config(cls, config_path: Path | str) -> SAPDocAgent:
        """Initialize all components from a config file."""
        config = load_config(config_path)
        llm = create_llm_provider(config.llm)
        doc_platform = create_doc_adapter(config.doc_platform)
        git = create_git_backend(config.git)
        return cls(config=config, llm=llm, doc_platform=doc_platform, git=git)
```

- [ ] **Step 4: Create conftest.py with shared fixtures**

```python
# tests/conftest.py
"""Shared test fixtures."""
import pytest
from pathlib import Path


MINIMAL_CONFIG_YAML = """\
sap_systems:
  - name: "Test BW"
    type: bw4hana
    transport: api
    scan_scope:
      top_level_providers: ["ADSO_TEST"]
      namespace_filter: ["Z*"]
      object_types: [adso]

doc_platform:
  type: bookstack
  url: "http://localhost:8253"
  auth:
    type: api_token
    token_env: BOOKSTACK_TOKEN

git:
  type: github
  url_env: GIT_REPO_URL
  token_env: GIT_TOKEN

llm:
  mode: none

standards: []
"""


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(MINIMAL_CONFIG_YAML)
    return cfg
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_app.py -v`
Expected: All 2 tests PASS

- [ ] **Step 6: Run full test suite**

Run: `pytest -v`
Expected: All tests PASS (should be ~40 tests total)

- [ ] **Step 7: Commit**

```bash
git add src/sap_doc_agent/app.py tests/conftest.py tests/test_app.py
git commit -m "feat: top-level SAPDocAgent app container with component wiring"
```

---

### Task 15: Push to GitHub + verify

- [ ] **Step 1: Create the GitHub repo**

Create a private repo on Henning's personal GitHub for the demo:

```bash
cd /home/hesch/dev/projects/sap-doc-agent
gh repo create sap-doc-agent --private --source=. --push
```

If `gh` is not available, create manually on github.com and:
```bash
git remote add origin https://github.com/<username>/sap-doc-agent.git
git push -u origin main
```

- [ ] **Step 2: Run full test suite one final time**

```bash
pytest -v --tb=short
```

Expected: All tests PASS

- [ ] **Step 3: Commit any remaining files**

```bash
git status
# Add anything missed
git add -A
git diff --cached --stat  # Review what's staged
git commit -m "chore: ensure all scaffolding files committed"
git push
```
