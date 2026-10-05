"""User properties, written as text: no Python needed.

A property file holds one property per line; ``#`` starts a comment::

    # id  "name"                    formula
    ME1 "neighbours never eat together":
        AG !(has(Eat, ph(1)) & has(Eat, ph(2)))
    P2: AG (marked("Packets To Send") -> EF enabled("Send Packet"))
    AF dead

A line may continue on the next ones while brackets are open or after a
trailing ``:``. The id and the quoted name are optional (ids default to
``U1``, ``U2``, ...). The same text is accepted by ``cpncheck check --prop``.

Formulas
--------
====================================  ========================================
``dead``                              no binding element is enabled
``enabled(T)``                        some transition named ``T`` is enabled
``marked(P)`` / ``empty(P)``          some / no place named ``P`` has a token
``tokens(P) op k``                    the tokens of the places named ``P``,
                                      added up, compare with ``k``
                                      (``op``: ``< <= = >= > <>``)
``enabled_count(T) op k``             likewise, enabled binding elements
``has(P, v)``                         a place named ``P`` holds the token
                                      ``v``, a CPN ML value (``ph(1)``,
                                      ``(1, "COL")``)
``!f``, ``f & g``, ``f | g``,         negation, conjunction, disjunction,
``f -> g``                            implication (weakest, right-assoc.)
``AG f``, ``AF f``, ``EF f``, ``EG f``  the CTL operators
``E[f U g]``, ``A[f U g]``            until
====================================  ========================================

Dead markings have a self-loop, as everywhere in CPNCheck: ``AF f`` fails on a
run that stops before ``f``, and ``EG f`` holds on one that stops in ``f``.

Names
-----
A name is either bare (``Eat``, ``Top/Eat``, ``Sender/Send_Packet``) or
quoted (``"Packets To Send"``). It refers to

1. the element whose full path in the flattened net is that name
   (``Top/Sender/Send Packet``); otherwise
2. every element on the page so named (``Sender/Send Packet``, all instances
   of the page); otherwise
3. every element with that name, wherever it is (``Eat``).

A name that matches nothing is an error that lists the names that exist.
"""

import collections
import re
from typing import Dict, List, Optional, Sequence, Tuple

from .coloured import ColouredNet, _canon
from .cpnml import MLError
from .formula import (AF, AG, COMPARISONS, EF, EU, And, Dead, Enabled,
                      EnabledTally, Formula, Holds, Marked, Not, Or, TokenCount)
from .properties import Property
from .selectors import Explicit

__all__ = ["QueryError", "UserProperty", "parse_formula", "parse_properties",
           "load_properties"]


# Exception raised for a property that cannot be read.
class QueryError(ValueError):
    """A property that does not parse, or names something the net lacks."""


# Class holding one user property before it is resolved against a net.
class UserProperty:
    """``id``, optional name and formula text of one user property.

    Attributes:
        id (str): The identifier the verdict is reported under.
        name (str): A short name.
        text (str): The formula as written.
    """

    __slots__ = ("id", "name", "text")

    # Method to hold one user property.
    def __init__(self, id: str, text: str, name: Optional[str] = None):
        """Create the property.

        Args:
            id (str): Identifier.
            text (str): Formula text.
            name (str, optional): Short name; the formula when omitted.
        """
        self.id = id
        self.text = text
        self.name = name or text

    # Method to describe the property in the report.
    def descriptor(self) -> Property:
        """The catalog entry the verdict is reported under.

        Returns:
            Property: A ``desired`` CTL property.
        """
        return Property(self.id, self.name[:28], self.text, "desired", (),
                        f"User property: {self.text}")

    # Method to render the property for debugging.
    def __repr__(self):
        """Return a short representation.

        Returns:
            str: ``<UserProperty P1: AG ...>``.
        """
        return f"<UserProperty {self.id}: {self.text}>"


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r"""
    (?P<space>\s+)
  | (?P<str>"(?:[^"\\]|\\.)*")
  | (?P<op>->|<=|>=|<>|!=|==|[!&|()\[\],<>=:])
  | (?P<int>\d+)
  | (?P<name>[A-Za-z_][A-Za-z0-9_'./#-]*)
""", re.X)

# Function to split a formula into tokens.
def _tokenize(text: str) -> List[Tuple[str, str, int]]:
    """Turn formula text into ``(kind, value, position)`` tokens.

    Args:
        text (str): The formula.

    Returns:
        list: Tokens, ending with ``("end", "", len(text))``.

    Raises:
        QueryError: On a character that starts no token.
    """
    out, i = [], 0
    while i < len(text):
        m = _TOKEN.match(text, i)
        if not m:
            raise QueryError(f"unexpected {text[i]!r} at {i} in {text!r}")
        kind = m.lastgroup
        if kind != "space":
            value = m.group(kind)
            if kind == "str":
                value = bytes(value[1:-1], "utf-8").decode("unicode_escape")
            out.append((kind, value, i))
        i = m.end()
    out.append(("end", "", len(text)))
    return out


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

# Class turning formula text into a formula over a net.
class _Parser:
    """Recursive descent over the grammar in the module docstring."""

    # Method to start parsing.
    def __init__(self, text: str, net: ColouredNet):
        """Create the parser.

        Args:
            text (str): The formula.
            net (ColouredNet): The net names are resolved against.
        """
        self.text = text
        self.net = net
        self.tokens = _tokenize(text)
        self.pos = 0

    # Method to look at the next token.
    def peek(self, offset: int = 0):
        """The token ``offset`` ahead.

        Args:
            offset (int): How far ahead.

        Returns:
            tuple: The token.
        """
        return self.tokens[min(self.pos + offset, len(self.tokens) - 1)]

    # Method to consume one token.
    def next(self):
        """Read one token.

        Returns:
            tuple: The token.
        """
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    # Method to consume a required token.
    def expect(self, value: str):
        """Read a token with a given value.

        Args:
            value (str): The value required.

        Raises:
            QueryError: When something else is found.
        """
        token = self.next()
        if token[1] != value or token[0] not in ("op", "name"):
            raise QueryError(f"expected {value!r} at {token[2]}, found "
                             f"{token[1] or 'the end'!r} in {self.text!r}")

    # Method to test for a token without consuming it otherwise.
    def accept(self, value: str) -> bool:
        """Read a token if it has a given value.

        Args:
            value (str): The value.

        Returns:
            bool: Whether it was read.
        """
        if self.peek()[1] == value and self.peek()[0] in ("op", "name"):
            self.pos += 1
            return True
        return False

    # Method to parse a complete formula.
    def formula(self) -> Formula:
        """Parse the whole text.

        Returns:
            Formula: The formula.

        Raises:
            QueryError: On trailing input.
        """
        phi = self.implication()
        if self.peek()[0] != "end":
            token = self.peek()
            raise QueryError(f"unexpected {token[1]!r} at {token[2]} in "
                             f"{self.text!r}")
        return phi

    # Method to parse an implication.
    def implication(self) -> Formula:
        """``f -> g``, right-associative, weakest of all.

        Returns:
            Formula: The formula.
        """
        left = self.disjunction()
        if self.accept("->"):
            return Or(Not(left), self.implication())
        return left

    # Method to parse a disjunction.
    def disjunction(self) -> Formula:
        """``f | g | ...``.

        Returns:
            Formula: The formula.
        """
        parts = [self.conjunction()]
        while self.accept("|"):
            parts.append(self.conjunction())
        return parts[0] if len(parts) == 1 else Or(*parts)

    # Method to parse a conjunction.
    def conjunction(self) -> Formula:
        """``f & g & ...``.

        Returns:
            Formula: The formula.
        """
        parts = [self.unary()]
        while self.accept("&"):
            parts.append(self.unary())
        return parts[0] if len(parts) == 1 else And(*parts)

    # Method to parse a prefix operator or an atom.
    def unary(self) -> Formula:
        """``!f``, the temporal operators, brackets and atoms.

        Returns:
            Formula: The formula.

        Raises:
            QueryError: On a token that starts no formula.
        """
        kind, value, where = self.peek()
        if kind == "op" and value == "!":
            self.next()
            return Not(self.unary())
        if kind == "op" and value == "(":
            self.next()
            phi = self.implication()
            self.expect(")")
            return phi
        if kind == "name" and value in ("AG", "AF", "EF", "EG"):
            self.next()
            operand = self.unary()
            if value == "AG":
                return AG(operand)
            if value == "AF":
                return AF(operand)
            if value == "EF":
                return EF(operand)
            return Not(AF(Not(operand)), note=f"EG {operand}")
        if kind == "name" and value in ("E", "A") and self.peek(1)[1] == "[":
            self.next()
            self.next()
            hold = self.implication()
            self.expect("U")
            target = self.implication()
            self.expect("]")
            if value == "E":
                return EU(hold, target)
            # A[f U g] = AF g and no path keeps !g until both are false.
            return And(AF(target),
                       Not(EU(Not(target), And(Not(hold), Not(target)))))
        if kind == "name":
            return self.atom()
        raise QueryError(f"a formula cannot start with {value or 'the end'!r} "
                         f"at {where} in {self.text!r}")

    # Method to parse an atomic proposition.
    def atom(self) -> Formula:
        """``dead`` and the propositions over named places and transitions.

        Returns:
            Formula: The proposition.

        Raises:
            QueryError: On an unknown proposition.
        """
        _kind, value, where = self.next()
        if value == "dead":
            return Dead()
        if value in ("enabled", "marked", "empty", "tokens", "enabled_count",
                     "has"):
            self.expect("(")
            transitions = value in ("enabled", "enabled_count")
            selector = self.reference("transition" if transitions else "place")
            if value == "has":
                return self.has(selector)
            self.expect(")")
            if value == "enabled":
                return Enabled(selector)
            if value == "marked":
                return Marked(selector)
            if value == "empty":
                return Not(Marked(selector), note=f"{selector.label} empty")
            op, limit = self.comparison()
            if value == "tokens":
                return TokenCount(selector, op, limit)
            return EnabledTally(selector, op, limit)
        raise QueryError(f"unknown proposition {value!r} at {where} in "
                         f"{self.text!r}; the propositions are dead, "
                         "enabled, marked, empty, tokens, enabled_count, has")

    # Method to parse the comparison after a counting proposition.
    def comparison(self) -> Tuple[str, int]:
        """``op k``.

        Returns:
            tuple: ``(op, k)`` with ``==``/``!=`` read as ``=``/``<>``.

        Raises:
            QueryError: When no comparison follows.
        """
        _kind, op, where = self.next()
        op = {"==": "=", "!=": "<>"}.get(op, op)
        if op not in COMPARISONS:
            raise QueryError(f"expected a comparison at {where} in "
                             f"{self.text!r}")
        kind, number, where = self.next()
        if kind != "int":
            raise QueryError(f"expected a number at {where} in {self.text!r}")
        return op, int(number)

    # Method to parse has(P, v).
    def has(self, selector) -> Formula:
        """The value part of ``has(P, v)``: CPN ML text up to the closing bracket.

        Args:
            selector (Explicit): The places.

        Returns:
            Formula: The proposition.

        Raises:
            QueryError: When the value is missing or cannot be evaluated.
        """
        self.expect(",")
        start = self.peek()[2]
        depth, i, quoted = 0, start, False
        while i < len(self.text):
            ch = self.text[i]
            if ch == '"' and (i == 0 or self.text[i - 1] != "\\"):
                quoted = not quoted
            elif not quoted and ch in "([{":
                depth += 1
            elif not quoted and ch in ")]}":
                if depth == 0:
                    break
                depth -= 1
            i += 1
        ml_text = self.text[start:i].strip()
        if not ml_text or i >= len(self.text):
            raise QueryError(f"has(...) needs a value and a closing bracket "
                             f"in {self.text!r}")
        try:
            value = _canon(self.net.declarations.evaluate(ml_text))
        except MLError as exc:
            raise QueryError(f"has(..., {ml_text}): {exc}")
        while self.peek()[2] < i:
            self.next()
        self.expect(")")
        return Holds(selector, value, ml_text)

    # Method to resolve a name to places or transitions.
    def reference(self, kind: str) -> Explicit:
        """Resolve a bare or quoted name, as the module docstring describes.

        Args:
            kind (str): ``"place"`` or ``"transition"``.

        Returns:
            Explicit: The selected elements, labelled with the name.

        Raises:
            QueryError: When the name matches nothing.
        """
        token_kind, name, where = self.next()
        if token_kind not in ("name", "str"):
            raise QueryError(f"expected a {kind} name at {where} in "
                             f"{self.text!r}")
        return resolve(self.net, kind, name)


# Function to resolve a name against a net.
def resolve(net: ColouredNet, kind: str, name: str) -> Explicit:
    """The places or transitions a name refers to.

    Args:
        net (ColouredNet): The net.
        kind (str): ``"place"`` or ``"transition"``.
        name (str): The name, as written in the property.

    Returns:
        Explicit: The elements.

    Raises:
        QueryError: When nothing matches; the message lists what exists.
    """
    elements = net.places if kind == "place" else net.transitions
    wanted = " ".join(name.split())
    rules = (lambda e: e["gid"] == wanted,
             lambda e: f"{e['page']}/{e['name']}" == wanted,
             lambda e: e["name"] == wanted)
    for rule in rules:
        found = tuple(i for i, e in enumerate(elements) if rule(e))
        if found:
            return Explicit(found, kind, wanted)
    known = sorted({e["name"] for e in elements})
    raise QueryError(f"no {kind} named {name!r}; the {kind}s are: "
                     f"{', '.join(known[:30])}"
                     f"{' ...' if len(known) > 30 else ''}")


# Function to parse one formula against a net.
def parse_formula(text: str, net: ColouredNet) -> Formula:
    """Parse property text into a formula over a net.

    Args:
        text (str): The formula.
        net (ColouredNet): The net its names refer to.

    Returns:
        Formula: The formula.

    Raises:
        QueryError: When it does not parse or names something the net lacks.
    """
    return _Parser(text, net).formula()


_HEAD = re.compile(r'^\s*(?:(?P<id>[A-Za-z][A-Za-z0-9_.-]*)\s*'
                   r'(?:"(?P<name>[^"]*)")?\s*:(?!=))?\s*(?P<body>.*)$', re.S)


# Function to read property definitions from text.
def parse_properties(text: str, first: int = 1) -> List[UserProperty]:
    """Read ``[id ["name"]:] formula`` definitions, one per logical line.

    A definition continues on the next lines while brackets are open or when
    its line ends with ``:``. ``#`` starts a comment (outside quotes).

    Args:
        text (str): The definitions.
        first (int): Number of the first automatic id (``U<first>``).

    Returns:
        list: The properties, in order.

    Raises:
        QueryError: On a duplicate id or an empty definition.
    """
    logical: List[str] = []
    pending = ""
    for raw in text.splitlines():
        line = _strip_comment(raw).rstrip()
        if not line.strip() and not pending:
            continue
        pending = f"{pending} {line.strip()}" if pending else line.strip()
        if _open_brackets(pending) > 0 or pending.endswith(":"):
            continue
        logical.append(pending)
        pending = ""
    if pending.strip():
        logical.append(pending)

    out: List[UserProperty] = []
    seen = set()
    counter = first
    for entry in logical:
        m = _HEAD.match(entry)
        pid, name, body = m.group("id"), m.group("name"), m.group("body").strip()
        if pid in {"AG", "AF", "EF", "EG"} or not body:
            pid, name, body = None, None, entry.strip()
        if not body:
            raise QueryError(f"empty property {entry!r}")
        if pid is None:
            while f"U{counter}" in seen:
                counter += 1
            pid = f"U{counter}"
            counter += 1
        if pid in seen:
            raise QueryError(f"duplicate property id {pid!r}")
        seen.add(pid)
        out.append(UserProperty(pid, body, name))
    return out


# Function to read property definitions from a file.
def load_properties(path: str) -> List[UserProperty]:
    """Read a property file.

    Args:
        path (str): The file.

    Returns:
        list: The properties.
    """
    with open(path, encoding="utf-8") as fh:
        return parse_properties(fh.read())


# Function to drop a comment from one line.
def _strip_comment(line: str) -> str:
    """The line up to a ``#`` outside quotes.

    Args:
        line (str): One line.

    Returns:
        str: The line without its comment.
    """
    quoted = False
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif ch == "#" and not quoted:
            return line[:i]
    return line


# Function to count the brackets still open in a text.
def _open_brackets(text: str) -> int:
    """Brackets opened and not closed, outside quotes.

    Args:
        text (str): The text.

    Returns:
        int: The depth at the end.
    """
    depth, quoted = 0, False
    for ch in text:
        if ch == '"':
            quoted = not quoted
        elif not quoted and ch in "([{":
            depth += 1
        elif not quoted and ch in ")]}":
            depth -= 1
    return depth
