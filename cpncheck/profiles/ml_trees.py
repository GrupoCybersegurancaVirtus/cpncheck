"""The profile of the nets pyruleanalyzer generates from tree ensembles.

Everything the checker used to know about decision trees, random forests and
gradient boosting lives here: which place holds the prediction, which pages are
trees, how a boosting channel is laid out, what a valid label is, and the
properties of the catalog written as formulas over those elements.

Read it as the worked example of what a profile is. A different family of nets
-- a protocol, a workflow, a controller -- is supported by writing another one
of these, with no change to the checker.

Naming conventions this profile recognises, all on nets written by
pyruleanalyzer's exporter:

============================  ================================================
``Prediction`` (top page)     the model's output
``Input`` (top page)          the sample being classified
pages named ``Tree...``       one base learner each; their transitions are the
                              leaves, and they share one output place
a page with ``Finalize``      a boosting class channel: places ``Acc<m>`` are
                              the per-stage accumulators and ``Finalize``
                              writes the channel score
``Decide*`` (top page)        the transitions that pick the class
``Vote`` (top page)           the random-forest aggregation
============================  ================================================
"""

import collections
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..coloured import ColouredNet
from ..formula import (AF, AG, EF, EU, AllMarked, And, Dead, Enabled,
                       EnabledCount, ForEach, Implies, Marked, MaxTokens, Not,
                       TokensIn)
from ..profile import Profile, register
from ..result import PropertyResult
from ..selectors import Explicit, Group, Places, Transitions

__all__ = ["TreeStructure", "MLTreeProfile"]


# Class locating the places and transitions the properties refer to.
class TreeStructure:
    """Places and transitions named by the atomic propositions.

    Attributes:
        pred (int): Index of the top-level Prediction place.
        input (int): Index of the top-level Input place.
        trees (OrderedDict): Tree page -> ``{"leaves": [ti], "out": pidx}``.
        channels (OrderedDict): Channel page -> ``{"acc": [pidx], "score": pidx}``.
        decides (list): Decide transition indices.
        vote (list): Vote transition indices.
        vote_socks (list): Output places of every tree -- what "every tree
            has voted" refers to. Defined by the trees, not by Vote's own input
            arcs, so a Vote that stops waiting for a tree is caught.
    """

    # Method to derive the structure from a coloured net.
    def __init__(self, cnet: ColouredNet):
        """Locate every place and transition the properties need.

        Args:
            cnet (ColouredNet): The flattened net.
        """
        top = cnet.top["name"]
        self.top = top
        places, trans = cnet.places, cnet.transitions
        self.pred = next(i for i, p in enumerate(places)
                         if p["name"] == "Prediction" and p["page"] == top)
        self.input = next(i for i, p in enumerate(places)
                          if p["name"] == "Input" and p["page"] == top)

        self.trees: "collections.OrderedDict[str, dict]" = collections.OrderedDict()
        for ti, t in enumerate(trans):
            page = t["page"]
            is_leaf = (page.startswith("Tree") if cnet.family != "Decision Tree"
                       else page == top)
            if not is_leaf:
                continue
            self.trees.setdefault(page, {"leaves": [], "out": None})
            self.trees[page]["leaves"].append(ti)
        for info in self.trees.values():
            outs = {p for ti in info["leaves"] for p, _ in trans[ti]["out"]}
            info["out"] = sorted(outs)[0] if len(outs) == 1 else None

        self.channels: "collections.OrderedDict[str, dict]" = collections.OrderedDict()
        for t in trans:
            if t["name"] != "Finalize":
                continue
            page = t["page"]
            accs = sorted((int(m.group(1)), i) for i, p in enumerate(places)
                          if p["page"] == page
                          for m in [re.fullmatch(r"Acc(\d+)", p["name"])] if m)
            self.channels[page] = {"acc": [i for _, i in accs],
                                   "score": t["out"][0][0] if t["out"] else None}

        self.decides = [ti for ti, t in enumerate(trans)
                        if t["page"] == top and t["name"].startswith("Decide")]
        self.vote = [ti for ti, t in enumerate(trans)
                     if t["page"] == top and t["name"] == "Vote"]
        self.vote_socks = ([info["out"] for info in self.trees.values()
                            if info["out"] is not None] if self.vote else [])


# ---------------------------------------------------------------------------
# The profile
# ---------------------------------------------------------------------------

# Class describing tree-ensemble nets to the checker.
class MLTreeProfile(Profile):
    """The pyruleanalyzer nets: decision trees, random forests and boosting.

    Attributes:
        ev_variants (dict): Properties whose ASK-CTL reading is also reported,
            mapped to the oracle key holding it.
    """

    name = "ml_trees"
    priority = 10
    ev_variants = {"A3": "A3_ev", "B2": "B2_ev",
                   "C3a": "C3a_ev", "D2a": "D2a_ev"}

    # Method to build the profile.
    def __init__(self):
        """Create the profile with an empty structure cache."""
        self._cache: Dict[int, "TreeStructure"] = {}

    # Method to decide whether this profile recognises a net.
    def matches(self, net) -> bool:
        """Whether the net has the top-level places this profile needs.

        Args:
            net (ColouredNet): The flattened net.

        Returns:
            bool: True when a top-level ``Prediction`` and ``Input`` exist.
        """
        top = net.top["name"]
        names = {p["name"] for p in net.places if p["page"] == top}
        return {"Prediction", "Input"} <= names

    # Method to name the net's family for the report.
    def family(self, net) -> str:
        """The model family the net was generated from.

        Args:
            net (ColouredNet): The flattened net.

        Returns:
            str: ``Decision Tree``, ``Random Forest`` or the boosting family.
        """
        return net.family

    # Method to derive and cache the structure of a net.
    def structure(self, net) -> "TreeStructure":
        """The located places and transitions, computed once per net.

        Args:
            net (ColouredNet): The flattened net.

        Returns:
            TreeStructure: The structure.
        """
        key = id(net)
        if key not in self._cache:
            self._cache[key] = TreeStructure(net)
        return self._cache[key]

    # Method to resolve every group the formulas quantify over.
    def resolve_groups(self, net):
        """Trees and boosting channels, as quantification domains.

        Args:
            net (ColouredNet): The flattened net.

        Returns:
            dict: ``{"trees": ..., "channels": ...}``.
        """
        structure = self.structure(net)
        trees = Group("trees", lambda n: collections.OrderedDict(
            (page, {"leaves": info["leaves"], "out": info["out"]})
            for page, info in structure.trees.items()))
        channels = Group("channels", lambda n: collections.OrderedDict(
            (page, {"acc": ch["acc"], "score": ch["score"]})
            for page, ch in structure.channels.items()))
        return {"trees": trees.resolve(net), "channels": channels.resolve(net)}

    # Method to determine the domain of the output tokens.
    def label_domain(self, net, declared):
        """The label domain the valid-output property checks against.

        Args:
            net (ColouredNet): The flattened net.
            declared (sequence, optional): A domain the caller declared.

        Returns:
            tuple: ``(labels or None, source)``.
        """
        return self._label_domain(net, self.structure(net), declared)

    # Method to name the properties answered by SCC analysis.
    def scc_properties(self, net, groups):
        """The home-marking property.

        Args:
            net (ColouredNet): The flattened net.
            groups (dict): The resolved groups.

        Returns:
            OrderedDict: ``{"A8": "home"}``.
        """
        return collections.OrderedDict((("A8", "home"),))

    # Method to build the temporal properties that apply to a net.
    def ctl_formulas(self, net, groups, labels):
        """The catalog, as formulas over this net's places and transitions.

        A property is included only when the net has the structure it talks
        about: a net with no aggregation transition has no aggregation
        properties, rather than having them and skipping them.

        Args:
            net (ColouredNet): The flattened net.
            groups (dict): The resolved groups.
            labels (list, optional): The label domain.

        Returns:
            OrderedDict: ``property id -> Formula``.
        """
        structure = self.structure(net)
        pred = Explicit([structure.pred], "place", "Prediction")
        out: "collections.OrderedDict[str, Any]" = collections.OrderedDict()

        out["A1"] = AF(Dead().phrased("termination"))
        out["A2"] = AG(Implies(Dead(), Marked(pred),
                               note="dead marking without a prediction"))
        out["A3"] = AF(Marked(pred, note="the prediction"))
        out["A4"] = AG(EF(Marked(pred, note="a prediction")))
        out["A5"] = AG(MaxTokens(pred, 1))
        if labels is not None:
            out["A6"] = AG(TokensIn(pred, labels))
        out["A7"] = AG(MaxTokens(Places(), 1))

        trees = groups.get("trees") or {}
        if trees:
            out["B1"] = ForEach("trees", self._leaf_determinism)
            out["B2"] = ForEach("trees", self._leaf_inevitable)
            outs = tuple(p for roles in trees.values() for p in roles["out"])
            if outs:
                out["B3"] = AG(MaxTokens(
                    Explicit(outs, "place", "tree output place"), 1))

        channels = groups.get("channels") or {}
        if channels:
            out["C1"] = ForEach("channels", self._stage_precedence(net))
            out["C2"] = ForEach("channels", self._no_premature_score(net))

        if structure.decides:
            dec = Explicit(structure.decides, "transition", "Decide")
            out["C3a"] = AF(Enabled(dec, note="a Decide enabling"))
            out["C3b"] = AG(EnabledCount(dec, 1))

        if structure.vote:
            vote = Explicit(structure.vote, "transition", "Vote")
            socks = Explicit(structure.vote_socks, "place", "tree output")
            out["D1"] = AG(Implies(Enabled(vote), AllMarked(socks),
                                   note="Vote enabled with a vote missing"))
            out["D2a"] = AF(Enabled(vote, note="a Vote enabling"))
            out["D2b"] = AG(MaxTokens(pred, 1))
        return out

    # Method to build the leaf-determinism formula of one tree.
    @staticmethod
    def _leaf_determinism(roles, label):
        """At most one leaf of this tree is ever enabled.

        Args:
            roles (dict): The tree's roles.
            label (str): The tree's page.

        Returns:
            Formula: The instance.
        """
        leaves = Explicit(roles["leaves"], "transition", f"{label} leaves")
        return AG(EnabledCount(leaves, 1))

    # Method to build the leaf-inevitability formula of one tree.
    @staticmethod
    def _leaf_inevitable(roles, label):
        """Some leaf of this tree inevitably becomes enabled.

        Args:
            roles (dict): The tree's roles.
            label (str): The tree's page.

        Returns:
            Formula: The instance.
        """
        leaves = Explicit(roles["leaves"], "transition", f"{label} leaves")
        return AF(Enabled(leaves, note="a leaf becoming enabled"))

    # Method to build the stage-precedence instances of one channel.
    def _stage_precedence(self, net):
        """Stage ``m`` is never completed before stage ``m-1``.

        Args:
            net (ColouredNet): The flattened net, for place names.

        Returns:
            callable: The per-channel instance builder.
        """
        def build(roles, label):
            accs = roles["acc"]
            if len(accs) < 2:
                return None
            parts = []
            for a, b in zip(accs, accs[1:]):
                na, nb = net.places[a]["name"], net.places[b]["name"]
                parts.append(Not(EU(Not(Marked(Explicit([a], "place", na))),
                                    Marked(Explicit([b], "place", nb)),
                                    note=f"{nb} reached before {na}")))
            return And(*parts)
        return build

    # Method to build the premature-score instance of one channel.
    def _no_premature_score(self, net):
        """A channel's score appears only after its last stage completed.

        Args:
            net (ColouredNet): The flattened net, for place names.

        Returns:
            callable: The per-channel instance builder.
        """
        def build(roles, label):
            accs, score = roles["acc"], roles["score"]
            if not accs or not score:
                return None
            last = accs[-1]
            na = net.places[last]["name"]
            return Not(EU(Not(Marked(Explicit([last], "place", na))),
                          Marked(Explicit(score, "place", "the score")),
                          note=f"score before {na}"))
        return build

    # Method to run the checks that do not use the occurrence graph.
    def static_checks(self, checker):
        """Guard disjointness over the whole feature space.

        Args:
            checker (CPNModelChecker): The checker.

        Returns:
            OrderedDict: ``{"B4": PropertyResult}``.
        """
        return collections.OrderedDict((("B4", self._check_b4(checker)),))

    # Method to compare the net with a reference implementation.
    def conformance(self, checker, reference, samples, use_final):
        """Prediction consistency of the net with the classifier.

        Args:
            checker (CPNModelChecker): The checker.
            reference: The classifier.
            samples (list): Record tuples.
            use_final (bool): Whether the net carries the refined rules.

        Returns:
            PropertyResult: The PC verdict.
        """
        return self._check_pc(checker, reference, samples, use_final)

    # Method to normalise an input into the token the net expects.
    def as_input_token(self, net, x, feature_names=None):
        """Convert a sample into the ``SAMPLE`` record the net reads.

        Args:
            net (ColouredNet): The flattened net.
            x: A sample.
            feature_names (list, optional): Ordered feature names.

        Returns:
            tuple: The record fields.
        """
        own = net.initial[self.structure(net).input]
        width = len(own[0]) if own else 0
        return self._as_sample(x, feature_names, width)

    # Method to name the places holding the input token.
    def input_places(self, net):
        """The place the sample is written into.

        Args:
            net (ColouredNet): The flattened net.

        Returns:
            tuple: One place index.
        """
        return (self.structure(net).input,)

    # Method to determine the label domain used by A6.
    def _label_domain(self, net, structure, class_labels
                      ) -> Tuple[Optional[List[int]], str]:
        """Choose the label domain and say where it came from.

        Args:
            class_labels (list, optional): Declared labels.

        Returns:
            tuple: ``(labels or None, source)``.
        """
        if class_labels is not None:
            try:
                return sorted({int(c) for c in class_labels}), "declared"
            except (TypeError, ValueError):
                pass
        trans = net.transitions
        if net.family == "Gradient Boosting Decision Trees":
            ks = [int(trans[ti]["name"].rsplit("_", 1)[-1])
                  for ti in structure.decides
                  if trans[ti]["name"].rsplit("_", 1)[-1].isdigit()]
            if ks:
                return sorted(ks), "Decide transitions"
        if net.family == "Random Forest":
            for info in structure.trees.values():
                for ti in info["leaves"]:
                    for _p, terms in trans[ti]["out"]:
                        try:
                            vec = eval(terms[0][1], dict(net.env))  # noqa: S307
                        except Exception:
                            continue
                        if isinstance(vec, (tuple, list)) and vec:
                            return list(range(len(vec))), "probability-vector width"
        return None, "undeclared"


    # Method to normalise a sample into the net's record layout.
    def _as_sample(self, x, feature_names, width
                   ) -> Tuple[float, ...]:
        """Convert an input into the tuple of ``SAMPLE`` record fields.

        Args:
            x: A dict keyed by ``f<i>`` or by feature name, a pandas Series, or
                a positional sequence.

        Returns:
            tuple: The field values, in field order.

        Raises:
            ValueError: If the sample has the wrong number of features.
        """
        if isinstance(x, tuple) and all(isinstance(v, float) for v in x):
            values = list(x)
        elif isinstance(x, dict):
            if all(str(k).startswith("f") and str(k)[1:].isdigit() for k in x):
                values = [float(x[f"f{i}"]) for i in range(len(x))]
            else:
                names = feature_names or list(x.keys())
                values = [float(x[n]) for n in names]
        else:
            raw = getattr(x, "values", x)
            values = [float(v) for v in list(raw)]
        if width and len(values) != width:
            raise ValueError(f"sample has {len(values)} features, the net's "
                             f"SAMPLE record has {width}")
        return tuple(values)


    # Method to read a leaf guard back as an axis-aligned box.
    @staticmethod
    def _guard_box(guard: Optional[str]):
        """Parse a conjunctive leaf guard into per-field intervals.

        Leaf guards are conjunctions of ``#f<i> x <= c`` / ``#f<i> x > c``, so a
        leaf covers a box. Catch-all guards are complements of a disjunction
        and are not boxes; None is returned for them, which is sound for the
        overlap test because a complement is disjoint from the leaves it was
        built from.

        Args:
            guard (str): The guard text.

        Returns:
            dict|None: ``{field: (low, high)}`` for ``low < x <= high``.
        """
        text = (guard or "").strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1].strip()
        if not text or text.lower() == "true":
            return {}
        if re.search(r"\bnot\b|\borelse\b|\bfalse\b", text):
            return None
        box: Dict[str, List[float]] = {}
        for atom in (a.strip() for a in text.split("andalso")):
            m = re.fullmatch(r"#(f\d+)\s+x\s*(<=|<|>=|>)\s*"
                             r"\(?(~?[\d.]+(?:[eE]~?[\d+-]+)?)\)?", atom)
            if not m:
                return None
            field, op, raw = m.group(1), m.group(2), m.group(3)
            value = float(raw.replace("~", "-"))
            low, high = box.setdefault(field, [float("-inf"), float("inf")])
            if op in ("<=", "<"):
                box[field][1] = min(high, value)
            else:
                box[field][0] = max(low, value)
        return {k: tuple(v) for k, v in box.items()}


    # Method to find leaves of the same tree whose regions intersect.
    def _check_b4(self, checker) -> PropertyResult:
        """Structural guard disjointness over the whole feature space.

        Returns:
            PropertyResult: The B4 verdict.
        """
        t0 = time.perf_counter()
        found = []
        unparsed = 0
        trans = checker.cnet.transitions
        inf = float("inf")
        for page, info in checker.structure.trees.items():
            boxes = []
            for ti in info["leaves"]:
                box = self._guard_box(trans[ti]["guard_text"])
                if box is None:
                    if not trans[ti]["name"].endswith("_default"):
                        unparsed += 1
                    continue
                boxes.append((trans[ti]["name"], box))
            for i in range(len(boxes)):
                for j in range(i + 1, len(boxes)):
                    (ni, bi), (nj, bj) = boxes[i], boxes[j]
                    if all(max(bi.get(f, (-inf, inf))[0], bj.get(f, (-inf, inf))[0])
                           < min(bi.get(f, (-inf, inf))[1], bj.get(f, (-inf, inf))[1])
                           for f in set(bi) | set(bj)):
                        found.append((page, ni, nj))
        elapsed = time.perf_counter() - t0
        if found:
            page, a, b = found[0]
            return PropertyResult("B4", False,
                                  f"{len(found)} overlapping leaf pair(s), first: "
                                  f"{page} {a} / {b}", elapsed)
        if unparsed:
            return PropertyResult("B4", None, f"{unparsed} leaf guard(s) are not "
                                  "conjunctions of bounds", elapsed)
        return PropertyResult("B4", True, "", elapsed)

    # Method to ask the classifier for the class of every sample.
    def _model_predictions(self, checker, classifier, xs,
                           use_final: bool) -> List[int]:
        """Predict a batch with whatever API the object exposes.

        A :class:`RuleClassifier` and a :class:`PyRuleAnalyzer` are asked for
        the requested rule set explicitly (``use_final`` / ``use_refined``).

        Args:
            classifier: A RuleClassifier, a PyRuleAnalyzer or an estimator.
            xs (list): Record tuples.
            use_final (bool): Query the refined rule set.

        Returns:
            list: One label per sample.
        """
        import numpy as np

        names = (checker.feature_names
                 or getattr(classifier, "_array_feature_names", None)
                 or getattr(classifier, "feature_names", None)
                 or [f"f{i}" for i in range(checker.width)])
        matrix = np.array(xs, dtype=np.float64)
        if hasattr(classifier, "predict_batch"):
            preds = classifier.predict_batch(matrix, feature_names=list(names),
                                             use_final=use_final)
            return [int(v) for v in np.asarray(preds).ravel()]
        if hasattr(classifier, "feature_names"):
            preds = classifier.predict(matrix, use_refined=use_final)
        else:
            preds = classifier.predict(matrix)
        return [int(v) for v in np.asarray(preds).ravel()]

    # Method to compare the net's result with the classifier's on many inputs.
    def _check_pc(self, checker, classifier, xs,
                  use_final: bool) -> PropertyResult:
        """Conformance testing: the terminal Prediction of a run vs the model.

        Args:
            classifier: The model the net was generated from.
            xs (list): Record tuples.
            use_final (bool): Whether the net carries the refined rules.

        Returns:
            PropertyResult: The PC verdict.
        """
        t0 = time.perf_counter()
        # A classifier that rounds its inputs to float32 (as scikit-learn
        # does) is a function of the rounded values; give the net the same
        # values, as the exporter does for the sample of the initial marking.
        clf = getattr(classifier, "classifier", classifier)
        if getattr(clf, "input_dtype", None) == "float32":
            import numpy as np
            xs = [tuple(float(v) for v in np.asarray(x, dtype=np.float32))
                  for x in xs]
        try:
            got = []
            for x in xs:
                final = checker.cnet.run(checker.cnet.initial_marking(x))
                tokens = final[checker.structure.pred]
                got.append(int(tokens[0]) if len(tokens) == 1 else None)
            expected = self._model_predictions(checker, classifier, xs, use_final)
        except Exception as exc:
            return PropertyResult("PC", None, f"not evaluated: {exc}",
                                  time.perf_counter() - t0)
        bad = [(g, e) for g, e in zip(got, expected) if g != e]
        if bad:
            return PropertyResult("PC", False, f"{len(bad)}/{len(xs)} input(s) "
                                  f"disagree, first: net={bad[0][0]} "
                                  f"model={bad[0][1]}", time.perf_counter() - t0)
        return PropertyResult("PC", True, f"{len(xs)}/{len(xs)} inputs agree",
                              time.perf_counter() - t0)


register(MLTreeProfile())
