"""Guard boxes and conformance, the two techniques that are not CTL.

Neither needs an occurrence graph, and neither is specific to any family of
nets: the first asks whether two guards can hold together for *any* input, the
second runs the net on concrete inputs and compares with a reference.
"""

import os

import pytest

from cpncheck.coloured import ColouredNet
from cpncheck.conformance import check_conformance, projection, terminal_marking
from cpncheck.net import CPNNet
from cpncheck.profiles.ml_trees import MLTreeProfile
from cpncheck.structural import (WHOLE, boxes_intersect, guard_box,
                                 overlapping_guards)

NETS = os.path.join(os.path.dirname(__file__), "nets")
GBDT = os.path.join(NETS, "gbdt_binary.cpn")


@pytest.fixture(scope="module")
def net():
    return ColouredNet(CPNNet(GBDT))


# ---------------------------------------------------------------------------
# Guard boxes
# ---------------------------------------------------------------------------

def test_a_conjunction_of_bounds_becomes_a_box():
    box = guard_box("[#f0 x <= 3.0 andalso #f1 x > 1.5]")
    assert set(box) == {("x", "f0"), ("x", "f1")}
    lo, lo_open, hi, hi_open = box[("x", "f0")]
    assert (lo, hi, hi_open) == (float("-inf"), 3.0, False)
    lo, lo_open, hi, hi_open = box[("x", "f1")]
    assert (lo, lo_open, hi) == (1.5, True, float("inf"))


def test_sml_negation_and_exponents_are_understood():
    box = guard_box("#f0 x <= ~2.5E~3")
    assert box[("x", "f0")].high == pytest.approx(-2.5e-3)


def test_a_bare_variable_needs_no_record_field():
    box = guard_box("y > 4")
    assert set(box) == {("y", None)}
    assert box[("y", None)].low == 4.0


def test_a_mirrored_comparison_is_flipped():
    assert guard_box("3.0 < #f0 x") == guard_box("#f0 x > 3.0")
    assert guard_box("3.0 >= y") == guard_box("y <= 3.0")


def test_an_always_true_guard_is_the_whole_space():
    assert guard_box("") == {}
    assert guard_box("[true]") == {}


def test_a_guard_outside_the_shape_is_unknown_not_unsatisfiable():
    assert guard_box("[not (#f0 x <= 3.0)]") is None
    assert guard_box("[#f0 x <= 3.0 orelse #f1 x > 1.0]") is None
    assert guard_box("[f (x) <= 3.0]") is None


def test_repeated_bounds_on_one_field_narrow_it():
    box = guard_box("#f0 x <= 5.0 andalso #f0 x <= 2.0 andalso #f0 x > 1.0")
    assert (box[("x", "f0")].low, box[("x", "f0")].high) == (1.0, 2.0)


# ---------------------------------------------------------------------------
# Intersection, including the closed endpoints the old test could not see
# ---------------------------------------------------------------------------

def test_disjoint_and_overlapping_boxes():
    a = guard_box("#f0 x <= 3.0")
    b = guard_box("#f0 x > 3.0")
    c = guard_box("#f0 x > 1.0")
    assert not boxes_intersect(a, b)
    assert boxes_intersect(a, c)
    assert boxes_intersect(a, {})            # an unconstrained guard meets all


def test_a_single_shared_point_counts_as_an_overlap():
    """`x >= 3` and `x <= 3` both admit 3; treating >= as > would miss it."""
    assert boxes_intersect(guard_box("y >= 3"), guard_box("y <= 3"))
    assert not boxes_intersect(guard_box("y > 3"), guard_box("y <= 3"))
    assert not boxes_intersect(guard_box("y >= 3"), guard_box("y < 3"))


def test_a_field_constrained_in_only_one_box_never_separates_them():
    assert boxes_intersect(guard_box("#f0 x <= 1.0"), guard_box("#f1 x <= 1.0"))


def test_disjointness_needs_only_one_field_to_disagree():
    a = guard_box("#f0 x <= 1.0 andalso #f1 x <= 9.0")
    b = guard_box("#f0 x > 2.0 andalso #f1 x <= 9.0")
    assert not boxes_intersect(a, b)


# ---------------------------------------------------------------------------
# Over a whole net
# ---------------------------------------------------------------------------

def test_the_leaves_of_a_correct_net_are_disjoint(net):
    groups = {label: roles["leaves"] for label, roles
              in MLTreeProfile().resolve_groups(net)["trees"].items()}
    found, unparsed = overlapping_guards(
        net, groups, ignore=lambda n: n.endswith("_default"))
    assert found == []
    assert unparsed == 0


def test_pairs_are_only_formed_inside_a_group(net):
    """Two branches of different choices may of course both be enabled."""
    everything = {label: roles["leaves"] for label, roles
                  in MLTreeProfile().resolve_groups(net)["trees"].items()}
    merged = {"all of them": [ti for g in everything.values() for ti in g]}
    apart, _ = overlapping_guards(net, everything,
                                  ignore=lambda n: n.endswith("_default"))
    together, _ = overlapping_guards(net, merged,
                                     ignore=lambda n: n.endswith("_default"))
    assert apart == [] and together != []


def test_an_unparsable_guard_is_counted_not_guessed(net):
    groups = {"one tree": [ti for ti, t in enumerate(net.transitions)
                           if t["page"] == "Tree_c1_s1"]}
    _found, unparsed = overlapping_guards(net, groups)
    assert unparsed == 1                      # the catch-all, when not ignored


# ---------------------------------------------------------------------------
# Conformance
# ---------------------------------------------------------------------------

def test_a_run_reaches_a_marking_holding_the_result(net):
    profile = MLTreeProfile()
    structure = profile.structure(net)
    final = terminal_marking(net)
    assert projection(final, (structure.pred,))


def test_conformance_agrees_with_the_net_itself(net):
    """A reference that is the net cannot disagree with it."""
    profile = MLTreeProfile()
    structure = profile.structure(net)
    inputs = [net.initial[structure.input][0]]
    mine = [projection(terminal_marking(net, x, (structure.input,)),
                       (structure.pred,))[0] for x in inputs]
    result = check_conformance(net, inputs, lambda batch: mine,
                               input_places=(structure.input,),
                               output_places=(structure.pred,))
    assert result.holds is True
    assert "1/1 inputs agree" in result.detail


def test_a_disagreement_names_the_input_that_caused_it(net):
    profile = MLTreeProfile()
    structure = profile.structure(net)
    inputs = [net.initial[structure.input][0]]
    result = check_conformance(net, inputs, lambda batch: [999] * len(batch),
                               input_places=(structure.input,),
                               output_places=(structure.pred,))
    assert result.holds is False
    assert "input=(" in result.detail and "expected=999" in result.detail


def test_a_broken_reference_is_reported_as_not_evaluated(net):
    profile = MLTreeProfile()
    structure = profile.structure(net)
    inputs = [net.initial[structure.input][0]]

    def boom(batch):
        raise RuntimeError("the model is not loaded")

    result = check_conformance(net, inputs, boom,
                               input_places=(structure.input,),
                               output_places=(structure.pred,))
    assert result.holds is None
    assert "the model is not loaded" in result.detail


def test_a_reference_of_the_wrong_length_is_refused(net):
    profile = MLTreeProfile()
    structure = profile.structure(net)
    inputs = [net.initial[structure.input][0]]
    result = check_conformance(net, inputs, lambda batch: [],
                               input_places=(structure.input,),
                               output_places=(structure.pred,))
    assert result.holds is None
    assert "0 values for 1 inputs" in result.detail
