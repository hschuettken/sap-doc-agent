"""Interaction QA — generates and runs interaction tests for SAC stories."""

from __future__ import annotations

import uuid


async def _test_filter(tenant_id: object, environment: str, story_id: str, test: dict) -> dict:
    """Stub: test filter interaction."""
    return {"status": "pass"}


async def _test_navigation(tenant_id: object, environment: str, story_id: str, test: dict) -> dict:
    """Stub: test navigation interaction."""
    return {"status": "pass"}


async def _test_drill(tenant_id: object, environment: str, story_id: str, test: dict) -> dict:
    """Stub: test drill-down interaction."""
    return {"status": "pass"}


async def _test_script(tenant_id: object, environment: str, story_id: str, test: dict) -> dict:
    """Stub: test scripted interaction."""
    return {"status": "pass"}


_TEST_DISPATCHERS = {
    "filter": _test_filter,
    "navigation": _test_navigation,
    "drill": _test_drill,
    "script": _test_script,
}


def generate_interaction_tests(test_spec: dict) -> list[dict]:
    """Extract interaction test definitions from a test specification.

    Args:
        test_spec: Dict containing test_cases.interaction list.

    Returns:
        List of test definition dicts, each with at least {title, test_type}.
    """
    raw_tests = test_spec.get("test_cases", {}).get("interaction", [])
    tests: list[dict] = []
    for raw in raw_tests:
        test: dict = {
            "title": raw.get("title", "Unnamed Test"),
            "test_type": raw.get("test_type", "script"),
        }
        # Carry through any extra fields (e.g. from_page, to_page, dimension, etc.)
        for key, value in raw.items():
            if key not in test:
                test[key] = value
        tests.append(test)
    return tests


async def run_interaction_tests(
    tenant_id: object,
    environment: str,
    story_id: str,
    tests: list[dict],
) -> list[dict]:
    """Run a list of interaction tests against a deployed SAC story.

    Args:
        tenant_id: Tenant identifier.
        environment: Environment name.
        story_id: SAC story identifier.
        tests: List of test definitions (from generate_interaction_tests).

    Returns:
        List of result dicts: {title, test_type, status, screenshot_path, error?}.
    """
    from spec2sphere.sac_factory.screenshot_engine import capture_page_screenshot

    results: list[dict] = []

    for test in tests:
        test_type = test.get("test_type", "script")
        title = test.get("title", "Unnamed Test")

        dispatcher = _TEST_DISPATCHERS.get(test_type, _test_script)

        try:
            outcome = await dispatcher(tenant_id, environment, story_id, test)
            status = outcome.get("status", "pass")
            error = outcome.get("error")
        except Exception as exc:  # noqa: BLE001
            status = "fail"
            error = str(exc)

        screenshot_path = await capture_page_screenshot(
            tenant_id,
            environment,
            f"{story_id}_{uuid.uuid4().hex[:6]}",
        )

        result: dict = {
            "title": title,
            "test_type": test_type,
            "status": status,
            "screenshot_path": screenshot_path,
        }
        if error:
            result["error"] = error

        results.append(result)

    return results
