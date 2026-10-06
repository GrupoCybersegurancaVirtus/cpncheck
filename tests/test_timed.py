"""Timed nets, priorities, guard-bound variables and code segments.

Each construct is checked on a net small enough to work out by hand. With
``CPNCHECK_CPNTOOLS=1``, finite variants of CPN Tools' TimedResourceAlloc
sample are also matched against CPN Tools' own occurrence graph.
"""

import os
import xml.etree.ElementTree as ET

import pytest

from cpncheck.coloured import (CPNTOOLS_401, REMOVED, ColouredNet,
                               UnsupportedNet)
from cpncheck.cpnml import TimedToken
from cpncheck.net import CPNNet
from cpncheck.reduction import Dependency, ReducedChecker
from cpncheck.statespace import build_state_space

from test_net_reading import write_net

TRA = os.path.join(os.environ.get(
    "CPNTOOLS_SAMPLES", r"C:\Program Files (x86)\CPN Tools\Sample CPN Models"),
    "TimedResourceAlloc", "TimedResourceAlloc.cpn")


# Function to build and read a one-page net.
def _net(tmp_path, places, trans, arcs, **kwargs):
    path = write_net(str(tmp_path / "n.cpn"), pages={"Top": {
        "places": places, "trans": trans, "arcs": arcs}}, **kwargs)
    return ColouredNet(CPNNet(path))


# Function to give the tokens of a place by name.
def _tokens(net, marking, name):
    return marking[next(i for i, p in enumerate(net.places) if p["name"] == name)]


# ---------------------------------------------------------------------------
# Timed nets
# ---------------------------------------------------------------------------

def _pipeline(tmp_path, out="x @+5", time=None):
    # P --T1--> Q --T2--> R, every place timed.
    extras = {"time": time} if time else None
    return _net(tmp_path,
                [("P", "P", "INT", "1`7", None), ("Q", "Q", "INT", None, None),
                 ("R", "R", "INT", None, None)],
                [("T1", "T1", None, extras), ("T2", "T2", None, None)],
                [("T1", "P", "PtoT", "x"), ("T1", "Q", "TtoP", out),
                 ("T2", "Q", "PtoT", "x"), ("T2", "R", "TtoP", "x")],
                variables=("x",), timed=("INT",))


def test_an_arc_delay_stamps_the_token_and_moves_the_clock(tmp_path):
    net = _pipeline(tmp_path)
    assert net.timed and not net.reducible
    m0 = net.initial
    assert m0[-1] == 0 and _tokens(net, m0, "P") == (TimedToken(7, 0),)
    (ti, _k, env), = net.enabled(m0)
    m1 = net.fire(m0, ti, env)
    assert _tokens(net, m1, "Q") == (TimedToken(7, 5),) and m1[-1] == 0
    # Nothing is ready at 0: the clock jumps to 5 for T2.
    (ti, _k, env), = net.enabled(m1)
    m2 = net.fire(m1, ti, env)
    assert m2[-1] == 5 and _tokens(net, m2, "R") == (TimedToken(7, 5),)


def test_transition_and_arc_delays_add_up(tmp_path):
    net = _pipeline(tmp_path, time="@+2")
    (ti, _k, env), = net.enabled(net.initial)
    assert _tokens(net, net.fire(net.initial, ti, env), "Q") == (TimedToken(7, 7),)


def test_time_reads_the_clock_of_the_occurrence(tmp_path):
    net = _pipeline(tmp_path, out="x @+5")
    m = net.initial
    for _ in range(2):
        (ti, _k, env), = net.enabled(m)
        m = net.fire(m, ti, env)
    # A third transition copying time() into a token would see 5: check the
    # environment hook directly on the reached marking.
    net._now = m[-1]
    assert net.env["time"](()) == 5


def test_a_delay_covers_the_whole_arc_inscription(tmp_path):
    # As in CPN Tools: "if .. then 1`x else empty @+3" delays both branches.
    net = _pipeline(tmp_path, out="if x = 7 then 1`x else empty @+3")
    (ti, _k, env), = net.enabled(net.initial)
    assert _tokens(net, net.fire(net.initial, ti, env), "Q") == (TimedToken(7, 3),)


def test_only_the_earliest_binding_elements_are_enabled(tmp_path):
    net = _net(tmp_path,
               [("A", "A", "INT", "1`1@4", None), ("B", "B", "INT", "1`2@9", None),
                ("C", "C", "INT", None, None)],
               [("TA", "TA", None, None), ("TB", "TB", None, None)],
               [("TA", "A", "PtoT", "x"), ("TA", "C", "TtoP", "x"),
                ("TB", "B", "PtoT", "x"), ("TB", "C", "TtoP", "x")],
               variables=("x",), timed=("INT",))
    names = [net.transitions[ti]["name"] for ti, _k, _e in net.enabled(net.initial)]
    assert names == ["TA"]
    ss = build_state_space(net)
    assert ss.n_nodes == 3 and ss.markings[-1][-1] == 9


def test_each_choice_of_ready_token_is_a_successor(tmp_path):
    # P holds value 1 stamped 1 and 2; T also needs W's token, ready at 5,
    # when both of P's are ready: T may take either, and the markings differ.
    net = _net(tmp_path,
               [("P", "P", "INT", "1`1@1 +++ 1`1@2", None),
                ("W", "W", "INT", "1`0@5", None), ("Q", "Q", "INT", None, None)],
               [("T", "T", None, None)],
               [("T", "W", "PtoT", "y"), ("T", "P", "PtoT", "x"),
                ("T", "Q", "TtoP", "x")],
               variables=("x", "y"), timed=("INT",))
    first = net.enabled(net.initial)
    assert sorted(e[REMOVED] for _t, _k, e in first) == [
        ((0, 1, (1,)), (1, 0, (5,))), ((0, 1, (2,)), (1, 0, (5,)))]
    ss = build_state_space(net)
    assert ss.n_nodes == 3
    assert {_tokens(net, ss.markings[d], "P") for _t, _k, d in ss.succ[0]} == {
        (TimedToken(1, 1),), (TimedToken(1, 2),)}


def test_the_cpntools_401_view_shifts_timestamps_by_the_clock(tmp_path):
    net = _pipeline(tmp_path)
    compat = ColouredNet(net.net, compat=CPNTOOLS_401)
    m = ((TimedToken(7, 3),), (TimedToken(7, 12),), (), 8)
    view = compat._expansion_view(m)
    assert view == ((TimedToken(7, 0),), (TimedToken(7, 4),), (), 8)
    assert net._expansion_view(m) == m
    with pytest.raises(ValueError):
        ColouredNet(net.net, compat="cpntools-9")


def test_a_timed_net_is_never_reduced(tmp_path):
    net = _pipeline(tmp_path)
    from cpncheck.formula import AG, Not, Dead
    checker = ReducedChecker(net, Dependency(net), max_nodes=1000)
    kind, graph = checker.graph_for(AG(Not(Dead())))
    assert kind == "full" and graph.complete


def test_a_real_delay_is_refused(tmp_path):
    with pytest.raises(UnsupportedNet):
        build_state_space(_pipeline(tmp_path, out="x @+ 1.5"))


# ---------------------------------------------------------------------------
# Priorities
# ---------------------------------------------------------------------------

def test_only_the_most_urgent_priority_may_occur(tmp_path):
    net = _net(tmp_path,
               [("P", "P", "INT", "1`1", None), ("Q", "Q", "INT", None, None)],
               [("Hi", "Hi", None, {"priority": "P_HIGH"}),
                ("Lo", "Lo", None, {"priority": "P_LOW"})],
               [("Hi", "P", "PtoT", "x"), ("Hi", "Q", "TtoP", "x"),
                ("Lo", "P", "PtoT", "x"), ("Lo", "Q", "TtoP", "x + 1")],
               variables=("x",))
    assert net.uses_priorities and not net.reducible
    names = [net.transitions[ti]["name"] for ti, _k, _e in net.enabled(net.initial)]
    assert names == ["Hi"]
    assert build_state_space(net).n_nodes == 2


# ---------------------------------------------------------------------------
# Guard-bound variables and code segments
# ---------------------------------------------------------------------------

def test_a_guard_can_define_a_variable(tmp_path):
    # y is on no input arc and INT has no finite domain: the guard defines it.
    net = _net(tmp_path,
               [("P", "P", "INT", "1`3", None), ("Q", "Q", "INT", None, None)],
               [("T", "T", "[y = x * 2]", None)],
               [("T", "P", "PtoT", "x"), ("T", "Q", "TtoP", "y")],
               variables=("x", "y"))
    (ti, _k, env), = net.enabled(net.initial)
    assert env["y"] == 6
    assert _tokens(net, net.fire(net.initial, ti, env), "Q") == (6,)


def test_a_pure_code_segment_binds_its_outputs(tmp_path):
    net = _net(tmp_path,
               [("P", "P", "INT", "1`3", None), ("Q", "Q", "INT", None, None)],
               [("T", "T", None, {"code": "input (x); output (y); action (x + 10);"})],
               [("T", "P", "PtoT", "x"), ("T", "Q", "TtoP", "y")],
               variables=("x", "y"))
    (ti, _k, env), = net.enabled(net.initial)
    assert _tokens(net, net.fire(net.initial, ti, env), "Q") == (13,)


# ---------------------------------------------------------------------------
# Against CPN Tools
# ---------------------------------------------------------------------------

@pytest.mark.skipif(os.environ.get("CPNCHECK_CPNTOOLS") != "1",
                    reason="set CPNCHECK_CPNTOOLS=1 to compare with CPN Tools")
@pytest.mark.skipif(not os.path.exists(TRA), reason="CPN Tools samples not found")
@pytest.mark.parametrize("bound", [1, 2])
def test_timed_resource_allocation_is_contained_in_ours(tmp_path, bound):
    """CPN Tools' graph of a finite TimedResourceAlloc is a subgraph of ours.

    The sample cycles forever (``i`` grows without bound); a guard
    ``[i < bound]`` on T5 makes it finite. Containment, not equality, is the
    check: see :func:`cpncheck.oracle.compare_graph_containment`.
    """
    from cpncheck.oracle import CPNToolsOracle, compare_graph_containment

    tree = ET.parse(TRA)
    for t in tree.getroot().iter("trans"):
        if t.findtext("text").strip() == "T5":
            t.find("cond").find("text").text = f"[i < {bound}]"
    path = str(tmp_path / f"tra{bound}.cpn")
    tree.write(path, encoding="iso-8859-1", xml_declaration=True)
    oracle = CPNToolsOracle()
    if oracle.missing():
        pytest.skip("CPN Tools engine incomplete")
    report = compare_graph_containment(path, oracle=oracle, compat=CPNTOOLS_401,
                                       timeout=1200)
    assert report["contained"], report
    assert report["dead"][0] == report["dead"][1]


def test_stubborn_reduction_builds_only_full_graphs_for_timed_nets(tmp_path):
    """Every graph, including the one the home-marking test asks for."""
    from cpncheck import check_cpn

    path = write_net(str(tmp_path / "t.cpn"), **dict(_pipeline_kwargs()))
    result = check_cpn(path, reduction="stubborn")
    assert {plan.split(" ")[0] for plan in result.stats["plans"].values()} \
        == {"full"}
    assert set(result.stats["per_kind"]) == {"full"}


# Function to give the write_net arguments of the timed pipeline.
def _pipeline_kwargs():
    return {"pages": {"Top": {
        "places": [("P", "P", "INT", "1`7", None), ("Q", "Q", "INT", None, None),
                   ("R", "R", "INT", None, None)],
        "trans": [("T1", "T1", None, None), ("T2", "T2", None, None)],
        "arcs": [("T1", "P", "PtoT", "x"), ("T1", "Q", "TtoP", "x @+5"),
                 ("T2", "Q", "PtoT", "x"), ("T2", "R", "TtoP", "x")]}},
        "variables": ("x",), "timed": ("INT",)}
