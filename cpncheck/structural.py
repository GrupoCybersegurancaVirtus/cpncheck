"""Guard analysis: what holds for every input, not just the explored ones.

A state space answers questions about the marking it was started from. Some
questions are not about one input at all -- *can these two transitions ever be
enabled together?* -- and for guards that are conjunctions of bounds they can be
answered exactly, for the whole colour domain, without exploring anything.

A guard of the form ``#f0 x <= 3.0 andalso #f1 x > 1.5`` describes a box: one
interval per variable field, with the rest unbounded. Two such guards are
simultaneously satisfiable exactly when their boxes intersect, which is an
interval test per field. Guards outside that shape are reported as unparsed
rather than guessed at -- a wrong "disjoint" would be the one answer that
matters.

Strictness is tracked, so ``x >= 3`` and ``x <= 3`` are correctly found to
overlap at the single point 3, while ``x > 3`` and ``x <= 3`` do not.
"""

import collections
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "Interval",
    "guard_box",
    "boxes_intersect",
    "overlapping_guards",
]

#: One field's admissible range: ``low`` to ``high``, each open or closed.
Interval = collections.namedtuple("Interval",
                                  "low low_open high high_open")

#: The unconstrained interval.
WHOLE = Interval(float("-inf"), True, float("inf"), True)

# One conjunct of a guard: an optional record field, a variable, a comparison
# and a number -- in either order, so both ``#f0 x <= 3.0`` and ``3.0 < x`` are
# understood.
_NUM = r"\(?\s*(~?\d+(?:\.\d*)?(?:[eE]~?[-+]?\d+)?)\s*\)?"
_VAR = r"(?:#(\w+)\s+)?([A-Za-z_]\w*)"
_OP = r"(<=|<|>=|>)"
_FORWARD = re.compile(rf"{_VAR}\s*{_OP}\s*{_NUM}")
_BACKWARD = re.compile(rf"{_NUM}\s*{_OP}\s*{_VAR}")

#: Comparisons in the mirrored form, so ``3 < x`` becomes ``x > 3``.
_FLIP = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}


# Function to read an SML numeric literal.
def _number(text: str) -> float:
    """Parse a number written the way CPN ML writes it.

    Args:
        text (str): The literal, possibly with SML's ``~`` negation.

    Returns:
        float: The value.
    """
    return float(text.replace("~", "-"))


# Function to narrow an interval with one comparison.
def _narrow(current: Interval, op: str, value: float) -> Interval:
    """Intersect an interval with a half-line.

    Args:
        current (Interval): The interval so far.
        op (str): ``<``, ``<=``, ``>`` or ``>=``.
        value (float): The bound.

    Returns:
        Interval: The narrowed interval.
    """
    low, low_open, high, high_open = current
    if op in ("<", "<="):
        strict = op == "<"
        if value < high or (value == high and strict):
            high, high_open = value, strict
    else:
        strict = op == ">"
        if value > low or (value == low and strict):
            low, low_open = value, strict
    return Interval(low, low_open, high, high_open)


# Function to read a conjunctive guard back as a box.
def guard_box(guard: Optional[str]) -> Optional[Dict[Any, Interval]]:
    """Parse a guard that is a conjunction of bounds into per-field intervals.

    Args:
        guard (str, optional): The guard text, as CPN Tools stores it.

    Returns:
        dict|None: ``{(variable, field): Interval}`` for a conjunction of
        bounds, ``{}`` for a guard that is always true, and None when the guard
        is not of that shape -- a disjunction, a negation, a call. None means
        *unknown*, never *unsatisfiable*.
    """
    text = (guard or "").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1].strip()
    if not text or text.lower() == "true":
        return {}
    if re.search(r"\bnot\b|\borelse\b|\bfalse\b", text):
        return None
    box: Dict[Any, Interval] = {}
    for atom in (a.strip() for a in re.split(r"\bandalso\b|,", text)):
        if not atom:
            continue
        m = _FORWARD.fullmatch(atom)
        if m:
            field, var, op, raw = m.group(1), m.group(2), m.group(3), m.group(4)
        else:
            m = _BACKWARD.fullmatch(atom)
            if not m:
                return None
            raw, op, field, var = (m.group(1), _FLIP[m.group(2)],
                                   m.group(3), m.group(4))
        key = (var, field)
        box[key] = _narrow(box.get(key, WHOLE), op, _number(raw))
    return box


# Function to test whether two boxes have a point in common.
def boxes_intersect(a: Dict[Any, Interval], b: Dict[Any, Interval]) -> bool:
    """Whether two boxes share at least one point.

    A field constrained in only one box is unconstrained in the other, so it
    never makes them disjoint.

    Args:
        a (dict): First box.
        b (dict): Second box.

    Returns:
        bool: True when some point satisfies both.
    """
    for key in set(a) | set(b):
        ia, ib = a.get(key, WHOLE), b.get(key, WHOLE)
        if ia.low > ib.low:
            low, low_open = ia.low, ia.low_open
        elif ib.low > ia.low:
            low, low_open = ib.low, ib.low_open
        else:
            low, low_open = ia.low, ia.low_open or ib.low_open
        if ia.high < ib.high:
            high, high_open = ia.high, ia.high_open
        elif ib.high < ia.high:
            high, high_open = ib.high, ib.high_open
        else:
            high, high_open = ia.high, ia.high_open or ib.high_open
        if low > high:
            return False
        if low == high and (low_open or high_open):
            return False
    return True


# Function to find transitions of the same group whose guards can hold together.
def overlapping_guards(net, groups, ignore=None
                       ) -> Tuple[List[Tuple[str, str, str]], int]:
    """Pairs of transitions in a group that are satisfiable together.

    Args:
        net (ColouredNet): The flattened net.
        groups (dict): ``label -> transition indices``; pairs are only formed
            within a group, because that is what "two branches of the same
            choice" means.
        ignore (callable, optional): ``name -> bool``; a transition it accepts
            is skipped when its guard cannot be parsed, for catch-all branches
            whose guard is a negation by construction and is disjoint from the
            branches it was built from.

    Returns:
        tuple: ``(findings, unparsed)``, where a finding is
        ``(label, name, name)``.
    """
    trans = net.transitions
    findings: List[Tuple[str, str, str]] = []
    unparsed = 0
    for label, indices in groups.items():
        boxes: List[Tuple[str, Dict[Any, Interval]]] = []
        for ti in indices:
            name = trans[ti]["name"]
            box = guard_box(trans[ti].get("guard_text"))
            if box is None:
                if ignore is None or not ignore(name):
                    unparsed += 1
                continue
            boxes.append((name, box))
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                if boxes_intersect(boxes[i][1], boxes[j][1]):
                    findings.append((label, boxes[i][0], boxes[j][0]))
    return findings, unparsed
