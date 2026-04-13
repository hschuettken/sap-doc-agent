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


async def main():
    parser = argparse.ArgumentParser(description="SAP Documentation Agent")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--output", default="output", help="Output directory")
    parser.add_argument("--scan", action="store_true", help="Run scanners")
    parser.add_argument("--sync", action="store_true", help="Sync to doc platform")
    parser.add_argument("--qa", action="store_true", help="Run quality checks")
    parser.add_argument("--report", action="store_true", help="Generate reports")
    parser.add_argument("--all", action="store_true", help="Run full pipeline")
    args = parser.parse_args()

    if args.all:
        args.scan = args.sync = args.qa = args.report = True

    if not any([args.scan, args.sync, args.qa, args.report]):
        parser.print_help()
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
