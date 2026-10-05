"""The model checker: four techniques, kept apart because they prove different things.

``ctl``
    Explicit-state CTL model checking on the occurrence graph
    (:mod:`cpncheck.statespace`, :mod:`cpncheck.ctl`), of the formulas a
    :class:`~cpncheck.profile.Profile` supplies (:mod:`cpncheck.formula`).
    Markings carry real token values, so a verdict is about the net's actual
    behaviour -- for the initial marking it was given, and only for that one.

``scc``
    Home markings, from the decomposition of the occurrence graph into strongly
    connected components: a home marking exists exactly when there is a single
    terminal component (Jensen & Kristensen, *Coloured Petri Nets*, 2009). Not a
    CTL formula; it is what CPN Tools' ``ListHomeMarkings`` computes.

``structural``
    Whatever the profile can establish without an occurrence graph -- for the
    tree profile, that guards which are conjunctions of bounds do not overlap.
    The answer holds for every input, which no single state space can show.

``testing``
    Conformance of the net with a reference implementation on a set of inputs.
    A functional-equivalence test on those inputs, not a temporal property.

The checker knows nothing about what the net computes. Which places and
transitions matter, which properties apply and what a valid output is all come
from the profile; see :mod:`cpncheck.profile` and
:mod:`cpncheck.profiles.ml_trees`.
"""

import collections
import os
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import profiles as _profiles          # noqa: F401  (registers built-ins)
from .coloured import ColouredNet, UnsupportedNet
from .counterexample import Counterexample
from .ctl import _af, _eu, _eu_witness
from .askctl import MLProgram
from .formula import Context
from .net import CPNNet
from .profile import Profile, detect
from .properties import Property
from .reduction import Dependency, ReducedChecker
from .result import ModelCheckResult, PropertyResult
from .statespace import DEFAULT_MAX_NODES, StateSpace, build_state_space

#: Accepted values of the ``reduction`` argument of :meth:`CPNModelChecker.check`.
REDUCTIONS = (None, "stubborn")

__all__ = ["CPNModelChecker", "check_cpn"]


# ---------------------------------------------------------------------------
# The checker
# ---------------------------------------------------------------------------

# Class performing model checking on a .cpn file.
class CPNModelChecker:
    """Model checker for a ``.cpn`` file.

    The net is read back from the file, never from whatever produced it, so a
    disagreement between the net and a reference implementation is a real one.

    Example:
        >>> mc = CPNModelChecker("model.cpn", class_labels=[0, 1])
        >>> mc.check().passed
        True
    """

    # Method to load a .cpn model and choose its profile.
    def __init__(self, path: str, feature_names: Optional[Sequence[str]] = None,
                 class_labels: Optional[Sequence[int]] = None,
                 max_nodes: int = DEFAULT_MAX_NODES,
                 profile: Optional[Profile] = None,
                 prelude: Optional[Dict[str, Any]] = None):
        """Parse and flatten a ``.cpn`` file, then resolve its properties.

        Args:
            path (str): The model.
            feature_names (list, optional): Ordered field names, to map named
                samples onto the fields of the input token.
            class_labels (list, optional): The output domain. Without it the
                profile decides, and the property is skipped if it cannot.
            max_nodes (int): Occurrence-graph budget; beyond it the state-space
                properties get no verdict.
            profile (Profile, optional): The profile to use; detected from the
                net when omitted.
            prelude (dict, optional): Names added to the net's own ML
                declarations, and winning over them. A net that declares its
                functions in ML needs none of this.

        Raises:
            UnsupportedNet: When no registered profile recognises the net.
        """
        self.path = path
        self.net = CPNNet(path)
        self.cnet = ColouredNet(self.net, prelude=prelude)
        self.profile = profile or detect(self.cnet)
        if self.profile is None:
            raise UnsupportedNet(
                f"{os.path.basename(path)}: no profile recognises this net; "
                "pass one with profile=... (see cpncheck.profile)")
        self.family = self.profile.family(self.cnet)
        self.groups = self.profile.resolve_groups(self.cnet)
        self.feature_names = list(feature_names) if feature_names else None
        self.max_nodes = int(max_nodes)
        self.labels, self.label_source = self.profile.label_domain(
            self.cnet, class_labels)
        self.formulas = self.profile.ctl_formulas(
            self.cnet, self.groups, self.labels)
        self.scc_props = self.profile.scc_properties(self.cnet, self.groups)
        self.unavailable = dict(self.profile.unavailable(
            self.cnet, self.groups, self.labels))
        self.catalog = getattr(self.profile, "catalog",
                               collections.OrderedDict())
        self.structure = (self.profile.structure(self.cnet)
                          if hasattr(self.profile, "structure") else None)
        self.input_places = tuple(self.profile.input_places(self.cnet))
        own = (self.cnet.initial[self.input_places[0]]
               if self.input_places else ())
        self.own_sample = own[0] if own else None
        self.width = len(self.own_sample) if self.own_sample else 0
        self._dependency: Optional[Dependency] = None

    # Property listing the identifiers this checker will answer.
    @property
    def property_ids(self) -> List[str]:
        """Properties the profile declared for this net.

        Returns:
            list: Identifiers, in catalog order.
        """
        ids = set(self.formulas) | set(self.scc_props) | set(self.unavailable)
        return [pid for pid in self.catalog if pid in ids]

    # ------------------------------------------------------------------
    # Inputs
    # ------------------------------------------------------------------

    # Method to normalise an input into the net's token layout.
    def as_sample(self, x):
        """Convert an input into the token the input place carries.

        Args:
            x: An input, in whatever shape the profile accepts.

        Returns:
            The token value.
        """
        return self.profile.as_input_token(self.cnet, x, self.feature_names)

    # Method to turn the samples argument into a list of record tuples.
    def _sample_list(self, samples) -> List[Optional[Tuple[float, ...]]]:
        """Normalise ``samples``; None means the file's own initial marking.

        Args:
            samples: None, one sample, a list of samples or a DataFrame.

        Returns:
            list: Record tuples (``None`` stands for the file's own input).
        """
        if samples is None:
            return [None]
        if hasattr(samples, "iloc") and hasattr(samples, "columns"):
            return [self.as_sample(samples.iloc[i]) for i in range(len(samples))]
        if isinstance(samples, dict):
            return [self.as_sample(samples)]
        if isinstance(samples, (list, tuple)) and samples and \
                not isinstance(samples[0], (int, float)):
            return [self.as_sample(s) for s in samples]
        return [self.as_sample(samples)]

    # ------------------------------------------------------------------
    # State space
    # ------------------------------------------------------------------

    # Method to build the occurrence graph for one input.
    def state_space(self, sample=None) -> StateSpace:
        """Build the occurrence graph with ``sample`` in the initial marking.

        Args:
            sample: An input, or None for the file's own initial marking.

        Returns:
            StateSpace: The occurrence graph.
        """
        initial = None
        if sample is not None:
            initial = self.cnet.initial_marking(self.as_sample(sample),
                                                places=self.input_places)
        return build_state_space(self.cnet, self.max_nodes, initial=initial)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    # Method to evaluate every formula on one occurrence graph.
    def _evaluate(self, ss: StateSpace, sample=None
                  ) -> Tuple[Dict[str, PropertyResult], Dict[str, str]]:
        """Evaluate the profile's formulas and the expected oracle values.

        Every formula is asked at the initial marking; a formula that fails is
        asked for a counterexample, which is attached to the verdict and also
        rendered into its ``detail``. The input the graph was built from is
        recorded on the counterexample, since a property is checked per input
        and which one failed is part of the evidence.

        Args:
            ss (StateSpace): A complete occurrence graph.
            sample (optional): The input written into the initial marking, or
                None when the file's own marking was used.

        Returns:
            tuple: ``({id: PropertyResult}, {oracle key: value})``.
        """
        ctx = Context(ss, self.cnet, self.groups, semantics="textbook")
        res: Dict[str, PropertyResult] = {}
        oracle: Dict[str, str] = {
            "nodes": str(ss.n_nodes), "arcs": str(ss.n_arcs),
            "scc_nodes": str(ss.n_sccs), "scc_arcs": str(ss.n_scc_arcs),
            "dead": str(len(ss.dead)), "home": str(len(ss.home)),
        }

        for pid, formula in self.formulas.items():
            t0 = time.perf_counter()
            holds = 0 in ctx.sat(formula)
            cex = None
            if not holds:
                cex = formula.counterexample(ctx)
                cex.input = sample
                cex.data["input_places"] = self.input_places
            res[pid] = PropertyResult(pid, holds, "" if holds else str(cex),
                                      time.perf_counter() - t0,
                                      spec=self.catalog.get(pid), cex=cex)
            oracle[pid] = "true" if holds else "false"

        # The same formulas under ASK-CTL's reading of AF, which is vacuously
        # true at a dead marking; reported so the oracle can be compared.
        variants = getattr(self.profile, "ev_variants", {})
        if variants:
            ev = Context(ss, self.cnet, self.groups, semantics="askctl")
            for pid, key in variants.items():
                if pid in self.formulas:
                    oracle[key] = ("true" if 0 in ev.sat(self.formulas[pid])
                                   else "false")

        for pid, reason in self.unavailable.items():
            res[pid] = PropertyResult(pid, None, reason,
                                      spec=self.catalog.get(pid))

        for pid, kind in self.scc_props.items():
            t0 = time.perf_counter()
            cex = None
            if kind == "home":
                if ss.home:
                    holds, detail = True, (f"{len(ss.home)} home marking(s), "
                                           f"{len(ss.terminal_sccs)} terminal SCC")
                else:
                    holds = False
                    cex = self._no_home_marking(ss, sample)
                    detail = str(cex)
            else:                                  # pragma: no cover - guard
                holds, detail = None, f"unknown SCC property kind {kind!r}"
            res[pid] = PropertyResult(pid, holds, detail,
                                      time.perf_counter() - t0,
                                      spec=self.catalog.get(pid), cex=cex)
            if holds is not None:
                oracle[pid] = "true" if holds else "false"

        extra = self.profile.state_space_report(self.cnet, ss)
        if extra:
            self._report = extra.get("report", {})
            oracle.update(extra.get("oracle", {}))
        return res, oracle

    # Method to show why no marking is reachable from every other.
    def _no_home_marking(self, ss: StateSpace, sample=None) -> Counterexample:
        """Evidence that the occurrence graph has several terminal components.

        A home marking exists exactly when the graph has one terminal
        component. When it has more, the evidence is two of them: once the net
        has entered either, the other can no longer be reached, so no marking
        is reachable from both.

        Args:
            ss (StateSpace): The occurrence graph.
            sample (optional): The input the graph was built from.

        Returns:
            Counterexample: The evidence.
        """
        first = {}
        for node in range(ss.n_nodes):
            first.setdefault(ss.scc[node], node)
        reps = [first[c] for c in ss.terminal_sccs[:2]]
        traces = [ss.trace(v) for v in reps]
        note = (f"{len(ss.terminal_sccs)} terminal SCCs: no marking is "
                "reachable from all others")
        if len(traces) == 2:
            note += (f"; after {traces[0]} and after {traces[1]} the runs can "
                     "no longer meet")
        return Counterexample(
            "witness", note=note, input=sample,
            data={"terminal_components": len(ss.terminal_sccs),
                  "representatives": traces})

    # Method to evaluate every property on stubborn-set reduced graphs.
    def _evaluate_reduced(self, sample=None
                          ) -> Tuple[Dict[str, PropertyResult], Dict[str, Any]]:
        """Decide the properties of one input with partial-order reduction.

        Each property is split into parts and every part is decided on the
        least-explored graph that provably gives the full graph's verdict
        (:mod:`cpncheck.reduction`). The home-marking property is read off the
        deadlock graph when the net terminates -- a finite acyclic graph has a
        home marking exactly when it has one dead marking -- and otherwise
        needs the full graph.

        Args:
            sample (optional): The input, or None for the file's own marking.

        Returns:
            tuple: ``({id: PropertyResult}, statistics)``.
        """
        initial = None
        if sample is not None:
            initial = self.cnet.initial_marking(self.as_sample(sample),
                                                places=self.input_places)
        if self._dependency is None:
            self._dependency = Dependency(self.cnet)
        rc = ReducedChecker(self.cnet, self._dependency, self.groups,
                            initial=initial, max_nodes=self.max_nodes)
        res: Dict[str, PropertyResult] = {}
        plans: Dict[str, str] = {}
        for pid, formula in self.formulas.items():
            t0 = time.perf_counter()
            holds, cex, plan = rc.decide(formula)
            if cex is not None:
                cex.input = sample
                cex.data["input_places"] = self.input_places
            detail = "" if holds else (str(cex) if cex is not None else
                                       "; ".join(plan.reasons[:2])
                                       or "reduced graph over budget")
            res[pid] = PropertyResult(pid, holds, detail,
                                      time.perf_counter() - t0,
                                      spec=self.catalog.get(pid), cex=cex)
            plans[pid] = plan.summary()

        for pid, reason in self.unavailable.items():
            res[pid] = PropertyResult(pid, None, reason,
                                      spec=self.catalog.get(pid))

        for pid, kind in self.scc_props.items():
            t0 = time.perf_counter()
            if kind != "home":                     # pragma: no cover - guard
                res[pid] = PropertyResult(pid, None,
                                          f"unknown SCC property kind {kind!r}",
                                          spec=self.catalog.get(pid))
                continue
            res[pid] = self._home_reduced(rc, pid, sample, plans)
            res[pid].elapsed = time.perf_counter() - t0
        stats = rc.stats()
        stats["plans"] = plans
        base = rc.graph("deadlock")
        stats.update({"nodes": base.n_nodes, "arcs": base.n_arcs,
                      "dead": len(base.dead), "reduction": "stubborn"})
        return res, stats

    # Method to decide the home-marking property with the reduced graphs.
    def _home_reduced(self, rc: ReducedChecker, pid: str, sample,
                      plans: Dict[str, str]) -> PropertyResult:
        """Home marking from the deadlock graph, or the full graph if needed.

        When every occurrence sequence is finite the full graph is acyclic,
        its terminal components are its dead markings, and the reduced graph
        has the same dead markings; so a home marking exists exactly when
        there is one dead marking. A net with an infinite occurrence sequence
        gets the full graph.

        Args:
            rc (ReducedChecker): The reduced checker of this input.
            pid (str): The property id.
            sample (optional): The input.
            plans (dict): Updated with the graph used.

        Returns:
            PropertyResult: The verdict.
        """
        spec = self.catalog.get(pid)
        terminating = rc.terminating()
        ss = rc.graph("deadlock" if terminating else "full")
        plans[pid] = "deadlock" if terminating else "full"
        if not ss.complete:
            return PropertyResult(pid, None, "occurrence graph over budget",
                                  spec=spec)
        if terminating:
            if len(ss.dead) == 1:
                return PropertyResult(pid, True, "terminating with one dead "
                                      "marking, which is the home marking",
                                      spec=spec)
            first = ss.dead[:2]
            cex = Counterexample(
                "witness", input=sample,
                note=(f"{len(ss.dead)} dead markings: no marking is reachable "
                      f"from all others; after {ss.trace(first[0])} and after "
                      f"{ss.trace(first[1])} the runs can no longer meet"),
                data={"terminal_components": len(ss.dead),
                      "representatives": [ss.trace(v) for v in first],
                      "reduction": "deadlock"})
            return PropertyResult(pid, False, str(cex), spec=spec, cex=cex)
        if ss.home:
            return PropertyResult(pid, True, f"{len(ss.home)} home marking(s), "
                                  f"{len(ss.terminal_sccs)} terminal SCC",
                                  spec=spec)
        cex = self._no_home_marking(ss, sample)
        return PropertyResult(pid, False, str(cex), spec=spec, cex=cex)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------


    # Method to verify the net for one or more inputs.
    def check(self, samples=None, classifier=None, use_final: bool = True,
              test_samples=None, max_nodes: Optional[int] = None,
              verbose: bool = False,
              reduction: Optional[str] = None) -> ModelCheckResult:
        """Verify every applicable property.

        Args:
            samples: Inputs to model check, one occurrence graph each (a sample,
                a list or a DataFrame). Defaults to the file's own initial
                marking.
            classifier: The classifier, to test prediction consistency (PC).
            use_final (bool): Whether the net carries the refined rules.
            test_samples: Inputs for conformance testing; defaults to
                ``samples``. Testing runs one maximal occurrence sequence per
                input, so it is cheap enough for a whole test set.
            max_nodes (int, optional): Occurrence-graph budget.
            verbose (bool): Print progress.
            reduction (str, optional): ``"stubborn"`` decides every property
                on stubborn-set reduced graphs (:mod:`cpncheck.reduction`)
                instead of the full occurrence graph. The verdicts are the
                same; the graph statistics are not, so no CPN Tools oracle
                values are produced in that mode.

        Returns:
            ModelCheckResult: Verdicts, statistics and the expected CPN Tools
            values.

        Raises:
            ValueError: For an unknown ``reduction``.
        """
        t0 = time.time()
        if reduction not in REDUCTIONS:
            raise ValueError(f"reduction must be one of {REDUCTIONS}, "
                             f"not {reduction!r}")
        if max_nodes is not None:
            self.max_nodes = int(max_nodes)
        xs = self._sample_list(samples)
        merged: "collections.OrderedDict[str, PropertyResult]" = \
            collections.OrderedDict()
        self._report = None
        stats: Dict[str, Any] = {}
        oracle: Dict[str, str] = {}
        warnings: List[str] = []
        for i, x in enumerate(xs):
            if verbose:
                print(f"  [mc] input {i + 1}/{len(xs)}")
            if reduction == "stubborn":
                part, rstats = self._evaluate_reduced(x)
                if not rstats["complete"]:
                    warnings.append(f"a reduced graph exceeded {self.max_nodes} "
                                    "markings: the properties it decides have "
                                    "no verdict")
                stats = stats or rstats
                self._merge(merged, part)
                continue
            ss = self.state_space(x)
            if not ss.complete:
                warnings.append(f"occurrence graph exceeded {self.max_nodes} "
                                "markings: no state-space verdicts")
                for pid in self.property_ids:
                    merged.setdefault(pid, PropertyResult(
                        pid, None, "occurrence graph over budget",
                        spec=self.catalog.get(pid)))
                stats = stats or {"nodes": ss.n_nodes, "arcs": ss.n_arcs,
                                  "complete": False}
                continue
            part, orc = self._evaluate(ss, x)
            if not stats:
                stats = {"nodes": ss.n_nodes, "arcs": ss.n_arcs,
                         "scc_nodes": ss.n_sccs, "scc_arcs": ss.n_scc_arcs,
                         "dead": len(ss.dead), "home": len(ss.home),
                         "complete": True, "generation_s": ss.elapsed}
            if x is None:
                oracle = orc
            self._merge(merged, part)

        merged.update(self.profile.static_checks(self))
        tested = 0
        if classifier is not None:
            pool = xs if test_samples is None else self._sample_list(test_samples)
            txs = [x if x is not None else self.own_sample for x in pool]
            verdict = self.profile.conformance(self, classifier, txs, use_final)
            if verdict is not None:
                merged[verdict.id] = verdict
                tested = len(txs)

        ordered = collections.OrderedDict(
            (pid, merged[pid]) for pid in self.catalog if pid in merged)
        return ModelCheckResult(self.path, self.family, ordered, stats,
                                samples=len(xs), tested=tested, warnings=warnings,
                                elapsed=time.time() - t0, oracle=oracle,
                                report=self._report)

    @staticmethod
    def _merge(target: Dict[str, PropertyResult], part: Dict[str, PropertyResult]):
        """Conjoin verdicts; the first counterexample found is kept.

        Args:
            target (dict): Accumulated verdicts, modified in place.
            part (dict): New verdicts.
        """
        for pid, r in part.items():
            old = target.get(pid)
            if old is None:
                target[pid] = PropertyResult(pid, r.holds, r.detail,
                                             r.elapsed, spec=r._spec,
                                             cex=r.cex)
                continue
            old.elapsed += r.elapsed
            if old.holds is False:
                continue
            if r.holds is False:
                old.holds, old.detail, old.cex = False, r.detail, r.cex
            elif old.holds is None:
                old.holds, old.detail, old.cex = r.holds, r.detail, r.cex

    # ------------------------------------------------------------------
    # CPN Tools

    # Method to produce the ASK-CTL program that asks CPN Tools the same questions.
    def ml_program(self) -> Tuple[str, "collections.OrderedDict[str, str]"]:
        """The CPN ML declarations and queries matching :meth:`_evaluate`.

        Rendered from the very formulas :meth:`_evaluate` evaluates
        (:mod:`cpncheck.askctl`), so the two engines cannot be asked different
        questions. Every query is a string-valued ML expression, evaluated
        after entering the state-space tool, calculating the occurrence and SCC
        graphs and loading ASK-CTL. The keys are those of
        :attr:`ModelCheckResult.oracle`.

        Returns:
            tuple: ``(declarations, {key: expression})``.
        """
        prog = MLProgram(self.cnet)
        ctx = Context.static(self.cnet, self.groups)
        variants = getattr(self.profile, "ev_variants", {})
        q: "collections.OrderedDict[str, str]" = collections.OrderedDict()
        q["nodes"] = "Int.toString (NoOfNodes ())"
        q["arcs"] = "Int.toString (NoOfArcs ())"
        q["scc_nodes"] = "Int.toString (SccNoOfNodes ())"
        q["scc_arcs"] = "Int.toString (SccNoOfArcs ())"
        q["dead"] = "Int.toString (length (ListDeadMarkings ()))"
        q["home"] = "Int.toString (length (ListHomeMarkings ()))"
        for pid in self.property_ids:
            if pid in self.formulas:
                q[pid] = prog.query(self.formulas[pid], ctx)
                if pid in variants:
                    q[variants[pid]] = prog.query(self.formulas[pid], ctx,
                                                  semantics="askctl")
            elif self.scc_props.get(pid) == "home":
                q[pid] = "Bool.toString (length (ListHomeMarkings ()) > 0)"
        q.update(self.profile.oracle_queries(self.cnet))
        return prog.declarations(), q

    # Method to write the ASK-CTL script matching this model for CPN Tools.
    def export_askctl(self, filepath: str) -> str:
        """Write a CPN Tools script that asks every question of :meth:`check`.

        Open the net in CPN Tools, apply *Enter State Space* from the State
        Space palette, then evaluate ``use "<this file>";`` in an auxiliary
        text. The script computes the occurrence and SCC graphs itself and ends
        with a string holding one ``key=value`` per line, with the keys of
        :attr:`ModelCheckResult.oracle`.

        Args:
            filepath (str): Destination ``.sml`` path.

        Returns:
            str: The path written.
        """
        decl, queries = self.ml_program()
        out = [
            "(* ASK-CTL cross-check generated by pyRuleAnalyzer for",
            f"   {os.path.basename(self.path)} ({self.family}).",
            "   1. open the net in CPN Tools and apply Enter State Space;",
            "   2. evaluate  use \"<this file>\";  in an auxiliary text.",
            "   AFmax phi encodes the textbook AF phi: ASK-CTL's EV is vacuously",
            "   true at dead markings, so EV alone would accept a net that",
            "   deadlocks before phi. *)",
            "",
            'use (ogpath ^ "ASKCTL/ASKCTLloader.sml");',
            "CalculateOccGraph ();",
            "CalculateSccGraph ();",
            "",
            decl,
            "",
            "val PYRA_RESULTS = [",
            ",\n".join(f'  ("{k}", {v})' for k, v in queries.items()),
            "];",
            'val PYRA_REPORT = String.concat (map (fn (k, v) => k ^ "=" ^ v ^ "\\n")'
            " PYRA_RESULTS);",
            "print PYRA_REPORT;",
            "PYRA_REPORT;",
        ]
        directory = os.path.dirname(os.path.abspath(filepath))
        os.makedirs(directory, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write("\n".join(out) + "\n")
        return filepath


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------


# Function to model check a generated .cpn file in one call.
def check_cpn(path: str, samples=None, classifier=None,
              feature_names: Optional[Sequence[str]] = None,
              class_labels: Optional[Sequence[int]] = None,
              use_final: bool = True, test_samples=None,
              max_nodes: int = DEFAULT_MAX_NODES,
              verbose: bool = False, profile=None,
              prelude: Optional[Dict[str, Any]] = None,
              reduction: Optional[str] = None) -> ModelCheckResult:
    """Verify a generated ``.cpn`` model.

    Args:
        path (str): The ``.cpn`` file.
        samples: Inputs to model check (defaults to the file's own).
        classifier: Classifier for the conformance test.
        feature_names (list, optional): Ordered feature names.
        class_labels (list, optional): Label domain for A6.
        use_final (bool): Whether the net carries the refined rules.
        test_samples: Inputs for conformance testing.
        max_nodes (int): Occurrence-graph budget.
        verbose (bool): Print progress.
        profile (Profile, optional): The profile to use.
        prelude (dict, optional): Names added to the net's ML declarations.
        reduction (str, optional): ``"stubborn"`` for partial-order reduction.

    Returns:
        ModelCheckResult: Verdicts and statistics.
    """
    checker = CPNModelChecker(path, feature_names=feature_names,
                              class_labels=class_labels, max_nodes=max_nodes,
                              profile=profile, prelude=prelude)
    return checker.check(samples=samples, classifier=classifier,
                         use_final=use_final, test_samples=test_samples,
                         verbose=verbose, reduction=reduction)
