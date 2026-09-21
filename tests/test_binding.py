"""Binding elements: what a transition can do, not just what its arcs match.

A transition's variables need not all come from its input arcs. CPN Tools
enumerates the rest over their colour sets, and a checker that does not is
looking at a strictly smaller net than the one on screen -- it would miss
behaviour rather than report it.

The nets here are built by injecting a variable into a fixture, because the
generated nets have no free variables at all: that is exactly the case that
used to be impossible to check.
"""

import os
import shutil
import xml.etree.ElementTree as ET

import pytest

from cpncheck.coloured import ColouredNet, UnsupportedNet
from cpncheck.net import CPNNet
from cpncheck.statespace import build_state_space

NETS = os.path.join(os.path.dirname(__file__), "nets")
GBDT = os.path.join(NETS, "gbdt_binary.cpn")


def _with_variable(tmp_path, name, colset, guard=None, transition=None):
    """Copy the fixture, declare a variable, and optionally guard a transition.

    Args:
        tmp_path: The pytest temporary directory.
        name (str): The variable to declare.
        colset (str): Its colour set.
        guard (str, optional): A guard to install.
        transition (str, optional): The transition to guard; the first one on
            the top page when omitted.

    Returns:
        str: The path of the edited net.
    """
    path = str(tmp_path / f"with_{name}.cpn")
    shutil.copy(GBDT, path)
    tree = ET.parse(path)
    root = tree.getroot()
    block = root.findall(".//globbox/block")[-1]
    var = ET.SubElement(block, "var", {"id": f"VAR_{name}"})
    type_el = ET.SubElement(var, "type")
    ET.SubElement(type_el, "id").text = colset
    ET.SubElement(var, "id").text = name
    ET.SubElement(var, "layout").text = f"var {name}: {colset};"

    if guard is not None:
        page = root.find(".//page")
        for element in page.findall("trans"):
            found = element.find("text")
            if transition and (found is None or found.text != transition):
                continue
            cond = element.find("cond")
            if cond is None:
                cond = ET.SubElement(element, "cond")
            text = cond.find("text")
            if text is None:
                text = ET.SubElement(cond, "text")
            text.text = guard
            break
    tree.write(path, encoding="iso-8859-1", xml_declaration=True)
    return path


def _first_top_transition(net):
    top = net.top["name"]
    return next(t for t in net.transitions if t["page"] == top)


# ---------------------------------------------------------------------------
# Enumeration over a finite colour set
# ---------------------------------------------------------------------------

def test_a_free_variable_is_enumerated_over_its_colour_set(tmp_path):
    """Two values of BOOL means two binding elements, not one."""
    plain = ColouredNet(CPNNet(GBDT))
    before = len(plain.enabled(plain.initial))

    path = _with_variable(tmp_path, "flag", "BOOL", guard="[flag orelse true]")
    net = ColouredNet(CPNNet(path))
    guarded = _first_top_transition(net)
    assert guarded["free_vars"] == ["flag"]
    assert len(guarded["domains"][0][1]) == 2

    bindings = [env for ti, _k, env in net.enabled(net.initial)
                if net.transitions[ti] is guarded]
    assert len(bindings) == 2
    assert {b["flag"] for b in bindings} == {False, True}
    assert len(net.enabled(net.initial)) == before + 1


def test_the_guard_filters_the_enumerated_bindings(tmp_path):
    path = _with_variable(tmp_path, "flag", "BOOL", guard="[flag]")
    net = ColouredNet(CPNNet(path))
    guarded = _first_top_transition(net)
    bindings = [env for ti, _k, env in net.enabled(net.initial)
                if net.transitions[ti] is guarded]
    assert len(bindings) == 1
    assert bindings[0]["flag"] is True


def test_the_extra_bindings_reach_the_occurrence_graph(tmp_path):
    """A binding element that changes nothing still is one, and is explored."""
    plain = build_state_space(ColouredNet(CPNNet(GBDT)))
    path = _with_variable(tmp_path, "flag", "BOOL", guard="[flag orelse true]")
    wider = build_state_space(ColouredNet(CPNNet(path)))
    assert wider.n_nodes == plain.n_nodes          # the same markings...
    assert wider.n_arcs == plain.n_arcs + 1        # ...reached two ways


def test_a_unit_variable_adds_exactly_one_binding(tmp_path):
    path = _with_variable(tmp_path, "u", "UNIT", guard="[u = ()]")
    net = ColouredNet(CPNNet(path))
    guarded = _first_top_transition(net)
    bindings = [env for ti, _k, env in net.enabled(net.initial)
                if net.transitions[ti] is guarded]
    assert len(bindings) == 1 and bindings[0]["u"] == ()


# ---------------------------------------------------------------------------
# What cannot be enumerated is refused, not ignored
# ---------------------------------------------------------------------------

def test_a_free_variable_over_an_infinite_colour_set_is_refused(tmp_path):
    path = _with_variable(tmp_path, "r", "REAL", guard="[r > 0.0]")
    with pytest.raises(UnsupportedNet) as caught:
        ColouredNet(CPNNet(path))
    assert "r" in str(caught.value) and "REAL" in str(caught.value)


def test_an_undeclared_variable_is_refused(tmp_path):
    path = _with_variable(tmp_path, "unused", "BOOL", guard="[mystery]")
    with pytest.raises(UnsupportedNet) as caught:
        ColouredNet(CPNNet(path))
    assert "mystery" in str(caught.value)
    assert "not declared" in str(caught.value)


def test_a_declared_value_is_not_mistaken_for_a_free_variable(tmp_path):
    """P_HIGH is declared in the net; it needs no enumeration."""
    path = _with_variable(tmp_path, "unused", "BOOL",
                          guard="[P_HIGH > 0]")
    net = ColouredNet(CPNNet(path))
    assert _first_top_transition(net)["free_vars"] == []
    assert net.enabled(net.initial)
