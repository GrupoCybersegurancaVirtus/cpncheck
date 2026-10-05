"""Partial-order reduction: the reduced graphs must give the full graph's verdicts.

A reduction is only worth having if it is invisible in the answers. The
standard held to here is the strongest one available without a proof
assistant: on every fixture net and every one of its mutants -- nets built to
violate each property in turn -- the verdict of every property with
``reduction="stubborn"`` equals the verdict on the full occurrence graph, and
every counterexample found on a reduced graph replays on the net.
"""

import os

import pytest

from cpncheck import CPNModelChecker, check_cpn
from cpncheck.coloured import ColouredNet
from cpncheck.formula import (AF, AG, EF, EU, Dead, Enabled, Implies, Marked,
                              MaxTokens, Not)
from cpncheck.mutation import make_mutants
from cpncheck.net import CPNNet
from cpncheck.reduction import (Dependency, ReducedChecker, build_reduced,
                                classify, split)
from cpncheck.selectors import Places, Transitions
from cpncheck.statespace import build_state_space

NETS = os.path.join(os.path.dirname(__file__), "nets")
FIXTURES = [("gbdt_binary.cpn", [0, 1]), ("rf_multiclass.cpn", [0, 1, 2])]
IDS = [f[0] for f in FIXTURES]


def _nets(tmp_path, name):
    """The fixture itself followed by every mutant of it."""
    src = os.path.join(NETS, name)
    return [{"name": "correct", "path": src, "labels": None}] + \
        make_mutants(src, str(tmp_path))


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,labels", FIXTURES, ids=IDS)
def test_reduced_verdicts_equal_full_verdicts(tmp_path, name, labels):
    compared = 0
    for m in _nets(tmp_path, name):
        mc = CPNModelChecker(m["path"], class_labels=m["labels"] or labels)
        full = mc.check()
        reduced = mc.check(reduction="stubborn")
        assert list(full.properties) == list(reduced.properties)
        for pid, r in full.properties.items():
            assert reduced.properties[pid].holds == r.holds, \
                (m["name"], pid, reduced.properties[pid].detail)
            compared += 1
    assert compared > 150


@pytest.mark.parametrize("name,labels", FIXTURES, ids=IDS)
def test_reduced_counterexamples_replay(tmp_path, name, labels):
    replayed = 0
    for m in _nets(tmp_path, name):
        mc = CPNModelChecker(m["path"], class_labels=m["labels"] or labels)
        for r in mc.check(reduction="stubborn").failures:
            assert r.cex is not None, (m["name"], r.id)
            if r.cex.kind in ("finite", "lasso"):
                assert r.cex.replay(mc.cnet), (m["name"], r.id, str(r.cex))
                replayed += 1
    assert replayed > 5


# ---------------------------------------------------------------------------
# The graphs themselves
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,labels", FIXTURES, ids=IDS)
def test_every_dead_marking_survives_the_reduction(tmp_path, name, labels):
    for m in _nets(tmp_path, name):
        net = ColouredNet(CPNNet(m["path"]))
        full = build_state_space(net)
        reduced = build_reduced(net, Dependency(net), "deadlock")
        assert reduced.complete
        assert sorted(reduced.markings[v] for v in reduced.dead) == \
            sorted(full.markings[v] for v in full.dead), m["name"]


@pytest.mark.parametrize("kind", ["deadlock", "stutter"])
@pytest.mark.parametrize("name,labels", FIXTURES, ids=IDS)
def test_a_reduced_graph_is_a_subgraph_of_the_full_one(name, labels, kind):
    net = ColouredNet(CPNNet(os.path.join(NETS, name)))
    full = build_state_space(net)
    index = {mk: i for i, mk in enumerate(full.markings)}
    full_arcs = {(src, ti, key, dst) for src, out in enumerate(full.succ)
                 for ti, key, dst in out}
    reduced = build_reduced(net, Dependency(net), kind)
    for src, out in enumerate(reduced.succ):
        for ti, key, dst in out:
            arc = (index[reduced.markings[src]], ti, key,
                   index[reduced.markings[dst]])
            assert arc in full_arcs


def test_independent_trees_are_no_longer_interleaved():
    """A forest of n trees has 2^n + 2 markings; the reduced graph n + 3."""
    net = ColouredNet(CPNNet(os.path.join(NETS, "rf_multiclass.cpn")))
    trees = {t["page"] for t in net.transitions if t["page"].startswith("Tree")}
    n = len(trees)
    assert build_state_space(net).n_nodes == 2 ** n + 2
    assert build_reduced(net, Dependency(net), "deadlock").n_nodes == n + 3


def test_enabling_is_recorded_beyond_the_expanded_arcs():
    """Enabling propositions must see what the reduction did not expand."""
    net = ColouredNet(CPNNet(os.path.join(NETS, "rf_multiclass.cpn")))
    ss = build_reduced(net, Dependency(net), "deadlock")
    wider = [v for v in range(ss.n_nodes)
             if len(ss.enabled[v]) > len(ss.succ[v])]
    assert wider, "the reduction expanded everything it saw"


def test_dependency_reads_the_arcs():
    net = ColouredNet(CPNNet(os.path.join(NETS, "rf_multiclass.cpn")))
    dep = Dependency(net)
    names = [t["name"] for t in net.transitions]
    dist = names.index("Distribute")
    inp = next(i for i, p in enumerate(net.places) if p["name"] == "Input")
    assert inp in dep.takes[dist]
    assert dep.givers.get(inp, frozenset()) == frozenset()
    leaf = next(i for i, t in enumerate(net.transitions)
                if t["page"].startswith("Tree"))
    siblings = {i for i, t in enumerate(net.transitions)
                if t["page"] == net.transitions[leaf]["page"]} - {leaf}
    assert siblings <= dep.conflicts[leaf]


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def test_each_formula_shape_gets_the_right_graph():
    pred = Places(name="Prediction")
    assert classify(AF(Dead()))[0] == "deadlock"
    assert classify(AG(Implies(Dead(), Marked(pred))))[0] == "deadlock"
    assert classify(AG(MaxTokens(pred, 1)))[0] == "safety"
    assert classify(Not(EF(Marked(pred))))[0] == "safety"
    assert classify(EF(Marked(pred)))[0] == "safety"
    assert classify(AF(Marked(pred)))[0] == "stutter"
    assert classify(AG(EF(Marked(pred))))[0] == "stutter"
    assert classify(Not(EU(Not(Marked(pred)), Marked(pred))))[0] == "stutter"
    assert classify(AF(Marked(pred), semantics="askctl"))[0] == "full"
    assert classify(AG(EF(Dead())))[0] == "full"


def test_a_bound_on_many_places_is_split_per_place():
    net = ColouredNet(CPNNet(os.path.join(NETS, "rf_multiclass.cpn")))
    rc = ReducedChecker(net, Dependency(net))
    parts = split(AG(MaxTokens(Places(), 1)), rc.static)
    assert len(parts) == len(net.places)
    assert all(classify(p)[0] == "safety" for _l, p in parts)


def test_a_stutter_graph_respects_visibility():
    """A transition the property observes is never fired as a lone ample set."""
    net = ColouredNet(CPNNet(os.path.join(NETS, "rf_multiclass.cpn")))
    dep = Dependency(net)
    rc = ReducedChecker(net, dep)
    kind, ss = rc.graph_for(AF(Marked(Places(name="Prediction"))))
    assert kind == "stutter"
    visible = ss.visible
    assert [net.transitions[t]["name"] for t in visible] == ["Vote"]
    reduced = 0
    for v in range(ss.n_nodes):
        expanded = [ti for ti, _k, _d in ss.succ[v]]
        if len(expanded) < len(ss.enabled[v]):
            assert len(expanded) == 1 and expanded[0] not in visible
            reduced += 1
    assert reduced, "nothing was reduced"
    assert ss.n_nodes < build_state_space(net).n_nodes

    # Vote's inputs are written by every leaf: nothing can be reordered.
    kind, ss = rc.graph_for(AF(Enabled(Transitions(name="Vote"))))
    assert ss.n_nodes == build_state_space(net).n_nodes


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

def test_the_report_says_which_graph_decided_each_property():
    result = check_cpn(os.path.join(NETS, "rf_multiclass.cpn"),
                       class_labels=[0, 1, 2], reduction="stubborn")
    text = result.report()
    assert "stubborn sets" in text
    assert "decided on: deadlock" in text
    assert result.stats["reduction"] == "stubborn"
    assert result.oracle == {}


def test_an_unknown_reduction_is_refused():
    mc = CPNModelChecker(os.path.join(NETS, "rf_multiclass.cpn"))
    with pytest.raises(ValueError):
        mc.check(reduction="symmetry")


def test_an_exhausted_budget_gives_no_verdict_and_says_why():
    mc = CPNModelChecker(os.path.join(NETS, "rf_multiclass.cpn"),
                         class_labels=[0, 1, 2])
    result = mc.check(reduction="stubborn", max_nodes=8)
    d2a = result.properties["D2a"]
    assert d2a.holds is None
    assert "cannot be reordered" in d2a.detail
    assert result.properties["A1"].holds is True
