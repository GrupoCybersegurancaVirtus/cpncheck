"""Naming places and transitions without hard-coding indices.

A :class:`Selector` is a *description* of a set of places or transitions --
"the place called ``Prediction`` on the top page", "every transition of a page
matching ``Tree\\d+``". It is resolved against a
:class:`~cpncheck.coloured.ColouredNet` the moment a property is evaluated, so
the same property applies to any net whose naming conventions match.

A :class:`Group` is a *labelled family* of such sets: "for each tree page, its
leaf transitions and its output place". Properties quantify over a group
(``forall T: ...``), and the label is what a counterexample is attributed to.

Groups are where a caller's domain knowledge goes. The generic layer only ever
sees ``label -> {role: indices}``; how those were found -- a naming convention,
a page structure, an annotation -- is the caller's business.
"""

import collections
import re
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

__all__ = [
    "Selector",
    "Places",
    "Transitions",
    "Explicit",
    "Group",
    "outputs_of",
    "inputs_of",
]


# Function to test one name against an exact value and a regular expression.
def _matches(value: str, exact: Optional[str], pattern: Optional[str]) -> bool:
    """Whether a name satisfies the constraints given.

    Args:
        value (str): The name to test.
        exact (str, optional): Required exact value.
        pattern (str, optional): Required full-match regular expression.

    Returns:
        bool: True when every constraint given is satisfied.
    """
    if exact is not None and value != exact:
        return False
    if pattern is not None and not re.fullmatch(pattern, value):
        return False
    return True


# Class describing a set of places or transitions of a net.
class Selector:
    """A description of a set of net elements, resolved on demand.

    Subclasses implement :meth:`resolve`. Two selectors that resolve to the
    same indices are interchangeable; nothing else about them is observable.
    """

    #: What the selector denotes: ``"place"`` or ``"transition"``.
    kind = "place"

    # Method to resolve the selector against a net.
    def resolve(self, net) -> Tuple[int, ...]:
        """Indices of the elements this selector denotes.

        Args:
            net (ColouredNet): The flattened net.

        Returns:
            tuple: Indices, in net order.

        Raises:
            NotImplementedError: Always; subclasses implement this.
        """
        raise NotImplementedError

    # Method to render the selector for a counterexample.
    def describe(self, net) -> str:
        """A short human-readable name for the selected elements.

        Args:
            net (ColouredNet): The flattened net.

        Returns:
            str: Something like ``Prediction`` or ``3 transitions``.
        """
        items = self.resolve(net)
        source = net.places if self.kind == "place" else net.transitions
        if not items:
            return "(nothing)"
        if len(items) <= 3:
            return ", ".join(source[i]["name"] for i in items)
        return f"{len(items)} {self.kind}s"


# Class selecting places by name and page.
class Places(Selector):
    """Places matching a name and a page.

    With no constraint at all every place is selected, which is what
    ``AG forall p: |p| <= 1`` quantifies over.
    """

    kind = "place"

    # Method to build a place selector.
    def __init__(self, name: Optional[str] = None, page: Optional[str] = None,
                 name_re: Optional[str] = None, page_re: Optional[str] = None):
        """Create the selector.

        Args:
            name (str, optional): Exact place name.
            page (str, optional): Exact page name.
            name_re (str, optional): Regular expression the name must match.
            page_re (str, optional): Regular expression the page must match.
        """
        self.name, self.page = name, page
        self.name_re, self.page_re = name_re, page_re

    # Method to resolve the selector against a net.
    def resolve(self, net) -> Tuple[int, ...]:
        """Indices of the matching places.

        Args:
            net (ColouredNet): The flattened net.

        Returns:
            tuple: Place indices.
        """
        return tuple(i for i, p in enumerate(net.places)
                     if _matches(p["name"], self.name, self.name_re)
                     and _matches(p["page"], self.page, self.page_re))

    # Method to render the selector for debugging.
    def __repr__(self):
        """Return a short representation.

        Returns:
            str: ``Places(name='Prediction')``.
        """
        args = {"name": self.name, "page": self.page,
                "name_re": self.name_re, "page_re": self.page_re}
        inner = ", ".join(f"{k}={v!r}" for k, v in args.items() if v is not None)
        return f"Places({inner})"


# Class selecting transitions by name and page.
class Transitions(Selector):
    """Transitions matching a name and a page."""

    kind = "transition"

    # Method to build a transition selector.
    def __init__(self, name: Optional[str] = None, page: Optional[str] = None,
                 name_re: Optional[str] = None, page_re: Optional[str] = None):
        """Create the selector.

        Args:
            name (str, optional): Exact transition name.
            page (str, optional): Exact page name.
            name_re (str, optional): Regular expression the name must match.
            page_re (str, optional): Regular expression the page must match.
        """
        self.name, self.page = name, page
        self.name_re, self.page_re = name_re, page_re

    # Method to resolve the selector against a net.
    def resolve(self, net) -> Tuple[int, ...]:
        """Indices of the matching transitions.

        Args:
            net (ColouredNet): The flattened net.

        Returns:
            tuple: Transition indices.
        """
        return tuple(i for i, t in enumerate(net.transitions)
                     if _matches(t["name"], self.name, self.name_re)
                     and _matches(t["page"], self.page, self.page_re))

    # Method to render the selector for debugging.
    def __repr__(self):
        """Return a short representation.

        Returns:
            str: ``Transitions(page_re='Tree\\\\d+')``.
        """
        args = {"name": self.name, "page": self.page,
                "name_re": self.name_re, "page_re": self.page_re}
        inner = ", ".join(f"{k}={v!r}" for k, v in args.items() if v is not None)
        return f"Transitions({inner})"


# Class wrapping indices that were computed rather than matched.
class Explicit(Selector):
    """A selector over indices a caller already computed.

    Groups produce these: once "the output place of this tree" has been worked
    out, the property layer only needs the index.
    """

    # Method to wrap a set of indices.
    def __init__(self, indices: Sequence[int], kind: str = "place",
                 label: Optional[str] = None):
        """Create the selector.

        Args:
            indices (sequence): The indices.
            kind (str): ``"place"`` or ``"transition"``.
            label (str, optional): Name used when describing the selection.
        """
        self.indices = tuple(indices)
        self.kind = kind
        self.label = label

    # Method to resolve the selector against a net.
    def resolve(self, net) -> Tuple[int, ...]:
        """The wrapped indices.

        Args:
            net (ColouredNet): Ignored; the indices are already resolved.

        Returns:
            tuple: The indices.
        """
        return self.indices

    # Method to render the selector for a counterexample.
    def describe(self, net) -> str:
        """The label if one was given, otherwise the element names.

        Args:
            net (ColouredNet): The flattened net.

        Returns:
            str: The description.
        """
        return self.label if self.label else super().describe(net)

    # Method to render the selector for debugging.
    def __repr__(self):
        """Return a short representation.

        Returns:
            str: ``Explicit(3 places)``.
        """
        return f"Explicit({len(self.indices)} {self.kind}s)"


# Function to collect the places a set of transitions writes to.
def outputs_of(net, transitions: Sequence[int]) -> Tuple[int, ...]:
    """Places on the output arcs of the given transitions.

    Args:
        net (ColouredNet): The flattened net.
        transitions (sequence): Transition indices.

    Returns:
        tuple: Place indices, sorted.
    """
    return tuple(sorted({p for ti in transitions
                         for p, _ in net.transitions[ti]["out"]}))


# Function to collect the places a set of transitions reads from.
def inputs_of(net, transitions: Sequence[int]) -> Tuple[int, ...]:
    """Places on the input arcs of the given transitions.

    Args:
        net (ColouredNet): The flattened net.
        transitions (sequence): Transition indices.

    Returns:
        tuple: Place indices, sorted.
    """
    return tuple(sorted({p for ti in transitions
                         for p, _ in (net.transitions[ti]["in"]
                                      + net.transitions[ti].get("in_expr", []))}))


# Class holding a labelled family of element sets.
class Group:
    """A labelled family of selections, the domain of a quantified property.

    ``forall T: AG |EN(leaves_T)| <= 1`` quantifies over a group whose labels
    are tree pages and whose ``"leaves"`` role holds that page's leaf
    transitions. The label is what a violation is reported against.

    Attributes:
        name (str): The group's name, as properties refer to it.
        builder (callable): ``net -> OrderedDict[label, {role: indices}]``.
    """

    # Method to build a group from a resolver.
    def __init__(self, name: str, builder: Callable[[Any], "collections.OrderedDict"]):
        """Create the group.

        Args:
            name (str): Group name.
            builder (callable): Resolver, called once per net.
        """
        self.name = name
        self.builder = builder

    # Method to resolve the group against a net.
    def resolve(self, net) -> "collections.OrderedDict":
        """Build the family for a net.

        Args:
            net (ColouredNet): The flattened net.

        Returns:
            OrderedDict: ``label -> {role: tuple of indices}``, with every role
            normalised to a tuple.
        """
        out: "collections.OrderedDict[str, Dict[str, Any]]" = \
            collections.OrderedDict()
        for label, roles in self.builder(net).items():
            entry: Dict[str, Any] = {}
            for role, value in roles.items():
                if value is None:
                    entry[role] = ()
                elif isinstance(value, int):
                    entry[role] = (value,)
                else:
                    entry[role] = tuple(value)
            out[label] = entry
        return out

    # Method to render the group for debugging.
    def __repr__(self):
        """Return a short representation.

        Returns:
            str: ``<Group trees>``.
        """
        return f"<Group {self.name}>"
