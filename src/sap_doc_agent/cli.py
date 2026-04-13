"""CLI entry point for SAP Doc Agent.

Usage:
    python -m sap_doc_agent.cli --config config.yaml [--scan] [--sync] [--qa] [--report] [--all]
    python -m sap_doc_agent.cli --config config.yaml --all   # Run full pipeline
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from sap_doc_agent.app import SAPDocAgent
from sap_doc_agent.scanner.models import ScanResult
from sap_doc_agent.scanner.output import write_scan_output
from sap_doc_agent.scanner.orchestrator import ScannerOrchestrator
from sap_doc_agent.agents.doc_sync import DocSyncAgent
from sap_doc_agent.agents.doc_qa import DocQAAgent, load_standard
from sap_doc_agent.agents.code_quality import CodeQualityAgent
from sap_doc_agent.agents.brs_traceability import BRSTraceabilityAgent, TraceReport
from sap_doc_agent.agents.report_generator import ReportGenerator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("sap-doc-agent")


async def run_scan(app: SAPDocAgent, output_dir: Path) -> ScanResult:
    """Run scanners for all configured SAP systems."""
    from sap_doc_agent.scanner.dsp_scanner import DSPScanner
    from sap_doc_agent.scanner.dsp_auth import DSPAuth
    import os

    results = []
    for system in app.config.sap_systems:
        if system.type == "datasphere":
            logger.info("Scanning Datasphere: %s", system.name)
            auth = DSPAuth(
                client_id=os.environ.get(system.oauth.client_id_env, ""),
                client_secret=os.environ.get(system.oauth.client_secret_env, ""),
                token_url=os.environ.get(system.oauth.token_url_env, ""),
            )
            # Derive base URL from token URL (remove /oauth/token path)
            token_url = os.environ.get(system.oauth.token_url_env, "")
            base_url = token_url.rsplit("/oauth", 1)[0] if "/oauth" in token_url else token_url
            scanner = DSPScanner(
                base_url=base_url,
                auth=auth,
                spaces=system.spaces or [],
                namespace_filter=system.scan_scope.namespace_filter if system.scan_scope else None,
            )
            result = await scanner.scan()
            results.append(result)
            logger.info("  Found %d objects", len(result.objects))
        elif system.type == "bw4hana":
            logger.info("BW/4HANA scanning requires ABAP execution — check Git for scan output from %s", system.name)
            # BW scan results come via Git, not direct API
            # Try to read from output dir if already present
            bw_output = output_dir / "bw_import"
            if bw_output.exists():
                logger.info("  Found BW scan output at %s", bw_output)
                # TODO: parse BW output files into ScanResult

    # Merge and deduplicate
    if results:
        orch = ScannerOrchestrator()
        merged = orch.merge(results)
        deduped = orch.deduplicate(merged)
        write_scan_output(deduped, output_dir)
        logger.info("Scan complete: %d objects, %d dependencies", len(deduped.objects), len(deduped.dependencies))
        return deduped

    logger.warning("No scan results produced")
    return ScanResult(source_system="empty", objects=[], dependencies=[])


async def run_sync(app: SAPDocAgent, result: ScanResult) -> None:
    """Sync scan results to documentation platform."""
    logger.info("Syncing to %s...", app.config.doc_platform.type)
    sync_agent = DocSyncAgent(app.doc_platform, source_system_name="SAP Documentation")
    report = await sync_agent.sync_scan_result(result)
    logger.info(
        "Sync complete: %d created, %d updated, %d errors",
        report.pages_created,
        report.pages_updated,
        len(report.errors),
    )
    for err in report.errors:
        logger.warning("  Sync error: %s", err)


async def run_qa(app: SAPDocAgent, result: ScanResult, output_dir: Path) -> None:
    """Run quality checks and generate reports."""
    # Load standards
    standards = []
    for std_path in app.config.standards:
        path = Path(std_path)
        if path.exists():
            standards.append(load_standard(path))
            logger.info("Loaded standard: %s", path)

    # Doc QA
    qa_agent = DocQAAgent(standards, llm=app.llm)
    qa_report = qa_agent.check_all(result)
    logger.info(
        "Doc QA: score %.1f%% (%d issues across %d objects)",
        qa_report.score,
        len(qa_report.issues),
        qa_report.objects_checked,
    )

    # Code Quality
    code_agent = CodeQualityAgent()
    code_issues = code_agent.check_all(result)
    logger.info("Code Quality: %d issues found", len(code_issues))

    # BRS Traceability (if brs/ has requirements)
    brs_dir = Path("brs")
    trace_report = TraceReport(requirements=[], links=[], unlinked_requirements=[], orphan_objects=[])
    if brs_dir.exists():
        brs_agent = BRSTraceabilityAgent()
        for req_file in brs_dir.glob("*.yaml"):
            reqs = brs_agent.load_requirements(req_file)
            if reqs:
                trace_report = brs_agent.trace(reqs, result)
                logger.info(
                    "BRS: %d requirements, %d linked, %d unlinked, %d orphans",
                    len(trace_report.requirements),
                    len(trace_report.links),
                    len(trace_report.unlinked_requirements),
                    len(trace_report.orphan_objects),
                )

    # Generate reports
    gen = ReportGenerator(doc_platform_url=app.config.doc_platform.url)
    gen.write_reports(output_dir, qa_report, code_issues, trace_report)
    logger.info("Reports written to %s/reports/", output_dir)


async def run_audit(args) -> None:
    """Run documentation audit — no SAP access needed.

    Takes client documentation (directory of PDFs/markdown) and optionally
    their documentation standard, evaluates against Horvath best-practice.

    Usage:
        sap-doc-agent audit --docs ./client-docs/ [--client-standard ./guidelines.pdf] [--output ./report]
    """
    from sap_doc_agent.agents.doc_review import (
        DocReviewAgent,
        load_documentation_standard,
    )
    from sap_doc_agent.agents.pdf_ingest import PDFIngestor

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load Horvath standard
    horvath_std_path = Path("standards/horvath/documentation_standard.yaml")
    if not horvath_std_path.exists():
        logger.error("Horvath standard not found at %s", horvath_std_path)
        sys.exit(1)
    horvath_std = load_documentation_standard(horvath_std_path)
    logger.info("Loaded Horvath standard: %s", horvath_std.name)

    # Ingest client documents
    docs_path = Path(args.docs)
    if not docs_path.exists():
        logger.error("Documentation path not found: %s", docs_path)
        sys.exit(1)

    documents = []
    ingestor = PDFIngestor()
    if docs_path.is_dir():
        # Ingest all PDFs
        pdf_docs = ingestor.extract_from_directory(docs_path)
        documents.extend(pdf_docs)
        # Also ingest markdown files
        for md_file in sorted(docs_path.glob("**/*.md")):
            documents.append(
                {
                    "title": md_file.stem.replace("_", " ").replace("-", " "),
                    "content": md_file.read_text(),
                    "source_path": str(md_file),
                }
            )
        logger.info("Ingested %d documents from %s", len(documents), docs_path)
    elif docs_path.suffix.lower() == ".pdf":
        text = ingestor.extract_text(docs_path)
        documents.append({"title": docs_path.stem, "content": text, "source_path": str(docs_path)})
        logger.info("Ingested 1 PDF: %s", docs_path.name)
    else:
        documents.append({"title": docs_path.stem, "content": docs_path.read_text(), "source_path": str(docs_path)})

    if not documents:
        logger.error("No documents found at %s", docs_path)
        sys.exit(1)

    # Set up LLM if config provided
    llm = None
    if args.config:
        try:
            from sap_doc_agent.config import load_config
            from sap_doc_agent.llm import create_llm_provider

            config = load_config(args.config)
            llm = create_llm_provider(config.llm)
        except Exception as e:
            logger.warning("Could not load LLM config: %s — running in rule-based mode", e)

    agent = DocReviewAgent(horvath_std, llm=llm)
    app_name = args.name or docs_path.stem

    # Parse client standard if provided
    client_std = None
    if args.client_standard:
        cs_path = Path(args.client_standard)
        if cs_path.suffix in (".yaml", ".yml"):
            client_std = load_documentation_standard(cs_path)
            logger.info("Loaded client standard from YAML: %s", client_std.name)
        else:
            # Parse from PDF/text
            if cs_path.suffix.lower() == ".pdf":
                cs_content = ingestor.extract_text(cs_path)
            else:
                cs_content = cs_path.read_text()
            client_std = await agent.parse_client_standard(cs_path.stem, cs_content)
            logger.info(
                "Parsed client standard from %s: %d document types detected",
                cs_path.name,
                len(client_std.document_types),
            )

    # Run review
    if client_std:
        result = agent.review_against_both_standards(app_name, documents, client_std, scope=args.scope)
        logger.info("Horvath score: %.1f%%", result["horvath_score"])
        logger.info("Client score: %.1f%%", result["client_score"])
        logger.info("Gap analysis: %d findings", len(result["gap_analysis"]))
        for gap in result["gap_analysis"][:5]:
            logger.info("  Gap: %s", gap)

        # Write combined report
        report_content = _render_audit_report(app_name, result, documents)
    else:
        review = agent.review_documentation_set(app_name, documents, scope=args.scope)
        logger.info("Horvath score: %.1f%%", review.percentage)
        logger.info("Issues: %d", len(review.overall_issues))
        for issue in review.overall_issues[:10]:
            logger.info("  %s", issue)

        result = {"horvath_review": review}
        report_content = _render_audit_report(app_name, result, documents)

    # Write outputs
    report_md = output_dir / "audit_report.md"
    report_md.write_text(report_content)
    logger.info("Audit report written to %s", report_md)

    # Also write HTML version
    report_html = output_dir / "audit_report.html"
    report_html.write_text(_render_audit_html(app_name, result, documents))
    logger.info("HTML report written to %s", report_html)

    logger.info("Audit complete!")


def _render_audit_report(app_name: str, result: dict, documents: list[dict]) -> str:
    """Render audit results as markdown."""
    lines = [
        f"# Documentation Audit Report: {app_name}",
        "",
        f"**Documents reviewed:** {len(documents)}",
        "",
    ]

    hrvth = result.get("horvath_review")
    if hrvth:
        lines.extend(
            [
                "## Horvath Best-Practice Assessment",
                "",
                f"**Score: {hrvth.percentage}%**",
                "",
            ]
        )
        if hrvth.overall_issues:
            lines.append("### Issues Found")
            lines.append("")
            for issue in hrvth.overall_issues:
                lines.append(f"- {issue}")
            lines.append("")
        if hrvth.suggestions:
            lines.append("### Recommendations")
            lines.append("")
            for s in hrvth.suggestions:
                lines.append(f"- {s}")
            lines.append("")

    client = result.get("client_review")
    if client:
        lines.extend(
            [
                "## Client Standard Assessment",
                "",
                f"**Score: {client.percentage}%**",
                "",
            ]
        )
        if client.overall_issues:
            lines.append("### Issues Found")
            lines.append("")
            for issue in client.overall_issues:
                lines.append(f"- {issue}")
            lines.append("")

    gaps = result.get("gap_analysis")
    if gaps:
        lines.extend(
            [
                "## Gap Analysis: Client Standard vs. Horvath Best-Practice",
                "",
                "Areas where the client's documentation standard could be strengthened:",
                "",
            ]
        )
        for gap in gaps:
            lines.append(f"- {gap}")
        lines.append("")

    lines.extend(
        [
            "---",
            "*Generated by SAP Doc Agent — Horvath Documentation Standard v1.0*",
        ]
    )
    return "\n".join(lines)


def _render_audit_html(app_name: str, result: dict, documents: list[dict]) -> str:
    """Render audit results as self-contained HTML."""
    md_content = _render_audit_report(app_name, result, documents)
    # Simple markdown-to-html (headings, lists, bold)
    import re

    html_body = md_content
    html_body = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html_body, flags=re.MULTILINE)
    html_body = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html_body, flags=re.MULTILINE)
    html_body = re.sub(r"^# (.+)$", r"<h1>\1</h1>", html_body, flags=re.MULTILINE)
    html_body = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html_body)
    html_body = re.sub(r"^- (.+)$", r"<li>\1</li>", html_body, flags=re.MULTILINE)
    html_body = html_body.replace("\n\n", "</p><p>").replace("\n", "<br>")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Documentation Audit: {app_name}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; color: #333; line-height: 1.6; }}
h1 {{ color: #1a365d; border-bottom: 3px solid #2b6cb0; padding-bottom: 10px; }}
h2 {{ color: #2b6cb0; margin-top: 30px; }}
h3 {{ color: #4a5568; }}
li {{ margin: 4px 0; }}
strong {{ color: #2d3748; }}
hr {{ border: none; border-top: 1px solid #e2e8f0; margin: 30px 0; }}
</style>
</head>
<body>
<p>{html_body}</p>
</body>
</html>"""


async def main():
    parser = argparse.ArgumentParser(
        description="SAP Documentation Agent",
        usage="sap-doc-agent <command> [options]",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # --- Audit subcommand ---
    audit_parser = subparsers.add_parser(
        "audit",
        help="Run documentation audit (no SAP access needed)",
        description="Evaluate client documentation against Horvath best-practice and optionally their own standard.",
    )
    audit_parser.add_argument("--docs", required=True, help="Path to client docs (directory or single file)")
    audit_parser.add_argument("--client-standard", help="Path to client's documentation standard (PDF, YAML, or text)")
    audit_parser.add_argument("--name", help="Application/project name for the report")
    audit_parser.add_argument(
        "--scope",
        choices=["application", "system"],
        default="application",
        help="Review scope: 'application' (sections 2-7) or 'system' (architecture overview)",
    )
    audit_parser.add_argument("--output", default="output", help="Output directory for reports")
    audit_parser.add_argument("--config", help="Optional config file (for LLM access)")

    # --- Platform subcommand (full pipeline) ---
    platform_parser = subparsers.add_parser(
        "platform",
        help="Run full platform pipeline (scan, sync, QA, reports)",
        description="Full SAP documentation platform: scan systems, sync to doc platform, run quality checks.",
    )
    platform_parser.add_argument("--config", default="config.yaml", help="Path to config file")
    platform_parser.add_argument("--output", default="output", help="Output directory")
    platform_parser.add_argument("--scan", action="store_true", help="Run scanners")
    platform_parser.add_argument("--sync", action="store_true", help="Sync to doc platform")
    platform_parser.add_argument("--qa", action="store_true", help="Run quality checks")
    platform_parser.add_argument("--report", action="store_true", help="Generate reports")
    platform_parser.add_argument("--all", action="store_true", help="Run full pipeline")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "audit":
        await run_audit(args)
        return

    if args.command == "platform":
        if args.all:
            args.scan = args.sync = args.qa = args.report = True

        if not any([args.scan, args.sync, args.qa, args.report]):
            platform_parser.print_help()
            sys.exit(1)

        config_path = Path(args.config)
        if not config_path.exists():
            logger.error("Config file not found: %s", config_path)
            sys.exit(1)

        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)

        app = SAPDocAgent.from_config(config_path)
        result = ScanResult(source_system="empty", objects=[], dependencies=[])

        if args.scan:
            result = await run_scan(app, output_dir)

        if args.sync and result.objects:
            await run_sync(app, result)

        if args.qa or args.report:
            await run_qa(app, result, output_dir)

        logger.info("Done!")


def cli_main():
    asyncio.run(main())


if __name__ == "__main__":
    cli_main()
