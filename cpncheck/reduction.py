"""Partial-order reduction of the occurrence graph with stubborn sets.

The full occurrence graph interleaves every pair of independent binding
elements in both orders. A net made of ``n`` components that never interact
until the end -- the trees of a random forest, the class channels of a boosting
model, the processes of a protocol -- therefore has a graph exponential in
``n``, although every interleaving leads to the same place. A *stubborn set*
(Valmari, 1988) is a set of transitions that can be fired first without losing
any behaviour that matters: exploring only its enabled members at every marking
yields a *reduced* graph, often linear in ``n``, from which the same verdicts
follow.

What "matters" depends on the property, so there is not one reduced graph but
up to four kinds, chosen per property by :func:`classify`:

``deadlock``
    Conditions D0-D2 only. Preserves every reachable dead marking and the
    existence of an infinite occurrence sequence, which is all that
    termination, "every dead marking satisfies psi" and the home-marking test
    of a terminating net need (Valmari, 1988, 1990).

``safety``
    D0-D2 plus a *goal* (an up-set): at a marking where the invariant ``psi``
    still holds, the stubborn set must contain every transition that can make
    ``psi`` false. Preserves the reachability of a marking violating ``psi``,
    with no cycle proviso (Kristensen & Valmari, 2000; Valmari & Hansen, 2017).
    Used for ``AG psi``, ``!EF chi`` and ``EF chi`` with ``psi``, ``chi``
    propositional.

``stutter``
    D0-D2 plus the conditions of Gerth, Kuiper, Peled & Penczek (1999):
    the ample set is a single invisible binding element or the whole enabled
    set (C2, C4), and no reduced step closes a cycle on the search stack (C3).
    The reduced graph is then stuttering bisimilar to the full one, so every
    CTL formula without the next-time operator (CTL-X) is preserved. Used for
    everything else that does not mention ``dead``.

``full``
    The ordinary occurrence graph, for the formulas no theorem above covers.

A formula is first split into independent parts -- a ``ForEach`` into its
instances, ``AG`` of a conjunction into one ``AG`` per conjunct, ``AG`` of a
bound on many places into one per place -- because a part observes less of the
net than the whole, and the less a formula observes the more it reduces.

The dependency relations are computed from the arc structure, never from the
values the transitions compute, so they over-approximate the real dependency:
the reduction may keep more than it needs, never less.
"""

import collections
import time
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

from .coloured import ColouredNet
from .formula import (AF, AG, COMPARISONS, EF, AllMarked, And, Context, Dead,
                      Enabled, EnabledCount, EnabledTally, ForEach, Formula,
                      Holds, Marked, MaxTokens, Not, Or, TokenCount, TokensIn)
from .selectors import Explicit
from .statespace import DEFAULT_MAX_NODES, StateSpace, build_state_space

__all__ = [
    "KINDS",
    "Dependency",
    "Plan",
    "ReducedChecker",
    "build_reduced",
    "classify",
    "split",
]

#: The graph kinds, from the most to the least reduced.
KINDS = ("deadlock", "safety", "stutter", "full")

#: Markings whose enabled binding elements are remembered across graphs.
_CACHE_LIMIT = 100_000

_ATOMS = (Marked, AllMarked, MaxTokens, TokensIn, TokenCount, Holds, Enabled,
          EnabledCount, EnabledTally, Dead)
_PLACE_ATOMS = (Marked, AllMarked, MaxTokens, TokensIn, TokenCount, Holds)
_TRANSITION_ATOMS = (Enabled, EnabledCount, EnabledTally)


# ---------------------------------------------------------------------------
# Dependency relations
# ---------------------------------------------------------------------------

# Class holding the static dependency relations of a net.
class Dependency:
    """Which transitions touch which places, read off the arcs.

    An arc pair with the same inscription in both directions (``x`` in, ``x``
    out) gives the place back unchanged and is a *test*: the transition needs
    the token but neither removes nor adds one. Two transitions that only test
    a place are independent of each other.

    Attributes:
        pre (list): Per transition, the places it needs tokens in (taken or
            tested).
        takes (list): Per transition, the places it removes tokens from.
        gives (list): Per transition, the places it adds tokens to.
        changes (list): ``takes | gives``.
        givers (dict): Place -> transitions adding tokens to it.
        takers (dict): Place -> transitions removing tokens from it.
        users (dict): Place -> transitions needing tokens in it.
        conflicts (list): Per transition, what must join it in a stubborn set
            when it is enabled (see :meth:`closure`).
    """

    # Method to derive the relations from the compiled transitions.
    def __init__(self, net: ColouredNet):
        """Classify every arc and build the per-place indexes.

        Args:
            net (ColouredNet): The flattened, compiled net.
        """
        self.net = net
        n = len(net.transitions)
        self.pre: List[FrozenSet[int]] = []
        self.takes: List[FrozenSet[int]] = []
        self.gives: List[FrozenSet[int]] = []
        for t in net.transitions:
            ins = collections.defaultdict(collections.Counter)
            outs = collections.defaultdict(collections.Counter)
            # From the raw arcs: an input arc may be a pattern or an
            # expression, and both take tokens from their place.
            for gid, text in t["in_raw"]:
                ins[net.index[gid]][" ".join(str(text).split())] += 1
            for gid, text in t["out_raw"]:
                outs[net.index[gid]][" ".join(str(text).split())] += 1
            tested = {p for p in ins if outs.get(p) == ins[p]}
            self.pre.append(frozenset(ins))
            self.takes.append(frozenset(set(ins) - tested))
            self.gives.append(frozenset(set(outs) - tested))
        self.changes = [self.takes[i] | self.gives[i] for i in range(n)]
        self.givers: Dict[int, FrozenSet[int]] = self._index(self.gives)
        self.takers: Dict[int, FrozenSet[int]] = self._index(self.takes)
        self.users: Dict[int, FrozenSet[int]] = self._index(self.pre)
        touch = self._index(self.changes)
        self.conflicts: List[FrozenSet[int]] = []
        for i in range(n):
            out: Set[int] = set()
            for p in self.pre[i]:
                out |= touch.get(p, frozenset())
            for p in self.takes[i]:
                out |= self.users.get(p, frozenset())
            out.discard(i)
            self.conflicts.append(frozenset(out))

    # Method to invert a per-transition place relation.
    @staticmethod
    def _index(rel: List[FrozenSet[int]]) -> Dict[int, FrozenSet[int]]:
        """Turn ``transition -> places`` into ``place -> transitions``.

        Args:
            rel (list): Places per transition.

        Returns:
            dict: Transitions per place.
        """
        out: Dict[int, Set[int]] = collections.defaultdict(set)
        for ti, places in enumerate(rel):
            for p in places:
                out[p].add(ti)
        return {p: frozenset(ts) for p, ts in out.items()}

    # Method to list the places whose token count rules a transition out.
    def deficient(self, marking: tuple, ti: int) -> List[int]:
        """Input places holding fewer tokens than any binding needs.

        Args:
            marking (tuple): The marking.
            ti (int): A transition.

        Returns:
            list: Place indices.
        """
        needs = self.net.transitions[ti]["needs"]
        return [p for p, k in needs.items() if len(marking[p]) < k]

    # Method to name the transitions without which a disabled one stays so.
    def enablers(self, marking: tuple, ti: int) -> FrozenSet[int]:
        """Transitions one of which must occur before ``ti`` can be enabled.

        Removing tokens never enables anything, so only transitions adding
        tokens matter. When some input place is short of tokens, adding to
        that one place is necessary, and its producers suffice; the place with
        the fewest producers is chosen. When none is short, the transition is
        disabled by the token values or its guard, and a token has to change
        in some input place: every producer of every input place is needed.

        Args:
            marking (tuple): A marking in which ``ti`` is disabled.
            ti (int): The transition.

        Returns:
            frozenset: The transitions.
        """
        short = self.deficient(marking, ti)
        if short:
            return min((self.givers.get(p, frozenset()) for p in short),
                       key=len)
        out: Set[int] = set()
        for p in self.pre[ti]:
            out |= self.givers.get(p, frozenset())
        return frozenset(out)

    # Method to close a set of transitions under the stubborn-set rules.
    def closure(self, seeds: Iterable[int], marking: tuple,
                enabled: Set[int]) -> Set[int]:
        """The least stubborn set containing ``seeds``.

        Two rules, applied until nothing changes:

        * an **enabled** transition ``t`` brings in every transition that adds
          to or takes from a place ``t`` needs (so nothing outside the set can
          disable ``t``, or give it a binding it did not have), and every
          transition needing a place ``t`` takes from (so ``t`` cannot disable
          them). This is condition D1, and it makes every enabled member a key
          transition (D2);
        * a **disabled** transition brings in its :meth:`enablers`, so nothing
          outside the set can enable it.

        Both rules look at one transition at a time, so the closure of a union
        is the union of the closures; :class:`_Chooser` relies on that.

        Args:
            seeds (iterable): Transitions that must be in the set.
            marking (tuple): The current marking.
            enabled (set): Transitions with an enabled binding.

        Returns:
            set: The closed set.
        """
        out: Set[int] = set()
        stack = list(seeds)
        while stack:
            t = stack.pop()
            if t in out:
                continue
            out.add(t)
            more = (self.conflicts[t] if t in enabled
                    else self.enablers(marking, t))
            stack.extend(u for u in more if u not in out)
        return out

    # Method to name the transitions that can change a set of places.
    def touching(self, places: Iterable[int]) -> FrozenSet[int]:
        """Transitions whose occurrence changes the marking of a place given.

        Args:
            places (iterable): Place indices.

        Returns:
            frozenset: The *visible* transitions for those places.
        """
        places = set(places)
        return frozenset(i for i, ch in enumerate(self.changes) if ch & places)


# ---------------------------------------------------------------------------
# Propositions evaluated on a marking, and the transitions that can flip them
# ---------------------------------------------------------------------------

# Function to tell whether a formula has no temporal operator.
def propositional(f: Formula) -> bool:
    """Whether the formula is a Boolean combination of atomic propositions.

    Args:
        f (Formula): The formula.

    Returns:
        bool: True for atoms, ``Not``, ``And`` and ``Or`` of atoms.
    """
    if isinstance(f, _ATOMS):
        return True
    if isinstance(f, Not):
        return propositional(f.operand)
    if isinstance(f, (And, Or)):
        return all(propositional(g) for g in f.operands)
    return False


# Function to tell whether a formula mentions dead markings.
def mentions_dead(f: Formula) -> bool:
    """Whether ``dead`` occurs anywhere in the formula.

    ``AF`` evaluated under the ASK-CTL reading counts as mentioning it, since
    there a dead marking satisfies ``AF phi`` vacuously.

    Args:
        f (Formula): The formula.

    Returns:
        bool: True when the formula depends on deadness.
    """
    if isinstance(f, Dead) or getattr(f, "opaque", False):
        return True
    if isinstance(f, AF) and f.semantics == "askctl":
        return True
    for g in _children(f):
        if mentions_dead(g):
            return True
    return False


# Function to list the operands of a formula.
def _children(f: Formula) -> List[Formula]:
    """The direct sub-formulas.

    Args:
        f (Formula): The formula.

    Returns:
        list: Its operands.
    """
    if isinstance(f, (And, Or)):
        return list(f.operands)
    if isinstance(f, (Not, AG, AF, EF)):
        return [f.operand]
    if hasattr(f, "hold") and hasattr(f, "target"):
        return [f.hold, f.target]
    return []


# Class evaluating propositions on a marking without a graph.
class _Atoms:
    """Truth of atomic propositions and the transitions that can flip them.

    Attributes:
        ctx (Context): A static context, to resolve selectors.
        dep (Dependency): The relations.
    """

    # Method to bind the evaluator to a net.
    def __init__(self, ctx: Context, dep: Dependency):
        """Create the evaluator.

        Args:
            ctx (Context): A static context of the net.
            dep (Dependency): Its dependency relations.
        """
        self.ctx = ctx
        self.dep = dep

    # Method to evaluate a propositional formula on one marking.
    def holds(self, f: Formula, m: tuple, counts: Dict[int, int]) -> bool:
        """Truth of ``f`` in marking ``m``.

        Args:
            f (Formula): A propositional formula.
            m (tuple): The marking.
            counts (dict): Enabled binding elements per transition in ``m``.

        Returns:
            bool: Whether ``m`` satisfies ``f``.
        """
        sel = self.ctx.select
        if isinstance(f, Marked):
            return any(m[p] for p in sel(f.selector))
        if isinstance(f, AllMarked):
            return all(m[p] for p in sel(f.selector))
        if isinstance(f, MaxTokens):
            return all(len(m[p]) <= f.limit for p in sel(f.selector))
        if isinstance(f, TokensIn):
            return all(tok in f.domain for p in sel(f.selector)
                       for tok in self.ctx.net.values_of(p, m[p]))
        if isinstance(f, Enabled):
            return any(counts.get(t, 0) for t in sel(f.selector))
        if isinstance(f, EnabledCount):
            return sum(counts.get(t, 0) for t in sel(f.selector)) <= f.limit
        if isinstance(f, TokenCount):
            total = sum(len(m[p]) for p in sel(f.selector))
            return COMPARISONS[f.op](total, f.limit)
        if isinstance(f, Holds):
            return any(f.value in self.ctx.net.values_of(p, m[p])
                       for p in sel(f.selector))
        if isinstance(f, EnabledTally):
            total = sum(counts.get(t, 0) for t in sel(f.selector))
            return COMPARISONS[f.op](total, f.limit)
        if isinstance(f, Dead):
            return not counts
        if isinstance(f, Not):
            return not self.holds(f.operand, m, counts)
        if isinstance(f, And):
            return all(self.holds(g, m, counts) for g in f.operands)
        if isinstance(f, Or):
            return any(self.holds(g, m, counts) for g in f.operands)
        raise TypeError(f"not propositional: {f}")

    # Method to collect the transitions that can change a formula's truth.
    def flip(self, f: Formula, m: tuple, counts: Dict[int, int]
             ) -> Optional[FrozenSet[int]]:
        """An up-set: every path that changes the truth of ``f`` fires one of these.

        Computed from the current value: a conjunction that holds can be
        falsified through any conjunct, so their sets are united; one that
        does not hold needs *every* false conjunct to become true, so the
        smallest of their sets suffices. Disjunction is the dual.

        Args:
            f (Formula): A propositional formula.
            m (tuple): The marking.
            counts (dict): Enabled binding elements per transition.

        Returns:
            frozenset|None: The transitions, or None when the formula's truth
            can change through any transition (``dead``).
        """
        dep, sel = self.dep, self.ctx.select
        now = self.holds(f, m, counts)

        def union(places, rel):
            out: Set[int] = set()
            for p in places:
                out |= rel.get(p, frozenset())
            return frozenset(out)

        def smallest(sets):
            sets = list(sets)
            if any(s is None for s in sets):
                rest = [s for s in sets if s is not None]
                return min(rest, key=len) if rest else None
            return min(sets, key=len) if sets else frozenset()

        if isinstance(f, Marked):
            places = sel(f.selector)
            if not now:
                return union(places, dep.givers)
            return smallest(dep.takers.get(p, frozenset())
                            for p in places if m[p])
        if isinstance(f, AllMarked):
            places = sel(f.selector)
            if now:
                return union(places, dep.takers)
            return smallest(dep.givers.get(p, frozenset())
                            for p in places if not m[p])
        if isinstance(f, MaxTokens):
            places = sel(f.selector)
            if now:
                return union(places, dep.givers)
            return smallest(dep.takers.get(p, frozenset()) for p in places
                            if len(m[p]) > f.limit)
        if isinstance(f, TokensIn):
            places = sel(f.selector)
            if now:
                return union(places, dep.givers)
            return smallest(dep.takers.get(p, frozenset()) for p in places
                            if any(tok not in f.domain
                                   for tok in self.ctx.net.values_of(p, m[p])))
        if isinstance(f, Enabled):
            group = sel(f.selector)
            if not now:
                out: Set[int] = set()
                for t in group:
                    out |= dep.enablers(m, t)
                return frozenset(out)
            return smallest(union(dep.pre[t], dep.takers) for t in group
                            if counts.get(t, 0))
        if isinstance(f, EnabledCount):
            group = sel(f.selector)
            if now:
                # The count grows when a disabled member becomes enabled
                # (its enablers) or an enabled one gains a binding (a token
                # added to one of its input places).
                out = set()
                for t in group:
                    out |= (union(dep.pre[t], dep.givers) if counts.get(t, 0)
                            else dep.enablers(m, t))
                return frozenset(out)
            places = set().union(*[dep.pre[t] for t in group]) if group else set()
            return union(places, dep.takers)
        if isinstance(f, (TokenCount, Holds)):
            # Either direction: any transition adding to or taking from the
            # places can change a count or a token's presence.
            places = sel(f.selector)
            return union(places, dep.givers) | union(places, dep.takers)
        if isinstance(f, EnabledTally):
            group = sel(f.selector)
            places = set().union(*[dep.pre[t] for t in group]) if group else set()
            return union(places, dep.givers) | union(places, dep.takers)
        if isinstance(f, Dead):
            return None
        if isinstance(f, Not):
            return self.flip(f.operand, m, counts)
        if isinstance(f, (And, Or)):
            conj = isinstance(f, And)
            parts = [(g, self.holds(g, m, counts)) for g in f.operands]
            if now == conj:
                # And that holds / Or that fails: any operand can flip it.
                out = set()
                for g, _v in parts:
                    s = self.flip(g, m, counts)
                    if s is None:
                        return None
                    out |= s
                return frozenset(out)
            # And that fails / Or that holds: one operand stuck at the
            # deciding value has to flip, and any of them will do.
            return smallest(self.flip(g, m, counts) for g, v in parts
                            if v == (not conj))
        raise TypeError(f"not propositional: {f}")

    # Method to collect the places a formula looks at.
    def observed(self, f: Formula) -> Set[int]:
        """Places whose marking can change the truth of an atom of ``f``.

        For a place proposition that is the selected places; for an enabling
        proposition, the input places of the selected transitions.

        Args:
            f (Formula): Any formula without ``dead``.

        Returns:
            set: Place indices.
        """
        if isinstance(f, _PLACE_ATOMS):
            return set(self.ctx.select(f.selector))
        if isinstance(f, _TRANSITION_ATOMS):
            out: Set[int] = set()
            for t in self.ctx.select(f.selector):
                out |= self.dep.pre[t]
            return out
        if isinstance(f, ForEach):
            out = set()
            for _label, g in f.instances(self.ctx):
                out |= self.observed(g)
            return out
        out = set()
        for g in _children(f):
            out |= self.observed(g)
        return out


# ---------------------------------------------------------------------------
# Choosing the stubborn set at one marking
# ---------------------------------------------------------------------------

# Class choosing the stubborn set of one marking.
class _Chooser:
    """Per-marking choice of the transitions to expand.

    Closures of single transitions are memoised for the marking at hand, and a
    candidate is the union of the closures of its seeds.
    """

    # Method to set up the choice at one marking.
    def __init__(self, dep: Dependency, marking: tuple,
                 counts: Dict[int, int]):
        """Prepare the choice.

        Args:
            dep (Dependency): The relations.
            marking (tuple): The marking.
            counts (dict): Enabled binding elements per transition.
        """
        self.dep = dep
        self.m = marking
        self.counts = counts
        self.enabled = set(counts)
        self._memo: Dict[int, Set[int]] = {}

    # Method to close one transition.
    def closure_of(self, t: int) -> Set[int]:
        """The stubborn closure of ``{t}``, memoised.

        Args:
            t (int): Transition.

        Returns:
            set: The closure.
        """
        c = self._memo.get(t)
        if c is None:
            c = self._memo[t] = self.dep.closure((t,), self.m, self.enabled)
        return c

    # Method to count the binding elements a set would expand.
    def size(self, s: Set[int]) -> int:
        """Number of enabled binding elements in a transition set.

        Args:
            s (set): Transitions.

        Returns:
            int: Binding elements.
        """
        return sum(self.counts.get(t, 0) for t in s)

    # Method to pick the smallest stubborn set containing some transitions.
    def smallest(self, required: Iterable[int] = ()) -> Set[int]:
        """The smallest candidate that contains ``required`` and a key.

        Args:
            required (iterable): Transitions the set must contain (an up-set).

        Returns:
            set: The transitions whose enabled bindings are expanded.
        """
        base: Set[int] = set()
        for t in required:
            base |= self.closure_of(t)
        if self.size(base):
            # Adding seeds only grows a set that already has a key.
            return base
        best: Optional[Set[int]] = base if self.size(base) else None
        for t in sorted(self.enabled):
            if t in base:
                continue
            cand = base | self.closure_of(t)
            n = self.size(cand)
            if best is None or n < self.size(best):
                best = cand
                if n == 1:
                    break
        return best if best is not None else set(self.enabled)

    # Method to pick an ample set of one invisible binding element.
    def singleton(self, visible: FrozenSet[int]) -> Optional[int]:
        """An enabled transition whose closure expands one invisible element.

        Args:
            visible (frozenset): The visible transitions.

        Returns:
            int|None: The transition, or None when there is none.
        """
        for t in sorted(self.enabled):
            if t in visible or self.counts[t] != 1:
                continue
            c = self.closure_of(t)
            if self.size(c) == 1:
                return t
        return None


# ---------------------------------------------------------------------------
# Building a reduced graph
# ---------------------------------------------------------------------------

# Function to enumerate the enabled binding elements of a marking.
def _enabled(net: ColouredNet, dep: Dependency, marking: tuple,
             previous: Optional[List[Tuple[int, tuple, dict]]] = None,
             fired: Optional[int] = None) -> List[Tuple[int, tuple, dict]]:
    """Enabled binding elements, reusing those of the predecessor.

    The bindings of a transition depend only on the tokens of its input
    places, so after an occurrence of ``fired`` only the transitions needing a
    place it changed have to be enumerated again.

    Args:
        net (ColouredNet): The net.
        dep (Dependency): Its relations.
        marking (tuple): The marking.
        previous (list, optional): Enabled elements of the predecessor.
        fired (int, optional): The transition leading here from it.

    Returns:
        list: ``(transition, binding key, binding)`` triples, sorted by
        transition.
    """
    if previous is None or fired is None:
        return net.enabled(marking)
    stale: Set[int] = set()
    for p in dep.changes[fired]:
        stale |= dep.users.get(p, frozenset())
    kept = [e for e in previous if e[0] not in stale]
    fresh = []
    for ti in stale:
        t = net.transitions[ti]
        if any(len(marking[p]) < k for p, k in t["needs"].items()):
            continue
        for env, _ready in net._bindings(marking, t):
            fresh.append((ti, tuple(sorted(env.items())), env))
    out = kept + fresh
    out.sort(key=lambda e: e[0])
    return out


# Function to explore the reduced occurrence graph of one kind.
def build_reduced(net: ColouredNet, dep: Dependency, kind: str,
                  atoms: Optional[_Atoms] = None,
                  invariant: Optional[Formula] = None,
                  visible: FrozenSet[int] = frozenset(),
                  initial: Optional[tuple] = None,
                  max_nodes: int = DEFAULT_MAX_NODES,
                  cache: Optional[Dict[tuple, list]] = None) -> StateSpace:
    """Explore the markings a stubborn-set search reaches.

    ``deadlock`` and ``safety`` graphs are searched breadth-first, so their
    counterexamples are short; ``stutter`` graphs depth-first, because the
    cycle proviso C3 is stated in terms of the search stack.

    Args:
        net (ColouredNet): The net.
        dep (Dependency): Its relations.
        kind (str): ``deadlock``, ``safety`` or ``stutter``.
        atoms (_Atoms, optional): Proposition evaluator (``safety``).
        invariant (Formula, optional): The invariant ``psi`` whose violation
            is the goal (``safety``).
        visible (frozenset): Visible transitions (``stutter``).
        initial (tuple, optional): Start marking.
        max_nodes (int): Budget.
        cache (dict, optional): Enabled binding elements per marking, shared
            between the graphs of one initial marking, which mostly visit the
            same markings in different orders.

    Returns:
        StateSpace: The reduced graph; ``enabled`` holds, per node, every
        enabled transition (one entry per binding), not only the expanded ones.
    """
    if kind not in ("deadlock", "safety", "stutter"):
        raise ValueError(f"unknown reduction kind {kind!r}")
    t0 = time.perf_counter()
    start = net.initial if initial is None else initial
    nodes = {start: 0}
    markings = [start]
    succ: List[List[Tuple[int, tuple, int]]] = [[]]
    parent: List[Optional[Tuple[int, int, tuple]]] = [None]
    enabled_rec: List[Tuple[int, ...]] = [()]
    pending: Dict[int, Tuple[Optional[list], Optional[int]]] = {0: (None, None)}
    complete = True
    expanded_fully = 0

    # Function to compute the binding elements expanded at one node.
    def expand(v, on_stack=None):
        nonlocal expanded_fully
        prev, fired = pending.pop(v)
        m = markings[v]
        en = cache.get(m) if cache is not None else None
        if en is None:
            en = _enabled(net, dep, m, prev, fired)
            if cache is not None and len(cache) < _CACHE_LIMIT:
                cache[m] = en
        enabled_rec[v] = tuple(e[0] for e in en)
        if not en:
            return en, []
        counts = collections.Counter(e[0] for e in en)
        chooser = _Chooser(dep, m, counts)
        chosen: Optional[Set[int]] = None
        if kind == "deadlock":
            chosen = chooser.smallest()
        elif kind == "safety":
            required: Iterable[int] = ()
            if atoms.holds(invariant, m, counts):
                up = atoms.flip(invariant, m, counts)
                required = up if up is not None else set(counts)
            chosen = chooser.smallest(required)
        else:
            t = chooser.singleton(visible)
            if t is not None:
                ti, key, env = next(e for e in en if e[0] == t)
                nxt = net.fire(m, ti, env)
                dst = nodes.get(nxt)
                if dst is None or not on_stack[dst]:
                    chosen = {t}
        if chosen is None or chooser.size(chosen) == len(en):
            expanded_fully += 1
            return en, en
        return en, [e for e in en if e[0] in chosen]

    # Function to add the successor of an occurrence, if new.
    def visit(src, en, ti, key, env):
        nonlocal complete
        nxt = net.fire(markings[src], ti, env)
        dst = nodes.get(nxt)
        new = False
        if dst is None:
            if len(markings) >= max_nodes:
                complete = False
                return None, False
            dst = len(markings)
            nodes[nxt] = dst
            markings.append(nxt)
            succ.append([])
            parent.append((src, ti, key))
            enabled_rec.append(())
            pending[dst] = (en, ti)
            new = True
        succ[src].append((ti, key, dst))
        return dst, new

    if kind in ("deadlock", "safety"):
        queue = collections.deque([0])
        while queue:
            v = queue.popleft()
            en, chosen = expand(v)
            for ti, key, env in chosen:
                dst, new = visit(v, en, ti, key, env)
                if new:
                    queue.append(dst)
    else:
        on_stack = [False]
        on_stack[0] = True
        en, chosen = expand(0, on_stack)
        stack = [(0, en, iter(chosen))]
        while stack:
            v, en, it = stack[-1]
            step = next(it, None)
            if step is None:
                on_stack[v] = False
                stack.pop()
                continue
            ti, key, env = step
            dst, new = visit(v, en, ti, key, env)
            if new:
                on_stack.append(True)
                en2, chosen2 = expand(dst, on_stack)
                stack.append((dst, en2, iter(chosen2)))
    # Nodes left unexpanded when the budget ran out keep an empty record.
    for v in list(pending):
        pending.pop(v)
    ss = StateSpace(net, markings, succ, complete, time.perf_counter() - t0,
                    parent, enabled=enabled_rec, reduction=kind)
    ss.fully_expanded = expanded_fully
    return ss


# ---------------------------------------------------------------------------
# Deciding which graph a formula needs
# ---------------------------------------------------------------------------

# Function to recognise "dead -> psi" with psi free of dead.
def _dead_guarded(f: Formula) -> bool:
    """Whether ``f`` is ``!dead | psi`` with ``psi`` not mentioning dead.

    Args:
        f (Formula): A propositional formula.

    Returns:
        bool: True for that shape.
    """
    if isinstance(f, Not) and isinstance(f.operand, Dead):
        return True                              # AG !dead: no dead marking
    if not isinstance(f, Or):
        return False
    guards = [g for g in f.operands
              if isinstance(g, Not) and isinstance(g.operand, Dead)]
    rest = [g for g in f.operands if g not in guards]
    return len(guards) >= 1 and not any(mentions_dead(g) for g in rest)


# Function to recognise "dead & chi" with chi free of dead.
def _dead_conjoined(f: Formula) -> bool:
    """Whether ``f`` is ``dead & chi`` with ``chi`` not mentioning dead.

    Args:
        f (Formula): A propositional formula.

    Returns:
        bool: True for that shape.
    """
    if isinstance(f, Dead):
        return True
    if not isinstance(f, And):
        return False
    deads = [g for g in f.operands if isinstance(g, Dead)]
    rest = [g for g in f.operands if not isinstance(g, Dead)]
    return len(deads) >= 1 and not any(mentions_dead(g) for g in rest)


# Function to choose the graph kind a formula can be decided on.
def classify(f: Formula) -> Tuple[str, Optional[Formula]]:
    """The least-explored graph whose verdict on ``f`` equals the full one's.

    Args:
        f (Formula): One part, as produced by :func:`split`.

    Returns:
        tuple: ``(kind, invariant)``; the invariant is the ``psi`` whose
        violation the ``safety`` search looks for, else None.
    """
    if isinstance(f, AF) and isinstance(f.operand, Dead) \
            and f.semantics != "askctl":
        return "deadlock", None
    if isinstance(f, AG) and propositional(f.operand):
        psi = f.operand
        if not mentions_dead(psi):
            return "safety", psi
        if _dead_guarded(psi):
            return "deadlock", None
        return "full", None
    if isinstance(f, Not) and isinstance(f.operand, EF) \
            and propositional(f.operand.operand):
        chi = f.operand.operand
        if not mentions_dead(chi):
            return "safety", Not(chi)
        if _dead_conjoined(chi):
            return "deadlock", None
        return "full", None
    if isinstance(f, EF) and propositional(f.operand):
        chi = f.operand
        if not mentions_dead(chi):
            return "safety", Not(chi)
        if _dead_conjoined(chi):
            return "deadlock", None
        return "full", None
    if not mentions_dead(f):
        return "stutter", None
    return "full", None


# Function to cut a formula into parts that can be decided separately.
def split(f: Formula, ctx: Context) -> List[Tuple[Optional[str], Formula]]:
    """Independent parts whose conjunction is ``f``.

    ``forall g: phi(g)`` is the conjunction of its instances; ``AG`` commutes
    with conjunction; a bound on a set of places is the conjunction of the
    bounds on each place. A part observes fewer places than the whole, so it
    has fewer visible transitions and a smaller up-set.

    Args:
        f (Formula): The formula.
        ctx (Context): A static context, to resolve groups and selectors.

    Returns:
        list: ``(label, part)`` pairs; the label names the group member a part
        came from, for counterexamples.
    """
    if isinstance(f, ForEach):
        out = []
        for label, inst in f.instances(ctx):
            for sub, g in split(inst, ctx):
                out.append((label if sub is None else f"{label}/{sub}", g))
        return out
    if isinstance(f, And):
        return [pair for g in f.operands for pair in split(g, ctx)]
    if isinstance(f, AG):
        inner = f.operand
        if isinstance(inner, And):
            return [pair for g in inner.operands
                    for pair in split(AG(g, note=f.note), ctx)]
        if isinstance(inner, (MaxTokens, TokensIn)):
            places = ctx.select(inner.selector)
            if len(places) > 1:
                out = []
                for p in places:
                    one = Explicit([p], "place", ctx.net.places[p]["name"])
                    atom = (MaxTokens(one, inner.limit, note=inner.note)
                            if isinstance(inner, MaxTokens)
                            else TokensIn(one, inner.domain, note=inner.note))
                    out.append((None, AG(atom, note=f.note)))
                return out
    return [(None, f)]


# ---------------------------------------------------------------------------
# Deciding formulas on reduced graphs
# ---------------------------------------------------------------------------

# Class recording how one property was decided.
class Plan:
    """The parts of a property and the graph each was decided on.

    Attributes:
        parts (list): ``(label, formula, kind)`` triples.
        reasons (list): Why parts got no verdict, if any did not.
    """

    # Method to hold the parts.
    def __init__(self, parts, reasons=None):
        """Create the plan.

        Args:
            parts (list): ``(label, formula, kind)`` triples.
            reasons (list, optional): Explanations for parts without verdict.
        """
        self.parts = parts
        self.reasons = list(reasons or [])

    # Method to summarise the kinds used.
    def summary(self) -> str:
        """``safety x12, stutter x1``.

        Returns:
            str: Kinds and how many parts used each.
        """
        counts = collections.Counter(kind for _l, _f, kind in self.parts)
        return ", ".join(f"{k} x{counts[k]}" if counts[k] > 1 else k
                         for k in KINDS if counts.get(k))


# Class deciding formulas on stubborn-set reduced graphs, with a graph cache.
class ReducedChecker:
    """Decides formulas for one initial marking, building graphs as needed.

    Attributes:
        net (ColouredNet): The net.
        dep (Dependency): Its relations.
        groups (dict): Resolved groups.
        initial (tuple): The initial marking.
        max_nodes (int): Budget per graph.
        graphs (dict): Graph cache, keyed by kind and its parameters.
    """

    # Method to set up the checker for one initial marking.
    def __init__(self, net: ColouredNet, dep: Dependency, groups=None,
                 initial: Optional[tuple] = None,
                 max_nodes: int = DEFAULT_MAX_NODES):
        """Create the checker.

        Args:
            net (ColouredNet): The net.
            dep (Dependency): Its relations.
            groups (dict, optional): Resolved groups.
            initial (tuple, optional): Start marking.
            max_nodes (int): Budget per graph.
        """
        self.net = net
        self.dep = dep
        self.groups = groups or {}
        self.initial = initial
        self.max_nodes = max_nodes
        self.static = Context.static(net, self.groups)
        self.atoms = _Atoms(self.static, dep)
        self.graphs: Dict[Any, StateSpace] = {}
        self._enabled_cache: Dict[tuple, list] = {}

    # Method to obtain (building if needed) one graph.
    def graph(self, kind: str, invariant: Optional[Formula] = None,
              visible: FrozenSet[int] = frozenset()) -> StateSpace:
        """The graph of a kind, built once per distinct parameter.

        Args:
            kind (str): A member of :data:`KINDS`.
            invariant (Formula, optional): For ``safety``.
            visible (frozenset): For ``stutter``.

        Returns:
            StateSpace: The graph.
        """
        if not getattr(self.net, "reducible", True):
            # A global clock or priorities: no reduced graph is sound, so
            # every request, whatever its kind, gets the full graph.
            kind, invariant, visible = "full", None, frozenset()
        if kind == "safety":
            key = ("safety", str(invariant), id(invariant))
        elif kind == "stutter":
            key = ("stutter", visible)
        else:
            key = (kind,)
        ss = self.graphs.get(key)
        if ss is None:
            if kind == "full":
                ss = build_state_space(self.net, self.max_nodes,
                                       initial=self.initial)
            else:
                ss = build_reduced(self.net, self.dep, kind, atoms=self.atoms,
                                   invariant=invariant, visible=visible,
                                   initial=self.initial,
                                   max_nodes=self.max_nodes,
                                   cache=self._enabled_cache)
            self.graphs[key] = ss
            # The invariant is part of the key by identity; keep it alive.
            ss.invariant = invariant
            ss.visible = visible
        return ss

    # Method to name the graph a part is decided on.
    def graph_for(self, part: Formula) -> Tuple[str, StateSpace]:
        """Classify a part and return its graph.

        Args:
            part (Formula): One part.

        Returns:
            tuple: ``(kind, graph)``.
        """
        kind, invariant = classify(part)
        if not getattr(self.net, "reducible", True):
            # A global clock or priorities make transitions depend on each
            # other in ways the arcs do not show: no reduction is sound.
            kind, invariant = "full", None
        visible: FrozenSet[int] = frozenset()
        if kind == "stutter":
            visible = self.dep.touching(self.atoms.observed(part))
        return kind, self.graph(kind, invariant, visible)

    # Method to decide one formula.
    def decide(self, formula: Formula):
        """Verdict of ``formula`` at the initial marking.

        Args:
            formula (Formula): A property.

        Returns:
            tuple: ``(holds or None, counterexample or None, Plan)``. None
            means some part's graph exceeded the budget and no part failed.
        """
        parts = split(formula, self.static)
        plan = []
        unknown = False
        reasons: List[str] = []
        for label, part in parts:
            kind, ss = self.graph_for(part)
            plan.append((label, part, kind))
            if not ss.complete:
                unknown = True
                reasons.append(self._over_budget(label, kind, ss))
                continue
            ctx = Context(ss, self.net, self.groups)
            if 0 in ctx.sat(part):
                continue
            cex = part.counterexample(ctx)
            if label is not None:
                cex.note = f"{label}: {cex.note}"
                cex.data["group_member"] = label
            cex.data["reduction"] = kind
            return False, cex, Plan(plan)
        return (None if unknown else True), None, Plan(plan, reasons)

    # Method to explain why a reduced graph did not fit the budget.
    def _over_budget(self, label: Optional[str], kind: str,
                     ss: StateSpace) -> str:
        """Say why a part got no verdict.

        A ``stutter`` graph cannot reorder the transitions its propositions
        observe; when nearly all of them are visible the reduced graph is
        nearly the full one, and that is the usual cause.

        Args:
            label (str, optional): The group member.
            kind (str): The graph kind.
            ss (StateSpace): The incomplete graph.

        Returns:
            str: The explanation.
        """
        head = f"{label}: " if label else ""
        text = f"{head}{kind} graph exceeded {self.max_nodes} markings"
        visible = getattr(ss, "visible", None)
        if kind == "stutter" and visible:
            text += (f"; {len(visible)} of {len(self.net.transitions)} "
                     "transitions change what the property observes and "
                     "cannot be reordered")
        return text

    # Method to decide termination and the home-marking property together.
    def terminating(self) -> Optional[bool]:
        """Whether every occurrence sequence is finite.

        The deadlock graph has a cycle exactly when the full graph has an
        infinite occurrence sequence, so this is read off the reduced graph.

        Returns:
            bool|None: The answer, or None over budget.
        """
        ss = self.graph("deadlock")
        if not ss.complete:
            return None
        return all(len(c) == 1 for c in _components(ss)) and \
            not any(dst == src for src, out in enumerate(ss.succ)
                    for _t, _k, dst in out)

    # Method to report the graphs built.
    def stats(self) -> Dict[str, Any]:
        """Sizes of the reduced graphs.

        Returns:
            dict: Counts per kind, total and largest node counts.
        """
        per_kind = collections.Counter(k[0] for k in self.graphs)
        sizes = [ss.n_nodes for ss in self.graphs.values()]
        return {"graphs": len(self.graphs), "per_kind": dict(per_kind),
                "nodes_total": sum(sizes), "nodes_max": max(sizes or [0]),
                "complete": all(ss.complete for ss in self.graphs.values())}


# Function to group a graph's nodes by SCC.
def _components(ss: StateSpace) -> List[List[int]]:
    """Nodes per strongly connected component.

    Args:
        ss (StateSpace): The graph.

    Returns:
        list: One node list per component.
    """
    comps: Dict[int, List[int]] = collections.defaultdict(list)
    for v, c in enumerate(ss.scc):
        comps[c].append(v)
    return list(comps.values())
