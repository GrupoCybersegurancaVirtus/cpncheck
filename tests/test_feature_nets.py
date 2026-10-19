"""Constructs whose meaning was measured in CPN Tools, not assumed.

Each net in ``tests/nets/features`` isolates one construct whose semantics
CPN Tools' documentation leaves open, and the figures below are what CPN
Tools 4.0.1 computes for it:

* inhibitor arcs (``inh_*``): the transition needs the place *empty*,
  whatever multiset the inscription names;
* reset arcs (``reset_*``): firing empties the place, whatever the
  inscription;
* lists on arcs of non-list places (``list_ms``): ``[a, b]`` and
  ``map f (E.all ())`` are multisets, since ``'a ms`` is ``'a list``;
* ``x @+ d`` on an *input* arc (``in_*``): a token stamped ``s`` may be
  taken from ``s - d`` on.

With ``CPNCHECK_CPNTOOLS=1`` the same nets are compared with CPN Tools live.
"""

import os

import pytest

from cpncheck.coloured import CPNTOOLS_401, ColouredNet, UnsupportedNet
from cpncheck.net import CPNNet
from cpncheck.statespace import build_state_space

from test_net_reading import write_net

NETS = os.path.join(os.path.dirname(__file__), "nets", "features")

#: (nodes, arcs, dead markings) as CPN Tools 4.0.1 computed them.
CPNTOOLS = {
    "inh_w1_tok1": (5, 4, 1),
    "inh_w2_tok1": (5, 4, 1),
    "inh_w2_tok2": (6, 5, 1),
    "reset_w1_tok2": (12, 11, 3),
    "reset_w2_tok1": (8, 7, 2),
    "list_ms": (8, 12, 1),
    "in_plain": (2, 1, 1),
    "in_delay4": (2, 1, 1),
    "in_delay15": (2, 1, 1),
    "in_two": (3, 2, 1),
}


# Function to build a net's occurrence graph.
def _graph(name):
    net = ColouredNet(CPNNet(os.path.join(NETS, f"{name}.cpn")))
    return net, build_state_space(net)


@pytest.mark.parametrize("name", sorted(CPNTOOLS))
def test_the_graph_is_the_one_cpntools_computes(name):
    _net, ss = _graph(name)
    assert (ss.n_nodes, ss.n_arcs, len(ss.dead)) == CPNTOOLS[name]


def test_an_input_arc_delay_takes_tokens_early():
    net, ss = _graph("in_delay4")
    # The token stamped 10 is taken at 6 (10 - 4) and put back unstamped.
    assert [str(m) for m in ss.markings] == ["((7@10,), (), 0)",
                                             "((), (7@6,), 6)"]
    net, ss = _graph("in_delay15")
    assert ss.markings[1][-1] == 0            # never before the clock


def test_lists_on_arcs_are_multisets_unless_the_place_holds_lists():
    net = ColouredNet(CPNNet(os.path.join(NETS, "list_ms.cpn")))
    names = [p["name"] for p in net.places]
    m0 = dict(zip(names, net.initial))
    assert len(m0["Src"]) == 2                  # [a, b] on a place of E
    assert len(m0["Lst"]) == 1                  # [a, b] on a place of list E


def test_inhibitor_and_reset_arcs_disable_reduction():
    net, _ss = _graph("inh_w1_tok1")
    assert net.special_arcs and not net.reducible


@pytest.mark.parametrize("orient", ["Inhibitor", "Reset", "PtoT", "TtoP"])
def test_an_arc_without_inscription_is_refused_by_name(tmp_path, orient):
    path = write_net(str(tmp_path / "e.cpn"), {"Top": {
        "places": [("C", "C", "INT", "1`0", None), ("H", "H", "INT", "1`1", None)],
        "trans": [("T", "Tick", "[n < 2]", None)],
        "arcs": [("T", "C", "PtoT", "n"), ("T", "C", "TtoP", "n + 1"),
                 ("T", "H", orient, "")]}})
    with pytest.raises(UnsupportedNet, match="does not compile the transition"):
        ColouredNet(CPNNet(path))


def test_a_transition_without_input_arcs_is_a_source(tmp_path):
    path = write_net(str(tmp_path / "s.cpn"), {"Top": {
        "places": [("C", "C", "INT", "1`0", None)],
        "trans": [("T", "Gen", None, None)],
        "arcs": [("T", "C", "TtoP", "1")]}})
    net = ColouredNet(CPNNet(path))
    assert not net.reducible
    assert [net.transitions[ti]["name"] for ti, _k, _e in net.enabled(net.initial)]         == ["Gen"]
    ss = build_state_space(net, max_nodes=200)
    # Gen keeps adding a token: the graph is infinite, and stops at the
    # budget rather than being refused.
    assert not ss.complete


@pytest.mark.skipif(os.environ.get("CPNCHECK_CPNTOOLS") != "1",
                    reason="set CPNCHECK_CPNTOOLS=1 to compare with CPN Tools")
@pytest.mark.parametrize("name", sorted(CPNTOOLS))
def test_cpntools_agrees_live(name):
    from cpncheck.oracle import (CPNToolsOracle, compare_graph_containment,
                                 compare_state_space)

    oracle = CPNToolsOracle()
    if oracle.missing():
        pytest.skip("CPN Tools engine incomplete")
    path = os.path.join(NETS, f"{name}.cpn")
    if name.startswith("in_"):
        report = compare_graph_containment(path, oracle=oracle, timeout=300,
                                           compat=CPNTOOLS_401)
        assert report["contained"], report
    else:
        report = compare_state_space(path, oracle=oracle, timeout=300)
        assert report["agree"], report["rows"]
