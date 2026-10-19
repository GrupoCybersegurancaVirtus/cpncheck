"""Declarations as nets in the wild write them.

Every case here comes from a net of the corpus (``tests/corpus``) that was
refused or misread before: colour sets given only as text, renamed unit and
bool values, unions, references, curried functions by cases, sequences,
flexible record patterns, and declarations repeated in ``<layout>``.
"""

import xml.etree.ElementTree as ET

import pytest

from cpncheck.colourset import _own_text, colour_from_text
from cpncheck.coloured import ColouredNet
from cpncheck.cpnml import (ConValue, EnumValue, MLError, PRELUDE,
                            compile_expression, match_pattern,
                            parse_declarations, parse_expression)
from cpncheck.net import CPNNet
from cpncheck.statespace import build_state_space

from test_net_reading import write_net


# Function to evaluate declarations into an environment.
def _declare(text, fields=None):
    env = dict(PRELUDE)
    for entry in parse_declarations(text):
        assert entry[0] != "error", entry
        tree = entry[2]
        if entry[0] == "fun":
            env[entry[1]] = compile_expression(tree, env, fields or {})({})
        else:
            env.update(match_pattern(entry[1],
                                     compile_expression(tree, env, fields or {})({}),
                                     {}, fields))
    return env


@pytest.mark.parametrize("text,kind,detail", [
    ("colset PH = index ph with 1..3;", "indexed", ("ph", ("1", "3"))),
    ("colset E = unit with e timed;", "enum", ["e"]),
    ("colset B = bool with (alive, die);", "enum", ["alive", "die"]),
    ("colset S = int with 1..5;", "index", [1, 2, 3, 4, 5]),
    ("colset P = union Data : D + Ack : A + Stop;", "union",
     (["Data", "Ack", "Stop"], ["D", "A", ""])),
    ("colset R = record x : INT * y : E;", "record", (["x", "y"], ["INT", "E"])),
    ("colset L = list INT timed;", "list", "INT"),
    ("colset X = product A * B;", "product", ["A", "B"]),
    ("colset C = with clerk | boss; (* staff *)", "enum", ["clerk", "boss"]),
    ("colset A = INT;", "alias", "INT"),
])
def test_colour_sets_written_as_text(text, kind, detail):
    cs = colour_from_text(text)
    assert cs.kind == kind
    if kind == "indexed":
        assert (cs.base, cs.bounds) == detail
    elif kind in ("enum", "index"):
        assert [str(v) if isinstance(v, EnumValue) else v for v in cs.values] == detail
    elif kind in ("union", "record"):
        assert (cs.labels, cs.parts) == detail
    elif kind in ("list", "alias"):
        assert cs.base == detail
    else:
        assert cs.parts == detail
    assert cs.timed == ("timed" in text)


def test_layout_text_is_not_read_twice():
    ml = ET.fromstring("<ml>val k = 1;<layout>val k = 1;</layout></ml>")
    assert _own_text(ml).strip() == "val k = 1;"


def test_a_union_colour_set_in_a_net(tmp_path):
    union = ('<color id="cP"><id>PK</id><union>'
             '<unionfield><id>Data</id><type><id>INT</id></type></unionfield>'
             '<unionfield><id>Ack</id></unionfield></union></color>')
    small = ('<color id="cS"><id>INT</id><int><with><ml>1</ml><ml>2</ml>'
             '</with></int></color>')
    path = write_net(str(tmp_path / "u.cpn"), {"Top": {
        "places": [("A", "A", "PK", "1`Data(1) ++ 1`Ack", None),
                   ("B", "B", "PK", None, None)],
        "trans": [("T", "Move", None, None)],
        "arcs": [("T", "A", "PtoT", "Data(n)"), ("T", "B", "TtoP", "Data(n + 1)")]}},
        colsets=("UNUSED",), colors=(small, union), typed_vars={"n": "INT"},
        variables=())
    net = ColouredNet(CPNNet(path))
    names = [p["name"] for p in net.places]
    m0 = dict(zip(names, net.initial))
    assert ConValue("Data", 1) in m0["A"] and EnumValue("Ack") in m0["A"]
    ss = build_state_space(net)
    final = dict(zip(names, ss.markings[ss.dead[0]]))
    assert final["B"] == (ConValue("Data", 2),) and final["A"] == (EnumValue("Ack"),)


def test_references_are_read_but_never_assigned():
    env = _declare("globref rate = 5; fun Wait () = !rate;")
    assert env["Wait"](()) == 5
    with pytest.raises(MLError, match="side effect"):
        compile_expression(parse_expression("rate := 3"), env)({})


def test_curried_functions_by_cases():
    env = _declare("fun ins2 x [] = [x] "
                   "| ins2 x (y::ys) = if x < y then x::y::ys else y::(ins2 x ys);")
    assert env["ins2"](3)((1, 2, 4, 5)) == (1, 2, 3, 4, 5)
    assert env["ins2"](9)(()) == (9,)


def test_sequences_evaluate_in_order_and_give_the_last():
    assert compile_expression(parse_expression("(1; 2; 3)"), dict(PRELUDE))({}) == 3
    env = _declare("val k = let val a = 1 in a; a + 1 end;")
    assert env["k"] == 2


def test_flexible_record_patterns_and_puns():
    fields = {"seq": 0, "data": 1}
    env = _declare("fun ext ({data, ...}) = data;", fields)
    assert env["ext"]((7, "x")) == "x"


def test_datatypes_exceptions_and_local_declarations(tmp_path):
    ml = ('datatype shape = Circle of INT | Square of INT * INT | Dot;'
          ' exception Bad of string;'
          ' fun area (Circle r) = 3 * r * r | area (Square (w, h)) = w * h'
          ' | area Dot = 0;'
          ' fun safe xs = hd xs handle Empty => ~1;'
          ' fun check n = if n < 0 then raise Bad "neg" else n;'
          ' local val k = 2 in fun twice x = k * x end;')
    path = write_net(str(tmp_path / "d.cpn"), {"Top": {
        "places": [("P", "P", "INT", "1`2", None), ("Q", "Q", "INT", None, None)],
        "trans": [("T", "T", None, None)],
        "arcs": [("T", "P", "PtoT", "n"),
                 ("T", "Q", "TtoP", "area (Square (n, 5)) + twice (safe [])"
                                    " + (check ~1 handle Bad m => String.size m)")]}},
        variables=("n",), ml=(ml,))
    net = ColouredNet(CPNNet(path))
    ss = build_state_space(net)
    final = dict(zip([p["name"] for p in net.places], ss.markings[ss.dead[0]]))
    assert final["Q"] == (10 - 2 + 3,)
