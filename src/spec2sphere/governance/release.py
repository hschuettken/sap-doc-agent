"""Release package assembler — bundles all project artifacts into a downloadable ZIP."""

from __future__ import annotations

import io
import json
import logging
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from spec2sphere.governance.doc_generator import (
    generate_decision_log,
    generate_functional_doc,
    generate_reconciliation_report,
    render_html_report,
    render_markdown_report,
)

logger = logging.getLogger(__name__)


@dataclass
class ReleaseManifest:
    """Metadata for a release package."""

    version: str
    project_name: str
    customer_name: str
    generated_at: str
    object_count: int
    approval_count: int
    test_count: int
    test_pass_count: int
    files: list[str] = field(default_factory=list)

    @classmethod
    def from_project_data(cls, data: dict[str, Any], version: str) -> "ReleaseManifest":
        """Create a manifest from project data and version."""
        recon = data.get("reconciliation_results", [])
        return cls(
            version=version,
            project_name=data["project"]["name"],
            customer_name=data.get("customer", {}).get("name", ""),
            generated_at=datetime.now(timezone.utc).isoformat(),
            object_count=len(data.get("technical_objects", [])),
            approval_count=len(data.get("approvals", [])),
            test_count=len(recon),
            test_pass_count=sum(1 for r in recon if r.get("delta_status") == "pass"),
        )


def assemble_release_package(data: dict[str, Any], version: str = "1.0.0") -> bytes:
    """Assemble a release ZIP package with all project artifacts.

    Contents:
        manifest.json           — Version, counts, file list
        docs/technical.html     — Self-contained HTML technical doc
        docs/technical.md       — Markdown technical doc
        docs/functional.md      — Markdown functional doc
        reconciliation/summary.json — Reconciliation results
        decisions/decision_log.json — Architecture decisions
        artifacts/*.sql         — Generated SQL artifacts
        approvals/approvals.json — Approval records
        screenshots/*.png       — QA screenshots (if present in data["screenshots"])
        open_issues/register.json — Open issues register (if present in data["open_issues"])

    Args:
        data: Project data dictionary containing project, technical_objects, approvals, etc.
        version: Version string for the release (default: "1.0.0")

    Returns:
        ZIP file contents as bytes.
    """
    buf = io.BytesIO()
    manifest = ReleaseManifest.from_project_data(data, version)
    files_written: list[str] = []

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Generate and add technical documentation (HTML)
        html_report = render_html_report(data)
        zf.writestr("docs/technical.html", html_report)
        files_written.append("docs/technical.html")

        # Generate and add technical documentation (Markdown)
        md_report = render_markdown_report(data)
        zf.writestr("docs/technical.md", md_report)
        files_written.append("docs/technical.md")

        # Generate and add functional documentation
        func_doc = generate_functional_doc(data)
        zf.writestr("docs/functional.md", func_doc["content"])
        files_written.append("docs/functional.md")

        # Generate and add reconciliation report
        recon = generate_reconciliation_report(data)
        zf.writestr("reconciliation/summary.json", json.dumps(recon, indent=2, default=str))
        files_written.append("reconciliation/summary.json")

        # Generate and add decision log
        decisions = generate_decision_log(data)
        zf.writestr("decisions/decision_log.json", json.dumps(decisions, indent=2, default=str))
        files_written.append("decisions/decision_log.json")

        # Add generated SQL artifacts
        for obj in data.get("technical_objects", []):
            if obj.get("generated_artifact"):
                path = f"artifacts/{obj['name']}.sql"
                zf.writestr(path, obj["generated_artifact"])
                files_written.append(path)

        # Add approval records if present
        approvals = data.get("approvals", [])
        if approvals:
            zf.writestr("approvals/approvals.json", json.dumps(approvals, indent=2, default=str))
            files_written.append("approvals/approvals.json")

        # Add screenshots if present
        screenshots = data.get("screenshots", [])
        for shot in screenshots:
            name = shot.get("name", "screenshot.png")
            content = shot.get("content", b"")
            if content:
                path = f"screenshots/{name}"
                zf.writestr(path, content)
                files_written.append(path)

        # Add open issues register if present
        open_issues = data.get("open_issues", [])
        if open_issues:
            zf.writestr("open_issues/register.json", json.dumps(open_issues, indent=2, default=str))
            files_written.append("open_issues/register.json")

        # Add manifest with final file list
        manifest.files = files_written
        zf.writestr("manifest.json", json.dumps(asdict(manifest), indent=2))

    return buf.getvalue()
