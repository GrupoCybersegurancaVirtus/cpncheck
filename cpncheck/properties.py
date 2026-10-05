"""Property descriptors: what is checked, how, and what a verdict guarantees.

A :class:`Property` is a descriptor, not an evaluator. It carries the
identifier a verdict is reported under, the formula in readable form, the
technique that answers it and a sentence saying what holding it does and does
not establish -- which is the part a reader of the report needs most.

The descriptors of a family of nets are gathered into a catalog and handed to
the checker by a :class:`~cpncheck.profile.Profile`; the catalog of the
tree-ensemble nets is :data:`cpncheck.profiles.ml_trees.TREE_CATALOG`. Nothing
here is specific to any family.
"""

import collections

__all__ = ["METHODS", "Property", "catalog"]

#: Human-readable names of the verification techniques.
METHODS = collections.OrderedDict((
    ("ctl", "CTL model checking on the occurrence graph"),
    ("scc", "SCC analysis of the occurrence graph"),
    ("structural", "Structural guard analysis (every input)"),
    ("testing", "Conformance testing against a reference implementation"),
))


# Class describing one verifiable property of a net.
class Property:
    """One entry of a property catalog.

    Attributes:
        id (str): Identifier used by the article (``A1``, ``B2``, ``C3a``, ...).
        name (str): Short name.
        ctl (str): The formula the check implements (ASCII).
        kind (str): ``"desired"``, ``"undesired"``, ``"structural"`` or
            ``"report"`` -- a fact about the net, shown as YES/NO, which never
            makes a check fail.
        families (tuple): Free-form note on which nets it suits.
        description (str): What the property guarantees -- and only that.
        method (str): One of :data:`METHODS`.
    """

    __slots__ = ("id", "name", "ctl", "kind", "families", "description", "method")

    # Method to build a catalog entry.
    def __init__(self, id, name, ctl, kind, families=(), description="",
                 method="ctl"):
        """Create a property descriptor.

        Args:
            id (str): Property identifier.
            name (str): Short name.
            ctl (str): Formula.
            kind (str): Category.
            families (tuple): Free-form note on which nets it suits; the
                checker does not read it, since a profile simply omits a
                property that does not apply.
            description (str): Guarantee.
            method (str): Verification technique.
        """
        self.id = id
        self.name = name
        self.ctl = ctl
        self.kind = kind
        self.families = families
        self.description = description
        self.method = method

    # Method to render the descriptor for debugging.
    def __repr__(self):
        """Return a short representation.

        Returns:
            str: ``<Property A1 Termination>``.
        """
        return f"<Property {self.id} {self.name}>"


# Function to gather property descriptors into a catalog.
def catalog(*properties: Property) -> "collections.OrderedDict[str, Property]":
    """Build a catalog, which fixes the order properties are reported in.

    Args:
        *properties (Property): The descriptors.

    Returns:
        OrderedDict: ``id -> Property``.

    Raises:
        ValueError: When two descriptors share an identifier.
    """
    out: "collections.OrderedDict[str, Property]" = collections.OrderedDict()
    for prop in properties:
        if prop.id in out:
            raise ValueError(f"duplicate property id {prop.id!r}")
        out[prop.id] = prop
    return out
