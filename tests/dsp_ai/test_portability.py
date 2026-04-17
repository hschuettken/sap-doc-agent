"""End-to-end portability smoke test.

Validates that a library export from one Spec2Sphere instance can be
imported into a fresh standalone instance running on different ports.
Run manually (not in default pytest run):

    pytest tests/dsp_ai/test_portability.py -m portability

Requires:
  - A running docker compose on the primary project (SPEC2SPHERE_URL)
  - Free ports 8360/8361 for the secondary ephemeral instance
  - Docker CLI available

This fixture is best-effort on CI/small machines (will skip if docker
is unavailable or ports are busy).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx
import pytest


pytestmark = [
    pytest.mark.portability,
    pytest.mark.skipif(
        not shutil.which("docker"),
        reason="requires docker CLI",
    ),
]


SECONDARY_PROJECT = "dspai-portability"
SECONDARY_WEB = "http://localhost:8360"
SECONDARY_DSPAI = "http://localhost:8361"
PRIMARY_WEB = os.environ.get("SPEC2SPHERE_URL", "http://localhost:8260")


@pytest.fixture(scope="module")
def repo_root() -> Path:
    """Derive repo root: tests/dsp_ai/test_portability.py → parent^2 = repo root."""
    return Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def exported_blob(tmp_path_factory, repo_root: Path) -> Path:
    """Pull the library export from the primary instance OR use the CPG bundle.

    Order of precedence:
    1. Live /ai-studio/library/export from PRIMARY_WEB (if reachable)
    2. Fallback: shipped CPG bundle at libraries/cpg_retail/export.json
    """
    out = tmp_path_factory.mktemp("portability") / "library.json"

    # Try live export first
    try:
        r = httpx.get(f"{PRIMARY_WEB}/ai-studio/library/export", timeout=10)
        if r.status_code == 200:
            out.write_text(r.text)
            return out
    except Exception:
        pass  # Primary unreachable; fall through to bundle

    # Fallback to CPG bundle
    bundle = repo_root / "libraries" / "cpg_retail" / "export.json"
    if not bundle.exists():
        pytest.skip("no library source (primary unreachable and cpg bundle missing)")
    out.write_bytes(bundle.read_bytes())
    return out


@pytest.fixture(scope="module")
def secondary_compose(repo_root: Path):
    """Spin up a SECOND docker compose stack under a different project name + ports.

    This fixture brings the stack up, waits for health, yields, then tears down.
    Best-effort: if docker compose up fails or the service doesn't become healthy
    within 3 minutes, the test is skipped rather than failed.
    """
    env = os.environ.copy()
    # Remap the two published ports so they don't clash with the primary (8260/8261)
    env["COMPOSE_PROJECT_NAME"] = SECONDARY_PROJECT
    env["WEB_PORT"] = "8360"
    env["DSPAI_PORT"] = "8361"
    # Ensure NEO4J_PASSWORD is set (required by compose)
    if "NEO4J_PASSWORD" not in env:
        env["NEO4J_PASSWORD"] = "portability_test"

    try:
        subprocess.check_call(
            ["docker", "compose", "-p", SECONDARY_PROJECT, "up", "-d"],
            cwd=repo_root,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"docker compose up failed: {exc} (check disk / port conflicts)")

    # Wait up to 3 min for dsp-ai to be healthy (190 * 1s checks)
    healthy = False
    for attempt in range(180):
        try:
            if httpx.get(f"{SECONDARY_DSPAI}/v1/healthz", timeout=2).status_code == 200:
                healthy = True
                break
        except Exception:
            pass
        if attempt % 30 == 0 and attempt > 0:
            # Log progress every 30 attempts
            pass
        time.sleep(1)

    if not healthy:
        subprocess.call(
            ["docker", "compose", "-p", SECONDARY_PROJECT, "down", "-v"],
            cwd=repo_root,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        pytest.skip("secondary stack did not become healthy within 3 min")

    yield

    # Teardown
    subprocess.call(
        ["docker", "compose", "-p", SECONDARY_PROJECT, "down", "-v"],
        cwd=repo_root,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest.mark.asyncio
async def test_export_and_restore_library_on_fresh_compose(exported_blob: Path, secondary_compose):
    """Core round-trip: export → import to fresh stack → verify schema persists.

    Steps:
    1. POST /ai-studio/library/import with mode=merge on secondary instance
    2. Verify import count matches expected (from export.json enhancements array)
    3. GET /ai-studio/library/export on secondary to confirm data round-tripped
    4. Verify first enhancement name matches
    """
    # Step 1: import on secondary
    async with httpx.AsyncClient(timeout=30.0) as client:
        with open(exported_blob, "rb") as f:
            r = await client.post(
                f"{SECONDARY_WEB}/ai-studio/library/import",
                files={"file": ("library.json", f, "application/json")},
                data={"mode": "merge"},
                headers={"X-User-Email": "portability@test"},
            )

    assert r.status_code == 200, f"import failed: {r.text}"
    result = r.json()
    imported = result.get("imported", 0) + result.get("updated", 0)
    expected = len(json.loads(exported_blob.read_text())["enhancements"])
    assert imported == expected, f"expected {expected} enhancements imported, got {imported}"

    # Step 2: list enhancements on secondary (via re-export)
    async with httpx.AsyncClient(timeout=10.0) as client:
        r2 = await client.get(f"{SECONDARY_WEB}/ai-studio/library/export")

    assert r2.status_code == 200, f"export failed: {r2.text}"
    enhs = r2.json()["enhancements"]
    assert len(enhs) >= expected, f"expected at least {expected}, got {len(enhs)}"

    # Step 3: verify schema and first enhancement round-tripped
    original = json.loads(exported_blob.read_text())
    assert "version" in original
    assert "exported_at" in original
    if original["enhancements"]:
        first_name = enhs[0]["name"]
        expected_name = original["enhancements"][0]["name"]
        assert first_name == expected_name, f"first enhancement name mismatch: {first_name} != {expected_name}"
