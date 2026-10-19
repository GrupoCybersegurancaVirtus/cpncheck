"""Colour sets, and the declarations a net makes about itself.

CPN Tools keeps colour sets and variables as structured XML rather than as ML
text, so they are read from the elements directly. What they are needed for is
the *domain* of a variable: a transition may use a variable no input arc binds,
and CPN Tools then enumerates that variable over its colour set to find the
binding elements. Without a domain there is nothing to enumerate and the net
cannot be explored.

Only some colour sets are finite. ``unit``, ``bool``, an enumeration, an index
range, a bounded integer, and products, records, subsets and aliases built from
those are; ``int``, ``real``, ``string`` and lists are not. An infinite domain
is reported as None rather than guessed at, and the caller refuses the net.

Values are Python values, chosen so that a marking stays hashable and
orderable: a record is a tuple in declared field order, a list is a tuple, and
unit is the empty tuple.
"""

import itertools
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .cpnml import (PRELUDE, EnumValue, IndexConstructor, IndexValue, MLError,
                    MultiSet, compile_expression, parse_declarations,
                    parse_expression)

__all__ = ["ColourSet", "Declarations"]

#: Colour sets whose values cannot be enumerated.
INFINITE = ("int", "real", "string", "list", "unknown")

#: How many values a domain may have before enumeration is refused.
MAX_DOMAIN = 100_000


# Class describing one declared colour set.
class ColourSet:
    """A declared colour set.

    Attributes:
        name (str): Its name.
        kind (str): ``unit``, ``bool``, ``int``, ``real``, ``string``,
            ``enum``, ``index`` (a bounded int), ``indexed`` (``index u with
            1..n``, values ``u(i)``), ``product``, ``record``, ``list``,
            ``subset``, ``alias`` or ``unknown``.
        parts (list): Component colour set names, for products and records.
        labels (list): Field names, for records.
        values (list): The explicit values, for enumerations and subsets.
        base (str): The underlying colour set, for aliases and subsets; the
            constructor name, for an ``indexed`` colour set.
        bounds (tuple): The two ML texts of an ``indexed`` colour set's range,
            evaluated once the net's values are known.
        timed (bool): Whether the colour set is timed.
    """

    __slots__ = ("name", "kind", "parts", "labels", "values", "base", "timed",
                 "bounds", "_domain")

    # Method to build a colour set description.
    def __init__(self, name, kind, parts=None, labels=None, values=None,
                 base=None, timed=False):
        """Create the description.

        Args:
            name (str): Colour set name.
            kind (str): The kind.
            parts (list, optional): Component colour sets.
            labels (list, optional): Record field names.
            values (list, optional): Explicit values.
            base (str, optional): Underlying colour set.
            timed (bool): Whether it is timed.
        """
        self.name = name
        self.kind = kind
        self.parts = list(parts or [])
        self.labels = list(labels or [])
        self.values = list(values or [])
        self.base = base
        self.timed = timed
        self.bounds: Tuple[str, ...] = ()
        self._domain: Any = False              # False means "not computed"

    # Method to compute the values of the colour set.
    def domain(self, sets: Dict[str, "ColourSet"]) -> Optional[Tuple]:
        """Every value of the colour set, when there are finitely many.

        Args:
            sets (dict): Every declared colour set, for the components.

        Returns:
            tuple|None: The values, or None when the colour set is infinite,
            too large to enumerate, or not understood.
        """
        if self._domain is not False:
            return self._domain
        self._domain = None                    # guards against a cycle
        self._domain = self._compute(sets)
        return self._domain

    # Method to enumerate the colour set.
    def _compute(self, sets) -> Optional[Tuple]:
        """Work out the values, recursing into the components.

        Args:
            sets (dict): Every declared colour set.

        Returns:
            tuple|None: The values, or None.
        """
        if self.kind in INFINITE:
            return None
        if self.kind == "unit":
            return ((),)
        if self.kind == "bool":
            return (False, True)
        if self.kind in ("enum", "index"):
            return tuple(self.values)
        if self.kind == "indexed":
            return tuple(self.values) if self.values else None
        if self.kind == "alias":
            other = sets.get(self.base)
            return other.domain(sets) if other else None
        if self.kind == "subset":
            # Only once the predicate or the listing has been evaluated;
            # before that the subset is unknown, never its base.
            return tuple(self.values) if self.values else None
        if self.kind in ("product", "record"):
            parts = []
            for name in self.parts:
                other = sets.get(name)
                values = other.domain(sets) if other else None
                if values is None:
                    return None
                parts.append(values)
            size = 1
            for values in parts:
                size *= len(values)
                if size > MAX_DOMAIN:
                    return None
            return tuple(itertools.product(*parts))
        return None

    # Method to render the colour set for debugging.
    def __repr__(self):
        """Return a short representation.

        Returns:
            str: ``<ColourSet SAMPLE record>``.
        """
        return f"<ColourSet {self.name} {self.kind}>"


# Function to read the name and body of one colour declaration.
def _read_colour(element: ET.Element) -> Optional[ColourSet]:
    """Turn one ``<color>`` element into a colour set.

    Args:
        element (Element): The ``<color>`` element.

    Returns:
        ColourSet|None: The colour set, or None when it has no name.
    """
    name_el = element.find("id")
    if name_el is None or not (name_el.text or "").strip():
        return None
    name = name_el.text.strip()
    timed = element.find("timed") is not None
    body = None
    for child in element:
        if child.tag not in ("id", "layout", "timed"):
            body = child
            break
    if body is None:
        return ColourSet(name, "unknown", timed=timed)

    kind = body.tag
    if kind in ("unit", "bool", "int", "real", "string", "intinf", "time"):
        values = _with_values(body)
        if kind == "int" and len(values) == 2:
            try:
                low, high = int(values[0]), int(values[1])
            except (TypeError, ValueError):
                return ColourSet(name, "int", timed=timed)
            if 0 <= high - low <= MAX_DOMAIN:
                return ColourSet(name, "index",
                                 values=list(range(low, high + 1)), timed=timed)
        mapped = {"intinf": "int", "time": "int"}.get(kind, kind)
        return ColourSet(name, mapped, timed=timed)
    if kind == "enum":
        return ColourSet(name, "enum",
                         values=[EnumValue((i.text or "").strip())
                                 for i in body.findall("id")],
                         timed=timed)
    if kind == "index":
        # colset U = index u with 1..10: the bounds are <ml> children, and may
        # be declared names (with NoOfSites), so they are evaluated later.
        bounds = [("".join(ml.itertext())).strip() for ml in body.findall("ml")]
        bounds = bounds or _with_values(body)
        ctor = body.find("id")
        if len(bounds) != 2 or ctor is None or not (ctor.text or "").strip():
            return ColourSet(name, "unknown", timed=timed)
        colset = ColourSet(name, "indexed", base=ctor.text.strip(), timed=timed)
        colset.bounds = tuple(bounds)
        return colset
    if kind == "product":
        return ColourSet(name, "product",
                         parts=[(i.text or "").strip() for i in body.findall("id")],
                         timed=timed)
    if kind == "record":
        labels, parts = [], []
        for field in body.findall("recordfield"):
            ids = field.findall("id")
            if len(ids) >= 2:
                labels.append((ids[0].text or "").strip())
                parts.append((ids[1].text or "").strip())
        return ColourSet(name, "record", parts=parts, labels=labels, timed=timed)
    if kind == "list":
        base = body.find("id")
        return ColourSet(name, "list",
                         base=(base.text or "").strip() if base is not None else None,
                         timed=timed)
    if kind == "alias":
        base = body.find("id")
        return ColourSet(name, kind,
                         base=(base.text or "").strip() if base is not None else None,
                         timed=timed)
    if kind == "subset":
        # subset B by f / subset B with [v1, v2]: both are ML evaluated once
        # the net's values are known; until then the subset has no domain, so
        # nothing can range over the whole of B by mistake.
        base = body.find("id")
        colset = ColourSet(name, kind,
                           base=(base.text or "").strip() if base is not None
                           else None, timed=timed)
        by = body.find("by")
        if by is not None:
            colset.bounds = ("by", " ".join("".join(ml.itertext()).strip()
                                            for ml in by.findall("ml")))
        elif body.find("with") is not None:
            colset.bounds = ("with", " ".join(_with_values(body)))
        return colset
    return ColourSet(name, "unknown", timed=timed)


# Function to build a CS.ran that refuses, with a reason.
def _no_random(name: str):
    """``CS.ran ()`` draws a random colour: it has no occurrence graph.

    Args:
        name (str): The colour set.

    Returns:
        callable: A function raising :class:`MLError` when called.
    """
    def ran(_unit):
        raise MLError(f"{name}.ran() draws a random value; a net that does "
                      "has no deterministic occurrence graph and is not "
                      "supported")
    return ran


# Function to write a value of a colour set as CPN Tools' mkstr does.
def mkstr(value, colset: Optional["ColourSet"], sets: Dict[str, "ColourSet"]
          ) -> str:
    """``CS.mkstr v``: ``u(2)``, ``(u(1),b)``, ``{x=3,y=b}``, ``(~3)``...

    Args:
        value: The value.
        colset (ColourSet, optional): Its colour set; None to go by the value.
        sets (dict): Every declared colour set, for the components.

    Returns:
        str: The text, as CPN Tools writes it.
    """
    from .mllib import sml_int, sml_real

    kind = colset.kind if colset is not None else None
    if colset is not None and kind in ("alias", "subset"):
        return mkstr(value, sets.get(colset.base), sets)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, IndexValue):
        return f"{value[0]}({sml_int(value[1])})"
    if isinstance(value, EnumValue):
        return str(value)
    if isinstance(value, int):
        return sml_int(value) if value >= 0 else f"({sml_int(value)})"
    if isinstance(value, float):
        text = sml_real(value)
        return text if value >= 0 else f"({text})"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, tuple):
        parts = colset.parts if colset is not None else []
        if kind == "record":
            return "{" + ",".join(
                f"{label}={mkstr(v, sets.get(part), sets)}"
                for label, part, v in zip(colset.labels, parts, value)) + "}"
        if kind == "list":
            inner = sets.get(colset.base)
            return "[" + ",".join(mkstr(v, inner, sets) for v in value) + "]"
        if kind == "unit" or value == ():
            return "()"
        subsets = [sets.get(p) for p in parts] or [None] * len(value)
        return "(" + ",".join(mkstr(v, c, sets)
                              for v, c in zip(value, subsets)) + ")"
    return repr(value)


# Function to build the functions CPN Tools declares for every colour set.
def _colour_set_functions(name: str, colset: "ColourSet",
                          sets: Dict[str, "ColourSet"]) -> Dict[str, Any]:
    """``CS.size``, ``CS.ord``, ``CS.col``, ``CS.legal``, ``CS.mkstr``,
    ``CS.mkstr_ms`` (and ``CS.input``/``CS.output``, which refuse).

    ``ord`` and ``col`` number the values from 0 in the colour set's order;
    on an infinite colour set they, and ``size``, raise as in CPN Tools.

    Args:
        name (str): The colour set.
        colset (ColourSet): Its declaration.
        sets (dict): Every declared colour set.

    Returns:
        dict: The functions, by qualified name.
    """
    def domain():
        values = colset.domain(sets)
        if values is None:
            raise MLError(f"{name}: the colour set is not finite")
        return values

    def size(_unit):
        return len(domain())

    def ord_(value):
        values = domain()
        try:
            return values.index(value)
        except ValueError:
            raise MLError(f"{name}.ord: {value!r} is not a value of {name}")

    def col(index):
        values = domain()
        if not 0 <= index < len(values):
            raise MLError(f"{name}.col: no value number {index}")
        return values[index]

    def legal(value):
        values = colset.domain(sets)
        if values is not None:
            return value in values
        base = colset
        while base is not None and base.kind == "alias":
            base = sets.get(base.base)
        kind = base.kind if base is not None else "unknown"
        if kind == "int":
            return isinstance(value, int) and not isinstance(value, bool)
        if kind == "real":
            return isinstance(value, float)
        if kind == "string":
            return isinstance(value, str)
        if kind == "list":
            return isinstance(value, tuple)
        return True

    def mkstr_ms(ms):
        from .cpnml import _as_multiset
        items = list(_as_multiset(ms).items())
        try:
            items.sort(key=lambda kv: ord_(kv[0]))
        except MLError:
            items.sort(key=lambda kv: repr(kv[0]))
        return "++\n".join(f"{count}`{mkstr(v, colset, sets)}"
                           for v, count in items)

    def no_io(what):
        def refuse(_arg):
            raise MLError(f"{name}.{what} reads or writes a file; a net that "
                          "does has no deterministic occurrence graph")
        return refuse

    return {f"{name}.size": size, f"{name}.ord": ord_, f"{name}.col": col,
            f"{name}.legal": legal,
            f"{name}.mkstr": lambda v: mkstr(v, colset, sets),
            f"{name}.mkstr_ms": mkstr_ms,
            f"{name}.input": no_io("input"), f"{name}.output": no_io("output")}


# Function to multiply multisets into a multiset of tuples.
def _product_of_multisets(parts) -> MultiSet:
    """``PR.mult (ms1, ms2, ...)``: every combination, counts multiplied.

    Args:
        parts (tuple): One multiset (or single value) per component.

    Returns:
        MultiSet: The product.
    """
    lists = []
    for part in parts:
        items = (list(part.items()) if isinstance(part, MultiSet)
                 else [(part, 1)])
        lists.append(items)
    out: Dict[Any, int] = {}
    for combination in itertools.product(*lists):
        value = tuple(v for v, _c in combination)
        count = 1
        for _v, c in combination:
            count *= c
        out[value] = out.get(value, 0) + count
    return MultiSet(out)


# Function to read the ML texts of a with clause.
def _with_values(element: ET.Element) -> List[str]:
    """The ``<ml>`` texts under a ``<with>`` child.

    Args:
        element (Element): The colour set body.

    Returns:
        list: The texts, in order.
    """
    clause = element.find("with")
    if clause is None:
        return []
    return [("".join(ml.itertext())).strip() for ml in clause.findall("ml")]


# Class holding everything a net declares about itself.
class Declarations:
    """Colour sets, variables and declared values of one net.

    Attributes:
        colsets (dict): ``name -> ColourSet``.
        variables (dict): ``variable -> colour set name``.
        fields (dict): ``record field label -> index``, for ``#label`` in an
            expression.
        globals (dict): Names every expression can use: the prelude, the
            constants and constructors of the colour sets, the net's own
            ``val`` and ``fun`` declarations, then whatever the caller added.
        symbols (dict): The constants (enumeration values) and constructors
            (of ``index`` colour sets) a pattern must not read as variables.
        problems (list): Declarations that could not be read, as text.
    """

    # Method to read the declarations of a parsed net.
    def __init__(self, path: str, prelude: Optional[Dict[str, Any]] = None):
        """Read every declaration of a ``.cpn`` file.

        Args:
            path (str): The ``.cpn`` file.
            prelude (dict, optional): Extra names, which win over the net's
                own declarations -- that is how a caller supplies the meaning
                of a function the net only declares in a form this cannot
                read.
        """
        self.colsets: Dict[str, ColourSet] = {}
        self.variables: Dict[str, str] = {}
        self.fields: Dict[str, int] = {}
        self.globals: Dict[str, Any] = dict(PRELUDE)
        self.symbols: Dict[str, Any] = {}
        self.problems: List[str] = []
        try:
            root = ET.parse(path).getroot()
        except Exception as exc:               # noqa: BLE001
            self.problems.append(f"the file could not be parsed: {exc}")
            root = None
        if root is not None:
            self._read_colours(root)
            self._read_variables(root)
            self._declare_colour_values()
            self._read_values(root)
            self._resolve_indexed()
            self._resolve_subsets()
        if prelude:
            self.globals.update(prelude)

    # Method to read every colour set declaration.
    def _read_colours(self, root) -> None:
        """Collect the colour sets and the record field positions.

        Args:
            root (Element): The document root.
        """
        for element in root.iter("color"):
            colset = _read_colour(element)
            if colset is None:
                continue
            self.colsets[colset.name] = colset
            for index, label in enumerate(colset.labels):
                if self.fields.get(label, index) != index:
                    self.problems.append(
                        f"field {label!r} is at a different position in two "
                        "record colour sets; #" + label + " is ambiguous")
                self.fields.setdefault(label, index)

    # Method to make the colour sets' constants and functions available.
    def _declare_colour_values(self) -> None:
        """Enumeration constants, index constructors and ``CS.all()``.

        These go into :attr:`symbols` too, so that the parser reads ``e`` in a
        pattern as the constant, not as a fresh variable.
        """
        for colset in self.colsets.values():
            if colset.kind == "enum":
                for value in colset.values:
                    self.symbols[str(value)] = value
            elif colset.kind == "indexed":
                self.symbols[colset.base] = IndexConstructor(colset.base)
        self.globals.update(self.symbols)
        for name, colset in self.colsets.items():
            self.globals[f"{name}.all"] = self._all_of(colset)
            self.globals[f"{name}.ran"] = _no_random(name)
            if colset.kind == "product":
                self.globals[f"{name}.mult"] = _product_of_multisets
            self.globals.update(_colour_set_functions(name, colset,
                                                      self.colsets))

    # Method to build the CS.all() function of a colour set.
    def _all_of(self, colset: "ColourSet"):
        """``CS.all ()``: every value of the colour set, as a multiset.

        Args:
            colset (ColourSet): The colour set.

        Returns:
            callable: The function; it raises :class:`MLError` for an infinite
            colour set.
        """
        def all_values(_unit, colset=colset, sets=self.colsets):
            values = colset.domain(sets)
            if values is None:
                raise MLError(f"{colset.name}.all: the colour set is not finite")
            return MultiSet({v: 1 for v in values})
        return all_values

    # Method to evaluate the ranges of the index colour sets.
    def _resolve_indexed(self) -> None:
        """Evaluate ``low..high`` of every ``index`` colour set.

        Done after the values are read, because a bound may be a declared name
        (``index S with 1..NoOfSites``). A range that cannot be evaluated
        leaves the colour set without a domain, which refuses any variable
        that would have to range over it.
        """
        for colset in self.colsets.values():
            if colset.kind != "indexed":
                continue
            try:
                low, high = (int(self.evaluate(b)) for b in colset.bounds)
            except (MLError, TypeError, ValueError) as exc:
                self.problems.append(f"{colset.name}: range {colset.bounds}: "
                                     f"{exc}")
                continue
            if not 0 <= high - low <= MAX_DOMAIN:
                continue
            ctor = self.symbols[colset.base]
            ctor.low, ctor.high = low, high
            colset.values = [IndexValue(colset.base, i)
                             for i in range(low, high + 1)]
            colset._domain = False

    # Method to evaluate the subset colour sets.
    def _resolve_subsets(self) -> None:
        """Compute the values of ``subset B by f`` and ``subset B with [...]``.

        ``by f`` keeps the values of ``B`` for which ``f`` holds; ``with``
        lists them. A subset that cannot be evaluated keeps no domain, so a
        variable ranging over it is refused rather than given ``B``'s values.
        """
        for colset in self.colsets.values():
            if colset.kind != "subset" or not colset.bounds:
                continue
            how, text = colset.bounds
            try:
                if how == "by":
                    base = self.colsets.get(colset.base)
                    values = base.domain(self.colsets) if base else None
                    if values is None:
                        continue
                    keep = self.evaluate(text)
                    colset.values = [v for v in values if keep(v)]
                else:
                    listed = self.evaluate(text)
                    colset.values = list(listed.counts if isinstance(
                        listed, MultiSet) else listed)
            except (MLError, TypeError) as exc:
                self.problems.append(f"{colset.name}: subset {how} {text!r}: "
                                     f"{exc}")
                continue
            colset._domain = False

    # Method to read every variable declaration.
    def _read_variables(self, root) -> None:
        """Collect the declared variables and their colour sets.

        Args:
            root (Element): The document root.
        """
        for element in root.iter("var"):
            type_el = element.find("type/id")
            if type_el is None:
                continue
            colset = (type_el.text or "").strip()
            for name_el in element.findall("id"):
                name = (name_el.text or "").strip()
                if name:
                    self.variables[name] = colset

    # Method to read every val and fun declaration.
    def _read_values(self, root) -> None:
        """Compile the net's own ``val`` and ``fun`` declarations.

        A declaration that cannot be read is recorded and skipped: nets
        declare things the checker never needs, and refusing the whole net
        because of one of them would be wrong. A declaration that *is* needed
        and missing shows up later as an unbound name.

        Args:
            root (Element): The document root.
        """
        for element in root.iter("ml"):
            text = "".join(element.itertext()).strip()
            if not text:
                continue
            try:
                entries = parse_declarations(text, self.symbols)
            except MLError as exc:
                self.problems.append(f"{text.splitlines()[0][:60]}: {exc}")
                continue
            for entry in entries:
                if entry[0] == "error":
                    self.problems.append(entry[1])
                    continue
                try:
                    self._bind(entry)
                except MLError as exc:
                    self.problems.append(f"{entry[1]!r}: {exc}")

    # Method to evaluate one declaration into the global environment.
    def _bind(self, entry) -> None:
        """Add one ``val`` or ``fun`` declaration to :attr:`globals`.

        Args:
            entry (tuple): A parsed declaration.

        Raises:
            MLError: When the declaration cannot be compiled or matched.
        """
        from .cpnml import match_pattern       # local: avoids a cycle at import

        kind = entry[0]
        if kind == "fun":
            _name, tree = entry[1], entry[2]
            value = compile_expression(tree, self.globals, self.fields)({})
            if hasattr(value, "name"):
                value.name = entry[1]
            self.globals[entry[1]] = value
            return
        pattern, tree = entry[1], entry[2]
        value = compile_expression(tree, self.globals, self.fields)({})
        bound = match_pattern(pattern, value, {}, self.fields)
        if bound is None:
            raise MLError("the declared pattern does not match its value")
        self.globals.update(bound)

    # Method to give the values a variable may take.
    def domain_of(self, variable: str) -> Optional[Tuple]:
        """Every value a variable may be bound to.

        Args:
            variable (str): The variable name.

        Returns:
            tuple|None: The values, or None when the variable is undeclared or
            its colour set is infinite.
        """
        name = self.variables.get(variable)
        colset = self.colsets.get(name) if name else None
        return colset.domain(self.colsets) if colset else None

    # Method to evaluate a literal expression in the declared environment.
    def evaluate(self, text: str):
        """Compile and run an expression against the declarations alone.

        Args:
            text (str): CPN ML source.

        Returns:
            The value.

        Raises:
            MLError: When it cannot be parsed, compiled or run.
        """
        return compile_expression(parse_expression(text, self.symbols),
                                  self.globals, self.fields)({})

    # Method to render the declarations for debugging.
    def __repr__(self):
        """Return a short representation.

        Returns:
            str: ``<Declarations 12 colsets, 3 vars>``.
        """
        return (f"<Declarations {len(self.colsets)} colsets, "
                f"{len(self.variables)} vars>")
