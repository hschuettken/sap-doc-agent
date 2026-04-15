import pytest
from pathlib import Path
from spec2sphere.config import load_config, AppConfig


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
    dsp_yaml = """\
sap_systems:
  - name: "Test BW"
    type: bw4hana
    transport: api
    scan_scope:
      top_level_providers: ["ADSO_TEST"]
      namespace_filter: ["Z*"]
      object_types: [adso, transformation]
  - name: "Test DSP"
    type: datasphere
    mcp_server: sap-datasphere-mcp
    oauth:
      client_id_env: DSP_CLIENT_ID
      client_secret_env: DSP_CLIENT_SECRET
      token_url_env: DSP_TOKEN_URL
    spaces: ["SPACE_A"]

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
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(dsp_yaml)
    cfg = load_config(cfg_file)
    assert len(cfg.sap_systems) == 2
    assert cfg.sap_systems[1].type == "datasphere"
    assert cfg.sap_systems[1].spaces == ["SPACE_A"]


def test_config_full_with_direct_llm(tmp_path: Path):
    full = MINIMAL_YAML.replace(
        "mode: none",
        """mode: direct
  provider: openai_compatible
  base_url_env: LLM_BASE_URL
  api_key_env: LLM_API_KEY
  model: qwen2.5:14b""",
    )
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(full)
    cfg = load_config(cfg_file)
    assert cfg.llm.mode == "direct"
    assert cfg.llm.model == "qwen2.5:14b"
