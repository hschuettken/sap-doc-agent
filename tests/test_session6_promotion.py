"""Tests for governance/promotion.py — Session 6."""

from __future__ import annotations


from spec2sphere.governance.promotion import (
    ANONYMIZATION_FIELDS,
    PromotionCandidate,
    anonymize_content,
    build_promotion_candidate,
)


def test_anonymize_strips_customer_names():
    """Fields in ANONYMIZATION_FIELDS are removed; their values are redacted in remaining fields."""
    content = {
        "customer_name": "Acme Corp",
        "object_name": "V_ACME_REVENUE",
        "kpi_names": ["acme_revenue", "acme_profit"],
        "pattern": "use_acme_naming",
        "route": "Acme Corp main route",
    }
    result = anonymize_content(content)

    # ANONYMIZATION_FIELDS keys must be absent
    for key in ANONYMIZATION_FIELDS:
        assert key not in result, f"Field {key!r} should have been removed"

    # Customer term "Acme Corp", "V_ACME_REVENUE", "acme_revenue", "acme_profit" should be redacted
    # The remaining string fields should not contain "Acme" or "acme"
    result_str = str(result).lower()
    assert "acme" not in result_str, f"Customer term 'acme' should be redacted, got: {result}"

    # The dict structure (non-sensitive keys) should be preserved
    assert "pattern" in result
    assert "route" in result


def test_anonymize_preserves_generic_fields():
    """Non-sensitive fields pass through unchanged if they contain no customer terms."""
    content = {
        "pattern": "star_schema",
        "route": "/api/v1/data",
        "platform": "SAP BW/4HANA",
        "customer_name": "InternalCo",  # will be stripped
    }
    result = anonymize_content(content)

    assert result["pattern"] == "star_schema"
    assert result["route"] == "/api/v1/data"
    assert result["platform"] == "SAP BW/4HANA"
    assert "customer_name" not in result


def test_build_promotion_candidate():
    """build_promotion_candidate returns a PromotionCandidate with status=pending."""
    content = {
        "customer_name": "GlobalBank",
        "pattern": "delta_load",
        "description": "GlobalBank uses delta load for reporting",
    }
    candidate = build_promotion_candidate(
        source_customer_id="cust-001",
        source_type="blueprint",
        source_id="bp-42",
        target_layer="global",
        content=content,
    )

    assert isinstance(candidate, PromotionCandidate)
    assert candidate.status == "pending"
    assert candidate.source_customer_id == "cust-001"
    assert candidate.source_type == "blueprint"
    assert candidate.source_id == "bp-42"
    assert candidate.target_layer == "global"
    # customer_name field should be gone
    assert "customer_name" not in candidate.anonymized_content
    # "GlobalBank" should be redacted in description
    assert "GlobalBank" not in str(candidate.anonymized_content)


def test_anonymize_deep_nested():
    """Customer terms in deeply nested dicts and lists are redacted."""
    content = {
        "metadata": {
            "model": "MyCorp_Sales_Model",
            "tags": ["MyCorp", "finance"],
            "nested": {
                "ref": "MyCorp data warehouse",
            },
        },
        "platform": "SAP Analytics Cloud",
    }
    result = anonymize_content(content, customer_terms=["MyCorp"])

    result_str = str(result).lower()
    assert "mycorp" not in result_str, f"'MyCorp' should be redacted everywhere, got: {result}"
    # Generic field untouched
    assert result["platform"] == "SAP Analytics Cloud"
