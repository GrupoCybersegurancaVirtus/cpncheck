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
from .ctl import _af, _eu, _eu_witness
from .askctl import MLProgram
from .formula import Context
from .net import CPNNet
from .profile import Profile, detect
from .properties import PROPERTY_CATALOG, Property
from .result import ModelCheckResult, PropertyResult
from .statespace import DEFAULT_MAX_NODES, StateSpace, build_state_space

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
                 profile: Optional[Profile] = None):
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

        Raises:
            UnsupportedNet: When no registered profile recognises the net.
        """
        self.path = path
        self.net = CPNNet(path)
        self.cnet = ColouredNet(self.net)
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
        self.catalog = getattr(self.profile, "catalog", PROPERTY_CATALOG)
        self.structure = (self.profile.structure(self.cnet)
                          if hasattr(self.profile, "structure") else None)
        self.input_places = tuple(self.profile.input_places(self.cnet))
        own = (self.cnet.initial[self.input_places[0]]
               if self.input_places else ())
        self.own_sample = own[0] if own else None
        self.width = len(self.own_sample) if self.own_sample else 0

    # Property listing the identifiers this checker will answer.
    @property
    def property_ids(self) -> List[str]:
        """Properties the profile declared for this net.

        Returns:
            list: Identifiers, in catalog order.
        """
        ids = set(self.formulas) | set(self.scc_props)
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
    def _evaluate(self, ss: StateSpace) -> Tuple[Dict[str, PropertyResult],
                                                 Dict[str, str]]:
        """Evaluate the profile's formulas and the expected oracle values.

        Every formula is asked at the initial marking; a formula that fails is
        asked to explain itself, which is what the ``detail`` of a verdict is.

        Args:
            ss (StateSpace): A complete occurrence graph.

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
            detail = "" if holds else formula.explain(ctx)
            res[pid] = PropertyResult(pid, holds, detail,
                                      time.perf_counter() - t0,
                                      spec=self.catalog.get(pid))
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

        for pid, kind in self.scc_props.items():
            t0 = time.perf_counter()
            if kind == "home":
                if ss.home:
                    holds, detail = True, (f"{len(ss.home)} home marking(s), "
                                           f"{len(ss.terminal_sccs)} terminal SCC")
                else:
                    holds, detail = False, (
                        f"{len(ss.terminal_sccs)} terminal SCCs: no marking is "
                        "reachable from all others")
            else:                                  # pragma: no cover - guard
                holds, detail = None, f"unknown SCC property kind {kind!r}"
            res[pid] = PropertyResult(pid, holds, detail,
                                      time.perf_counter() - t0,
                                      spec=self.catalog.get(pid))
            if holds is not None:
                oracle[pid] = "true" if holds else "false"
        return res, oracle

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------


    # Method to verify the net for one or more inputs.
    def check(self, samples=None, classifier=None, use_final: bool = True,
              test_samples=None, max_nodes: Optional[int] = None,
              verbose: bool = False) -> ModelCheckResult:
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

        Returns:
            ModelCheckResult: Verdicts, statistics and the expected CPN Tools
            values.
        """
        t0 = time.time()
        if max_nodes is not None:
            self.max_nodes = int(max_nodes)
        xs = self._sample_list(samples)
        merged: "collections.OrderedDict[str, PropertyResult]" = \
            collections.OrderedDict()
        stats: Dict[str, Any] = {}
        oracle: Dict[str, str] = {}
        warnings: List[str] = []
        for i, x in enumerate(xs):
            if verbose:
                print(f"  [mc] input {i + 1}/{len(xs)}")
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
            part, orc = self._evaluate(ss)
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
                                elapsed=time.time() - t0, oracle=oracle)

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
                                             r.elapsed, spec=r._spec)
                continue
            old.elapsed += r.elapsed
            if old.holds is False:
                continue
            if r.holds is False:
                old.holds, old.detail = False, r.detail
            elif old.holds is None:
                old.holds, old.detail = r.holds, r.detail

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
        return prog.declarations(), q

    # Method to produce the hand-written ASK-CTL program of the tree profile.
    def _legacy_ml_program(self) -> Tuple[str,
                                          "collections.OrderedDict[str, str]"]:
        """The CPN ML declarations and queries matching :meth:`_evaluate`.

        Every query is a string-valued ML expression, evaluated after entering
        the state-space tool, calculating the occurrence and SCC graphs and
        loading ASK-CTL. The keys are those of :attr:`ModelCheckResult.oracle`.

        Returns:
            tuple: ``(declarations, {key: expression})``.
        """
        S = self.structure
        net = self.cnet
        top = S.top

        def mark(pidx):
            p = net.places[pidx]
            return f"(fn n => size (Mark.{p['page']}'{p['name']} 1 n))"

        def group_fun(name, tis):
            cases = " | ".join(
                f"Bind.{net.transitions[ti]['page']}'{net.transitions[ti]['name']} _ "
                f"=> true" for ti in tis)
            return f"fun {name} a = case ArcToBE a of {cases} | _ => false;"

        decl: List[str] = []
        decl.append("val DEAD = NOT(MODAL(TT));")
        decl.append(f"fun nPred n = size (Mark.{top}'Prediction 1 n);")
        decl.append('val PRED = NF("predicted", fn n => nPred n > 0);')
        decl.append("fun AFmax phi = AND(EV(phi), "
                    "NOT(EXIST_UNTIL(NOT(phi), AND(DEAD, NOT(phi)))));")
        decl.append("fun enCount isT n = length (List.filter isT (OutArcs n));")
        decl.append('fun EN isT = NF("enabled", fn n => enCount isT n > 0);')
        decl.append('fun MK f = NF("marked", fn (n : Node) => (f n : int) > 0);')
        decl.append("val allMarks = [" + ", ".join(mark(i) for i in
                                                    range(len(net.places))) + "];")
        if self.labels is not None:
            decl.append("val LABELS = [" + ", ".join(str(k) for k in self.labels)
                        + "];")
            decl.append(f"fun validLabels n = let val m = Mark.{top}'Prediction 1 n "
                        "in size m = List.foldl (fn (k, acc) => acc + cf (k, m)) 0 "
                        "LABELS end;")
        tree_names = []
        for i, info in enumerate(S.trees.values()):
            decl.append(group_fun(f"isLeaf{i}", info["leaves"]))
            tree_names.append(f"isLeaf{i}")
        if tree_names:
            decl.append("val leafGroups = [" + ", ".join(tree_names) + "];")
            outs = [info["out"] for info in S.trees.values() if info["out"] is not None]
            decl.append("val treeOuts = [" + ", ".join(mark(p) for p in outs) + "];")
        if S.channels:
            pairs = [(a, b) for ch in S.channels.values()
                     for a, b in zip(ch["acc"], ch["acc"][1:])]
            decl.append("val accPairs = [" + ", ".join(
                f"({mark(a)}, {mark(b)})" for a, b in pairs) + "];")
            scores = [(ch["acc"][-1], ch["score"]) for ch in S.channels.values()
                      if ch["acc"] and ch["score"] is not None]
            decl.append("val scorePairs = [" + ", ".join(
                f"({mark(a)}, {mark(b)})" for a, b in scores) + "];")
        if S.decides:
            decl.append(group_fun("isDecide", S.decides))
        if S.vote:
            decl.append(group_fun("isVote", S.vote))
            decl.append("val voteMarks = [" + ", ".join(
                mark(p) for p in S.vote_socks) + "];")

        def ev(formula):
            return f"Bool.toString (eval_node ({formula}) InitNode)"

        q: "collections.OrderedDict[str, str]" = collections.OrderedDict()
        q["nodes"] = "Int.toString (NoOfNodes ())"
        q["arcs"] = "Int.toString (NoOfArcs ())"
        q["scc_nodes"] = "Int.toString (SccNoOfNodes ())"
        q["scc_arcs"] = "Int.toString (SccNoOfArcs ())"
        q["dead"] = "Int.toString (length (ListDeadMarkings ()))"
        q["home"] = "Int.toString (length (ListHomeMarkings ()))"
        q["A1"] = ev("EV(DEAD)")
        q["A2"] = ev("NOT(POS(AND(DEAD, NOT(PRED))))")
        q["A3"] = ev("AFmax PRED")
        q["A3_ev"] = ev("EV(PRED)")
        q["A4"] = ev("INV(POS(PRED))")
        q["A5"] = ev('INV(NF("one prediction", fn n => nPred n <= 1))')
        if self.labels is not None:
            q["A6"] = ev('INV(NF("valid labels", validLabels))')
        q["A7"] = ev('INV(NF("safe", fn n => List.all (fn f => f n <= 1) allMarks))')
        q["A8"] = "Bool.toString (length (ListHomeMarkings ()) > 0)"
        if tree_names:
            q["B1"] = ev('INV(NF("leaf determinism", fn n => List.all '
                         '(fn isT => enCount isT n <= 1) leafGroups))')
            q["B2"] = ("Bool.toString (List.all (fn isT => eval_node "
                       "(AFmax (EN isT)) InitNode) leafGroups)")
            q["B2_ev"] = ("Bool.toString (List.all (fn isT => eval_node "
                          "(EV (EN isT)) InitNode) leafGroups)")
            q["B3"] = ev('INV(NF("tree outputs", fn n => List.all '
                         '(fn f => f n <= 1) treeOuts))')
        if S.channels:
            q["C1"] = ("Bool.toString (List.all (fn (a, b) => eval_node "
                       "(NOT(EXIST_UNTIL(NOT(MK a), MK b))) InitNode) accPairs)")
            q["C2"] = ("Bool.toString (List.all (fn (a, b) => eval_node "
                       "(NOT(EXIST_UNTIL(NOT(MK a), MK b))) InitNode) scorePairs)")
        if S.decides:
            q["C3a"] = ev("AFmax (EN isDecide)")
            q["C3a_ev"] = ev("EV (EN isDecide)")
            q["C3b"] = ev('INV(NF("one decision", fn n => enCount isDecide n <= 1))')
        if S.vote:
            q["D1"] = ev('INV(OR(NOT(EN isVote), NF("all votes", fn n => '
                         'List.all (fn f => f n > 0) voteMarks)))')
            q["D2a"] = ev("AFmax (EN isVote)")
            q["D2a_ev"] = ev("EV (EN isVote)")
            q["D2b"] = ev('INV(NF("one aggregation", fn n => nPred n <= 1))')
        return "\n".join(decl), q

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
              verbose: bool = False) -> ModelCheckResult:
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

    Returns:
        ModelCheckResult: Verdicts and statistics.
    """
    checker = CPNModelChecker(path, feature_names=feature_names,
                              class_labels=class_labels, max_nodes=max_nodes)
    return checker.check(samples=samples, classifier=classifier,
                         use_final=use_final, test_samples=test_samples,
                         verbose=verbose)
