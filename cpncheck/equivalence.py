"""Equivalence reduction: the occurrence graph of classes of markings.

An *equivalence* relates markings that behave alike. Exploring one
representative per class gives the *quotient* graph, which can be much
smaller -- or finite where the occurrence graph is not. It is sound when the
equivalence is *consistent* (Jensen & Kristensen, ch. 8): equivalent markings
have equivalent successors, and the properties asked do not tell equivalent
markings apart. Then the quotient and the occurrence graph are bisimilar for
those properties, and every CTL verdict carries over.

Here an equivalence is a *canonical form*: a function giving one
representative of each class. Two are built in:

* **time equivalence** (:func:`time_equivalence`), for timed nets: a marking
  is moved to clock 0, each timestamp becoming its delay from the clock (0 for
  a token already ready). Markings that differ only by when they happen
  behave alike, as long as no inscription reads the clock with ``time()``;
  a net whose state space is infinite only because time goes on gets a
  finite quotient. It is exact for every property CPNCheck can state, since
  none observes timestamps.
* **symmetry** (:mod:`cpncheck.symmetry`): permutations of colour values.

A user canonical form is accepted too. Consistency is then *tested, not
proved*: :func:`build_quotient` compares, on sampled markings, the classes of
the successors of a marking with those of its representative, and the result
reports the test; the verdicts are conditional on it.

Not preserved: the home-marking property (a class can be a home class while
none of its markings is a home marking), and the graph statistics, which
describe the quotient.
"""

import collections
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .coloured import ColouredNet
from .cpnml import TimedToken
from .formula import Context, Formula
from .statespace import StateSpace

__all__ = ["Equivalence", "time_equivalence", "build_quotient",
           "ConsistencyReport", "EquivalenceError", "user_equivalence"]


# Class signalling an equivalence that cannot be used.
class EquivalenceError(ValueError):
    """An equivalence that does not apply to the net, or is not admitted."""


# Class describing an equivalence on markings.
class Equivalence:
    """A canonical form, with what it preserves.

    Attributes:
        name (str): For reports.
        canonical (callable): ``canonical(marking) -> marking``, the class
            representative.
        exact (bool): Whether consistency is established (built-in forms)
            rather than only tested.
        note (str): Why it is exact, or what the verdicts are conditional on.
        observes (callable): ``observes(formula) -> reason or None``: why the
            formula could tell equivalent markings apart, if it can.
        checks (list): Extra consistency checks, ``check(net, marking) ->
            message or None`` (symmetry tests each generator on the marking).
            They run on every representative explored.
    """

    # Method to describe an equivalence.
    def __init__(self, name: str, canonical: Callable[[tuple], tuple],
                 exact: bool = False, note: str = "",
                 observes: Optional[Callable[[Formula], Optional[str]]] = None,
                 checks: Optional[List[Callable]] = None):
        """Create the equivalence.

        Args:
            name (str): For reports.
            canonical (callable): The canonical form.
            exact (bool): Consistency established.
            note (str): Explanation.
            observes (callable, optional): Formula check; None means no
                formula can tell equivalent markings apart.
            checks (list, optional): Extra consistency checks.
        """
        self.name = name
        self.canonical = canonical
        self.exact = exact
        self.note = note
        self.observes = observes or (lambda _f: None)
        self.checks = list(checks or [])

    # Method to render the equivalence.
    def __repr__(self):
        """Return a short representation.

        Returns:
            str: ``Equivalence(name)``.
        """
        return f"Equivalence({self.name!r})"


_READS_TIME = re.compile(r"\btime\s*\(")


# Function to build the time equivalence of a timed net.
def time_equivalence(net: ColouredNet) -> Equivalence:
    """Markings equal up to a shift of time are one class.

    Args:
        net (ColouredNet): A timed net.

    Returns:
        Equivalence: The time equivalence.

    Raises:
        EquivalenceError: For an untimed net, or one whose inscriptions read
            the clock (then shifting time changes behaviour).
    """
    if not net.timed:
        raise EquivalenceError("time equivalence needs a timed net")
    readers = []
    for t in net.transitions:
        texts = [t.get("guard_text"), t.get("time_text"), t.get("code_text")]
        texts += [e for _g, e in t["in_raw"]] + [e for _g, e in t["out_raw"]]
        if any(x and _READS_TIME.search(x) for x in texts):
            readers.append(t["name"])
    if readers:
        raise EquivalenceError(
            "time equivalence does not apply: "
            f"{', '.join(sorted(set(readers))[:5])} read the clock with time(), "
            "so two markings at different times can behave differently")
    timed = sorted(net.timed_places)

    def canonical(marking: tuple) -> tuple:
        clock = marking[-1]
        if clock == 0 and all(tok[1] >= 0 for p in timed for tok in marking[p]):
            return marking
        out = list(marking)
        for p in timed:
            out[p] = tuple(sorted(TimedToken(tok[0], max(0, tok[1] - clock))
                                  for tok in marking[p]))
        out[-1] = 0
        return tuple(out)

    return Equivalence(
        "time", canonical, exact=True,
        note="markings equal up to a shift of time; no inscription reads "
             "time(), and no property observes timestamps")


# Function to wrap a user canonical form.
def user_equivalence(canonical: Callable[[tuple], tuple],
                     name: Optional[str] = None) -> Equivalence:
    """An equivalence given by a canonical-form function.

    Args:
        canonical (callable): ``canonical(marking) -> marking``. It must
            return a marking of the net (the representative is explored).
        name (str, optional): For reports.

    Returns:
        Equivalence: Not exact: its verdicts depend on the consistency test.
    """
    return Equivalence(name or getattr(canonical, "__name__", "user"),
                       canonical, exact=False,
                       note="given by the user; consistency was tested on "
                            "sampled markings, not proved")


# Class reporting the consistency test.
class ConsistencyReport:
    """What the consistency test of a quotient found.

    Attributes:
        tested (int): Markings tested against their representatives.
        violations (list): Messages, at most a few.
        exact (bool): Whether the equivalence is exact by construction.
    """

    # Method to collect the outcome.
    def __init__(self, exact: bool):
        """Create an empty report.

        Args:
            exact (bool): Whether the equivalence is exact.
        """
        self.exact = exact
        self.tested = 0
        self.violations: List[str] = []

    # Property telling whether the verdicts can be trusted.
    @property
    def consistent(self) -> bool:
        """No violation was found.

        Returns:
            bool: True when the test found nothing.
        """
        return not self.violations

    # Method to render the outcome.
    def summary(self) -> str:
        """One line for the report.

        Returns:
            str: The outcome.
        """
        if self.violations:
            return (f"INCONSISTENT on {len(self.violations)} of {self.tested} "
                    f"tested markings: {self.violations[0]}")
        how = "exact by construction; " if self.exact else ""
        return f"{how}consistent on {self.tested} tested markings"


# Function to give the classes of the successors of a marking.
def _successor_classes(net: ColouredNet, eq: Equivalence, marking: tuple
                       ) -> frozenset:
    """The ``(transition, class)`` pairs a marking can reach in one step.

    A set, not a multiset: what consistency requires is that the same
    classes are reachable, and two occurrences may well lead to one class
    from one marking and to two markings of it from another (two ready
    tokens stamped at different past times are one token class).

    Args:
        net (ColouredNet): The net.
        eq (Equivalence): The equivalence.
        marking (tuple): A marking.

    Returns:
        frozenset: The classes reached, per transition.
    """
    return frozenset((ti, eq.canonical(net.fire(marking, ti, env)))
                     for ti, _key, env in net.enabled(marking))


# Function to explore the quotient graph.
def build_quotient(net: ColouredNet, eq: Equivalence, max_nodes: int = 200_000,
                   initial: Optional[tuple] = None, checks: int = 300
                   ) -> Tuple[StateSpace, ConsistencyReport]:
    """Explore one representative per class.

    Args:
        net (ColouredNet): The net.
        eq (Equivalence): The equivalence.
        max_nodes (int): Budget of classes.
        initial (tuple, optional): Start marking.
        checks (int): Markings to test for consistency.

    Returns:
        tuple: ``(quotient, consistency report)``. The quotient's markings are
        the representatives.

    Raises:
        EquivalenceError: When the canonical form does not return a marking.
    """
    t0 = time.perf_counter()
    start = eq.canonical(net.initial if initial is None else initial)
    nodes = {start: 0}
    markings = [start]
    succ: List[List[Tuple[int, Tuple, int]]] = [[]]
    parent: List[Optional[Tuple[int, int, tuple]]] = [None]
    queue = collections.deque([0])
    complete = True
    samples: List[Tuple[tuple, tuple]] = []
    report = ConsistencyReport(eq.exact)
    while queue:
        src = queue.popleft()
        marking = markings[src]
        for ti, key, env in net.enabled(marking):
            concrete = net.fire(marking, ti, env)
            rep = eq.canonical(concrete)
            if not isinstance(rep, tuple) or len(rep) != len(concrete):
                raise EquivalenceError(f"{eq.name}: the canonical form of a "
                                       "marking is not a marking")
            if rep != concrete and len(samples) < checks:
                samples.append((concrete, rep))
            dst = nodes.get(rep)
            if dst is None:
                if len(markings) >= max_nodes:
                    complete = False
                    continue
                dst = len(markings)
                nodes[rep] = dst
                markings.append(rep)
                succ.append([])
                parent.append((src, ti, key))
                queue.append(dst)
            succ[src].append((ti, key, dst))
    elapsed = time.perf_counter() - t0
    # Consistency: a marking and its representative reach the same classes.
    for concrete, rep in samples:
        report.tested += 1
        if _successor_classes(net, eq, concrete) != \
                _successor_classes(net, eq, rep):
            if len(report.violations) < 5:
                report.violations.append(
                    "a marking and its representative reach different classes")
    for check in eq.checks:
        for m in markings:
            message = check(net, m)
            report.tested += 1
            if message and len(report.violations) < 5:
                report.violations.append(message)
    ss = StateSpace(net, markings, succ, complete, elapsed, parent)
    return ss, report


# Class deciding properties on a quotient graph.
class QuotientChecker:
    """Decides formulas on the quotient of an equivalence.

    Attributes:
        net (ColouredNet): The net.
        eq (Equivalence): The equivalence.
        ss (StateSpace): The quotient.
        consistency (ConsistencyReport): The test.
    """

    # Method to build the quotient.
    def __init__(self, net: ColouredNet, eq: Equivalence, groups=None,
                 initial: Optional[tuple] = None, max_nodes: int = 200_000):
        """Create the checker and explore the quotient.

        Args:
            net (ColouredNet): The net.
            eq (Equivalence): The equivalence.
            groups (dict, optional): Resolved groups.
            initial (tuple, optional): Start marking.
            max_nodes (int): Budget of classes.
        """
        self.net = net
        self.eq = eq
        self.groups = groups or {}
        self.ss, self.consistency = build_quotient(net, eq, max_nodes, initial)

    # Method to decide one formula.
    def decide(self, formula: Formula):
        """Verdict on the quotient, when the equivalence preserves it.

        Args:
            formula (Formula): The property.

        Returns:
            tuple: ``(holds or None, counterexample or None, reason)``.
        """
        reason = self.eq.observes(formula)
        if reason:
            return None, None, f"not preserved by {self.eq.name}: {reason}"
        if not self.consistency.consistent:
            return None, None, (f"{self.eq.name} is not consistent: "
                                f"{self.consistency.violations[0]}")
        if not self.ss.complete:
            return None, None, "quotient graph over budget"
        ctx = Context(self.ss, self.net, self.groups, semantics="textbook")
        if 0 in ctx.sat(formula):
            return True, None, ""
        cex = formula.counterexample(ctx)
        cex.data["reduction"] = self.eq.name
        cex.note = (f"{cex.note} (in the quotient by {self.eq.name}: each "
                    "marking stands for its class)")
        return False, cex, ""

    # Method to report the quotient.
    def stats(self) -> Dict[str, Any]:
        """Figures of the quotient.

        Returns:
            dict: Counts for the report.
        """
        return {"reduction": "equivalence", "equivalence": self.eq.name,
                "classes": self.ss.n_nodes, "arcs": self.ss.n_arcs,
                "dead": len(self.ss.dead), "complete": self.ss.complete,
                "consistency": self.consistency.summary(),
                "exact": self.eq.exact, "generation_s": self.ss.elapsed}
