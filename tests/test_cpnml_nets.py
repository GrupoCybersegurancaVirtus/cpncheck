"""More of CPN ML, on nets: multisets, expression arcs, constants, colour sets.

Every construct here appears in CPN Tools' own example models; the samples
that use them are compared with CPN Tools by ``tests/test_cpntools_samples.py``
(with ``CPNCHECK_CPNTOOLS=1``). These tests pin each construct down on a small
net where the right answer is known, including the two places where a wrong
reading would be silent: a constant in a pattern must match that constant
only, and a subset must not range over its whole base.
"""

import os

import pytest

from cpncheck.coloured import ColouredNet, UnsupportedNet
from cpncheck.cpnml import EnumValue, IndexValue, MultiSet
from cpncheck.net import CPNNet
from cpncheck.statespace import build_state_space

from test_net_reading import write_net

ENUM_E = '<color id="cE"><id>E</id><enum><id>a</id><id>b</id><id>c</id></enum></color>'
INDEX_U = ('<color id="cU"><id>U</id><index><ml>1</ml><ml>NoOfU</ml>'
           '<id>u</id></index></color>')
PAIR = '<color id="cP"><id>P</id><product><id>U</id><id>U</id></product></color>'
DIFF = ('<color id="cD"><id>D</id><subset><id>P</id><by><ml>diff</ml></by>'
        '</subset></color>')


def net(tmp_path, pages, **kw):
    return ColouredNet(CPNNet(write_net(str(tmp_path / "n.cpn"), pages, **kw)))


def tokens(cn, marking, name):
    return marking[next(i for i, p in enumerate(cn.places) if p["name"] == name)]


# ---------------------------------------------------------------------------
# Multisets
# ---------------------------------------------------------------------------

def test_a_multiset_inside_an_if_is_a_value(tmp_path):
    """then 1`x else empty: produce the token or nothing."""
    cn = net(tmp_path, {"Top": {
        "places": [("P", "P", "INT", "1`1 ++ 1`2 ++ 1`3", None),
                   ("Q", "Even", "INT", None, None)],
        "trans": [("T", "Filter", None, None)],
        "arcs": [("T", "P", "PtoT", "x"),
                 ("T", "Q", "TtoP", "if x mod 2 = 0 then 1`x else empty")]}},
        variables=("x",))
    ss = build_state_space(cn)
    finals = {tokens(cn, ss.markings[v], "Even") for v in ss.dead}
    assert finals == {(2,)}


def test_coefficients_and_sums_on_arcs_and_markings(tmp_path):
    cn = net(tmp_path, {"Top": {
        "places": [("P", "P", "INT", "2`5 ++ 1`6", None),
                   ("Q", "Q", "INT", None, None)],
        "trans": [("T", "Double", None, None)],
        "arcs": [("T", "P", "PtoT", "x"), ("T", "Q", "TtoP", "2`x ++ 1`(x+1)")]}},
        variables=("x",))
    assert tokens(cn, cn.initial, "P") == (5, 5, 6)
    ss = build_state_space(cn)
    finals = {tokens(cn, ss.markings[v], "Q") for v in ss.dead}
    assert finals == {(5, 5, 5, 5, 6, 6, 6, 6, 7)}


# ---------------------------------------------------------------------------
# Input arcs that are expressions
# ---------------------------------------------------------------------------

def test_an_input_expression_takes_what_it_evaluates_to(tmp_path):
    """Take x from P and, only when x is even, also 1`x from R."""
    cn = net(tmp_path, {"Top": {
        "places": [("P", "P", "INT", "1`1 ++ 1`2", None),
                   ("R", "R", "INT", "1`2", None)],
        "trans": [("T", "Take", None, None)],
        "arcs": [("T", "P", "PtoT", "x"),
                 ("T", "R", "PtoT", "if x mod 2 = 0 then 1`x else empty")]}},
        variables=("x",))
    fired = {env["x"]: cn.fire(cn.initial, ti, env)
             for ti, _k, env in cn.enabled(cn.initial)}
    assert set(fired) == {1, 2}
    assert tokens(cn, fired[1], "R") == (2,)        # took nothing from R
    assert tokens(cn, fired[2], "R") == ()          # took 1`2


def test_an_input_expression_disables_when_the_tokens_are_missing(tmp_path):
    cn = net(tmp_path, {"Top": {
        "places": [("P", "P", "INT", "1`4", None), ("R", "R", "INT", "1`9", None)],
        "trans": [("T", "Take", None, None)],
        "arcs": [("T", "P", "PtoT", "x"), ("T", "R", "PtoT", "1`x")]}},
        variables=("x",))
    assert cn.enabled(cn.initial) == []


def test_an_input_expression_calling_a_declared_function(tmp_path):
    cn = net(tmp_path, {"Top": {
        "places": [("P", "P", "INT", "1`3", None),
                   ("R", "R", "INT", "1`3 ++ 1`4 ++ 1`5", None)],
        "trans": [("T", "Neighbours", None, None)],
        "arcs": [("T", "P", "PtoT", "x"), ("T", "R", "PtoT", "Next(x)")]}},
        variables=("x",), ml=("fun Next(x) = 1`(x+1) ++ 1`(x+2);",))
    (ti, _k, env), = cn.enabled(cn.initial)
    assert tokens(cn, cn.fire(cn.initial, ti, env), "R") == (3,)


# ---------------------------------------------------------------------------
# Enumeration constants
# ---------------------------------------------------------------------------

def test_a_constant_in_a_pattern_matches_that_constant_only(tmp_path):
    """Read as a variable, 'a' would match the b token and enable the arc."""
    cn = net(tmp_path, {"Top": {
        "places": [("P", "P", "E", "1`b", None), ("Q", "Q", "E", None, None)],
        "trans": [("T", "TakeA", None, None)],
        "arcs": [("T", "P", "PtoT", "a"), ("T", "Q", "TtoP", "a")]}},
        colsets=("INT",), colors=(ENUM_E,), variables=("x",))
    assert tokens(cn, cn.initial, "P") == (EnumValue("b"),)
    assert cn.enabled(cn.initial) == []


def test_a_variable_over_an_enumeration_is_enumerated(tmp_path):
    cn = net(tmp_path, {"Top": {
        "places": [("S", "Start", "INT", "1`0", None), ("Q", "Q", "E", None, None)],
        "trans": [("T", "Pick", None, None)],
        "arcs": [("T", "S", "PtoT", "n"), ("T", "Q", "TtoP", "e")]}},
        colors=(ENUM_E,), variables=("n",), typed_vars={"e": "E"})
    assert {env["e"] for _t, _k, env in cn.enabled(cn.initial)} == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# Index colour sets, products and subsets
# ---------------------------------------------------------------------------

def test_index_values_constructors_and_all(tmp_path):
    cn = net(tmp_path, {"Top": {
        "places": [("P", "P", "U", "U.all()", None), ("Q", "Q", "INT", None, None)],
        "trans": [("T", "Unwrap", None, None)],
        "arcs": [("T", "P", "PtoT", "u(i)"), ("T", "Q", "TtoP", "i")]}},
        colors=(INDEX_U,), variables=("i",), ml=("val NoOfU = 3;",))
    assert tokens(cn, cn.initial, "P") == tuple(IndexValue("u", i)
                                                for i in (1, 2, 3))
    ss = build_state_space(cn)
    finals = {tokens(cn, ss.markings[v], "Q") for v in ss.dead}
    assert finals == {(1, 2, 3)}


def test_a_subset_by_predicate_ranges_over_its_members_only(tmp_path):
    """Ranging over the whole product would also produce (u(i), u(i))."""
    cn = net(tmp_path, {"Top": {
        "places": [("S", "Start", "INT", "1`0", None), ("Q", "Q", "D", None, None)],
        "trans": [("T", "Pick", None, None)],
        "arcs": [("T", "S", "PtoT", "n"), ("T", "Q", "TtoP", "d")]}},
        colors=(INDEX_U, PAIR, DIFF), variables=("n",), typed_vars={"d": "D"},
        ml=("val NoOfU = 3;", "fun diff(x,y) = (x<>y);"))
    picked = {env["d"] for _t, _k, env in cn.enabled(cn.initial)}
    assert len(picked) == 6
    assert all(x != y for x, y in picked)


def test_a_subset_that_cannot_be_evaluated_has_no_domain(tmp_path):
    with pytest.raises(UnsupportedNet, match="not finite"):
        net(tmp_path, {"Top": {
            "places": [("S", "Start", "INT", "1`0", None),
                       ("Q", "Q", "D", None, None)],
            "trans": [("T", "Pick", None, None)],
            "arcs": [("T", "S", "PtoT", "n"), ("T", "Q", "TtoP", "d")]}},
            colors=(INDEX_U, PAIR, DIFF), variables=("n",),
            typed_vars={"d": "D"}, ml=("val NoOfU = 3;",))   # no diff declared


def test_product_mult_multiplies_multisets(tmp_path):
    cn = net(tmp_path, {"Top": {
        "places": [("P", "P", "P", "P.mult(1`u(1) ++ 1`u(2), 2`u(3))", None)],
        "trans": [], "arcs": []}},
        colors=(INDEX_U, PAIR), variables=("n",), ml=("val NoOfU = 3;",))
    assert tokens(cn, cn.initial, "P") == (
        (IndexValue("u", 1), IndexValue("u", 3)),) * 2 + (
        (IndexValue("u", 2), IndexValue("u", 3)),) * 2


def test_list_concatenation():
    from cpncheck.cpnml import PRELUDE, compile_expression, parse_expression
    code = compile_expression(parse_expression("[1, 2] ^^ [3]"), PRELUDE)
    assert code({}) == (1, 2, 3)


def test_multiset_difference_requires_containment():
    from cpncheck.cpnml import (PRELUDE, MLError, compile_expression,
                                parse_expression)
    ok = compile_expression(parse_expression("2`1 ++ 1`2 -- 1`1"), PRELUDE)
    assert ok({}) == MultiSet({1: 1, 2: 1})
    bad = compile_expression(parse_expression("1`1 -- 1`2"), PRELUDE)
    with pytest.raises(MLError):
        bad({})
