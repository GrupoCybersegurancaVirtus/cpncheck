"""The CPN ML front end: lexer, parser, compiler, colour sets and declarations.

Guards and inscriptions used to be translated with regular expressions, which
works for what a generator emits and fails on what people write. These tests
are the fragment the parser claims to cover, and the shapes it must refuse
rather than misread -- a wrong reading of a guard is a wrong verdict.
"""

import os

import pytest

from cpncheck.coloured import ColouredNet, parse_pattern_multiset
from cpncheck.colourset import ColourSet, Declarations
from cpncheck.cpnml import (PRELUDE, MLError, compile_expression,
                            free_variables, match_pattern, parse_declarations,
                            parse_expression, parse_multiset, parse_pattern,
                            pattern_variables, tokenize)
from cpncheck.net import CPNNet

NETS = os.path.join(os.path.dirname(__file__), "nets")
GBDT = os.path.join(NETS, "gbdt_binary.cpn")
RF = os.path.join(NETS, "rf_multiclass.cpn")


def ev(source, env=None, globals_=None):
    """Compile and run one expression."""
    scope = dict(PRELUDE)
    scope.update(globals_ or {})
    return compile_expression(parse_expression(source), scope)(env or {})


# ---------------------------------------------------------------------------
# Lexing
# ---------------------------------------------------------------------------

def test_sml_negation_is_part_of_a_number():
    assert ev("~2.5") == -2.5
    assert ev("~3") == -3
    assert ev("2.0E~3") == pytest.approx(0.002)


def test_comments_nest():
    assert ev("1 + (* a (* nested *) comment *) 2") == 3


def test_qualified_names_are_one_token():
    kinds = [k for k, _v, _p in tokenize("List.foldl")]
    assert kinds == ["id", "end"]


def test_the_wildcard_is_not_a_variable():
    """`_` twice in one pattern must not demand that the two agree."""
    pattern = parse_pattern("(_, a, _)")
    assert pattern_variables(pattern) == {"a"}
    assert match_pattern(pattern, (1, 2, 3)) == {"a": 2}


# ---------------------------------------------------------------------------
# The fragment
# ---------------------------------------------------------------------------

def test_arithmetic_and_precedence():
    assert ev("1 + 2 * 3") == 7
    assert ev("(1 + 2) * 3") == 9
    assert ev("7 div 2") == 3 and ev("7 mod 2") == 1
    assert ev("7.0 / 2.0") == 3.5


def test_comparison_and_boolean_operators():
    assert ev("1 < 2 andalso 2 <= 2") is True
    assert ev("1 = 2 orelse 3 <> 4") is True
    assert ev("not (1 = 1)") is False


def test_andalso_short_circuits():
    """The right-hand side must not run when the left already decides it."""
    assert ev("false andalso (1 div 0) = 0") is False
    assert ev("true orelse (1 div 0) = 0") is True


def test_conditionals():
    assert ev("if x > 3 then 1 else 0", {"x": 5}) == 1
    assert ev("if x > 3 then 1 else 0", {"x": 1}) == 0


def test_let_bindings_see_the_earlier_ones():
    assert ev("let val a = 2 val b = a * 3 in a + b end") == 8


def test_case_takes_the_first_matching_clause():
    assert ev('case n of 0 => "zero" | _ => "more"', {"n": 0}) == "zero"
    assert ev('case n of 0 => "zero" | _ => "more"', {"n": 7}) == "more"


def test_functions_are_values_and_may_recurse():
    assert ev("(fn (a, b) => a + b) (3, 4)") == 7
    assert ev("let fun f n = if n <= 1 then 1 else n * f (n - 1) in f 5 end") \
        == 120


def test_lists_and_their_operators():
    assert ev("1 :: [2, 3] @ [4]") == (1, 2, 3, 4)
    assert ev("hd [1, 2]") == 1 and ev("tl [1, 2]") == (2,)
    assert ev("List.foldl (fn (x, acc) => x + acc) 0 [1,2,3,4]") == 10
    assert ev("List.filter (fn x => x > 2) [1,2,3,4]") == (3, 4)


def test_records_are_tuples_in_field_order():
    fields = {"f0": 0, "f1": 1}
    tree = parse_expression("#f1 x")
    assert compile_expression(tree, {}, fields)({"x": (10.0, 20.0)}) == 20.0
    built = compile_expression(parse_expression("{f1 = 2.0, f0 = 1.0}"),
                               {}, fields)({})
    assert built == (1.0, 2.0)


def test_tuple_selectors_are_one_based():
    assert compile_expression(parse_expression("#2 t"), {})({"t": (7, 8)}) == 8


def test_type_annotations_are_read_and_ignored():
    assert ev("let fun f (x : real) = x + 1.0 in f 2.0 end") == 3.0
    assert ev("(fn (a : int, b : int) => a + b) (1, 2)") == 3


def test_multi_clause_functions():
    source = "fun len [] = 0 | len (_ :: t) = 1 + len t;"
    declared = dict(PRELUDE)
    for entry in parse_declarations(source):
        assert entry[0] == "fun"
        declared[entry[1]] = compile_expression(entry[2], declared)({})
    assert declared["len"]((1, 2, 3)) == 3


def test_free_variables_ignores_what_is_bound_locally():
    assert free_variables(parse_expression("a + b")) == {"a", "b"}
    assert free_variables(parse_expression("fn x => x + y")) == {"y"}
    assert free_variables(parse_expression("let val x = y in x + z end")) \
        == {"y", "z"}


# ---------------------------------------------------------------------------
# What must be refused
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source", [
    "1 +",
    "if x then 1",
    "let val a = 1 in a",
    "fn => 1",
    "1 ) 2",
    "$bad",
])
def test_a_malformed_expression_is_refused(source):
    with pytest.raises(MLError):
        parse_expression(source)


def test_an_unbound_name_is_an_error_not_a_guess():
    with pytest.raises(MLError):
        ev("nowhere + 1")


def test_a_declaration_that_cannot_be_read_is_reported():
    """Silently dropping one would surface much later as an unbound name."""
    entries = parse_declarations("val a = 1; val b = ; val c = 3;")
    kinds = [e[0] for e in entries]
    assert "error" in kinds
    assert kinds.count("val") == 2


# ---------------------------------------------------------------------------
# Multisets
# ---------------------------------------------------------------------------

def test_an_arc_may_carry_a_multiset():
    terms = parse_multiset("1`x ++ 2`(y, z)")
    assert len(terms) == 2
    assert terms[1][0] is not None                    # the coefficient 2


def test_an_input_arc_may_match_several_tokens():
    terms = parse_pattern_multiset("2`x ++ 1`(a, b)")
    assert [count for count, _p in terms] == [2, 1]


def test_an_input_coefficient_must_be_literal():
    from cpncheck.coloured import UnsupportedNet
    with pytest.raises(UnsupportedNet):
        parse_pattern_multiset("n`x")


# ---------------------------------------------------------------------------
# Colour sets
# ---------------------------------------------------------------------------

def test_colour_sets_are_read_from_the_declarations():
    d = Declarations(GBDT)
    assert d.colsets["SAMPLE"].kind == "record"
    assert d.colsets["SAMPLE"].labels == [f"f{i}" for i in range(6)]
    assert d.colsets["SS"].kind == "product"
    assert d.variables == {"x": "SAMPLE", "sc": "REAL", "lv": "REAL"}
    assert d.fields["f3"] == 3
    assert not d.problems


def test_finite_and_infinite_domains():
    d = Declarations(GBDT)
    assert d.colsets["BOOL"].domain(d.colsets) == (False, True)
    assert d.colsets["UNIT"].domain(d.colsets) == ((),)
    assert d.colsets["REAL"].domain(d.colsets) is None
    assert d.colsets["SAMPLE"].domain(d.colsets) is None      # a record of reals


def test_a_product_of_finite_colour_sets_is_finite():
    sets = {
        "B": ColourSet("B", "bool"),
        "E": ColourSet("E", "enum", values=["a", "b", "c"]),
        "P": ColourSet("P", "product", parts=["B", "E"]),
    }
    assert len(sets["P"].domain(sets)) == 6


def test_a_product_containing_an_infinite_colour_set_is_infinite():
    sets = {
        "R": ColourSet("R", "real"),
        "B": ColourSet("B", "bool"),
        "P": ColourSet("P", "product", parts=["B", "R"]),
    }
    assert sets["P"].domain(sets) is None


# ---------------------------------------------------------------------------
# A net describes its own functions
# ---------------------------------------------------------------------------

def test_the_net_declares_the_functions_its_arcs_use():
    """Nothing about soft voting is built into the checker; the net says it."""
    d = Declarations(RF)
    assert not d.problems
    for name in ("vadd", "vsum", "argmax", "allzero", "decide"):
        assert name in d.globals, name
    assert d.globals["vadd"](((1.0, 2.0), (10.0, 20.0))) == (11.0, 22.0)
    assert d.globals["vsum"](((1.0, 2.0), (3.0, 4.0))) == (4.0, 6.0)
    assert d.globals["argmax"]((0.1, 0.9, 0.3)) == 1
    assert d.globals["argmax"](()) == 0
    assert d.globals["allzero"]((0.0, 0.0)) is True
    assert d.globals["decide"]((0.0, 0.0, 0.0)) == 0
    assert d.globals["decide"]((0.1, 0.7, 0.2)) == 1


def test_a_caller_may_override_a_declared_function():
    always_zero = Declarations(RF, prelude={"decide": lambda xs: 0})
    assert always_zero.globals["decide"]((0.1, 0.7, 0.2)) == 0


def test_the_nets_still_flatten_and_fire():
    for path in (GBDT, RF):
        net = ColouredNet(CPNNet(path))
        marking = net.initial
        assert net.enabled(marking), path
        ti, _key, env = net.enabled(marking)[0]
        assert net.fire(marking, ti, env) != marking
