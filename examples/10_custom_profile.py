"""Teaching CPNCheck about your nets: profiles, Python formulas and mutants.

Text properties (03_user_properties.py) cover most needs. A *profile* goes
further: it is how a family of nets -- yours -- gets its own catalog of
properties, quantified over the net's parts, with settings (``options``),
inputs to check the net with, a conformance test against a reference
implementation, and mutation operators that prove each property can fail.

Part A writes a profile for dining philosophers; part B one for a net that
computes a function (an invoice from an order) and is tested against Python.

A profile shipped in a package is found automatically through an entry
point (``pyproject.toml``)::

    [project.entry-points."cpncheck.profiles"]
    dining = "my_package.profiles:PROFILE"

    python examples/10_custom_profile.py
"""

import collections
import os
import tempfile

from _common import net, section

from cpncheck import CPNModelChecker
from cpncheck.cpnml import EnumValue, IndexValue
from cpncheck.formula import AG, EF, And, Dead, ForEach, Holds, Not
from cpncheck.mutation import Mutant, make_mutants
from cpncheck.profile import Profile, register
from cpncheck.properties import Property
from cpncheck.result import PropertyResult
from cpncheck.selectors import Explicit


# ===========================================================================
# Part A: a profile for dining philosophers
# ===========================================================================

# Function to edit a mutant: philosophers use only the left chopstick.
def _left_only(doc, info):
    """Make philosophers take, and put back, just the left chopstick.

    Both arcs change: taking one and returning two would create chopsticks,
    and the occurrence graph would be infinite (every verdict skipped).

    Args:
        doc (CPNDocument): The net being mutated.
        info (dict): The profile's analysis (unused).

    Returns:
        bool: True when the edit was made.
    """
    edited = 0
    for trans, orientation in (("Take Chopsticks", "PtoT"),
                               ("Put Down Chopsticks", "TtoP")):
        for arc in doc.arcs("Top", trans, orientation):
            if doc.place_of("Top", arc) == "Unused Chopsticks":
                doc.set_inscription(arc, "1`Left(p)")
                edited += 1
    return edited == 2


# Function to edit a mutant: philosophers who eat never come back.
def _never_return(doc, info):
    """Remove the arc from ``Put Down Chopsticks`` back to ``Think``.

    Args:
        doc (CPNDocument): The net being mutated.
        info (dict): The profile's analysis (unused).

    Returns:
        bool: True when the edit was made.
    """
    for arc in doc.arcs("Top", "Put Down Chopsticks", "TtoP"):
        if doc.place_of("Top", arc) == "Think":
            doc.remove_arc("Top", arc)
            return True
    return False


# Class describing dining-philosopher nets to the checker.
class DiningProfile(Profile):
    """Properties every dining-philosophers net should have."""

    name = "dining philosophers"
    priority = 10           # offered the net before the default profile (-100)
    catalog = collections.OrderedDict(
        (p.id, p) for p in [
            Property("DP1", "Neighbours never eat at once",
                     "forall i: AG !(Eat(ph i) & Eat(ph i+1))", "desired",
                     description="No two neighbours hold the same chopstick."),
            Property("DP2", "No deadlock", "AG !dead", "desired"),
            Property("DP3", "Watched one can always eat",
                     "AG EF Eat(ph w)", "desired",
                     description="Needs the option watch=<w>."),
            Property("DP4", "Home marking", "one terminal SCC", "desired",
                     method="scc"),
        ])

    # Method to recognise the family by its places.
    def matches(self, net) -> bool:
        """A net with places Think, Eat and Unused Chopsticks.

        Args:
            net (ColouredNet): The flattened net.

        Returns:
            bool: True for dining philosophers.
        """
        names = {p["name"] for p in net.places}
        return {"Think", "Eat", "Unused Chopsticks"} <= names

    # Method to build the groups the formulas quantify over.
    def resolve_groups(self, net):
        """One member per pair of neighbours.

        Args:
            net (ColouredNet): The flattened net.

        Returns:
            dict: ``{"neighbours": {label: {"eat": (place,), "pair": (i, j)}}}``.
        """
        eat = next(i for i, p in enumerate(net.places) if p["name"] == "Eat")
        n = len(net.initial[eat - 1]) or 5            # philosophers in Think
        pairs = collections.OrderedDict()
        for i in range(1, n + 1):
            j = 1 if i == n else i + 1
            pairs[f"ph({i})/ph({j})"] = {"eat": (eat,), "pair": (i, j)}
        return {"neighbours": pairs}

    # Method to build the properties as Python formulas.
    def ctl_formulas(self, net, groups, options):
        """DP1-DP3 as formula objects.

        Args:
            net (ColouredNet): The flattened net.
            groups (dict): From :meth:`resolve_groups`.
            options (dict): ``watch`` names the philosopher of DP3.

        Returns:
            OrderedDict: Property id -> formula.
        """
        def eats(eat, i):
            return Holds(Explicit(eat, "place", "Eat"), IndexValue("ph", i),
                         f"ph({i})", note=f"ph({i}) eats")

        def apart(roles, label):
            i, j = roles["pair"]
            return AG(Not(And(eats(roles["eat"], i), eats(roles["eat"], j))))

        out = collections.OrderedDict()
        out["DP1"] = ForEach("neighbours", apart)
        out["DP2"] = AG(Not(Dead()))
        if "watch" in options:
            eat = next(iter(groups["neighbours"].values()))["eat"]
            out["DP3"] = AG(EF(eats(eat, int(options["watch"]))))
        return out

    # Method to name the properties that cannot be decided without a setting.
    def unavailable(self, net, groups, options):
        """DP3 needs to know whom to watch.

        Args:
            net (ColouredNet): The flattened net.
            groups (dict): The groups.
            options (dict): The settings.

        Returns:
            dict: Property id -> reason.
        """
        if "watch" not in options:
            return {"DP3": "no philosopher to watch: pass -O watch=<n>"}
        return {}

    # Method to name the properties answered by SCC analysis.
    def scc_properties(self, net, groups):
        """DP4 is the home-marking test.

        Args:
            net (ColouredNet): The flattened net.
            groups (dict): The groups.

        Returns:
            OrderedDict: Property id -> ``"home"``.
        """
        return collections.OrderedDict([("DP4", "home")])

    # Method to list the mutation operators of the family.
    def mutation_operators(self):
        """Edits that must make a property fail.

        Returns:
            list: The operators.
        """
        always = lambda info: True                       # noqa: E731
        return [
            Mutant("left_only", ("DP1",), always,
                   "use only the left chopstick", _left_only),
            Mutant("never_return", ("DP2",), always,
                   "philosophers who eat never think again", _never_return),
        ]


DINING = register(DiningProfile())

# ---------------------------------------------------------------------------
section("A1. The profile is detected from the net")
# ---------------------------------------------------------------------------
checker = CPNModelChecker(net("dining"))
print("profile:", checker.profile.name)
print(checker.check().report())

# ---------------------------------------------------------------------------
section("A2. Options: settings for the profile (-O key=value)")
# ---------------------------------------------------------------------------
result = CPNModelChecker(net("dining"), options={"watch": 3}).check()
print("DP3:", result.properties["DP3"].status, "-", result.properties["DP3"].spec.name)
# From the command line: cpncheck check dining.cpn -O watch=3

# ---------------------------------------------------------------------------
section("A3. Mutants: every property must be able to fail")
# ---------------------------------------------------------------------------
# A property that cannot fail checks nothing. Each operator edits the net so
# that its target properties must fail; checking the mutants shows they do.
out_dir = os.path.join(tempfile.mkdtemp(), "mutants")
for m in make_mutants(net("dining"), out_dir):
    result = CPNModelChecker(m["path"], profile=DINING).check()
    failed = {r.id for r in result.failures}
    statuses = {t: result.properties[t].status for t in m["targets"]}
    print(f"  {m['name']:<13} {m['description']:<40} {statuses}: "
          f"{'caught' if set(m['targets']) <= failed else 'MISSED'}")
# From the command line: cpncheck mutants dining.cpn out_dir/

# The deadlocking variant has a different structure, but the same places:
# the profile recognises it too and finds the deadlock.
result = CPNModelChecker(net("dining_deadlock")).check()
print("dining_deadlock: failed", [r.id for r in result.failures])


# ===========================================================================
# Part B: a net that computes a function, tested against Python
# ===========================================================================

# Function to compute the fee of an order, as the net should.
def reference_fee(order):
    """The intended invoice: rush orders cost double, plus a fee of 1.

    Args:
        order (tuple): ``(kind, quantity)``.

    Returns:
        int: The fee.
    """
    kind, qty = order
    return (qty * 2 if kind == "rush" else qty) + 1


# Class describing order-processing nets to the checker.
class OrderProfile(Profile):
    """One order in, one invoice out."""

    name = "orders"
    priority = 10
    catalog = collections.OrderedDict(
        (p.id, p) for p in [
            Property("O1", "Every order is invoiced", "AF tokens(Invoices) = 1",
                     "desired"),
            Property("FEE", "Fee matches the reference",
                     "net(x) = reference(x)", "desired", method="testing"),
        ])

    # Method to recognise the family.
    def matches(self, net) -> bool:
        """A net with places Orders and Invoices.

        Args:
            net (ColouredNet): The flattened net.

        Returns:
            bool: True for order nets.
        """
        return {"Orders", "Invoices"} <= {p["name"] for p in net.places}

    # Method to name the input place.
    def input_places(self, net):
        """The input token goes into Orders.

        Args:
            net (ColouredNet): The flattened net.

        Returns:
            tuple: Place indices.
        """
        return tuple(i for i, p in enumerate(net.places) if p["name"] == "Orders")

    # Method to turn an input into the token of the input place.
    def as_input_token(self, net, x, options=None):
        """``("rush", 3)`` -> the ORDER token ``(rush, 3)``.

        Args:
            net (ColouredNet): The flattened net.
            x (tuple): Kind and quantity.
            options (dict, optional): Unused.

        Returns:
            tuple: The token.
        """
        return (EnumValue(x[0]), int(x[1]))

    # Method to build the temporal properties.
    def ctl_formulas(self, net, groups, options):
        """O1: the run always ends with one invoice.

        Args:
            net (ColouredNet): The flattened net.
            groups (dict): Unused.
            options (dict): Unused.

        Returns:
            OrderedDict: Property id -> formula.
        """
        from cpncheck.formula import AF, TokenCount
        invoices = Explicit(self._place(net, "Invoices"), "place", "Invoices")
        return collections.OrderedDict(
            [("O1", AF(TokenCount(invoices, "=", 1)))])

    # Method to compare the net with the reference on inputs.
    def conformance(self, checker, reference, samples, options):
        """Run the net on each input and compare the invoice.

        Args:
            checker (CPNModelChecker): The checker.
            reference (callable): The intended function.
            samples (list): Input tokens.
            options (dict): Unused.

        Returns:
            PropertyResult: FEE.
        """
        cn = checker.cnet
        out = self._place(cn, "Invoices")
        wrong = []
        for token in samples:
            m0 = cn.initial_marking(token, places=self.input_places(cn))
            got = cn.run(m0)[out[0]]
            want = reference((str(token[0]), token[1]))
            if got != (want,):
                wrong.append(f"{token}: net {got}, reference {want}")
        return PropertyResult("FEE", not wrong,
                              "; ".join(wrong[:3]) or f"{len(samples)} inputs agree",
                              spec=self.catalog["FEE"])

    # Method to find a place by name.
    @staticmethod
    def _place(net, name):
        """Indices of the places with a name.

        Args:
            net (ColouredNet): The flattened net.
            name (str): The name.

        Returns:
            tuple: Indices.
        """
        return tuple(i for i, p in enumerate(net.places) if p["name"] == name)


ORDERS = register(OrderProfile())

# ---------------------------------------------------------------------------
section("B1. Inputs: one occurrence graph per input")
# ---------------------------------------------------------------------------
inputs = [("rush", 3), ("normal", 5), ("normal", 15)]
result = CPNModelChecker(net("ml_features")).check(
    samples=inputs, reference=reference_fee,
    test_samples=[(k, q) for k in ("rush", "normal") for q in range(0, 21)])
print(result.report())

# ---------------------------------------------------------------------------
section("B2. A reference that disagrees is reported")
# ---------------------------------------------------------------------------
result = CPNModelChecker(net("ml_features")).check(
    samples=inputs[:1], reference=lambda order: order[1] + 1,
    test_samples=inputs)
print("FEE:", result.properties["FEE"].status, "-", result.properties["FEE"].detail)
