"""CPNCheck's CPN ML library computes what CPN Tools computes.

Every case of ``tests/data/mllib_cases.txt`` was evaluated by CPN Tools 4.0.1
in the environment of ``tests/nets/mllib.cpn``, and its answer is stored in
``tests/data/mllib_expected.json`` (``make_mllib_fixture.py`` regenerates it).
Here CPNCheck evaluates the same expression in the same environment and must
give the same value -- or, where CPN Tools raised an exception, refuse with
an :class:`~cpncheck.cpnml.MLError` too, never return something.
"""

import json
import os

import pytest

from cpncheck.coloured import ColouredNet
from cpncheck.cpnml import MLError, compile_expression, parse_expression
from cpncheck.net import CPNNet
from cpncheck.smlvalue import normalise, parse_repl, same

HERE = os.path.dirname(os.path.abspath(__file__))
NET = os.path.join(HERE, "nets", "mllib.cpn")
with open(os.path.join(HERE, "data", "mllib_expected.json"), encoding="utf-8") as _fh:
    FIXTURE = json.load(_fh)
CASES = FIXTURE["cases"]


@pytest.fixture(scope="module")
def net():
    return ColouredNet(CPNNet(NET))


# Function to evaluate one case the way an inscription is evaluated.
def evaluate(net, expr: str):
    """CPNCheck's value of an expression in the net's environment.

    Args:
        net (ColouredNet): The net, for its declarations.
        expr (str): The expression.

    Returns:
        The value.
    """
    tree = parse_expression(f"({expr})", net.symbols)
    return compile_expression(tree, net.env, net.fields)({})


@pytest.mark.parametrize("case", CASES, ids=[c["expr"] for c in CASES])
def test_the_same_value_as_cpntools(net, case):
    kind, expected, typ = parse_repl(case["cpntools"])
    assert kind != "error", f"CPN Tools does not compile it: {case['cpntools']}"
    if kind == "exception":
        with pytest.raises(MLError):
            evaluate(net, case["expr"])
        return
    got = normalise(evaluate(net, case["expr"]))
    assert same(got, expected, bag=case["mode"] == "bag"), \
        f"CPNCheck {got!r}, CPN Tools {expected!r} : {typ}"


def test_the_fixture_was_recorded_by_cpntools():
    assert "Simulator/CPN v4.0.1" in (FIXTURE.get("banner") or "")
    assert len(CASES) >= 200
