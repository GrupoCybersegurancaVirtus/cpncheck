"""User properties written as text (cpncheck.query).

The language is checked three ways: it parses what the documentation says and
refuses the rest with a message; on small nets each operator means what CTL
says; and, with ``CPNCHECK_CPNTOOLS=1``, every user property on two of CPN
Tools' own samples gets the verdict CPN Tools gives it.
"""

import os
import subprocess
import sys

import pytest

from cpncheck import CPNModelChecker, check_cpn
from cpncheck.coloured import ColouredNet
from cpncheck.net import CPNNet
from cpncheck.query import (QueryError, UserProperty, parse_formula,
                            parse_properties)

from test_net_reading import write_net

SAMPLES_DIR = os.environ.get(
    "CPNTOOLS_SAMPLES", r"C:\Program Files (x86)\CPN Tools\Sample CPN Models")
DINING = os.path.join(SAMPLES_DIR, "DiningPhilosophers", "DiningPhilosophers.cpn")
PROTOCOL = os.path.join(SAMPLES_DIR, "SimpleProtocol", "SimpleProtocol_OG.cpn")
HAVE_SAMPLES = os.path.exists(DINING) and os.path.exists(PROTOCOL)

DINING_PROPS = '''
ME "neighbours never eat together": AG !(has(Eat, ph(1)) & has(Eat, ph(2)))
NOEAT: AG !has(Eat, ph(1))
STARVE: AF has(Eat, ph(3))
CANSTARVE: EG !has(Eat, ph(1))
BOUND: AG tokens("Unused Chopsticks") <= 5 & AG tokens(Eat) < 3
TAKE: AG enabled_count("Take Chopsticks") >= 1
UNTIL: E[!has(Eat, ph(1)) U has(Eat, ph(2))]
AUNTIL: A[tokens(Eat) = 0 U tokens(Eat) > 0]
'''

PROTOCOL_PROPS = '''
DONE: AG (dead -> has(NextRec, 5))
REACH: EF has(NextRec, 5)
ALWAYS: AF has(NextRec, 5)
LIMIT: AG tokens(Limit) <= 2 & EF tokens(Limit) = 0
ORDER: !E[!has(NextRec, 2) U has(NextRec, 3)]
LIVE: AG EF enabled("Send Packet")
'''


def _counter(tmp_path):
    """C counts 0..3; Reset takes it back from 3 to 0."""
    return write_net(str(tmp_path / "count.cpn"), {"Top": {
        "places": [("C", "Counter", "INT", "1`0", None)],
        "trans": [("T", "Tick", "[n < 3]", None),
                  ("R", "Reset", "[n = 3]", None)],
        "arcs": [("T", "C", "PtoT", "n"), ("T", "C", "TtoP", "n + 1"),
                 ("R", "C", "PtoT", "n"), ("R", "C", "TtoP", "0")]}})


def _verdicts(path, text):
    result = check_cpn(path, properties=text)
    return {p.id: result.properties[p.id].holds
            for p in parse_properties(text)}, result


# ---------------------------------------------------------------------------
# Reading property files
# ---------------------------------------------------------------------------

def test_ids_names_comments_and_continuations():
    props = parse_properties('''
        # a comment
        P1 "first one": AG !dead      # trailing comment
        AF dead
        P3:
            AG (tokens(Counter) <= 3 &
                tokens(Counter) >= 0)
    ''')
    assert [(p.id, p.name) for p in props] == [
        ("P1", "first one"), ("U1", "AF dead"),
        ("P3", "AG (tokens(Counter) <= 3 & tokens(Counter) >= 0)")]


def test_a_duplicate_id_is_refused():
    with pytest.raises(QueryError, match="duplicate"):
        parse_properties("P1: AG !dead\nP1: AF dead")


@pytest.mark.parametrize("text,message", [
    ("AG tokens(Counter) + 1 <= 3", "unexpected"),
    ("AG frobnicate(Counter)", "unknown proposition"),
    ("AG marked(Nowhere)", "no place named 'Nowhere'"),
    ("AG enabled(Counter)", "no transition named"),
    ("AG tokens(Counter)", "comparison"),
    ("AG (marked(Counter)", r"expected '\)'"),
])
def test_bad_properties_are_refused_with_a_message(tmp_path, text, message):
    net = ColouredNet(CPNNet(_counter(tmp_path)))
    with pytest.raises(QueryError, match=message):
        parse_formula(text, net)


def test_names_resolve_by_path_page_and_name(tmp_path):
    net = ColouredNet(CPNNet(_counter(tmp_path)))
    for name in ("Counter", "Top/Counter", '"Counter"'):
        phi = parse_formula(f"AG marked({name})", net)
        assert phi.operand.selector.indices == (0,)


# ---------------------------------------------------------------------------
# Meaning
# ---------------------------------------------------------------------------

def test_the_operators_on_a_counter(tmp_path):
    verdicts, result = _verdicts(_counter(tmp_path), '''
        A: AG tokens(Counter) = 1
        B: AG !has(Counter, 4)
        C: EF has(Counter, 3)
        D: AF has(Counter, 3)
        E: AG AF has(Counter, 0)
        F: EG !has(Counter, 2)
        G: E[!has(Counter, 2) U has(Counter, 1)]
        H: A[has(Counter, 0) U has(Counter, 1)]
        I: AG (has(Counter, 3) -> enabled(Reset) & !enabled(Tick))
        J: AG enabled_count(Tick) <= 1 & AG empty(Counter)
    ''')
    assert verdicts == {"A": True, "B": True, "C": True, "D": True, "E": True,
                        "F": False, "G": True, "H": True, "I": True,
                        "J": False}
    # User properties are requirements: a false one fails the check.
    assert not result.passed and [r.id for r in result.failures] == ["F", "J"]


def test_a_counterexample_replays(tmp_path):
    path = _counter(tmp_path)
    mc = CPNModelChecker(path, properties="X: AG !has(Counter, 2)")
    r = mc.check().properties["X"]
    assert r.holds is False and r.cex.kind == "finite"
    assert r.cex.replay(mc.cnet)
    assert "has(Counter, 2) holds" in r.detail


def test_an_id_clashing_with_the_profile_is_refused(tmp_path):
    with pytest.raises(QueryError, match="clashes"):
        CPNModelChecker(_counter(tmp_path), properties="R1: AG !dead")


def test_user_properties_survive_the_reduction(tmp_path):
    path = _counter(tmp_path)
    text = "A: AG tokens(Counter) = 1\nD: AF has(Counter, 3)\nF: EG !has(Counter, 2)"
    full = check_cpn(path, properties=text)
    reduced = check_cpn(path, properties=text, reduction="stubborn")
    assert {k: r.holds for k, r in full.properties.items()} == \
        {k: r.holds for k, r in reduced.properties.items()}


def test_the_command_line(tmp_path):
    path = _counter(tmp_path)
    props = tmp_path / "p.props"
    props.write_text("P1: AG tokens(Counter) <= 3\n", encoding="utf-8")
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    run = lambda *a: subprocess.run(                       # noqa: E731
        [sys.executable, "-m", "cpncheck.cli", "check", path, *a],
        capture_output=True, text=True, cwd=root,
        env={**os.environ, "PYTHONPATH": root})
    ok = run("--props", str(props), "--prop", "AF has(Counter, 3)")
    assert ok.returncode == 0, ok.stderr
    assert "P1" in ok.stdout and "U2" in ok.stdout and "PASS" in ok.stdout
    bad = run("--prop", "AG marked(Nowhere)")
    assert bad.returncode == 2
    assert "property error" in bad.stderr and "Traceback" not in bad.stderr
    failed = run("--prop", "AG !has(Counter, 3)")
    assert failed.returncode == 1


# ---------------------------------------------------------------------------
# CPN Tools' own samples
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAVE_SAMPLES, reason="CPN Tools samples not found")
@pytest.mark.parametrize("path,text", [(DINING, DINING_PROPS),
                                       (PROTOCOL, PROTOCOL_PROPS)],
                         ids=["dining", "protocol"])
def test_user_properties_on_samples_agree_with_the_reduction(path, text):
    full = check_cpn(path, properties=text)
    reduced = check_cpn(path, properties=text, reduction="stubborn")
    assert {k: r.holds for k, r in full.properties.items()} == \
        {k: r.holds for k, r in reduced.properties.items()}
    falses = [k for k, r in full.properties.items()
              if r.holds is False and r.spec.kind != "report"]
    assert falses, "the sample properties should include false ones"


@pytest.mark.skipif(not HAVE_SAMPLES, reason="CPN Tools samples not found")
@pytest.mark.skipif(os.environ.get("CPNCHECK_CPNTOOLS") != "1",
                    reason="set CPNCHECK_CPNTOOLS=1 to compare with CPN Tools")
@pytest.mark.parametrize("path,text", [(DINING, DINING_PROPS),
                                       (PROTOCOL, PROTOCOL_PROPS)],
                         ids=["dining", "protocol"])
def test_user_properties_agree_with_cpntools(path, text):
    from cpncheck.oracle import CPNToolsOracle, compare_with_oracle

    oracle = CPNToolsOracle()
    if oracle.missing():
        pytest.skip("CPN Tools engine incomplete")
    report = compare_with_oracle(path, oracle=oracle, properties=text,
                                 timeout=600)
    assert not report["errors"], report["errors"]
    assert report["agree"], [r for r in report["rows"] if not r[3]]
    ids = {p.id for p in parse_properties(text)}
    compared = {key for key, *_ in report["rows"]}
    assert ids <= compared
