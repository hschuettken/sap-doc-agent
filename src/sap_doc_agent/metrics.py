"""Prometheus metrics for SAP Doc Agent."""

try:
    from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST

    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False

if _PROMETHEUS_AVAILABLE:
    scan_duration = Histogram(
        "sapdoc_scan_duration_seconds",
        "Duration of scan operations",
        ["scanner_type"],
    )
    llm_tokens_total = Counter(
        "sapdoc_llm_tokens_total",
        "Total LLM tokens used",
        ["provider"],
    )
    queue_depth = Gauge(
        "sapdoc_queue_depth",
        "Current queue depth",
        ["queue"],
    )
    scan_errors_total = Counter(
        "sapdoc_scan_errors_total",
        "Total scan errors",
        ["scanner_type", "error_type"],
    )


def get_metrics_text() -> tuple[str, str]:
    """Returns (content, content_type) for /metrics endpoint."""
    if not _PROMETHEUS_AVAILABLE:
        return "# prometheus_client not installed\n", "text/plain"
    return generate_latest().decode(), CONTENT_TYPE_LATEST
