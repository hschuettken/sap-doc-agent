"""Lab runner — sandbox experiment execution and diff computation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


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


async def run_experiment(
    platform: str,
    object_type: str,
    experiment_type: str,
    input_definition: dict,
    route: str = "cdp",
    environment: str = "sandbox",
) -> LabResult:
    """Run an experiment in sandbox environment.

    Enforces sandbox-only constraint. Returns a simulated result.
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

    # Simulated output: copy input with a marker field added
    output_definition: dict = {**input_definition, "_experiment": experiment_type}
    diff = compute_diff(input_definition, output_definition)

    return LabResult(
        success=True,
        input_definition=input_definition,
        output_definition=output_definition,
        diff=diff,
        route_used=route,
    )
