from pathlib import Path
from unittest.mock import patch
from sap_doc_agent.knowledge.seed import seed_knowledge, SEED_FILES
from sap_doc_agent.app import SAPDocAgent
from sap_doc_agent.llm.noop import NoopLLMProvider


# --- Knowledge seeding tests ---


def test_seed_creates_files(tmp_path: Path):
    seed_knowledge(target_dir=tmp_path)
    for f in SEED_FILES:
        assert (tmp_path / "shared" / f).exists()
        assert (tmp_path / "shared" / f).stat().st_size > 100


def test_seed_idempotent(tmp_path: Path):
    seed_knowledge(target_dir=tmp_path)
    f = tmp_path / "shared" / "hana_sql.md"
    f.write_text("custom")
    seed_knowledge(target_dir=tmp_path)
    assert f.read_text() == "custom"


def test_seed_force(tmp_path: Path):
    seed_knowledge(target_dir=tmp_path)
    f = tmp_path / "shared" / "hana_sql.md"
    f.write_text("custom")
    seed_knowledge(target_dir=tmp_path, force=True)
    assert f.read_text() != "custom"


def test_seed_creates_tenants(tmp_path: Path):
    seed_knowledge(target_dir=tmp_path)
    assert (tmp_path / "tenants").exists()


# --- App container tests ---

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


def test_create_agent(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BOOKSTACK_TOKEN", "1:secret")
    monkeypatch.setenv("GIT_REPO_URL", "user/repo")
    monkeypatch.setenv("GIT_TOKEN", "ghp_test")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(MINIMAL_YAML)
    with patch("sap_doc_agent.git_backend.github_backend.Github"):
        agent = SAPDocAgent.from_config(cfg)
    assert isinstance(agent.llm, NoopLLMProvider)
    assert agent.config.sap_systems[0].name == "Test BW"
    assert agent.doc_platform is not None
    assert agent.git is not None
