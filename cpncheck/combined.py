"""Combined reductions: stubborn sets, the sweep-line method and quotients.

Each reduction alone is in :mod:`cpncheck.reduction`,
:mod:`cpncheck.sweepline`, :mod:`cpncheck.equivalence` and
:mod:`cpncheck.symmetry`. They act on different things -- which successors
are explored, which markings are kept, which markings are told apart -- so
they compose. ``reduction="stubborn+symmetry"`` (any order, ``+``
separated, two or more of ``stubborn``, ``sweep``, ``equivalence``,
``symmetry``) asks for all of them at once.

What a combination preserves is what every one of its parts preserves, and
only the combinations below are claimed:

``equivalence+symmetry``
    One quotient by the equivalence both generate. Its canonical form is the
    symmetry representative of the time (or user) representative
    (:func:`cpncheck.equivalence.compose`); time equivalence and symmetry
    commute, so with both built in it is exact. Decides what a quotient
    decides.

``stubborn`` + a quotient
    The ``deadlock`` and ``safety`` stubborn-set graphs are explored on class
    representatives: a representative's stubborn set is computed at the
    representative, which behaves as every marking of its class. Dead
    classes, the existence of an infinite run and the reachability of a
    class violating an invariant the equivalence does not observe are
    preserved. Properties of other kinds -- the ``stutter`` graph's cycle
    proviso is stated on the search stack and is not known to survive the
    quotient -- are decided on the plain quotient instead.

``sweep`` + a quotient
    The sweep explores representatives and forgets them behind the sweep
    line. Decides ``AG psi``, ``EF chi`` and ``not EF chi`` with ``psi`` and
    ``chi`` propositional and not observed by the equivalence.

``sweep+stubborn`` (and with a quotient)
    The sweep explores the ``deadlock`` or ``safety`` stubborn graph of the
    part. A stubborn choice depends on the marking alone, so the reduced
    successor relation is fixed and the sweep reaches all of its markings:
    dead markings and invariant violations are found. Propositional parts the
    stubborn theorems do not cover are swept on every successor.

Stubborn sets need a net whose transitions interact only through their arcs:
on a timed net, or one with priorities, inhibitor or reset arcs, or
transitions without input places, the stubborn part is dropped and the rest
of the combination still applies (the report says so). Nothing in a
combination decides the home-marking property; its verdicts do not keep
counterexample paths through concrete markings, only through
representatives (or, with the sweep, the violating marking alone).
"""

import time
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

from .coloured import ColouredNet
from .counterexample import Counterexample
from .equivalence import (ConsistencyReport, Equivalence, EquivalenceError,
                          build_quotient, check_consistency, compose,
                          time_equivalence, user_equivalence)
from .formula import AG, EF, Context, Formula, Not
from .reduction import (Dependency, _Atoms, build_reduced, classify,
                        propositional, split, stubborn_choice)
from .statespace import DEFAULT_MAX_NODES, StateSpace

__all__ = ["COMPONENTS", "CombinedChecker", "parse_combination"]

#: The reductions a combination may join.
COMPONENTS = ("stubborn", "sweep", "equivalence", "symmetry")


# Function to read a combination of reductions.
def parse_combination(reduction) -> Optional[Tuple[str, ...]]:
    """The components of a combined reduction, or None for a single one.

    Args:
        reduction: ``"stubborn+symmetry"``, a sequence of names, a single
            name or None.

    Returns:
        tuple|None: The components in :data:`COMPONENTS` order, or None when
        fewer than two are named.

    Raises:
        ValueError: For an unknown or repeated component.
    """
    if reduction is None:
        return None
    if isinstance(reduction, str):
        names = [n.strip() for n in reduction.split("+")]
    else:
        names = [str(n).strip() for n in reduction]
    if len(names) < 2:
        return None
    unknown = [n for n in names if n not in COMPONENTS]
    if unknown:
        raise ValueError(f"unknown reduction {unknown[0]!r} in a combination; "
                         f"use {', '.join(COMPONENTS)} joined with '+'")
    if len(set(names)) != len(names):
        raise ValueError("a reduction is named twice in the combination")
    return tuple(n for n in COMPONENTS if n in names)


# Function to give the state predicate a sweep decides a part through.
def _sweep_plan(part: Formula) -> Optional[Tuple[str, Formula]]:
    """How a sweep decides a part, as :meth:`SweepChecker.plan`.

    Args:
        part (Formula): One part of a property.

    Returns:
        tuple|None: ``(kind, predicate)``, or None when the sweep cannot.
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


# Class deciding properties under a combination of reductions.
class CombinedChecker:
    """Decides formulas for one initial marking under a combination.

    Attributes:
        net (ColouredNet): The net.
        components (tuple): The reductions combined.
        eq (Equivalence|None): The quotient's equivalence, if any.
        stubborn (bool): Whether stubborn sets are used (False when the net
            does not admit them, even if asked).
        progress (ProgressMeasure|None): The sweep's measure, if any.
        notes (list): What was dropped and why.
    """

    # Method to set up the checker.
    def __init__(self, net: ColouredNet, components: Sequence[str],
                 groups=None, initial: Optional[tuple] = None,
                 max_nodes: int = DEFAULT_MAX_NODES, progress=None,
                 equivalence=None, symmetry=None):
        """Resolve the components.

        Args:
            net (ColouredNet): The net.
            components (sequence): From :func:`parse_combination`.
            groups (dict, optional): Resolved groups.
            initial (tuple, optional): Start marking (concrete).
            max_nodes (int): Budget per graph (stored markings for a sweep).
            progress (optional): The sweep's measure
                (:func:`cpncheck.sweepline.parse_progress`).
            equivalence (optional): ``"time"`` or a canonical form, for the
                ``equivalence`` component.
            symmetry (optional): The symmetry specification, for the
                ``symmetry`` component.

        Raises:
            EquivalenceError: When an equivalence does not apply.
        """
        from .sweepline import parse_progress
        from .symmetry import symmetry_equivalence

        self.net = net
        self.components = tuple(components)
        self.groups = groups or {}
        self.initial = initial
        self.max_nodes = max_nodes
        self.static = Context.static(net, self.groups)
        self.notes: List[str] = []
        eqs: List[Equivalence] = []
        if "equivalence" in self.components:
            if equivalence is None or equivalence == "time":
                eqs.append(time_equivalence(net))
            elif callable(equivalence):
                eqs.append(user_equivalence(equivalence))
            else:
                raise EquivalenceError(f"unknown equivalence {equivalence!r}: "
                                       "use 'time' or a canonical-form function")
        if "symmetry" in self.components:
            if symmetry is None:
                raise EquivalenceError("the symmetry component needs symmetry=")
            eqs.append(symmetry_equivalence(net, symmetry, initial))
        self.eq: Optional[Equivalence] = None
        if len(eqs) == 1:
            self.eq = eqs[0]
        elif len(eqs) == 2:
            self.eq = compose(eqs[0], eqs[1])
        self.stubborn = "stubborn" in self.components
        if self.stubborn and not getattr(net, "reducible", True):
            self.stubborn = False
            self.notes.append("stubborn sets dropped: the net has a global "
                              "clock, priorities, inhibitor or reset arcs or "
                              "transitions without input places, so its "
                              "transitions depend on each other beyond the arcs")
        self.progress = (parse_progress(progress, net)
                         if "sweep" in self.components else None)
        self.dep = Dependency(net)
        self.atoms = _Atoms(self.static, self.dep)
        self.graphs: Dict[Any, Tuple[Any, StateSpace, ConsistencyReport]] = {}
        self.sweeps: List[Any] = []
        self._consistency: Optional[ConsistencyReport] = None

    # Property naming the combination for reports.
    @property
    def name(self) -> str:
        """``stubborn+symmetry`` and so on.

        Returns:
            str: The components joined with ``+``.
        """
        return "+".join(self.components)

    # Method to give the canonical form, if any.
    def _canonical(self):
        """The equivalence's canonical form, or None.

        Returns:
            callable|None: The form.
        """
        return self.eq.canonical if self.eq is not None else None

    # Method to say why a part is out of the combination's reach.
    def _refusal(self, part: Formula) -> Optional[str]:
        """Why the combination cannot decide a part, if it cannot.

        Args:
            part (Formula): One part.

        Returns:
            str|None: The reason.
        """
        if getattr(part, "opaque", False):
            return "an ASK-CTL query reads the whole occurrence graph"
        if self.eq is not None:
            reason = self.eq.observes(part)
            if reason:
                return f"not preserved by {self.eq.name}: {reason}"
        if self.progress is not None and _sweep_plan(part) is None:
            return ("not preserved by the sweep-line method (it keeps no "
                    "paths)")
        return None

    # Method to obtain a graph of the combination, built once.
    def _graph(self, kind: str, invariant: Optional[Formula] = None
               ) -> Tuple[StateSpace, ConsistencyReport]:
        """A stubborn graph on representatives, or the plain quotient.

        Args:
            kind (str): ``deadlock``, ``safety`` or ``quotient``.
            invariant (Formula, optional): For ``safety``.

        Returns:
            tuple: ``(graph, consistency report)``.
        """
        key = (kind, id(invariant)) if kind == "safety" else (kind,)
        hit = self.graphs.get(key)
        if hit is not None:
            return hit[1], hit[2]
        if kind == "quotient":
            ss, report = build_quotient(self.net, self.eq, self.max_nodes,
                                        self.initial)
        else:
            ss = build_reduced(self.net, self.dep, kind, atoms=self.atoms,
                               invariant=invariant, initial=self.initial,
                               max_nodes=self.max_nodes,
                               canonical=self._canonical())
            report = check_consistency(self.net, self.eq, ss.markings)
        self.graphs[key] = (invariant, ss, report)
        return ss, report

    # Method to decide one part on a graph.
    def _decide_on_graph(self, label, part: Formula):
        """Stubborn graph on representatives, or the quotient.

        Args:
            label (str, optional): The group member.
            part (Formula): The part.

        Returns:
            tuple: ``(holds or None, counterexample or None, how)``.
        """
        kind, invariant = classify(part)
        if not self.stubborn or kind not in ("deadlock", "safety"):
            kind, invariant = "quotient", None
        ss, report = self._graph(kind, invariant)
        how = f"{kind} graph of {self.eq.name} classes"
        if not report.consistent:
            return None, None, (f"{self.eq.name} is not consistent: "
                                f"{report.violations[0]}")
        if not ss.complete:
            return None, None, f"{how} exceeded {self.max_nodes} markings"
        ctx = Context(ss, self.net, self.groups)
        if 0 in ctx.sat(part):
            return True, None, how
        cex = part.counterexample(ctx)
        if label is not None:
            cex.note = f"{label}: {cex.note}"
            cex.data["group_member"] = label
        cex.data["reduction"] = f"{self.name} ({kind})"
        cex.note = (f"{cex.note} (in the {how}: each marking stands for its "
                    "class)")
        return False, cex, how

    # Method to decide several formulas.
    def decide_all(self, formulas: Dict[str, Formula]
                   ) -> Dict[str, Tuple[Optional[bool], Optional[Counterexample],
                                        str]]:
        """Verdicts of the formulas at the initial marking.

        Args:
            formulas (dict): ``{id: formula}``.

        Returns:
            dict: ``{id: (holds or None, counterexample or None, how)}``.
        """
        if self.progress is not None:
            return self._sweep_all(formulas)
        out = {}
        for pid, formula in formulas.items():
            verdict: Optional[bool] = True
            hows: List[str] = []
            cex = None
            for label, part in split(formula, self.static):
                head = f"{label}: " if label else ""
                reason = self._refusal(part)
                if reason:
                    verdict = None if verdict is not False else False
                    hows.append(head + reason)
                    continue
                holds, part_cex, how = self._decide_on_graph(label, part)
                if holds is False:
                    verdict, cex = False, part_cex
                    hows.append(head + how)
                    break
                if holds is None:
                    verdict = None if verdict is not False else False
                    hows.append(head + how)
            out[pid] = (verdict, cex, "; ".join(dict.fromkeys(hows)))
        return out

    # Method to decide the formulas a sweep can, sweeping once per graph.
    def _sweep_all(self, formulas: Dict[str, Formula]):
        """One sweep per stubborn graph kind, every predicate at once.

        Args:
            formulas (dict): ``{id: formula}``.

        Returns:
            dict: As :meth:`decide_all`.
        """
        from .sweepline import describe_marking, sweep

        # Group the predicates by the successor relation they need.
        groups: Dict[Any, Dict[str, Any]] = {}
        plans: Dict[str, List[Tuple[Optional[str], Any]]] = {}
        for pid, formula in formulas.items():
            entries: List[Tuple[Optional[str], Any]] = []
            for label, part in split(formula, self.static):
                reason = self._refusal(part)
                if reason:
                    entries.append((label, ("refused", reason)))
                    continue
                kind, target = _sweep_plan(part)
                if kind == "initial":
                    entries.append((label, ("initial", target)))
                    continue
                skind, invariant = classify(part)
                if not self.stubborn or skind not in ("deadlock", "safety"):
                    skind, invariant = "all", None
                key = (skind, id(invariant)) if skind == "safety" else (skind,)
                group = groups.setdefault(key, {"kind": skind,
                                                "invariant": invariant,
                                                "predicates": []})
                predicate = target if kind != "invariant" else Not(target)
                group["predicates"].append(predicate)
                entries.append((label, (kind, key,
                                        len(group["predicates"]) - 1)))
            plans[pid] = entries
        results = {}
        for key, group in groups.items():
            successors = None
            if group["kind"] in ("deadlock", "safety"):
                successors = (lambda m, en, k=group["kind"],
                              inv=group["invariant"]:
                              stubborn_choice(self.dep, k, self.atoms, inv,
                                              m, en))
            preds = [lambda m, c, f=f: self.atoms.holds(f, m, c)
                     for f in group["predicates"]]
            res = sweep(self.net, self.progress, preds, initial=self.initial,
                        max_stored=self.max_nodes, successors=successors,
                        canonical=self._canonical())
            res.kind = group["kind"]
            self.sweeps.append(res)
            results[key] = res
        report = self._check_sweep_consistency()
        start = self.net.initial if self.initial is None else self.initial
        out = {}
        for pid, entries in plans.items():
            verdict: Optional[bool] = True
            witness = None
            hows: List[str] = []
            for label, entry in entries:
                head = f"{label}: " if label else ""
                if entry[0] == "refused":
                    verdict = None if verdict is not False else False
                    hows.append(head + entry[1])
                    continue
                if entry[0] == "initial":
                    counts: Dict[int, int] = {}
                    for ti, _k, _e in self.net.enabled(start):
                        counts[ti] = counts.get(ti, 0) + 1
                    if not self.atoms.holds(entry[1], start, counts):
                        verdict, witness = False, start
                    continue
                kind, key, i = entry
                res = results[key]
                if report is not None and not report.consistent:
                    verdict = None if verdict is not False else False
                    hows.append(f"{head}{self.eq.name} is not consistent: "
                                f"{report.violations[0]}")
                    continue
                hit = res.found.get(i)
                if kind in ("invariant", "unreachable"):
                    if hit is not None:
                        verdict, witness = False, hit
                        hows.append(f"{head}violated at a marking found by the "
                                    f"sweep ({res.kind} successors)")
                    elif not res.complete and verdict is not False:
                        verdict = None
                        hows.append(f"{head}sweep stopped early")
                elif hit is None:
                    if res.complete:
                        verdict = False
                        hows.append(f"{head}no reachable marking satisfies it")
                    elif verdict is not False:
                        verdict = None
                        hows.append(f"{head}sweep stopped early")
            cex = None
            if verdict is False and witness is not None:
                stands = (f" (a representative of its {self.eq.name} class)"
                          if self.eq is not None else "")
                cex = Counterexample(
                    "witness",
                    note=(f"a reachable marking violates it: "
                          f"{describe_marking(self.net, witness)}{stands}; "
                          f"the {self.name} search keeps no path to it"),
                    data={"marking": describe_marking(self.net, witness),
                          "reduction": self.name})
            out[pid] = (verdict, cex, "; ".join(dict.fromkeys(hows)))
        return out

    # Method to test the equivalence on what the sweeps explored.
    def _check_sweep_consistency(self) -> Optional[ConsistencyReport]:
        """The consistency test, on the sweeps' dead markings and start.

        A sweep keeps no markings, so the test runs on a fresh breadth-first
        sample of representatives, as many as :func:`check_consistency`
        examines.

        Returns:
            ConsistencyReport|None: None without an equivalence.
        """
        if self.eq is None:
            return None
        if self._consistency is None:
            sample, _ = build_quotient(self.net, self.eq, 300, self.initial,
                                       checks=0)
            self._consistency = check_consistency(self.net, self.eq,
                                                  sample.markings)
        return self._consistency

    # Method to report the exploration.
    def stats(self) -> Dict[str, Any]:
        """Figures of the graphs or sweeps.

        Returns:
            dict: Counts for the report.
        """
        out: Dict[str, Any] = {"reduction": self.name, "notes": self.notes}
        if self.eq is not None:
            out["equivalence"] = self.eq.name
            out["exact"] = self.eq.exact
        if self.progress is not None:
            out["progress"] = self.progress.text
            out["sweeps"] = [{"successors": r.kind, "explored": r.explored,
                              "peak_stored": r.distinct_bound,
                              "complete": r.complete, "dead": len(r.dead)}
                             for r in self.sweeps]
            out["nodes"] = max([r.explored for r in self.sweeps] or [0])
            out["complete"] = all(r.complete for r in self.sweeps)
            if self._consistency is not None:
                out["consistency"] = self._consistency.summary()
        else:
            out["graphs"] = {k[0]: ss.n_nodes
                             for k, (_i, ss, _r) in self.graphs.items()}
            out["nodes"] = max([ss.n_nodes for _i, ss, _r in
                                self.graphs.values()] or [0])
            out["complete"] = all(ss.complete for _i, ss, _r in
                                  self.graphs.values())
            reports = [r for _i, _s, r in self.graphs.values()]
            if reports:
                out["consistency"] = reports[0].summary()
        return out
