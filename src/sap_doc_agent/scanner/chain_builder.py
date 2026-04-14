"""Build end-to-end data flow chains from a dependency graph."""

from __future__ import annotations

from collections import defaultdict

from sap_doc_agent.scanner.models import ChainStep, DataFlowChain, ObjectType

# Types that represent transformation steps (have logic)
_STEP_TYPES = {"TRANSFORMATION"}

# Types that are shared dependencies (master data), not chain members
_SHARED_TYPES = {"INFOOBJECT"}


def build_chains_from_graph(graph: dict) -> list[DataFlowChain]:
    """Walk a graph.json and identify all source-to-consumption chains.

    Algorithm:
    1. Build adjacency lists (forward + reverse)
    2. Find terminal nodes (no outgoing data edges, or COMPOSITE type)
    3. For each terminal, walk backwards collecting all upstream objects
    4. Extract transformation steps in execution order
    5. Identify inter-step storage objects and shared dependencies
    """
    nodes = {n["id"]: n for n in graph["nodes"]}

    # Forward: source -> [edges]
    forward: dict[str, list[dict]] = defaultdict(list)
    # Reverse: target -> [edges]
    reverse: dict[str, list[dict]] = defaultdict(list)

    for edge in graph["edges"]:
        forward[edge["source"]].append(edge)
        reverse[edge["target"]].append(edge)

    # Find terminal nodes: nodes with no downstream data consumers
    # (excluding REFERENCES edges which are shared deps)
    terminal_ids = set()
    for node_id, node in nodes.items():
        if node["type"] in _SHARED_TYPES:
            continue

        outgoing_data = [
            e
            for e in forward.get(node_id, [])
            if e["type"] in ("READS_FROM", "WRITES_TO") and nodes.get(e["target"], {}).get("type") not in _SHARED_TYPES
        ]
        if not outgoing_data or node["type"] == "COMPOSITE":
            terminal_ids.add(node_id)

    # Remove terminals that are ancestors of other terminals
    # (e.g. DSO_AGG is technically terminal but feeds CMP_REV)
    real_terminals = set()
    for tid in terminal_ids:
        # Check if any other terminal is downstream of this one
        is_ancestor = False
        for other_tid in terminal_ids:
            if other_tid == tid:
                continue
            # Check if tid is an ancestor of other_tid
            if _is_ancestor(tid, other_tid, forward, nodes):
                is_ancestor = True
                break
        if not is_ancestor:
            real_terminals.add(tid)

    chains = []
    chain_counter = 0

    for terminal_id in sorted(real_terminals):
        chain_counter += 1
        visited = set()
        all_ids = []
        shared_deps = []

        # BFS backwards from terminal
        queue = [terminal_id]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            all_ids.append(current)

            node = nodes.get(current, {})
            node_type = node.get("type", "")

            if node_type in _SHARED_TYPES:
                shared_deps.append(current)
                continue

            # Find upstream nodes
            for edge in reverse.get(current, []):
                upstream_id = edge["source"]
                if upstream_id not in visited:
                    queue.append(upstream_id)

        # Identify sources (nodes with no upstream data edges within this chain)
        source_ids = []
        for obj_id in all_ids:
            if obj_id in shared_deps:
                continue
            upstream_in_chain = [
                e["source"]
                for e in reverse.get(obj_id, [])
                if e["source"] in visited and e["source"] not in shared_deps
            ]
            if not upstream_in_chain:
                source_ids.append(obj_id)

        # Topological sort via BFS from sources
        chain_forward: dict[str, list[str]] = defaultdict(list)
        for edge in graph["edges"]:
            if edge["source"] in visited and edge["target"] in visited:
                if edge["type"] in ("READS_FROM", "WRITES_TO"):
                    chain_forward[edge["source"]].append(edge["target"])

        topo_order = []
        topo_visited: set[str] = set()
        topo_queue = list(source_ids)
        while topo_queue:
            current = topo_queue.pop(0)
            if current in topo_visited:
                continue
            topo_visited.add(current)
            topo_order.append(current)
            for next_id in chain_forward.get(current, []):
                if next_id not in topo_visited:
                    topo_queue.append(next_id)

        # Build ChainStep objects for transformations
        steps = []
        position = 0
        for obj_id in topo_order:
            node = nodes.get(obj_id, {})
            if node.get("type") not in _STEP_TYPES:
                continue
            position += 1

            # Find the inter-step object (what this transformation writes to)
            inter_step_id = None
            inter_step_name = None
            inter_step_fields: list[str] = []
            for next_id in chain_forward.get(obj_id, []):
                next_node = nodes.get(next_id, {})
                if next_node.get("type") in ("ADSO", "DATA_SOURCE"):
                    inter_step_id = next_id
                    inter_step_name = next_node.get("name", "")
                    inter_step_fields = next_node.get("metadata", {}).get("fields", [])
                    break

            steps.append(
                ChainStep(
                    position=position,
                    object_id=obj_id,
                    object_type=ObjectType(node["type"].lower()),
                    name=node.get("name", obj_id),
                    inter_step_object_id=inter_step_id,
                    inter_step_object_name=inter_step_name,
                    inter_step_fields=inter_step_fields,
                )
            )

        terminal_node = nodes.get(terminal_id, {})
        chain = DataFlowChain(
            chain_id=f"chain_{chain_counter:03d}",
            terminal_object_id=terminal_id,
            terminal_object_type=ObjectType(terminal_node.get("type", "other").lower()),
            source_object_ids=source_ids,
            steps=steps,
            all_object_ids=[oid for oid in all_ids if oid not in shared_deps],
            shared_dependency_ids=shared_deps,
        )
        chains.append(chain)

    return chains


def _is_ancestor(
    candidate: str,
    target: str,
    forward: dict[str, list[dict]],
    nodes: dict[str, dict],
) -> bool:
    """Check if candidate is an ancestor of target via forward edges."""
    visited: set[str] = set()
    queue = [candidate]
    while queue:
        current = queue.pop(0)
        if current == target:
            return True
        if current in visited:
            continue
        visited.add(current)
        for edge in forward.get(current, []):
            if edge["type"] in ("READS_FROM", "WRITES_TO"):
                queue.append(edge["target"])
    return False
