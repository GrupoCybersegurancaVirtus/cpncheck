"""ASK-CTL query files as input (``cpncheck.askctl_input``).

The expected verdicts below are CPN Tools 4.0.1's own: each file was
evaluated with ASKCTL.sml after *Enter State Space* on the same net. They
include the places where ASK-CTL is not textbook CTL (``EV`` vacuous at a
dead marking, the SCC fast paths that are not, ``ALONG`` at a dead end).
With ``CPNCHECK_CPNTOOLS=1`` the files are also run through CPN Tools again.
"""

import os
import subprocess
import sys

import pytest

from cpncheck import CPNModelChecker, check_cpn
from cpncheck.askctl_input import AskCtlError, AskCtlScript

HERE = os.path.dirname(os.path.abspath(__file__))
NETS = os.path.join(HERE, "..", "examples", "nets")
QUERIES = os.path.join(HERE, "data", "askctl")

#: Verdicts CPN Tools gave on each file.
EXPECTED = {
    "dining": {"CanEat": True, "AlwaysAgain": True, "NeverTwo": False,
               "Q1": True, "Q2": True, "Q3": True, "Q4": False, "Q5": False,
               "Q6": False},
    "workers": dict(zip(
        [f"W{i}" for i in range(1, 21)],
        [True, True, False, True, False, True, False, True, True, False,
         True, True, True, False, True, True, True, False, False, True])),
    "dining_deadlock": dict(zip(
        [f"D{i}" for i in range(1, 21)],
        [True, True, False, True, True, True, False, False, False, False,
         True, False, False, False, True, False, True, False, False, True])),
}


# Function to give the paths of one case.
def _paths(name):
    """The net and the query file of a case.

    Args:
        name (str): The case.

    Returns:
        tuple: ``(net path, query path)``.
    """
    return (os.path.join(NETS, f"{name}.cpn"),
            os.path.join(QUERIES, f"{name}.sml"))


# Test that every query gets CPN Tools' verdict.
@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_verdicts_match_cpn_tools(name):
    net, queries = _paths(name)
    result = check_cpn(net, askctl=queries)
    got = {pid: result.properties[pid].holds for pid in EXPECTED[name]}
    assert got == EXPECTED[name]


# Test that the fast path and the basic evaluator differ where CPN Tools' do.
def test_fast_path_is_not_the_basic_evaluator():
    net, queries = _paths("workers")
    result = check_cpn(net, askctl=queries)
    # POS (ALONG a) is decided on the SCC graph, where a dead end counts...
    assert result.properties["W6"].holds
    # ...but hidden from the pattern, ALONG never holds at a dead marking.
    assert not result.properties["W7"].holds


# Test that queries may be given as text and mixed with user properties.
def test_text_and_user_properties():
    net, _ = _paths("dining")
    text = ("fun E n = Mark.Top'Eat 1 n <> empty;\n"
            "eval_node (POS (NF (\"e\", E))) InitNode;\n"
            "eval_node (INV (NF (\"e\", E))) InitNode;")
    result = check_cpn(net, askctl=text, properties="EF marked(Eat)")
    assert result.properties["Q1"].holds
    assert not result.properties["Q2"].holds
    assert result.properties["U1"].holds


# Test that a violated query explains itself.
def test_violation_is_reported():
    net, queries = _paths("dining")
    result = check_cpn(net, askctl=queries)
    verdict = result.properties["NeverTwo"]
    assert not verdict.holds
    assert "InitNode is false" in str(verdict.detail)


# Test that a reduction never decides a query on a reduced graph.
def test_reductions_fall_back_to_the_full_graph():
    net, queries = _paths("workers")
    full = check_cpn(net, askctl=queries)
    reduced = check_cpn(net, askctl=queries, reduction="stubborn")
    for pid in EXPECTED["workers"]:
        assert reduced.properties[pid].holds == full.properties[pid].holds


# Test the errors a query file can raise.
@pytest.mark.parametrize("text, message", [
    ("fun f n = true;", "asks nothing"),
    ("eval_node (NF (\"x\", fn _ => true)) 2;", "initial marking"),
    ("eval_node (AF (\"x\", fn _ => true)) InitNode;", "Arc handled as Node"),
    ("eval_node (NF (\"x\", fn _ => 1)) InitNode;", "not a bool"),
    ("structure S = struct end;", "not supported"),
])
def test_errors(text, message):
    net, _ = _paths("dining")
    with pytest.raises((AskCtlError, Exception)) as info:
        check_cpn(net, askctl=text)
    assert message in str(info.value)


# Test that the state-space functions see the graph CPNCheck built.
def test_state_space_functions():
    net, _ = _paths("workers")
    mc = CPNModelChecker(net, askctl=(
        "val n = NoOfNodes ();\n"
        "fun Path m = length (NodesInPath (InitNode, m)) > 0;\n"
        "fun Back m = Reachable (m, InitNode);\n"
        "eval_node (INV (NF (\"path\", Path))) InitNode;\n"
        "eval_node (NF (\"back\", fn _ => n = SccNoOfNodes ())) InitNode;\n"
        "eval_node (POS (NOT (NF (\"back\", Back)))) InitNode;"))
    result = mc.check()
    assert result.properties["Q1"].holds          # every node is reachable
    assert result.properties["Q2"].holds          # acyclic: one node per SCC
    assert result.properties["Q3"].holds          # it terminates


# Test the command-line option.
def test_command_line():
    net, queries = _paths("dining")
    out = subprocess.run([sys.executable, "-m", "cpncheck.cli", "check", net,
                          "--askctl", queries], capture_output=True,
                         text=True, cwd=os.path.join(HERE, ".."))
    assert "CanEat" in out.stdout and "NeverTwo" in out.stdout


# Test the parsed statements of a file.
def test_script_statements():
    net, queries = _paths("dining")
    mc = CPNModelChecker(net)
    with open(queries, encoding="utf-8") as handle:
        script = AskCtlScript(handle.read(), mc.cnet)
    assert [q[0] for q in script.queries][:3] == ["CanEat", "AlwaysAgain",
                                                 "NeverTwo"]
    assert "use" not in script.declarations
    assert "fun Eating" in script.declarations


# Test the same files against CPN Tools itself.
@pytest.mark.skipif(os.environ.get("CPNCHECK_CPNTOOLS") != "1",
                    reason="set CPNCHECK_CPNTOOLS=1 to compare with CPN Tools")
@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_against_cpn_tools(name):
    from cpncheck.oracle import compare_with_oracle

    net, queries = _paths(name)
    report = compare_with_oracle(net, askctl=queries)
    rows = {key: row for key, *row in report["rows"]}
    for pid in EXPECTED[name]:
        assert rows[pid][2], (pid, rows[pid])
