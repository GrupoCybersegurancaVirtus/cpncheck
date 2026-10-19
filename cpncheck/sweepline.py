"""The generalised sweep-line method.

The sweep-line method (Christensen, Kristensen and Mailund, 2001) explores the
markings in the order of a *progress measure* and deletes those it has left
behind: a marking whose progress is below that of every marking still to be
explored can only be reached again through a *regress* arc, one leading to
less progress. The generalised method (Kristensen and Mailund, 2002) keeps the
targets of regress arcs as *persistent* markings and starts a new sweep from
them, so it terminates on every finite occurrence graph, with any measure.

**What it preserves.** Every reachable marking is explored, so a property of
single markings is decided exactly: ``AG psi``, ``EF chi`` and ``not EF chi``
for propositional ``psi``/``chi``, which may mention ``dead`` and
``enabled`` (the successors of a marking are known when it is explored).
Dead markings are found. Properties of paths (``AF``, ``EG``, ``AG EF``, home
markings) are not: the arcs are not kept. Neither are counterexample paths --
the marking that violates a property is reported, not how to get there.

**Any measure is sound.** A measure that is not monotone only makes regress
arcs, and so more sweeps and markings explored more than once; the verdicts
do not depend on it. A timed net has a natural one: its clock never goes
back, so there are no regress arcs at all.
"""

import heapq
import itertools
import re
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .coloured import ColouredNet
from .formula import AG, EF, Context, Formula, Not
from .reduction import Dependency, _Atoms, propositional, split
from .statespace import DEFAULT_MAX_NODES

__all__ = ["ProgressMeasure", "parse_progress", "SweepResult", "sweep",
           "SweepChecker", "ProgressError"]


# Class signalling an unusable progress measure.
class ProgressError(ValueError):
    """A progress measure that cannot be read or evaluated."""


# Class holding a progress measure.
class ProgressMeasure:
    """A function from markings to numbers that the sweep follows.

    Attributes:
        text (str): How the measure was given, for reports.
        fn (callable): ``fn(marking) -> number``.
    """

    # Method to wrap a measure.
    def __init__(self, fn: Callable[[tuple], Any], text: str):
        """Create the measure.

        Args:
            fn (callable): The function.
            text (str): Its description.
        """
        self.fn = fn
        self.text = text

    # Method to evaluate the measure.
    def __call__(self, marking: tuple):
        """The progress of a marking.

        Args:
            marking (tuple): The marking.

        Returns:
            The progress value (anything ordered).
        """
        return self.fn(marking)

    # Method to render the measure.
    def __repr__(self):
        """Return the description.

        Returns:
            str: The text.
        """
        return f"ProgressMeasure({self.text!r})"


_TERM = re.compile(r"\s*([+-]?)\s*(?:(\d+)\s*\*\s*)?"
                   r"(clock|(tokens|sum)\(\s*(?:\"([^\"]+)\"|([^()]+?))\s*\)|\d+)\s*")


# Function to read a progress measure from text.
def parse_progress(spec, net: ColouredNet) -> ProgressMeasure:
    """A progress measure from text, a callable, or the net's clock.

    The text is a sum of terms ``[k *] tokens(P)`` (how many tokens),
    ``[k *] sum(P)`` (the sum of their integer values), ``[k *] clock`` and
    integer constants, each with a sign: ``tokens(Received) -
    tokens(Sent)``, ``clock``, ``2*tokens("Done 1") + sum(Counter)``. A name
    is resolved as in property files.

    Args:
        spec (str|callable|ProgressMeasure|None): The measure. A callable gets
            the marking. None means the clock of a timed net.
        net (ColouredNet): The net.

    Returns:
        ProgressMeasure: The measure.

    Raises:
        ProgressError: When the text cannot be read, names an unknown place,
            or None is given for an untimed net.
    """
    from .query import QueryError, resolve

    if isinstance(spec, ProgressMeasure):
        return spec
    if spec is None:
        if not net.timed:
            raise ProgressError(
                "the sweep-line method needs a progress measure (for example "
                "--progress \"tokens(Done) - tokens(Todo)\"); only a timed net "
                "has one of its own, its clock")
        spec = "clock"
    if callable(spec):
        return ProgressMeasure(spec, getattr(spec, "__name__", "callable"))
    text = str(spec)
    terms: List[Tuple[int, str, Tuple[int, ...]]] = []
    pos = 0
    while pos < len(text):
        m = _TERM.match(text, pos)
        if m is None or m.end() == pos:
            raise ProgressError(f"cannot read progress measure {text!r} at "
                                f"position {pos}")
        if terms and not m.group(1):
            raise ProgressError(f"expected + or - at position {pos} in {text!r}")
        sign = -1 if m.group(1) == "-" else 1
        factor = sign * int(m.group(2) or 1)
        body = m.group(3)
        if body == "clock":
            if not net.timed:
                raise ProgressError("clock in a progress measure of an untimed "
                                    "net")
            terms.append((factor, "clock", ()))
        elif body.isdigit():
            terms.append((factor * int(body), "const", ()))
        else:
            name = m.group(5) or m.group(6)
            try:
                places = resolve(net, "place", name).indices
            except QueryError as exc:
                raise ProgressError(str(exc)) from exc
            terms.append((factor, m.group(4), places))
        pos = m.end()
    if not terms:
        raise ProgressError("empty progress measure")

    def measure(marking: tuple) -> int:
        total = 0
        for factor, kind, places in terms:
            if kind == "clock":
                total += factor * marking[-1]
            elif kind == "const":
                total += factor
            elif kind == "tokens":
                total += factor * sum(len(marking[p]) for p in places)
            else:
                for p in places:
                    for value in net.values_of(p, marking[p]):
                        if isinstance(value, bool) or not isinstance(value, int):
                            raise ProgressError(f"sum({net.places[p]['name']}) "
                                                f"met the token {value!r}, "
                                                "which is not an integer")
                        total += factor * value
        return total

    return ProgressMeasure(measure, " ".join(text.split()))


# Class holding the outcome of one sweep-line exploration.
class SweepResult:
    """What a sweep-line exploration found.

    Attributes:
        complete (bool): Whether every reachable marking was explored.
        explored (int): Markings explored, counting re-explorations.
        distinct_bound (int): Distinct markings stored at once, at most.
        sweeps (int): Number of sweeps (1 + those started by regress arcs).
        regress (int): Regress arcs met.
        persistent (int): Markings kept for good.
        dead (list): Dead markings found (distinct).
        found (dict): For each predicate index, the first marking where it
            holds.
        elapsed (float): Seconds.
    """

    # Method to gather the outcome.
    def __init__(self, **kw):
        """Create the result.

        Args:
            **kw: The attributes.
        """
        self.__dict__.update(kw)


# Function to explore a net with the generalised sweep-line method.
def sweep(net: ColouredNet, progress: ProgressMeasure,
          predicates: Sequence[Callable[[tuple, Dict[int, int]], bool]] = (),
          initial: Optional[tuple] = None, max_stored: int = DEFAULT_MAX_NODES,
          max_explored: Optional[int] = None, stop_when_all_found: bool = False,
          max_dead: int = 10_000, successors=None,
          canonical=None) -> SweepResult:
    """Explore every reachable marking, keeping only a moving window of them.

    Args:
        net (ColouredNet): The net.
        progress (ProgressMeasure): The measure.
        predicates (sequence): ``p(marking, enabled_counts) -> bool``; for
            each, the first marking where it holds is recorded.
        initial (tuple, optional): Start marking.
        max_stored (int): Markings that may be stored at once.
        max_explored (int, optional): Markings that may be explored in all
            (default ``50 * max_stored``); an infinite graph needs it.
        stop_when_all_found (bool): Stop as soon as every predicate held
            somewhere (the verdicts are then known).
        max_dead (int): Dead markings remembered.
        successors (callable, optional): ``successors(marking, enabled) ->
            binding elements to fire``; a stubborn choice
            (:func:`cpncheck.reduction.stubborn_choice`) explores the reduced
            graph. Every enabled one by default.
        canonical (callable, optional): A canonical form: each marking
            reached is replaced by its class representative
            (:mod:`cpncheck.equivalence`).

    Returns:
        SweepResult: The outcome.
    """
    t0 = time.perf_counter()
    if max_explored is None:
        max_explored = 50 * max_stored
    start = net.initial if initial is None else initial
    if canonical is not None:
        start = canonical(start)
    persistent = {start}
    unexplored = [start]
    found: Dict[int, tuple] = {}
    dead: Dict[tuple, None] = {}
    explored = sweeps = regress = 0
    peak = 1
    complete = True
    counter = itertools.count()
    while unexplored and complete:
        sweeps += 1
        layers: Dict[Any, set] = {}
        heap: List[Tuple[Any, int, tuple]] = []
        for root in unexplored:
            p = progress(root)
            layers.setdefault(p, set()).add(root)
            heapq.heappush(heap, (p, next(counter), root))
        unexplored = []
        # Markings stored besides the persistent ones (the roots are).
        stored = 0
        while heap:
            p, _, m = heapq.heappop(heap)
            # Forget what is behind the sweep line (persistent ones stay).
            for q in [q for q in layers if q < p]:
                stored -= sum(1 for x in layers.pop(q) if x not in persistent)
            if explored >= max_explored:
                complete = False
                break
            explored += 1
            enabled = net.enabled(m)
            counts: Dict[int, int] = {}
            for ti, _k, _e in enabled:
                counts[ti] = counts.get(ti, 0) + 1
            if not enabled and len(dead) < max_dead:
                dead[m] = None
            for i, pred in enumerate(predicates):
                if i not in found and pred(m, counts):
                    found[i] = m
            if stop_when_all_found and len(found) == len(predicates):
                complete = False
                heap = []
                break
            fire = enabled if successors is None else successors(m, enabled)
            for ti, _k, env in fire:
                nxt = net.fire(m, ti, env)
                if canonical is not None:
                    nxt = canonical(nxt)
                if nxt in persistent:
                    continue
                q = progress(nxt)
                if q < p:
                    regress += 1
                    persistent.add(nxt)
                    unexplored.append(nxt)
                    continue
                layer = layers.setdefault(q, set())
                if nxt in layer:
                    continue
                if stored + len(persistent) >= max_stored:
                    complete = False
                    heap = []
                    break
                layer.add(nxt)
                stored += 1
                heapq.heappush(heap, (q, next(counter), nxt))
            peak = max(peak, stored + len(persistent))
        if heap:
            complete = False
    if unexplored:
        complete = False
    return SweepResult(complete=complete, explored=explored,
                       distinct_bound=peak, sweeps=sweeps, regress=regress,
                       persistent=len(persistent), dead=list(dead),
                       found=found, elapsed=time.perf_counter() - t0)


# Function to describe a marking briefly.
def describe_marking(net: ColouredNet, marking: tuple, limit: int = 12) -> str:
    """The marked places of a marking, as text.

    Args:
        net (ColouredNet): The net.
        marking (tuple): The marking.
        limit (int): Places shown at most.

    Returns:
        str: ``Place: tokens; ...`` (and the clock of a timed net).
    """
    parts = []
    for i, p in enumerate(net.places):
        if marking[i]:
            parts.append(f"{p['name']}: {', '.join(map(str, marking[i]))}")
    shown = "; ".join(parts[:limit]) + (" ..." if len(parts) > limit else "")
    if net.timed:
        shown += f" (clock {marking[-1]})"
    return shown or "(empty)"


# Class deciding properties with the sweep-line method.
class SweepChecker:
    """Decides the formulas the sweep-line method preserves, in one sweep.

    Attributes:
        net (ColouredNet): The net.
        progress (ProgressMeasure): The measure.
        result (SweepResult): The exploration, once :meth:`run` is called.
    """

    # Method to set up the checker.
    def __init__(self, net: ColouredNet, progress: ProgressMeasure, groups=None,
                 initial: Optional[tuple] = None, max_nodes: int = DEFAULT_MAX_NODES):
        """Create the checker.

        Args:
            net (ColouredNet): The net.
            progress (ProgressMeasure): The measure.
            groups (dict, optional): Resolved groups.
            initial (tuple, optional): Start marking.
            max_nodes (int): Markings stored at once.
        """
        self.net = net
        self.progress = progress
        self.groups = groups or {}
        self.initial = initial
        self.max_nodes = max_nodes
        self.static = Context.static(net, self.groups)
        self.atoms = _Atoms(self.static, Dependency(net))
        self.result: Optional[SweepResult] = None

    # Method to name the state predicate a part reduces to.
    def plan(self, part: Formula) -> Optional[Tuple[str, Formula]]:
        """How the sweep decides a part, if it can.

        Args:
            part (Formula): One part of a property.

        Returns:
            tuple|None: ``("invariant", psi)`` (holds iff no marking violates
            ``psi``), ``("reachable", chi)`` (holds iff some marking satisfies
            ``chi``) or ``("unreachable", chi)``; None when the method does
            not preserve the part.
        """
        if isinstance(part, AG) and propositional(part.operand):
            return "invariant", part.operand
        if isinstance(part, EF) and propositional(part.operand):
            return "reachable", part.operand
        if isinstance(part, Not) and isinstance(part.operand, EF) \
                and propositional(part.operand.operand):
            return "unreachable", part.operand.operand
        if propositional(part):
            return "initial", part
        return None

    # Method to decide several formulas with one exploration.
    def decide_all(self, formulas: Dict[str, Formula]
                   ) -> Dict[str, Tuple[Optional[bool], Optional[tuple], str]]:
        """Verdicts of the formulas at the initial marking.

        Args:
            formulas (dict): ``{id: formula}``.

        Returns:
            dict: ``{id: (holds or None, witness marking or None, how)}``.
        """
        plans: Dict[str, List[Tuple[Optional[str], Optional[Tuple[str, Formula]]]]] = {}
        predicates: List[Callable] = []
        index: Dict[int, int] = {}
        for pid, formula in formulas.items():
            entries = []
            for label, part in split(formula, self.static):
                how = self.plan(part)
                entries.append((label, how))
                if how is None or how[0] == "initial":
                    continue
                target = how[1] if how[0] != "invariant" else Not(how[1])
                if id(target) not in index:
                    index[id(target)] = len(predicates)
                    predicates.append(
                        lambda m, c, f=target: self.atoms.holds(f, m, c))
                entries[-1] = (label, (how[0], how[1], index[id(target)]))
            plans[pid] = entries
        self.result = sweep(self.net, self.progress, predicates,
                            initial=self.initial, max_stored=self.max_nodes)
        res = self.result
        start = self.net.initial if self.initial is None else self.initial
        out = {}
        for pid, entries in plans.items():
            verdict: Optional[bool] = True
            witness = None
            how_text = []
            for label, how in entries:
                head = f"{label}: " if label else ""
                if how is None:
                    verdict = None if verdict is not False else False
                    how_text.append(f"{head}not preserved by the sweep-line "
                                    "method (it keeps no paths)")
                    continue
                if how[0] == "initial":
                    counts: Dict[int, int] = {}
                    for ti, _k, _e in self.net.enabled(start):
                        counts[ti] = counts.get(ti, 0) + 1
                    if not self.atoms.holds(how[1], start, counts):
                        verdict, witness = False, start
                    continue
                kind, _f, i = how
                hit = res.found.get(i)
                if kind in ("invariant", "unreachable"):
                    if hit is not None:
                        verdict, witness = False, hit
                        how_text.append(f"{head}violated at a marking found by "
                                        "the sweep")
                    elif not res.complete and verdict is not False:
                        verdict = None
                        how_text.append(f"{head}sweep stopped early")
                else:
                    if hit is None:
                        if res.complete:
                            verdict = False
                            how_text.append(f"{head}no reachable marking "
                                            "satisfies it")
                        elif verdict is not False:
                            verdict = None
                            how_text.append(f"{head}sweep stopped early")
            out[pid] = (verdict, witness, "; ".join(how_text))
        return out

    # Method to report the exploration.
    def stats(self) -> Dict[str, Any]:
        """Figures of the sweep.

        Returns:
            dict: Counts for the report.
        """
        r = self.result
        if r is None:
            return {}
        return {"reduction": "sweep", "progress": self.progress.text,
                "explored": r.explored, "peak_stored": r.distinct_bound,
                "sweeps": r.sweeps, "regress": r.regress,
                "persistent": r.persistent, "dead": len(r.dead),
                "complete": r.complete, "generation_s": r.elapsed}
