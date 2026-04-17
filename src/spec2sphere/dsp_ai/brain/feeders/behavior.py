"""Behavior feeder — records widget telemetry events into the brain graph.

This is a **stub** created in Session B Task 2 so that the telemetry endpoint
can import ``record_event`` without error. Task 3 (Behavior Feeder) will replace
the body with real Neo4j writes and InfluxDB metrics.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...adapters.live import TelemetryEvent

logger = logging.getLogger(__name__)


async def record_event(event: "TelemetryEvent") -> None:
    """Placeholder — Task 3 fills this in with graph writes + metrics."""
    logger.debug("telemetry stub: kind=%s user=%s", event.kind, event.user_id)
