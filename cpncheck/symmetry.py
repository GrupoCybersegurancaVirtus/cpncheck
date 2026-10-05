"""Symmetry reduction: markings equal up to a permutation of colours.

Many nets treat the values of a colour set alike: every philosopher behaves
the same, and so does every site of a database. Renaming them maps a
reachable marking to a reachable marking with the same behaviour. A
*symmetry specification* names the colour sets that may be permuted and how
(all permutations, or rotations only); the quotient explored has one marking
per orbit (:mod:`cpncheck.equivalence`).

Colour sets whose values are related -- philosopher ``ph(i)`` holds
chopsticks ``cs(i)`` and ``cs(i+1)`` -- must be permuted *together*, by
position: ``{"PH,CS": "rotation"}`` rotates both at once.

**Admissibility is checked, not assumed** (the conditions of Jensen &
Kristensen, ch. 8): the initial marking must be invariant under every
generator, and for each explored marking ``M`` and generator ``g`` the
successors of ``g(M)`` must be exactly the images of those of ``M``. A net
whose guards or arc functions break the symmetry fails this test, and its
verdicts are withheld. The test covers the markings explored, which is the
state space the verdicts are about; it is not a proof for other initial
markings.

**What is preserved:** every CTL property whose propositions do not single
out permuted values -- token counts, enabledness and deadness are kept;
``has(P, ph(1))`` is not (it is reported without a verdict). The home-marking
property and the statistics are not preserved.
"""

import collections
import itertools
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from .coloured import ColouredNet
from .cpnml import TimedToken
from .equivalence import Equivalence, EquivalenceError
from .formula import Formula, Holds, TokensIn

__all__ = ["symmetry_equivalence", "parse_symmetry", "SymmetryError",
           "MAX_GROUP"]

#: Largest group enumerated to find the canonical representative.
MAX_GROUP = 40_320


# Class signalling an unusable symmetry specification.
class SymmetryError(EquivalenceError):
    """A symmetry specification that does not apply to the net."""


# Function to read a symmetry specification from text.
def parse_symmetry(spec: Union[str, Sequence[str], Dict[str, str]]
                   ) -> Dict[Tuple[str, ...], str]:
    """``"PH,CS=rotation"`` (repeatable) as ``{("PH", "CS"): "rotation"}``.

    Args:
        spec: A dict, a string, or a sequence of strings ``SETS=KIND`` where
            ``SETS`` is a comma-separated list of colour sets permuted
            together and ``KIND`` is ``all`` or ``rotation`` (default
            ``all``).

    Returns:
        dict: Colour-set groups to their kind.

    Raises:
        SymmetryError: On an unknown kind or an empty specification.
    """
    if isinstance(spec, dict):
        items = list(spec.items())
    else:
        texts = [spec] if isinstance(spec, str) else list(spec)
        items = []
        for text in texts:
            for chunk in text.split(";"):
                if not chunk.strip():
                    continue
                sets, _, kind = chunk.partition("=")
                items.append((sets, kind or "all"))
    out: Dict[Tuple[str, ...], str] = {}
    for sets, kind in items:
        names = tuple(s.strip() for s in
                      (sets.split(",") if isinstance(sets, str) else sets)
                      if s.strip())
        kind = kind.strip().lower()
        if kind not in ("all", "rotation"):
            raise SymmetryError(f"symmetry kind must be 'all' or 'rotation', "
                                f"not {kind!r}")
        if not names:
            raise SymmetryError("a symmetry names no colour set")
        out[names] = kind
    if not out:
        raise SymmetryError("empty symmetry specification")
    return out


# Function to resolve a colour set to its declaration.
def _colset(net: ColouredNet, name: str):
    """The colour set declaration, through aliases.

    Args:
        net (ColouredNet): The net.
        name (str): A colour set name.

    Returns:
        ColourSet|None: The declaration.
    """
    sets = net.declarations.colsets
    seen = set()
    cs = sets.get(name)
    while cs is not None and cs.kind == "alias" and cs.name not in seen:
        seen.add(cs.name)
        cs = sets.get(cs.base)
    return cs


# Function to build the value maps of a symmetry group.
def _group(net: ColouredNet, spec: Dict[Tuple[str, ...], str]
           ) -> Tuple[List[Dict[str, Dict[Any, Any]]], List[Dict[str, Dict[Any, Any]]]]:
    """Every element of the group, and its generators, as value maps.

    Args:
        net (ColouredNet): The net.
        spec (dict): The parsed specification.

    Returns:
        tuple: ``(elements, generators)``; each is a ``{colour set: {value:
        image}}`` map.

    Raises:
        SymmetryError: When a colour set is unknown, infinite, or the group
            is too large to enumerate.
    """
    factors = []           # per spec entry: list of {colset: mapping}
    generators = []
    for names, kind in spec.items():
        domains = []
        for name in names:
            cs = _colset(net, name)
            if cs is None:
                known = ", ".join(sorted(net.declarations.colsets)[:30])
                raise SymmetryError(f"no colour set named {name!r}; the colour "
                                    f"sets are: {known}")
            values = cs.domain(net.declarations.colsets)
            if not values:
                raise SymmetryError(f"colour set {name} has no finite list of "
                                    "values to permute")
            domains.append((name, list(values)))
        size = len(domains[0][1])
        if any(len(v) != size for _n, v in domains):
            raise SymmetryError(f"{', '.join(names)} are permuted together by "
                                "position, so they need the same number of "
                                "values")
        if kind == "rotation":
            orders = [tuple((i + k) % size for i in range(size))
                      for k in range(size)]
            gens = [tuple((i + 1) % size for i in range(size))] if size > 1 else []
        else:
            orders = list(itertools.permutations(range(size)))
            gens = []
            if size > 1:
                gens.append(tuple([1, 0] + list(range(2, size))))
                gens.append(tuple((i + 1) % size for i in range(size)))
        to_map = (lambda order, d=domains:
                  {n: {v[i]: v[order[i]] for i in range(len(v))} for n, v in d})
        factors.append([to_map(o) for o in orders])
        generators.extend(to_map(g) for g in gens)
    total = 1
    for f in factors:
        total *= len(f)
    if total > MAX_GROUP:
        raise SymmetryError(f"the symmetry group has {total} elements; at most "
                            f"{MAX_GROUP} are enumerated (use rotation, or "
                            "fewer colour sets)")
    elements = []
    for combo in itertools.product(*factors):
        merged: Dict[str, Dict[Any, Any]] = {}
        for part in combo:
            merged.update(part)
        elements.append(merged)
    return elements, generators


# Function to build the function applying a value map to one colour set.
def _applier(net: ColouredNet, colset_name: Optional[str], permuted: set,
             generators: Sequence[Dict[str, Dict[Any, Any]]] = ()
             ) -> Optional[Callable[[Any, Dict[str, Dict[Any, Any]]], Any]]:
    """How a permutation acts on a value of a colour set.

    Args:
        net (ColouredNet): The net.
        colset_name (str): The place's colour set.
        permuted (set): Names of the permuted colour sets.
        generators (sequence): The group's generators, to check that a
            subset of a permuted colour set is closed under them.

    Returns:
        callable|None: ``apply(value, maps)``, or None when no permuted
        colour occurs in the colour set.

    Raises:
        SymmetryError: For a subset of a permuted colour set that a
            permutation can leave.
    """
    sets = net.declarations.colsets

    def build(name, seen):
        if name in permuted:
            return lambda v, maps, n=name: maps[n].get(v, v) if n in maps else v
        cs = sets.get(name)
        if cs is None or name in seen:
            return None
        seen = seen | {name}
        if cs.kind == "alias":
            if cs.base in permuted:
                return lambda v, maps, n=cs.base: maps[n].get(v, v) if n in maps else v
            return build(cs.base, seen)
        if cs.kind == "subset":
            inner = build(cs.base, seen)
            if inner is None:
                return None
            values = cs.domain(sets)
            if values is None:
                raise SymmetryError(f"colour set {name} is a subset of a "
                                    "permuted colour set whose members are "
                                    "not known")
            members = set(values)
            for g in generators:
                if {inner(v, g) for v in members} != members:
                    raise SymmetryError(
                        f"colour set {name} is a subset of a permuted colour "
                        f"set that {_describe(g)} does not map onto itself")
            return inner
        if cs.kind in ("product", "record"):
            parts = [build(p, seen) for p in cs.parts]
            if all(p is None for p in parts):
                return None
            return lambda v, maps, ps=parts: tuple(
                x if f is None else f(x, maps) for f, x in zip(ps, v))
        if cs.kind == "list":
            inner = build(cs.base, seen)
            if inner is None:
                return None
            return lambda v, maps, f=inner: tuple(f(x, maps) for x in v)
        return None

    return build(colset_name, frozenset()) if colset_name else None


# Function to build a symmetry equivalence.
def symmetry_equivalence(net: ColouredNet,
                         spec: Union[str, Sequence[str], Dict[str, str]],
                         initial: Optional[tuple] = None) -> Equivalence:
    """The equivalence of markings in one orbit of a symmetry group.

    Args:
        net (ColouredNet): The net.
        spec: The symmetry specification (see :func:`parse_symmetry`).
        initial (tuple, optional): The initial marking it must preserve.

    Returns:
        Equivalence: With the admissibility test among its checks.

    Raises:
        SymmetryError: When the specification does not apply, or the initial
            marking is not symmetric.
    """
    parsed = parse_symmetry(spec)
    permuted = {n for names in parsed for n in names}
    elements, generators = _group(net, parsed)
    appliers = [_applier(net, p.get("colset"), permuted, generators)
                for p in net.places]
    if all(a is None for a in appliers):
        raise SymmetryError("no place holds a value of "
                            f"{', '.join(sorted(permuted))}")
    timed = net.timed_places
    moving = [i for i, a in enumerate(appliers) if a is not None]

    def image(marking: tuple, maps) -> tuple:
        out = list(marking)
        for i in moving:
            f = appliers[i]
            if i in timed:
                out[i] = tuple(sorted(TimedToken(f(tok[0], maps), tok[1])
                                      for tok in marking[i]))
            else:
                out[i] = tuple(sorted(f(tok, maps) for tok in marking[i]))
        return tuple(out)

    def canonical(marking: tuple) -> tuple:
        best = marking
        best_key = repr(marking)
        for maps in elements:
            m = image(marking, maps)
            key = repr(m)
            if key < best_key:
                best, best_key = m, key
        return best

    start = net.initial if initial is None else initial
    for g in generators:
        if image(start, g) != start:
            raise SymmetryError("the initial marking is not symmetric under "
                                f"{_describe(g)}, so the symmetry is not "
                                "admitted by the net")

    def admissible(_net, marking):
        mine = collections.Counter(net.fire(marking, ti, env)
                                   for ti, _k, env in net.enabled(marking))
        for g in generators:
            moved = image(marking, g)
            theirs = collections.Counter(net.fire(moved, ti, env)
                                         for ti, _k, env in net.enabled(moved))
            if collections.Counter({image(m, g): n for m, n in mine.items()}) \
                    != theirs:
                return (f"the successors of a marking moved by {_describe(g)} "
                        "are not the moved successors: a guard or an arc "
                        "inscription breaks the symmetry")
        return None

    def observes(formula: Formula) -> Optional[str]:
        for atom in _atoms(formula):
            if isinstance(atom, Holds):
                for pidx in _selected(net, atom.selector):
                    f = appliers[pidx]
                    if f is not None and any(f(atom.value, g) != atom.value
                                             for g in generators):
                        return (f"it singles out the value {atom.value!r}, "
                                "which the symmetry moves")
            if isinstance(atom, TokensIn):
                for pidx in _selected(net, atom.selector):
                    f = appliers[pidx]
                    if f is not None and any(
                            {f(v, g) for v in atom.domain} != set(atom.domain)
                            for g in generators):
                        return "its set of values is not closed under the symmetry"
        return None

    kinds = "; ".join(f"{','.join(n)}: {k}" for n, k in parsed.items())
    return Equivalence(
        f"symmetry ({kinds})", canonical, exact=False,
        note=(f"group of {len(elements)} permutations; the initial marking is "
              "symmetric and every generator was tested on the explored "
              "markings"),
        observes=observes, checks=[admissible])


# Function to describe a generator.
def _describe(maps: Dict[str, Dict[Any, Any]]) -> str:
    """A generator, as text.

    Args:
        maps (dict): ``{colour set: {value: image}}``.

    Returns:
        str: For messages.
    """
    parts = []
    for name, mapping in maps.items():
        moved = [f"{k}->{v}" for k, v in mapping.items() if k != v]
        parts.append(f"{name}: {', '.join(moved[:4])}"
                     f"{' ...' if len(moved) > 4 else ''}")
    return "; ".join(parts)


# Function to list the atomic propositions of a formula.
def _atoms(f: Formula) -> List[Formula]:
    """Every atom of a formula, through every operator.

    Args:
        f (Formula): The formula.

    Returns:
        list: The atoms.
    """
    from .reduction import _ATOMS, _children

    if isinstance(f, _ATOMS):
        return [f]
    out: List[Formula] = []
    for g in _children(f):
        out.extend(_atoms(g))
    return out


# Function to resolve a selector to place indices.
def _selected(net: ColouredNet, selector) -> Sequence[int]:
    """The places a selector picks.

    Args:
        net (ColouredNet): The net.
        selector: A selector.

    Returns:
        sequence: Place indices.
    """
    try:
        return selector.resolve(net)
    except Exception:                                      # noqa: BLE001
        return range(len(net.places))
