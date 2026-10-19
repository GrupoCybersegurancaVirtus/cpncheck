"""Rendering a formula as an ASK-CTL query for CPN Tools.

The same :mod:`cpncheck.formula` tree that :mod:`cpncheck.checker` evaluates in
Python is rendered here as CPN ML, so the two engines are asked *the same*
question by construction. Before this existed the Python check and the ASK-CTL
script were written by hand side by side, and nothing but care kept them in
agreement.

Correspondence with ASK-CTL (Cheng, Christensen & Mortensen; the ``ASKCTL``
library shipped with CPN Tools):

=========================  ====================================================
``Dead``                   ``DEAD``, declared as ``NOT(MODAL(TT))``
``Not`` / ``And`` / ``Or`` ``NOT`` / ``AND`` / ``OR`` (binary, folded right)
``AG``                     ``INV``
``EF``                     ``POS``
``EU``                     ``EXIST_UNTIL``
``AF`` (textbook)          ``AFmax``, declared below
``AF`` (ASK-CTL reading)   ``EV``
atomic propositions        ``NF("name", fn cpnq_n => ...)`` over the node's marking
``ForEach``                folded into ``AND``, one conjunct per member
=========================  ====================================================

``AF`` needs the declared helper because ASK-CTL's ``EV`` is vacuously true at a
dead marking: ``EV(phi)`` means ``AF(phi or dead)``, so a net that stops before
``phi`` would satisfy it. ``AFmax phi`` adds the missing conjunct.
"""

import collections
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import formula as F

__all__ = ["MLProgram", "UnsupportedFormula"]


# Exception raised when a formula has no ASK-CTL rendering.
class UnsupportedFormula(Exception):
    """The formula uses a construct this renderer cannot express in CPN ML."""


# Class rendering formulas as ASK-CTL and collecting the declarations they need.
class MLProgram:
    """Builds the declarations and the queries of one CPN Tools script.

    Rendering a formula may require declarations -- a predicate over arcs for a
    transition group, the ``AFmax`` helper -- which are emitted once and in
    dependency order. Render every formula first, then read
    :meth:`declarations`.

    Attributes:
        net (ColouredNet): The net being rendered, for page and element names.
    """

    # Method to build an empty program.
    def __init__(self, net):
        """Create the renderer.

        Args:
            net (ColouredNet): The flattened net.
        """
        self.net = net
        self._decls: List[str] = []
        self._seen = set()
        self._groups: Dict[tuple, str] = {}

    # Method to emit a declaration once.
    def declare(self, text: str) -> None:
        """Add a declaration, ignoring repeats.

        Args:
            text (str): The CPN ML declaration.
        """
        if text not in self._seen:
            self._seen.add(text)
            self._decls.append(text)

    # Method to return every declaration emitted so far.
    def declarations(self) -> str:
        """The declarations the rendered queries depend on.

        Returns:
            str: One declaration per line, in dependency order.
        """
        return "\n".join(self._decls)

    # ------------------------------------------------------------------
    # Names
    # ------------------------------------------------------------------

    # Method to render the token count of one place as an ML function.
    def mark(self, pidx: int) -> str:
        """A function from a node to the number of tokens of a place.

        Args:
            pidx (int): Place index.

        Returns:
            str: ``(fn cpnq_n => size (Mark.Page'Place 1 cpnq_n))``.
        """
        return f"(fn cpnq_n => size ({self.multiset(pidx)}))"

    # Method to render a list of token counters.
    def marks(self, places: Sequence[int]) -> str:
        """An ML list of the counting functions of several places.

        Args:
            places (sequence): Place indices.

        Returns:
            str: ``[f1, f2, ...]``.
        """
        return "[" + ", ".join(self.mark(p) for p in places) + "]"

    # Method to render the marking of one place as an ML multiset.
    def multiset(self, pidx: int) -> str:
        """The marking of a place, as the ML multiset expression.

        Args:
            pidx (int): Place index.

        Returns:
            str: ``Mark.Page'Place 1 cpnq_n``.
        """
        p = self.net.places[pidx]
        return f"Mark.{_ml_of(p)} {p.get('instance', 1)} cpnq_n"

    # Method to declare and name an arc predicate for a transition group.
    def group(self, transitions: Sequence[int]) -> str:
        """A predicate telling whether an arc belongs to a transition group.

        Args:
            transitions (sequence): Transition indices.

        Returns:
            str: The name of the declared predicate.

        Raises:
            UnsupportedFormula: When the group is empty.
        """
        key = tuple(sorted(transitions))
        if not key:
            raise UnsupportedFormula("an empty transition group has no "
                                     "ASK-CTL rendering")
        if key in self._groups:
            return self._groups[key]
        name = f"isG{len(self._groups)}"
        cases = " | ".join(
            f"Bind.{_ml_of(self.net.transitions[ti])} "
            f"({self.net.transitions[ti].get('instance', 1)}, _) => true"
            for ti in key)
        self.declare("fun enCount cpnq_isT cpnq_n = length "
                     "(List.filter cpnq_isT (OutArcs cpnq_n));")
        self.declare(f"fun {name} cpnq_a = case ArcToBE cpnq_a of {cases} "
                     "| _ => false;")
        self._groups[key] = name
        return name

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    # Method to render one formula as an ASK-CTL expression.
    def render(self, phi, ctx, semantics: str = "textbook") -> str:
        """Translate a formula into an ASK-CTL expression.

        Args:
            phi (Formula): The formula.
            ctx (Context): The context the selectors resolve against.
            semantics (str): ``"textbook"`` or ``"askctl"``, for ``AF``.

        Returns:
            str: The ASK-CTL expression.

        Raises:
            UnsupportedFormula: For a formula with no rendering.
        """
        render = lambda x: self.render(x, ctx, semantics)   # noqa: E731

        if getattr(phi, "script", None) is not None:
            # An ASK-CTL query as the user wrote it, after its file.
            if phi.script.declarations:
                self.declare(phi.script.declarations)
            return phi.text

        if isinstance(phi, F.Dead):
            self.declare("val DEAD = NOT(MODAL(TT));")
            return "DEAD"

        if isinstance(phi, F.Marked):
            places = ctx.select(phi.selector)
            body = (f"size ({self.multiset(places[0])}) > 0" if len(places) == 1
                    else f"List.exists (fn cpnq_f => cpnq_f cpnq_n > 0) "
                    f"{self.marks(places)}")
            return f'NF("marked", fn cpnq_n => {body})'

        if isinstance(phi, F.AllMarked):
            places = ctx.select(phi.selector)
            return ('NF("all marked", fn cpnq_n => List.all '
                    '(fn cpnq_f => cpnq_f cpnq_n > 0) '
                    f'{self.marks(places)})')

        if isinstance(phi, F.MaxTokens):
            places = ctx.select(phi.selector)
            return (f'NF("at most {phi.limit}", fn cpnq_n => List.all '
                    f'(fn cpnq_f => cpnq_f cpnq_n <= {phi.limit}) '
                    f'{self.marks(places)})')

        if isinstance(phi, F.TokensIn):
            places = ctx.select(phi.selector)
            domain = "[" + ", ".join(_ml_literal(v)
                                     for v in sorted(phi.domain)) + "]"
            parts = [f"(let val cpnq_m = {self.multiset(p)} in size cpnq_m = "
                     f"List.foldl (fn (cpnq_k, cpnq_acc) => cpnq_acc + "
                     f"cf (cpnq_k, cpnq_m)) 0 {domain} end)"
                     for p in places]
            return ('NF("in domain", fn cpnq_n => ' + " andalso ".join(parts) + ")")

        if isinstance(phi, F.TokenCount):
            places = ctx.select(phi.selector)
            total = " + ".join(f"{self.mark(p)} cpnq_n" for p in places) or "0"
            return (f'NF("tokens", fn cpnq_n => ({total}) {phi.op} {phi.limit})')

        if isinstance(phi, F.Holds):
            places = ctx.select(phi.selector)
            parts = " orelse ".join(f"cf ({phi.ml_text}, {self.multiset(p)}) > 0"
                                    for p in places) or "false"
            return f'NF("has", fn cpnq_n => {parts})'

        if isinstance(phi, F.EnabledTally):
            name = self.group(ctx.select(phi.selector))
            return (f'NF("enabled count", fn cpnq_n => enCount {name} cpnq_n '
                    f'{phi.op} {phi.limit})')

        if isinstance(phi, F.Enabled):
            name = self.group(ctx.select(phi.selector))
            return f'NF("enabled", fn cpnq_n => enCount {name} cpnq_n > 0)'

        if isinstance(phi, F.EnabledCount):
            name = self.group(ctx.select(phi.selector))
            return (f'NF("at most {phi.limit} enabled", fn cpnq_n => enCount '
                    f'{name} cpnq_n <= {phi.limit})')

        if isinstance(phi, F.Not):
            return f"NOT({render(phi.operand)})"

        if isinstance(phi, F.And):
            return _fold("AND", [render(o) for o in phi.operands])

        if isinstance(phi, F.Or):
            return _fold("OR", [render(o) for o in phi.operands])

        if isinstance(phi, F.AG):
            return f"INV({render(phi.operand)})"

        if isinstance(phi, F.EF):
            return f"POS({render(phi.operand)})"

        if isinstance(phi, F.EU):
            return f"EXIST_UNTIL({render(phi.hold)}, {render(phi.target)})"

        if isinstance(phi, F.AF):
            inner = render(phi.operand)
            if (phi.semantics or semantics) == "askctl":
                return f"EV({inner})"
            self.declare("val DEAD = NOT(MODAL(TT));")
            self.declare("fun AFmax phi = AND(EV(phi), "
                         "NOT(EXIST_UNTIL(NOT(phi), AND(DEAD, NOT(phi)))));")
            return f"AFmax ({inner})"

        if isinstance(phi, F.ForEach):
            parts = [render(f) for _label, f in phi.instances(ctx)]
            if not parts:
                return "TT"
            return _fold("AND", parts)

        raise UnsupportedFormula(
            f"{type(phi).__name__} has no ASK-CTL rendering")

    # Method to render a formula as a complete, string-valued query.
    def query(self, phi, ctx, semantics: str = "textbook") -> str:
        """A query evaluating the formula at the initial marking.

        Args:
            phi (Formula): The formula.
            ctx (Context): The context the selectors resolve against.
            semantics (str): ``"textbook"`` or ``"askctl"``.

        Returns:
            str: A string-valued CPN ML expression.
        """
        return (f"Bool.toString (eval_node ({self.render(phi, ctx, semantics)})"
                " InitNode)")


# Function to fold a binary ASK-CTL connective over a list.
def _fold(op: str, parts: List[str]) -> str:
    """Combine expressions with a binary connective.

    Args:
        op (str): ``"AND"`` or ``"OR"``.
        parts (list): The rendered operands.

    Returns:
        str: The folded expression.
    """
    if not parts:
        return "TT" if op == "AND" else "NOT(TT)"
    out = parts[-1]
    for part in reversed(parts[:-1]):
        out = f"{op}({part}, {out})"
    return out


# Function to give the CPN ML path of a flattened place or transition.
def _ml_of(element) -> str:
    """``Page'Name`` as CPN Tools spells it in ``Mark.`` and ``Bind.``.

    Args:
        element (dict): A place or transition of the flattened net.

    Returns:
        str: The path; built from the names when the record has none.
    """
    if element.get("ml"):
        return element["ml"]
    clean = lambda s: re.sub(r"[^A-Za-z0-9_']", "_", s.strip())  # noqa: E731
    return f"{clean(element['page'])}'{clean(element['name'])}"


# Function to render a Python token value as a CPN ML literal.
def _ml_literal(value) -> str:
    """Write a token value the way CPN ML spells it.

    Args:
        value: The token value.

    Returns:
        str: The literal.

    Raises:
        UnsupportedFormula: For a value with no literal form.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value) if value >= 0 else f"~{-value}"
    if isinstance(value, float):
        text = repr(value)
        return text.replace("-", "~") if text.startswith("-") else text
    raise UnsupportedFormula(f"no CPN ML literal for {value!r}")
