"""CPN ML: a lexer, a parser and a compiler for the expression language.

CPN Tools writes guards, arc inscriptions and initial markings as CPN ML, a
subset of Standard ML. Reading them with regular expressions works for the
shapes a generator emits and fails on the ones people write, so this is a real
parser: ``if``/``then``/``else``, ``let``/``in``/``end``, ``case``/``of``,
``fn``, function application, the operators with their SML precedences, lists,
tuples, records and multisets.

An expression compiles to a Python closure over an environment, rather than
being interpreted node by node, so the occurrence-graph search stays fast: the
tree is walked once, at compile time, and firing a binding element then costs
one call per node.

Multisets are values: ``2`x``, ``ms1 ++ ms2``, ``ms1 -- ms2`` and ``empty``
may appear anywhere, so ``if ok then 1`p else empty`` is an expression like any
other. Names a net declares as constants (the values of an enumeration colour
set) and constructors (``u`` of ``index u with 1..n``) are passed to the parser
as *symbols*, because a pattern cannot tell ``e`` the constant from ``e`` a
variable without knowing the declarations -- and reading a constant as a
variable would make an input arc accept any token.

What is deliberately absent: references, exceptions, ``while``, and
user-defined datatypes. An expression using them raises :class:`MLError`,
which the caller turns into a refusal to analyse the net -- never into a
guess.
"""

import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "MLError",
    "MultiSet",
    "EnumValue",
    "IndexValue",
    "IndexConstructor",
    "parse_expression",
    "parse_pattern",
    "parse_declarations",
    "compile_expression",
    "compile_pattern",
    "match_pattern",
    "pattern_variables",
    "free_variables",
    "PRELUDE",
]


# Exception raised when CPN ML cannot be read or run.
class MLError(Exception):
    """The expression is outside the fragment, or cannot be evaluated."""


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

#: Words with a meaning of their own.
KEYWORDS = {
    "if", "then", "else", "let", "val", "in", "end", "fun", "fn", "case", "of",
    "andalso", "orelse", "not", "div", "mod", "true", "false", "nil", "rec",
}

#: Operators, longest first so that ``<=`` is not read as ``<`` then ``=``.
OPERATORS = [
    "=>", "->", "<=", ">=", "<>", "::", "++", "--", "@", "^^", "^", "+", "-", "*",
    "/",
    "<", ">", "=", "|", ":", ",", ";", "(", ")", "[", "]", "{", "}", "#", "~",
    "`", "_",
]

_REAL = re.compile(r"~?\d+\.\d*(?:[eE]~?[-+]?\d+)?|~?\d+[eE]~?[-+]?\d+")
_INT = re.compile(r"~?\d+")
# Qualified names such as ``List.nth`` are one identifier, not three.
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*")
_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')
_SPACE = re.compile(r"\s+")


# Function to split CPN ML source into tokens.
def tokenize(text: str) -> List[Tuple[str, Any, int]]:
    """Turn source into ``(kind, value, position)`` tokens.

    Args:
        text (str): CPN ML source.

    Returns:
        list: The tokens, ending with an ``end`` token.

    Raises:
        MLError: On a character that cannot start a token.
    """
    out: List[Tuple[str, Any, int]] = []
    i, n = 0, len(text)
    while i < n:
        m = _SPACE.match(text, i)
        if m:
            i = m.end()
            continue
        if text.startswith("(*", i):                    # nested ML comments
            depth, i = 1, i + 2
            while i < n and depth:
                if text.startswith("(*", i):
                    depth, i = depth + 1, i + 2
                elif text.startswith("*)", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            continue
        m = _STRING.match(text, i)
        if m:
            out.append(("str", m.group(0)[1:-1], i))
            i = m.end()
            continue
        m = _REAL.match(text, i)
        if m:
            out.append(("real", float(m.group(0).replace("~", "-")), i))
            i = m.end()
            continue
        m = _INT.match(text, i)
        if m:
            out.append(("int", int(m.group(0).replace("~", "-")), i))
            i = m.end()
            continue
        m = _IDENT.match(text, i)
        if m:
            word = m.group(0)
            if word == "_":                              # the wildcard pattern
                out.append(("op", "_", i))
            else:
                out.append((("kw" if word in KEYWORDS else "id"), word, i))
            i = m.end()
            continue
        for op in OPERATORS:
            if text.startswith(op, i):
                out.append(("op", op, i))
                i += len(op)
                break
        else:
            raise MLError(f"unexpected character {text[i]!r} at {i}")
    out.append(("end", None, n))
    return out


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

#: Binary operators, with their SML precedence and associativity.
BINOPS = {
    "orelse": (1, "left"), "andalso": (2, "left"),
    # Multisets: ++ and -- bind loosest, so 2`x ++ 1`y is (2`x) ++ (1`y); the
    # coefficient binds tighter than a comparison and looser than arithmetic,
    # so (n+1)`x and 2*k`x read as written.
    "++": (3, "left"), "--": (3, "left"), "`": (4.5, "right"),
    "=": (4, "left"), "<>": (4, "left"), "<": (4, "left"), ">": (4, "left"),
    "<=": (4, "left"), ">=": (4, "left"),
    "::": (5, "right"), "@": (5, "right"), "^^": (5, "right"),
    "+": (6, "left"), "-": (6, "left"), "^": (6, "left"),
    "*": (7, "left"), "/": (7, "left"), "div": (7, "left"), "mod": (7, "left"),
}

#: Where function application sits: tighter than every binary operator.
APPLICATION = 10


# Class turning a token stream into an expression tree.
class Parser:
    """A precedence-climbing parser for the CPN ML fragment.

    The tree is made of tuples, ``(tag, ...)``, which keeps it cheap to build
    and easy to walk; :func:`compile_expression` is the only thing that needs
    to know the tags.
    """

    # Method to start parsing a token stream.
    def __init__(self, tokens, source="", symbols=None):
        """Create the parser.

        Args:
            tokens (list): Tokens from :func:`tokenize`.
            source (str): The original text, for error messages.
            symbols (dict, optional): Declared constants and constructors,
                ``name -> value``; a value that is an
                :class:`IndexConstructor` makes the name a constructor.
        """
        self.tokens = tokens
        self.pos = 0
        self.source = source
        self.symbols = symbols or {}

    # Method to look at the current token.
    def peek(self):
        """The token about to be read.

        Returns:
            tuple: ``(kind, value, position)``.
        """
        return self.tokens[self.pos]

    # Method to consume the current token.
    def next(self):
        """Read one token and advance.

        Returns:
            tuple: The token read.
        """
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    # Method to consume a token of an expected shape.
    def expect(self, kind, value=None):
        """Read a token, refusing anything else.

        Args:
            kind (str): Expected kind.
            value: Expected value, when it matters.

        Returns:
            tuple: The token read.

        Raises:
            MLError: When the next token is not the one wanted.
        """
        token = self.next()
        if token[0] != kind or (value is not None and token[1] != value):
            want = value if value is not None else kind
            raise MLError(f"expected {want!r}, found {token[1]!r} "
                          f"in {self.source.strip()!r}")
        return token

    # Method to test and consume an optional token.
    def accept(self, kind, value=None) -> bool:
        """Read a token only if it is the one given.

        Args:
            kind (str): Expected kind.
            value: Expected value, when it matters.

        Returns:
            bool: Whether the token was consumed.
        """
        token = self.peek()
        if token[0] == kind and (value is None or token[1] == value):
            self.pos += 1
            return True
        return False

    # ------------------------------------------------------------------
    # Expressions
    # ------------------------------------------------------------------

    # Method to parse a complete expression.
    def expression(self, level: int = 0):
        """Parse an expression at or above a precedence level.

        Args:
            level (int): Minimum binding power.

        Returns:
            tuple: The expression tree.
        """
        kind, value, _ = self.peek()
        if kind == "kw" and value == "if":
            self.next()
            test = self.expression()
            self.expect("kw", "then")
            yes = self.expression()
            self.expect("kw", "else")
            return ("if", test, yes, self.expression())
        if kind == "kw" and value == "let":
            return self.let_expression()
        if kind == "kw" and value == "case":
            self.next()
            subject = self.expression()
            self.expect("kw", "of")
            return ("case", subject, self.match_rules())
        if kind == "kw" and value == "fn":
            self.next()
            return ("fn", self.match_rules())
        return self.binary(level)

    # Method to parse a let block.
    def let_expression(self):
        """Parse ``let val p = e ... in body end``.

        Returns:
            tuple: ``("let", bindings, body)``.

        Raises:
            MLError: On a declaration form that is not ``val`` or ``fun``.
        """
        self.expect("kw", "let")
        bindings = []
        while not (self.peek()[0] == "kw" and self.peek()[1] == "in"):
            if self.accept("kw", "val"):
                pattern = self.pattern()
                self.expect("op", "=")
                bindings.append(("val", pattern, self.expression()))
            elif self.accept("kw", "fun"):
                name, rule = self.fun_clause()
                bindings.append(("fun", name, rule))
            else:
                raise MLError(f"only val and fun may be declared in a let, "
                              f"found {self.peek()[1]!r}")
            self.accept("op", ";")
        self.expect("kw", "in")
        body = self.expression()
        self.expect("kw", "end")
        return ("let", bindings, body)

    # Method to parse the clauses of a fn or case.
    def match_rules(self):
        """Parse ``pattern => expression`` alternatives separated by ``|``.

        Returns:
            list: ``(pattern, expression)`` pairs.
        """
        rules = []
        while True:
            pattern = self.pattern()
            self.expect("op", "=>")
            rules.append((pattern, self.expression()))
            if not (self.peek()[0] == "op" and self.peek()[1] == "|"):
                return rules
            self.next()

    # Method to parse a fun declaration, with all of its clauses.
    def fun_clause(self):
        """Parse ``f p = e`` and any further ``| f p = e`` clauses.

        Several clauses are how a function is written by cases in ML, and the
        cases are tried in order -- which is what a multi-clause function
        means. Clauses that take several parameters are curried; several
        clauses *and* several parameters is refused rather than guessed at.

        Returns:
            tuple: ``(name, ("fn", [(pattern, body), ...]))``.

        Raises:
            MLError: On a multi-clause function of several parameters, or on
                clauses that do not all name the same function.
        """
        name = self.expect("id")[1]
        rules = []
        arity = None
        while True:
            params = []
            while not (self.peek()[0] == "op" and self.peek()[1] == "="):
                params.append(self.pattern())
            self.expect("op", "=")
            body = self.expression()
            if arity is not None and len(params) != arity:
                raise MLError(f"{name}: clauses take different numbers of "
                              "parameters")
            arity = len(params)
            rules.append((params, body))
            if not (self.peek()[0] == "op" and self.peek()[1] == "|"):
                break
            here = self.pos
            self.next()
            token = self.peek()
            if token[0] != "id" or token[1] != name:
                self.pos = here                  # the | belongs to something else
                break
            self.next()
        if len(rules) == 1:
            params, body = rules[0]
            for pattern in reversed(params):
                body = ("fn", [(pattern, body)])
            return name, body
        if arity != 1:
            raise MLError(f"{name}: several clauses with {arity} parameters "
                          "are not supported; rewrite them over a tuple")
        return name, ("fn", [(params[0], body) for params, body in rules])

    # Method to parse a binary-operator expression.
    def binary(self, level: int):
        """Precedence climbing over :data:`BINOPS`.

        Args:
            level (int): Minimum binding power.

        Returns:
            tuple: The expression tree.
        """
        left = self.application()
        while True:
            kind, value, _ = self.peek()
            if kind not in ("op", "kw") or value not in BINOPS:
                return left
            power, associativity = BINOPS[value]
            if power < level:
                return left
            self.next()
            right = self.binary(power + (1 if associativity == "left" else 0))
            left = ("binop", value, left, right)

    # Method to parse a chain of applications.
    def application(self):
        """Parse ``f x y``, which is ``(f x) y``.

        Returns:
            tuple: The expression tree.
        """
        expr = self.unary()
        while self.starts_atom():
            expr = ("app", expr, self.unary())
        return expr

    # Method to parse a possibly negated atom.
    def unary(self):
        """Parse ``~e`` and ``not e``, then an atom.

        Returns:
            tuple: The expression tree.
        """
        kind, value, _ = self.peek()
        if kind == "op" and value == "~":
            self.next()
            return ("neg", self.unary())
        if kind == "kw" and value == "not":
            self.next()
            return ("not", self.unary())
        return self.atom()

    # Method to tell whether an atom can start here.
    def starts_atom(self) -> bool:
        """Whether the next token can begin an argument.

        Returns:
            bool: True when an application may continue.
        """
        kind, value, _ = self.peek()
        if kind in ("int", "real", "str", "id"):
            return True
        if kind == "kw":
            return value in ("true", "false", "nil")
        return kind == "op" and value in ("(", "[", "{", "#", "~")

    # Method to parse one atomic expression.
    def atom(self):
        """Parse a literal, a name, a selector or a bracketed expression.

        Returns:
            tuple: The expression tree.

        Raises:
            MLError: On a token that cannot start an expression.
        """
        kind, value, _ = self.next()
        if kind in ("int", "real", "str"):
            return ("lit", value)
        if kind == "kw":
            if value == "true":
                return ("lit", True)
            if value == "false":
                return ("lit", False)
            if value == "nil":
                return ("list", [])
            raise MLError(f"{value!r} cannot start an expression")
        if kind == "id":
            return ("var", value)
        if value == "#":
            label = self.next()
            if label[0] not in ("id", "int"):
                raise MLError(f"#{label[1]!r} is not a field selector")
            return ("selector", label[1])
        if value == "(":
            if self.accept("op", ")"):
                return ("lit", ())                       # the unit value
            items = [self.expression()]
            if self.accept("op", ":"):
                self.skip_type()
            while self.accept("op", ","):
                items.append(self.expression())
                if self.accept("op", ":"):
                    self.skip_type()
            self.expect("op", ")")
            return items[0] if len(items) == 1 else ("tuple", items)
        if value == "[":
            items = []
            if not self.accept("op", "]"):
                items.append(self.expression())
                while self.accept("op", ","):
                    items.append(self.expression())
                self.expect("op", "]")
            return ("list", items)
        if value == "{":
            fields = []
            if not self.accept("op", "}"):
                while True:
                    label = self.next()[1]
                    self.expect("op", "=")
                    fields.append((str(label), self.expression()))
                    if not self.accept("op", ","):
                        break
                self.expect("op", "}")
            return ("record", fields)
        raise MLError(f"{value!r} cannot start an expression")

    # ------------------------------------------------------------------
    # Patterns
    # ------------------------------------------------------------------

    # Method to parse a pattern, including the list cons operator.
    def pattern(self):
        """Parse a pattern, right-associating ``::``.

        A pattern may carry a type annotation -- ``([] : real list)`` -- which
        is read and discarded: values here are Python values and carry their
        own type, so the annotation constrains nothing the checker does.

        Returns:
            tuple: The pattern tree.
        """
        left = self.pattern_atom()
        if self.accept("op", ":"):
            self.skip_type()
        if self.peek()[0] == "op" and self.peek()[1] == "::":
            self.next()
            return ("pcons", left, self.pattern())
        if self.accept("op", ":"):
            self.skip_type()
        return left

    # Method to consume a type expression without interpreting it.
    def skip_type(self):
        """Read past a type: names, ``*``, ``->`` and bracketed groups."""
        depth = 0
        while True:
            kind, value, _ = self.peek()
            if kind == "end":
                return
            if kind == "op":
                if value in ("(", "[", "{"):
                    depth += 1
                elif value in (")", "]", "}"):
                    if depth == 0:
                        return
                    depth -= 1
                elif depth == 0 and value not in ("*", "->", ","):
                    return
                elif depth == 0 and value == ",":
                    return
            elif kind == "kw":
                return
            self.next()

    # Method to parse one atomic pattern.
    def pattern_atom(self):
        """Parse a variable, a wildcard, a literal, a tuple, a list or a record.

        Returns:
            tuple: The pattern tree.

        Raises:
            MLError: On a token that cannot start a pattern.
        """
        kind, value, _ = self.next()
        if kind == "id":
            symbol = self.symbols.get(value, _MISSING)
            if isinstance(symbol, IndexConstructor):
                return ("pcon", value, self.pattern_atom())
            if symbol is not _MISSING:
                return ("plit", symbol)          # a declared constant
            return ("pvar", value)
        if kind in ("int", "real", "str"):
            return ("plit", value)
        if kind == "kw" and value in ("true", "false"):
            return ("plit", value == "true")
        if kind == "kw" and value == "nil":
            return ("plist", [])
        if kind == "op" and value == "_":
            return ("pwild",)
        if kind == "op" and value == "~":
            token = self.next()
            if token[0] not in ("int", "real"):
                raise MLError("~ in a pattern must precede a number")
            return ("plit", -token[1])
        if kind == "op" and value == "(":
            if self.accept("op", ")"):
                return ("plit", ())
            items = [self.pattern()]
            while self.accept("op", ","):
                items.append(self.pattern())
            self.expect("op", ")")
            return items[0] if len(items) == 1 else ("ptuple", items)
        if kind == "op" and value == "[":
            items = []
            if not self.accept("op", "]"):
                items.append(self.pattern())
                while self.accept("op", ","):
                    items.append(self.pattern())
                self.expect("op", "]")
            return ("plist", items)
        if kind == "op" and value == "{":
            fields = []
            if not self.accept("op", "}"):
                while True:
                    label = str(self.next()[1])
                    self.expect("op", "=")
                    fields.append((label, self.pattern()))
                    if not self.accept("op", ","):
                        break
                self.expect("op", "}")
            return ("precord", fields)
        raise MLError(f"{value!r} cannot start a pattern")

    # ------------------------------------------------------------------
    # Multisets
    # ------------------------------------------------------------------

    # Method to parse a multiset of expressions.
    def multiset(self):
        """Parse ``2`x ++ 1`y``, the form of an arc inscription.

        The inscription is one expression; its top-level ``++`` and the
        coefficient operator are then read off as terms, so a simple
        inscription keeps the shape ``[(coefficient, value), ...]``. A term
        without a coefficient is one token, which is how CPN Tools lets a
        plain expression stand for a singleton multiset -- and a term whose
        value is itself a multiset (``if ok then 1`p else empty``) is
        evaluated as one.

        Returns:
            list: ``(coefficient expression or None, value expression)``.
        """
        return _terms_of(self.expression())


# Function to read the top-level terms of a multiset expression.
def _terms_of(tree) -> List[Tuple[Any, Any]]:
    """Split ``a ++ b`` and ``n`x`` at the top of a tree into terms.

    Args:
        tree (tuple): An expression tree.

    Returns:
        list: ``(coefficient tree or None, value tree)`` pairs.
    """
    if tree[0] == "binop" and tree[1] == "++":
        return _terms_of(tree[2]) + _terms_of(tree[3])
    if tree[0] == "binop" and tree[1] == "`":
        return [(tree[2], tree[3])]
    return [(None, tree)]


# ---------------------------------------------------------------------------
# The public parsing entry points
# ---------------------------------------------------------------------------

# Function to parse one expression.
def parse_expression(text: str, symbols=None):
    """Parse a complete CPN ML expression.

    Args:
        text (str): The source.
        symbols (dict, optional): Declared constants and constructors.

    Returns:
        tuple: The expression tree.

    Raises:
        MLError: On a syntax error or trailing input.
    """
    parser = Parser(tokenize(text), text, symbols)
    tree = parser.expression()
    if parser.peek()[0] != "end":
        raise MLError(f"unexpected {parser.peek()[1]!r} after an expression "
                      f"in {text.strip()!r}")
    return tree


# Function to parse one pattern.
def parse_pattern(text: str, symbols=None):
    """Parse a complete CPN ML pattern.

    Args:
        text (str): The source.
        symbols (dict, optional): Declared constants and constructors.

    Returns:
        tuple: The pattern tree.

    Raises:
        MLError: On a syntax error or trailing input.
    """
    parser = Parser(tokenize(text), text, symbols)
    tree = parser.pattern()
    if parser.peek()[0] != "end":
        raise MLError(f"unexpected {parser.peek()[1]!r} after a pattern "
                      f"in {text.strip()!r}")
    return tree


# Function to parse a multiset expression.
def parse_multiset(text: str, symbols=None):
    """Parse an arc inscription, which is a multiset of expressions.

    Args:
        text (str): The source.
        symbols (dict, optional): Declared constants and constructors.

    Returns:
        list: ``(coefficient tree or None, value tree)`` per term.

    Raises:
        MLError: On a syntax error or trailing input.
    """
    parser = Parser(tokenize(text), text, symbols)
    terms = parser.multiset()
    if parser.peek()[0] != "end":
        raise MLError(f"unexpected {parser.peek()[1]!r} after a multiset "
                      f"in {text.strip()!r}")
    return terms


# Function to parse a block of declarations.
def parse_declarations(text: str, symbols=None) -> List[Tuple]:
    """Parse ``val`` and ``fun`` declarations, skipping anything else.

    CPN Tools keeps colour sets and variables as structured XML and only uses
    ``<ml>`` blocks for values and functions, so those are what this reads. A
    declaration it does not understand is skipped rather than fatal: a net may
    declare things the checker never needs.

    Args:
        text (str): The source of one or more declarations.
        symbols (dict, optional): Declared constants and constructors.

    Returns:
        list: ``("val", pattern, expression)`` and ``("fun", name, expression)``
        entries in order, with ``("error", message)`` for a declaration that
        could not be read.
    """
    out: List[Tuple] = []
    parser = Parser(tokenize(text), text, symbols)
    while parser.peek()[0] != "end":
        start = parser.pos
        try:
            if parser.accept("kw", "val"):
                pattern = parser.pattern()
                parser.expect("op", "=")
                out.append(("val", pattern, parser.expression()))
            elif parser.accept("kw", "fun"):
                name, rule = parser.fun_clause()
                out.append(("fun", name, rule))
            else:
                parser.next()
                continue
        except MLError as exc:
            parser.pos = start + 1
            named = ""
            if parser.peek()[0] == "id":
                named = f"{parser.peek()[1]}: "
            out.append(("error", f"{named}{exc}"))
            _skip_to_semicolon(parser)
            continue
        parser.accept("op", ";")
    return out


# Function to skip past the end of a declaration.
def _skip_to_semicolon(parser: Parser) -> None:
    """Advance to just after the next ``;``.

    Args:
        parser (Parser): The parser to advance.
    """
    while parser.peek()[0] != "end":
        if parser.next()[:2] == ("op", ";"):
            return


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------
#
# Token values have to be hashable and orderable, because a marking is a sorted
# tuple of them and two markings are the same node exactly when they are equal.
# So an ML list is a Python tuple, a record is a tuple in declared field order,
# and unit is the empty tuple.


#: Marks a name absent from the symbol table (None is a legitimate value).
_MISSING = object()


# Class holding a multiset value.
class MultiSet:
    """A finite multiset: value -> positive count.

    Immutable and hashable, so it can be compared and used as a value; a
    place's marking is still a sorted tuple of tokens, and a multiset an arc
    produces is expanded into it.

    Attributes:
        counts (dict): ``value -> count``, counts positive.
    """

    __slots__ = ("counts", "_hash")

    # Method to build a multiset.
    def __init__(self, counts=None):
        """Create the multiset.

        Args:
            counts (dict, optional): ``value -> count``; zero counts dropped.

        Raises:
            MLError: On a negative count.
        """
        clean = {}
        for value, count in (counts or {}).items():
            if count < 0:
                raise MLError(f"negative coefficient {count} for {value!r}")
            if count:
                clean[value] = count
        self.counts = clean
        self._hash = None

    # Method to list the elements with their counts.
    def items(self):
        """``(value, count)`` pairs.

        Returns:
            iterable: The pairs.
        """
        return self.counts.items()

    # Method to give the total number of elements.
    def __len__(self):
        """Number of elements, counting multiplicity.

        Returns:
            int: The size.
        """
        return sum(self.counts.values())

    # Method to compare two multisets.
    def __eq__(self, other):
        """Equality as multisets.

        Args:
            other: Another value.

        Returns:
            bool: Whether both hold the same elements equally often.
        """
        return isinstance(other, MultiSet) and self.counts == other.counts

    # Method to hash the multiset.
    def __hash__(self):
        """Hash compatible with equality.

        Returns:
            int: The hash.
        """
        if self._hash is None:
            self._hash = hash(frozenset(self.counts.items()))
        return self._hash

    # Method to render the multiset as CPN ML.
    def __repr__(self):
        """Render as ``2`x ++ 1`y``.

        Returns:
            str: The text.
        """
        if not self.counts:
            return "empty"
        return " ++ ".join(f"{c}`{v!r}" for v, c in self.counts.items())


# Function to coerce a value into a multiset.
def _as_multiset(value) -> "MultiSet":
    """A multiset as is; any other value as the singleton holding it.

    Args:
        value: A value.

    Returns:
        MultiSet: The multiset.
    """
    return value if isinstance(value, MultiSet) else MultiSet({value: 1})


# Function to build n copies of a value.
def _ms_scale(count, value) -> "MultiSet":
    """``n`x``: ``n`` copies of ``x``, or ``n`` times a multiset ``x``.

    Args:
        count (int): The coefficient.
        value: The element, or a multiset to scale.

    Returns:
        MultiSet: The result.

    Raises:
        MLError: When the coefficient is not a non-negative integer.
    """
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise MLError(f"a coefficient must be a non-negative integer, not "
                      f"{count!r}")
    if isinstance(value, MultiSet):
        return MultiSet({v: c * count for v, c in value.items()})
    return MultiSet({value: count})


# Function to add two multisets.
def _ms_union(left, right) -> "MultiSet":
    """``a ++ b``.

    Args:
        left: A multiset (or a value, as a singleton).
        right: A multiset (or a value, as a singleton).

    Returns:
        MultiSet: The sum.
    """
    out = dict(_as_multiset(left).counts)
    for value, count in _as_multiset(right).items():
        out[value] = out.get(value, 0) + count
    return MultiSet(out)


# Function to subtract one multiset from another.
def _ms_diff(left, right) -> "MultiSet":
    """``a -- b``, defined only when ``b`` is contained in ``a``.

    Args:
        left: A multiset.
        right: A multiset.

    Returns:
        MultiSet: The difference.

    Raises:
        MLError: When ``b`` is not contained in ``a``, as in CPN ML.
    """
    out = dict(_as_multiset(left).counts)
    for value, count in _as_multiset(right).items():
        if out.get(value, 0) < count:
            raise MLError(f"cannot subtract {count}`{value!r}: not contained")
        out[value] -= count
    return MultiSet(out)


# Class holding a value of an enumeration colour set.
class EnumValue(str):
    """A constant of ``colset E = with a | b``.

    A string subclass, so it hashes, compares and sorts like its name, and is
    shown as the bare name rather than quoted.
    """

    __slots__ = ()

    # Method to render the constant.
    def __repr__(self):
        """The bare name.

        Returns:
            str: The constant as CPN ML writes it.
        """
        return str(self)


# Class holding a value of an index colour set.
class IndexValue(tuple):
    """``u(3)`` of ``colset U = index u with 1..10``: a (constructor, index) pair.

    A tuple subclass, so it hashes and orders; the coloured net's ``_canon``
    must not turn it into a plain tuple.
    """

    __slots__ = ()

    # Method to build an index value.
    def __new__(cls, constructor: str, index: int):
        """Create the value.

        Args:
            constructor (str): The constructor name.
            index (int): The index.

        Returns:
            IndexValue: The value.
        """
        return super().__new__(cls, (constructor, index))

    # Method to render the value.
    def __repr__(self):
        """Render as ``u(3)``.

        Returns:
            str: The value as CPN ML writes it.
        """
        return f"{self[0]}({self[1]})"


# Class building the values of an index colour set.
class IndexConstructor:
    """The constructor ``u`` of ``index u with low..high``: ``u(i)`` is a value.

    Attributes:
        name (str): The constructor.
        low (int|None): Lowest index, once the declarations are evaluated.
        high (int|None): Highest index.
    """

    __slots__ = ("name", "low", "high")

    # Method to create the constructor.
    def __init__(self, name: str, low=None, high=None):
        """Create the constructor.

        Args:
            name (str): The constructor name.
            low (int, optional): Lowest index.
            high (int, optional): Highest index.
        """
        self.name = name
        self.low = low
        self.high = high

    # Method to apply the constructor.
    def __call__(self, index):
        """Build ``name(index)``.

        Args:
            index (int): The index.

        Returns:
            IndexValue: The value.

        Raises:
            MLError: When the index is outside the declared range.
        """
        if self.low is not None and not self.low <= index <= self.high:
            raise MLError(f"{self.name}({index}) is outside "
                          f"{self.low}..{self.high}")
        return IndexValue(self.name, index)

    # Method to render the constructor.
    def __repr__(self):
        """Return a short representation.

        Returns:
            str: ``<constructor u>``.
        """
        return f"<constructor {self.name}>"


# Class holding a function value with the environment it closed over.
class Closure:
    """A CPN ML function: clauses, and the bindings visible where it was written.

    Attributes:
        rules (list): ``(pattern, compiled body)`` clauses, tried in order.
        env (dict): The captured environment.
        name (str): For error messages.
    """

    __slots__ = ("rules", "env", "name")

    # Method to build a function value.
    def __init__(self, rules, env, name="fn"):
        """Create the closure.

        Args:
            rules (list): ``(pattern, compiled body)`` clauses.
            env (dict): Captured bindings.
            name (str): Name used in error messages.
        """
        self.rules = rules
        self.env = env
        self.name = name

    # Method to apply the function to an argument.
    def __call__(self, argument):
        """Match the argument against each clause and run the first that fits.

        Args:
            argument: The argument value.

        Returns:
            The result.

        Raises:
            MLError: When no clause matches.
        """
        for pattern, body in self.rules:
            bound = match_pattern(pattern, argument, self.env)
            if bound is not None:
                return body(bound)
        raise MLError(f"{self.name}: no clause matches {argument!r}")

    # Method to render the closure for debugging.
    def __repr__(self):
        """Return a short representation.

        Returns:
            str: ``<fn decide>``.
        """
        return f"<fn {self.name}>"


# ---------------------------------------------------------------------------
# Pattern matching
# ---------------------------------------------------------------------------

# Function to match a pattern against a value.
def match_pattern(pattern, value, env: Optional[Dict] = None,
                  fields: Optional[Dict[str, int]] = None):
    """Extend an environment so that a pattern denotes a value.

    Args:
        pattern (tuple): A pattern tree.
        value: The value to match.
        env (dict, optional): Bindings already made.
        fields (dict, optional): ``label -> index`` for record patterns.

    Returns:
        dict|None: The extended bindings, or None when the pattern does not
        match. The environment passed in is never modified.
    """
    tag = pattern[0]
    if tag == "pwild":
        return dict(env) if env is not None else {}
    if tag == "pvar":
        name = pattern[1]
        current = env or {}
        if name in current:
            return dict(current) if current[name] == value else None
        out = dict(current)
        out[name] = value
        return out
    if tag == "plit":
        if pattern[1] is True or pattern[1] is False:
            return dict(env or {}) if value is pattern[1] else None
        return dict(env or {}) if pattern[1] == value else None
    if tag == "ptuple":
        items = pattern[1]
        if not isinstance(value, tuple) or len(value) != len(items):
            return None
        out = dict(env or {})
        for sub, item in zip(items, value):
            out = match_pattern(sub, item, out, fields)
            if out is None:
                return None
        return out
    if tag == "plist":
        items = pattern[1]
        if not isinstance(value, tuple) or len(value) != len(items):
            return None
        out = dict(env or {})
        for sub, item in zip(items, value):
            out = match_pattern(sub, item, out, fields)
            if out is None:
                return None
        return out
    if tag == "pcons":
        if not isinstance(value, tuple) or not value:
            return None
        out = match_pattern(pattern[1], value[0], env, fields)
        if out is None:
            return None
        return match_pattern(pattern[2], value[1:], out, fields)
    if tag == "pcon":
        if not isinstance(value, IndexValue) or value[0] != pattern[1]:
            return None
        return match_pattern(pattern[2], value[1], env, fields)
    if tag == "precord":
        if not isinstance(value, tuple):
            return None
        out = dict(env or {})
        for label, sub in pattern[1]:
            index = _field_index(label, fields)
            if index is None or index >= len(value):
                return None
            out = match_pattern(sub, value[index], out, fields)
            if out is None:
                return None
        return out
    raise MLError(f"cannot match {tag!r}")


# Function to list the variables a pattern binds.
def pattern_variables(pattern) -> set:
    """Names a pattern binds.

    Args:
        pattern (tuple): A pattern tree.

    Returns:
        set: The bound names.
    """
    tag = pattern[0]
    if tag == "pvar":
        return {pattern[1]}
    if tag in ("ptuple", "plist"):
        out = set()
        for sub in pattern[1]:
            out |= pattern_variables(sub)
        return out
    if tag == "pcons":
        return pattern_variables(pattern[1]) | pattern_variables(pattern[2])
    if tag == "pcon":
        return pattern_variables(pattern[2])
    if tag == "precord":
        out = set()
        for _label, sub in pattern[1]:
            out |= pattern_variables(sub)
        return out
    return set()


# Function to list the names an expression reads without binding.
def free_variables(tree) -> set:
    """Names an expression uses but does not itself bind.

    A transition's guard and output arcs may mention variables no input arc
    binds; those are the ones that have to be enumerated over their colour
    set, which is how CPN Tools finds binding elements.

    Args:
        tree (tuple): An expression tree.

    Returns:
        set: The free names.
    """
    tag = tree[0]
    if tag == "var":
        return {tree[1]}
    if tag in ("lit", "selector"):
        return set()
    if tag in ("neg", "not"):
        return free_variables(tree[1])
    if tag == "binop":
        return free_variables(tree[2]) | free_variables(tree[3])
    if tag == "if":
        return (free_variables(tree[1]) | free_variables(tree[2])
                | free_variables(tree[3]))
    if tag == "app":
        return free_variables(tree[1]) | free_variables(tree[2])
    if tag in ("tuple", "list"):
        out = set()
        for item in tree[1]:
            out |= free_variables(item)
        return out
    if tag == "record":
        out = set()
        for _label, item in tree[1]:
            out |= free_variables(item)
        return out
    if tag == "fn":
        out = set()
        for pattern, body in tree[1]:
            out |= free_variables(body) - pattern_variables(pattern)
        return out
    if tag == "case":
        out = free_variables(tree[1])
        for pattern, body in tree[2]:
            out |= free_variables(body) - pattern_variables(pattern)
        return out
    if tag == "let":
        bound: set = set()
        out = set()
        for entry in tree[1]:
            if entry[0] == "val":
                out |= free_variables(entry[2]) - bound
                bound |= pattern_variables(entry[1])
            else:
                bound.add(entry[1])
                out |= free_variables(entry[2]) - bound
        return out | (free_variables(tree[2]) - bound)
    raise MLError(f"cannot inspect {tag!r}")


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------

# Function to resolve a record or tuple field label to an index.
def _field_index(label, fields: Optional[Dict[str, int]]) -> Optional[int]:
    """The position a field selector refers to.

    Args:
        label: The label, a name or a 1-based tuple position.
        fields (dict, optional): ``label -> index`` from the colour sets.

    Returns:
        int|None: The index, or None when the label is unknown.
    """
    if isinstance(label, int):
        return label - 1                      # #1 is the first component
    if fields and label in fields:
        return fields[label]
    m = re.fullmatch(r"f(\d+)", str(label))   # the exporter's own convention
    return int(m.group(1)) if m else None


# Function to divide two numbers the way SML does.
def _divide(a, b):
    """Real division, refusing division by zero.

    Args:
        a: Numerator.
        b: Denominator.

    Returns:
        float: The quotient.

    Raises:
        MLError: On division by zero.
    """
    if b == 0:
        raise MLError("division by zero")
    return a / b


#: Binary operators that are a plain Python expression.
_BINARY: Dict[str, Callable] = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "/": _divide,
    "div": lambda a, b: a // b,
    "mod": lambda a, b: a % b,
    "^": lambda a, b: a + b,
    "=": lambda a, b: a == b,
    "<>": lambda a, b: a != b,
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
    "::": lambda a, b: (a,) + b,
    "@": lambda a, b: a + b,
    "^^": lambda a, b: a + b,                # CPN ML list concatenation
    "`": _ms_scale,
    "++": _ms_union,
    "--": _ms_diff,
}


# Function to compile an expression tree into a closure over an environment.
def compile_expression(tree, globals_: Optional[Dict] = None,
                       fields: Optional[Dict[str, int]] = None) -> Callable:
    """Turn an expression tree into ``f(env) -> value``.

    The tree is walked once, here; evaluating the result then costs one Python
    call per node and no dispatch on tags.

    Args:
        tree (tuple): The expression tree.
        globals_ (dict, optional): Names visible to every expression --
            declared values and functions, and the prelude. It is read at call
            time, so declarations may be mutually recursive.
        fields (dict, optional): ``label -> index`` for record selectors.

    Returns:
        callable: ``env -> value``.

    Raises:
        MLError: On a construct with no compilation.
    """
    globals_ = {} if globals_ is None else globals_
    compile_ = lambda sub: compile_expression(sub, globals_, fields)  # noqa: E731
    tag = tree[0]

    if tag == "lit":
        value = tree[1]
        return lambda env: value

    if tag == "var":
        name = tree[1]

        def read(env, name=name, globals_=globals_):
            if name in env:
                return env[name]
            if name in globals_:
                return globals_[name]
            raise MLError(f"unbound name {name!r}")
        return read

    if tag == "selector":
        index = _field_index(tree[1], fields)
        if index is None:
            raise MLError(f"unknown field {tree[1]!r}: the colour sets do not "
                          "declare it")
        return lambda env, i=index: (lambda record: record[i])

    if tag == "neg":
        inner = compile_(tree[1])
        return lambda env: -inner(env)

    if tag == "not":
        inner = compile_(tree[1])
        return lambda env: not inner(env)

    if tag == "binop":
        op = tree[1]
        left, right = compile_(tree[2]), compile_(tree[3])
        if op == "andalso":
            return lambda env: bool(left(env)) and bool(right(env))
        if op == "orelse":
            return lambda env: bool(left(env)) or bool(right(env))
        apply = _BINARY[op]
        return lambda env: apply(left(env), right(env))

    if tag == "if":
        test, yes, no = compile_(tree[1]), compile_(tree[2]), compile_(tree[3])
        return lambda env: yes(env) if test(env) else no(env)

    if tag == "app":
        function, argument = compile_(tree[1]), compile_(tree[2])

        def call(env, function=function, argument=argument):
            value = function(env)
            if not callable(value):
                raise MLError(f"{value!r} is not a function")
            return value(argument(env))
        return call

    if tag == "tuple":
        parts = [compile_(item) for item in tree[1]]
        return lambda env: tuple(part(env) for part in parts)

    if tag == "list":
        parts = [compile_(item) for item in tree[1]]
        return lambda env: tuple(part(env) for part in parts)

    if tag == "record":
        ordered = sorted(tree[1], key=lambda f: _field_index(f[0], fields)
                         if _field_index(f[0], fields) is not None else 0)
        if any(_field_index(label, fields) is None for label, _ in tree[1]):
            raise MLError(f"unknown record field in {tree[1]!r}")
        parts = [compile_(item) for _label, item in ordered]
        return lambda env: tuple(part(env) for part in parts)

    if tag == "fn":
        rules = [(pattern, compile_(body)) for pattern, body in tree[1]]
        return lambda env: Closure(rules, env)

    if tag == "let":
        steps = []
        for entry in tree[1]:
            if entry[0] == "val":
                steps.append(("val", entry[1], compile_(entry[2])))
            else:
                steps.append(("fun", entry[1], compile_(entry[2])))
        body = compile_(tree[2])

        def run_let(env, steps=steps, body=body, fields=fields):
            local = dict(env)
            for kind, target, value in steps:
                if kind == "val":
                    bound = match_pattern(target, value(local), local, fields)
                    if bound is None:
                        raise MLError(f"the let binding {target!r} does not "
                                      "match")
                    local = bound
                else:
                    closure = value(local)
                    if isinstance(closure, Closure):
                        closure.name = target
                        closure.env = local          # so that it may recurse
                    local[target] = closure
            return body(local)
        return run_let

    if tag == "case":
        subject = compile_(tree[1])
        rules = [(pattern, compile_(body)) for pattern, body in tree[2]]

        def run_case(env, subject=subject, rules=rules, fields=fields):
            value = subject(env)
            for pattern, body in rules:
                bound = match_pattern(pattern, value, env, fields)
                if bound is not None:
                    return body(bound)
            raise MLError(f"no case matches {value!r}")
        return run_case

    raise MLError(f"cannot compile {tag!r}")


# Function to compile a pattern for repeated matching.
def compile_pattern(pattern, fields: Optional[Dict[str, int]] = None
                    ) -> Callable:
    """Turn a pattern into ``f(value, env) -> bindings or None``.

    Args:
        pattern (tuple): The pattern tree.
        fields (dict, optional): ``label -> index`` for record patterns.

    Returns:
        callable: The matcher.
    """
    return lambda value, env=None: match_pattern(pattern, value, env, fields)


# ---------------------------------------------------------------------------
# The prelude
# ---------------------------------------------------------------------------

# Function to fold a list from the left, as SML does.
def _foldl(function):
    """``List.foldl f init xs``: ``f`` takes ``(element, accumulator)``.

    Args:
        function: The step function, curried CPN ML style.

    Returns:
        callable: The rest of the curried application.
    """
    def with_init(init):
        def over(items):
            acc = init
            for item in items:
                acc = function((item, acc))
            return acc
        return over
    return with_init


# Function to fold a list from the right, as SML does.
def _foldr(function):
    """``List.foldr f init xs``: ``f`` takes ``(element, accumulator)``.

    Args:
        function: The step function.

    Returns:
        callable: The rest of the curried application.
    """
    def with_init(init):
        def over(items):
            acc = init
            for item in reversed(items):
                acc = function((item, acc))
            return acc
        return over
    return with_init


# Function to curry a two-argument builtin.
def _curry(function):
    """Adapt a Python two-argument function to CPN ML's curried application.

    Args:
        function: ``f(a, b)``.

    Returns:
        callable: ``a -> b -> result``.
    """
    return lambda a: lambda b: function(a, b)


#: The standard names a net may use without declaring them.
PRELUDE: Dict[str, Any] = {
    "empty": MultiSet(),
    "abs": abs,
    "real": float,
    "floor": lambda x: int(__import__("math").floor(x)),
    "ceil": lambda x: int(__import__("math").ceil(x)),
    "round": lambda x: int(round(x)),
    "trunc": int,
    "not": lambda x: not x,
    "hd": lambda xs: xs[0],
    "tl": lambda xs: xs[1:],
    "null": lambda xs: len(xs) == 0,
    "length": len,
    "rev": lambda xs: tuple(reversed(xs)),
    "size": len,
    "explode": lambda s: tuple(s),
    "implode": lambda cs: "".join(cs),
    "Int.toString": str,
    "Int.abs": abs,
    "Int.max": _curry(max),
    "Int.min": _curry(min),
    "Real.fromInt": float,
    "Real.toString": lambda x: repr(x).replace("-", "~"),
    "Real.max": _curry(max),
    "Real.min": _curry(min),
    "Bool.toString": lambda b: "true" if b else "false",
    "String.concat": lambda xs: "".join(xs),
    "String.size": len,
    "List.length": len,
    "List.hd": lambda xs: xs[0],
    "List.tl": lambda xs: xs[1:],
    "List.null": lambda xs: len(xs) == 0,
    "List.rev": lambda xs: tuple(reversed(xs)),
    "List.nth": _curry(lambda xs, i: xs[i]),
    "List.take": _curry(lambda xs, n: xs[:n]),
    "List.drop": _curry(lambda xs, n: xs[n:]),
    "List.concat": lambda xss: tuple(x for xs in xss for x in xs),
    "List.map": lambda f: lambda xs: tuple(f(x) for x in xs),
    "map": lambda f: lambda xs: tuple(f(x) for x in xs),
    "List.filter": lambda f: lambda xs: tuple(x for x in xs if f(x)),
    "List.all": lambda f: lambda xs: all(f(x) for x in xs),
    "List.exists": lambda f: lambda xs: any(f(x) for x in xs),
    "List.foldl": _foldl,
    "List.foldr": _foldr,
    "List.last": lambda xs: xs[-1],
    "List.tabulate": _curry(lambda n, f: tuple(f(i) for i in range(n))),
    "ListPair.zip": lambda pair: tuple(zip(pair[0], pair[1])),
    "ListPair.unzip": lambda xs: (tuple(a for a, _ in xs),
                                  tuple(b for _, b in xs)),
    "ListPair.map": lambda f: lambda pair: tuple(
        f((a, b)) for a, b in zip(pair[0], pair[1])),
    "ListPair.all": lambda f: lambda pair: all(
        f((a, b)) for a, b in zip(pair[0], pair[1])),
    "ListPair.exists": lambda f: lambda pair: any(
        f((a, b)) for a, b in zip(pair[0], pair[1])),
    "ListPair.foldl": lambda f: lambda init: lambda pair: _pair_foldl(
        f, init, pair),
}


# Function to fold over two lists at once, as ListPair does.
def _pair_foldl(function, init, pair):
    """``ListPair.foldl f init (xs, ys)``, stopping at the shorter list.

    Args:
        function: The step, taking ``(x, y, accumulator)``.
        init: The initial accumulator.
        pair (tuple): The two lists.

    Returns:
        The accumulated value.
    """
    acc = init
    for a, b in zip(pair[0], pair[1]):
        acc = function((a, b, acc))
    return acc
