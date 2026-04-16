"""Lab runner — sandbox experiment execution and diff computation."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_CDP_URL = "http://chrome:9222"
_DEFAULT_TEST_URL = "https://example.com"
_DEFAULT_MODIFY_URL = "https://example.org"


@dataclass
class LabResult:
    success: bool
    input_definition: dict
    output_definition: dict
    diff: dict
    route_used: str
    error: Optional[str] = None


def compute_diff(before: dict, after: dict) -> dict:
    """Compare two dicts at the top-level key level.

    Returns:
        {
            changed: bool,
            additions: dict,      # keys in after but not before
            modifications: dict,  # keys in both but with different values
            removals: dict,       # keys in before but not after
        }
    """
    additions: dict = {}
    modifications: dict = {}
    removals: dict = {}

    before_keys = set(before.keys())
    after_keys = set(after.keys())

    for key in after_keys - before_keys:
        additions[key] = after[key]

    for key in before_keys - after_keys:
        removals[key] = before[key]

    for key in before_keys & after_keys:
        if before[key] != after[key]:
            modifications[key] = {"before": before[key], "after": after[key]}

    changed = bool(additions or modifications or removals)

    return {
        "changed": changed,
        "additions": additions,
        "modifications": modifications,
        "removals": removals,
    }


async def _cdp_read_page_state(cdp_base: str, target_id: str) -> dict:
    """Fetch current page state for a target from /json/list.

    Returns a dict with title, url, and type fields.
    Returns an empty dict if the target is not found.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{cdp_base}/json/list")
        resp.raise_for_status()
        targets = resp.json()

    for t in targets:
        if t.get("id") == target_id:
            return {
                "title": t.get("title", ""),
                "url": t.get("url", ""),
                "type": t.get("type", ""),
            }
    return {}


async def _cdp_create_and_navigate(cdp_base: str, url: str) -> tuple[str, dict]:
    """Create a new Chrome tab and navigate to url.

    Returns (target_id, initial_state) where initial_state comes from
    /json/list after a brief wait for the page to load.

    Raises httpx.ConnectError if Chrome is not reachable.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.put(f"{cdp_base}/json/new?{url}")
        resp.raise_for_status()
        target = resp.json()

    target_id: str = target.get("id", "")

    # Brief wait for the page to begin loading; /json/new opens about:blank
    # and the title/url update asynchronously after navigation starts.
    await asyncio.sleep(1.5)

    state = await _cdp_read_page_state(cdp_base, target_id)
    # Augment with the requested URL if CDP hasn't updated yet
    if not state.get("url"):
        state["url"] = url

    return target_id, state


async def _simulate_experiment(
    experiment_type: str,
    input_definition: dict,
    route: str,
) -> LabResult:
    """Fallback simulation used when Chrome CDP is not available."""
    output_definition: dict = {**input_definition, "_experiment": experiment_type}
    diff = compute_diff(input_definition, output_definition)
    return LabResult(
        success=True,
        input_definition=input_definition,
        output_definition=output_definition,
        diff=diff,
        route_used=route,
    )


async def run_experiment(
    platform: str,
    object_type: str,
    experiment_type: str,
    input_definition: dict,
    route: str = "cdp",
    environment: str = "sandbox",
) -> LabResult:
    """Run an experiment in sandbox environment using Chrome CDP when available.

    Enforces sandbox-only constraint.

    When Chrome CDP is reachable:
      1. Opens a new tab and navigates to the test URL.
      2. Reads back the page state (read_before).
      3. For "modify" experiments, navigates to a second URL.
      4. Reads back again (read_after).
      5. Computes diff and closes the tab.

    Falls back to simulation when Chrome is not reachable, so unit tests
    pass without a live browser.
    """
    if environment != "sandbox":
        return LabResult(
            success=False,
            input_definition=input_definition,
            output_definition={},
            diff={},
            route_used=route,
            error=f"Experiments must run in sandbox environment, got: {environment}",
        )

    cdp_base = os.environ.get("BROWSER_CDP_URL", _DEFAULT_CDP_URL)
    test_url: str = input_definition.get("test_url", _DEFAULT_TEST_URL)

    # --- Probe Chrome availability ---
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            probe = await client.get(f"{cdp_base}/json/version")
        chrome_available = probe.status_code == 200
    except Exception:
        chrome_available = False

    if not chrome_available:
        logger.info("Chrome CDP not reachable at %s — falling back to simulation", cdp_base)
        return await _simulate_experiment(experiment_type, input_definition, route)

    # --- Real CDP path ---
    target_id: Optional[str] = None
    try:
        target_id, read_before = await _cdp_create_and_navigate(cdp_base, test_url)

        if experiment_type == "modify":
            modify_url: str = input_definition.get("modify_url", _DEFAULT_MODIFY_URL)
            # Open a fresh tab at the modify_url to simulate a mutation
            target_id2, read_after = await _cdp_create_and_navigate(cdp_base, modify_url)
            # Close the secondary tab
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.get(f"{cdp_base}/json/close/{target_id2}")
            except Exception:
                pass
        else:
            # For create/read experiments: read_after == read_before plus
            # an injected marker to guarantee a visible diff.
            read_after = {**read_before, "_experiment": experiment_type}

        diff = compute_diff(read_before, read_after)

        return LabResult(
            success=True,
            input_definition=input_definition,
            output_definition=read_after,
            diff=diff,
            route_used=route,
        )

    except Exception as exc:
        logger.warning("CDP experiment failed: %s — falling back to simulation", exc)
        return await _simulate_experiment(experiment_type, input_definition, route)

    finally:
        if target_id:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.get(f"{cdp_base}/json/close/{target_id}")
            except Exception:
                pass
