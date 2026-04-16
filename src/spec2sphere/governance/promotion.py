"""Shared learning promotion engine — anonymize and promote learnings up the hierarchy."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from spec2sphere.db import _get_conn

ANONYMIZATION_FIELDS: set[str] = {
    "customer_name",
    "object_name",
    "kpi_names",
    "customer_id",
    "project_name",
    "project_id",
    "tenant_name",
}


def _collect_customer_terms(content: dict) -> list[str]:
    """Auto-detect customer terms from ANONYMIZATION_FIELDS values in content.

    For each string value, we collect both the whole value and individual
    tokens split by whitespace/underscore/hyphen so that sub-words like
    "acme" (from "acme_revenue") are also treated as terms to redact.
    Tokens shorter than 3 characters are skipped to avoid over-redaction.
    """
    raw: list[str] = []
    for key, value in content.items():
        if key in ANONYMIZATION_FIELDS:
            if isinstance(value, str) and value:
                raw.append(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item:
                        raw.append(item)

    terms: list[str] = []
    for raw_term in raw:
        terms.append(raw_term)
        # Also add individual tokens so sub-word matches work
        tokens = re.split(r"[\s_\-]+", raw_term)
        for token in tokens:
            if len(token) >= 3 and token not in terms:
                terms.append(token)
    return terms


def _replace_terms_in_string(text: str, terms: list[str]) -> str:
    """Replace all customer terms in a string with [REDACTED], longest first."""
    sorted_terms = sorted(terms, key=len, reverse=True)
    for term in sorted_terms:
        text = re.sub(re.escape(term), "[REDACTED]", text, flags=re.IGNORECASE)
    return text


def _anonymize_value(value: Any, terms: list[str]) -> Any:
    """Recursively anonymize a value."""
    if isinstance(value, str):
        return _replace_terms_in_string(value, terms)
    elif isinstance(value, dict):
        return {k: _anonymize_value(v, terms) for k, v in value.items()}
    elif isinstance(value, list):
        return [_anonymize_value(item, terms) for item in value]
    return value


def anonymize_content(content: dict, customer_terms: list[str] | None = None) -> dict:
    """
    Anonymize a content dict for promotion.

    - Auto-detects customer terms from ANONYMIZATION_FIELDS values.
    - Removes all fields in ANONYMIZATION_FIELDS entirely.
    - Replaces customer_terms in remaining string values (case-insensitive) with [REDACTED].
    - Recursively handles nested dicts and lists.
    - Sorts terms by length descending before replacement.
    """
    auto_terms = _collect_customer_terms(content)
    all_terms = list(set(auto_terms + (customer_terms or [])))
    # Sort longest first so longer matches take precedence
    all_terms = sorted(all_terms, key=len, reverse=True)

    result: dict = {}
    for key, value in content.items():
        if key in ANONYMIZATION_FIELDS:
            continue  # Strip the field entirely
        result[key] = _anonymize_value(value, all_terms)
    return result


@dataclass
class PromotionCandidate:
    id: str
    source_customer_id: str
    source_type: str
    source_id: str
    target_layer: str
    anonymized_content: dict
    status: str = "pending"


def build_promotion_candidate(
    source_customer_id: str,
    source_type: str,
    source_id: str,
    target_layer: str,
    content: dict,
    customer_terms: list[str] | None = None,
) -> PromotionCandidate:
    """Build a PromotionCandidate with auto-anonymized content."""
    import uuid

    anonymized = anonymize_content(content, customer_terms)
    return PromotionCandidate(
        id=str(uuid.uuid4()),
        source_customer_id=source_customer_id,
        source_type=source_type,
        source_id=source_id,
        target_layer=target_layer,
        anonymized_content=anonymized,
        status="pending",
    )


async def save_candidate(candidate: PromotionCandidate) -> None:
    """INSERT a PromotionCandidate into promotion_candidates."""
    import json

    conn = await _get_conn()
    try:
        await conn.execute(
            """
            INSERT INTO promotion_candidates
                (id, source_customer_id, source_type, source_id, target_layer,
                 anonymized_content, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            candidate.id,
            candidate.source_customer_id,
            candidate.source_type,
            candidate.source_id,
            candidate.target_layer,
            json.dumps(candidate.anonymized_content),
            candidate.status,
        )
    finally:
        await conn.close()


async def review_candidate(candidate_id: str, approved: bool, reviewer_id: str) -> None:
    """UPDATE a promotion candidate's review status."""
    status = "approved" if approved else "rejected"
    conn = await _get_conn()
    try:
        await conn.execute(
            """
            UPDATE promotion_candidates
            SET status = $1, reviewed_by = $2, reviewed_at = $3
            WHERE id = $4
            """,
            status,
            reviewer_id,
            datetime.now(timezone.utc),
            candidate_id,
        )
    finally:
        await conn.close()


async def list_candidates(status: str | None = None, limit: int = 50) -> list[dict]:
    """SELECT promotion candidates with optional status filter."""
    conn = await _get_conn()
    try:
        if status is not None:
            rows = await conn.fetch(
                "SELECT * FROM promotion_candidates WHERE status = $1 LIMIT $2",
                status,
                limit,
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM promotion_candidates LIMIT $1",
                limit,
            )
        return [dict(r) for r in rows]
    finally:
        await conn.close()
