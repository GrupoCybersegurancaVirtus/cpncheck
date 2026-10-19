"""Verdicts, and the reports built from them.

:class:`PropertyResult` is the outcome of one property, :class:`ModelCheckResult`
the outcome of one net, and :func:`compare_results` puts two runs side by side
so that a refinement can be accepted or rejected on the properties it preserves.

Reports are plain text, JSON (:meth:`ModelCheckResult.to_dict`) and LaTeX
(:meth:`ModelCheckResult.latex_table`).
"""

import os
from typing import Any, Dict, List, Optional, Tuple

from .properties import METHODS, Property

__all__ = ["PropertyResult", "ModelCheckResult", "compare_results"]


# Class holding the verdict of one property.
class PropertyResult:
    """The outcome of checking a single property.

    Attributes:
        id (str): Property identifier.
        holds (bool|None): ``True``/``False``, or ``None`` when not evaluated.
        detail (str): Counterexample, witness or reason for skipping, as
            text; the same thing as :attr:`cex` when there is one.
        elapsed (float): Seconds spent evaluating the property.
        cex (Counterexample): The evidence, when the property was violated and
            the technique produces evidence.
    """

    __slots__ = ("id", "holds", "detail", "elapsed", "_spec", "cex")

    # Method to build a property verdict.
    def __init__(self, id, holds, detail="", elapsed=0.0, spec=None, cex=None):
        """Create a verdict.

        Args:
            id (str): Property identifier.
            holds (bool|None): The verdict.
            detail (str): Evidence, counterexample or reason.
            elapsed (float): Evaluation time in seconds.
            spec (Property, optional): The descriptor, when it does not come
                from the built-in catalog -- a profile may define its own.
            cex (Counterexample, optional): The evidence for a violation.
        """
        self.id = id
        self.holds = holds
        self.detail = detail
        self.elapsed = elapsed
        self._spec = spec
        self.cex = cex

    # Property returning the catalog entry behind this verdict.
    @property
    def spec(self) -> Property:
        """The catalog descriptor.

        A verdict built by hand, or one for an identifier the profile's
        catalog does not describe, gets a bare descriptor rather than an
        error: a report must be printable whatever it contains.

        Returns:
            Property: The descriptor the verdict was given, or a bare one.
        """
        if self._spec is None:
            self._spec = Property(self.id, self.id, "", "desired", (),
                                  "No description was supplied.")
        return self._spec

    # Property returning the printable status of the verdict.
    @property
    def status(self) -> str:
        """Status label.

        A ``report`` property states a fact rather than a requirement, so it
        reads ``YES``/``NO``.

        Returns:
            str: ``"PASS"``, ``"FAIL"``, ``"YES"``, ``"NO"`` or ``"SKIP"``.
        """
        if self.holds is None:
            return "SKIP"
        if self.spec.kind == "report":
            return "YES" if self.holds else "NO"
        return "PASS" if self.holds else "FAIL"

    # Method to render the verdict for debugging.
    def __repr__(self):
        """Return a short representation.

        Returns:
            str: ``<A1 PASS>``.
        """
        return f"<{self.id} {self.status}>"


# Class aggregating every verdict produced for one .cpn model.
class ModelCheckResult:
    """The outcome of verifying one generated ``.cpn``.

    Attributes:
        path (str): The checked file.
        family (str): Detected model family.
        properties (dict): ``{id: PropertyResult}``.
        stats (dict): State-space statistics of the first verified input.
        samples (int): Inputs model checked.
        tested (int): Inputs used for conformance testing.
        warnings (list): Non-fatal problems.
        oracle (dict): The values CPN Tools is expected to print for the input
            in the file's initial marking (see :mod:`cpntools_oracle`).
        report (dict): The profile's state-space report (place bounds, dead
            and live transitions), when it produces one.
    """

    # Method to build a model-checking result.
    def __init__(self, path, family, properties, stats, samples=1, tested=0,
                 warnings=None, elapsed=0.0, oracle=None, report=None):
        """Create a result.

        Args:
            path (str): Checked model.
            family (str): Model family.
            properties (dict): Verdicts.
            stats (dict): State-space statistics.
            samples (int): Inputs model checked.
            tested (int): Inputs used for conformance testing.
            warnings (list, optional): Warnings.
            elapsed (float): Total time in seconds.
            oracle (dict, optional): Expected CPN Tools values.
            report (dict, optional): The state-space report.
        """
        self.path = path
        self.family = family
        self.properties = properties
        self.stats = stats
        self.samples = samples
        self.tested = tested
        self.warnings = list(warnings or [])
        self.elapsed = elapsed
        self.oracle = dict(oracle or {})
        self.report_data = dict(report or {})

    # Property telling whether every evaluated property holds.
    @property
    def passed(self) -> bool:
        """Whether no evaluated property was violated.

        Report properties state facts and do not count.

        Returns:
            bool: True if nothing failed (skipped properties do not count).
        """
        return not self.failures

    # Property listing the violated properties.
    @property
    def failures(self) -> List[PropertyResult]:
        """Violated properties.

        Returns:
            list: Results whose verdict is False, report facts excepted.
        """
        return [r for r in self.properties.values()
                if r.holds is False and r.spec.kind != "report"]

    # Property listing the properties that could not be evaluated.
    @property
    def skipped(self) -> List[PropertyResult]:
        """Properties without a verdict.

        Returns:
            list: Results whose verdict is None.
        """
        return [r for r in self.properties.values() if r.holds is None]

    # Method to allow using the result in a boolean test.
    def __bool__(self):
        """Truth value.

        Returns:
            bool: Same as :attr:`passed`.
        """
        return self.passed

    # Method to convert the result into a plain dictionary.
    def to_dict(self) -> Dict[str, Any]:
        """Serialise the result.

        Returns:
            dict: JSON-friendly representation.
        """
        return {
            "path": self.path, "family": self.family, "passed": self.passed,
            "samples": self.samples, "tested": self.tested,
            "elapsed": self.elapsed, "stats": self.stats,
            "warnings": self.warnings, "oracle": self.oracle,
            "report": self.report_data,
            "properties": {
                pid: {"name": r.spec.name, "formula": r.spec.ctl,
                      "method": r.spec.method, "kind": r.spec.kind,
                      "holds": r.holds, "status": r.status, "detail": r.detail,
                      "elapsed": r.elapsed,
                      "counterexample": (r.cex.to_dict() if r.cex is not None
                                         else None)}
                for pid, r in self.properties.items()
            },
        }

    # Method to render the result as a plain-text report.
    def report(self, show_formula: bool = True) -> str:
        """Build a human-readable report, grouped by technique.

        Args:
            show_formula (bool): Include the formula column.

        Returns:
            str: The report.
        """
        lines = []
        head = f"Model checking: {os.path.basename(self.path)}  [{self.family}]"
        lines.append(head)
        lines.append("=" * max(len(head), 76))
        st = self.stats
        if st.get("reduction") == "sweep":
            lines.append(f"  reduction        : sweep-line, progress "
                         f"{st.get('progress')}; {st.get('explored')} markings "
                         f"explored in {st.get('sweeps')} sweep(s), at most "
                         f"{st.get('peak_stored')} stored, {st.get('regress')} "
                         f"regress arc(s), {st.get('dead')} dead marking(s)"
                         f"{'' if st.get('complete', True) else ' (STOPPED EARLY)'}")
        elif st.get("reduction") in ("equivalence", "symmetry"):
            lines.append(f"  reduction        : {st.get('equivalence')}; "
                         f"{st.get('classes')} classes, {st.get('arcs')} arcs, "
                         f"{st.get('dead')} dead class(es)"
                         f"{'' if st.get('complete', True) else ' (INCOMPLETE)'}")
            lines.append(f"  consistency      : {st.get('consistency')}")
        elif st.get("reduction"):
            per = ", ".join(f"{k} x{n}" for k, n in st.get("per_kind", {}).items())
            lines.append(f"  reduction        : stubborn sets; {st.get('graphs')} "
                         f"reduced graph(s) ({per}), {st.get('nodes_total')} "
                         f"nodes in all, largest {st.get('nodes_max')}"
                         f"{'' if st.get('complete', True) else ' (SOME INCOMPLETE)'}")
            lines.append(f"  deadlock graph   : {st['nodes']} nodes, {st['arcs']} "
                         f"arcs, {st.get('dead')} dead marking(s)")
        elif st.get("nodes") is not None:
            lines.append(f"  occurrence graph : {st['nodes']} nodes, {st['arcs']} arcs"
                         f"{'' if st.get('complete', True) else ' (INCOMPLETE)'}")
            if st.get("complete", True):
                lines.append(f"  SCC graph        : {st.get('scc_nodes')} nodes, "
                             f"{st.get('scc_arcs')} arcs, {st.get('dead')} dead "
                             f"marking(s), {st.get('home')} home marking(s)")
        lines.append(f"  inputs           : {self.samples} model checked, "
                     f"{self.tested} tested   time: {self.elapsed:.2f}s")
        lines.append("  semantics        : CTL over the occurrence graph, dead "
                     "markings with a self-loop")
        id_width = max([5] + [len(pid) + 1 for pid in self.properties])
        for method, title in METHODS.items():
            rows = [r for r in self.properties.values() if r.spec.method == method]
            if not rows:
                continue
            lines.append("")
            lines.append(f"  {title}")
            lines.append("  " + "-" * 78)
            for r in rows:
                # A long name or formula pushes the columns along rather
                # than running into the next one.
                row = f"  {r.id:<{id_width}}{r.spec.name:<28} "
                if show_formula:
                    row += f"{r.spec.ctl:<40} "
                row += r.status
                lines.append(row)
                plan = st.get("plans", {}).get(r.id)
                if plan:
                    lines.append(f"        decided on: {plan}")
                if r.detail and r.holds is not True:
                    lines.append(f"        -> {r.detail}")
        lines.extend(self._report_lines())
        lines.append("")
        facts = [r for r in self.properties.values()
                 if r.spec.kind == "report" and r.holds is not None]
        n_pass = sum(1 for r in self.properties.values()
                     if r.holds is True and r.spec.kind != "report")
        if facts and len(facts) + len(self.skipped) == len(self.properties):
            lines.append(f"  {len(facts)} facts reported, "
                         f"{len(self.skipped)} skipped")
        else:
            lines.append(f"  {n_pass} passed, {len(self.failures)} failed, "
                         f"{len(self.skipped)} skipped -- "
                         f"{'VERIFIED' if self.passed else 'VIOLATION FOUND'}")
        for w in self.warnings:
            lines.append(f"  [warning] {w}")
        return "\n".join(lines)

    # Method to render the profile's state-space report.
    def _report_lines(self, limit: int = 40) -> List[str]:
        """Place bounds and dead/live transitions, when the profile gave them.

        Args:
            limit (int): Rows shown per table before eliding.

        Returns:
            list: Report lines (empty when there is no report).
        """
        rep = self.report_data
        if not rep:
            return []
        lines = ["", "  State space report", "  " + "-" * 78]
        bounds = rep.get("bounds", [])
        if bounds:
            lines.append(f"  {'place':<56}{'lower':>8}{'upper':>8}")
            for gid, low, high in bounds[:limit]:
                lines.append(f"  {gid[:56]:<56}{low:>8}{high:>8}")
            if len(bounds) > limit:
                lines.append(f"  ... {len(bounds) - limit} more places")
        ms_bounds = rep.get("multiset_bounds", [])
        if ms_bounds:
            lines.append("  multiset bounds (upper / lower):")
            for gid, up, lo in ms_bounds[:limit]:
                lines.append(f"    {gid[:40]:<40} {up[:60]}")
                lines.append(f"    {'':<40} {lo[:60]}")
        for key, title in (("dead_transitions", "dead transitions"),
                           ("live_transitions", "live transitions")):
            names = rep.get(key, [])
            shown = ", ".join(names[:limit]) if names else "none"
            more = f" ... {len(names) - limit} more" if len(names) > limit else ""
            lines.append(f"  {title} ({len(names)}): {shown}{more}")
        if "fairness" in rep:
            if not rep.get("infinite_runs"):
                lines.append("  fairness: no infinite occurrence sequences")
            else:
                for kind, title in (("impartial", "impartial transitions"),
                                    ("fair", "fair transitions"),
                                    ("just", "just transitions"),
                                    ("none", "transitions with no fairness")):
                    names = [n for n, k in rep["fairness"] if k == kind]
                    shown = ", ".join(names[:limit]) if names else "none"
                    lines.append(f"  {title} ({len(names)}): {shown}")
        return lines

    # Method to escape a formula for a LaTeX texttt cell.
    @staticmethod
    def _latex_escape(text: str) -> str:
        """Make a formula safe inside ``\\texttt{...}``.

        Args:
            text (str): The formula.

        Returns:
            str: The escaped formula.
        """
        table = {"_": r"\_", "{": r"\{", "}": r"\}", "&": r"\&", "%": r"\%",
                 "$": r"\$", "#": r"\#", "|": r"\textbar{}",
                 "<": r"\textless{}", ">": r"\textgreater{}",
                 "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
        return "".join(table.get(ch, ch) for ch in text)

    # Method to render the verdicts as LaTeX table rows.
    def latex_rows(self) -> str:
        """LaTeX rows ``ID & Property & Formula & Method & Result & Time``.

        The result column uses ``\\cmark`` / ``\\xmark``, which the preamble
        must define (``pifont``'s ``\\ding{51}`` and ``\\ding{55}``).

        Returns:
            str: One row per property.
        """
        out = []
        for pid, r in self.properties.items():
            res = {"PASS": r"\cmark", "FAIL": r"\xmark", "SKIP": "--",
                   "YES": "yes", "NO": "no"}[r.status]
            out.append(f"{pid} & {r.spec.name} & "
                       f"\\texttt{{{self._latex_escape(r.spec.ctl)}}} & "
                       f"{r.spec.method} & {res} & {r.elapsed:.3f} \\\\")
        return "\n".join(out)

    # Method to render the verdicts as a complete LaTeX table.
    def latex_table(self, label: str = "tab:model_checking",
                    caption: Optional[str] = None) -> str:
        """The whole results table, ready to paste.

        Args:
            label (str): ``\\label`` of the table.
            caption (str, optional): Caption; a default names the model and
                the size of the occurrence graph.

        Returns:
            str: A ``table`` environment.
        """
        if caption is None:
            st = self.stats
            size = (f" (occurrence graph: {st['nodes']} nodes, {st['arcs']} arcs)"
                    if st.get("nodes") else "")
            caption = (f"Verification results for the generated {self.family} "
                       f"net{size}; {self.samples} input(s) model checked.")
        return "\n".join([
            r"\begin{table}[t]", r"\centering",
            f"\\caption{{{caption}}}", f"\\label{{{label}}}",
            r"\begin{tabular}{@{}lllllr@{}}", r"\toprule",
            r"ID & Property & Formula & Method & Result & Time (s) \\",
            r"\midrule", self.latex_rows(), r"\bottomrule",
            r"\end{tabular}", r"\end{table}",
        ])

    # Method to render the result for debugging.
    def __repr__(self):
        """Return a short representation.

        Returns:
            str: ``<ModelCheckResult x.cpn VERIFIED 18/18>``.
        """
        ok = sum(1 for r in self.properties.values() if r.holds is True)
        return (f"<ModelCheckResult {os.path.basename(self.path)} "
                f"{'VERIFIED' if self.passed else 'VIOLATION'} "
                f"{ok}/{len(self.properties)}>")


# Function to compare the verdicts of the initial and the refined model.
def compare_results(initial: ModelCheckResult, final: ModelCheckResult,
                    names: Tuple[str, str] = ("initial", "refined")) -> str:
    """Side-by-side report of two runs, e.g. a model before and after a change.

    Args:
        initial (ModelCheckResult): Verdicts for the first version.
        final (ModelCheckResult): Verdicts for the second version.
        names (tuple): What to call the two versions; the default suits the
            acceptance test of a refinement.

    Returns:
        str: The comparison, listing every regression.
    """
    first, second = names
    refinement = tuple(names) == ("initial", "refined")
    broken = "by the refinement" if refinement else f"in the {second} model"
    kept = "the refinement" if refinement else f"the {second} model"
    ids = list(initial.properties)
    ids += [pid for pid in final.properties if pid not in initial.properties]
    width = max(9, len(first) + 1, len(second) + 1)
    lines = [f"{first.capitalize()} vs. {second} model", "=" * 76,
             f"  {'ID':<5}{'PROPERTY':<30}{'METHOD':<12}{first.upper():<{width}}"
             f"{second.upper():<{width}}RESULT", "  " + "-" * 74]
    regressions = []
    for pid in ids:
        a, b = initial.properties.get(pid), final.properties.get(pid)
        sa = a.status if a else "n/a"
        sb = b.status if b else "n/a"
        verdict = "same"
        if a and b and a.holds is True and b.holds is False:
            verdict = "REGRESSION"
            regressions.append((pid, b.detail))
        elif a and b and a.holds is False and b.holds is True:
            verdict = "fixed"
        elif (a and a.holds is None) or (b and b.holds is None):
            verdict = "not compared"
        spec = (a or b).spec
        lines.append(f"  {pid:<5}{spec.name:<30}{spec.method:<12}{sa:<{width}}"
                     f"{sb:<{width}}{verdict}")
    lines.append("")
    if regressions:
        lines.append(f"  {len(regressions)} property(ies) broken {broken}:")
        for pid, detail in regressions:
            lines.append(f"    {pid}: {detail}")
    else:
        lines.append(f"  {kept} preserved every verified property")
    return "\n".join(lines)
