"""ASK-CTL queries as input: the SML a CPN Tools user already wrote.

A query file is what one would evaluate in CPN Tools after *Enter State
Space*::

    use (ogpath^"ASKCTL/ASKCTLloader.sml");      (* skipped: nothing to load *)
    fun Eating n = Mark.Top'Eat 1 n <> empty;
    val NoStarvation = eval_node (INV (POS (NF ("eating", Eating)))) InitNode;
    eval_node (EV (NF ("eating", Eating))) InitNode;

Every top-level ``eval_node F InitNode`` (bare, or bound with ``val``) becomes
a property, named after the ``val`` (``Q1``, ``Q2``, ... when bare). The rest
of the file is CPN ML declarations, evaluated with the net's own
declarations and the state-space functions below.

Semantics
---------
The formulas mean exactly what ``ASKCTL.sml`` (shipped with CPN Tools 4.0.1)
makes them mean, which is not textbook CTL:

* formulas are evaluated at nodes or at arcs; ``MODAL`` moves between them,
  ``NF`` predicates hold of nodes and ``AF`` predicates of arcs;
* ``FORALL_UNTIL`` -- hence ``EV`` -- holds vacuously at a dead marking
  (``forall`` over no successors), and ``ALONG`` never holds there;
* the formula is first rewritten (``NOT (NOT a)`` is ``a``, ``POS (EV a)`` is
  ``POS a``, ``OR`` with ``TT``/``FF`` folds, ...), and then three shapes are
  decided on the SCC graph instead: ``POS (INV a)``, ``POS (ALONG a)`` and
  ``EV (INV a)``. Those do *not* treat dead markings vacuously: for them a
  dead marking is a terminal component like any other.

Everything else is the least fixpoint the basic evaluator computes. (CPN
Tools' evaluator is a memoised depth-first search that answers ``false`` on a
node still in progress; on some graphs that memo depends on the order of the
search, and CPNCheck gives the fixpoint.)

State-space functions
---------------------
``InitNode``, ``NoOfNodes``, ``NoOfArcs``, ``OutArcs``, ``InArcs``,
``OutNodes``, ``InNodes``, ``SourceNode``, ``DestNode``, ``ArcToTI``,
``ArcToBE``, ``Reachable``, ``NodesInPath``, ``ArcsInPath``,
``ListDeadMarkings``, ``ListHomeMarkings``, ``ListDeadTIs``,
``ListLiveTIs``, ``PredAllNodes``, ``PredAllArcs``, ``PredNodes``,
``PredArcs``, ``SearchAllNodes``, ``SearchAllArcs``, ``SearchNodes``,
``SearchArcs``, ``EntireGraph``, ``NoLimit``, ``NodeToScc``, ``SccToNodes``,
``SccTerminal``, ``SccTrivial``, ``SccNoOfNodes``, ``SccNoOfArcs``,
``Mark.<page>'<place> <instance> <node>``, ``TI.<page>'<transition>
<instance>`` and ``Bind.<page>'<transition> (<instance>, {<binding>})``.

``Mark`` gives the colours of the tokens; timestamps are not kept. Node and
arc numbers are CPNCheck's (node 1 is the initial marking, as in CPN Tools);
other numbers need not match CPN Tools' own, so a query should not compare
them with literals.
"""

import collections
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

from .cpnml import (DataConstructor, MLError, MultiSet, Parser, RecordValue,
                    _constructors_declaration, compile_expression,
                    match_pattern, tokenize)
from .formula import Context, Formula

__all__ = ["AskCtlError", "AskCtlScript", "AskCtlQuery", "load_askctl",
           "parse_askctl"]


# Exception raised for a query file that cannot be used.
class AskCtlError(ValueError):
    """An ASK-CTL file that does not parse or asks something unsupported."""


# ---------------------------------------------------------------------------
# The formulas, as ASKCTL.sml builds them
# ---------------------------------------------------------------------------
#
# A formula is a tuple: ("NF", name, predicate), ("AF", name, predicate),
# ("TT",), ("NOT", a), ("OR", a, b), ("EU", a, b), ("FU", a, b),
# ("MODAL", a). Every other operator is derived, as in ASKCTL.sml.

TT = ("TT",)
FF = ("NOT", TT)


# Function to build the ASK-CTL constructors and derived operators.
def _operators() -> Dict[str, Any]:
    """``NF``, ``AF``, ``TT``, ``FF``, ``NOT``, ``AND``, ... as ML values.

    Returns:
        dict: ``name -> value``; binary operators take a pair.
    """
    def OR(pair):
        return ("OR", pair[0], pair[1])

    def NOT(a):
        return ("NOT", a)

    def AND(pair):
        return NOT(OR((NOT(pair[0]), NOT(pair[1]))))

    def MODAL(a):
        return ("MODAL", a)

    def EXIST_MODAL(pair):
        return MODAL(AND((pair[0], MODAL(pair[1]))))

    def EXIST_NEXT(a):
        return EXIST_MODAL((TT, a))

    def EXIST_UNTIL(pair):
        return ("EU", pair[0], pair[1])

    def FORALL_UNTIL(pair):
        return ("FU", pair[0], pair[1])

    def EV(a):
        return FORALL_UNTIL((TT, a))

    def POS(a):
        return EXIST_UNTIL((TT, a))

    return {
        "TT": TT, "FF": FF,
        "NF": lambda pair: ("NF", pair[0], pair[1]),
        "AF": lambda pair: ("AF", pair[0], pair[1]),
        "NOT": NOT, "OR": OR, "AND": AND, "MODAL": MODAL,
        "EXIST_UNTIL": EXIST_UNTIL, "FORALL_UNTIL": FORALL_UNTIL,
        "EXIST_MODAL": EXIST_MODAL,
        "FORALL_MODAL": lambda pair: NOT(EXIST_MODAL((pair[0], NOT(pair[1])))),
        "EXIST_NEXT": EXIST_NEXT,
        "FORALL_NEXT": lambda a: NOT(EXIST_NEXT(NOT(a))),
        "POS": POS, "INV": lambda a: NOT(POS(NOT(a))),
        "EV": EV, "ALONG": lambda a: NOT(EV(NOT(a))),
    }


# Function to switch between node and arc evaluation.
def _flip(mode: str) -> str:
    """``"S"`` (nodes) for ``"T"`` (arcs) and back.

    Args:
        mode (str): The current mode.

    Returns:
        str: The other one.
    """
    return "T" if mode == "S" else "S"


# Function to simplify a formula as ASKCTL.sml does before evaluating it.
def rewrite(f: tuple, mode: str) -> tuple:
    """ASKCTL.sml's ``rewrite``, clause for clause.

    Args:
        f (tuple): The formula.
        mode (str): ``"S"`` at a node, ``"T"`` at an arc.

    Returns:
        tuple: The rewritten formula.
    """
    tag = f[0]
    if tag in ("NF", "AF", "TT"):
        return f
    if tag in ("EU", "FU") and f[1] == TT and f[2][0] in ("EU", "FU") \
            and f[2][1] == TT:
        both_forall = tag == "FU" and f[2][0] == "FU"
        return rewrite(("FU" if both_forall else "EU", TT, f[2][2]), mode)
    if tag == "NOT":
        inner = rewrite(f[1], mode)
        return inner[1] if inner[0] == "NOT" else ("NOT", inner)
    if tag == "OR":
        a = rewrite(f[1], mode)
        if a == TT:
            return TT
        if a == FF:
            return rewrite(f[2], mode)
        b = rewrite(f[2], mode)
        if b == TT:
            return TT
        if b == FF:
            return a
        return ("OR", a, b)
    if tag in ("EU", "FU"):
        a = rewrite(f[1], mode)
        if a == FF:
            return rewrite(f[2], mode)
        b = rewrite(f[2], mode)
        if b == FF:
            return FF
        return (tag, a, b)
    if tag == "MODAL":
        a = rewrite(f[1], _flip(mode))
        if a == FF:
            return FF
        if a == TT and mode == "T":
            return TT                   # an arc always has a next state
        return ("MODAL", a)
    raise AskCtlError(f"not an ASK-CTL formula: {f!r}")


# ---------------------------------------------------------------------------
# The occurrence graph as CPN Tools' state-space library sees it
# ---------------------------------------------------------------------------

# Class exposing an occurrence graph through CPN Tools' functions.
class _Graph:
    """Arcs numbered, adjacency both ways, SCC graph, ML names.

    CPN Tools numbers nodes and arcs from 1; internally everything here is
    0-based and converted at the ML boundary.

    Attributes:
        ss (StateSpace): The occurrence graph.
        net (ColouredNet): The net.
        src, dst, ti, key (list): Per arc.
        out_arcs, in_arcs (list): Per node, arc ids.
    """

    # Method to index the graph.
    def __init__(self, ss, net):
        """Number the arcs and build the SCC graph.

        Args:
            ss (StateSpace): The occurrence graph.
            net (ColouredNet): The net.
        """
        self.ss, self.net = ss, net
        self.src: List[int] = []
        self.dst: List[int] = []
        self.ti: List[int] = []
        self.key: List[tuple] = []
        self.out_arcs: List[List[int]] = [[] for _ in range(ss.n_nodes)]
        self.in_arcs: List[List[int]] = [[] for _ in range(ss.n_nodes)]
        for s, out in enumerate(ss.succ):
            for ti, key, d in out:
                a = len(self.src)
                self.src.append(s)
                self.dst.append(d)
                self.ti.append(ti)
                self.key.append(key)
                self.out_arcs[s].append(a)
                self.in_arcs[d].append(a)
        self.n_arcs = len(self.src)
        comp = ss.scc
        self.scc_nodes: List[List[int]] = [[] for _ in range(ss.n_sccs)]
        for v, c in enumerate(comp):
            self.scc_nodes[c].append(v)
        self.scc_succ: List[set] = [set() for _ in range(ss.n_sccs)]
        self.scc_arcs: List[List[int]] = [[] for _ in range(ss.n_sccs)]
        for a in range(self.n_arcs):
            cs, cd = comp[self.src[a]], comp[self.dst[a]]
            if cs != cd:
                self.scc_succ[cs].add(cd)
            else:
                self.scc_arcs[cs].append(a)
        self.terminal = set(ss.terminal_sccs)
        self.trivial = [len(self.scc_nodes[c]) == 1 and not self.scc_arcs[c]
                        for c in range(ss.n_sccs)]
        self._pred_nodes: Optional[List[List[int]]] = None

    # Method to give the objects of one sort.
    def universe(self, mode: str) -> range:
        """All nodes or all arcs.

        Args:
            mode (str): ``"S"`` or ``"T"``.

        Returns:
            range: The object ids.
        """
        return range(self.ss.n_nodes if mode == "S" else self.n_arcs)

    # Method to give the SCC an object belongs to, as ASKCTL.sml does.
    def scc_of(self, x: int, mode: str) -> int:
        """A node's SCC; an arc's is its source node's.

        Args:
            x (int): The object.
            mode (str): Its sort.

        Returns:
            int: The SCC index.
        """
        return self.ss.scc[x if mode == "S" else self.src[x]]

    # Method to give the first object of an SCC, as SccToFirstObject does.
    def first(self, c: int, mode: str) -> int:
        """The first node, or the first arc inside, of a component.

        Args:
            c (int): The SCC.
            mode (str): The sort wanted.

        Returns:
            int: The object.

        Raises:
            MLError: For the arcs of a component that has none (``hd []``).
        """
        if mode == "S":
            return self.scc_nodes[c][0]
        if not self.scc_arcs[c]:
            raise MLError("ASK-CTL raised Empty: an arc formula asked of a "
                          "strongly connected component without arcs")
        return self.scc_arcs[c][0]

    # Method to list what ASK-CTL's NextCand gives.
    def next_cand(self, x: int, mode: str) -> List[int]:
        """Successor objects of the same sort.

        Args:
            x (int): The object.
            mode (str): Its sort.

        Returns:
            list: Successor nodes of a node; arcs leaving an arc's target.
        """
        if mode == "S":
            return [self.dst[a] for a in self.out_arcs[x]]
        return self.out_arcs[self.dst[x]]

    # Method to list the predecessors with respect to NextCand.
    def prev_cand(self, y: int, mode: str) -> List[int]:
        """Every ``x`` with ``y`` in ``next_cand(x)``, once per occurrence.

        Args:
            y (int): The object.
            mode (str): Its sort.

        Returns:
            list: The predecessors, repeated as often as ``y`` occurs.
        """
        if mode == "S":
            return [self.src[a] for a in self.in_arcs[y]]
        return self.in_arcs[self.src[y]]

    # Method to tell whether a set of objects of a component has a cycle.
    def cycle(self, c: int, mode: str, keep) -> bool:
        """ASKCTL.sml's ``CycleExists``.

        At nodes: a cycle through nodes of ``c`` that ``keep`` admits. At
        arcs: a cycle through nodes of ``c`` along arcs ``keep`` admits.

        Args:
            c (int): The SCC.
            mode (str): The sort ``keep`` is about.
            keep (callable): ``object -> bool``.

        Returns:
            bool: Whether such a cycle exists.
        """
        inside = set(self.scc_nodes[c])
        if mode == "S":
            nodes = {v for v in inside if keep(v)}
            edges = {v: [self.dst[a] for a in self.out_arcs[v]
                         if self.dst[a] in nodes] for v in nodes}
        else:
            nodes = inside
            edges = {v: [self.dst[a] for a in self.out_arcs[v]
                         if self.dst[a] in nodes and keep(a)] for v in nodes}
        # Strip nodes with no successor left; a cycle is what remains.
        outdeg = {v: len(edges[v]) for v in nodes}
        preds: Dict[int, List[int]] = collections.defaultdict(list)
        for v, ws in edges.items():
            for w in ws:
                preds[w].append(v)
        stack = [v for v, d in outdeg.items() if d == 0]
        removed = 0
        while stack:
            w = stack.pop()
            removed += 1
            for v in preds[w]:
                outdeg[v] -= 1
                if outdeg[v] == 0:
                    stack.append(v)
        return removed < len(nodes)

    # Method to give, per SCC, whether a property holds of a reachable one.
    def reach_any(self, good: Sequence[bool]) -> List[bool]:
        """Whether some SCC reachable from each one (itself included) is good.

        Tarjan's numbering puts every component after the ones it reaches,
        so one pass in index order suffices.

        Args:
            good (sequence): Per SCC.

        Returns:
            list: Per SCC.
        """
        out = [False] * len(good)
        for c in range(len(good)):
            out[c] = good[c] or any(out[d] for d in self.scc_succ[c])
        return out


# Class evaluating ASK-CTL formulas over a graph.
class _Evaluator:
    """Satisfaction sets of rewritten formulas, at nodes or at arcs.

    Attributes:
        g (_Graph): The graph.
    """

    # Method to start an evaluator.
    def __init__(self, graph: _Graph):
        """Create the evaluator.

        Args:
            graph (_Graph): The graph.
        """
        self.g = graph
        self._memo: Dict[Tuple[int, str], Tuple[tuple, FrozenSet[int]]] = {}

    # Method to evaluate a formula as eval_node or eval_arc would.
    def holds(self, f: tuple, mode: str) -> FrozenSet[int]:
        """Rewrite, then compute the satisfaction set.

        Args:
            f (tuple): The formula, as built.
            mode (str): ``"S"`` for ``eval_node``, ``"T"`` for ``eval_arc``.

        Returns:
            frozenset: The objects (0-based) satisfying it.
        """
        return self.sat(rewrite(f, mode), mode)

    # Method to compute one satisfaction set, memoised.
    def sat(self, f: tuple, mode: str) -> FrozenSet[int]:
        """Satisfaction set of a rewritten formula.

        Args:
            f (tuple): The formula.
            mode (str): The sort it is evaluated at.

        Returns:
            frozenset: The objects satisfying it.
        """
        key = (id(f), mode)
        hit = self._memo.get(key)
        if hit is None:
            hit = self._memo[key] = (f, frozenset(self._sat(f, mode)))
        return hit[1]

    # Method to compute one satisfaction set.
    def _sat(self, f: tuple, mode: str):
        """The clauses of ASKCTL.sml's ``eval'``, fast paths first.

        Args:
            f (tuple): The formula.
            mode (str): The sort.

        Returns:
            set: The objects satisfying it.
        """
        g = self.g
        tag = f[0]
        everything = g.universe(mode)
        if tag in ("EU", "FU") and f[1] == TT and f[2][0] == "NOT":
            inner = f[2][1]
            if tag == "EU" and inner[0] == "EU" and inner[1] == TT:
                # POS (INV a): some reachable terminal component satisfies it.
                invariant = self.sat(f[2], mode)
                good = [c in g.terminal and g.first(c, mode) in invariant
                        for c in range(len(g.scc_nodes))]
                reach = g.reach_any(good)
                return {x for x in everything if reach[g.scc_of(x, mode)]}
            if tag == "EU" and inner[0] == "FU" and inner[1] == TT:
                # POS (ALONG (NOT a)): a reachable terminal dead end or cycle
                # avoiding a.
                a = self.sat(inner[2], mode)
                good = []
                for c in range(len(g.scc_nodes)):
                    if g.trivial[c]:
                        good.append(c in g.terminal
                                    and g.first(c, mode) not in a)
                    else:
                        good.append(g.cycle(c, mode, lambda x: x not in a))
                reach = g.reach_any(good)
                return {x for x in everything if reach[g.scc_of(x, mode)]}
            if tag == "FU" and inner[0] == "EU" and inner[1] == TT:
                # EV (INV a): every reachable terminal or cyclic component
                # satisfies it.
                invariant = self.sat(f[2], mode)
                bad = []
                for c in range(len(g.scc_nodes)):
                    if c not in g.terminal and g.trivial[c]:
                        bad.append(False)
                    else:
                        bad.append(g.first(c, mode) not in invariant)
                reach = g.reach_any(bad)
                return {x for x in everything if not reach[g.scc_of(x, mode)]}
        if tag == "TT":
            return set(everything)
        if tag == "NF":
            if mode != "S":
                raise MLError("Error: Node handled as Arc in ASK-CTL")
            return {x for x in everything if _truth(f[2](x + 1), f[1])}
        if tag == "AF":
            if mode != "T":
                raise MLError("Error: Arc handled as Node in ASK-CTL")
            return {x for x in everything if _truth(f[2](x + 1), f[1])}
        if tag == "NOT":
            return set(everything) - self.sat(f[1], mode)
        if tag == "OR":
            return set(self.sat(f[1], mode)) | self.sat(f[2], mode)
        if tag == "MODAL":
            inner = self.sat(f[1], _flip(mode))
            if mode == "S":
                return {x for x in everything
                        if any(a in inner for a in g.out_arcs[x])}
            return {x for x in everything if g.dst[x] in inner}
        if tag == "EU":
            return self._until(f, mode, exists=True)
        if tag == "FU":
            return self._until(f, mode, exists=False)
        raise AskCtlError(f"not an ASK-CTL formula: {f!r}")

    # Method to compute EXIST_UNTIL or FORALL_UNTIL as a least fixpoint.
    def _until(self, f: tuple, mode: str, exists: bool) -> set:
        """``a2 or (a1 and (exists|forall) successor in Z)``, least ``Z``.

        ``forall`` over no successors is true, as in ASKCTL.sml.

        Args:
            f (tuple): ``("EU"|"FU", a1, a2)``.
            mode (str): The sort.
            exists (bool): EXIST_UNTIL when True.

        Returns:
            set: The fixpoint.
        """
        g = self.g
        a1, a2 = self.sat(f[1], mode), self.sat(f[2], mode)
        z = set(a2)
        stack = list(z)
        if not exists:
            left = {x: len(g.next_cand(x, mode)) for x in a1 if x not in z}
            for x, n in list(left.items()):
                if n == 0:
                    z.add(x)
                    stack.append(x)
        while stack:
            y = stack.pop()
            for x in g.prev_cand(y, mode):
                if x in z or x not in a1:
                    continue
                if not exists:
                    left[x] -= 1
                    if left[x]:
                        continue
                z.add(x)
                stack.append(x)
        return z


# Function to read an ML truth value returned by a predicate.
def _truth(value, name: str) -> bool:
    """A predicate's answer, which must be a boolean.

    Args:
        value: What the predicate returned.
        name (str): The predicate's label, for the error.

    Returns:
        bool: The answer.

    Raises:
        MLError: When the predicate returned something else.
    """
    if value is True or value is False:
        return value
    raise MLError(f"the predicate {name!r} returned {value!r}, not a bool")


# ---------------------------------------------------------------------------
# State-space functions
# ---------------------------------------------------------------------------

# Function to give the ML spelling of a place or transition.
def _ml_of(element) -> str:
    """``Page'Name`` as CPN Tools spells it in ``Mark.`` and ``Bind.``.

    Args:
        element (dict): A place or transition of the flattened net.

    Returns:
        str: The path.
    """
    from .askctl import _ml_of as ml_of
    return ml_of(element)


# Function to build the symbols a query file's patterns may name.
def _symbols(net) -> Dict[str, Any]:
    """``TI.<page>'<t>`` and ``Bind.<page>'<t>`` as constructors.

    Args:
        net (ColouredNet): The net.

    Returns:
        dict: ``name -> DataConstructor``.
    """
    out: Dict[str, Any] = {}
    for t in net.transitions:
        ml = _ml_of(t)
        out[f"TI.{ml}"] = DataConstructor(f"TI.{ml}")
        out[f"Bind.{ml}"] = DataConstructor(f"Bind.{ml}")
    return out


# Function to bind CPN Tools' state-space functions to a graph.
def _library(graph: _Graph, evaluator: _Evaluator) -> Dict[str, Any]:
    """Every name a query file may use, besides the net's declarations.

    Args:
        graph (_Graph): The graph.
        evaluator (_Evaluator): Evaluates ``eval_node``/``eval_arc``.

    Returns:
        dict: ``name -> ML value``.
    """
    g, ss, net = graph, graph.ss, graph.net
    n_nodes = ss.n_nodes

    def node(n) -> int:
        if not isinstance(n, int) or not 1 <= n <= n_nodes:
            raise MLError(f"no node {n!r} in the occurrence graph")
        return n - 1

    def arc(a) -> int:
        if not isinstance(a, int) or not 1 <= a <= g.n_arcs:
            raise MLError(f"no arc {a!r} in the occurrence graph")
        return a - 1

    def scc(s) -> int:
        if not isinstance(s, int) or not 1 <= s <= ss.n_sccs:
            raise MLError(f"no strongly connected component {s!r}")
        return s - 1

    def ti_value(t: int):
        tr = net.transitions[t]
        return DataConstructor(f"TI.{_ml_of(tr)}")(tr.get("instance", 1))

    def be_value(a: int):
        tr = net.transitions[g.ti[a]]
        binding = dict(g.key[a])
        names = tuple(sorted(binding))
        record = RecordValue(names, tuple(binding[n] for n in names))
        return DataConstructor(f"Bind.{_ml_of(tr)}")((tr.get("instance", 1),
                                                     record))

    def path(pair) -> Optional[List[int]]:
        start, goal = node(pair[0]), node(pair[1])
        back = {start: None}
        queue = collections.deque([start])
        while queue:
            v = queue.popleft()
            if v == goal:
                arcs = []
                while back[v] is not None:
                    a = back[v]
                    arcs.append(a)
                    v = g.src[a]
                return arcs[::-1]
            for a in g.out_arcs[v]:
                if g.dst[a] not in back:
                    back[g.dst[a]] = a
                    queue.append(g.dst[a])
        return None

    def arcs_in_path(pair):
        arcs = path(pair)
        return tuple(a + 1 for a in arcs) if arcs is not None else ()

    def nodes_in_path(pair):
        arcs = path(pair)
        if arcs is None:
            return ()
        return (pair[0],) + tuple(g.dst[a] + 1 for a in arcs)

    def dead_tis(_unit):
        fired = set(g.ti)
        return tuple(ti_value(t) for t in range(len(net.transitions))
                     if t not in fired)

    def live_tis(_unit):
        live = None
        for c in g.terminal:
            here = {g.ti[a] for a in g.scc_arcs[c]}
            live = here if live is None else live & here
        return tuple(ti_value(t) for t in sorted(live or ()))

    def area(value, total: int, convert) -> List[int]:
        if value == "EntireGraph":
            return list(range(total))
        return [convert(x) for x in value]

    def limit_of(value) -> Optional[int]:
        return None if value == "NoLimit" else value

    def search(objects, pred, limit, evaluate, start, combine):
        acc, found = start, 0
        for x in objects:
            if limit is not None and found >= limit:
                break
            if _truth(pred(x + 1), "search predicate"):
                found += 1
                acc = combine((evaluate(x + 1), acc))
        return acc

    def pred_list(objects, pred, limit):
        out = []
        for x in objects:
            if limit is not None and len(out) >= limit:
                break
            if _truth(pred(x + 1), "search predicate"):
                out.append(x + 1)
        return tuple(out)

    def eval_with(mode):
        def outer(formula):
            sat = evaluator.holds(formula, mode)
            convert = node if mode == "S" else arc
            return lambda x: convert(x) in sat
        return outer

    lib: Dict[str, Any] = {
        "InitNode": 1,
        "EntireGraph": "EntireGraph",
        "NoLimit": "NoLimit",
        "NoOfNodes": lambda _u: n_nodes,
        "NoOfArcs": lambda _u: g.n_arcs,
        "OutArcs": lambda n: tuple(a + 1 for a in g.out_arcs[node(n)]),
        "InArcs": lambda n: tuple(a + 1 for a in g.in_arcs[node(n)]),
        "OutNodes": lambda n: tuple(g.dst[a] + 1 for a in g.out_arcs[node(n)]),
        "InNodes": lambda n: tuple(g.src[a] + 1 for a in g.in_arcs[node(n)]),
        "SourceNode": lambda a: g.src[arc(a)] + 1,
        "DestNode": lambda a: g.dst[arc(a)] + 1,
        "ArcToTI": lambda a: ti_value(g.ti[arc(a)]),
        "ArcToBE": lambda a: be_value(arc(a)),
        "Reachable": lambda pair: path(pair) is not None,
        "ArcsInPath": arcs_in_path,
        "NodesInPath": nodes_in_path,
        "ListDeadMarkings": lambda _u: tuple(v + 1 for v in ss.dead),
        "ListHomeMarkings": lambda _u: tuple(v + 1 for v in ss.home),
        "ListDeadTIs": dead_tis,
        "ListLiveTIs": live_tis,
        "PredAllNodes": lambda p: pred_list(range(n_nodes), p, None),
        "PredAllArcs": lambda p: pred_list(range(g.n_arcs), p, None),
        "PredNodes": lambda t: pred_list(area(t[0], n_nodes, node), t[1],
                                         limit_of(t[2])),
        "PredArcs": lambda t: pred_list(area(t[0], g.n_arcs, arc), t[1],
                                        limit_of(t[2])),
        "SearchAllNodes": lambda t: search(range(n_nodes), t[0], None, *t[1:]),
        "SearchAllArcs": lambda t: search(range(g.n_arcs), t[0], None, *t[1:]),
        "SearchNodes": lambda t: search(area(t[0], n_nodes, node), t[1],
                                        limit_of(t[2]), *t[3:]),
        "SearchArcs": lambda t: search(area(t[0], g.n_arcs, arc), t[1],
                                       limit_of(t[2]), *t[3:]),
        "NodeToScc": lambda n: ss.scc[node(n)] + 1,
        "SccToNodes": lambda s: tuple(v + 1 for v in g.scc_nodes[scc(s)]),
        "SccTerminal": lambda s: scc(s) in g.terminal,
        "SccTrivial": lambda s: g.trivial[scc(s)],
        "SccNoOfNodes": lambda _u: ss.n_sccs,
        "SccNoOfArcs": lambda _u: ss.n_scc_arcs,
        "eval_node": eval_with("S"),
        "eval_arc": eval_with("T"),
    }
    lib.update(_operators())
    lib.update(_symbols(net))
    for pidx, p in enumerate(net.places):
        name = f"Mark.{_ml_of(p)}"
        instance = p.get("instance", 1)
        entry = lib.setdefault(name, {})
        if isinstance(entry, dict):
            entry[instance] = pidx
    for name, by_instance in list(lib.items()):
        if name.startswith("Mark.") and isinstance(by_instance, dict):
            lib[name] = _marking_function(name, by_instance, graph, node)
    return lib


# Function to build one Mark.<page>'<place> function.
def _marking_function(name: str, by_instance: Dict[int, int], graph: _Graph,
                      node):
    """``Mark.P'p inst n``: the colours on a place instance at a node.

    Args:
        name (str): The ML name, for errors.
        by_instance (dict): ``instance -> place index``.
        graph (_Graph): The graph.
        node (callable): Converts an ML node number.

    Returns:
        callable: The curried function.
    """
    def at_instance(instance):
        pidx = by_instance.get(instance)
        if pidx is None:
            raise MLError(f"{name} has no instance {instance!r}")

        def at_node(n):
            v = node(n)
            values = graph.net.values_of(pidx, graph.ss.markings[v][pidx])
            return MultiSet(collections.Counter(values))
        return at_node
    return at_instance


# ---------------------------------------------------------------------------
# Query files
# ---------------------------------------------------------------------------

# Class holding one query of a file, as a CPNCheck formula.
class AskCtlQuery(Formula):
    """``eval_node F InitNode`` from a query file.

    Evaluating it runs the whole file (once per graph) and gives the nodes
    where ``F`` holds; the property holds when the initial marking is one.

    Attributes:
        script (AskCtlScript): The file.
        index (int): Which query of the file.
        text (str): ``F`` as written.
    """

    #: Not decided on reduced graphs: an ASK-CTL predicate sees everything.
    opaque = True

    # Method to hold one query.
    def __init__(self, script: "AskCtlScript", index: int, text: str):
        """Create the query.

        Args:
            script (AskCtlScript): The file.
            index (int): Position among the file's queries.
            text (str): The formula's source text.
        """
        self.script = script
        self.index = index
        self.text = text

    # Method to compute the satisfaction set.
    def eval(self, ctx: Context) -> FrozenSet[int]:
        """Nodes where the query's formula holds.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            frozenset: The nodes.
        """
        return self.script.run(ctx)[self.index]

    # Method to describe the failure.
    def at_fail(self, ctx: Context, node: int) -> str:
        """Why the initial marking violates the query.

        Args:
            ctx (Context): The evaluation context.
            node (int): The node.

        Returns:
            str: The reason.
        """
        return f"eval_node {self.text} {'InitNode' if node == 0 else node + 1} is false"

    # Method to render the query.
    def __str__(self):
        """Return the formula text.

        Returns:
            str: The text.
        """
        return self.text


# Class holding a parsed query file.
class AskCtlScript:
    """The statements of one ASK-CTL file, run against occurrence graphs.

    Attributes:
        statements (list): ``(kind, data, source)`` in order.
        queries (list): ``(id, formula text, statement index)``.
        declarations (str): The source of every statement that is not a
            query, for CPN Tools.
    """

    # Method to parse a file against a net.
    def __init__(self, text: str, net, first: int = 1):
        """Parse every statement.

        Args:
            text (str): The SML.
            net (ColouredNet): The net its names refer to.
            first (int): Number of the first bare query (``Q<first>``).

        Raises:
            AskCtlError: On text that does not parse or an unsupported form.
        """
        self.net = net
        self.text = text
        symbols = dict(net.declarations.symbols)
        symbols.update(_symbols(net))
        tokens = tokenize(text)
        parser = Parser(tokens, text, symbols)
        self.statements: List[Tuple[str, Any, str]] = []
        self.queries: List[Tuple[str, str, int]] = []
        number = first
        while parser.peek()[0] != "end":
            start = parser.pos
            try:
                kind, data = self._statement(parser)
            except MLError as exc:
                line = text.count("\n", 0, tokens[start][2]) + 1
                raise AskCtlError(f"line {line}: {exc}") from None
            end = parser.pos
            parser.accept("op", ";")
            source = text[tokens[start][2]:tokens[end][2]
                          if tokens[end][0] != "end" else len(text)].strip()
            if kind == "skip":
                continue
            if kind == "query":
                name, (first_tok, end_tok), _trees = data
                if name is None:
                    name, number = f"Q{number}", number + 1
                f_text = text[tokens[first_tok][2]:tokens[end_tok][2]].strip()
                self.queries.append((name, f_text, len(self.statements)))
            self.statements.append((kind, data, source))
        if not self.queries:
            raise AskCtlError("the file asks nothing: no top-level "
                              "eval_node F InitNode")
        self.declarations = "\n".join(src.rstrip(";") + ";"
                                      for kind, _d, src in self.statements
                                      if kind != "query")
        self._runs: Dict[int, Tuple[Any, List[FrozenSet[int]]]] = {}

    # Method to read one top-level statement.
    @staticmethod
    def _statement(parser: Parser) -> Tuple[str, Any]:
        """Parse a declaration, a query or an expression.

        Args:
            parser (Parser): Positioned at the statement.

        Returns:
            tuple: ``(kind, data)``.

        Raises:
            MLError: On text that does not parse or is not supported.
        """
        tok = parser.peek()
        if parser.accept("kw", "val"):
            pattern = parser.pattern()
            parser.expect("op", "=")
            query = _query(parser)
            if query is not None:
                name = pattern[1] if pattern[0] == "pvar" else None
                return "query", (name,) + query
            return "val", (pattern, parser.expression())
        if parser.accept("kw", "fun"):
            return "fun", parser.fun_clause()
        if tok[0] == "kw" and tok[1] in ("datatype", "exception"):
            return "constructors", _constructors_declaration(parser)[1]
        if tok[0] == "id" and tok[1] in ("use", "open"):
            while parser.peek()[0] != "end" and \
                    parser.peek()[:2] != ("op", ";"):
                parser.next()
            return "skip", None
        if tok[0] in ("kw", "id") and tok[1] in ("local", "structure",
                                                 "signature", "functor"):
            raise MLError(f"'{tok[1]}' is not supported in a query file")
        query = _query(parser)
        if query is not None:
            return "query", (None,) + query
        return "expr", parser.expression()

    # Method to give the queries as CPNCheck formulas.
    def formulas(self) -> List[Tuple[str, AskCtlQuery]]:
        """One formula per query.

        Returns:
            list: ``(id, AskCtlQuery)``.
        """
        return [(name, AskCtlQuery(self, i, text))
                for i, (name, text, _s) in enumerate(self.queries)]

    # Method to run the file against one graph.
    def run(self, ctx: Context) -> List[FrozenSet[int]]:
        """Evaluate every statement; satisfaction set of every query.

        Args:
            ctx (Context): The context, whose graph must be complete and not
                reduced.

        Returns:
            list: Per query, the nodes (0-based) where its formula holds.

        Raises:
            MLError: When the graph is reduced or a statement fails.
        """
        ss = ctx.ss
        hit = self._runs.get(id(ss))
        if hit is not None and hit[0] is ss:
            return hit[1]
        if getattr(ss, "reduction", None):
            raise MLError("ASK-CTL queries need the full occurrence graph")
        graph = _Graph(ss, self.net)
        evaluator = _Evaluator(graph)
        decl = self.net.declarations
        env: Dict[str, Any] = dict(decl.globals)
        env.update(_library(graph, evaluator))
        fields = decl.fields
        results: List[FrozenSet[int]] = []
        for kind, data, source in self.statements:
            try:
                if kind == "val":
                    value = compile_expression(data[1], env, fields)({})
                    bound = match_pattern(data[0], value, {}, fields)
                    if bound is None:
                        raise MLError("the pattern does not match its value")
                    env.update(bound)
                elif kind == "fun":
                    name, tree = data
                    value = compile_expression(tree, env, fields)({})
                    if hasattr(value, "name"):
                        value.name = name
                    env[name] = value
                elif kind == "constructors":
                    for name, has_arg in data:
                        env[name] = (DataConstructor(name) if has_arg
                                     else _enum(name))
                elif kind == "expr":
                    compile_expression(data, env, fields)({})
                else:
                    name, _span, (formula_tree, node_tree) = data
                    formula = compile_expression(formula_tree, env, fields)({})
                    at = compile_expression(node_tree, env, fields)({})
                    if at != 1:
                        raise MLError(f"asked at node {at!r}: properties are "
                                      "decided at the initial marking "
                                      "(InitNode)")
                    sat = evaluator.holds(formula, "S")
                    results.append(sat)
                    if name is not None:
                        env[name] = 0 in sat
            except MLError as exc:
                raise MLError(f"{source[:60]}: {exc}") from None
        self._runs[id(ss)] = (ss, results)
        return results


# Function to make an enumeration constant.
def _enum(name: str):
    """A constructor without argument.

    Args:
        name (str): Its name.

    Returns:
        EnumValue: The constant.
    """
    from .cpnml import EnumValue
    return EnumValue(name)


# Function to recognise a top-level eval_node F N.
def _query(parser: Parser) -> Optional[Tuple[Tuple[int, int], Tuple[Any, Any]]]:
    """Read ``eval_node F N`` when the statement is exactly that.

    Args:
        parser (Parser): Positioned at the expression.

    Returns:
        tuple|None: ``((first, end) token span of F, (F tree, N tree))``;
        None, with the parser left where it was, for anything else.
    """
    save = parser.pos
    if parser.peek()[:2] != ("id", "eval_node"):
        return None
    parser.next()
    first = parser.pos
    formula = parser.atom()
    end = parser.pos
    at = parser.atom()
    if parser.peek()[0] == "end" or parser.peek()[:2] == ("op", ";"):
        return (first, end), (formula, at)
    parser.pos = save
    return None


# Function to parse a query file against a net.
def parse_askctl(text: str, net, first: int = 1) -> AskCtlScript:
    """Read an ASK-CTL file.

    Args:
        text (str): The SML.
        net (ColouredNet): The flattened net.
        first (int): Number of the first bare query.

    Returns:
        AskCtlScript: The parsed file.
    """
    return AskCtlScript(text, net, first)


# Function to read a query file from disk.
def load_askctl(path: str, net, first: int = 1) -> AskCtlScript:
    """Read an ASK-CTL file from disk.

    Args:
        path (str): The ``.sml`` file.
        net (ColouredNet): The flattened net.
        first (int): Number of the first bare query.

    Returns:
        AskCtlScript: The parsed file.
    """
    with open(path, encoding="utf-8") as handle:
        return AskCtlScript(handle.read(), net, first)
