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
    "MLRaise",
    "MultiSet",
    "Delayed",
    "Stamped",
    "TimedToken",
    "EnumValue",
    "IndexValue",
    "IndexConstructor",
    "ConValue",
    "DataConstructor",
    "sort_tokens",
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


# Exception raised by an SML raise, catchable with handle.
class MLRaise(MLError):
    """An SML exception: ``raise e``, or one a library function raises.

    ``e handle p => v`` catches these, matching ``p`` against :attr:`packet`;
    other :class:`MLError` (a construct not understood, an unbound name) are
    the checker's, not the net's, and are never handled.

    Attributes:
        packet: The exception value (``Empty``, ``Fail "msg"``...).
    """

    # Method to carry the exception value.
    def __init__(self, packet, message: str = ""):
        """Create the exception.

        Args:
            packet: The exception value.
            message (str): For reports.
        """
        super().__init__(message or f"exception {packet!r}")
        self.packet = packet


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

#: Words with a meaning of their own.
KEYWORDS = {
    "if", "then", "else", "let", "val", "in", "end", "fun", "fn", "case", "of",
    "andalso", "orelse", "not", "div", "mod", "true", "false", "nil", "rec",
    "raise", "handle", "datatype", "exception",
}

#: Operators, longest first so that ``<=`` is not read as ``<`` then ``=``.
OPERATORS = [
    "...", ":=", "<><>", "<<=", ">>=", "<<", ">>", "==",
    "=>", "->", "<=", ">=", "<>", "::", "+++", "++", "--", "@++", "@+", "@", "^^", "^", "+", "-",
    "*",
    "/",
    "<", ">", "=", "|", ":", ",", ";", "(", ")", "[", "]", "{", "}", "#", "~",
    "!",
    "`", "_",
]

_REAL = re.compile(r"~?\d+\.\d*(?:[eE]~?[-+]?\d+)?|~?\d+[eE]~?[-+]?\d+")
_INT = re.compile(r"~?\d+")
# Qualified names such as ``List.nth`` are one identifier, not three.
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*")
_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')
# A character literal, #"a"; characters are one-character strings here.
_CHAR = re.compile(r'#"((?:[^"\\]|\\.)+)"')


# Function to decode the escapes of a string or character literal.
def _unescape(body: str) -> str:
    """``\\n``, ``\\t``, ``\\"``, ``\\\\`` and ``\\ddd`` decoded.

    Args:
        body (str): The text between the quotes.

    Returns:
        str: The value.
    """
    if "\\" not in body:
        return body
    out, i = [], 0
    while i < len(body):
        ch = body[i]
        if ch != "\\" or i + 1 == len(body):
            out.append(ch)
            i += 1
            continue
        nxt = body[i + 1]
        if nxt.isdigit():
            out.append(chr(int(body[i + 1:i + 4])))
            i += 4
            continue
        out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(nxt, nxt))
        i += 2
    return "".join(out)


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
        m = _CHAR.match(text, i)
        if m:
            out.append(("str", _unescape(m.group(1)), i))
            i = m.end()
            continue
        m = _STRING.match(text, i)
        if m:
            out.append(("str", _unescape(m.group(0)[1:-1]), i))
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
    "+++": (3, "left"), "++": (3, "left"), "--": (3, "left"), "`": (4.5, "right"),
    # Multiset comparisons bind looser than ++, so 1`a ++ 1`b == 1`b ++ 1`a
    # compares the two sums, as in CPN Tools.
    "==": (2.5, "left"), "<><>": (2.5, "left"), "<<": (2.5, "left"),
    "<<=": (2.5, "left"), ">>": (2.5, "left"), ">>=": (2.5, "left"),
    # Function composition, SML's infix 3.
    "o": (3, "left"),
    # Assignment to a reference: SML's infix 3; it has a side effect, so it
    # parses (to be refused by name) but never evaluates.
    ":=": (0.5, "left"),
    "=": (4, "left"), "<>": (4, "left"), "<": (4, "left"), ">": (4, "left"),
    "<=": (4, "left"), ">=": (4, "left"),
    "::": (5, "right"), "^^": (5, "right"),
    # Time: x@t stamps a token, ms@+d delays a multiset. Both bind looser than
    # the coefficient and tighter than ++, so 1`x@+3 ++ 1`y is
    # ((1`x)@+3) ++ (1`y). As in SML, "else e @+ d" delays e only.
    "@": (4, "left"), "@+": (4, "left"),
    "+": (6, "left"), "-": (6, "left"), "^": (6, "left"),
    "*": (7, "left"), "/": (7, "left"), "div": (7, "left"), "mod": (7, "left"),
}

#: Constructors and constants every pattern knows (SOME, NONE...); filled in
#: from :mod:`cpncheck.mllib` at the end of this module.
DEFAULT_SYMBOLS: Dict[str, Any] = {}

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
        # SOME, NONE and the order constants are known to every pattern.
        self.symbols = {**DEFAULT_SYMBOLS, **(symbols or {})}

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
        if kind == "kw" and value == "raise":
            self.next()
            return ("raise", self.expression())
        expr = self.binary(level)
        if self.peek()[0] == "op" and self.peek()[1] == ":" and level == 0:
            # e : T -- the annotation constrains nothing a value here does.
            self.next()
            self.skip_type()
        if self.peek()[0] == "kw" and self.peek()[1] == "handle":
            self.next()
            return ("handle", expr, self.match_rules())
        return expr

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
        if self.peek()[0] == "op" and self.peek()[1] == ";":
            items = [body]
            while self.accept("op", ";"):
                items.append(self.expression())
            body = ("seq", items)
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
        if arity == 1:
            return name, ("fn", [(params[0], body) for params, body in rules])
        # fun f p1 q1 = e1 | f p2 q2 = e2: take the arguments one by one,
        # then match them together, clause by clause.
        args = [f"cpnq_arg{i}" for i in range(arity)]
        body = ("case", ("tuple", [("var", a) for a in args]),
                [(("ptuple", params), clause) for params, clause in rules])
        for arg in reversed(args):
            body = ("fn", [(("pvar", arg), body)])
        return name, body

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
            if not (kind in ("op", "kw") or (kind == "id" and value == "o")) \
                    or value not in BINOPS:
                return left
            power, associativity = BINOPS[value]
            if power < level:
                return left
            self.next()
            # A left-associative operator takes, on its right, only what
            # binds strictly tighter: levels are not all whole numbers.
            right = self.binary(power + (1e-6 if associativity == "left" else 0))
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
        if kind == "op" and value == "!":
            self.next()
            return ("deref", self.unary())
        return self.atom()

    # Method to tell whether an atom can start here.
    def starts_atom(self) -> bool:
        """Whether the next token can begin an argument.

        Returns:
            bool: True when an application may continue.
        """
        kind, value, _ = self.peek()
        if kind == "id" and value == "o":
            return False
        if kind in ("int", "real", "str", "id"):
            return True
        if kind == "kw":
            return value in ("true", "false", "nil")
        return kind == "op" and value in ("(", "[", "{", "#", "~", "!")

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
        if kind == "id" and value == "op":
            # (op +): the infix operator as a function of a pair.
            kind2, sym, _ = self.next()
            if sym not in BINOPS or sym in ("andalso", "orelse"):
                raise MLError(f"op {sym!r} is not an infix operator")
            return ("opfn", sym)
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
            if self.peek()[0] == "op" and self.peek()[1] == ";":
                # (e1; e2; ...): evaluate in order, the value is the last.
                while self.accept("op", ";"):
                    items.append(self.expression())
                self.expect("op", ")")
                return ("seq", items)
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
            if isinstance(symbol, (IndexConstructor, DataConstructor)):
                # The kind says how to rebuild the value from the pattern.
                kind = "data" if isinstance(symbol, DataConstructor) else "index"
                return ("pcon", value, self.pattern_atom(), kind)
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
            flexible = False
            if not self.accept("op", "}"):
                while True:
                    if self.accept("op", "..."):
                        # {seq, ...}: the other fields are not matched.
                        flexible = True
                        break
                    label = str(self.next()[1])
                    if self.accept("op", "="):
                        fields.append((label, self.pattern()))
                    else:
                        fields.append((label, ("pvar", label)))   # {data}
                    if not self.accept("op", ","):
                        break
                self.expect("op", "}")
            return ("precord", fields, flexible)
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
    if tree[0] == "binop" and tree[1] in ("++", "+++"):
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
            elif parser.peek()[0] == "kw" and parser.peek()[1] in (
                    "datatype", "exception"):
                out.append(_constructors_declaration(parser))
            elif parser.peek()[0] == "id" and parser.peek()[1] == "globref":
                # globref x = e: a reference, read with !x. Nets use them as
                # parameters; assigning one (:=) is a side effect, refused.
                parser.next()
                name = parser.expect("id")[1]
                parser.expect("op", "=")
                out.append(("val", ("pvar", name), ("app", ("var", "ref"),
                                                    parser.expression())))
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


# Function to read a datatype or exception declaration.
def _constructors_declaration(parser: "Parser") -> Tuple:
    """``datatype t = A | B of int * t`` or ``exception E of string``.

    The constructors become symbols of the parser at once, so that the
    declarations after it can match them in patterns.

    Args:
        parser (Parser): Positioned on ``datatype`` or ``exception``.

    Returns:
        tuple: ``("constructors", [(name, takes_argument), ...])``.
    """
    keyword = parser.next()[1]
    ctors = []
    while True:
        if keyword == "datatype":
            parser.expect("id")                     # the type's name
            parser.expect("op", "=")
        while True:
            name = parser.expect("id")[1]
            has_arg = parser.accept("kw", "of")
            if has_arg:
                parser.skip_type()
            ctors.append((name, has_arg))
            parser.symbols[name] = (DataConstructor(name) if has_arg
                                    else EnumValue(name))
            if keyword == "exception" or not parser.accept("op", "|"):
                break
        if not (parser.peek()[0] == "id" and parser.peek()[1] == "and"):
            break
        parser.next()                               # datatype ... and ...
    return ("constructors", ctors)


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
            raise MLRaise(EnumValue("Subtract"),
                          f"cannot subtract {count}`{value!r}: not contained")
        out[value] -= count
    return MultiSet(out)


# Class marking a token produced with a delay.
class Delayed(tuple):
    """``x @+ d``: a token whose timestamp is the occurrence time plus ``d``.

    Only an output arc of a timed place may produce one; the coloured net
    turns it into a :class:`TimedToken` when the transition occurs.
    """

    __slots__ = ()

    # Method to build a delayed token.
    def __new__(cls, value, delay: int):
        """Create the marker.

        Args:
            value: The token value.
            delay (int): The delay.

        Returns:
            Delayed: The marker.
        """
        return super().__new__(cls, (value, delay))

    # Method to render the marker.
    def __repr__(self):
        """Render as ``v@+d``.

        Returns:
            str: The text.
        """
        return f"{self[0]!r}@+{self[1]}"


# Class marking a token with an absolute timestamp.
class Stamped(tuple):
    """``x @ t``: a token carrying the timestamp ``t`` (initial markings)."""

    __slots__ = ()

    # Method to build a stamped token.
    def __new__(cls, value, time: int):
        """Create the marker.

        Args:
            value: The token value.
            time (int): The timestamp.

        Returns:
            Stamped: The marker.
        """
        return super().__new__(cls, (value, time))

    # Method to render the marker.
    def __repr__(self):
        """Render as ``v@t``.

        Returns:
            str: The text.
        """
        return f"{self[0]!r}@{self[1]}"


# Class holding a token of a timed place.
class TimedToken(tuple):
    """A token of a timed place: a value and the model time it is ready at.

    Two tokens with the same value and different timestamps are different
    tokens, so a marking holding them is a different marking -- as in CPN
    Tools' timed state space.
    """

    __slots__ = ()

    # Method to build a timed token.
    def __new__(cls, value, time: int):
        """Create the token.

        Args:
            value: The token value.
            time (int): Its timestamp.

        Returns:
            TimedToken: The token.
        """
        return super().__new__(cls, (value, time))

    # Property giving the token's value.
    @property
    def value(self):
        """The colour.

        Returns:
            The value.
        """
        return self[0]

    # Property giving the token's timestamp.
    @property
    def time(self) -> int:
        """The model time from which the token is ready.

        Returns:
            int: The timestamp.
        """
        return self[1]

    # Method to render the token.
    def __repr__(self):
        """Render as ``v@t``.

        Returns:
            str: The text.
        """
        return f"{self[0]!r}@{self[1]}"


# Function to check that a time is an integer.
def _model_time(value) -> int:
    """A model time: integer time only, as in CPN Tools' timed state space.

    Args:
        value: The time.

    Returns:
        int: The time.

    Raises:
        MLError: For a real or other non-integer time.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise MLError(f"model time must be an integer, not {value!r} "
                      "(real-time nets are not supported)")
    return value


# Function to delay a token or every element of a multiset.
def _delay(value, delay) -> "MultiSet":
    """``ms @+ d``.

    Args:
        value: A token or a multiset.
        delay (int): The delay.

    Returns:
        MultiSet: The delayed tokens; delays of nested ``@+`` add up.
    """
    delay = _model_time(delay)
    out: Dict[Any, int] = {}
    for element, count in _as_multiset(value).items():
        if isinstance(element, Delayed):
            element = Delayed(element[0], element[1] + delay)
        else:
            element = Delayed(element, delay)
        out[element] = out.get(element, 0) + count
    return MultiSet(out)


# Function to stamp a token, or append two lists.
def _at(left, right):
    """``x @ t`` with an integer ``t`` stamps a token; with lists, appends.

    CPN ML uses ``@`` for timestamps (``^^`` appends lists), but SML code in a
    net's declarations may still append lists with it.

    Args:
        left: A token, a multiset, or a list.
        right: An integer time, or a list.

    Returns:
        The stamped tokens, or the appended list.
    """
    if isinstance(right, tuple) and isinstance(left, tuple):
        return left + right
    time = _model_time(right)
    out: Dict[Any, int] = {}
    for element, count in _as_multiset(left).items():
        element = Stamped(element, time)
        out[element] = out.get(element, 0) + count
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


# Class holding a value built by a datatype constructor.
class ConValue(tuple):
    """``SOME 3``: a constructor applied to a value, as a (name, payload) pair.

    A tuple subclass, so it hashes, compares and orders; patterns
    ``SOME x`` match it by name. Nullary constructors (``NONE``) are
    :class:`EnumValue` constants instead.
    """

    __slots__ = ()

    # Method to build the value.
    def __new__(cls, name: str, payload):
        """Create the value.

        Args:
            name (str): The constructor.
            payload: Its argument.

        Returns:
            ConValue: The value.
        """
        return super().__new__(cls, (name, payload))

    # Property giving the constructor name.
    @property
    def name(self) -> str:
        """The constructor.

        Returns:
            str: Its name.
        """
        return self[0]

    # Property giving the argument.
    @property
    def payload(self):
        """The value the constructor was applied to.

        Returns:
            The argument.
        """
        return self[1]

    # Property telling whether the constructor took an argument.
    @property
    def has_payload(self) -> bool:
        """Always True: nullary constructors are EnumValue constants.

        Returns:
            bool: True.
        """
        return True

    # Method to render the value.
    def __repr__(self):
        """Render as ``SOME 3`` or ``SOME (1,2)``.

        Returns:
            str: The value as SML writes it.
        """
        inner = repr(self[1])
        if isinstance(self[1], (ConValue, IndexValue)) or (
                isinstance(self[1], tuple) and not isinstance(self[1], ConValue)):
            inner = f"({inner.strip('()')})" if isinstance(self[1], tuple) \
                and type(self[1]) is tuple else f"({inner})"
        return f"{self[0]} {inner}"


# Class building the values of a datatype constructor.
class DataConstructor:
    """A constructor taking an argument, such as ``SOME``.

    Attributes:
        name (str): The constructor.
    """

    __slots__ = ("name",)

    # Method to create the constructor.
    def __init__(self, name: str):
        """Create the constructor.

        Args:
            name (str): Its name.
        """
        self.name = name

    # Method to apply the constructor.
    def __call__(self, payload):
        """Build ``name payload``.

        Args:
            payload: The argument.

        Returns:
            ConValue: The value.
        """
        return ConValue(self.name, payload)

    # Method to render the constructor.
    def __repr__(self):
        """Return a short representation.

        Returns:
            str: ``<constructor SOME>``.
        """
        return f"<constructor {self.name}>"


# Class holding an SML reference.
class Ref:
    """``ref v``: a mutable cell. Only read here (``!r``); assigning one is
    a side effect, which an occurrence graph cannot have.

    Attributes:
        value: The contents.
    """

    __slots__ = ("value",)

    # Method to create the reference.
    def __init__(self, value):
        """Create the cell.

        Args:
            value: Its contents.
        """
        self.value = value

    # Method to render the reference.
    def __repr__(self):
        """Return ``ref v``.

        Returns:
            str: The text.
        """
        return f"ref {self.value!r}"


# Function standing for assignment, which is refused.
def _assign(_ref, _value):
    """``r := v`` changes state outside the marking.

    Raises:
        MLError: Always.
    """
    raise MLError("assignment (:=) to a reference has a side effect; a net "
                  "whose inscriptions change state outside the marking has "
                  "no occurrence graph of its own")


# Function to give a total order over token values of any kind.
def token_key(value):
    """A sort key under which any two token values compare.

    A place may hold values Python cannot compare -- ``Ack`` (a constant)
    and ``Data 1`` (a constructed value) of one union colour set -- yet a
    marking is kept sorted, so that equal markings are equal tuples.

    Args:
        value: A token value.

    Returns:
        tuple: The key.
    """
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, (int, float)):
        return (1, value)
    if isinstance(value, EnumValue):
        return (2, str(value))
    if isinstance(value, str):
        return (3, value)
    if isinstance(value, IndexValue):
        return (4, value[0], token_key(value[1]))
    if isinstance(value, ConValue):
        return (5, value[0], token_key(value[1]))
    if isinstance(value, TimedToken):
        return (6, token_key(value[0]), value[1])
    if isinstance(value, tuple):
        return (7, tuple(token_key(v) for v in value))
    return (8, repr(value))


# Function to sort the tokens of a place.
def sort_tokens(tokens) -> tuple:
    """The tokens in canonical order.

    Args:
        tokens (iterable): Token values.

    Returns:
        tuple: Sorted; values of one kind by their own order, mixed kinds by
        :func:`token_key`.
    """
    tokens = list(tokens)
    try:
        return tuple(sorted(tokens))
    except TypeError:
        return tuple(sorted(tokens, key=token_key))


# Class holding a function value with the environment it closed over.
class Closure:
    """A CPN ML function: clauses, and the bindings visible where it was written.

    Attributes:
        rules (list): ``(pattern, compiled body)`` clauses, tried in order.
        env (dict): The captured environment.
        name (str): For error messages.
    """

    __slots__ = ("rules", "env", "name", "fields")

    # Method to build a function value.
    def __init__(self, rules, env, name="fn", fields=None):
        """Create the closure.

        Args:
            rules (list): ``(pattern, compiled body)`` clauses.
            env (dict): Captured bindings.
            name (str): Name used in error messages.
            fields (dict, optional): ``label -> index``, for record patterns
                among the parameters.
        """
        self.rules = rules
        self.env = env
        self.name = name
        self.fields = fields

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
            bound = match_pattern(pattern, argument, self.env, self.fields)
            if bound is not None:
                return body(bound)
        raise MLRaise(EnumValue("Match"),
                      f"{self.name}: no clause matches {argument!r}")

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
        if not isinstance(value, (IndexValue, ConValue)) or \
                value[0] != pattern[1]:
            return None
        return match_pattern(pattern[2], value[1], env, fields)
    if tag == "precord":
        if not isinstance(value, tuple):
            return None
        out = dict(env or {})
        for label, sub in pattern[1]:
            index = _record_index(value, label, fields)
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
    if tag in ("lit", "selector", "opfn"):
        return set()
    if tag in ("neg", "not", "deref", "raise"):
        return free_variables(tree[1])
    if tag == "handle":
        out = free_variables(tree[1])
        for pattern, handler in tree[2]:
            out |= free_variables(handler) - pattern_variables(pattern)
        return out
    if tag == "binop":
        return free_variables(tree[2]) | free_variables(tree[3])
    if tag == "if":
        return (free_variables(tree[1]) | free_variables(tree[2])
                | free_variables(tree[3]))
    if tag == "app":
        return free_variables(tree[1]) | free_variables(tree[2])
    if tag in ("tuple", "list", "seq"):
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


# Class holding a record that carries its own labels.
class RecordValue(tuple):
    """A record built outside the declared colour sets (a binding record).

    Declared records are plain tuples in field order, located through the
    colour sets' labels; this one knows its labels itself.

    Attributes:
        labels (tuple): The field names, in the order of the values.
    """

    labels: Tuple[str, ...] = ()

    # Method to build the record.
    def __new__(cls, labels, values):
        """Create the record.

        Args:
            labels (sequence): Field names.
            values (sequence): Field values, in the same order.

        Returns:
            RecordValue: The record.
        """
        obj = super().__new__(cls, tuple(values))
        obj.labels = tuple(labels)
        return obj

    # Method to render the record as CPN ML.
    def __repr__(self):
        """Render as ``{x=1,y=2}``.

        Returns:
            str: The text.
        """
        return "{" + ",".join(f"{k}={v!r}" for k, v in zip(self.labels, self)) + "}"


# Function to find a field of a record value.
def _record_index(record, label, fields) -> Optional[int]:
    """Position of a field, from the record's own labels when it has them.

    Args:
        record: The record value.
        label: The field label.
        fields (dict, optional): The colour sets' labels.

    Returns:
        int|None: The index, or None when the field is unknown.
    """
    labels = getattr(record, "labels", None)
    if labels is not None:
        return labels.index(label) if label in labels else None
    return _field_index(label, fields)


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


# Function to divide integers as SML does.
def _integer_division(a, b, op: str):
    """``a div b`` (rounding down) or ``a mod b`` (sign of ``b``).

    Python's ``//`` and ``%`` round the same way as SML's ``div`` and
    ``mod``; only division by zero differs, which SML signals with ``Div``.

    Args:
        a (int): Numerator.
        b (int): Denominator.
        op (str): ``"div"`` or ``"mod"``.

    Returns:
        int: The result.

    Raises:
        MLError: On division by zero.
    """
    if b == 0:
        raise MLRaise(EnumValue("Div"), f"exception Div: {a} {op} 0")
    return a // b if op == "div" else a % b


#: Binary operators that are a plain Python expression.
_BINARY: Dict[str, Callable] = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "/": _divide,
    "div": lambda a, b: _integer_division(a, b, "div"),
    "mod": lambda a, b: _integer_division(a, b, "mod"),
    "^": lambda a, b: a + b,
    "=": lambda a, b: a == b,
    "<>": lambda a, b: a != b,
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
    "::": lambda a, b: (a,) + b,
    "@": lambda a, b: _at(a, b),             # a timestamp (or SML list append)
    "@+": lambda a, b: _delay(a, b),         # a delay on produced tokens
    "^^": lambda a, b: a + b,                # CPN ML list concatenation
    "`": _ms_scale,
    "++": _ms_union,
    # Timed multiset sum: the tokens already carry their timestamps.
    "+++": _ms_union,
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
        label = tree[1]
        index = _field_index(label, fields)

        def select(record, label=label, index=index):
            i = _record_index(record, label, fields)                 if isinstance(record, RecordValue) else index
            if i is None:
                raise MLError(f"unknown field {label!r}: the colour sets do "
                              "not declare it")
            return record[i]
        return lambda env: select

    if tag == "raise":
        inner = compile_(tree[1])

        def raise_(env, inner=inner):
            packet = inner(env)
            raise MLRaise(packet, f"exception {packet!r} raised")
        return raise_

    if tag == "handle":
        body = compile_(tree[1])
        rules = [(pattern, compile_(handler)) for pattern, handler in tree[2]]

        def handle(env, body=body, rules=rules, fields=fields):
            try:
                return body(env)
            except MLRaise as exc:
                for pattern, handler in rules:
                    bound = match_pattern(pattern, exc.packet, env, fields)
                    if bound is not None:
                        return handler(bound)
                raise
        return handle

    if tag == "seq":
        parts = [compile_(item) for item in tree[1]]

        def run_seq(env, parts=parts):
            value = None
            for part in parts:
                value = part(env)
            return value
        return run_seq

    if tag == "deref":
        inner = compile_(tree[1])

        def deref(env, inner=inner):
            box = inner(env)
            if not isinstance(box, Ref):
                raise MLError(f"! of {box!r}, which is not a reference")
            return box.value
        return deref

    if tag == "opfn":
        apply = _BINARY[tree[1]]
        return lambda env, apply=apply: (lambda pair: apply(pair[0], pair[1]))

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
        return lambda env, fields=fields: Closure(rules, env, fields=fields)

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
                        raise MLRaise(EnumValue("Bind"), f"the let binding "
                                      f"{target!r} does not match")
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
            raise MLRaise(EnumValue("Match"), f"no case matches {value!r}")
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

#: The standard names a net may use without declaring them: CPN Tools'
#: priorities, then the library (:mod:`cpncheck.mllib`), added at the end of
#: this module because it is built on the classes above.
PRELUDE: Dict[str, Any] = {
    # Transition priorities, as CPN Tools declares them.
    "P_HIGH": 100,
    "P_NORMAL": 1000,
    "P_LOW": 10000,
}


# The library, and the operators defined in it.
from .mllib import LIBRARY as _LIBRARY, SYMBOLS as _SYMBOLS  # noqa: E402
from .mllib import ms_compare as _ms_compare  # noqa: E402

PRELUDE.update(_LIBRARY)
PRELUDE["ref"] = Ref
_BINARY[":="] = _assign
DEFAULT_SYMBOLS.update(_SYMBOLS)
for _op in ("==", "<><>", "<<", "<<=", ">>", ">>="):
    _BINARY[_op] = _ms_compare(_op)
_BINARY["o"] = lambda f, g: (lambda x: f(g(x)))
