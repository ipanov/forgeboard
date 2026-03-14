"""
Parameter dependency tracking for ForgeBoard.

Provides a directed graph of parameter dependencies used for change
propagation: when a master parameter changes (e.g. pole diameter), the graph
determines which downstream parameters are affected and in what order they
must be re-evaluated.

The graph supports:
    - Adding named parameters as nodes.
    - Adding directed dependency edges with optional transformation formulas.
    - Cascade detection: BFS from a changed parameter to find all affected
      downstream parameters.
    - Topological sort: determines safe evaluation order (Kahn's algorithm).
    - Cycle detection.

Also usable at the component level (node = component instance name) for
assembly solve-order determination.

Example::

    g = DependencyGraph()
    g.add_dependency("pole.outer_diameter", "clamp.bore_id", "source + 1.0")
    g.add_dependency("clamp.bore_id", "adapter.inner_diameter", "source")
    affected = g.detect_cascade("pole.outer_diameter")
    # -> ["clamp.bore_id", "adapter.inner_diameter"]
    order = g.topological_sort()
    # -> ["pole.outer_diameter", "clamp.bore_id", "adapter.inner_diameter"]
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class DependencyEdge:
    """A directed edge from *source* to *target* with an optional formula.

    The formula is a string expression.  When evaluated, the variable
    ``source`` is bound to the current value of the source parameter.
    For example: ``"source + 1.0"`` or ``"source * 0.5"``.  If the formula
    is ``None``, the dependency is tracked for ordering purposes only
    (identity propagation: target = source).
    """

    source: str
    target: str
    formula: Optional[str] = None


class DependencyGraph:
    """Directed graph of parameter or component dependencies.

    Nodes are parameter names (strings like ``"pole.outer_diameter"`` or
    component instance names like ``"base_plate"``).  An edge from A to B
    means "when A changes, B must be re-evaluated".

    Usage::

        g = DependencyGraph()
        g.add_dependency("pole.od_mm", "clamp.bore_mm", "source + 1.0")
        g.add_dependency("clamp.bore_mm", "adapter.id_mm", "source")

        # What changes if we modify pole.od_mm?
        affected = g.detect_cascade("pole.od_mm")
        # -> ["clamp.bore_mm", "adapter.id_mm"]

        # Safe evaluation order
        order = g.topological_sort()
        # -> ["pole.od_mm", "clamp.bore_mm", "adapter.id_mm"]
    """

    def __init__(self) -> None:
        self._nodes: set[str] = set()
        # Forward edges: source -> set of targets
        self._forward: dict[str, set[str]] = defaultdict(set)
        # Reverse edges: target -> set of sources
        self._reverse: dict[str, set[str]] = defaultdict(set)
        # Edge metadata: (source, target) -> DependencyEdge
        self._edges: dict[tuple[str, str], DependencyEdge] = {}

    # -- Mutation -------------------------------------------------------------

    def add_node(self, name: str) -> None:
        """Ensure *name* exists in the graph (even without edges)."""
        self._nodes.add(name)

    def add_dependency(
        self,
        source_param: str,
        target_param: str,
        formula: Optional[str] = None,
    ) -> None:
        """Add a directed dependency: *target_param* depends on *source_param*.

        Parameters
        ----------
        source_param:
            The upstream parameter name.
        target_param:
            The downstream parameter that must be updated when *source_param*
            changes.
        formula:
            Optional string expression.  When evaluated, ``source`` is bound
            to the current value of *source_param*.  Examples:
            ``"source + 1.0"``, ``"source * 0.5"``, ``"max(source, 10)"``.
            If ``None``, the relationship is tracked for ordering only.
        """
        self._nodes.add(source_param)
        self._nodes.add(target_param)
        self._forward[source_param].add(target_param)
        self._reverse[target_param].add(source_param)
        self._edges[(source_param, target_param)] = DependencyEdge(
            source=source_param,
            target=target_param,
            formula=formula,
        )

    # Backward-compat alias (the previous version used add_edge)
    def add_edge(self, source: str, target: str) -> None:
        """Add a dependency edge without a formula (alias for add_dependency)."""
        self.add_dependency(source, target, formula=None)

    # -- Cascade detection ----------------------------------------------------

    def detect_cascade(self, changed_param: str) -> list[str]:
        """BFS from *changed_param* to find all transitively affected parameters.

        Returns a list of affected parameters in BFS order (breadth-first).
        The *changed_param* itself is NOT included in the result.
        """
        if changed_param not in self._nodes:
            return []

        visited: set[str] = set()
        queue: deque[str] = deque()
        result: list[str] = []

        # Seed with direct dependents
        for dep in sorted(self._forward.get(changed_param, set())):
            if dep not in visited:
                visited.add(dep)
                queue.append(dep)
                result.append(dep)

        # BFS
        while queue:
            current = queue.popleft()
            for dep in sorted(self._forward.get(current, set())):
                if dep not in visited:
                    visited.add(dep)
                    queue.append(dep)
                    result.append(dep)

        return result

    # -- Topological sort -----------------------------------------------------

    def topological_sort(self) -> list[str]:
        """Return nodes in topological order (Kahn's algorithm).

        Nodes with no incoming edges come first.  Within the same
        topological level, nodes are sorted alphabetically for
        deterministic output.

        Raises
        ------
        ValueError
            If the graph contains a cycle.
        """
        in_degree: dict[str, int] = {n: 0 for n in self._nodes}
        for targets in self._forward.values():
            for t in targets:
                in_degree[t] = in_degree.get(t, 0) + 1

        queue: deque[str] = deque(
            n for n, d in sorted(in_degree.items()) if d == 0
        )
        result: list[str] = []

        while queue:
            node = queue.popleft()
            result.append(node)
            for neighbour in sorted(self._forward.get(node, set())):
                in_degree[neighbour] -= 1
                if in_degree[neighbour] == 0:
                    queue.append(neighbour)

        if len(result) != len(self._nodes):
            missing = self._nodes - set(result)
            raise ValueError(
                f"Dependency cycle detected involving: {sorted(missing)}"
            )

        return result

    # -- Query helpers --------------------------------------------------------

    def dependents(self, name: str) -> set[str]:
        """Return the set of nodes that directly depend on *name*."""
        return set(self._forward.get(name, set()))

    def dependencies(self, name: str) -> set[str]:
        """Return the set of nodes that *name* directly depends on."""
        return set(self._reverse.get(name, set()))

    def get_edge(
        self, source: str, target: str
    ) -> Optional[DependencyEdge]:
        """Return the edge metadata between *source* and *target*, if any."""
        return self._edges.get((source, target))

    def get_formula(self, source: str, target: str) -> Optional[str]:
        """Return the formula string for the edge from *source* to *target*."""
        edge = self._edges.get((source, target))
        return edge.formula if edge else None

    def has_cycle(self) -> bool:
        """Return True if the graph contains a cycle."""
        try:
            self.topological_sort()
            return False
        except ValueError:
            return True

    @property
    def nodes(self) -> set[str]:
        """All parameter / component names in the graph."""
        return set(self._nodes)

    @property
    def edges(self) -> list[DependencyEdge]:
        """All dependency edges in the graph."""
        return list(self._edges.values())

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, name: str) -> bool:
        return name in self._nodes

    def __repr__(self) -> str:
        return (
            f"DependencyGraph({len(self._nodes)} nodes, "
            f"{len(self._edges)} edges)"
        )
