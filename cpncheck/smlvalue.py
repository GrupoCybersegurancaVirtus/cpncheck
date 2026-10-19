"""Read values as the SML REPL prints them, and compare them with CPNCheck's.

When CPN Tools evaluates ``val x = e;`` its SML/NJ REPL answers with the
value and its type: ``val x = [u 1,u 2] : U.cs ms``. To check that CPNCheck
computes what CPN Tools computes, both sides are brought to one *normal
form*: plain Python data with tags where Python would conflate two SML values
(``true`` and ``1``, a list and a multiset).

==============================  =============================================
SML                             normal form
==============================  =============================================
``3``, ``~3``                   ``3``, ``-3``
``2.5``                         ``("real", 2.5)``
``true``                        ``("bool", True)``
``"ab"``, ``#"a"``              ``"ab"``, ``"a"``
``[1,2]``, ``(1,2)``, ``()``    ``(1, 2)``, ``(1, 2)``, ``()``
``{x=3,y=b}``                   ``(3, ("con", "b", None))`` (label order)
``a``, ``u 2``, ``SOME 3``      ``("con", "a", None)``, ``("con", "u", 2)``...
a value of type ``... ms``      ``("ms", ((item, count), ...))``, sorted
``fn``                          ``("fn",)``
==============================  =============================================
"""

import collections
import re
from typing import Any, List, Optional, Tuple

__all__ = ["parse_repl", "normalise", "same", "SMLParseError"]


# Class signalling REPL text that cannot be read.
class SMLParseError(ValueError):
    """The REPL text is not a value this module understands."""


_TOKEN = re.compile(r"""
    \s*(?:
      (?P<real>~?\d+\.\d+(?:E~?\d+)?|~?\d+E~?\d+)
    | (?P<int>~?\d+)
    | (?P<char>\#"(?:[^"\\]|\\.)*")
    | (?P<str>"(?:[^"\\]|\\.)*")
    | (?P<id>[A-Za-z][A-Za-z0-9_'.]*)
    | (?P<sym>[\[\](){},=])
    )""", re.VERBOSE)


# Function to decode the escapes of an SML string literal.
def _unescape(body: str) -> str:
    """``\\"``, ``\\\\``, ``\\n``, ``\\t`` and ``\\ddd`` decoded.

    Args:
        body (str): The text between the quotes.

    Returns:
        str: The string.
    """
    out, i = [], 0
    while i < len(body):
        ch = body[i]
        if ch != "\\":
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


# Function to split printed SML into tokens.
def _tokens(text: str) -> List[Tuple[str, str]]:
    """Tokens of a printed value.

    Args:
        text (str): The value's text.

    Returns:
        list: ``(kind, text)`` pairs.

    Raises:
        SMLParseError: On text that is not a printed value.
    """
    out, pos = [], 0
    text = text.strip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if m is None or m.end() == pos:
            raise SMLParseError(f"cannot read {text[pos:pos + 30]!r}")
        out.append((m.lastgroup, m.group(m.lastgroup)))
        pos = m.end()
        while pos < len(text) and text[pos].isspace():
            pos += 1
    return out


# Class reading one printed value.
class _Reader:
    """Recursive-descent reader over the tokens of a printed value."""

    # Method to start reading.
    def __init__(self, tokens):
        """Create the reader.

        Args:
            tokens (list): From :func:`_tokens`.
        """
        self.tokens = tokens
        self.pos = 0

    # Method to look at the next token.
    def peek(self):
        """The next token, or ``("end", "")``.

        Returns:
            tuple: The token.
        """
        return self.tokens[self.pos] if self.pos < len(self.tokens) else ("end", "")

    # Method to consume a token.
    def take(self, text: Optional[str] = None):
        """Consume the next token, which must be ``text`` when given.

        Args:
            text (str, optional): The expected text.

        Returns:
            tuple: The token.

        Raises:
            SMLParseError: When it is not.
        """
        token = self.peek()
        if text is not None and token[1] != text:
            raise SMLParseError(f"expected {text!r}, found {token[1]!r}")
        self.pos += 1
        return token

    # Method to tell whether an atom starts here.
    def starts_atom(self) -> bool:
        """Whether a constructor argument follows.

        Returns:
            bool: True for a literal, a name or an opening bracket.
        """
        kind, text = self.peek()
        return kind in ("real", "int", "char", "str", "id") or             text in ("(", "[", "{")

    # Method to read a value, including constructor application.
    def value(self):
        """``C v`` or an atom.

        Returns:
            The normal form.
        """
        kind, text = self.peek()
        if kind == "id" and text not in ("true", "false", "fn"):
            self.take()
            if self.starts_atom():
                return ("con", text, self.atom())
            return ("con", text, None)
        return self.atom()

    # Method to read an atom.
    def atom(self):
        """A literal, a name, or a bracketed value.

        Returns:
            The normal form.

        Raises:
            SMLParseError: On anything else.
        """
        kind, text = self.take()
        if kind == "int":
            return int(text.replace("~", "-"))
        if kind == "real":
            return ("real", float(text.replace("~", "-")))
        if kind == "str":
            return _unescape(text[1:-1])
        if kind == "char":
            return _unescape(text[2:-1])
        if kind == "id":
            if text in ("true", "false"):
                return ("bool", text == "true")
            if text == "fn":
                return ("fn",)
            return ("con", text, None)
        if text in ("(", "["):
            close = ")" if text == "(" else "]"
            items = []
            if self.peek()[1] != close:
                items.append(self.value())
                while self.peek()[1] == ",":
                    self.take(",")
                    items.append(self.value())
            self.take(close)
            if text == "(" and len(items) == 1:
                return items[0]
            return tuple(items)
        if text == "{":
            fields = []
            if self.peek()[1] != "}":
                while True:
                    label = self.take()[1]
                    self.take("=")
                    fields.append((label, self.value()))
                    if self.peek()[1] != ",":
                        break
                    self.take(",")
            self.take("}")
            return tuple(v for _label, v in sorted(fields, key=_label_order))
        raise SMLParseError(f"unexpected {text!r}")


# Function to order record labels as SML does.
def _label_order(field):
    """Numeric labels by number, then the others alphabetically.

    Args:
        field (tuple): ``(label, value)``.

    Returns:
        tuple: The sort key.
    """
    label = field[0]
    return (0, int(label), "") if label.isdigit() else (1, 0, label)


# Function to turn a multiset's items into its normal form.
def _bag(items) -> tuple:
    """``("ms", ((item, count), ...))``, sorted by the items' text.

    Args:
        items (iterable): The normal forms of the items.

    Returns:
        tuple: The normal form.
    """
    counts = collections.Counter(items)
    return ("ms", tuple(sorted(counts.items(), key=lambda kv: repr(kv[0]))))


# Function to read one REPL answer.
def parse_repl(text: str) -> Tuple[str, Any, str]:
    """``val x = v : t`` as ``("value", normal form, type)``.

    Args:
        text (str): What the REPL printed (as the oracle's raw queries return
            it).

    Returns:
        tuple: ``("value", value, type)``, ``("exception", None, text)`` for
        an exception raised while evaluating, or ``("error", None, text)``
        for an expression that does not compile.

    Raises:
        SMLParseError: For a value this module cannot read.
    """
    if "Error:" in text:
        return ("error", None, text)
    if "Exception" in text or "uncaught exception" in text:
        return ("exception", None, text)
    m = re.search(r"val \S+ =\s*(.*)\s:\s*([^:]*?)\s*$", text.strip(), re.S)
    if m is None:
        raise SMLParseError(f"not a REPL answer: {text[:80]!r}")
    body, typ = m.group(1), " ".join(m.group(2).split())
    reader = _Reader(_tokens(body))
    value = reader.value()
    if reader.pos != len(reader.tokens):
        raise SMLParseError(f"trailing text in {body!r}")
    if re.search(r"\bms$", typ):
        value = _bag(value)
    return ("value", value, typ)


# Function to bring a CPNCheck value to the normal form.
def normalise(value) -> Any:
    """The normal form of a value CPNCheck computed.

    Args:
        value: A value (int, float, bool, str, tuple, multiset, enumeration
            constant, index value, constructed value or function).

    Returns:
        The normal form.
    """
    from .cpnml import ConValue, EnumValue, IndexValue, MultiSet

    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, EnumValue):
        return ("con", str(value), None)
    if isinstance(value, IndexValue):
        return ("con", value[0], normalise(value[1]))
    if isinstance(value, ConValue):
        return ("con", value.name, normalise(value.payload)
                if value.has_payload else None)
    if isinstance(value, MultiSet):
        items = []
        for item, count in value.items():
            items.extend([normalise(item)] * count)
        return _bag(items)
    if isinstance(value, float):
        return ("real", value)
    if isinstance(value, (int, str)):
        return value
    if isinstance(value, tuple):
        return tuple(normalise(v) for v in value)
    if callable(value):
        return ("fn",)
    raise TypeError(f"no normal form for {value!r}")


# Function to compare two normal forms.
def same(a, b, bag: bool = False) -> bool:
    """Whether two normal forms denote the same value.

    Reals are compared to the precision the REPL prints (12 digits).

    Args:
        a: A normal form.
        b: Another.
        bag (bool): Compare lists (and multiset text) ignoring order.

    Returns:
        bool: True when equal.
    """
    if bag:
        if isinstance(a, str) and isinstance(b, str):
            return _ms_text_bag(a) == _ms_text_bag(b)
        if isinstance(a, tuple) and isinstance(b, tuple) and a[:1] != ("ms",):
            return sorted(map(repr, a)) == sorted(map(repr, b))
    if isinstance(a, tuple) and len(a) == 2 and a[0] == "real" and \
            isinstance(b, tuple) and len(b) == 2 and b[0] == "real":
        return abs(a[1] - b[1]) <= 1e-9 * max(1.0, abs(a[1]))
    if isinstance(a, tuple) and isinstance(b, tuple):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b


# Function to read the terms of a multiset's text.
def _ms_text_bag(text: str) -> List[str]:
    """``"1`a++\\n2`b"`` as the sorted list of its terms.

    Args:
        text (str): The text of a multiset.

    Returns:
        list: The terms, without white space.
    """
    return sorted(t for t in re.sub(r"\s+", "", text).split("++") if t)
