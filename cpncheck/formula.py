"""CTL formulas as data, evaluated over an occurrence graph.

A property is built out of the classes here instead of being written as Python
code against a particular net. That buys three things:

* the same formula can be evaluated in Python and rendered as an ASK-CTL query
  for CPN Tools (:mod:`cpncheck.askctl`), so the two can no longer drift apart;
* a violated formula explains itself -- every operator knows what a
  counterexample to *it* looks like;
* a caller can state its own properties without touching the checker.

A state formula denotes the set of markings satisfying it, computed with the
standard fixpoint characterisations (:mod:`cpncheck.ctl`). Properties are asked
at the initial marking: ``holds`` means ``0 in phi.eval(ctx)``.

Quantifiers
-----------
:class:`ForEach` ranges over a :class:`~cpncheck.selectors.Group` -- the tree
pages, the class channels -- and denotes the intersection of its instances, so
``forall T: phi(T)`` is a state formula like any other. A violation is reported
against the label of the instance that failed.
"""

import collections
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Sequence

from .counterexample import Counterexample, Step
from .ctl import _af, _af_lasso, _eu, _eu_path

__all__ = [
    "Context",
    "Formula",
    "Dead",
    "Marked",
    "AllMarked",
    "MaxTokens",
    "TokensIn",
    "Enabled",
    "EnabledCount",
    "Not",
    "And",
    "Or",
    "Implies",
    "AG",
    "AF",
    "EF",
    "EU",
    "ForEach",
    "steps_of",
]


# Function to turn state-space arcs into counterexample steps.
def steps_of(ctx, arcs):
    """Describe a list of occurrence-graph arcs as counterexample steps.

    Args:
        ctx (Context): The evaluation context.
        arcs (sequence): ``(transition index, binding key, node)`` triples.

    Returns:
        list: :class:`~cpncheck.counterexample.Step` objects.
    """
    out = []
    for ti, key, node in arcs:
        t = ctx.net.transitions[ti]
        out.append(Step(ti, t["name"], t["page"], dict(key), node))
    return out


# Class holding everything a formula is evaluated against.
class Context:
    """The occurrence graph, the net and the resolved groups.

    Attributes:
        ss (StateSpace): The occurrence graph.
        net (ColouredNet): The flattened net.
        groups (dict): ``name -> OrderedDict[label, {role: indices}]``.
        semantics (str): ``"textbook"`` or ``"askctl"``; see :mod:`cpncheck.ctl`.
    """

    # Method to build an evaluation context.
    def __init__(self, ss, net, groups=None, semantics: str = "textbook"):
        """Create the context.

        Args:
            ss (StateSpace): The occurrence graph.
            net (ColouredNet): The flattened net.
            groups (dict, optional): Resolved groups.
            semantics (str): Semantics used by :class:`AF`.
        """
        self.ss = ss
        self.net = net
        self.groups = dict(groups or {})
        self.semantics = semantics
        self.all: FrozenSet[int] = (frozenset(range(ss.n_nodes))
                                    if ss is not None else frozenset())
        self.dead: FrozenSet[int] = (frozenset(ss.dead) if ss is not None
                                     else frozenset())
        # Keyed by id(), and the key's owner is kept alive alongside the
        # value: without that reference a temporary formula can be collected
        # and the next one allocated at the same address, which would silently
        # return the wrong satisfaction set.
        self._cache: Dict[int, tuple] = {}
        self._selected: Dict[int, tuple] = {}

    # Method to build a context that resolves names but evaluates nothing.
    @classmethod
    def static(cls, net, groups=None) -> "Context":
        """A context without an occurrence graph, for rendering only.

        :mod:`cpncheck.askctl` needs selectors and groups resolved but never
        evaluates anything, so it uses one of these.

        Args:
            net (ColouredNet): The flattened net.
            groups (dict, optional): Resolved groups.

        Returns:
            Context: A context whose node sets are empty.
        """
        return cls(None, net, groups)

    # Method to evaluate a formula, memoising the result.
    def sat(self, formula: "Formula") -> FrozenSet[int]:
        """Satisfaction set of a formula, computed once per context.

        Args:
            formula (Formula): The formula.

        Returns:
            frozenset: The nodes satisfying it.
        """
        key = id(formula)
        entry = self._cache.get(key)
        if entry is None:
            entry = self._cache[key] = (formula, frozenset(formula.eval(self)))
        return entry[1]

    # Method to resolve a selector, memoising the result.
    def select(self, selector) -> tuple:
        """Resolve a selector against the net, once per context.

        Args:
            selector (Selector): The selector.

        Returns:
            tuple: The indices.
        """
        key = id(selector)
        entry = self._selected.get(key)
        if entry is None:
            entry = self._selected[key] = (selector,
                                           tuple(selector.resolve(self.net)))
        return entry[1]

    # Method to count the arcs of a node whose transition is in a group.
    def enabled_at(self, node: int, transitions) -> List[int]:
        """Transition indices enabled at a node, restricted to a set.

        Args:
            node (int): Node id.
            transitions (container): Transition indices of interest.

        Returns:
            list: One entry per outgoing arc, so repeated bindings count twice.
        """
        return [ti for ti, _key, _w in self.ss.succ[node] if ti in transitions]


# ---------------------------------------------------------------------------
# The formula tree
# ---------------------------------------------------------------------------

# Class every formula derives from.
class Formula:
    """A state formula.

    Subclasses implement :meth:`eval`. :meth:`explain` is called only when the
    formula fails at the initial marking, and :meth:`at_fail` only for a node
    known to violate it.

    Attributes:
        note (str): Optional phrasing used in counterexamples instead of the
            generated description.
    """

    note: Optional[str] = None

    # Method to compute the satisfaction set.
    def eval(self, ctx: Context) -> FrozenSet[int]:
        """Nodes satisfying the formula.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            frozenset: The satisfaction set.

        Raises:
            NotImplementedError: Always; subclasses implement this.
        """
        raise NotImplementedError

    # Method to describe the formula in a counterexample.
    def describe(self, ctx: Context) -> str:
        """Human-readable name of the formula.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            str: The description.
        """
        return self.note or str(self)

    # Method to say why one node violates the formula.
    def at_fail(self, ctx: Context, node: int) -> str:
        """Why a particular marking violates the formula.

        Args:
            ctx (Context): The evaluation context.
            node (int): A node outside the satisfaction set.

        Returns:
            str: The reason.
        """
        return self.describe(ctx) + " does not hold"

    # Method to produce the evidence for a failure at the initial marking.
    def counterexample(self, ctx: Context) -> Counterexample:
        """Evidence that the formula fails at the initial marking.

        Every operator knows what a counterexample to *it* looks like: a
        safety property hands back the sequence to a violating marking, a
        liveness property a run that never gets there. The default is a bare
        statement, for a formula with nothing to exhibit.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            Counterexample: The evidence.
        """
        return Counterexample("witness", note=self.at_fail(ctx, 0))

    # Method to produce the counterexample for a failure, as text.
    def explain(self, ctx: Context) -> str:
        """Counterexample for a formula that fails at the initial marking.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            str: The counterexample, rendered.
        """
        return str(self.counterexample(ctx))

    # Method to attach custom phrasing to a formula.
    def phrased(self, note: str) -> "Formula":
        """Return the formula with a caller-supplied description.

        Args:
            note (str): The phrasing used in counterexamples.

        Returns:
            Formula: This formula.
        """
        self.note = note
        return self


# ---------------------------------------------------------------------------
# Atomic propositions
# ---------------------------------------------------------------------------

# Class holding of the markings with no enabled binding element.
class Dead(Formula):
    """True in a marking where no binding element is enabled."""

    # Method to compute the satisfaction set.
    def eval(self, ctx):
        """The dead markings.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            frozenset: The dead markings.
        """
        return ctx.dead

    # Method to render the formula.
    def __str__(self):
        """Return the formula text.

        Returns:
            str: ``dead``.
        """
        return "dead"


# Class holding of the markings where a selected place carries a token.
class Marked(Formula):
    """True when at least one selected place holds at least one token."""

    # Method to build the proposition.
    def __init__(self, selector, note: Optional[str] = None):
        """Create the proposition.

        Args:
            selector (Selector): The places.
            note (str, optional): Phrasing for counterexamples.
        """
        self.selector = selector
        self.note = note

    # Method to compute the satisfaction set.
    def eval(self, ctx):
        """Markings where a selected place is non-empty.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            frozenset: The satisfaction set.
        """
        places = ctx.select(self.selector)
        return frozenset(v for v in ctx.all
                         if any(ctx.ss.markings[v][p] for p in places))

    # Method to describe the formula in a counterexample.
    def describe(self, ctx):
        """Name the places.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            str: The description.
        """
        return self.note or self.selector.describe(ctx.net)

    # Method to say why one node violates the formula.
    def at_fail(self, ctx, node):
        """Report the empty places.

        Args:
            ctx (Context): The evaluation context.
            node (int): The violating node.

        Returns:
            str: The reason.
        """
        return f"{self.describe(ctx)} holds no token"

    # Method to render the formula.
    def __str__(self):
        """Return the formula text.

        Returns:
            str: ``marked(...)``.
        """
        return f"marked({self.selector!r})"


# Class holding of the markings where every selected place carries a token.
class AllMarked(Formula):
    """True when *every* selected place holds at least one token."""

    # Method to build the proposition.
    def __init__(self, selector, note: Optional[str] = None):
        """Create the proposition.

        Args:
            selector (Selector): The places.
            note (str, optional): Phrasing for counterexamples.
        """
        self.selector = selector
        self.note = note

    # Method to compute the satisfaction set.
    def eval(self, ctx):
        """Markings where no selected place is empty.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            frozenset: The satisfaction set.
        """
        places = ctx.select(self.selector)
        return frozenset(v for v in ctx.all
                         if all(ctx.ss.markings[v][p] for p in places))

    # Method to describe the formula in a counterexample.
    def describe(self, ctx):
        """Name the places.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            str: The description.
        """
        return self.note or f"every {self.selector.describe(ctx.net)}"

    # Method to say why one node violates the formula.
    def at_fail(self, ctx, node):
        """Name a place that is empty.

        Args:
            ctx (Context): The evaluation context.
            node (int): The violating node.

        Returns:
            str: The reason.
        """
        missing = [ctx.net.places[p]["name"] for p in ctx.select(self.selector)
                   if not ctx.ss.markings[node][p]]
        return f"{self.describe(ctx)}: {', '.join(missing[:3])} still empty"

    # Method to render the formula.
    def __str__(self):
        """Return the formula text.

        Returns:
            str: ``all_marked(...)``.
        """
        return f"all_marked({self.selector!r})"


# Class bounding the number of tokens of every selected place.
class MaxTokens(Formula):
    """True when no selected place holds more than ``limit`` tokens."""

    # Method to build the proposition.
    def __init__(self, selector, limit: int = 1, note: Optional[str] = None):
        """Create the proposition.

        Args:
            selector (Selector): The places.
            limit (int): The bound.
            note (str, optional): Phrasing for counterexamples.
        """
        self.selector = selector
        self.limit = int(limit)
        self.note = note

    # Method to compute the satisfaction set.
    def eval(self, ctx):
        """Markings respecting the bound.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            frozenset: The satisfaction set.
        """
        places = ctx.select(self.selector)
        limit = self.limit
        return frozenset(v for v in ctx.all
                         if all(len(ctx.ss.markings[v][p]) <= limit
                                for p in places))

    # Method to describe the formula in a counterexample.
    def describe(self, ctx):
        """Name the bound.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            str: The description.
        """
        return (self.note or
                f"|{self.selector.describe(ctx.net)}| <= {self.limit}")

    # Method to say why one node violates the formula.
    def at_fail(self, ctx, node):
        """Name a place over the bound.

        Args:
            ctx (Context): The evaluation context.
            node (int): The violating node.

        Returns:
            str: The reason.
        """
        for p in ctx.select(self.selector):
            n = len(ctx.ss.markings[node][p])
            if n > self.limit:
                return (f"{ctx.net.places[p]['name']} holds {n} tokens "
                        f"(limit {self.limit})")
        return self.describe(ctx) + " does not hold"

    # Method to render the formula.
    def __str__(self):
        """Return the formula text.

        Returns:
            str: ``|...| <= k``.
        """
        return f"|{self.selector!r}| <= {self.limit}"


# Class restricting the tokens of the selected places to a domain.
class TokensIn(Formula):
    """True when every token of every selected place belongs to a domain."""

    # Method to build the proposition.
    def __init__(self, selector, domain: Sequence[Any],
                 note: Optional[str] = None):
        """Create the proposition.

        Args:
            selector (Selector): The places.
            domain (sequence): The allowed token values.
            note (str, optional): Phrasing for counterexamples.
        """
        self.selector = selector
        self.domain = frozenset(domain)
        self.note = note

    # Method to compute the satisfaction set.
    def eval(self, ctx):
        """Markings whose selected places hold only allowed tokens.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            frozenset: The satisfaction set.
        """
        places = ctx.select(self.selector)
        domain = self.domain
        return frozenset(v for v in ctx.all
                         if all(tok in domain for p in places
                                for tok in ctx.ss.markings[v][p]))

    # Method to describe the formula in a counterexample.
    def describe(self, ctx):
        """Name the domain.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            str: The description.
        """
        return (self.note or
                f"{self.selector.describe(ctx.net)} in {sorted(self.domain)}")

    # Method to say why one node violates the formula.
    def at_fail(self, ctx, node):
        """Name the offending token.

        Args:
            ctx (Context): The evaluation context.
            node (int): The violating node.

        Returns:
            str: The reason.
        """
        for p in ctx.select(self.selector):
            for tok in ctx.ss.markings[node][p]:
                if tok not in self.domain:
                    return (f"{ctx.net.places[p]['name']} holds {tok!r}, "
                            f"outside {sorted(self.domain)}")
        return self.describe(ctx) + " does not hold"

    # Method to render the formula.
    def __str__(self):
        """Return the formula text.

        Returns:
            str: ``tokens_in(...)``.
        """
        return f"tokens_in({self.selector!r}, {sorted(self.domain)})"


# Class bounding the number of enabled occurrences of a transition group.
class EnabledCount(Formula):
    """True when at most ``limit`` occurrences of the selected transitions are enabled.

    Counted per outgoing arc, so a transition enabled in two bindings counts
    twice -- which is what ``|EN(G)|`` means in the property catalog.
    """

    # Method to build the proposition.
    def __init__(self, selector, limit: int = 1, note: Optional[str] = None):
        """Create the proposition.

        Args:
            selector (Selector): The transitions.
            limit (int): The bound.
            note (str, optional): Phrasing for counterexamples.
        """
        self.selector = selector
        self.limit = int(limit)
        self.note = note

    # Method to compute the satisfaction set.
    def eval(self, ctx):
        """Markings respecting the bound.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            frozenset: The satisfaction set.
        """
        group = set(ctx.select(self.selector))
        limit = self.limit
        return frozenset(v for v in ctx.all
                         if len(ctx.enabled_at(v, group)) <= limit)

    # Method to describe the formula in a counterexample.
    def describe(self, ctx):
        """Name the bound.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            str: The description.
        """
        return (self.note or
                f"|EN({self.selector.describe(ctx.net)})| <= {self.limit}")

    # Method to say why one node violates the formula.
    def at_fail(self, ctx, node):
        """Name the transitions enabled together.

        Args:
            ctx (Context): The evaluation context.
            node (int): The violating node.

        Returns:
            str: The reason.
        """
        group = set(ctx.select(self.selector))
        names = [ctx.net.transitions[ti]["name"]
                 for ti in ctx.enabled_at(node, group)]
        return (f"{len(names)} occurrences enabled together "
                f"({', '.join(names[:3])})")

    # Method to render the formula.
    def __str__(self):
        """Return the formula text.

        Returns:
            str: ``|EN(...)| <= k``.
        """
        return f"|EN({self.selector!r})| <= {self.limit}"


# Class holding of the markings enabling a transition group.
class Enabled(Formula):
    """True when at least one of the selected transitions is enabled."""

    # Method to build the proposition.
    def __init__(self, selector, note: Optional[str] = None):
        """Create the proposition.

        Args:
            selector (Selector): The transitions.
            note (str, optional): Phrasing for counterexamples.
        """
        self.selector = selector
        self.note = note

    # Method to compute the satisfaction set.
    def eval(self, ctx):
        """Markings with an enabled occurrence of the group.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            frozenset: The satisfaction set.
        """
        group = set(ctx.select(self.selector))
        return frozenset(v for v in ctx.all if ctx.enabled_at(v, group))

    # Method to describe the formula in a counterexample.
    def describe(self, ctx):
        """Name the transitions.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            str: The description.
        """
        return self.note or f"EN({self.selector.describe(ctx.net)})"

    # Method to say why one node violates the formula.
    def at_fail(self, ctx, node):
        """Report that nothing of the group is enabled.

        Args:
            ctx (Context): The evaluation context.
            node (int): The violating node.

        Returns:
            str: The reason.
        """
        return f"{self.describe(ctx)} is not enabled"

    # Method to render the formula.
    def __str__(self):
        """Return the formula text.

        Returns:
            str: ``EN(...)``.
        """
        return f"EN({self.selector!r})"


# ---------------------------------------------------------------------------
# Boolean connectives
# ---------------------------------------------------------------------------

# Class negating a formula.
class Not(Formula):
    """Negation."""

    # Method to build the connective.
    def __init__(self, operand: Formula, note: Optional[str] = None):
        """Create the negation.

        Args:
            operand (Formula): The negated formula.
            note (str, optional): Phrasing for counterexamples.
        """
        self.operand = operand
        self.note = note

    # Method to compute the satisfaction set.
    def eval(self, ctx):
        """The complement of the operand's satisfaction set.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            frozenset: The satisfaction set.
        """
        return ctx.all - ctx.sat(self.operand)

    # Method to produce the evidence for a failure.
    def counterexample(self, ctx):
        """Evidence for a negation that fails, i.e. an operand that holds.

        ``NOT E[hold U target]`` is the shape of the precedence properties, and
        the evidence against it is the occurrence sequence witnessing the
        ``EU``.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            Counterexample: The evidence.
        """
        inner = self.operand
        if isinstance(inner, EU):
            return inner.witness(ctx)
        if isinstance(inner, EF):
            bad = sorted(ctx.sat(inner.operand))
            if bad:
                v = bad[0]
                return Counterexample(
                    "finite", note=inner.operand.at_fail(ctx, v),
                    prefix=steps_of(ctx, ctx.ss.path(v)),
                    final=ctx.ss.markings[v])
        return Counterexample(
            "witness",
            note=f"{inner.describe(ctx)} holds at the initial marking")

    # Method to render the formula.
    def __str__(self):
        """Return the formula text.

        Returns:
            str: ``!(...)``.
        """
        return f"!({self.operand})"


# Class conjoining formulas.
class And(Formula):
    """Conjunction; the first failing conjunct is the counterexample."""

    # Method to build the connective.
    def __init__(self, *operands: Formula, **kwargs):
        """Create the conjunction.

        Args:
            *operands (Formula): The conjuncts.
            **kwargs: ``note`` for counterexample phrasing.
        """
        self.operands = list(operands)
        self.note = kwargs.get("note")

    # Method to compute the satisfaction set.
    def eval(self, ctx):
        """Intersection of the conjuncts' satisfaction sets.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            frozenset: The satisfaction set.
        """
        out = ctx.all
        for operand in self.operands:
            out = out & ctx.sat(operand)
        return out

    # Method to say why one node violates the formula.
    def at_fail(self, ctx, node):
        """Delegate to the first conjunct the node violates.

        Args:
            ctx (Context): The evaluation context.
            node (int): The violating node.

        Returns:
            str: The reason.
        """
        for operand in self.operands:
            if node not in ctx.sat(operand):
                return operand.at_fail(ctx, node)
        return self.describe(ctx) + " does not hold"

    # Method to produce the evidence for a failure.
    def counterexample(self, ctx):
        """Evidence from the first conjunct that fails at the initial marking.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            Counterexample: The evidence.
        """
        for operand in self.operands:
            if 0 not in ctx.sat(operand):
                return operand.counterexample(ctx)
        return Counterexample("witness",
                              note=self.describe(ctx) + " does not hold")

    # Method to render the formula.
    def __str__(self):
        """Return the formula text.

        Returns:
            str: ``(a & b)``.
        """
        return "(" + " & ".join(str(o) for o in self.operands) + ")"


# Class disjoining formulas.
class Or(Formula):
    """Disjunction."""

    # Method to build the connective.
    def __init__(self, *operands: Formula, **kwargs):
        """Create the disjunction.

        Args:
            *operands (Formula): The disjuncts.
            **kwargs: ``note`` for counterexample phrasing.
        """
        self.operands = list(operands)
        self.note = kwargs.get("note")

    # Method to compute the satisfaction set.
    def eval(self, ctx):
        """Union of the disjuncts' satisfaction sets.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            frozenset: The satisfaction set.
        """
        out: FrozenSet[int] = frozenset()
        for operand in self.operands:
            out = out | ctx.sat(operand)
        return out

    # Method to say why one node violates the formula.
    def at_fail(self, ctx, node):
        """Report the disjunct that was expected to hold.

        With an implication ``a -> b`` the interesting half is ``b``, which is
        the last disjunct, so that is the one reported.

        Args:
            ctx (Context): The evaluation context.
            node (int): The violating node.

        Returns:
            str: The reason.
        """
        if self.note:
            return self.note
        return self.operands[-1].at_fail(ctx, node)

    # Method to render the formula.
    def __str__(self):
        """Return the formula text.

        Returns:
            str: ``(a | b)``.
        """
        return "(" + " | ".join(str(o) for o in self.operands) + ")"


# Function to build an implication.
def Implies(left: Formula, right: Formula, note: Optional[str] = None) -> Formula:
    """``left -> right``, as ``!left | right``.

    Args:
        left (Formula): The antecedent.
        right (Formula): The consequent.
        note (str, optional): Phrasing for counterexamples.

    Returns:
        Formula: The implication.
    """
    return Or(Not(left), right, note=note)


# ---------------------------------------------------------------------------
# Temporal operators
# ---------------------------------------------------------------------------

# Class holding the markings from which the operand always holds.
class AG(Formula):
    """``AG phi``: every marking reachable from here satisfies ``phi``."""

    # Method to build the operator.
    def __init__(self, operand: Formula, note: Optional[str] = None):
        """Create the operator.

        Args:
            operand (Formula): The invariant.
            note (str, optional): Phrasing for counterexamples.
        """
        self.operand = operand
        self.note = note

    # Method to compute the satisfaction set.
    def eval(self, ctx):
        """Markings that cannot reach a violation of the operand.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            frozenset: The satisfaction set.
        """
        bad = ctx.all - ctx.sat(self.operand)
        if not bad:
            return ctx.all
        return ctx.all - frozenset(_eu(ctx.ss, set(ctx.all), set(bad)))

    # Method to produce the evidence for a failure.
    def counterexample(self, ctx):
        """The shortest occurrence sequence to a marking violating ``phi``.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            Counterexample: The evidence.
        """
        bad = sorted(ctx.all - ctx.sat(self.operand))
        if not bad:
            return Counterexample("witness",
                                  note=self.describe(ctx) + " does not hold")
        v = bad[0]
        many = f"{len(bad)} marking(s), e.g. " if len(bad) > 1 else ""
        return Counterexample(
            "finite", note=f"{many}{self.operand.at_fail(ctx, v)}",
            prefix=steps_of(ctx, ctx.ss.path(v)),
            final=ctx.ss.markings[v],
            data={"violating_markings": len(bad)})

    # Method to render the formula.
    def __str__(self):
        """Return the formula text.

        Returns:
            str: ``AG ...``.
        """
        return f"AG {self.operand}"


# Class holding the markings from which the operand is inevitable.
class AF(Formula):
    """``AF phi``: every maximal occurrence sequence reaches ``phi``.

    Under ``semantics="textbook"`` a dead marking outside ``phi`` falsifies the
    formula; under ``"askctl"`` it satisfies it vacuously, which is how CPN
    Tools' ``EV`` reads it. See :mod:`cpncheck.ctl`.
    """

    # Method to build the operator.
    def __init__(self, operand: Formula, semantics: Optional[str] = None,
                 note: Optional[str] = None):
        """Create the operator.

        Args:
            operand (Formula): The goal.
            semantics (str, optional): Overrides the context's semantics.
            note (str, optional): Phrasing for counterexamples.
        """
        self.operand = operand
        self.semantics = semantics
        self.note = note

    # Method to compute the satisfaction set.
    def eval(self, ctx):
        """Least fixpoint of ``phi or AX Z``.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            frozenset: The satisfaction set.
        """
        target = set(ctx.sat(self.operand))
        return frozenset(_af(ctx.ss, target, self.semantics or ctx.semantics))

    # Method to produce the evidence for a failure.
    def counterexample(self, ctx):
        """A maximal occurrence sequence that never reaches ``phi``.

        Two shapes: a run that stops before ``phi`` -- a path to a dead marking
        outside it -- or a run that goes on forever without reaching it, which
        needs the repeating part to be exhibited at all.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            Counterexample: The evidence.
        """
        target = set(ctx.sat(self.operand))
        what = self.operand.describe(ctx)
        stops = _eu_path(ctx.ss, set(ctx.all) - target, set(ctx.dead) - target)
        if stops is not None:
            end = stops[-1][2] if stops else 0
            return Counterexample(
                "finite", note=f"{what} never happens", via="on:",
                prefix=steps_of(ctx, stops), final=ctx.ss.markings[end],
                data={"ends_in": "a dead marking"})
        lasso = _af_lasso(ctx.ss, target)
        if lasso is not None:
            prefix, cycle = lasso
            entry = prefix[-1][2] if prefix else 0
            return Counterexample(
                "lasso", note=f"{what} never happens", via="on:",
                prefix=steps_of(ctx, prefix), cycle=steps_of(ctx, cycle),
                final=ctx.ss.markings[entry],
                data={"cycle_length": len(cycle)})
        return Counterexample("witness", note=f"a reachable cycle avoids {what}")

    # Method to render the formula.
    def __str__(self):
        """Return the formula text.

        Returns:
            str: ``AF ...``.
        """
        return f"AF {self.operand}"


# Class holding the markings from which the operand is reachable.
class EF(Formula):
    """``EF phi``: some occurrence sequence reaches ``phi``."""

    # Method to build the operator.
    def __init__(self, operand: Formula, note: Optional[str] = None):
        """Create the operator.

        Args:
            operand (Formula): The goal.
            note (str, optional): Phrasing for counterexamples.
        """
        self.operand = operand
        self.note = note

    # Method to compute the satisfaction set.
    def eval(self, ctx):
        """Backward reachability from the operand.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            frozenset: The satisfaction set.
        """
        return frozenset(_eu(ctx.ss, set(ctx.all), set(ctx.sat(self.operand))))

    # Method to say why one node violates the formula.
    def at_fail(self, ctx, node):
        """Report that the goal is unreachable from the marking.

        Args:
            ctx (Context): The evaluation context.
            node (int): The violating node.

        Returns:
            str: The reason.
        """
        return f"{self.operand.describe(ctx)} is unreachable"

    # Method to produce the evidence for a failure.
    def counterexample(self, ctx):
        """Report that no reachable marking satisfies the operand.

        There is no sequence to show: the evidence is the exhausted state
        space itself.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            Counterexample: The evidence.
        """
        return Counterexample(
            "witness",
            note=f"no reachable marking satisfies "
                 f"{self.operand.describe(ctx)}",
            data={"markings_searched": len(ctx.all)})

    # Method to render the formula.
    def __str__(self):
        """Return the formula text.

        Returns:
            str: ``EF ...``.
        """
        return f"EF {self.operand}"


# Class holding the markings satisfying an existential until.
class EU(Formula):
    """``E[hold U target]``: a path along ``hold`` reaching ``target``."""

    # Method to build the operator.
    def __init__(self, hold: Formula, target: Formula,
                 note: Optional[str] = None):
        """Create the operator.

        Args:
            hold (Formula): What holds before the target.
            target (Formula): The goal.
            note (str, optional): Phrasing for counterexamples.
        """
        self.hold = hold
        self.target = target
        self.note = note

    # Method to compute the satisfaction set.
    def eval(self, ctx):
        """Least fixpoint of ``target or (hold and EX Z)``.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            frozenset: The satisfaction set.
        """
        return frozenset(_eu(ctx.ss, set(ctx.sat(self.hold)),
                             set(ctx.sat(self.target))))

    # Method to produce the occurrence sequence witnessing the until.
    def witness(self, ctx) -> Counterexample:
        """The shortest occurrence sequence along ``hold`` into ``target``.

        This is evidence *for* the until, which is what a counterexample to
        its negation is -- and negated untils are how precedence properties
        are written.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            Counterexample: The sequence, or a bare statement when there is
            none.
        """
        path = _eu_path(ctx.ss, set(ctx.sat(self.hold)),
                        set(ctx.sat(self.target)))
        what = self.note or (f"{self.target.describe(ctx)} while "
                             f"{self.hold.describe(ctx)}")
        if path is None:
            return Counterexample("witness",
                                  note=f"{what} (no occurrence sequence)")
        end = path[-1][2] if path else 0
        return Counterexample("finite", note=what, via="on:",
                              prefix=steps_of(ctx, path),
                              final=ctx.ss.markings[end])

    # Method to produce the evidence for a failure.
    def counterexample(self, ctx):
        """Report that no such occurrence sequence exists.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            Counterexample: The evidence.
        """
        return Counterexample(
            "witness",
            note=f"no occurrence sequence reaches "
                 f"{self.target.describe(ctx)} along "
                 f"{self.hold.describe(ctx)}")

    # Method to render the formula.
    def __str__(self):
        """Return the formula text.

        Returns:
            str: ``E[a U b]``.
        """
        return f"E[{self.hold} U {self.target}]"


# ---------------------------------------------------------------------------
# Quantification over a group
# ---------------------------------------------------------------------------

# Class quantifying a formula over the members of a group.
class ForEach(Formula):
    """``forall g in group: phi(g)``, the intersection of the instances.

    The builder is called once per group member with that member's roles, and
    may return ``None`` to skip a member that the property does not apply to.
    A violation is reported against the member's label.
    """

    # Method to build the quantifier.
    def __init__(self, group_name: str,
                 builder: Callable[[Dict[str, tuple], str], Optional[Formula]],
                 note: Optional[str] = None):
        """Create the quantifier.

        Args:
            group_name (str): Name of the group to range over.
            builder (callable): ``(roles, label) -> Formula or None``.
            note (str, optional): Phrasing for counterexamples.
        """
        self.group_name = group_name
        self.builder = builder
        self.note = note
        self._instances: Optional[List] = None

    # Method to build the per-member formulas.
    def instances(self, ctx) -> List:
        """The instantiated formulas, one per applicable group member.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            list: ``(label, Formula)`` pairs.
        """
        if self._instances is None:
            out = []
            for label, roles in ctx.groups.get(self.group_name, {}).items():
                formula = self.builder(roles, label)
                if formula is not None:
                    out.append((label, formula))
            self._instances = out
        return self._instances

    # Method to compute the satisfaction set.
    def eval(self, ctx):
        """Intersection of the instances' satisfaction sets.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            frozenset: The satisfaction set.
        """
        out = ctx.all
        for _label, formula in self.instances(ctx):
            out = out & ctx.sat(formula)
        return out

    # Method to say why one node violates the formula.
    def at_fail(self, ctx, node):
        """Delegate to the first instance the node violates.

        Args:
            ctx (Context): The evaluation context.
            node (int): The violating node.

        Returns:
            str: The reason, prefixed with the member's label.
        """
        for label, formula in self.instances(ctx):
            if node not in ctx.sat(formula):
                return f"{label}: {formula.at_fail(ctx, node)}"
        return self.describe(ctx) + " does not hold"

    # Method to produce the evidence for a failure.
    def counterexample(self, ctx):
        """Evidence from the first instance that fails, blamed on its member.

        Args:
            ctx (Context): The evaluation context.

        Returns:
            Counterexample: The evidence, with the member's label in the note.
        """
        for label, formula in self.instances(ctx):
            if 0 not in ctx.sat(formula):
                cex = formula.counterexample(ctx)
                cex.note = f"{label}: {cex.note}"
                cex.data["group_member"] = label
                return cex
        return Counterexample("witness",
                              note=self.describe(ctx) + " does not hold")

    # Method to render the formula.
    def __str__(self):
        """Return the formula text.

        Returns:
            str: ``forall <group>: ...``.
        """
        return f"forall {self.group_name}: ..."
