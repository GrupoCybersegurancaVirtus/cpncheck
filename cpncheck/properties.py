"""The property catalog: what is checked, how, and of which nets.

A :class:`Property` is a descriptor, not an evaluator -- it says what the
formula is, which technique answers it and what a verdict guarantees. The
evaluators live in :mod:`cpncheck.checker`.

.. note::
   The catalog below is the pyruleanalyzer catalog (decision trees, random
   forests and gradient boosting) and its ``families`` field names ML model
   families. Turning this into a declarative catalog that any net can supply is
   the central refactor; see ``MIGRATION.md``.
"""

import collections

__all__ = ["METHODS", "Property", "PROPERTY_CATALOG", "AF_PROPERTIES"]

#: Human-readable names of the verification techniques.
METHODS = collections.OrderedDict((
    ("ctl", "CTL model checking on the occurrence graph"),
    ("scc", "SCC analysis of the occurrence graph"),
    ("structural", "Structural guard analysis (every input)"),
    ("testing", "Conformance testing against the classifier"),
))

_ALL = ("Decision Tree", "Random Forest", "Gradient Boosting Decision Trees")
_GBDT = ("Gradient Boosting Decision Trees",)
_RF = ("Random Forest",)


# Class describing one verifiable property of the generated nets.
class Property:
    """One entry of the property catalog.

    Attributes:
        id (str): Identifier used by the article (``A1``, ``B2``, ``C3a``, ...).
        name (str): Short name.
        ctl (str): The formula the check implements (ASCII).
        kind (str): ``"desired"``, ``"undesired"`` or ``"structural"``.
        families (tuple): Model families the property applies to.
        description (str): What the property guarantees -- and only that.
        method (str): One of :data:`METHODS`.
    """

    __slots__ = ("id", "name", "ctl", "kind", "families", "description", "method")

    # Method to build a catalog entry.
    def __init__(self, id, name, ctl, kind, families, description, method="ctl"):
        """Create a property descriptor.

        Args:
            id (str): Property identifier.
            name (str): Short name.
            ctl (str): Formula.
            kind (str): Category.
            families (tuple): Applicable families.
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


#: Every property the checker knows about, in report order.
PROPERTY_CATALOG: "collections.OrderedDict[str, Property]" = collections.OrderedDict()
for _p in (
    Property("A1", "Termination", "AF dead", "desired", _ALL,
             "Every maximal occurrence sequence is finite: no reachable cycle."),
    Property("A2", "No spurious deadlock", "!EF(dead & !pred)", "undesired", _ALL,
             "Every reachable dead marking holds a prediction."),
    Property("A3", "Inevitable decision", "AF pred", "desired", _ALL,
             "On every maximal occurrence sequence Prediction becomes marked."),
    Property("A4", "Prediction recoverability", "AG EF pred", "desired", _ALL,
             "From every reachable marking a marking with a prediction is "
             "reachable. This is not a home-marking property; see A8."),
    Property("A5", "Unique output", "AG |Prediction| <= 1", "undesired", _ALL,
             "Prediction never holds more than one token."),
    Property("A6", "Valid label", "AG Prediction subset L", "undesired", _ALL,
             "Every token ever deposited in Prediction belongs to the declared "
             "label domain L."),
    Property("A7", "Safeness", "AG forall p: |p| <= 1", "structural", _ALL,
             "Every place holds at most one token in every reachable marking."),
    Property("A8", "Home marking", "one terminal SCC", "desired", _ALL,
             "Some marking is reachable from every reachable marking.",
             method="scc"),
    Property("B1", "Leaf determinism", "forall T: AG |EN(leaves_T)| <= 1",
             "undesired", _ALL,
             "For the input in the initial marking, no reachable marking enables "
             "two leaf occurrences of the same tree."),
    Property("B2", "Inevitable leaf selection", "forall T: AF EN(leaves_T)",
             "desired", _ALL,
             "Every tree inevitably reaches a marking where one of its leaves is "
             "enabled."),
    Property("B3", "Single tree output", "forall T: AG |out_T| <= 1",
             "structural", _ALL,
             "The output place of every tree holds at most one token."),
    Property("B4", "Guard disjointness", "forall T, i!=j: box_i & box_j = {}",
             "undesired", _ALL,
             "No two leaf guards of the same tree are satisfiable together, for "
             "any input: the leaves partition the feature space.",
             method="structural"),
    Property("C1", "Stage precedence", "forall k,m: !E[!acc(k,m-1) U acc(k,m)]",
             "undesired", _GBDT,
             "In every class channel, stage m is never completed before stage "
             "m-1 has been."),
    Property("C2", "No premature score", "forall k: !E[!acc(k,M) U score(k)]",
             "undesired", _GBDT,
             "A channel's score appears only after its last stage completed."),
    Property("C3a", "Inevitable decision firing", "AF EN(decide)", "desired", _GBDT,
             "A Decide transition inevitably becomes enabled."),
    Property("C3b", "Decision determinism", "AG |EN(decide)| <= 1", "undesired",
             _GBDT,
             "No reachable marking enables two Decide occurrences."),
    Property("D1", "Complete vote", "AG(EN(vote) -> votes_all)", "undesired", _RF,
             "Vote is only enabled when every tree has voted."),
    Property("D2a", "Inevitable aggregation", "AF EN(vote)", "desired", _RF,
             "Vote inevitably becomes enabled."),
    Property("D2b", "Single aggregation", "AG |Prediction| <= 1", "structural", _RF,
             "The aggregation deposits at most one class (same formula as A5)."),
    Property("PC", "Prediction consistency", "net(x) = model(x)", "desired", _ALL,
             "On the tested inputs, the class the net computes equals the "
             "classifier's.", method="testing"),
):
    PROPERTY_CATALOG[_p.id] = _p
del _p

#: The AF-type properties, for which ASK-CTL's EV reading is also reported.
AF_PROPERTIES = ("A3", "B2", "C3a", "D2a")
