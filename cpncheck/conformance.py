"""Conformance: does the net compute what it is supposed to compute?

The temporal properties say how the net behaves; none of them says that the
answer is *right*. That is a different question, and it is answered by running
the net on concrete inputs and comparing its result with a reference
implementation.

One maximal occurrence sequence is followed per input, rather than the whole
occurrence graph, which is cheap enough for a whole test set. That this single
run gives *the* result of the net rests on confluence, which the model-checking
step is what establishes -- so this check is only meaningful alongside it, never
instead of it.
"""

import time
from typing import Any, Callable, List, Optional, Sequence, Tuple

from .result import PropertyResult

__all__ = ["terminal_marking", "projection", "check_conformance"]


# Function to run the net to a marking where nothing is enabled.
def terminal_marking(net, token=None, input_places: Sequence[int] = (),
                     limit: int = 100_000) -> tuple:
    """Follow one maximal occurrence sequence and return where it stops.

    Args:
        net (ColouredNet): The flattened net.
        token: The value placed in ``input_places``; None keeps the net's own
            initial marking.
        input_places (sequence): Places the token is written into.
        limit (int): Maximum number of occurrences.

    Returns:
        tuple: The marking the run stopped in.
    """
    initial = (net.initial if token is None
               else net.initial_marking(token, places=input_places))
    return net.run(initial, limit=limit)


# Function to read the tokens of the output places out of a marking.
def projection(marking: tuple, places: Sequence[int]) -> tuple:
    """The tokens the given places hold, in place order.

    Args:
        marking (tuple): A marking.
        places (sequence): Place indices.

    Returns:
        tuple: The tokens.
    """
    return tuple(tok for p in places for tok in marking[p])


# Function to compare the net's result with a reference on a set of inputs.
def check_conformance(net, inputs: Sequence[Any], reference: Callable,
                      input_places: Sequence[int],
                      output_places: Sequence[int], pid: str = "PC",
                      spec=None, decode: Optional[Callable] = None,
                      limit: int = 100_000) -> PropertyResult:
    """Run the net on every input and compare the outcome with a reference.

    Args:
        net (ColouredNet): The flattened net.
        inputs (sequence): Input tokens, already in the net's own shape.
        reference (callable): ``inputs -> expected outputs``, one per input.
            It is called once with the whole batch, so a vectorised reference
            stays vectorised.
        input_places (sequence): Places the input token is written into.
        output_places (sequence): Places holding the result.
        pid (str): Property identifier for the verdict.
        spec (Property, optional): Descriptor for the verdict.
        decode (callable, optional): ``tokens -> value``, applied to the
            projection of the terminal marking. The default takes the single
            token, or None when there is not exactly one.
        limit (int): Maximum occurrences per run.

    Returns:
        PropertyResult: The verdict; a disagreement names the first input that
        produced one.
    """
    t0 = time.perf_counter()
    take_one = decode or (lambda toks: toks[0] if len(toks) == 1 else None)
    try:
        got = [take_one(projection(
                   terminal_marking(net, x, input_places, limit),
                   output_places))
               for x in inputs]
        expected = list(reference(inputs))
    except Exception as exc:
        return PropertyResult(pid, None, f"not evaluated: {exc}",
                              time.perf_counter() - t0, spec=spec)
    if len(expected) != len(got):
        return PropertyResult(pid, None, f"the reference returned "
                              f"{len(expected)} values for {len(got)} inputs",
                              time.perf_counter() - t0, spec=spec)
    bad = [(x, g, e) for x, g, e in zip(inputs, got, expected) if g != e]
    if bad:
        x, g, e = bad[0]
        return PropertyResult(
            pid, False,
            f"{len(bad)}/{len(got)} input(s) disagree, first: "
            f"input={_short(x)} net={g} expected={e}",
            time.perf_counter() - t0, spec=spec)
    return PropertyResult(pid, True, f"{len(got)}/{len(got)} inputs agree",
                          time.perf_counter() - t0, spec=spec)


# Function to render an input compactly for a counterexample.
def _short(value, width: int = 60) -> str:
    """A one-line form of an input, truncated.

    Args:
        value: The input token.
        width (int): Maximum length.

    Returns:
        str: The rendering.
    """
    if isinstance(value, tuple):
        text = "(" + ", ".join(f"{v:g}" if isinstance(v, float) else repr(v)
                               for v in value) + ")"
    else:
        text = repr(value)
    return text if len(text) <= width else text[:width - 3] + "...)"
