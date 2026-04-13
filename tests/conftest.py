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
