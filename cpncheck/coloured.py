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

Input arcs that are not patterns
--------------------------------
An input arc is usually a pattern (``x``, ``(n, p)``, ``2`e``): it is matched
against the tokens and binds variables. CPN Tools also accepts any expression
whose variables are bound some other way -- ``Mes(s)``, ``if x = p then 1`e
else empty``. Such an arc binds nothing; once the binding is complete it is
evaluated to a multiset, and the transition is enabled only if the place holds
that multiset on top of what the pattern arcs take.

Values
------
Tokens are Python values, chosen so a marking is hashable and orderable: a
record is a tuple in declared field order, a list is a tuple, unit is the empty
tuple, an enumeration constant a string, ``u(i)`` an
:class:`~cpncheck.cpnml.IndexValue`. Two markings are the same node exactly
when they are equal. An arc may evaluate to a multiset; it is expanded into
tokens.
"""

import collections
import itertools
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .colourset import Declarations
from .cpnml import (Delayed, IndexValue, MLError, MultiSet, Parser, Stamped,
                    _delay,
                    TimedToken, compile_expression, free_variables,
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
    if isinstance(value, (IndexValue, TimedToken, Delayed, Stamped)):
        return value
    if isinstance(value, list):
        return tuple(_canon(v) for v in value)
    if isinstance(value, tuple):
        return tuple(_canon(v) for v in value)
    return value


# Function to turn an arc term into the tokens it denotes.
def _tokens(number, value) -> List[Any]:
    """``number`` copies of a value, or of every element of a multiset.

    Args:
        number (int): The term's coefficient.
        value: A token value, or a :class:`~cpncheck.cpnml.MultiSet`.

    Returns:
        list: The tokens, canonical.
    """
    number = int(number)
    if isinstance(value, MultiSet):
        out: List[Any] = []
        for element, count in value.items():
            out.extend([_canon(element)] * (count * number))
        return out
    return [_canon(value)] * number


#: The binding entry recording which timestamps a timed occurrence removes
#: (not an ML identifier, so it cannot clash with a variable).
REMOVED = "'removed"

#: The ``compat`` mode reproducing CPN Tools 4.0.1's timed state spaces.
CPNTOOLS_401 = "cpntools-4.0.1"


# Function to check that a delay is an integer model time.
def _model_time_of(value, where: str) -> int:
    """A delay as an integer model time.

    Args:
        value: The evaluated delay.
        where (str): The transition, for messages.

    Returns:
        int: The delay.

    Raises:
        MLError: For a non-integer delay (real time is not supported).
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise MLError(f"{where}: delay {value!r} is not an integer model time")
    return value


# Function to split an arc inscription at its top-level delay.
def _split_arc_delay(text: str) -> Tuple[str, Optional[str]]:
    """Split ``expr @+ d`` at the first ``@+`` outside any brackets.

    CPN Tools reads a timed arc inscription as an expression followed by a
    delay, so in ``if b then 1`x else empty @+7`` the delay applies to both
    branches, not only to ``empty`` as an operator would.

    Args:
        text (str): The inscription.

    Returns:
        tuple: ``(expression, delay text or None)``.
    """
    depth = 0
    for kind, value, pos in tokenize(text):
        if kind == "op" and value in ("(", "[", "{"):
            depth += 1
        elif kind == "op" and value in (")", "]", "}"):
            depth -= 1
        elif kind == "kw" and value in ("let", "local"):
            depth += 1
        elif kind == "kw" and value == "end":
            depth -= 1
        elif kind == "op" and value == "@++":
            raise MLError("@++ adds a real-valued delay; only integer model "
                          "time (@+) is supported")
        elif kind == "op" and value == "@+" and depth == 0:
            return text[:pos], text[pos + 2:]
    return text, None


# Function to parse a multiset of patterns, as an input arc carries.
def parse_pattern_multiset(text: str, symbols=None) -> List[Tuple[int, Any]]:
    """Parse ``2`x ++ 1`(a, b)`` into counted patterns.

    An input arc consumes a multiset, so a coefficient means "this many
    tokens, each matching the pattern". The coefficient has to be a literal:
    a variable number of tokens would have to be solved for, not matched.

    Args:
        text (str): The inscription.
        symbols (dict, optional): Declared constants and constructors, so
            that a constant in the pattern matches that constant only.

    Returns:
        list: ``(count, pattern)`` pairs.

    Raises:
        UnsupportedNet: On a syntax error or a non-literal coefficient.
    """
    try:
        parser = Parser(tokenize(text or ""), text or "", symbols)
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
    def __init__(self, net: CPNNet, prelude: Optional[Dict[str, Any]] = None,
                 compat: Optional[str] = None):
        """Flatten the hierarchy and compile every inscription.

        Args:
            net (CPNNet): The parsed ``.cpn``.
            prelude (dict, optional): Names added to the net's own
                declarations, and winning over them. A net that declares its
                functions in ML needs none of this; it is for the one that
                does not.
            compat (str, optional): ``"cpntools-4.0.1"`` reproduces how the
                state-space tool of CPN Tools 4.0.1 expands a timed marking
                (see :meth:`_expansion_view`). Only for validating against
                it: the default follows the timed semantics of the
                literature, which its simulator implements.

        Raises:
            UnsupportedNet: When an inscription cannot be compiled.
        """
        if compat not in (None, CPNTOOLS_401):
            raise ValueError(f"unknown compat mode {compat!r}")
        self.compat = compat
        self.net = net
        self.declarations = Declarations(net.path, prelude)
        self.env = self.declarations.globals
        self.fields = self.declarations.fields
        self.symbols = self.declarations.symbols
        # time() reads the model time of the evaluation in progress.
        self._now = 0
        self.env["time"] = lambda _unit: self._now
        self.top = net.top_page()
        self.places: List[Dict[str, Any]] = []
        self.transitions: List[Dict[str, Any]] = []
        self.port_of: Dict[Tuple[str, str], int] = {}
        #: How many times each page is instantiated.
        self.page_instances: Dict[str, int] = collections.Counter()
        self._flatten()
        self.index = {p["gid"]: i for i, p in enumerate(self.places)}
        self.consumers: Dict[int, List[int]] = collections.defaultdict(list)
        for ti, t in enumerate(self.transitions):
            places = {p for p, _ in t["in"]} | {p for p, _ in t["in_expr"]}
            for pidx in places:
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
            return compile_expression(parse_expression(text, self.symbols),
                                      self.env, self.fields)
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
            tree = parse_expression(text, self.symbols)
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
            body, delay_text = _split_arc_delay(text)
            if delay_text is not None:
                # "expr @+ d" is arc syntax in CPN Tools: the delay covers the
                # whole inscription, however the expression is built.
                value = compile_expression(parse_expression(body, self.symbols),
                                           self.env, self.fields)
                delay_tree = parse_expression(delay_text, self.symbols)
                delay = compile_expression(delay_tree, self.env, self.fields)
                return ([(1, lambda env: _delay(value(env), delay(env)))],
                        [parse_expression(body, self.symbols), delay_tree])
            parsed = parse_multiset(text, self.symbols)
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
        one on screen, so the net is refused by name instead. Timed nets,
        priorities and code segments are supported; what remains is refused.

        Raises:
            UnsupportedNet: For synchronous channels.
        """
        for page in self.net.page_by_id.values():
            for tr in page["transitions"].values():
                where = f"{page['name']}/{tr['name']}"
                if tr.get("channel"):
                    raise UnsupportedNet(f"{where}: synchronous channels are "
                                         "not supported")

    # Method to compile a transition's time inscription.
    def _compile_delay(self, t, where):
        """``@+d`` on a transition: a delay added to every timed output token.

        Args:
            t (dict): The transition record.
            where (str): Its name, for messages.

        Returns:
            tuple: ``(callable or None, expression trees)``.

        Raises:
            UnsupportedNet: When the inscription is not ``@+ expression``.
        """
        text = (t.get("time_text") or "").strip()
        if not text:
            return None, []
        if not text.startswith("@+") or text.startswith("@++"):
            raise UnsupportedNet(f"{where}: time inscription {text!r} is not "
                                 "supported (integer delays @+d only)")
        body = text[2:].strip()
        try:
            tree = parse_expression(body, self.symbols)
            return compile_expression(tree, self.env, self.fields), [tree]
        except MLError as exc:
            raise UnsupportedNet(f"{where}: time inscription {text!r}: {exc}")

    # Method to compile a transition's priority.
    def _compile_priority(self, t, where) -> int:
        """The priority, a CPN ML integer (``P_HIGH``, ``P_NORMAL``, ...).

        Args:
            t (dict): The transition record.
            where (str): Its name, for messages.

        Returns:
            int: The priority; smaller is more urgent.

        Raises:
            UnsupportedNet: When it is not a constant integer expression.
        """
        text = (t.get("priority_text") or "").strip()
        if not text:
            return self.env["P_NORMAL"]
        try:
            value = compile_expression(parse_expression(text, self.symbols),
                                       self.env, self.fields)({})
        except MLError as exc:
            raise UnsupportedNet(f"{where}: priority {text!r}: {exc}")
        if isinstance(value, bool) or not isinstance(value, int):
            raise UnsupportedNet(f"{where}: priority {text!r} is not an integer")
        return value

    # Method to compile a transition's code segment.
    def _compile_code(self, t, where):
        """``input (...); output (...); action e;``, without side effects.

        The action is CPN ML like any other expression, so anything with a
        side effect -- a reference, a file, a socket -- is outside the fragment
        and refused. Its result binds the output variables at occurrence.

        Args:
            t (dict): The transition record.
            where (str): Its name, for messages.

        Returns:
            tuple: ``(action callable or None, output variable names, trees)``.

        Raises:
            UnsupportedNet: When the segment does not parse or compile.
        """
        text = (t.get("code_text") or "").strip()
        if not text:
            return None, [], []
        m = re.match(r"^\s*(?:input\s*\(?(?P<inp>[^;)]*)\)?\s*;)?\s*"
                     r"(?:output\s*\(?(?P<out>[^;)]*)\)?\s*;)?\s*"
                     r"action\s*(?P<act>.*?)\s*;?\s*$", text, re.S)
        if not m:
            raise UnsupportedNet(f"{where}: code segment {text!r} is not "
                                 "input/output/action")
        outputs = [v.strip() for v in (m.group("out") or "").split(",")
                   if v.strip()]
        try:
            tree = parse_expression(m.group("act"), self.symbols)
            action = compile_expression(tree, self.env, self.fields)
            unknown = sorted(free_variables(tree) - set(self.env)
                             - set(self.declarations.variables))
        except MLError as exc:
            raise UnsupportedNet(f"{where}: code segment: {exc} (code with "
                                 "side effects is not supported)")
        if unknown:
            raise UnsupportedNet(
                f"{where}: code segment uses {', '.join(unknown)}, which is not "
                "part of the supported CPN ML (code with side effects is not "
                "supported)")
        return action, outputs, [tree]

    # Method to compile one transition's guard, arcs and variables.
    def _compile_transition(self, t, index):
        """Compile a transition and work out which variables to enumerate.

        Args:
            t (dict): The transition record, modified in place.
            index (dict): Place gid to index.

        Raises:
            UnsupportedNet: When something will not compile, when the
                transition has no input arc, or when a free variable has no
                finite colour set to range over and no guard defining it.
        """
        where = f"{t['page']}/{t['name']}"
        guard = self.compile_guard(t["guard_text"])
        t["guard"] = guard[0] if guard else None
        guard_trees = guard[1] if guard else []
        t["delay"], delay_trees = self._compile_delay(t, where)
        t["priority"] = self._compile_priority(t, where)
        t["action"], t["code_outputs"], code_trees = self._compile_code(t, where)

        t["in"], t["in_expr"] = [], []
        expr_trees = []
        for g, e in t["in_raw"]:
            if "@" in e and index[g] in self.timed_places:
                raise UnsupportedNet(f"{where}: input arc {e.strip()!r}: time "
                                     "inscriptions on input arcs are not "
                                     "supported")
            try:
                terms = parse_pattern_multiset(e, self.symbols)
            except UnsupportedNet as not_a_pattern:
                # Not a pattern: an expression over variables bound elsewhere,
                # evaluated once the binding is complete.
                try:
                    code, trees = self._compile_input_expression(e)
                except UnsupportedNet as exc:
                    raise UnsupportedNet(f"{not_a_pattern}; as an expression: "
                                         f"{exc}")
                t["in_expr"].append((index[g], code))
                expr_trees.extend(trees)
                continue
            t["in"].append((index[g], _name_wildcards(terms, where)))
        out_trees = []
        compiled_out = []
        for g, e in t["out_raw"]:
            terms, trees = self.compile_output(e)
            compiled_out.append((index[g], terms))
            out_trees.extend(trees)
        t["out"] = compiled_out

        if not t["in"] and not t["in_expr"]:
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

        # The code segment's outputs are bound when it runs, not enumerated.
        produced = set(t["code_outputs"])
        used = set()
        for tree in (guard_trees + out_trees + expr_trees + delay_trees
                     + code_trees):
            try:
                used |= free_variables(tree)
            except MLError as exc:
                raise UnsupportedNet(f"{where}: {exc}")
        free = sorted(used - bound - set(self.env) - produced)
        domains, missing = [], []
        for name in free:
            values = self.declarations.domain_of(name)
            if values is None:
                missing.append(name)
            else:
                domains.append((name, values))
        computed = self._guard_definitions(
            missing, guard_trees, bound | {n for n, _v in domains}, where)
        t["free_vars"] = free
        t["domains"] = domains
        t["computed"] = computed

    # Method to find guard conjuncts that define otherwise unbound variables.
    def _guard_definitions(self, names, guard_trees, known, where):
        """Variables bound by a guard conjunct ``x = e`` (or ``e = x``).

        CPN Tools binds such a variable by evaluating ``e`` once the variables
        ``e`` mentions are bound. Definitions may chain; they are ordered so
        that each comes after those it needs.

        Args:
            names (list): Variables with no input arc and no finite domain.
            guard_trees (list): The guard's conjuncts.
            known (set): Variables already bound by arcs or enumeration.
            where (str): The transition, for messages.

        Returns:
            list: ``(name, compiled expression)`` in evaluation order.

        Raises:
            UnsupportedNet: For a variable no conjunct defines.
        """
        candidates = {}
        for tree in guard_trees:
            if tree[0] != "binop" or tree[1] != "=":
                continue
            for var, expr in ((tree[2], tree[3]), (tree[3], tree[2])):
                if var[0] == "var" and var[1] in names \
                        and var[1] not in candidates:
                    candidates[var[1]] = expr
        order, known = [], set(known)
        pending = [n for n in names]
        progress = True
        while pending and progress:
            progress = False
            for name in list(pending):
                expr = candidates.get(name)
                if expr is None:
                    continue
                try:
                    needs = free_variables(expr) - set(self.env)
                except MLError:
                    continue
                if needs <= known:
                    order.append((name, compile_expression(expr, self.env,
                                                           self.fields)))
                    known.add(name)
                    pending.remove(name)
                    progress = True
        if pending:
            name = pending[0]
            declared = self.declarations.variables.get(name)
            reason = (f"its colour set {declared} is not finite"
                      if declared else "it is not declared")
            raise UnsupportedNet(
                f"{where}: the variable {name!r} is not bound by an input arc "
                f"or a guard, and cannot be enumerated because {reason}")
        return order

    # Method to tell whether a colour set name is timed.
    def _is_timed_colset(self, name) -> bool:
        """Whether a place of this colour set holds timed tokens.

        Args:
            name (str): The colour set as written on the place.

        Returns:
            bool: True for a timed colour set.
        """
        colset = self.declarations.colsets.get((name or "").strip())
        return bool(colset and colset.timed)

    # Method to give the values of a place's tokens, without timestamps.
    def values_of(self, pidx: int, tokens) -> list:
        """The colours of a place's tokens; timestamps dropped.

        Args:
            pidx (int): The place.
            tokens (tuple): Its tokens in some marking.

        Returns:
            list: The values.
        """
        if pidx in self.timed_places:
            return [tok[0] for tok in tokens]
        return list(tokens)

    # Method to read the model time of a marking.
    def clock_of(self, marking: tuple) -> int:
        """The global clock of a marking (0 for an untimed net).

        Args:
            marking (tuple): A marking.

        Returns:
            int: The model time.
        """
        return marking[-1] if self.timed else 0

    # Method to compile an input arc that is not a pattern.
    def _compile_input_expression(self, text: str):
        """Compile an input inscription as an expression to evaluate later.

        Args:
            text (str): The inscription.

        Returns:
            tuple: ``(code, expression trees)``; ``code(env)`` gives the
            multiset of values the arc takes.

        Raises:
            UnsupportedNet: When it does not compile as an expression either.
        """
        terms, trees = self.compile_output(text)

        def taken(env, terms=terms):
            out: Dict[Any, int] = {}
            for count, code in terms:
                number = count if isinstance(count, int) else count(env)
                for token in _tokens(number, code(env)):
                    if isinstance(token, (Delayed, Stamped)):
                        raise MLError("an input arc cannot carry a time "
                                      "inscription")
                    out[token] = out.get(token, 0) + 1
            return MultiSet(out)
        return taken, trees

    # Method to build the initial marking, optionally with another input.
    def initial_marking(self, token=None, places=None) -> tuple:
        """Assemble the initial marking from the places' initial inscriptions.

        A timed net's marking ends with the global clock, which starts at 0;
        its timed places hold :class:`~cpncheck.cpnml.TimedToken` values,
        stamped 0 unless the inscription says ``@t``.

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
            marking.append(tuple(sorted(self._stamp_initial(i, tokens))))
        if self.timed:
            marking.append(0)
        return tuple(marking)

    # Method to give initial tokens their timestamps.
    def _stamp_initial(self, pidx: int, tokens) -> list:
        """Initial tokens as stored: timed places get timestamps.

        Args:
            pidx (int): The place.
            tokens (list): Values, possibly ``Stamped``/``Delayed``.

        Returns:
            list: The tokens.

        Raises:
            UnsupportedNet: For a timestamp on an untimed place.
        """
        out = []
        for tok in tokens:
            if pidx in self.timed_places:
                if isinstance(tok, Stamped):
                    out.append(TimedToken(tok[0], tok[1]))
                elif isinstance(tok, Delayed):
                    out.append(TimedToken(tok[0], tok[1]))
                else:
                    out.append(TimedToken(tok, 0))
            elif isinstance(tok, (Stamped, Delayed)):
                raise UnsupportedNet(f"{self.places[pidx]['name']}: a timestamp "
                                     "on an untimed place")
            else:
                out.append(tok)
        return out

    # Method to list every enabled binding element of a marking.
    def enabled(self, marking: tuple) -> List[Tuple[int, Tuple, dict]]:
        """Enumerate the binding elements enabled in a marking.

        In a timed net these are the binding elements enabled at the earliest
        model time at which any is: if nothing is enabled now, the clock moves
        on to the first time something is, as CPN Tools does. Among them, only
        those of the most urgent priority may occur.

        A binding takes values, and a timed place may hold several ready
        tokens of one value with different timestamps. Which of them goes is
        a choice, and each choice is its own successor; the binding then
        records it under :data:`REMOVED`. (CPN Tools 4.0.1's state space tool
        explores some of these choices, not always the same ones from run to
        run, so its graph is contained in this one.)

        Args:
            marking (tuple): A marking.

        Returns:
            list: ``(transition index, binding key, binding)`` triples.
        """
        candidates = set()
        for pidx in range(len(self.places)):
            if marking[pidx]:
                candidates.update(self.consumers.get(pidx, ()))
        marking = self._expansion_view(marking)
        found = []
        for ti in sorted(candidates):
            t = self.transitions[ti]
            if any(len(marking[p]) < n for p, n in t["needs"].items()):
                continue
            for env, ready in self._bindings(marking, t):
                key = tuple(sorted(env.items()))
                found.append((ti, key, env, ready))
        if self.timed and found:
            earliest = min(f[3] for f in found)
            found = [choice for f in found if f[3] == earliest
                     for choice in self._removal_choices(marking, f, earliest)]
        if found and self.uses_priorities:
            top = min(self.transitions[f[0]]["priority"] for f in found)
            found = [f for f in found
                     if self.transitions[f[0]]["priority"] == top]
        return [(ti, key, env) for ti, key, env, _ready in found]

    # Method to split a timed binding by the tokens it may remove.
    def _removal_choices(self, marking, found, now):
        """The ways a binding can pick its tokens among the ready ones.

        Args:
            marking (tuple): The (expansion view of the) marking.
            found (tuple): ``(ti, key, env, ready)``.
            now (int): The occurrence time.

        Returns:
            list: One ``(ti, key, env, ready)`` per choice; the env carries
            the choice under :data:`REMOVED`.
        """
        ti, _key, env, ready = found
        per_value = []
        for pidx, wanted in sorted(self._taken(self.transitions[ti], env).items()):
            if pidx not in self.timed_places:
                continue
            for value, count in sorted(wanted.items(), key=repr):
                stamps = sorted(tok[1] for tok in marking[pidx]
                                if tok[0] == value and tok[1] <= now)
                options = sorted(set(itertools.combinations(stamps, count)))
                per_value.append([(pidx, value, o) for o in options])
        out = []
        for combo in itertools.product(*per_value):
            chosen = dict(env)
            chosen[REMOVED] = tuple(combo)
            out.append((ti, tuple(sorted(chosen.items(), key=lambda kv: kv[0])),
                        chosen, ready))
        return out

    # Method to give the time a binding element becomes enabled.
    def ready_time(self, marking: tuple, ti: int, env: dict) -> int:
        """When an enabled binding element can occur (the clock if untimed).

        Args:
            marking (tuple): The marking.
            ti (int): Transition index.
            env (dict): The binding.

        Returns:
            int: The model time of the occurrence.
        """
        if not self.timed:
            return 0
        return self._ready(self._expansion_view(marking), self.transitions[ti],
                           env)

    # Method to give the marking a successor is computed from.
    def _expansion_view(self, marking: tuple) -> tuple:
        """The marking successors are computed from.

        Normally the marking itself. With ``compat="cpntools-4.0.1"``, the
        state-space tool of CPN Tools 4.0.1 is reproduced: before expanding
        a node it subtracts the node's clock from every timestamp (clamping
        at 0) but leaves the clock where it was, so tokens become ready
        early. That is its ``CPN'subtract creationtime`` in
        ``OGToSimDataGen.sml``, applied although the creation-time reduction
        that should pair it with a reset clock is off.

        Args:
            marking (tuple): A marking.

        Returns:
            tuple: The marking to expand.
        """
        if self.compat != CPNTOOLS_401 or not self.timed:
            return marking
        clock = marking[-1]
        view = list(marking)
        for pidx in self.timed_places:
            view[pidx] = tuple(sorted(
                TimedToken(tok[0], max(0, tok[1] - clock)) for tok in marking[pidx]))
        return tuple(view)

    # Method to compute when the tokens a binding takes are all ready.
    def _ready(self, marking, t, env) -> int:
        """The earliest model time at which a binding's tokens are ready.

        A binding takes values, not particular tokens; it can occur once, for
        every value it takes ``n`` of from a timed place, ``n`` tokens of that
        value have reached their timestamps.

        Args:
            marking (tuple): The marking.
            t (dict): The transition.
            env (dict): The binding.

        Returns:
            int: The time (never before the marking's clock).
        """
        clock = marking[-1]
        ready = clock
        if REMOVED in env:
            for _pidx, _value, stamps in env[REMOVED]:
                ready = max([ready, *stamps])
            return ready
        for pidx, wanted in self._taken(t, env).items():
            if pidx not in self.timed_places:
                continue
            for value, count in wanted.items():
                stamps = sorted(tok[1] for tok in marking[pidx]
                                if tok[0] == value)
                ready = max(ready, stamps[count - 1])
        return ready

    # Method to list what a binding takes from each place.
    def _taken(self, t, env) -> Dict[int, collections.Counter]:
        """Values a binding removes, per place.

        Args:
            t (dict): The transition.
            env (dict): The binding.

        Returns:
            dict: ``{place: Counter(value -> count)}``.
        """
        out: Dict[int, collections.Counter] = collections.defaultdict(
            collections.Counter)
        for pidx, pattern in t["flat_in"]:
            out[pidx][_instantiate(pattern, env)] += 1
        for pidx, code in t["in_expr"]:
            for value, count in code(env).items():
                out[pidx][value] += count
        return out

    # Method to enumerate the bindings of one transition in a marking.
    def _bindings(self, marking, t) -> List[Tuple[dict, int]]:
        """Enumerate the bindings of a transition, honouring its guard.

        Input patterns are matched against the values available; variables no
        input arc binds are then run through their colour sets, or defined by
        the guard, which is how CPN Tools finds the rest of the binding
        elements.

        Args:
            marking (tuple): The marking.
            t (dict): The transition record.

        Returns:
            list: Distinct complete bindings, each with the model time it can
            occur at (the marking's clock for an untimed net).

        Raises:
            UnsupportedNet: When the guard cannot be evaluated, or when the
                transition has more binding elements than the budget allows.
        """
        results, seen = [], set()
        inputs = t["flat_in"]
        guard = t["guard"]
        domains = t["domains"]
        computed = t["computed"]
        expr_arcs = t["in_expr"]
        values = {pidx: self.values_of(pidx, marking[pidx])
                  for pidx in {p for p, _ in inputs}
                  | {p for p, _ in expr_arcs}}
        self._now = self.clock_of(marking)

        def available_for_expressions(env, used):
            # The expression arcs take their multisets on top of what the
            # pattern arcs took; each must be present in full.
            taken: Dict[int, collections.Counter] = {
                p: collections.Counter(c) for p, c in used.items()}
            for pidx, code in expr_arcs:
                try:
                    wanted = code(env)
                except MLError as exc:
                    raise UnsupportedNet(f"{t['name']}: input arc: {exc}")
                have = collections.Counter(values[pidx])
                have.subtract(taken.get(pidx, {}))
                for token, count in wanted.items():
                    if have[token] < count:
                        return False
                    taken.setdefault(pidx, collections.Counter())[token] += count
            return True

        def accept(env, used):
            if expr_arcs and not available_for_expressions(env, used):
                return
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
                ready = self._ready(marking, t, env) if self.timed else 0
                results.append((env, ready))
                if len(results) > MAX_BINDINGS:
                    raise UnsupportedNet(
                        f"{t['name']} has more than {MAX_BINDINGS} binding "
                        "elements in one marking")

        def define(env, used):
            # Variables defined by guard conjuncts x = e, in dependency order.
            if computed:
                env = dict(env)
                for name, code in computed:
                    try:
                        env[name] = _canon(code(env))
                    except MLError as exc:
                        raise UnsupportedNet(f"{t['name']}: guard defining "
                                             f"{name!r}: {exc}")
            accept(env, used)

        def complete(env, used):
            if not domains:
                define(env, used)
                return
            names = [name for name, _values in domains]
            for combination in itertools.product(*[v for _n, v in domains]):
                extended = dict(env)
                extended.update(zip(names, combination))
                define(extended, used)

        def rec(i, env, used):
            if i == len(inputs):
                complete(env, used)
                return
            pidx, pattern = inputs[i]
            available = collections.Counter(values[pidx])
            available.subtract(used.get(pidx, {}))
            for token in sorted(set(values[pidx])):
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

        In a timed net the occurrence happens at the time the binding element
        is ready (see :meth:`enabled`), which becomes the new clock; tokens
        produced on timed places are stamped with it plus the transition's
        and the arc's delays. Of several ready tokens with the same value, the
        one with the smallest timestamp is taken.

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
        marking = self._expansion_view(marking)
        now = self._ready(marking, t, env) if self.timed else 0
        self._now = now
        n_places = len(self.places)
        new = [list(marking[p]) for p in range(n_places)]
        chosen = {(pidx, value): stamps
                  for pidx, value, stamps in env.get(REMOVED, ())}
        env = {k: v for k, v in env.items() if k != REMOVED}
        for pidx, wanted in self._taken(t, env).items():
            for value, count in wanted.items():
                if pidx not in self.timed_places:
                    for _ in range(count):
                        new[pidx].remove(value)
                    continue
                stamps = chosen.get((pidx, value))
                if stamps is None:
                    # No choice given (a run, not a graph): the oldest go.
                    stamps = sorted(tok[1] for tok in new[pidx]
                                    if tok[0] == value and tok[1] <= now)[:count]
                for stamp in stamps:
                    new[pidx].remove(TimedToken(value, stamp))
        if t["action"] is not None:
            env = dict(env)
            try:
                result = t["action"](env)
            except MLError as exc:
                raise UnsupportedNet(f"{t['name']}: code segment: {exc}")
            outs = t["code_outputs"]
            if len(outs) == 1:
                env[outs[0]] = _canon(result)
            elif outs:
                if not isinstance(result, tuple) or len(result) != len(outs):
                    raise UnsupportedNet(f"{t['name']}: the code segment's "
                                         f"result {result!r} does not match "
                                         f"output ({', '.join(outs)})")
                env.update(zip(outs, (_canon(v) for v in result)))
        delay = 0
        if t["delay"] is not None:
            try:
                delay = _model_time_of(t["delay"](env), t["name"])
            except MLError as exc:
                raise UnsupportedNet(f"{t['name']}: time inscription: {exc}")
        for pidx, terms in t["out"]:
            for count, code in terms:
                try:
                    number = count if isinstance(count, int) else count(env)
                    tokens = _tokens(number, code(env))
                except MLError as exc:
                    raise UnsupportedNet(f"{t['name']}: output arc: {exc}")
                except Exception as exc:                       # noqa: BLE001
                    raise UnsupportedNet(f"{t['name']}: output arc could not "
                                         f"be evaluated ({exc})")
                for tok in tokens:
                    new[pidx].append(self._produced(pidx, tok, now + delay,
                                                    t["name"]))
        out = [tuple(sorted(tokens)) for tokens in new]
        if self.timed:
            out.append(now)
        return tuple(out)

    # Method to turn a produced value into the token a place stores.
    def _produced(self, pidx: int, tok, stamp: int, where: str):
        """The token an output arc deposits.

        Args:
            pidx (int): The output place.
            tok: The value, possibly ``Delayed``/``Stamped``.
            stamp (int): The occurrence time plus the transition's delay.
            where (str): The transition, for messages.

        Returns:
            The stored token.

        Raises:
            UnsupportedNet: For a delay on an untimed place.
        """
        if pidx in self.timed_places:
            if isinstance(tok, Delayed):
                return TimedToken(tok[0], stamp + tok[1])
            if isinstance(tok, Stamped):
                return TimedToken(tok[0], tok[1])
            return TimedToken(tok, stamp)
        if isinstance(tok, (Delayed, Stamped)):
            raise UnsupportedNet(f"{where}: a time inscription on an arc to the "
                                 f"untimed place {self.places[pidx]['name']}")
        return tok


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
            self.page_instances[page["name"]] += 1
            instance = self.page_instances[page["name"]]
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
                                   "colset": pl.get("type"),
                                   "instance": instance,
                                   "ml": f"{page['ml']}'{pl['ml']}"}
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
                              "time_text": tr.get("time"),
                              "priority_text": tr.get("priority"),
                              "code_text": tr.get("code"),
                              "in_raw": ins, "out_raw": outs,
                              "instance": instance,
                              "ml": f"{page['ml']}'{tr['ml']}"})
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
        #: Places whose colour set is timed: their tokens carry timestamps,
        #: and the marking then ends with the global clock.
        self.timed_places = {i for i, p in enumerate(self.places)
                             if self._is_timed_colset(p.get("colset"))}
        self.timed = bool(self.timed_places)
        for t in trans:
            self._compile_transition(t, index)
            self.transitions.append(t)
        self.uses_priorities = len({t["priority"] for t in self.transitions}) > 1
        #: Whether partial-order reduction applies: independence does not
        #: survive a global clock or priorities.
        self.reducible = not self.timed and not self.uses_priorities




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
            try:
                number = count if isinstance(count, int) else count({})
                tokens.extend(_tokens(number, value({})))
            except MLError as exc:
                raise UnsupportedNet(f"initial marking {text!r}: {exc}")
        return tokens






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
        if tag == "pcon":
            return ("pcon", pattern[1], rename(pattern[2]))
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
    if tag == "pcon":
        return IndexValue(pattern[1], _instantiate(pattern[2], env))
    raise UnsupportedNet(f"cannot rebuild the token matched by {tag!r}")
