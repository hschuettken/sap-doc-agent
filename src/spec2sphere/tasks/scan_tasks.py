"""Celery scan tasks — invoke real scanners, write graph.json, persist to landscape.

Each task is a thin asyncio wrapper around the CLI-level scan flow:
1. Load config
2. Resolve system
3. Run DSP REST or CDP scan (by type)
4. Write output/objects/*.md + output/graph.json
5. Record success/failure in logs

Tasks are intended to chain into build_chains, which reads graph.json.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from spec2sphere.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _scan_dsp_api(system_name: str, config_path: str, output_dir: Path) -> dict:
    """Run the DSP REST API scanner for the named system."""
    from spec2sphere.app import SAPDocAgent
    from spec2sphere.scanner.dsp_auth import DSPAuth
    from spec2sphere.scanner.dsp_scanner import DSPScanner
    from spec2sphere.scanner.models import ScanResult
    from spec2sphere.scanner.orchestrator import ScannerOrchestrator
    from spec2sphere.scanner.output import write_scan_output

    app = SAPDocAgent.from_config(config_path)

    system = next((s for s in app.config.sap_systems if s.name == system_name), None)
    if system is None:
        return {"status": "failed", "reason": f"system {system_name!r} not found in config"}
    if system.type != "datasphere":
        return {"status": "skipped", "reason": f"system {system_name!r} is not a DSP system"}

    token_url = os.environ.get(system.oauth.token_url_env, "")
    base_url = token_url.rsplit("/oauth", 1)[0] if "/oauth" in token_url else token_url

    auth = DSPAuth(
        client_id=os.environ.get(system.oauth.client_id_env, ""),
        client_secret=os.environ.get(system.oauth.client_secret_env, ""),
        token_url=token_url,
    )
    scanner = DSPScanner(
        base_url=base_url,
        auth=auth,
        spaces=system.spaces or [],
        namespace_filter=system.scan_scope.namespace_filter if system.scan_scope else None,
    )

    result: ScanResult = await scanner.scan()

    orch = ScannerOrchestrator()
    deduped = orch.deduplicate(orch.merge([result]))
    write_scan_output(deduped, output_dir)

    return {
        "status": "completed",
        "system_name": system_name,
        "objects": len(deduped.objects),
        "dependencies": len(deduped.dependencies),
    }


async def _scan_cdp(system_name: str, config_path: str, output_dir: Path) -> dict:
    """Placeholder for CDP-based deep scan — requires a live DSP tenant + browser.

    The real CDP scan is driven from the browser pool + cdp_scanner module.
    This task accepts extractions produced elsewhere (e.g. an interactive
    session) and persists them. Without extractions we return a skipped status
    instead of silently succeeding.
    """
    extractions_path = output_dir / "cdp_extractions.json"
    if not extractions_path.exists():
        return {
            "status": "skipped",
            "reason": "no CDP extractions found; run interactive CDP session first",
            "expected_path": str(extractions_path),
        }

    import json

    from spec2sphere.scanner.cdp_scanner import DSPCDPScanner
    from spec2sphere.scanner.orchestrator import ScannerOrchestrator
    from spec2sphere.scanner.output import write_scan_output

    extractions = json.loads(extractions_path.read_text())
    scanner = DSPCDPScanner(source_system=system_name)
    result = scanner.scan_from_extractions(extractions)

    orch = ScannerOrchestrator()
    deduped = orch.deduplicate(orch.merge([result]))
    write_scan_output(deduped, output_dir)

    return {
        "status": "completed",
        "system_name": system_name,
        "objects": len(deduped.objects),
        "dependencies": len(deduped.dependencies),
    }


def _resolve_output_dir(config_path: str) -> Path:
    """Load config, return the configured output_dir or ./output as fallback."""
    try:
        from spec2sphere.app import SAPDocAgent

        app = SAPDocAgent.from_config(config_path)
        # AppConfig.output_dir is the canonical source; fall back to ./output
        out = getattr(app.config, "output_dir", None) or "output"
        return Path(out)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load config at %s (%s) — defaulting to ./output", config_path, exc)
        return Path("output")


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, queue="scan")
def run_scan(
    self, scanner_type: str = "dsp_api", config_path: str = "config.yaml", run_id: str = "", system_name: str = ""
) -> dict:
    """Dispatch to the correct scanner based on type.

    scanner_type: "dsp_api" (default) or "cdp".
    system_name: when empty, scans every configured DSP system.
    """
    logger.info("run_scan: type=%s run_id=%s system=%s", scanner_type, run_id, system_name or "<all>")
    output_dir = _resolve_output_dir(config_path)

    from spec2sphere.telemetry import get_tracer as _get_tracer  # noqa: PLC0415

    _active_tracer = _get_tracer()

    async def _run_all() -> list[dict]:
        if system_name:
            systems = [system_name]
        else:
            from spec2sphere.app import SAPDocAgent

            app = SAPDocAgent.from_config(config_path)
            systems = [s.name for s in app.config.sap_systems if s.type == "datasphere"]
            if not systems:
                return [{"status": "skipped", "reason": "no DSP systems configured"}]

        results = []
        for name in systems:
            if scanner_type == "cdp":
                r = await _scan_cdp(name, config_path, output_dir)
            else:
                r = await _scan_dsp_api(name, config_path, output_dir)
            results.append(r)
        return results

    def _execute() -> list[dict]:
        return asyncio.run(_run_all())

    if _active_tracer:
        with _active_tracer.start_as_current_span("scanner.run") as _span:
            _span.set_attribute("scanner.type", scanner_type)
            _span.set_attribute("scanner.run_id", run_id)
            _span.set_attribute("scanner.system", system_name or "<all>")
            try:
                outcomes = _execute()
            except FileNotFoundError as exc:
                logger.warning("run_scan: config file not found (%s) — returning skipped", exc)
                return {
                    "run_id": run_id,
                    "status": "skipped",
                    "scanner_type": scanner_type,
                    "reason": f"config not found: {exc}",
                }
            except Exception as exc:  # noqa: BLE001
                logger.exception("run_scan failed: %s", exc)
                raise self.retry(exc=exc)
    else:
        try:
            outcomes = _execute()
        except FileNotFoundError as exc:
            # Permanent failure — don't retry for a missing config file
            logger.warning("run_scan: config file not found (%s) — returning skipped", exc)
            return {
                "run_id": run_id,
                "status": "skipped",
                "scanner_type": scanner_type,
                "reason": f"config not found: {exc}",
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("run_scan failed: %s", exc)
            raise self.retry(exc=exc)

    return {
        "run_id": run_id,
        "status": "completed",
        "scanner_type": scanner_type,
        "outcomes": outcomes,
    }


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, queue="scan")
def run_abap_scan(self, system_name: str, config_path: str, run_id: str) -> dict:
    """BW/4HANA scans run on the SAP system via ABAP (Z_DOC_AGENT_SCAN) and push
    output to Git. This task imports whatever the ABAP side has already pushed.
    """
    output_dir = _resolve_output_dir(config_path)
    bw_import = output_dir / "bw_import"
    if not bw_import.exists():
        return {
            "run_id": run_id,
            "status": "skipped",
            "reason": "no BW import directory found; run Z_DOC_AGENT_SCAN on the SAP system first",
            "expected_path": str(bw_import),
            "system_name": system_name,
        }

    # Count what's there (full parser is a future enhancement)
    files = list(bw_import.rglob("*.md")) + list(bw_import.rglob("*.json"))
    return {
        "run_id": run_id,
        "status": "completed",
        "system_name": system_name,
        "imported_files": len(files),
        "note": "BW structural import completed; merge into graph.json is manual for now",
    }


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, queue="scan")
def run_dsp_api_scan(self, system_name: str, config_path: str, run_id: str) -> dict:
    """Single-system DSP REST API scan."""
    logger.info("run_dsp_api_scan: system=%s run_id=%s", system_name, run_id)
    output_dir = _resolve_output_dir(config_path)
    try:
        outcome = asyncio.run(_scan_dsp_api(system_name, config_path, output_dir))
    except Exception as exc:  # noqa: BLE001
        logger.exception("run_dsp_api_scan failed: %s", exc)
        raise self.retry(exc=exc)
    return {"run_id": run_id, **outcome}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, queue="chrome")
def run_cdp_scan(self, system_name: str, config_path: str, run_id: str) -> dict:
    """Single-system CDP import (expects cdp_extractions.json pre-produced)."""
    logger.info("run_cdp_scan: system=%s run_id=%s", system_name, run_id)
    output_dir = _resolve_output_dir(config_path)
    try:
        outcome = asyncio.run(_scan_cdp(system_name, config_path, output_dir))
    except Exception as exc:  # noqa: BLE001
        logger.exception("run_cdp_scan failed: %s", exc)
        raise self.retry(exc=exc)
    return {"run_id": run_id, **outcome}
