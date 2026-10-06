"""Equivalence and symmetry reduction: quotient verdicts are the full graph's.

A quotient is sound only for a consistent equivalence and for properties that
do not tell equivalent markings apart. Both conditions are exercised here in
both directions: on nets where they hold, every verdict must equal the full
graph's; where they fail -- a symmetry the net does not have, a canonical form
that merges markings that behave differently, a property naming a permuted
value -- the verdict must be withheld, never given wrongly.
"""

import os
import subprocess
import sys

import pytest

from cpncheck import check_cpn
from cpncheck.coloured import ColouredNet
from cpncheck.equivalence import (EquivalenceError, build_quotient,
                                  time_equivalence, user_equivalence)
from cpncheck.net import CPNNet
from cpncheck.query import parse_properties
from cpncheck.statespace import build_state_space
from cpncheck.symmetry import SymmetryError, parse_symmetry, symmetry_equivalence

from test_net_reading import write_net

PH = ('<color id="cPH"><id>PH</id><index><ml>1</ml><ml>N</ml>'
      '<id>ph</id></index></color>')
CS = ('<color id="cCS"><id>CS</id><index><ml>1</ml><ml>N</ml>'
      '<id>cs</id></index></color>')


# Function to write dining philosophers with N = 4.
def _philosophers(tmp_path, chopsticks="1`cs(i) ++ 1`cs(if i = N then 1 else i + 1)",
                  think="PH.all()"):
    return write_net(str(tmp_path / "dp.cpn"), {"Page": {
        "places": [("T", "Think", "PH", think, None),
                   ("E", "Eat", "PH", None, None),
                   ("U", "Unused", "CS", "CS.all()", None)],
        "trans": [("Tk", "Take", None, None), ("Pt", "Put", None, None)],
        "arcs": [("Tk", "T", "PtoT", "p"), ("Tk", "U", "PtoT", "Chopsticks(p)"),
                 ("Tk", "E", "TtoP", "p"),
                 ("Pt", "E", "PtoT", "p"), ("Pt", "U", "TtoP", "Chopsticks(p)"),
                 ("Pt", "T", "TtoP", "p")]}},
        colsets=("INT",), colors=(PH, CS), variables=("n",),
        typed_vars={"p": "PH"},
        ml=("val N = 4;", f"fun Chopsticks(ph(i)) = {chopsticks};"))


# Function to write a timed net whose clock grows forever.
def _timed_cycle(tmp_path, out="x @+ 3"):
    return write_net(str(tmp_path / "cycle.cpn"), {"Top": {
        "places": [("A", "A", "INT", "1`1 ++ 1`2", None),
                   ("B", "B", "INT", None, None)],
        "trans": [("Go", "Go", None, None), ("Back", "Back", None, None)],
        "arcs": [("Go", "A", "PtoT", "x"), ("Go", "B", "TtoP", out),
                 ("Back", "B", "PtoT", "x"), ("Back", "A", "TtoP", "x @+ x")]}},
        variables=("x",), timed=("INT",))


# Function to write a finite timed net where three jobs pass two stages.
def _jobs(tmp_path):
    return write_net(str(tmp_path / "jobs.cpn"), {"Top": {
        "places": [("A", "Todo", "INT", "1`1 ++ 1`2 ++ 1`3", None),
                   ("B", "Doing", "INT", None, None),
                   ("C", "Done", "INT", None, None)],
        "trans": [("S", "Start", None, None), ("F", "Finish", None, None)],
        "arcs": [("S", "A", "PtoT", "x"), ("S", "B", "TtoP", "x @+ x"),
                 ("F", "B", "PtoT", "x"), ("F", "C", "TtoP", "x @+ 1")]}},
        variables=("x",), timed=("INT",))


# Function to write properties over every place of a net.
def _props(path):
    lines = []
    for pl in ColouredNet(CPNNet(path)).places:
        g = pl["gid"]
        lines += [f'AG tokens("{g}") <= 2', f'EF empty("{g}")',
                  f'AG EF marked("{g}")', f'AF marked("{g}")',
                  f'AG (dead -> marked("{g}"))', f'E[marked("{g}") U dead]']
    return "\n".join(lines)


# Function to compare quotient verdicts with full-graph verdicts.
def _agree(path, **kw):
    text = _props(path)
    full = check_cpn(path, properties=text)
    quotient = check_cpn(path, properties=text, **kw)
    decided = 0
    for pid, r in quotient.properties.items():
        if r.holds is not None:
            decided += 1
            assert r.holds == full.properties[pid].holds, pid
    return decided, quotient


# ---------------------------------------------------------------------------
# Time equivalence
# ---------------------------------------------------------------------------

def test_time_equivalence_agrees_with_the_full_graph(tmp_path):
    # Nothing here repeats up to a time shift, so no class has two members:
    # the quotient is the graph itself, and must say the same.
    decided, q = _agree(_jobs(tmp_path), reduction="equivalence")
    assert decided >= 15
    assert q.stats["classes"] == build_state_space(
        ColouredNet(CPNNet(_jobs(tmp_path)))).n_nodes
    assert "exact" in q.stats["consistency"]


def test_time_equivalence_makes_a_clock_driven_graph_finite(tmp_path):
    net = ColouredNet(CPNNet(_timed_cycle(tmp_path)))
    assert not build_state_space(net, max_nodes=2_000).complete
    quotient, report = build_quotient(net, time_equivalence(net))
    assert quotient.complete and report.consistent and report.tested > 0
    result = check_cpn(_timed_cycle(tmp_path), reduction="equivalence",
                       properties="AG !dead\nAG tokens(A) <= 2\n"
                                  "AG EF tokens(B) = 0")
    assert [result.properties[p].holds for p in ("U1", "U3")] == [True, True]


def test_time_equivalence_refuses_nets_that_read_the_clock(tmp_path):
    net = ColouredNet(CPNNet(_timed_cycle(tmp_path, out="x @+ (time() mod 2)")))
    with pytest.raises(EquivalenceError, match="time\\(\\)"):
        time_equivalence(net)


def test_time_equivalence_needs_a_timed_net(tmp_path):
    with pytest.raises(EquivalenceError, match="timed net"):
        check_cpn(_philosophers(tmp_path), reduction="equivalence")


# ---------------------------------------------------------------------------
# User equivalences
# ---------------------------------------------------------------------------

def test_a_user_equivalence_gives_conditional_verdicts(tmp_path):
    decided, q = _agree(_philosophers(tmp_path), reduction="equivalence",
                        equivalence=lambda m: m)
    assert decided > 0
    assert all("conditional" in r.detail for r in q.properties.values()
               if r.holds is not None)


def test_an_inconsistent_equivalence_withholds_every_verdict(tmp_path):
    # Forgetting who eats merges markings that behave differently.
    forget = lambda m: (m[0], (), m[2])                    # noqa: E731
    path = _philosophers(tmp_path)
    q = check_cpn(path, reduction="equivalence", equivalence=forget,
                  properties=_props(path))
    assert "INCONSISTENT" in q.stats["consistency"]
    assert all(r.holds is None for r in q.properties.values())


# ---------------------------------------------------------------------------
# Symmetry
# ---------------------------------------------------------------------------

def test_rotating_philosophers_and_chopsticks_together(tmp_path):
    path = _philosophers(tmp_path)
    decided, q = _agree(path, reduction="symmetry", symmetry="PH,CS=rotation")
    assert decided > 0
    full = build_state_space(ColouredNet(CPNNet(path)))
    assert q.stats["classes"] < full.n_nodes
    assert "consistent" in q.stats["consistency"]


@pytest.mark.parametrize("spec", ["PH,CS=all", "PH=rotation"])
def test_a_symmetry_the_net_does_not_have_is_caught(tmp_path, spec):
    path = _philosophers(tmp_path)
    q = check_cpn(path, reduction="symmetry", symmetry=spec,
                  properties=_props(path))
    assert "INCONSISTENT" in q.stats["consistency"]
    assert all(r.holds is None for r in q.properties.values())


def test_a_property_naming_a_permuted_value_is_not_preserved(tmp_path):
    q = check_cpn(_philosophers(tmp_path), reduction="symmetry",
                  symmetry="PH,CS=rotation",
                  properties="EF has(Eat, ph(1))\nAG tokens(Eat) <= 2")
    assert q.properties["U1"].holds is None
    assert "singles out" in q.properties["U1"].detail
    assert q.properties["U2"].holds is True


def test_an_asymmetric_initial_marking_is_refused(tmp_path):
    path = _philosophers(tmp_path, think="1`ph(1) ++ 1`ph(2)")
    net = ColouredNet(CPNNet(path))
    with pytest.raises(SymmetryError, match="initial marking"):
        symmetry_equivalence(net, "PH,CS=rotation")


@pytest.mark.parametrize("spec,match", [
    ("XX=all", "no colour set named"),
    ("PH=swap", "'all' or 'rotation'"),
    ("PH,INT=all", "finite list"),
])
def test_bad_symmetry_specifications(tmp_path, spec, match):
    net = ColouredNet(CPNNet(_philosophers(tmp_path)))
    with pytest.raises(SymmetryError, match=match):
        symmetry_equivalence(net, spec)


def test_parse_symmetry():
    assert parse_symmetry(["PH,CS=rotation", "D"]) == {
        ("PH", "CS"): "rotation", ("D",): "all"}
    assert parse_symmetry({"PH": "all"}) == {("PH",): "all"}


def test_the_command_line(tmp_path):
    path = _philosophers(tmp_path)
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    run = lambda *a: subprocess.run(                       # noqa: E731
        [sys.executable, "-m", "cpncheck.cli", "check", path, *a],
        capture_output=True, text=True, cwd=root,
        env={**os.environ, "PYTHONPATH": root})
    ok = run("--reduction", "symmetry", "--symmetry", "PH,CS=rotation",
             "--prop", "AG tokens(Eat) <= 2")
    assert ok.returncode == 0, ok.stderr
    assert "classes" in ok.stdout and "consistency" in ok.stdout
    bad = run("--reduction", "symmetry", "--symmetry", "XX=all")
    assert bad.returncode == 2 and "no colour set" in bad.stderr


SAMPLES = os.environ.get("CPNTOOLS_SAMPLES",
                         r"C:\Program Files (x86)\CPN Tools\Sample CPN Models")


@pytest.mark.parametrize("rel,spec,classes", [
    (os.path.join("DiningPhilosophers", "DiningPhilosophers.cpn"),
     "PH,CS=rotation", 3),
    (os.path.join("DistributedDataBase", "DistributedDataBase.cpn"),
     "DBM=all", 11),
])
def test_symmetry_on_cpntools_samples(rel, spec, classes):
    """Philosophers rotate (11 markings, 3 classes); database sites permute
    freely (109 markings, 11 classes)."""
    path = os.path.join(SAMPLES, rel)
    if not os.path.exists(path):
        pytest.skip("CPN Tools samples not found")
    decided, q = _agree(path, reduction="symmetry", symmetry=spec)
    assert decided > 0 and q.stats["classes"] == classes


def test_counterexample_steps_show_index_values_as_written(tmp_path):
    q = check_cpn(_philosophers(tmp_path), properties="AG tokens(Eat) <= 1")
    steps = [s.detailed() for s in q.properties["U1"].cex.prefix]
    assert steps and all("p = ph(" in s for s in steps), steps
