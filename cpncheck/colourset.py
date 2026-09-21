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

from .cpnml import (PRELUDE, MLError, compile_expression, parse_declarations,
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
            ``enum``, ``index``, ``product``, ``record``, ``list``,
            ``subset``, ``alias`` or ``unknown``.
        parts (list): Component colour set names, for products and records.
        labels (list): Field names, for records.
        values (list): The explicit values, for enumerations and subsets.
        base (str): The underlying colour set, for aliases and subsets.
        timed (bool): Whether the colour set is timed.
    """

    __slots__ = ("name", "kind", "parts", "labels", "values", "base", "timed",
                 "_domain")

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
        if self.kind == "alias":
            other = sets.get(self.base)
            return other.domain(sets) if other else None
        if self.kind == "subset":
            if self.values:
                return tuple(self.values)
            other = sets.get(self.base)
            return other.domain(sets) if other else None
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
                         values=[(i.text or "").strip() for i in body.findall("id")],
                         timed=timed)
    if kind == "index":
        values = _with_values(body)
        try:
            low, high = int(values[0]), int(values[1])
        except (TypeError, ValueError, IndexError):
            return ColourSet(name, "unknown", timed=timed)
        if high - low > MAX_DOMAIN:
            return ColourSet(name, "unknown", timed=timed)
        return ColourSet(name, "index", values=list(range(low, high + 1)),
                         timed=timed)
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
    if kind in ("alias", "subset"):
        base = body.find("id")
        return ColourSet(name, kind,
                         base=(base.text or "").strip() if base is not None else None,
                         values=_with_values(body), timed=timed)
    return ColourSet(name, "unknown", timed=timed)


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
        globals (dict): Names every expression can use: the prelude, then the
            net's own ``val`` and ``fun`` declarations, then whatever the
            caller added.
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
        self.problems: List[str] = []
        try:
            root = ET.parse(path).getroot()
        except Exception as exc:               # noqa: BLE001
            self.problems.append(f"the file could not be parsed: {exc}")
            root = None
        if root is not None:
            self._read_colours(root)
            self._read_variables(root)
            self._read_values(root)
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
                entries = parse_declarations(text)
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
        return compile_expression(parse_expression(text), self.globals,
                                  self.fields)({})

    # Method to render the declarations for debugging.
    def __repr__(self):
        """Return a short representation.

        Returns:
            str: ``<Declarations 12 colsets, 3 vars>``.
        """
        return (f"<Declarations {len(self.colsets)} colsets, "
                f"{len(self.variables)} vars>")
