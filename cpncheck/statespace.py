"""The occurrence graph and its strongly connected components.

:func:`build_state_space` explores every reachable marking of a
:class:`~cpncheck.coloured.ColouredNet` breadth-first, keeping the BFS parent of
each node so that a shortest occurrence sequence to any marking can be printed.
:class:`StateSpace` holds the result and its Tarjan decomposition, from which
terminal components and home markings follow.

Markings carry real token values: there is no abstraction, and two markings
that differ in one token value are two nodes.
"""

import collections
import time
from typing import Any, Dict, List, Optional, Tuple

from .coloured import ColouredNet

#: Maximum number of markings explored before giving up on a state space.
DEFAULT_MAX_NODES = 200_000

__all__ = ["StateSpace", "build_state_space", "DEFAULT_MAX_NODES"]


# ---------------------------------------------------------------------------
# The occurrence graph
# ---------------------------------------------------------------------------

# Class holding a computed occurrence graph and its SCC decomposition.
class StateSpace:
    """The occurrence graph of a net and the derived structures.

    Attributes:
        net (ColouredNet): The explored net.
        markings (list): Marking of each node; node 0 is the initial marking.
        succ (list): Per node, ``(transition index, binding key, target)``.
        pred (list): Per node, ``(transition index, source)``.
        parent (list): BFS tree parent ``(source, transition index, binding
            key)`` per node, which is what a counterexample trace is built
            from -- the binding is kept because a trace without it cannot be
            re-fired.
        dead (list): Nodes without successors.
        complete (bool): False when exploration stopped at the node budget.
        scc (list): SCC index of every node.
        terminal_sccs (list): SCC indices with no arc leaving them.
        home (list): Home markings (nodes of the unique terminal SCC).
        elapsed (float): Generation time in seconds.
        enabled (list|None): For a reduced graph, the transition of every
            binding element enabled at each node -- the arcs alone list only
            the expanded ones. None for a full graph, whose arcs are all of
            them.
        reduction (str|None): The reduction kind (:mod:`cpncheck.reduction`),
            or None for the full occurrence graph.
    """

    # Method to hold the graph data.
    def __init__(self, net, markings, succ, complete, elapsed, parent,
                 enabled=None, reduction=None):
        """Create the state space and compute its SCC decomposition.

        Args:
            net (ColouredNet): The net.
            markings (list): Node markings.
            succ (list): Successor lists.
            complete (bool): Whether exploration finished.
            elapsed (float): Generation time.
            parent (list): BFS parents.
            enabled (list, optional): Enabled transitions per node, for a
                reduced graph.
            reduction (str, optional): The reduction kind, for a reduced
                graph.
        """
        self.net = net
        self.enabled = enabled
        self.reduction = reduction
        self.markings = markings
        self.succ = succ
        self.complete = complete
        self.elapsed = elapsed
        self.parent = parent
        self.pred: List[List[Tuple[int, int]]] = [[] for _ in markings]
        for src, out in enumerate(succ):
            for ti, _key, dst in out:
                self.pred[dst].append((ti, src))
        self.dead = [n for n, out in enumerate(succ) if not out]
        self._compute_sccs()

    # Property returning the number of nodes.
    @property
    def n_nodes(self) -> int:
        """Number of reachable markings.

        Returns:
            int: Node count.
        """
        return len(self.markings)

    # Property returning the number of arcs.
    @property
    def n_arcs(self) -> int:
        """Number of binding-element occurrences in the graph.

        Returns:
            int: Arc count.
        """
        return sum(len(out) for out in self.succ)

    # Method to compute strongly connected components with Tarjan's algorithm.
    def _compute_sccs(self):
        """Iterative Tarjan decomposition, then terminal SCCs and home markings.

        A home marking exists exactly when the SCC graph has a single terminal
        component, and then every marking of that component is a home marking
        (Jensen & Kristensen, 2009). This is also how CPN Tools computes
        ``ListHomeMarkings``.
        """
        n = len(self.markings)
        index = [-1] * n
        low = [0] * n
        on_stack = [False] * n
        stack: List[int] = []
        comp = [-1] * n
        counter = 0
        n_comp = 0
        for root in range(n):
            if index[root] != -1:
                continue
            work = [(root, 0)]
            while work:
                v, i = work.pop()
                if i == 0:
                    index[v] = low[v] = counter
                    counter += 1
                    stack.append(v)
                    on_stack[v] = True
                recurse = False
                out = self.succ[v]
                while i < len(out):
                    w = out[i][2]
                    i += 1
                    if index[w] == -1:
                        work.append((v, i))
                        work.append((w, 0))
                        recurse = True
                        break
                    if on_stack[w]:
                        low[v] = min(low[v], index[w])
                if recurse:
                    continue
                if low[v] == index[v]:
                    while True:
                        w = stack.pop()
                        on_stack[w] = False
                        comp[w] = n_comp
                        if w == v:
                            break
                    n_comp += 1
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[v])
        self.scc = comp
        self.n_sccs = n_comp
        leaves = set(range(n_comp))
        inter_arcs = 0
        for src, out in enumerate(self.succ):
            for _ti, _key, dst in out:
                if comp[src] != comp[dst]:
                    leaves.discard(comp[src])
                    inter_arcs += 1
        self.n_scc_arcs = inter_arcs
        self.terminal_sccs = sorted(leaves)
        if len(self.terminal_sccs) == 1:
            c = self.terminal_sccs[0]
            self.home = [v for v in range(n) if comp[v] == c]
        else:
            self.home = []

    # Method to count the tokens of one place in one node.
    def tokens(self, node: int, pidx: int) -> tuple:
        """Tokens held by a place in a marking.

        Args:
            node (int): Node id.
            pidx (int): Place index.

        Returns:
            tuple: The sorted token values.
        """
        return self.markings[node][pidx]

    # Method to list the shortest occurrence sequence reaching a node.
    def path(self, node: int) -> List[Tuple[int, tuple, int]]:
        """Shortest occurrence sequence from the initial marking to a node.

        Args:
            node (int): Target node.

        Returns:
            list: ``(transition index, binding key, node reached)`` per step,
            in order; empty when the node is the initial marking.
        """
        steps: List[Tuple[int, tuple, int]] = []
        while node != 0 and self.parent[node] is not None:
            src, ti, key = self.parent[node]
            steps.append((ti, key, node))
            node = src
        steps.reverse()
        return steps

    # Method to print the shortest firing sequence reaching a node.
    def trace(self, node: int, limit: int = 12) -> str:
        """Shortest occurrence sequence to a node, as text.

        Args:
            node (int): Target node.
            limit (int): Maximum number of steps to print.

        Returns:
            str: ``t1 -> t2 -> ...``.
        """
        steps = [self.net.transitions[ti]["name"]
                 for ti, _key, _dst in self.path(node)]
        if not steps:
            return "(initial marking)"
        if len(steps) > limit:
            steps = steps[:3] + [f"... {len(steps) - 6} more ..."] + steps[-3:]
        return " -> ".join(steps)


# Function to build the occurrence graph of a net by breadth-first search.
def build_state_space(net: ColouredNet, max_nodes: int = DEFAULT_MAX_NODES,
                      initial: Optional[tuple] = None) -> StateSpace:
    """Explore every reachable marking.

    Args:
        net (ColouredNet): The net to explore.
        max_nodes (int): Stop after this many markings; the result is then
            flagged as incomplete and must not be used for verdicts.
        initial (tuple, optional): Start from this marking instead of the
            net's own initial marking (another input sample).

    Returns:
        StateSpace: The (possibly partial) occurrence graph.
    """
    t0 = time.perf_counter()
    start = net.initial if initial is None else initial
    nodes = {start: 0}
    markings = [start]
    succ: List[List[Tuple[int, Tuple, int]]] = [[]]
    parent: List[Optional[Tuple[int, int, tuple]]] = [None]
    queue = collections.deque([0])
    complete = True
    while queue:
        src = queue.popleft()
        marking = markings[src]
        for ti, key, env in net.enabled(marking):
            nxt = net.fire(marking, ti, env)
            dst = nodes.get(nxt)
            if dst is None:
                if len(markings) >= max_nodes:
                    complete = False
                    continue
                dst = len(markings)
                nodes[nxt] = dst
                markings.append(nxt)
                succ.append([])
                parent.append((src, ti, key))
                queue.append(dst)
            succ[src].append((ti, key, dst))
    return StateSpace(net, markings, succ, complete,
                      time.perf_counter() - t0, parent)
