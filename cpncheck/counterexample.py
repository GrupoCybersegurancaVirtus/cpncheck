"""What a violated property hands back.

A verdict of "false" is only half an answer. The other half is the evidence:
which occurrence sequence, from which initial marking, with which bindings, and
what is wrong with the marking it ends in. This module is that evidence, as an
object rather than a sentence.

Shapes
------
``finite``
    A safety property failed: there is a reachable marking that violates it,
    and the prefix is the shortest occurrence sequence to it.
``lasso``
    A liveness property failed on an infinite run: a prefix into a cycle that
    the net can repeat forever without ever reaching the goal. Without the
    cycle this case has no finite witness at all, which is why it is a shape of
    its own.
``witness``
    Evidence for a property whose failure is not a single sequence -- two
    terminal components with no common successor, say -- rendered as the
    markings that show it.
``structural``
    A fault of the net as written, independent of any run: two guards that can
    hold at once. It carries the point of the input space where they do, which
    turns a static finding into an input the net can be run on.
``conformance``
    The net's result differs from a reference implementation on a concrete
    input.

Certificate
-----------
:meth:`Counterexample.replay` re-fires the sequence from the initial marking
and checks it ends where the counterexample says it does. It uses the net's
firing rule, not the search that produced the trace, so it is an independent
check on the checker: a bug in the fixpoints cannot forge a sequence that
replays.
"""

from typing import Any, Dict, List, Optional, Sequence

__all__ = ["Step", "Counterexample"]

#: How many occurrences are printed before a trace is elided.
DISPLAY_LIMIT = 12


# Class holding one occurrence of a binding element.
class Step:
    """One step of an occurrence sequence.

    Attributes:
        transition (int): Index of the transition that occurred.
        name (str): Its name.
        page (str): The page it is on.
        binding (dict): The values its variables took, which is what CPN Tools
            shows when a binding element is inspected.
        target (int): The node reached, for cross-referencing the state space.
    """

    __slots__ = ("transition", "name", "page", "binding", "target")

    # Method to build one step.
    def __init__(self, transition, name, page, binding=None, target=None):
        """Create the step.

        Args:
            transition (int): Transition index.
            name (str): Transition name.
            page (str): Page name.
            binding (dict, optional): Variable bindings.
            target (int, optional): Node reached.
        """
        self.transition = transition
        self.name = name
        self.page = page
        self.binding = dict(binding or {})
        self.target = target

    # Method to render the step with its binding.
    def detailed(self) -> str:
        """The step with its variable bindings spelled out.

        Returns:
            str: ``Feed_1<x = (2.0, 7.0)>``, or just the name when the
            transition binds nothing.
        """
        if not self.binding:
            return self.name
        inner = ", ".join(f"{k} = {_render(v)}"
                          for k, v in sorted(self.binding.items()))
        return f"{self.name}<{inner}>"

    # Method to render the step for debugging.
    def __repr__(self):
        """Return a short representation.

        Returns:
            str: ``<Step Feed_1>``.
        """
        return f"<Step {self.name}>"

    # Method to render the step as its transition name.
    def __str__(self):
        """Return the transition name.

        Returns:
            str: The name.
        """
        return self.name


# Class holding the evidence for one violated property.
class Counterexample:
    """Evidence that a property does not hold.

    Attributes:
        kind (str): ``finite``, ``lasso``, ``witness``, ``structural`` or
            ``conformance``.
        note (str): What is wrong, in words -- the part that does not depend on
            how the marking was reached.
        via (str): How the note joins the sequence when rendered.
        prefix (list): The occurrence sequence from the initial marking.
        cycle (list): The repeatable part, for a lasso; empty otherwise.
        input: The input the net was given, when it was given one. A property
            is checked per input, so which input produced the violation is part
            of the evidence.
        final (tuple): The marking the prefix ends in, for :meth:`replay`.
        data (dict): Anything the shape needs -- the overlapping pair and the
            point for ``structural``, the two results for ``conformance``.
    """

    __slots__ = ("kind", "note", "via", "prefix", "cycle", "input", "final",
                 "data")

    # Method to build a counterexample.
    def __init__(self, kind="finite", note="", via="after:", prefix=None,
                 cycle=None, input=None, final=None, data=None):
        """Create the evidence.

        Args:
            kind (str): The shape.
            note (str): What is wrong.
            via (str): Joins the note to the sequence when rendered.
            prefix (list, optional): Steps from the initial marking.
            cycle (list, optional): The repeatable steps.
            input (optional): The input the net was given.
            final (tuple, optional): The marking the prefix ends in.
            data (dict, optional): Shape-specific extras.
        """
        self.kind = kind
        self.note = note
        self.via = via
        self.prefix = list(prefix or [])
        self.cycle = list(cycle or [])
        self.input = input
        self.final = final
        self.data = dict(data or {})

    # Property giving the number of occurrences in the evidence.
    @property
    def length(self) -> int:
        """Total number of occurrences.

        Returns:
            int: Prefix plus cycle.
        """
        return len(self.prefix) + len(self.cycle)

    # Method to render the occurrence sequence.
    def sequence(self, limit: int = DISPLAY_LIMIT, bindings: bool = False) -> str:
        """The occurrence sequence, elided in the middle when long.

        Args:
            limit (int): Maximum number of steps shown.
            bindings (bool): Show each step's variable bindings.

        Returns:
            str: ``t1 -> t2 -> ...``, or a note that nothing had to occur.
        """
        text = _join(self.prefix, limit, bindings)
        if self.cycle:
            inner = _join(self.cycle, limit, bindings)
            return (f"{text} then forever [{inner}]" if self.prefix
                    else f"forever [{inner}]")
        return text

    # Method to re-fire the sequence and check it does what it says.
    def replay(self, net) -> bool:
        """Fire the sequence from the initial marking and check where it ends.

        This uses only the net's firing rule, so it is independent of the
        search that produced the trace: a counterexample that replays is one
        the checker did not invent.

        Args:
            net (ColouredNet): The net the counterexample came from.

        Returns:
            bool: True when the sequence is enabled throughout and ends in the
            recorded marking -- and, for a lasso, returns to where the cycle
            began. False when the evidence is not a sequence at all, or when
            there is no recorded marking to check against.
        """
        if self.kind not in ("finite", "lasso") or self.final is None:
            return False
        marking = net.initial if self.input is None else net.initial_marking(
            self.input, places=self.data.get("input_places"))
        for step in self.prefix:
            marking = _fire(net, marking, step)
            if marking is None:
                return False
        if marking != self.final:
            return False
        if not self.cycle:
            return True
        start = marking
        for step in self.cycle:
            marking = _fire(net, marking, step)
            if marking is None:
                return False
        return marking == start

    # Method to convert the evidence into a plain dictionary.
    def to_dict(self) -> Dict[str, Any]:
        """Serialise the counterexample, without eliding the sequence.

        Returns:
            dict: JSON-friendly representation.
        """
        def steps(items):
            return [{"transition": s.name, "page": s.page,
                     "binding": {k: _render(v) for k, v in s.binding.items()}}
                    for s in items]

        out: Dict[str, Any] = {
            "kind": self.kind, "note": self.note, "length": self.length,
            "prefix": steps(self.prefix), "cycle": steps(self.cycle),
            "text": str(self),
        }
        if self.input is not None:
            out["input"] = _render(self.input)
        if self.data:
            out["data"] = {k: _render(v) for k, v in self.data.items()
                           if k != "input_places"}
        return out

    # Method to render the evidence as one line.
    def __str__(self):
        """The counterexample as the report prints it.

        A property is checked once per input, so when several were given the
        trace says which one it belongs to; without that a reader cannot tell
        whether the violation needs a particular input or happens for all.

        Returns:
            str: The note, then the sequence when there is one.
        """
        if self.kind in ("structural", "conformance", "witness"):
            return self.note
        seq = self.sequence()
        body = f"{self.note} {self.via} {seq}" if self.note else seq
        if self.input is not None:
            return f"for input={_render(self.input)}: {body}"
        return body

    # Method to render the evidence for debugging.
    def __repr__(self):
        """Return a short representation.

        Returns:
            str: ``<Counterexample lasso, 7 steps>``.
        """
        return f"<Counterexample {self.kind}, {self.length} steps>"


# Function to fire one recorded step.
def _fire(net, marking, step: Step):
    """Fire a step's binding element, if it is enabled.

    Args:
        net (ColouredNet): The net.
        marking (tuple): The current marking.
        step (Step): The step to fire.

    Returns:
        tuple|None: The successor marking, or None when the step is not
        enabled with that binding.
    """
    for ti, _key, env in net.enabled(marking):
        if ti == step.transition and env == step.binding:
            return net.fire(marking, ti, env)
    return None


# Function to join steps into a readable sequence.
def _join(steps: Sequence[Step], limit: int, bindings: bool) -> str:
    """Render steps, eliding the middle when there are too many.

    Args:
        steps (sequence): The steps.
        limit (int): Maximum shown.
        bindings (bool): Show variable bindings.

    Returns:
        str: The sequence.
    """
    if not steps:
        return "(initial marking)"
    names = [s.detailed() if bindings else s.name for s in steps]
    if len(names) > limit:
        names = names[:3] + [f"... {len(names) - 6} more ..."] + names[-3:]
    return " -> ".join(names)


# Function to render a token value the way a report should show it.
def _render(value):
    """A readable form of a token value.

    Args:
        value: The value.

    Returns:
        The value, with tuples of floats shortened.
    """
    if isinstance(value, tuple):
        return "(" + ", ".join(f"{v:g}" if isinstance(v, float) else str(v)
                               for v in value) + ")"
    if isinstance(value, float):
        return f"{value:g}"
    return value
