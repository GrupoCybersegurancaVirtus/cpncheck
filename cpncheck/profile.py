"""What a caller supplies so that the checker can verify *their* nets.

A :class:`Profile` answers the questions the generic layer cannot: which places
and transitions play which role, what the label domain is, which properties
apply, and how an input is written into the initial marking. Everything the
checker knows about a particular *kind* of net lives in a profile; the checker
itself knows only markings, arcs and formulas.

A profile is selected automatically by :func:`detect`, which asks each
registered profile whether it recognises the net, most specific first. Callers
with their own nets register their own profile and pass it explicitly, or let
detection find it.
"""

import collections
from typing import Any, Dict, List, Optional, Sequence, Tuple

__all__ = ["Profile", "register", "profiles", "detect"]

#: Registered profiles, in registration order.
_REGISTRY: List["Profile"] = []


# Class describing one family of nets to the checker.
class Profile:
    """The interface between the checker and a family of nets.

    A subclass overrides what it needs; every method has a neutral default, so
    a profile that only declares groups and formulas is already usable.

    Attributes:
        name (str): Short identifier, reported as the model family.
        priority (int): Higher profiles are offered the net first.
    """

    name = "generic"
    priority = 0
    #: Descriptors of the properties this profile reports, in report order.
    catalog: "collections.OrderedDict" = collections.OrderedDict()

    # Method to decide whether this profile recognises a net.
    def matches(self, net) -> bool:
        """Whether the profile applies to a net.

        Args:
            net (ColouredNet): The flattened net.

        Returns:
            bool: True when the profile recognises it.
        """
        return False

    # Method to name the net's family for the report.
    def family(self, net) -> str:
        """The family name shown in reports.

        Args:
            net (ColouredNet): The flattened net.

        Returns:
            str: The family name.
        """
        return self.name

    # Method to resolve every group the formulas quantify over.
    def resolve_groups(self, net) -> Dict[str, "collections.OrderedDict"]:
        """Build the quantification domains for a net.

        Args:
            net (ColouredNet): The flattened net.

        Returns:
            dict: ``group name -> OrderedDict[label, {role: indices}]``.
        """
        return {}

    # Method to determine the domain of the output tokens.
    def label_domain(self, net, declared: Optional[Sequence[int]]
                     ) -> Tuple[Optional[List[int]], str]:
        """Choose the token domain a "valid output" property checks against.

        Args:
            net (ColouredNet): The flattened net.
            declared (sequence, optional): A domain the caller declared.

        Returns:
            tuple: ``(domain or None, where it came from)``.
        """
        if declared is not None:
            try:
                return sorted({int(c) for c in declared}), "declared"
            except (TypeError, ValueError):
                pass
        return None, "undeclared"

    # Method to build the temporal properties that apply to a net.
    def ctl_formulas(self, net, groups, labels
                     ) -> "collections.OrderedDict[str, Any]":
        """The formulas to evaluate, keyed by property id.

        Only properties the net actually supports should appear: a profile
        that finds no aggregation group simply omits the aggregation
        properties, and the checker reports them as not applicable rather than
        as skipped.

        Args:
            net (ColouredNet): The flattened net.
            groups (dict): The resolved groups.
            labels (list, optional): The token domain, when known.

        Returns:
            OrderedDict: ``property id -> Formula``.
        """
        return collections.OrderedDict()

    # Method to name the properties answered by SCC analysis.
    def scc_properties(self, net, groups) -> "collections.OrderedDict[str, str]":
        """Properties answered from the SCC decomposition.

        Args:
            net (ColouredNet): The flattened net.
            groups (dict): The resolved groups.

        Returns:
            OrderedDict: ``property id -> kind``, where kind is ``"home"``.
        """
        return collections.OrderedDict()

    # Method to run the checks that do not use the occurrence graph.
    def static_checks(self, checker) -> "collections.OrderedDict[str, Any]":
        """Verdicts that hold for every input, not just the ones explored.

        Args:
            checker (CPNModelChecker): The checker, for access to the net.

        Returns:
            OrderedDict: ``property id -> PropertyResult``.
        """
        return collections.OrderedDict()

    # Method to compare the net with a reference implementation.
    def conformance(self, checker, reference, samples, use_final: bool):
        """Conformance of the net with a reference function on some inputs.

        Args:
            checker (CPNModelChecker): The checker.
            reference: Whatever the profile accepts as a reference.
            samples (list): The inputs.
            use_final (bool): Profile-specific flag passed through by the caller.

        Returns:
            PropertyResult|None: The verdict, or None when not supported.
        """
        return None

    # Method to list the mutation operators that suit this family of nets.
    def mutation_operators(self) -> Sequence:
        """Operators deriving, from a correct net, one that must fail.

        Returns:
            sequence: :class:`~cpncheck.mutation.Mutant` operators.
        """
        return ()

    # Method to analyse a net before its mutants are derived.
    def analyse_for_mutation(self, path: str) -> Optional[Dict[str, Any]]:
        """Whatever the operators need to know about a net before editing it.

        The driver passes the result to every operator untouched, so its shape
        is entirely up to the profile. Two conventional keys are read by the
        driver itself: ``"labels"``, reported as the mutant's output domain.

        Args:
            path (str): The correct ``.cpn``.

        Returns:
            dict|None: The analysis.
        """
        return None

    # Method to normalise an input into the token the net expects.
    def as_input_token(self, net, x, feature_names=None):
        """Convert a caller's input into the token of the input place.

        Args:
            net (ColouredNet): The flattened net.
            x: The input, in whatever shape the caller uses.
            feature_names (list, optional): Ordered field names.

        Returns:
            The token value.
        """
        return x

    # Method to name the places holding the input token.
    def input_places(self, net) -> Tuple[int, ...]:
        """Places whose marking is replaced when another input is checked.

        Args:
            net (ColouredNet): The flattened net.

        Returns:
            tuple: Place indices.
        """
        return ()

    # Method to render the profile for debugging.
    def __repr__(self):
        """Return a short representation.

        Returns:
            str: ``<Profile ml_trees>``.
        """
        return f"<Profile {self.name}>"


# Function to add a profile to the registry.
def register(profile: Profile) -> Profile:
    """Make a profile available to :func:`detect`.

    Args:
        profile (Profile): The profile instance.

    Returns:
        Profile: The profile, so this can be used as a decorator.
    """
    _REGISTRY.append(profile)
    return profile


# Function to list the registered profiles.
def profiles() -> List[Profile]:
    """Every registered profile, most specific first.

    Returns:
        list: The profiles.
    """
    return sorted(_REGISTRY, key=lambda p: -p.priority)


# Function to choose the profile that recognises a net.
def detect(net) -> Optional[Profile]:
    """The first registered profile that recognises the net.

    Args:
        net (ColouredNet): The flattened net.

    Returns:
        Profile|None: The profile, or None when nothing recognises it.
    """
    for profile in profiles():
        try:
            if profile.matches(net):
                return profile
        except Exception:                      # a profile must never break others
            continue
    return None
