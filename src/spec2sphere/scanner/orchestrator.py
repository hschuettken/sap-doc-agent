"""
Scanner orchestrator: merge and deduplicate results from multiple scanners.
"""

from __future__ import annotations

from spec2sphere.scanner.models import Dependency, ScanResult, ScannedObject


class ScannerOrchestrator:
    """Merges and deduplicates ScanResult objects from multiple sources."""

    def merge(self, results: list[ScanResult]) -> ScanResult:
        """Concatenate all objects and dependencies from multiple ScanResults."""
        all_objects: list[ScannedObject] = []
        all_deps: list[Dependency] = []
        for result in results:
            all_objects.extend(result.objects)
            all_deps.extend(result.dependencies)
        return ScanResult(
            source_system="merged",
            objects=all_objects,
            dependencies=all_deps,
        )

    def deduplicate(self, result: ScanResult) -> ScanResult:
        """
        Remove duplicate objects (same name) and remap dependency IDs.

        For objects with the same name, the one with the longer description wins.
        Dependency source_id and target_id are remapped through the winner mapping.
        Duplicate edges (same source, target, type) are also removed.
        """
        # Group objects by name
        by_name: dict[str, list[ScannedObject]] = {}
        for obj in result.objects:
            by_name.setdefault(obj.name, []).append(obj)

        # For each name group: pick winner (longest description), build remap for losers
        winners: list[ScannedObject] = []
        id_remap: dict[str, str] = {}

        for name, group in by_name.items():
            if len(group) == 1:
                winners.append(group[0])
                continue
            # Sort: longest description first, then stable by object_id for determinism
            sorted_group = sorted(group, key=lambda o: (-len(o.description), o.object_id))
            winner = sorted_group[0]
            winners.append(winner)
            for loser in sorted_group[1:]:
                id_remap[loser.object_id] = winner.object_id

        # Remap dependency IDs through id_remap
        remapped_deps: list[Dependency] = []
        for dep in result.dependencies:
            new_source = id_remap.get(dep.source_id, dep.source_id)
            new_target = id_remap.get(dep.target_id, dep.target_id)
            remapped_deps.append(
                Dependency(
                    source_id=new_source,
                    target_id=new_target,
                    dependency_type=dep.dependency_type,
                    metadata=dep.metadata,
                )
            )

        # Deduplicate edges by (source, target, type)
        seen_edges: set[tuple[str, str, str]] = set()
        deduped_deps: list[Dependency] = []
        for dep in remapped_deps:
            key = (dep.source_id, dep.target_id, dep.dependency_type.value)
            if key not in seen_edges:
                seen_edges.add(key)
                deduped_deps.append(dep)

        return ScanResult(
            source_system=result.source_system,
            objects=winners,
            dependencies=deduped_deps,
        )
