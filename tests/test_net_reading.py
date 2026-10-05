"""Reading real CPN Tools nets: the hierarchy, double arcs, fusion, refusals.

Each construct is checked the same way: a net using it must have exactly the
occurrence graph of the plain net it abbreviates -- a double arc of separate
input and output arcs, a fusion set of one shared place. A construct whose
semantics is not implemented must be refused by name, never read as something
else.
"""

import copy
import os
import xml.etree.ElementTree as ET

import pytest

from cpncheck.coloured import ColouredNet, UnsupportedNet
from cpncheck.net import CPNNet
from cpncheck.statespace import build_state_space

NETS = os.path.join(os.path.dirname(__file__), "nets")
RF = os.path.join(NETS, "rf_multiclass.cpn")


# ---------------------------------------------------------------------------
# A minimal net writer
# ---------------------------------------------------------------------------

def _text(parent, tag, value):
    el = ET.SubElement(parent, tag)
    ET.SubElement(el, "text").text = value
    return el


def write_net(path, pages, colsets=("INT",), variables=("n", "x"),
              instances=True, timed=(), fusion=None, colors=(), typed_vars=None,
              ml=()):
    """Write the parts of a ``.cpn`` file CPNCheck reads.

    ``pages`` maps a page name to ``{"places": [...], "trans": [...],
    "arcs": [...]}``: a place is ``(id, name, colset, initmark or None,
    fusion set or None)``, a transition ``(id, name, guard or None, extras)``
    with ``extras`` a dict of further inscriptions (``code``, ``time``...), an
    arc ``(transition id, place id, orientation, inscription)``. ``colors``
    are extra ``<color>`` elements as XML text, ``typed_vars`` maps a variable
    to its colour set, ``ml`` holds ``val``/``fun`` declarations.
    """
    root = ET.Element("workspaceElements")
    cpnet = ET.SubElement(root, "cpnet")
    globbox = ET.SubElement(cpnet, "globbox")
    for name in colsets:
        color = ET.SubElement(globbox, "color", id=f"c_{name}")
        ET.SubElement(color, "id").text = name
        ET.SubElement(color, "int")
        if name in timed:
            ET.SubElement(color, "timed")
    for i, xml in enumerate(colors):
        globbox.append(ET.fromstring(xml))
    var = ET.SubElement(globbox, "var", id="v1")
    ET.SubElement(ET.SubElement(var, "type"), "id").text = colsets[0]
    for v in variables:
        ET.SubElement(var, "id").text = v
    for i, (v, colset) in enumerate((typed_vars or {}).items()):
        tv = ET.SubElement(globbox, "var", id=f"tv{i}")
        ET.SubElement(ET.SubElement(tv, "type"), "id").text = colset
        ET.SubElement(tv, "id").text = v
    for i, text in enumerate(ml):
        ET.SubElement(globbox, "ml", id=f"ml{i}").text = text
    for pname, page in pages.items():
        pel = ET.SubElement(cpnet, "page", id=f"page_{pname}")
        ET.SubElement(pel, "pageattr", name=pname)
        for pid, name, colset, initmark, fset in page.get("places", []):
            pl = ET.SubElement(pel, "place", id=pid)
            ET.SubElement(pl, "text").text = name
            _text(pl, "type", colset)
            if initmark:
                _text(pl, "initmark", initmark)
            if fset:
                ET.SubElement(pl, "fusioninfo", name=fset)
        for tid, name, guard, extras in page.get("trans", []):
            tr = ET.SubElement(pel, "trans", id=tid)
            ET.SubElement(tr, "text").text = name
            _text(tr, "cond", guard or "")
            for tag, value in (extras or {}).items():
                _text(tr, tag, value)
        for i, (tid, pid, orient, expr) in enumerate(page.get("arcs", [])):
            arc = ET.SubElement(pel, "arc", id=f"{pname}_a{i}",
                                orientation=orient)
            ET.SubElement(arc, "transend", idref=tid)
            ET.SubElement(arc, "placeend", idref=pid)
            _text(arc, "annot", expr)
    if instances:
        inst = ET.SubElement(cpnet, "instances")
        for pname in pages:
            ET.SubElement(inst, "instance", id=f"i_{pname}", page=f"page_{pname}")
    ET.ElementTree(root).write(path, encoding="utf-8")
    return path


def graph(path):
    net = ColouredNet(CPNNet(path))
    return net, build_state_space(net)


def markings_by_name(net, ss):
    """Every reachable marking as ``{place name: tokens}``, order-free."""
    names = [p["name"] for p in net.places]
    return {tuple(sorted((names[i], toks) for i, toks in enumerate(m)))
            for m in ss.markings}


# ---------------------------------------------------------------------------
# Double arcs
# ---------------------------------------------------------------------------

def _counter(orientation_pairs):
    """P holds 1`7 and is only tested; C counts 0..3."""
    return {"Top": {
        "places": [("P", "P", "INT", "1`7", None), ("C", "C", "INT", "1`0", None)],
        "trans": [("T", "Count", "[n < 3]", None)],
        "arcs": [("T", "C", "PtoT", "n"), ("T", "C", "TtoP", "n + 1")]
                + orientation_pairs,
    }}


def test_a_double_arc_takes_and_puts_back(tmp_path):
    double = write_net(str(tmp_path / "double.cpn"),
                       _counter([("T", "P", "BOTHDIR", "x")]))
    separate = write_net(str(tmp_path / "separate.cpn"),
                         _counter([("T", "P", "PtoT", "x"),
                                   ("T", "P", "TtoP", "x")]))
    net_d, ss_d = graph(double)
    net_s, ss_s = graph(separate)
    assert ss_d.n_nodes == ss_s.n_nodes == 4
    assert markings_by_name(net_d, ss_d) == markings_by_name(net_s, ss_s)
    p = next(i for i, pl in enumerate(net_d.places) if pl["name"] == "P")
    assert all(m[p] == (7,) for m in ss_d.markings)


def test_a_double_arc_binds_its_variable(tmp_path):
    """Read as an output only, x would be unbound and the net refused."""
    path = write_net(str(tmp_path / "bind.cpn"), {"Top": {
        "places": [("P", "P", "INT", "1`5", None), ("Q", "Q", "INT", None, None)],
        "trans": [("T", "Copy", None, None)],
        "arcs": [("T", "P", "BOTHDIR", "x"), ("T", "Q", "TtoP", "x")],
    }}, variables=("x",))
    net = ColouredNet(CPNNet(path))
    assert net.enabled(net.initial)


def test_a_double_arc_on_a_real_net_agrees(tmp_path):
    """A tested place added to the forest's Vote changes nothing but itself."""
    tree = ET.parse(RF)
    cpnet = tree.getroot().find("cpnet")
    top = cpnet.find("page")
    template = next(pl for pl in top.iter("place") if pl.findtext("text") == "Input")
    vote = next(tr for tr in top.iter("trans") if tr.findtext("text") == "Vote")
    probe = copy.deepcopy(template)
    probe.set("id", "IDprobe")
    probe.find("text").text = "Probe"
    for i, child in enumerate(probe.iter()):
        if child is not probe and child.get("id"):
            child.set("id", f"IDprobe{i}")
    probe.find("posattr").set("y", "300.000000")
    arc = copy.deepcopy(next(top.iter("arc")))
    arc.set("id", "IDprobearc")
    arc.set("orientation", "BOTHDIR")
    arc.find("transend").set("idref", vote.get("id"))
    arc.find("placeend").set("idref", "IDprobe")
    arc.find("annot").set("id", "IDprobeannot")
    first_arc = list(top).index(next(top.iter("arc")))
    top.insert(first_arc, probe)
    top.append(arc)
    path = str(tmp_path / "rf_probe.cpn")
    tree.write(path, encoding="utf-8", xml_declaration=True)

    _net0, base = graph(RF)
    net, ss = graph(path)
    assert ss.n_nodes == base.n_nodes and ss.n_arcs == base.n_arcs
    p = next(i for i, pl in enumerate(net.places) if pl["name"] == "Probe")
    assert {len(m[p]) for m in ss.markings} == {1}

    if os.environ.get("CPNCHECK_CPNTOOLS") == "1":
        from cpncheck.oracle import CPNToolsOracle, compare_state_space
        oracle = CPNToolsOracle()
        if oracle.missing():
            pytest.skip("CPN Tools engine incomplete")
        report = compare_state_space(path, oracle=oracle)
        assert not report["errors"], report["errors"]
        assert report["agree"], report["rows"]


# ---------------------------------------------------------------------------
# The hierarchy and fusion
# ---------------------------------------------------------------------------

def _two_pages(fset_a="FS", fset_b="FS", mark_b="1`0"):
    return {
        "A": {"places": [("FA", "F", "INT", "1`0", fset_a)],
              "trans": [("TA", "IncA", "[n < 4]", None)],
              "arcs": [("TA", "FA", "PtoT", "n"), ("TA", "FA", "TtoP", "n + 1")]},
        "B": {"places": [("FB", "F", "INT", mark_b, fset_b)],
              "trans": [("TB", "IncB", "[n < 4]", None)],
              "arcs": [("TB", "FB", "PtoT", "n"), ("TB", "FB", "TtoP", "n + 2")]},
    }


def test_every_prime_page_is_part_of_the_model(tmp_path):
    path = write_net(str(tmp_path / "two.cpn"), _two_pages(None, None))
    net, ss = graph(path)
    assert {t["name"] for t in net.transitions} == {"IncA", "IncB"}
    assert len(net.places) == 2
    # Two independent counters: A reaches 0..4, B reaches 0, 2, 4, 6 (n < 4).
    assert ss.n_nodes == 5 * 3


def test_without_instances_the_unreferenced_pages_are_prime(tmp_path):
    path = write_net(str(tmp_path / "noinst.cpn"), _two_pages(None, None),
                     instances=False)
    net = ColouredNet(CPNNet(path))
    assert {t["name"] for t in net.transitions} == {"IncA", "IncB"}


def test_a_fusion_set_is_one_place(tmp_path):
    fused = write_net(str(tmp_path / "fused.cpn"), _two_pages())
    one = write_net(str(tmp_path / "one.cpn"), {"Top": {
        "places": [("F", "F", "INT", "1`0", None)],
        "trans": [("TA", "IncA", "[n < 4]", None), ("TB", "IncB", "[n < 4]", None)],
        "arcs": [("TA", "F", "PtoT", "n"), ("TA", "F", "TtoP", "n + 1"),
                 ("TB", "F", "PtoT", "n"), ("TB", "F", "TtoP", "n + 2")]}})
    net_f, ss_f = graph(fused)
    net_o, ss_o = graph(one)
    assert len(net_f.places) == 1
    assert sorted(m[0] for m in ss_f.markings) == sorted(m[0] for m in ss_o.markings)
    assert ss_f.n_arcs == ss_o.n_arcs


def test_a_fusion_set_with_conflicting_initial_markings_is_refused(tmp_path):
    path = write_net(str(tmp_path / "bad.cpn"), _two_pages(mark_b="1`5"))
    with pytest.raises(UnsupportedNet, match="different initial markings"):
        ColouredNet(CPNNet(path))


def test_names_lose_their_line_breaks(tmp_path):
    path = write_net(str(tmp_path / "names.cpn"), {"Top": {
        "places": [("P", "Packets\nTo Send", "INT", "1`1", None)],
        "trans": [("T", "Send\n  Packet", None, None)],
        "arcs": [("T", "P", "PtoT", "x")]}}, variables=("x",))
    net = ColouredNet(CPNNet(path))
    assert net.places[0]["name"] == "Packets To Send"
    assert net.transitions[0]["name"] == "Send Packet"


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

def _single(extras=None, timed=()):
    return dict(pages={"Top": {
        "places": [("P", "P", "INT", "1`1", None)],
        "trans": [("T", "T", None, extras)],
        "arcs": [("T", "P", "PtoT", "x")]}}, variables=("x",), timed=timed)


@pytest.mark.parametrize("kwargs,reason", [
    (_single(timed=("INT",)), "timed nets"),
    (_single({"time": "@+5"}), "time inscription"),
    (_single({"code": "input (x); action print (Int.toString x);"}),
     "code segments"),
    (_single({"priority": "P_HIGH"}), "priority"),
    (_single({"channel": "ch !! x"}), "synchronous channels"),
])
def test_unsupported_constructs_are_refused_by_name(tmp_path, kwargs, reason):
    path = write_net(str(tmp_path / "x.cpn"), **kwargs)
    with pytest.raises(UnsupportedNet, match=reason):
        ColouredNet(CPNNet(path))


def test_the_default_priority_is_accepted(tmp_path):
    path = write_net(str(tmp_path / "p.cpn"), **_single({"priority": "P_NORMAL"}))
    assert ColouredNet(CPNNet(path)).transitions
