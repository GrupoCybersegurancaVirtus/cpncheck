"""The generic layer: selectors, formulas, profiles and ASK-CTL rendering.

These tests use the fixture nets, but none of them go through the tree
profile's catalog: they state properties by hand, and one of them drives the
whole checker with a profile written inside the test. That is the claim the
extraction has to support -- that a caller can verify their own nets without
touching the checker.
"""

import collections
import os

import pytest

from cpncheck import CPNModelChecker
from cpncheck.askctl import MLProgram, UnsupportedFormula
from cpncheck.coloured import ColouredNet
from cpncheck.formula import (AF, AG, EF, AllMarked, And, Context, Dead,
                              Enabled, EnabledCount, Implies, Marked,
                              MaxTokens, Not, Or, TokensIn)
from cpncheck.net import CPNNet
from cpncheck.profile import Profile, detect
from cpncheck.properties import Property
from cpncheck.selectors import Explicit, Places, Transitions, outputs_of

NETS = os.path.join(os.path.dirname(__file__), "nets")
GBDT = os.path.join(NETS, "gbdt_binary.cpn")
RF = os.path.join(NETS, "rf_multiclass.cpn")


@pytest.fixture(scope="module")
def net():
    return ColouredNet(CPNNet(GBDT))


# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------

def test_selectors_resolve_by_name_page_and_pattern(net):
    top = net.top["name"]
    pred = Places(name="Prediction", page=top).resolve(net)
    assert len(pred) == 1
    assert net.places[pred[0]]["name"] == "Prediction"

    everything = Places().resolve(net)
    assert len(everything) == len(net.places)

    leaves = Transitions(page_re=r"Tree.*").resolve(net)
    assert leaves and all(net.transitions[t]["page"].startswith("Tree")
                          for t in leaves)

    assert Places(name="NoSuchPlace").resolve(net) == ()


def test_outputs_of_follows_the_arcs(net):
    leaves = Transitions(page_re=r"Tree_c1_s1")
    outs = outputs_of(net, leaves.resolve(net))
    assert outs
    assert all(isinstance(p, int) for p in outs)


def test_a_selector_describes_itself(net):
    assert Places(name="Prediction").describe(net) == "Prediction"
    assert "places" in Places().describe(net)
    assert Explicit((), "place", "nothing at all").describe(net) == \
        "nothing at all"


# ---------------------------------------------------------------------------
# Formulas
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ctx(net):
    from cpncheck.statespace import build_state_space
    return Context(build_state_space(net), net)


def test_hand_written_formulas_agree_with_the_catalog(ctx):
    """The same properties, stated by hand, give the same verdicts."""
    pred = Places(name="Prediction", page=ctx.net.top["name"])
    assert 0 in ctx.sat(AF(Dead()))                        # A1
    assert 0 in ctx.sat(AF(Marked(pred)))                  # A3
    assert 0 in ctx.sat(AG(EF(Marked(pred))))              # A4
    assert 0 in ctx.sat(AG(MaxTokens(pred, 1)))            # A5
    assert 0 in ctx.sat(AG(MaxTokens(Places(), 1)))        # A7


def test_a_false_formula_explains_itself(ctx):
    phi = AG(MaxTokens(Places(name="Prediction"), 0))
    assert 0 not in ctx.sat(phi)
    detail = phi.explain(ctx)
    assert "holds 1 tokens" in detail and "after:" in detail


def test_af_explains_with_an_occurrence_sequence(ctx):
    phi = AF(Marked(Places(name="Prediction"), note="the impossible"))
    unreachable = AF(Marked(Places(name="NoSuchPlace"), note="the impossible"))
    assert 0 in ctx.sat(phi)
    assert 0 not in ctx.sat(unreachable)
    assert "never happens on:" in unreachable.explain(ctx)


def test_boolean_connectives(ctx):
    pred = Places(name="Prediction")
    everywhere = Or(Marked(pred), Not(Marked(pred)))
    nowhere = And(Marked(pred), Not(Marked(pred)))
    assert ctx.sat(everywhere) == ctx.all
    assert ctx.sat(nowhere) == frozenset()
    assert ctx.sat(Implies(Dead(), Dead())) == ctx.all


def test_tokens_in_a_domain(ctx):
    pred = Places(name="Prediction")
    assert 0 in ctx.sat(AG(TokensIn(pred, [0, 1])))
    bad = AG(TokensIn(pred, [7]))
    assert 0 not in ctx.sat(bad)
    assert "outside [7]" in bad.explain(ctx)


def test_enabled_counts_arcs_not_transitions(ctx):
    leaves = Transitions(page_re=r"Tree.*")
    assert 0 in ctx.sat(AG(EnabledCount(leaves, 3)))
    assert 0 in ctx.sat(EF(Enabled(leaves)))


# ---------------------------------------------------------------------------
# ASK-CTL rendering
# ---------------------------------------------------------------------------

def test_every_catalog_formula_renders_to_askctl():
    for path, labels in ((GBDT, [0, 1]), (RF, [0, 1, 2])):
        mc = CPNModelChecker(path, class_labels=labels)
        decl, queries = mc.ml_program()
        assert set(queries) >= set(mc.formulas)
        for pid in mc.formulas:
            assert queries[pid].startswith("Bool.toString (eval_node")
        assert "val DEAD" in decl and "fun AFmax" in decl


def test_the_generated_program_asks_about_every_property():
    """Every property the checker answers is also asked of CPN Tools.

    That the two engines then give the same answers is what ``cpncheck
    oracle`` establishes; see tests/test_oracle.py.
    """
    for path, labels in ((GBDT, [0, 1]), (RF, [0, 1, 2])):
        mc = CPNModelChecker(path, class_labels=labels)
        queries = mc.ml_program()[1]
        assert set(mc.property_ids) <= set(queries)
        assert set(queries) <= set(mc.check().oracle)


def test_askctl_uses_ev_only_for_the_askctl_reading(net):
    ctx = Context.static(net)
    prog = MLProgram(net)
    phi = AF(Marked(Places(name="Prediction")))
    assert prog.render(phi, ctx, "textbook").startswith("AFmax")
    assert prog.render(phi, ctx, "askctl").startswith("EV(")


def test_an_empty_transition_group_is_refused(net):
    with pytest.raises(UnsupportedFormula):
        MLProgram(net).render(Enabled(Transitions(name="NoSuchTransition")),
                              Context.static(net))


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

def test_the_tree_profile_is_detected(net):
    profile = detect(net)
    assert profile is not None and profile.name == "ml_trees"


def test_a_profile_written_here_drives_the_whole_checker():
    """A caller's own profile, with its own property ids, verifies their net."""
    my_catalog = collections.OrderedDict()
    for spec in (
        Property("T1", "It stops", "AF dead", "desired", (), "No cycles.",
                 method="ctl"),
        Property("T2", "One output", "AG |Prediction| <= 1", "undesired", (),
                 "Never two results.", method="ctl"),
        Property("T3", "Reaches an end", "one terminal SCC", "desired", (),
                 "A home marking exists.", method="scc"),
    ):
        my_catalog[spec.id] = spec

    class MyProfile(Profile):
        name = "written in a test"
        catalog = my_catalog

        def matches(self, net):
            return True

        def ctl_formulas(self, net, groups, labels):
            out = collections.OrderedDict()
            out["T1"] = AF(Dead().phrased("the end"))
            out["T2"] = AG(MaxTokens(Places(name="Prediction"), 1))
            return out

        def scc_properties(self, net, groups):
            return collections.OrderedDict((("T3", "home"),))

    result = CPNModelChecker(GBDT, profile=MyProfile()).check()
    assert result.passed, result.report()
    assert list(result.properties) == ["T1", "T2", "T3"]
    assert result.family == "written in a test"
    assert "It stops" in result.report()
    assert result.to_dict()["properties"]["T1"]["formula"] == "AF dead"


def test_a_profile_can_fail_and_say_why():
    x_catalog = collections.OrderedDict(
        (("X1", Property("X1", "Impossible", "AG false", "desired", (),
                         "Cannot hold.", method="ctl")),))

    class Impossible(Profile):
        name = "impossible"
        catalog = x_catalog

        def matches(self, net):
            return True

        def ctl_formulas(self, net, groups, labels):
            return collections.OrderedDict(
                (("X1", AG(MaxTokens(Places(name="Prediction"), 0))),))

    result = CPNModelChecker(GBDT, profile=Impossible()).check()
    assert not result.passed
    assert result.properties["X1"].detail
    assert "VIOLATION FOUND" in result.report()


def test_an_unrecognised_net_is_refused(tmp_path, monkeypatch):
    import cpncheck.profile as P
    monkeypatch.setattr(P, "_REGISTRY", [])
    from cpncheck.coloured import UnsupportedNet
    with pytest.raises(UnsupportedNet):
        CPNModelChecker(GBDT)
