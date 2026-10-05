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


# ---------------------------------------------------------------------------
# Conformance
# ---------------------------------------------------------------------------


