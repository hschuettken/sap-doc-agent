"""Report Generator — produces markdown summaries, HTML reports, and XML sitemaps."""

from __future__ import annotations

from pathlib import Path

from spec2sphere.agents.brs_traceability import TraceReport
from spec2sphere.agents.code_quality import CodeIssue
from spec2sphere.agents.doc_qa import QAReport


class ReportGenerator:
    def __init__(self, doc_platform_url: str = ""):
        self.doc_platform_url = doc_platform_url

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_summary(
        self,
        qa_report: QAReport,
        code_issues: list[CodeIssue],
        trace_report: TraceReport,
    ) -> str:
        """Return a Markdown summary of the quality run."""
        score = qa_report.score
        by_severity = qa_report.by_severity

        # Code issue counts by severity
        code_by_sev: dict[str, int] = {}
        for ci in code_issues:
            code_by_sev[ci.severity] = code_by_sev.get(ci.severity, 0) + 1

        lines: list[str] = [
            "# SAP Doc Agent — Quality Summary",
            "",
            f"**Quality Score:** {score}%",
            "",
            "## Documentation Issues",
            "",
        ]

        if by_severity:
            for sev in ("critical", "important", "minor"):
                count = by_severity.get(sev, 0)
                if count:
                    lines.append(f"- **{sev}**: {count}")
        else:
            lines.append("- No documentation issues found.")

        lines += [
            "",
            "## Code Quality Issues",
            "",
        ]
        if code_by_sev:
            for sev in ("critical", "important", "minor"):
                count = code_by_sev.get(sev, 0)
                if count:
                    lines.append(f"- **{sev}**: {count}")
        else:
            lines.append("- No code quality issues found.")

        # Top 10 doc issues
        if qa_report.issues:
            lines += [
                "",
                "## Top Issues",
                "",
            ]
            severity_order = {"critical": 0, "important": 1, "minor": 2}
            top = sorted(
                qa_report.issues,
                key=lambda i: severity_order.get(i.severity, 9),
            )[:10]
            for issue in top:
                lines.append(f"- `{issue.object_id}` [{issue.severity}] {issue.message}")

        lines += [
            "",
            "## Traceability",
            "",
            f"- **Unlinked requirements:** {len(trace_report.unlinked_requirements)}",
            f"- **Orphan objects:** {len(trace_report.orphan_objects)}",
        ]

        return "\n".join(lines)

    def generate_html_report(
        self,
        qa_report: QAReport,
        code_issues: list[CodeIssue],
        trace_report: TraceReport,
    ) -> str:
        """Return a self-contained HTML report with inline CSS."""
        score = qa_report.score
        by_sev = qa_report.by_severity

        def _row(cells: list[str]) -> str:
            return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"

        doc_rows = ""
        for issue in qa_report.issues:
            doc_rows += _row([issue.object_id, issue.rule_id, issue.severity, issue.message])

        code_rows = ""
        for ci in code_issues:
            line_val = str(ci.line) if ci.line is not None else ""
            code_rows += _row([ci.object_id, ci.rule, ci.severity, ci.message, line_val])

        trace_rows = ""
        for link in trace_report.links:
            trace_rows += _row([link.req_id, link.object_id, link.match_type, f"{link.confidence:.2f}"])

        unlinked = ", ".join(trace_report.unlinked_requirements) or "none"
        orphans = ", ".join(trace_report.orphan_objects) or "none"

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SAP Doc Agent — Quality Report</title>
<style>
  body {{ font-family: sans-serif; margin: 2rem; color: #333; }}
  h1 {{ color: #1a1a2e; }}
  h2 {{ color: #16213e; border-bottom: 1px solid #ccc; padding-bottom: 0.3rem; }}
  .score {{ font-size: 2rem; font-weight: bold; color: #0f3460; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; }}
  th, td {{ border: 1px solid #ddd; padding: 0.4rem 0.6rem; text-align: left; font-size: 0.9rem; }}
  th {{ background: #f4f4f4; }}
  tr:nth-child(even) {{ background: #fafafa; }}
  .critical {{ color: #c0392b; font-weight: bold; }}
  .important {{ color: #e67e22; }}
  .minor {{ color: #7f8c8d; }}
</style>
</head>
<body>
<h1>SAP Doc Agent — Quality Report</h1>
<p class="score">Score: {score}%</p>
<p>Objects checked: {qa_report.objects_checked} | Total checks: {qa_report.total_checks} | Passed: {qa_report.checks_passed}</p>

<h2>Documentation Issues by Severity</h2>
<ul>
  <li class="critical">Critical: {by_sev.get("critical", 0)}</li>
  <li class="important">Important: {by_sev.get("important", 0)}</li>
  <li class="minor">Minor: {by_sev.get("minor", 0)}</li>
</ul>

<h2>Documentation Issues</h2>
<table>
  <tr><th>Object</th><th>Rule</th><th>Severity</th><th>Message</th></tr>
  {doc_rows}
</table>

<h2>Code Quality Issues</h2>
<table>
  <tr><th>Object</th><th>Rule</th><th>Severity</th><th>Message</th><th>Line</th></tr>
  {code_rows}
</table>

<h2>Traceability</h2>
<table>
  <tr><th>Requirement</th><th>Object</th><th>Match Type</th><th>Confidence</th></tr>
  {trace_rows}
</table>
<p><strong>Unlinked requirements:</strong> {unlinked}</p>
<p><strong>Orphan objects:</strong> {orphans}</p>
</body>
</html>"""
        return html

    def generate_sitemap(self, pages: list[dict]) -> str:
        """Return an XML sitemap for the given pages list.

        Each page dict: url (str), lastmod (str ISO), page_type (str: space/chapter/page).
        Priority: space=1.0, chapter=0.8, page=0.5.
        """
        priority_map = {"space": "1.0", "chapter": "0.8", "page": "0.5"}

        url_entries: list[str] = []
        for page in pages:
            ptype = page.get("page_type", "page")
            priority = priority_map.get(ptype, "0.5")
            url_entries.append(
                f"  <url>\n"
                f"    <loc>{page['url']}</loc>\n"
                f"    <lastmod>{page['lastmod']}</lastmod>\n"
                f"    <priority>{priority}</priority>\n"
                f"  </url>"
            )

        entries_str = "\n".join(url_entries)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{entries_str}\n"
            "</urlset>"
        )

    def write_reports(
        self,
        output_dir: Path,
        qa_report: QAReport,
        code_issues: list[CodeIssue],
        trace_report: TraceReport,
        pages: list[dict] | None = None,
    ) -> None:
        """Write summary.md, report.html (and optionally sitemap.xml) to output_dir/reports/."""
        reports_dir = output_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        (reports_dir / "summary.md").write_text(
            self.generate_summary(qa_report, code_issues, trace_report),
            encoding="utf-8",
        )
        (reports_dir / "report.html").write_text(
            self.generate_html_report(qa_report, code_issues, trace_report),
            encoding="utf-8",
        )
        if pages is not None:
            (reports_dir / "sitemap.xml").write_text(
                self.generate_sitemap(pages),
                encoding="utf-8",
            )
