"""The standard names of CPN ML: what CPN Tools 4.0.1 binds before a net's own
declarations.

That environment is SML/NJ's Basis Library plus CPN Tools' own functions on
lists and multisets. Every name here follows SML's calling convention exactly
-- ``Int.max (a, b)`` takes a pair, ``mem l x`` is curried -- because a
function applied the wrong way does not fail, it silently returns a function
where a value was meant. Each one is checked against CPN Tools in
``tests/test_mllib.py`` (the expected answers were recorded from CPN Tools
itself).

Where SML raises an exception (``hd []``, ``valOf NONE``, ``listsub`` of a
missing element), the function raises :class:`~cpncheck.cpnml.MLError`
naming it, which makes the binding element unusable -- as in CPN Tools, where
an exception during enabling makes the simulator report an error rather than
pick a value.

Names that would make the state space depend on something other than the
marking are deliberately absent or refuse: ``random`` and ``CS.ran``
(chance), ``print`` and ``TextIO`` (output), ``CS.input`` (files).
"""

import functools
import math
from typing import Any, Callable, Dict

from .cpnml import (ConValue, DataConstructor, EnumValue, MLError, MLRaise,
                    MultiSet, _as_multiset)

__all__ = ["LIBRARY", "SYMBOLS", "sml_int", "sml_real"]


# Function to raise an SML exception.
def _raise(name: str, why: str):
    """Raise the :class:`MLError` standing for SML's exception ``name``.

    Args:
        name (str): The SML exception (``Empty``, ``Subscript``...).
        why (str): What happened.

    Raises:
        MLError: Always.
    """
    raise MLRaise(EnumValue(name), f"exception {name}: {why}")


# Function to write an integer as SML does.
def sml_int(n: int) -> str:
    """``~3`` for -3.

    Args:
        n (int): The integer.

    Returns:
        str: The text.
    """
    return str(n).replace("-", "~")


# Function to write a real as SML does.
def sml_real(x: float) -> str:
    """``2.5``, ``3.0``, ``~1.5``, ``1E10``: SML/NJ's ``Real.toString``.

    Args:
        x (float): The real.

    Returns:
        str: The text.
    """
    if math.isnan(x):
        return "nan"
    if math.isinf(x):
        return "inf" if x > 0 else "~inf"
    text = f"{x:.12g}"
    if "e" in text:
        mantissa, exponent = text.split("e")
        text = f"{mantissa}E{int(exponent)}"
    elif "." not in text:
        text += ".0"
    return text.replace("-", "~")


# ---------------------------------------------------------------------------
# Integers and reals
# ---------------------------------------------------------------------------

# Function to read an integer as Int.fromString does.
def _int_from_string(text: str):
    """``SOME n`` for the leading integer of ``text``, else ``NONE``.

    Args:
        text (str): The text.

    Returns:
        ConValue|EnumValue: ``SOME n`` or ``NONE``.
    """
    s = text.lstrip()
    sign, i = 1, 0
    if s[:1] in ("~", "-", "+"):
        sign, i = (1 if s[0] == "+" else -1), 1
    j = i
    while j < len(s) and s[j].isdigit():
        j += 1
    if j == i:
        return NONE
    return SOME(sign * int(s[i:j]))


# Function to compare two values into SML's order type.
def _compare(pair):
    """``LESS``, ``EQUAL`` or ``GREATER``.

    Args:
        pair (tuple): ``(a, b)``.

    Returns:
        EnumValue: The order.
    """
    a, b = pair
    return LESS if a < b else (GREATER if a > b else EQUAL)


# ---------------------------------------------------------------------------
# Strings and characters
# ---------------------------------------------------------------------------

# Function to take a substring as SML does.
def _substring(args):
    """``String.substring (s, i, n)``.

    Args:
        args (tuple): ``(s, i, n)``.

    Returns:
        str: The substring.
    """
    s, i, n = args
    if i < 0 or n < 0 or i + n > len(s):
        _raise("Subscript", f"substring ({s!r}, {i}, {n})")
    return s[i:i + n]


# Function to extract the end of a string as SML does.
def _extract(args):
    """``String.extract (s, i, NONE | SOME n)``.

    Args:
        args (tuple): ``(s, i, option)``.

    Returns:
        str: The extract.
    """
    s, i, opt = args
    if isinstance(opt, ConValue):
        return _substring((s, i, opt.payload))
    if i < 0 or i > len(s):
        _raise("Subscript", f"extract ({s!r}, {i})")
    return s[i:]


# Function to index a string.
def _sub(args):
    """``String.sub (s, i)``.

    Args:
        args (tuple): ``(s, i)``.

    Returns:
        str: The character.
    """
    s, i = args
    if not 0 <= i < len(s):
        _raise("Subscript", f"sub ({s!r}, {i})")
    return s[i]


# Function to split a string on separator characters.
def _split(keep_empty: bool):
    """``String.fields`` (keeps empty fields) or ``String.tokens``.

    Args:
        keep_empty (bool): Fields rather than tokens.

    Returns:
        callable: ``is_separator -> string -> string list``.
    """
    def by(is_sep):
        def split(s):
            parts, cur = [], []
            for ch in s:
                if is_sep(ch):
                    parts.append("".join(cur))
                    cur = []
                else:
                    cur.append(ch)
            parts.append("".join(cur))
            return tuple(p for p in parts if keep_empty or p)
        return split
    return by


# Function to give a character from its code.
def _chr(code: int) -> str:
    """``chr n``.

    Args:
        code (int): The code.

    Returns:
        str: The character.
    """
    if not 0 <= code <= 255:
        _raise("Chr", f"chr {code}")
    return chr(code)


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------

# Function to give the head of a list.
def _hd(xs):
    """``hd xs``.

    Args:
        xs (tuple): The list.

    Returns:
        The first element.
    """
    if not xs:
        _raise("Empty", "hd of an empty list")
    return xs[0]


# Function to give the tail of a list.
def _tl(xs):
    """``tl xs``.

    Args:
        xs (tuple): The list.

    Returns:
        tuple: All but the first element.
    """
    if not xs:
        _raise("Empty", "tl of an empty list")
    return xs[1:]


# Function to give the last element of a list.
def _last(xs):
    """``List.last xs``.

    Args:
        xs (tuple): The list.

    Returns:
        The last element.
    """
    if not xs:
        _raise("Empty", "List.last of an empty list")
    return xs[-1]


# Function to index a list.
def _nth(args):
    """``List.nth (xs, i)``.

    Args:
        args (tuple): ``(xs, i)``.

    Returns:
        The element.
    """
    xs, i = args
    if not 0 <= i < len(xs):
        _raise("Subscript", f"List.nth (_, {i}) of a list of {len(xs)}")
    return xs[i]


# Function to take a prefix of a list.
def _take(args):
    """``List.take (xs, n)``.

    Args:
        args (tuple): ``(xs, n)``.

    Returns:
        tuple: The first ``n`` elements.
    """
    xs, n = args
    if not 0 <= n <= len(xs):
        _raise("Subscript", f"List.take (_, {n}) of a list of {len(xs)}")
    return xs[:n]


# Function to drop a prefix of a list.
def _drop(args):
    """``List.drop (xs, n)``.

    Args:
        args (tuple): ``(xs, n)``.

    Returns:
        tuple: All but the first ``n`` elements.
    """
    xs, n = args
    if not 0 <= n <= len(xs):
        _raise("Subscript", f"List.drop (_, {n}) of a list of {len(xs)}")
    return xs[n:]


# Function to fold a list from the left.
def _foldl(f):
    """``foldl f init xs``, with ``f (x, acc)``.

    Args:
        f (callable): The step.

    Returns:
        callable: ``init -> xs -> result``.
    """
    def with_init(init):
        def over(xs):
            acc = init
            for x in xs:
                acc = f((x, acc))
            return acc
        return over
    return with_init


# Function to fold a list from the right.
def _foldr(f):
    """``foldr f init xs``, with ``f (x, acc)``.

    Args:
        f (callable): The step.

    Returns:
        callable: ``init -> xs -> result``.
    """
    def with_init(init):
        def over(xs):
            acc = init
            for x in reversed(xs):
                acc = f((x, acc))
            return acc
        return over
    return with_init


# Function to find the first element satisfying a predicate.
def _find(p):
    """``List.find p xs``.

    Args:
        p (callable): The predicate.

    Returns:
        callable: ``xs -> option``.
    """
    def over(xs):
        for x in xs:
            if p(x):
                return SOME(x)
        return NONE
    return over


# Function to keep the SOME results of a function.
def _map_partial(f):
    """``List.mapPartial f xs``.

    Args:
        f (callable): ``x -> option``.

    Returns:
        callable: ``xs -> list``.
    """
    def over(xs):
        out = []
        for x in xs:
            r = f(x)
            if isinstance(r, ConValue):
                out.append(r.payload)
        return tuple(out)
    return over


# Function to sort a list with a less-than function.
def _sort(lt):
    """``sort lt xs`` (CPN Tools; also ``Misc.sort``): ascending by ``lt``.

    Args:
        lt (callable): ``(a, b) -> bool``.

    Returns:
        callable: ``xs -> sorted list``.
    """
    def cmp(a, b):
        return -1 if lt((a, b)) else (1 if lt((b, a)) else 0)
    return lambda xs: tuple(sorted(xs, key=functools.cmp_to_key(cmp)))


# ---------------------------------------------------------------------------
# CPN Tools' list functions (they treat lists as bags)
# ---------------------------------------------------------------------------

# Function to remove the first occurrence of an element.
def _rm_first(x, xs):
    """``rm x xs`` as a plain function.

    Args:
        x: The element.
        xs (tuple): The list.

    Returns:
        tuple: The list without its first ``x``.
    """
    for i, y in enumerate(xs):
        if y == x:
            return xs[:i] + xs[i + 1:]
    return xs


# Function to tell whether every element of a list is in another.
def _contains_all(ys):
    """``contains_all ys xs``: ``xs`` is a sub-bag of ``ys``.

    Args:
        ys (tuple): The larger list.

    Returns:
        callable: ``xs -> bool``.
    """
    def of(xs):
        rest = ys
        for x in xs:
            if x not in rest:
                return False
            rest = _rm_first(x, rest)
        return True
    return of


# Function to intersect two lists as bags.
def _intersect(xs):
    """``intersect xs ys``: the common elements, counted as in a bag.

    Args:
        xs (tuple): A list.

    Returns:
        callable: ``ys -> list``.
    """
    def with_(ys):
        out, rest = [], ys
        for x in xs:
            if x in rest:
                out.append(x)
                rest = _rm_first(x, rest)
        return tuple(out)
    return with_


# Function to subtract a list from another as bags.
def _listsub(xs):
    """``listsub xs ys``; ``Subtract`` when ``ys`` is not a sub-bag of ``xs``.

    Args:
        xs (tuple): The list.

    Returns:
        callable: ``ys -> list``.
    """
    def minus(ys):
        rest = xs
        for y in ys:
            if y not in rest:
                _raise("Subtract", f"listsub: {y!r} is not in the list")
            rest = _rm_first(y, rest)
        return rest
    return minus


# Function to drop duplicates, keeping the last occurrence.
def _remdupl(xs):
    """``remdupl xs``: an element is kept where it last occurs.

    Args:
        xs (tuple): The list.

    Returns:
        tuple: The list without duplicates.
    """
    return tuple(x for i, x in enumerate(xs) if x not in xs[i + 1:])


# ---------------------------------------------------------------------------
# Multisets
# ---------------------------------------------------------------------------

# Function to sort a multiset's elements for listing.
def _ordered(ms: MultiSet):
    """The elements of a multiset, each repeated, in sorted order.

    CPN Tools keeps a place's tokens sorted; the order of a multiset built
    by ``++`` is not part of its meaning.

    Args:
        ms (MultiSet): The multiset.

    Returns:
        tuple: The elements.
    """
    items = list(ms.items())
    try:
        items.sort(key=lambda kv: kv[0])
    except TypeError:
        items.sort(key=lambda kv: repr(kv[0]))
    return tuple(v for v, c in items for _ in range(c))


# Function to give the coefficient of a colour in a multiset.
def _cf(args) -> int:
    """``cf (c, ms)``.

    Args:
        args (tuple): ``(colour, multiset)``.

    Returns:
        int: How often the colour occurs.
    """
    colour, ms = args
    return _as_multiset(ms).counts.get(colour, 0)


# Function to turn a one-element multiset into its colour.
def _ms_to_col(ms):
    """``ms_to_col ms``; an exception unless ``ms`` has exactly one element.

    Args:
        ms (MultiSet): The multiset.

    Returns:
        The colour.
    """
    ms = _as_multiset(ms)
    if len(ms) != 1:
        _raise("ms_to_col", f"{len(ms)} elements, not 1")
    return next(iter(ms.counts))


# Function to map a function over a multiset.
def _ext_col(f):
    """``ext_col f ms``: ``f`` applied to every element.

    Args:
        f (callable): The function.

    Returns:
        callable: ``ms -> ms``.
    """
    def over(ms):
        out: Dict[Any, int] = {}
        for v, c in _as_multiset(ms).items():
            r = f(v)
            out[r] = out.get(r, 0) + c
        return MultiSet(out)
    return over


# Function to map a multiset-valued function over a multiset.
def _ext_ms(f):
    """``ext_ms f ms``: the sum of ``f x`` over the elements.

    Args:
        f (callable): ``x -> multiset``.

    Returns:
        callable: ``ms -> ms``.
    """
    def over(ms):
        out: Dict[Any, int] = {}
        for v, c in _as_multiset(ms).items():
            for w, d in _as_multiset(f(v)).items():
                out[w] = out.get(w, 0) + c * d
        return MultiSet(out)
    return over


# Function to keep the elements of a multiset satisfying a predicate.
def _filter(p):
    """``filter p ms``.

    Args:
        p (callable): The predicate.

    Returns:
        callable: ``ms -> ms``.
    """
    return lambda ms: MultiSet({v: c for v, c in _as_multiset(ms).items()
                                if p(v)})


# Function to compare two multisets by inclusion.
def ms_compare(op: str) -> Callable:
    """The multiset comparisons ``== <><> << <<= >> >>=``.

    Args:
        op (str): The operator.

    Returns:
        callable: ``(a, b) -> bool``.
    """
    def sub(a, b):
        return all(b.counts.get(v, 0) >= c for v, c in a.items())

    def compare(left, right):
        a, b = _as_multiset(left), _as_multiset(right)
        if op == "==":
            return a == b
        if op == "<><>":
            return a != b
        if op == "<<=":
            return sub(a, b)
        if op == "<<":
            return sub(a, b) and a != b
        if op == ">>=":
            return sub(b, a)
        return sub(b, a) and a != b                    # ">>"
    return compare


# Function to refuse a random choice.
def _no_random(_ms):
    """``random ms`` draws by chance: no occurrence graph has it.

    Args:
        _ms: The multiset.

    Raises:
        MLError: Always.
    """
    raise MLError("random draws a value by chance; a net that does has no "
                  "deterministic occurrence graph and is not supported")


# ---------------------------------------------------------------------------
# Constructors and the environment
# ---------------------------------------------------------------------------

SOME = DataConstructor("SOME")
NONE = EnumValue("NONE")
LESS, EQUAL, GREATER = EnumValue("LESS"), EnumValue("EQUAL"), EnumValue("GREATER")

#: Constructors and constants every pattern may name.
SYMBOLS: Dict[str, Any] = {"SOME": SOME, "NONE": NONE, "LESS": LESS,
                           "EQUAL": EQUAL, "GREATER": GREATER}

#: SML's standard exceptions, and CPN Tools' Subtract: values a net may
#: raise and handle.
for _name in ("Empty", "Subscript", "Option", "Div", "Chr", "Size", "Domain",
              "Overflow", "Match", "Bind", "Subtract"):
    SYMBOLS[_name] = EnumValue(_name)
SYMBOLS["Fail"] = DataConstructor("Fail")


# Function to give the value inside an option.
def _val_of(opt):
    """``valOf (SOME x)``; the exception ``Option`` for ``NONE``.

    Args:
        opt: The option.

    Returns:
        The value.
    """
    if isinstance(opt, ConValue):
        return opt.payload
    _raise("Option", "valOf NONE")


# Function to give an option's value or a default.
def _get_opt(args):
    """``getOpt (opt, default)``.

    Args:
        args (tuple): ``(option, default)``.

    Returns:
        The value or the default.
    """
    opt, default = args
    return opt.payload if isinstance(opt, ConValue) else default


_is_some = lambda opt: isinstance(opt, ConValue)                # noqa: E731
_map = lambda f: lambda xs: tuple(f(x) for x in xs)             # noqa: E731
_floor = lambda x: int(math.floor(x))                           # noqa: E731
_ceil = lambda x: int(math.ceil(x))                             # noqa: E731
_explode = lambda s: tuple(s)                                   # noqa: E731
_implode = lambda cs: "".join(cs)                               # noqa: E731
_concat = lambda xs: "".join(xs)                                # noqa: E731
_rev = lambda xs: tuple(reversed(xs))                           # noqa: E731
_size = lambda v: len(v)                                        # noqa: E731

#: Every standard name, keyed as a net writes it.
LIBRARY: Dict[str, Any] = {
    # Integers.
    "abs": abs,
    "Int.abs": abs,
    "Int.max": lambda p: max(p[0], p[1]),
    "Int.min": lambda p: min(p[0], p[1]),
    "Int.sign": lambda n: (n > 0) - (n < 0),
    "Int.toString": sml_int,
    "Int.fromString": _int_from_string,
    "Int.compare": _compare,
    # Reals.
    "real": float,
    "floor": _floor,
    "ceil": _ceil,
    "round": lambda x: int(round(x)),
    "trunc": lambda x: int(x),
    "Real.fromInt": float,
    "Real.max": lambda p: max(p[0], p[1]),
    "Real.min": lambda p: min(p[0], p[1]),
    "Real.abs": abs,
    "Real.floor": _floor,
    "Real.ceil": _ceil,
    "Real.round": lambda x: int(round(x)),
    "Real.trunc": lambda x: int(x),
    "Real.toString": sml_real,
    "Real.compare": _compare,
    "Math.sqrt": math.sqrt,
    "Math.pi": math.pi,
    "Math.e": math.e,
    "Math.exp": math.exp,
    "Math.ln": math.log,
    "Math.pow": lambda p: math.pow(p[0], p[1]),
    "Math.sin": math.sin,
    "Math.cos": math.cos,
    # Booleans.
    "not": lambda b: not b,
    "Bool.toString": lambda b: "true" if b else "false",
    # Strings and characters.
    "size": _size,
    "String.size": len,
    "String.concat": _concat,
    "concat": _concat,
    "String.concatWith": lambda sep: lambda xs: sep.join(xs),
    "String.sub": _sub,
    "String.substring": _substring,
    "substring": _substring,
    "String.extract": _extract,
    "String.isPrefix": lambda p: lambda s: s.startswith(p),
    "String.isSuffix": lambda p: lambda s: s.endswith(p),
    "String.isSubstring": lambda p: lambda s: p in s,
    "String.explode": _explode,
    "explode": _explode,
    "String.implode": _implode,
    "implode": _implode,
    "String.str": lambda ch: ch,
    "str": lambda ch: ch,
    "String.map": lambda f: lambda s: "".join(f(ch) for ch in s),
    "String.translate": lambda f: lambda s: "".join(f(ch) for ch in s),
    "String.tokens": _split(False),
    "String.fields": _split(True),
    "String.compare": _compare,
    "ord": ord,
    "chr": _chr,
    "Char.ord": ord,
    "Char.chr": _chr,
    "Char.isDigit": lambda ch: ch.isdigit(),
    "Char.isAlpha": lambda ch: ch.isalpha(),
    "Char.isAlphaNum": lambda ch: ch.isalnum(),
    "Char.isUpper": lambda ch: ch.isupper(),
    "Char.isLower": lambda ch: ch.islower(),
    "Char.isSpace": lambda ch: ch in " \t\n\r\v\f",
    "Char.toUpper": lambda ch: ch.upper(),
    "Char.toLower": lambda ch: ch.lower(),
    "Char.compare": _compare,
    # Options.
    "SOME": SOME,
    "NONE": NONE,
    "isSome": _is_some,
    "Option.isSome": _is_some,
    "valOf": _val_of,
    "Option.valOf": _val_of,
    "getOpt": _get_opt,
    "Option.getOpt": _get_opt,
    "Option.map": lambda f: lambda opt: (SOME(f(opt.payload))
                                         if isinstance(opt, ConValue) else NONE),
    "LESS": LESS,
    "EQUAL": EQUAL,
    "GREATER": GREATER,
    # Lists.
    "hd": _hd,
    "tl": _tl,
    "length": len,
    "rev": _rev,
    "map": _map,
    "app": lambda f: lambda xs: (tuple(f(x) for x in xs), ())[1],
    "foldl": _foldl,
    "foldr": _foldr,
    "List.hd": _hd,
    "List.tl": _tl,
    "List.null": lambda xs: len(xs) == 0,
    "List.length": len,
    "List.rev": _rev,
    "List.last": _last,
    "List.nth": _nth,
    "List.take": _take,
    "List.drop": _drop,
    "List.concat": lambda xss: tuple(x for xs in xss for x in xs),
    "List.map": _map,
    "List.app": lambda f: lambda xs: (tuple(f(x) for x in xs), ())[1],
    "List.filter": lambda p: lambda xs: tuple(x for x in xs if p(x)),
    "List.partition": lambda p: lambda xs: (tuple(x for x in xs if p(x)),
                                            tuple(x for x in xs if not p(x))),
    "List.all": lambda p: lambda xs: all(p(x) for x in xs),
    "List.exists": lambda p: lambda xs: any(p(x) for x in xs),
    "List.find": _find,
    "List.mapPartial": _map_partial,
    "List.foldl": _foldl,
    "List.foldr": _foldr,
    "List.tabulate": lambda p: tuple(p[1](i) for i in range(p[0])),
    "List.getItem": lambda xs: SOME((xs[0], xs[1:])) if xs else NONE,
    "ListPair.zip": lambda p: tuple(zip(p[0], p[1])),
    "ListPair.unzip": lambda xs: (tuple(a for a, _ in xs),
                                  tuple(b for _, b in xs)),
    "ListPair.map": lambda f: lambda p: tuple(f((a, b)) for a, b in zip(*p)),
    "ListPair.all": lambda f: lambda p: all(f((a, b)) for a, b in zip(*p)),
    "ListPair.exists": lambda f: lambda p: any(f((a, b)) for a, b in zip(*p)),
    "ListPair.foldl": lambda f: lambda init: lambda p: _foldl(
        lambda t: f((t[0][0], t[0][1], t[1])))(init)(tuple(zip(*p))),
    "sort": _sort,
    "Misc.sort": _sort,
    # CPN Tools' list functions.
    "mem": lambda xs: lambda x: x in xs,
    "rm": lambda x: lambda xs: _rm_first(x, xs),
    "rmall": lambda x: lambda xs: tuple(y for y in xs if y != x),
    "contains": lambda ys: lambda xs: all(x in ys for x in xs),
    "contains_all": _contains_all,
    "remdupl": _remdupl,
    "intersect": _intersect,
    "union": lambda xs: lambda ys: xs + ys,
    "listsub": _listsub,
    "ins": lambda xs: lambda x: xs + (x,),
    "ins_new": lambda xs: lambda x: xs if x in xs else xs + (x,),
    # Multisets.
    "empty": MultiSet(),
    "cf": _cf,
    "ms_to_col": _ms_to_col,
    "ms_to_list": lambda ms: _ordered(_as_multiset(ms)),
    "list_to_ms": lambda xs: MultiSet(dict(_count(xs))),
    "ext_col": _ext_col,
    "ext_ms": _ext_ms,
    "filter": _filter,
    "random": _no_random,
}

# Function to give a multiset's elements as a list.
def _as_list(value):
    """A multiset as the list of its elements; anything else unchanged.

    In CPN Tools ``'a ms`` *is* ``'a list``, so the list functions apply to
    multisets: ``map f (CS.all ())`` is a list of images.

    Args:
        value: An argument.

    Returns:
        The argument, a multiset replaced by its elements in order.
    """
    if isinstance(value, MultiSet):
        return tuple(v for v, c in value.items() for _ in range(c))
    if type(value) is tuple and any(isinstance(v, MultiSet) for v in value):
        return tuple(_as_list(v) for v in value)
    return value


# Function to make a list function accept multisets.
def _on_lists(function):
    """Wrap a (possibly curried) function so multiset arguments are lists.

    Args:
        function (callable): The list function.

    Returns:
        callable: The wrapped function.
    """
    def wrapped(argument):
        result = function(_as_list(argument))
        if callable(result) and not isinstance(result, (DataConstructor,)):
            return _on_lists(result)
        return result
    return wrapped


#: The names whose arguments may be multisets used as lists.
LIST_FUNCTIONS = (
    "hd", "tl", "length", "rev", "map", "app", "foldl", "foldr",
    "mem", "rm", "rmall", "contains", "contains_all", "remdupl", "intersect",
    "union", "listsub", "ins", "ins_new", "sort", "Misc.sort")

LIBRARY.update({name: _on_lists(LIBRARY[name]) for name in LIST_FUNCTIONS})
LIBRARY.update({name: _on_lists(f) for name, f in list(LIBRARY.items())
                if name.startswith(("List.", "ListPair."))})


#: CPN Tools' random distribution functions: each draws a value by chance.
DISTRIBUTIONS = ("bernoulli", "beta", "binomial", "chisq", "discrete",
                 "erlang", "exponential", "gamma", "normal", "poisson",
                 "rayleigh", "student", "uniform", "weibull")


# Function to build a distribution that refuses.
def _no_distribution(name: str):
    """A distribution function raising :class:`MLError` when called.

    Args:
        name (str): The distribution.

    Returns:
        callable: The refusing function.
    """
    def draw(*_args):
        raise MLError(f"{name} draws a random value; a net that does has no "
                      "deterministic occurrence graph and is not supported")
    return draw


LIBRARY.update({name: _no_distribution(name) for name in DISTRIBUTIONS})
LIBRARY.update(SYMBOLS)


# Function to count the elements of a list.
def _count(xs):
    """``(value, count)`` pairs of a list, in first-occurrence order.

    Args:
        xs (tuple): The list.

    Returns:
        list: The pairs.
    """
    counts: Dict[Any, int] = {}
    for x in xs:
        counts[x] = counts.get(x, 0) + 1
    return list(counts.items())
