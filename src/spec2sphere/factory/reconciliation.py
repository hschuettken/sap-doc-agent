"""Data Reconciliation Engine — delta classification and result storage.

Executes baseline and candidate queries, classifies deltas, and stores
reconciliation results in the reconciliation_results table.
"""

from __future__ import annotations

from typing import Any

from spec2sphere.db import _get_conn
from spec2sphere.tenant.context import ContextEnvelope


# ---------------------------------------------------------------------------
# Delta classification
# ---------------------------------------------------------------------------

_STATUSES = ("pass", "within_tolerance", "expected_change", "probable_defect", "needs_review")


def classify_delta(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    tolerance_type: str,
    tolerance_value: float,
    expected_delta: dict[str, Any] | None = None,
) -> str:
    """Classify the delta between baseline and candidate result sets.

    Args:
        baseline: dict of column → value from the reference query.
        candidate: dict of column → value from the new query.
        tolerance_type: "absolute" | "percentage" | "exact"
        tolerance_value: numeric threshold for absolute/percentage modes.
        expected_delta: optional dict of column → expected_diff; if all
            computed deltas match this, returns "expected_change".

    Returns:
        One of: "pass", "within_tolerance", "expected_change",
                "probable_defect", "needs_review".
    """
    baseline_keys = set(baseline.keys())
    candidate_keys = set(candidate.keys())

    if baseline_keys != candidate_keys:
        return "needs_review"

    # Exact match — no differences at all
    if all(baseline[k] == candidate[k] for k in baseline_keys):
        return "pass"

    # Compute per-key numeric deltas
    computed_deltas: dict[str, float] = {}
    for k in baseline_keys:
        bv = baseline[k]
        cv = candidate[k]
        if bv == cv:
            computed_deltas[k] = 0.0
            continue

        try:
            bv_num = float(bv)  # type: ignore[arg-type]
            cv_num = float(cv)  # type: ignore[arg-type]
            computed_deltas[k] = cv_num - bv_num
        except (TypeError, ValueError):
            # Non-numeric mismatch
            return "probable_defect"

    # Check expected_delta before tolerance
    if expected_delta is not None:
        # Simpler: all keys in expected_delta match, and no extra diffs exist outside expected keys
        expected_keys = set(expected_delta.keys())
        all_match = True
        for k in baseline_keys:
            delta = computed_deltas[k]
            if k in expected_keys:
                try:
                    if abs(delta - float(expected_delta[k])) >= 1e-9:  # type: ignore[arg-type]
                        all_match = False
                        break
                except (TypeError, ValueError):
                    all_match = False
                    break
            else:
                if delta != 0.0:
                    all_match = False
                    break
        if all_match:
            return "expected_change"

    # Tolerance classification
    if tolerance_type == "exact":
        return "probable_defect"

    within = True
    for k in baseline_keys:
        bv = baseline[k]
        cv = candidate[k]
        if bv == cv:
            continue
        try:
            bv_num = float(bv)  # type: ignore[arg-type]
            cv_num = float(cv)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return "probable_defect"

        diff = abs(cv_num - bv_num)
        if tolerance_type == "absolute":
            if diff > tolerance_value:
                within = False
                break
        elif tolerance_type == "percentage":
            base_abs = abs(bv_num)
            if base_abs == 0:
                if diff > 0:
                    within = False
                    break
            else:
                pct = (diff / base_abs) * 100
                if pct > tolerance_value:
                    within = False
                    break

    return "within_tolerance" if within else "probable_defect"


# ---------------------------------------------------------------------------
# Run reconciliation
# ---------------------------------------------------------------------------


async def run_reconciliation(
    ctx: ContextEnvelope,
    test_spec_id: str,
    test_cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Execute each test case against the DB and store results.

    Args:
        ctx: tenant context with customer_id and project_id.
        test_spec_id: UUID string for the parent test spec.
        test_cases: list of dicts with keys:
            key, title, baseline_query, candidate_query,
            tolerance_type, tolerance_value, expected_delta (optional).

    Returns:
        List of result dicts with keys:
            key, title, delta_status, delta, explanation.
    """
    conn = await _get_conn()
    results: list[dict[str, Any]] = []

    try:
        for tc in test_cases:
            key = tc["key"]
            title = tc.get("title", key)
            baseline_query = tc["baseline_query"]
            candidate_query = tc["candidate_query"]
            tolerance_type = tc.get("tolerance_type", "exact")
            tolerance_value = tc.get("tolerance_value", 0.0)
            expected_delta = tc.get("expected_delta")

            try:
                baseline_row = await conn.fetchrow(baseline_query)
                candidate_row = await conn.fetchrow(candidate_query)

                baseline = dict(baseline_row) if baseline_row else {}
                candidate = dict(candidate_row) if candidate_row else {}

                # Compute raw delta for storage
                delta: dict[str, Any] = {}
                for k in set(baseline) | set(candidate):
                    bv = baseline.get(k)
                    cv = candidate.get(k)
                    if bv != cv:
                        delta[k] = {"baseline": bv, "candidate": cv}

                status = classify_delta(baseline, candidate, tolerance_type, tolerance_value, expected_delta)
                explanation = f"Delta classification: {status}"

            except Exception as exc:
                baseline = {}
                candidate = {}
                delta = {}
                status = "needs_review"
                explanation = f"Query execution failed: {exc}"

            # Persist result
            await conn.execute(
                """
                INSERT INTO reconciliation_results
                    (test_spec_id, project_id, test_case_key,
                     baseline_value, candidate_value, delta,
                     delta_status, explanation)
                VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb, $7, $8)
                """,
                test_spec_id,
                str(ctx.project_id),
                key,
                __import__("json").dumps(baseline),
                __import__("json").dumps(candidate),
                __import__("json").dumps(delta),
                status,
                explanation,
            )

            results.append(
                {
                    "key": key,
                    "title": title,
                    "delta_status": status,
                    "delta": delta,
                    "explanation": explanation,
                }
            )
    finally:
        await conn.close()

    return results


# ---------------------------------------------------------------------------
# Aggregate summary
# ---------------------------------------------------------------------------


def compute_aggregate_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute pass/tolerance/expected/defect/review percentages.

    Args:
        results: list of result dicts containing "delta_status".

    Returns:
        Dict with keys: total, pass_pct, tolerance_pct, expected_pct,
                        defect_pct, review_pct — percentages rounded to 1dp.
    """
    total = len(results)
    if total == 0:
        return {
            "total": 0,
            "pass_pct": 0.0,
            "tolerance_pct": 0.0,
            "expected_pct": 0.0,
            "defect_pct": 0.0,
            "review_pct": 0.0,
        }

    counts: dict[str, int] = {
        "pass": 0,
        "within_tolerance": 0,
        "expected_change": 0,
        "probable_defect": 0,
        "needs_review": 0,
    }
    for r in results:
        status = r.get("delta_status", "needs_review")
        counts[status] = counts.get(status, 0) + 1

    def pct(n: int) -> float:
        return round(n / total * 100, 1)

    return {
        "total": total,
        "pass_pct": pct(counts["pass"]),
        "tolerance_pct": pct(counts["within_tolerance"]),
        "expected_pct": pct(counts["expected_change"]),
        "defect_pct": pct(counts["probable_defect"]),
        "review_pct": pct(counts["needs_review"]),
    }
