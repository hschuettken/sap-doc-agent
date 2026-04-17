"""DSP data feeder — writes ``Event`` nodes into the Brain for observed
row-count deltas, distribution shifts, or schema changes on DSP objects.

Session A ships the row-count helper only; distribution + schema-change
variants land in Session B once the direct-DB scanner is wired up.
"""

from __future__ import annotations

import datetime as dt
import uuid

from ..client import run


async def record_row_count_delta(object_id: str, old: int, new: int) -> str:
    """Create an :Event node + CHANGED_AT edge for a row-count change.

    Returns the newly created Event id so callers can wire it to other
    edges (e.g. CORRELATED_WITH Topic) in follow-up work.
    """
    eid = str(uuid.uuid4())
    await run(
        """
        MERGE (o:DspObject {id: $oid})
        CREATE (e:Event {
            id: $eid, kind: 'data_change', ts: datetime($ts),
            old_value: $old, new_value: $new, metric: 'row_count'
        })
        MERGE (o)-[:CHANGED_AT]->(e)
        """,
        oid=object_id,
        eid=eid,
        ts=dt.datetime.now(dt.timezone.utc).isoformat(),
        old=old,
        new=new,
    )
    return eid
