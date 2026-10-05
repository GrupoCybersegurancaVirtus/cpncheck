"""The sweep-line method: the verdicts it gives are the full graph's.

The method decides properties of single markings (``AG``, ``EF``, ``not EF``
of state predicates) and nothing else. Its claim is that the verdict does not
depend on the progress measure, monotone or not: a bad measure costs regress
arcs and re-exploration, never a wrong answer. So every check below compares
with the full occurrence graph under several measures, one of them chosen to
be as bad as possible.
"""

import os
import subprocess
import sys

import pytest

from cpncheck import CPNModelChecker, check_cpn
from cpncheck.coloured import ColouredNet
from cpncheck.mutation import make_mutants
from cpncheck.net import CPNNet
from cpncheck.query import parse_properties
from cpncheck.statespace import build_state_space
from cpncheck.sweepline import ProgressError, parse_progress, sweep

from test_net_reading import write_net

NETS = os.path.join(os.path.dirname(__file__), "nets")
FIXTURES = ["gbdt_binary.cpn", "rf_multiclass.cpn"]


# Function to write a counter that goes 0..3 and back to 0.
def _counter(tmp_path):
    return write_net(str(tmp_path / "count.cpn"), {"Top": {
        "places": [("C", "Counter", "INT", "1`0", None)],
        "trans": [("T", "Tick", "[n < 3]", None),
                  ("R", "Reset", "[n = 3]", None)],
        "arcs": [("T", "C", "PtoT", "n"), ("T", "C", "TtoP", "n + 1"),
                 ("R", "C", "PtoT", "n"), ("R", "C", "TtoP", "0")]}})


# Function to write a timed net where three jobs pass two stages.
def _jobs(tmp_path):
    return write_net(str(tmp_path / "jobs.cpn"), {"Top": {
        "places": [("A", "Todo", "INT", "1`1 ++ 1`2 ++ 1`3", None),
                   ("B", "Doing", "INT", None, None),
                   ("C", "Done", "INT", None, None)],
        "trans": [("S", "Start", None, None), ("F", "Finish", None, None)],
        "arcs": [("S", "A", "PtoT", "x"), ("S", "B", "TtoP", "x @+ x"),
                 ("F", "B", "PtoT", "x"), ("F", "C", "TtoP", "x @+ 1")]}},
        variables=("x",), timed=("INT",))


#: Measures every verdict must be independent of: none at all, token counts,
#: and an arbitrary non-monotone function of the marking.
MEASURES = ["0", "tokens(\"{first}\")", lambda m: hash(m) % 5]


# Function to give the measures for a net.
def _measures(path):
    first = ColouredNet(CPNNet(path)).places[0]["gid"]
    return [m.format(first=first) if isinstance(m, str) else m for m in MEASURES]


# Function to write user properties over the first places of a net.
def _props(path, places=4):
    lines = []
    for pl in ColouredNet(CPNNet(path)).places[:places]:
        g = pl["gid"]
        lines += [f'AG tokens("{g}") <= 1', f'EF empty("{g}")',
                  f'!EF tokens("{g}") >= 2', f'AG (dead -> marked("{g}"))']
    return parse_properties("\n".join(lines))


# Function to compare the sweep's verdicts with the full graph's.
def _agree(path, labels=None, props=None):
    options = {"class_labels": labels} if labels else None
    full = check_cpn(path, properties=props, options=options)
    decided = 0
    for measure in _measures(path):
        swept = check_cpn(path, properties=props, options=options,
                          reduction="sweep", progress=measure)
        for pid, r in swept.properties.items():
            if r.holds is None:
                continue
            decided += 1
            assert r.holds == full.properties[pid].holds, (path, measure, pid)
    return decided


@pytest.mark.parametrize("name", FIXTURES)
def test_the_sweep_agrees_with_the_full_graph_on_every_mutant(tmp_path, name):
    decided = 0
    for net in [{"path": os.path.join(NETS, name), "labels": None}] + \
            make_mutants(os.path.join(NETS, name), str(tmp_path)):
        decided += _agree(net["path"], net.get("labels"), _props(net["path"]))
    assert decided > 0


def test_user_properties_agree_on_a_counter(tmp_path):
    path = _counter(tmp_path)
    text = ("AG tokens(Counter) = 1\nEF has(Counter, 3)\n!EF has(Counter, 4)\n"
            "AG !dead\nAG has(Counter, 0)\nEF dead")
    full = check_cpn(path, properties=text)
    for progress in ("sum(Counter)", "0", "-1 * sum(Counter)"):
        swept = check_cpn(path, properties=text, reduction="sweep",
                          progress=progress)
        for p in parse_properties(text):
            assert swept.properties[p.id].holds == full.properties[p.id].holds


def test_a_violation_names_the_marking(tmp_path):
    result = check_cpn(_counter(tmp_path), properties="AG !has(Counter, 2)",
                       reduction="sweep", progress="sum(Counter)")
    r = result.properties["U1"]
    assert r.holds is False and "Counter: 2" in r.detail


def test_path_properties_get_no_verdict(tmp_path):
    result = check_cpn(_counter(tmp_path),
                       properties="AF has(Counter, 3)\nAG EF has(Counter, 0)",
                       reduction="sweep", progress="sum(Counter)")
    for pid in ("U1", "U2"):
        r = result.properties[pid]
        assert r.holds is None and "not preserved" in r.detail


def test_the_clock_of_a_timed_net_never_regresses(tmp_path):
    path = _jobs(tmp_path)
    net = ColouredNet(CPNNet(path))
    full = build_state_space(net)
    measure = parse_progress(None, net)
    assert measure.text == "clock"
    res = sweep(net, measure, max_stored=10_000)
    assert res.complete and res.regress == 0 and res.sweeps == 1
    assert res.explored == full.n_nodes
    assert res.distinct_bound < full.n_nodes
    assert len(res.dead) == len(full.dead)


def test_a_small_budget_leaves_unviolated_properties_undecided(tmp_path):
    path = _counter(tmp_path)
    result = CPNModelChecker(path, max_nodes=2, properties=(
        "AG tokens(Counter) = 1\nAG !has(Counter, 1)")).check(
        reduction="sweep", progress="0")
    assert result.properties["U1"].holds is None
    assert result.properties["U2"].holds is False


@pytest.mark.parametrize("spec,match", [
    ("tokens(Nowhere)", "no place named"),
    ("clock", "untimed"),
    (None, "needs a progress measure"),
    ("tokens(Counter) tokens(Counter)", "expected \\+ or -"),
    ("2 ** 3", "cannot read"),
])
def test_bad_measures_are_refused(tmp_path, spec, match):
    net = ColouredNet(CPNNet(_counter(tmp_path)))
    with pytest.raises(ProgressError, match=match):
        parse_progress(spec, net)


def test_the_command_line(tmp_path):
    path = _counter(tmp_path)
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    run = lambda *a: subprocess.run(                       # noqa: E731
        [sys.executable, "-m", "cpncheck.cli", "check", path, *a],
        capture_output=True, text=True, cwd=root,
        env={**os.environ, "PYTHONPATH": root})
    ok = run("--reduction", "sweep", "--progress", "sum(Counter)",
             "--prop", "AG tokens(Counter) = 1")
    assert ok.returncode == 0, ok.stderr
    assert "sweep-line" in ok.stdout
    bad = run("--reduction", "sweep")
    assert bad.returncode == 2 and "progress measure" in bad.stderr
