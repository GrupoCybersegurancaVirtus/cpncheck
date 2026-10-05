"""The flattened net: what it means, and how it fires.

:class:`ColouredNet` fuses the page hierarchy read by
:class:`cpncheck.net.CPNNet` into one place/transition net, compiles every
guard and inscription with the CPN ML front end (:mod:`cpncheck.cpnml`), and
enumerates and fires the binding elements enabled in a marking.

Binding elements
----------------
A transition's variables come from two places. Most are bound by matching its
input-arc patterns against the tokens available -- that is the cheap half, and
the only half a generated net needs. The rest are *free*: a variable the guard
or an output arc mentions and no input arc binds. CPN Tools finds those by
running through the variable's colour set, and so does this: the declared
colour set gives the domain, and every combination is tried. A free variable
whose colour set is infinite makes the net unexplorable, and it is refused
rather than silently ignored.

Values
------
Tokens are Python values, chosen so a marking is hashable and orderable: a
record is a tuple in declared field order, a list is a tuple, unit is the empty
tuple. Two markings are the same node exactly when they are equal.
"""

import collections
import itertools
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .colourset import Declarations
from .cpnml import (MLError, Parser, compile_expression, free_variables,
                    match_pattern, parse_expression, parse_multiset,
                    pattern_variables, tokenize)
from .net import CPNNet

__all__ = ["UnsupportedNet", "ColouredNet"]

#: How many binding elements one transition may have before giving up.
MAX_BINDINGS = 100_000


# Exception raised when a net uses CPN ML outside the supported fragment.
class UnsupportedNet(Exception):
    """The net uses a construct the state-space generator does not implement."""


# Function to put a token value in canonical, hashable form.
def _canon(value):
    """Convert lists to tuples recursively so tokens are hashable and ordered.

    Args:
        value: A token value.

    Returns:
        The canonical value.
    """
    if isinstance(value, list):
        return tuple(_canon(v) for v in value)
    if isinstance(value, tuple):
        return tuple(_canon(v) for v in value)
    return value


# Function to parse a multiset of patterns, as an input arc carries.
def parse_pattern_multiset(text: str) -> List[Tuple[int, Any]]:
    """Parse ``2`x ++ 1`(a, b)`` into counted patterns.

    An input arc consumes a multiset, so a coefficient means "this many
    tokens, each matching the pattern". The coefficient has to be a literal:
    a variable number of tokens would have to be solved for, not matched.

    Args:
        text (str): The inscription.

    Returns:
        list: ``(count, pattern)`` pairs.

    Raises:
        UnsupportedNet: On a syntax error or a non-literal coefficient.
    """
    try:
        parser = Parser(tokenize(text or ""), text or "")
        if parser.peek()[0] == "end":
            raise MLError("an input arc needs an inscription")
        terms = []
        while True:
            count = 1
            token = parser.peek()
            following = (parser.tokens[parser.pos + 1][:2]
                         if parser.pos + 1 < len(parser.tokens) else (None, None))
            if token[0] == "int" and following == ("op", "`"):
                count = parser.next()[1]
                parser.next()
            elif token[0] not in ("int", "real", "str") and following == \
                    ("op", "`"):
                raise MLError("an input arc needs a literal coefficient")
            terms.append((count, parser.pattern()))
            if not parser.accept("op", "++"):
                break
        if parser.peek()[0] != "end":
            raise MLError(f"unexpected {parser.peek()[1]!r}")
        return terms
    except MLError as exc:
        raise UnsupportedNet(f"input arc {(text or '').strip()!r}: {exc}")


# ---------------------------------------------------------------------------
# The flattened net
# ---------------------------------------------------------------------------

# Class holding a hierarchy-free view of a net, ready to fire.
class ColouredNet:
    """A flattened Coloured Petri Net with compiled guards and inscriptions.

    Attributes:
        places (list): Place records ``{gid, name, page, port, initmark}``;
            the list index is the place index used in markings.
        transitions (list): Transition records with compiled guard, input
            patterns, output terms and the variables to enumerate.
        declarations (Declarations): The net's colour sets, variables and
            declared values.
        env (dict): Names every expression can use.
        initial (tuple): The initial marking.
    """

    # Method to flatten and compile a parsed net.
    def __init__(self, net: CPNNet, prelude: Optional[Dict[str, Any]] = None):
        """Flatten the hierarchy and compile every inscription.

        Args:
            net (CPNNet): The parsed ``.cpn``.
            prelude (dict, optional): Names added to the net's own
                declarations, and winning over them. A net that declares its
                functions in ML needs none of this; it is for the one that
                does not.

        Raises:
            UnsupportedNet: When an inscription cannot be compiled.
        """
        self.net = net
        self.declarations = Declarations(net.path, prelude)
        self.env = self.declarations.globals
        self.fields = self.declarations.fields
        self.top = net.top_page()
        self.places: List[Dict[str, Any]] = []
        self.transitions: List[Dict[str, Any]] = []
        self.port_of: Dict[Tuple[str, str], int] = {}
        self._flatten()
        self.index = {p["gid"]: i for i, p in enumerate(self.places)}
        self.consumers: Dict[int, List[int]] = collections.defaultdict(list)
        for ti, t in enumerate(self.transitions):
            for pidx in {p for p, _ in t["in"]}:
                self.consumers[pidx].append(ti)
        self.initial = self.initial_marking()

    # Method to compile one expression against the net's declarations.
    def compile(self, text: str):
        """Compile a CPN ML expression in the net's environment.

        Args:
            text (str): The source.

        Returns:
            callable: ``env -> value``.

        Raises:
            UnsupportedNet: When it cannot be parsed or compiled.
        """
        try:
            return compile_expression(parse_expression(text), self.env,
                                      self.fields)
        except MLError as exc:
            raise UnsupportedNet(f"{text.strip()!r}: {exc}")

    # Method to compile a transition guard.
    def compile_guard(self, text: Optional[str]):
        """Compile a guard, which CPN Tools writes as a list of conditions.

        Args:
            text (str, optional): The guard text, possibly empty.

        Returns:
            tuple|None: ``(callable, expression trees)``, or None when the
            transition has no guard.

        Raises:
            UnsupportedNet: When the guard cannot be compiled.
        """
        text = (text or "").strip()
        if not text:
            return None
        try:
            tree = parse_expression(text)
        except MLError as exc:
            raise UnsupportedNet(f"guard {text!r}: {exc}")
        parts = tree[1] if tree[0] == "list" else [tree]
        if not parts:
            return None
        try:
            codes = [compile_expression(part, self.env, self.fields)
                     for part in parts]
        except MLError as exc:
            raise UnsupportedNet(f"guard {text!r}: {exc}")

        def holds(env, codes=codes):
            return all(bool(code(env)) for code in codes)
        return holds, parts

    # Method to compile an output arc inscription.
    def compile_output(self, text: str):
        """Compile an output inscription, which may be a multiset.

        Args:
            text (str): The inscription.

        Returns:
            tuple: ``(terms, expression trees)``, where a term is
            ``(count callable or int, value callable)``.

        Raises:
            UnsupportedNet: When the inscription cannot be compiled.
        """
        try:
            parsed = parse_multiset(text)
            terms, trees = [], []
            for coefficient, value in parsed:
                count = (1 if coefficient is None
                         else compile_expression(coefficient, self.env,
                                                 self.fields))
                terms.append((count, compile_expression(value, self.env,
                                                        self.fields)))
                trees.append(value)
                if coefficient is not None:
                    trees.append(coefficient)
            if not terms:
                raise MLError("empty inscription")
            return terms, trees
        except MLError as exc:
            raise UnsupportedNet(f"output arc {text.strip()!r}: {exc}")

    # Method to refuse the constructs whose semantics is not implemented.
    def _refuse_unsupported(self):
        """Raise on anything that would change the state space if ignored.

        Each of these is something CPN Tools takes into account when it builds
        the occurrence graph; skipping it would check a different net from the
        one on screen, so the net is refused by name instead.

        Raises:
            UnsupportedNet: For timed colour sets, transition time
                inscriptions, code segments, priorities other than the default
                and synchronous channels.
        """
        timed = sorted(name for name, cs in self.declarations.colsets.items()
                       if cs.timed)
        if timed:
            raise UnsupportedNet(
                f"timed nets are not supported (timed colour set(s): "
                f"{', '.join(timed[:3])})")
        for page in self.net.page_by_id.values():
            for tr in page["transitions"].values():
                where = f"{page['name']}/{tr['name']}"
                if tr.get("time"):
                    raise UnsupportedNet(f"{where}: time inscription "
                                         f"{tr['time']!r} (timed nets are not "
                                         "supported)")
                if tr.get("code"):
                    raise UnsupportedNet(f"{where}: code segments are not "
                                         "supported")
                if tr.get("priority") and tr["priority"] != "P_NORMAL":
                    raise UnsupportedNet(f"{where}: transition priority "
                                         f"{tr['priority']!r} is not supported")
                if tr.get("channel"):
                    raise UnsupportedNet(f"{where}: synchronous channels are "
                                         "not supported")

    # Method to map every fused place to the flat place of its fusion set.
    def _fusion_groups(self) -> Dict[str, str]:
        """Place id -> the global id shared by its fusion set.

        All places of a fusion set are one place, wherever they are drawn and
        however many times their page is instantiated. Members must agree on
        the colour set and the initial marking; a disagreement is refused
        rather than resolved by picking one.

        Returns:
            dict: ``{place id: "fusion:<set name>"}``.

        Raises:
            UnsupportedNet: When the members of a set disagree.
        """
        out: Dict[str, str] = {}
        for name, members in self.net.fusion_sets().items():
            entries = [pl for page in self.net.page_by_id.values()
                       for pid, pl in page["places"].items() if pid in members]
            marks = {" ".join((pl.get("initmark") or "").split())
                     for pl in entries}
            types = {pl.get("type") for pl in entries}
            if len(marks) > 1:
                raise UnsupportedNet(f"fusion set {name!r}: its places have "
                                     "different initial markings")
            if len(types) > 1:
                raise UnsupportedNet(f"fusion set {name!r}: its places have "
                                     "different colour sets")
            for pid in members:
                out[pid] = f"fusion:{name}"
        return out

    # Method to expand the page hierarchy into flat places and transitions.
    def _flatten(self):
        """Fuse port places with their sockets and compile every transition.

        Raises:
            UnsupportedNet: When a transition cannot be compiled, or has no
                input arc and so would be enabled forever.
        """
        places: Dict[str, Dict[str, Any]] = collections.OrderedDict()
        trans: List[Dict[str, Any]] = []
        self._refuse_unsupported()
        fusion_of = self._fusion_groups()

        def expand(page, prefix, fused):
            pid_of = {}
            for lid, pl in page["places"].items():
                if lid in fused and lid in fusion_of:
                    raise UnsupportedNet(
                        f"{page['name']}/{pl['name']} is both a port and a member "
                        f"of fusion set {pl['fusion']!r}")
                gid = (fused.get(lid) or fusion_of.get(lid)
                       or f"{prefix}/{pl['name']}")
                pid_of[lid] = gid
                if gid not in places:
                    places[gid] = {"gid": gid, "name": pl["name"],
                                   "page": page["name"], "port": pl.get("port"),
                                   "initmark": pl.get("initmark"),
                                   "colset": pl.get("type")}
                if pl.get("port"):
                    self.port_of[(page["name"], pl["name"])] = gid
            for tid, tr in page["transitions"].items():
                if tr["subpage"]:
                    continue
                ins, outs = [], []
                for a in page["arcs"]:
                    if a["trans"] != tid:
                        continue
                    arc = (pid_of[a["place"]], a["expr"])
                    # A double arc is an input and an output arc with the
                    # same inscription: the token is taken and put back.
                    if a["orient"] in ("PtoT", "BOTHDIR"):
                        ins.append(arc)
                    if a["orient"] in ("TtoP", "BOTHDIR"):
                        outs.append(arc)
                    if a["orient"] not in ("PtoT", "TtoP", "BOTHDIR"):
                        raise UnsupportedNet(
                            f"{page['name']}/{tr['name']}: arc orientation "
                            f"{a['orient']!r} is not supported")
                trans.append({"gid": f"{prefix}/{tr['name']}", "name": tr["name"],
                              "page": page["name"], "guard_text": tr["guard"],
                              "in_raw": ins, "out_raw": outs})
            for tid, tr in page["transitions"].items():
                if not tr["subpage"]:
                    continue
                sub = self.net.page_by_id[tr["subpage"]]
                sub_fused = {}
                for a, b in tr["portsock"]:
                    sock, port = (a, b) if a in page["places"] else (b, a)
                    sub_fused[port] = pid_of[sock]
                expand(sub, f"{prefix}/{tr['name']}", sub_fused)

        # Every prime page instance is part of the model. A page that is
        # instantiated twice at the top gets a distinct prefix per instance.
        seen: Dict[str, int] = collections.Counter()
        for page in self.net.prime_pages():
            seen[page["name"]] += 1
            prefix = page["name"] if seen[page["name"]] == 1 else \
                f"{page['name']}#{seen[page['name']]}"
            expand(page, prefix, {})
        self.places = list(places.values())
        index = {p["gid"]: i for i, p in enumerate(self.places)}
        for t in trans:
            self._compile_transition(t, index)
            self.transitions.append(t)

    # Method to compile one transition's guard, arcs and variables.
    def _compile_transition(self, t, index):
        """Compile a transition and work out which variables to enumerate.

        Args:
            t (dict): The transition record, modified in place.
            index (dict): Place gid to index.

        Raises:
            UnsupportedNet: When something will not compile, when the
                transition has no input arc, or when a free variable has no
                finite colour set to range over.
        """
        where = f"{t['page']}/{t['name']}"
        guard = self.compile_guard(t["guard_text"])
        t["guard"] = guard[0] if guard else None
        guard_trees = guard[1] if guard else []

        t["in"] = [(index[g], _name_wildcards(parse_pattern_multiset(e), where))
                   for g, e in t["in_raw"]]
        out_trees = []
        compiled_out = []
        for g, e in t["out_raw"]:
            terms, trees = self.compile_output(e)
            compiled_out.append((index[g], terms))
            out_trees.extend(trees)
        t["out"] = compiled_out

        if not t["in"]:
            raise UnsupportedNet(f"{where} has no input arc "
                                 "(it would be enabled forever)")

        bound = set()
        for _pidx, terms in t["in"]:
            for _count, pattern in terms:
                bound |= pattern_variables(pattern)
        t["in_vars"] = bound

        needs: Dict[int, int] = collections.Counter()
        flat = []
        for pidx, terms in t["in"]:
            for count, pattern in terms:
                needs[pidx] += count
                flat.extend([(pidx, pattern)] * count)
        t["needs"] = dict(needs)
        t["flat_in"] = flat

        used = set()
        for tree in guard_trees + out_trees:
            try:
                used |= free_variables(tree)
            except MLError as exc:
                raise UnsupportedNet(f"{where}: {exc}")
        free = sorted(used - bound - set(self.env))
        domains = []
        for name in free:
            values = self.declarations.domain_of(name)
            if values is None:
                declared = self.declarations.variables.get(name)
                reason = (f"its colour set {declared} is not finite"
                          if declared else "it is not declared")
                raise UnsupportedNet(
                    f"{where}: the variable {name!r} is not bound by an input "
                    f"arc and cannot be enumerated because {reason}")
            domains.append((name, values))
        t["free_vars"] = free
        t["domains"] = domains

    # Method to build the initial marking, optionally with another input.
    def initial_marking(self, token=None, places=None) -> tuple:
        """Assemble the initial marking from the places' initial inscriptions.

        Args:
            token (optional): A value to put in ``places`` instead of what
                they declare, so the same net can be explored for another
                input.
            places (sequence, optional): Indices of the places to overwrite.
                Which places carry the input is the caller's to say; the net
                itself does not distinguish them.

        Returns:
            tuple: The initial marking, one sorted token tuple per place.

        Raises:
            UnsupportedNet: When an initial marking cannot be evaluated, or
                when a token is given with no places to put it in. Quietly
                ignoring the input would mean checking the net against the
                wrong thing and never saying so.
        """
        if token is not None and not places:
            raise UnsupportedNet(
                "initial_marking was given a token but no places to put it "
                "in; pass places=..., which a profile supplies through "
                "input_places()")
        override = set(places or ())
        marking = []
        for i, pl in enumerate(self.places):
            if token is not None and i in override:
                tokens = [_canon(token)]
            else:
                tokens = self.parse_initial_marking(pl["initmark"])
            marking.append(tuple(sorted(tokens)))
        return tuple(marking)

    # Method to evaluate a place's initial marking.
    def parse_initial_marking(self, text: Optional[str]) -> List[Any]:
        """Evaluate a place's initial-marking inscription.

        Args:
            text (str, optional): The inscription, possibly empty.

        Returns:
            list: The tokens.

        Raises:
            UnsupportedNet: When the inscription cannot be evaluated.
        """
        text = (text or "").strip()
        if not text:
            return []
        terms, _trees = self.compile_output(text)
        tokens: List[Any] = []
        for count, value in terms:
            number = count if isinstance(count, int) else count({})
            try:
                tokens.extend([_canon(value({}))] * int(number))
            except MLError as exc:
                raise UnsupportedNet(f"initial marking {text!r}: {exc}")
        return tokens

    # Method to list every enabled binding element of a marking.
    def enabled(self, marking: tuple) -> List[Tuple[int, Tuple, dict]]:
        """Enumerate the binding elements enabled in a marking.

        Args:
            marking (tuple): A marking.

        Returns:
            list: ``(transition index, binding key, binding)`` triples.
        """
        candidates = set()
        for pidx, tokens in enumerate(marking):
            if tokens:
                candidates.update(self.consumers.get(pidx, ()))
        found = []
        for ti in sorted(candidates):
            t = self.transitions[ti]
            if any(len(marking[p]) < n for p, n in t["needs"].items()):
                continue
            for env in self._bindings(marking, t):
                key = tuple(sorted(env.items()))
                found.append((ti, key, env))
        return found

    # Method to enumerate the bindings of one transition in a marking.
    def _bindings(self, marking, t) -> List[dict]:
        """Enumerate the bindings of a transition, honouring its guard.

        Input patterns are matched against the tokens available; variables no
        input arc binds are then run through their colour sets, which is how
        CPN Tools finds the rest of the binding elements.

        Args:
            marking (tuple): The marking.
            t (dict): The transition record.

        Returns:
            list: Distinct complete bindings.

        Raises:
            UnsupportedNet: When the guard cannot be evaluated, or when the
                transition has more binding elements than the budget allows.
        """
        results, seen = [], set()
        inputs = t["flat_in"]
        guard = t["guard"]
        domains = t["domains"]

        def accept(env):
            if guard is not None:
                try:
                    if not guard(env):
                        return
                except MLError as exc:
                    raise UnsupportedNet(f"{t['name']}: guard: {exc}")
                except Exception as exc:                       # noqa: BLE001
                    raise UnsupportedNet(f"{t['name']}: guard could not be "
                                         f"evaluated ({exc})")
            key = tuple(sorted(env.items()))
            if key not in seen:
                seen.add(key)
                results.append(env)
                if len(results) > MAX_BINDINGS:
                    raise UnsupportedNet(
                        f"{t['name']} has more than {MAX_BINDINGS} binding "
                        "elements in one marking")

        def complete(env):
            if not domains:
                accept(env)
                return
            names = [name for name, _values in domains]
            for combination in itertools.product(*[v for _n, v in domains]):
                extended = dict(env)
                extended.update(zip(names, combination))
                accept(extended)

        def rec(i, env, used):
            if i == len(inputs):
                complete(env)
                return
            pidx, pattern = inputs[i]
            available = collections.Counter(marking[pidx])
            available.subtract(used.get(pidx, {}))
            for token in sorted(set(marking[pidx])):
                if available[token] <= 0:
                    continue
                env2 = match_pattern(pattern, token, env, self.fields)
                if env2 is None:
                    continue
                used2 = {k: collections.Counter(v) for k, v in used.items()}
                used2.setdefault(pidx, collections.Counter())[token] += 1
                rec(i + 1, env2, used2)

        rec(0, {}, {})
        return results

    # Method to follow one maximal occurrence sequence.
    def run(self, marking: Optional[tuple] = None, limit: int = 100_000) -> tuple:
        """Fire the first enabled binding element until none is enabled.

        Used for conformance testing on many inputs, where building the whole
        occurrence graph per input would be wasteful. It gives the terminal
        marking of *one* maximal run; that this is *the* result of the net
        rests on confluence, which the model-checking step establishes.

        Args:
            marking (tuple, optional): Start marking (initial marking if None).
            limit (int): Maximum number of occurrences.

        Returns:
            tuple: The marking where the run stopped.

        Raises:
            UnsupportedNet: When no dead marking is reached within the limit.
        """
        m = self.initial if marking is None else marking
        for _ in range(limit):
            options = self.enabled(m)
            if not options:
                return m
            ti, _key, env = options[0]
            m = self.fire(m, ti, env)
        raise UnsupportedNet(f"no dead marking within {limit} occurrences")

    # Method to fire one binding element.
    def fire(self, marking: tuple, ti: int, env: dict) -> tuple:
        """Compute the marking reached by an occurrence.

        Args:
            marking (tuple): Current marking.
            ti (int): Transition index.
            env (dict): The binding.

        Returns:
            tuple: The successor marking.

        Raises:
            UnsupportedNet: When an output inscription cannot be evaluated.
        """
        t = self.transitions[ti]
        new = [list(tokens) for tokens in marking]
        for pidx, pattern in t["flat_in"]:
            new[pidx].remove(_instantiate(pattern, env))
        for pidx, terms in t["out"]:
            for count, code in terms:
                try:
                    number = count if isinstance(count, int) else count(env)
                    value = _canon(code(env))
                except MLError as exc:
                    raise UnsupportedNet(f"{t['name']}: output arc: {exc}")
                except Exception as exc:                       # noqa: BLE001
                    raise UnsupportedNet(f"{t['name']}: output arc could not "
                                         f"be evaluated ({exc})")
                new[pidx].extend([value] * int(number))
        return tuple(tuple(sorted(tokens)) for tokens in new)


# Function to give every wildcard of an input arc a name.
def _name_wildcards(terms, where):
    """Replace ``_`` in an input pattern with a variable nobody else uses.

    A wildcard on an input arc says "any token", but firing has to know which
    token was taken, and a binding element has to say so too or it could not
    be replayed. Naming the wildcard keeps both: the token appears in the
    binding, under a name the net itself cannot refer to.

    Args:
        terms (list): ``(count, pattern)`` pairs.
        where (str): The transition, for the generated names.

    Returns:
        list: The patterns, with wildcards named.
    """
    counter = [0]

    def rename(pattern):
        tag = pattern[0]
        if tag == "pwild":
            counter[0] += 1
            return ("pvar", f"_any{counter[0]}")
        if tag in ("ptuple", "plist"):
            return (tag, [rename(p) for p in pattern[1]])
        if tag == "pcons":
            return ("pcons", rename(pattern[1]), rename(pattern[2]))
        if tag == "precord":
            return ("precord", [(lab, rename(p)) for lab, p in pattern[1]])
        return pattern

    return [(count, rename(pattern)) for count, pattern in terms]


# Function to rebuild the token a pattern denotes under a complete binding.
def _instantiate(pattern, env):
    """Evaluate a pattern back into the token it consumes.

    Args:
        pattern (tuple): Pattern tree.
        env (dict): Complete binding.

    Returns:
        The token value.

    Raises:
        UnsupportedNet: For a pattern shape that cannot be rebuilt.
    """
    tag = pattern[0]
    if tag == "pvar":
        return env[pattern[1]]
    if tag == "plit":
        return pattern[1]
    if tag in ("ptuple", "plist"):
        return tuple(_instantiate(p, env) for p in pattern[1])
    if tag == "pcons":
        return (_instantiate(pattern[1], env),) + _instantiate(pattern[2], env)
    raise UnsupportedNet(f"cannot rebuild the token matched by {tag!r}")
