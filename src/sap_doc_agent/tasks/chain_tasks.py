"""Celery tasks for chain-level documentation."""

import json
import logging
from pathlib import Path

from sap_doc_agent.scanner.chain_builder import build_chains_from_graph
from sap_doc_agent.scanner.output import render_chain_markdown
from sap_doc_agent.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30, queue="scan")
def build_chains(self, output_dir: str, scan_id: str) -> dict:
    """Post-process a scan: build chains from graph.json, write chain docs."""
    output_path = Path(output_dir)
    graph_path = output_path / "graph.json"

    if not graph_path.exists():
        return {"status": "skipped", "reason": "no graph.json", "scan_id": scan_id}

    with open(graph_path) as f:
        graph = json.load(f)

    objects_dir = output_path / "objects"
    chains = build_chains_from_graph(graph, objects_dir=objects_dir if objects_dir.exists() else None)

    # Write chain markdown + JSON files
    chains_dir = output_path / "chains"
    chains_dir.mkdir(exist_ok=True)

    chain_ids = []
    for chain in chains:
        md = render_chain_markdown(chain)
        chain_file = chains_dir / f"{chain.chain_id}.md"
        chain_file.write_text(md)
        chain_ids.append(chain.chain_id)

        # Also write raw JSON for programmatic access
        json_file = chains_dir / f"{chain.chain_id}.json"
        json_file.write_text(chain.model_dump_json(indent=2))

    logger.info("build_chains: scan_id=%s chains=%d", scan_id, len(chains))

    # Fan-out: dispatch LLM analysis for each chain
    dispatched = 0
    for chain_id in chain_ids:
        json_path = str(chains_dir / f"{chain_id}.json")
        try:
            analyze_single_chain.apply_async(kwargs={"chain_json_path": json_path})
            dispatched += 1
        except Exception as exc:
            # Celery broker unavailable — skip fan-out, chains can be analyzed later
            logger.warning("Could not dispatch analyze_single_chain for %s: %s", chain_id, exc)
            break

    return {
        "status": "completed",
        "scan_id": scan_id,
        "chain_count": len(chains),
        "chain_ids": chain_ids,
        "analysis_dispatched": dispatched,
    }


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30, queue="llm")
def analyze_single_chain(self, chain_json_path: str, config_path: str = "config.yaml") -> dict:
    """LLM analysis of a single chain (2-pass: step summaries + chain summary)."""
    import asyncio

    from sap_doc_agent.app import SAPDocAgent
    from sap_doc_agent.scanner.chain_analyzer import analyze_chain_steps, summarize_chain
    from sap_doc_agent.scanner.models import DataFlowChain

    chain_path = Path(chain_json_path)
    chain = DataFlowChain.model_validate_json(chain_path.read_text())
    app = SAPDocAgent.from_config(config_path)

    async def _run():
        analyzed = await analyze_chain_steps(chain, app.llm)
        summarized = await summarize_chain(analyzed, app.llm)
        return summarized

    result = asyncio.run(_run())

    # Overwrite chain files with analysis results
    chain_path.write_text(result.model_dump_json(indent=2))

    md_path = chain_path.with_suffix(".md")
    md_path.write_text(render_chain_markdown(result))

    logger.info(
        "analyze_single_chain: chain_id=%s name=%s confidence=%.2f",
        result.chain_id,
        result.name,
        result.confidence,
    )

    return {
        "status": "completed",
        "chain_id": result.chain_id,
        "name": result.name,
        "confidence": result.confidence,
    }
