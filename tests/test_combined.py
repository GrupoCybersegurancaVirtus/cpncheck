"""Combined reductions (``cpncheck.combined``) against the full graph.

Every combination must give the full occurrence graph's verdict or none,
and a verdict on what it claims to preserve.
"""

import os

import pytest

from cpncheck import check_cpn
from cpncheck.combined import parse_combination

NETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                    "examples", "nets")

#: Properties of every kind: deadlock, safety, reachability, paths.
PROPS = {
    "dining": ("PH,CS=rotation", "tokens(Eat)", """
        D1: AG !dead
        D2: EF dead
        T: AF dead
        E2: EF tokens(Eat) = 2
        B: AG tokens(Eat) <= 2
        R: AG EF marked(Eat)
        NE: !EF tokens(Eat) = 3
        G: AG (dead -> tokens(Eat) = 0)
    """),
    "dining_deadlock": ("PH,CS=rotation", 'tokens(Eat) + tokens("Has Left")',
                        """
        D1: AG !dead
        D2: EF dead
        T: AF dead
        E2: EF tokens(Eat) = 2
        B: AG tokens(Eat) <= 2
        R: AG EF marked(Eat)
        NE: !EF tokens(Eat) = 3
        G: AG (dead -> tokens(Eat) = 0)
    """),
    "workers": ("WORKER=all", "tokens(Done)", """
        D1: AG !dead
        D2: EF dead
        T: AF dead
        B: AG tokens(Busy) <= 6
        F: EF tokens(Done) = 6
        G: AG (dead -> tokens(Done) = 6)
        R: AG (marked(Busy) -> EF marked(Done))
    """),
    "pipelines": (None, 'tokens("Done 1") + tokens("Done 2")', """
        D1: AG !dead
        D2: EF dead
        T: AF dead
        G: AG (dead -> marked("Done 8"))
        B: AG tokens("Busy 1") <= 1
        F: EF marked("Done 3")
    """),
}

#: Combinations each net can take.
COMBOS = {
    "dining": ["stubborn+symmetry", "sweep+symmetry", "sweep+stubborn",
               "sweep+stubborn+symmetry"],
    "dining_deadlock": ["stubborn+symmetry", "sweep+symmetry",
                        "sweep+stubborn", "sweep+stubborn+symmetry"],
    "workers": ["stubborn+symmetry", "sweep+symmetry", "sweep+stubborn",
                "sweep+stubborn+symmetry"],
    "pipelines": ["sweep+stubborn"],
}

_cache = {}


# Function to give the full graph's verdicts of a net.
def _full(net):
    """Verdicts on the full occurrence graph, computed once.

    Args:
        net (str): The example net.

    Returns:
        dict: ``{id: holds}``.
    """
    if net not in _cache:
        _sym, _prog, props = PROPS[net]
        result = check_cpn(os.path.join(NETS, f"{net}.cpn"), properties=props)
        _cache[net] = {pid: r.holds for pid, r in result.properties.items()
                       if pid in props}
    return _cache[net]


# Test every combination against the full graph.
@pytest.mark.parametrize("net, combo", [(n, c) for n, cs in COMBOS.items()
                                        for c in cs])
def test_combination_agrees_with_full_graph(net, combo):
    sym, prog, props = PROPS[net]
    full = _full(net)
    result = check_cpn(os.path.join(NETS, f"{net}.cpn"), properties=props,
                       reduction=combo, symmetry=sym, progress=prog)
    for pid, expected in full.items():
        got = result.properties[pid].holds
        assert got is None or got == expected, (pid, got, expected)
    # What each combination preserves gets a verdict.
    preserved = {"D1", "D2", "G", "B", "NE", "E2", "F"} & set(full)
    if "sweep" not in combo:
        preserved |= {"T", "R"} & set(full)
    for pid in preserved:
        assert result.properties[pid].holds is not None, \
            (pid, result.properties[pid].detail)


# Test that stubborn sets still reduce when swept.
def test_stubborn_sweep_reduces_independent_pipelines():
    path = os.path.join(NETS, "pipelines.cpn")
    full = check_cpn(path, properties="AG !dead")
    swept = check_cpn(path, properties="AG !dead",
                      reduction="sweep+stubborn",
                      progress='tokens("Done 1")')
    assert swept.stats["nodes"] < full.stats["nodes"] / 10
    assert swept.properties["U1"].holds == full.properties["U1"].holds


#: Verdicts of the symmetric timed loop, from its time-equivalence quotient
#: (exact; the occurrence graph itself is infinite, time grows forever).
LOOP_PROPS = """
    D: EF dead
    A: AG tokens(Away) <= 2
    E: EF marked(Away)
    N: !EF tokens(Away) = 3
    T: AF dead
"""


# Function to write a timed net with a real symmetry.
def _symmetric_loop(tmp_path):
    """``timed_loop.cpn`` with a delay that no longer depends on the token.

    Args:
        tmp_path: pytest's directory.

    Returns:
        str: The path.
    """
    with open(os.path.join(NETS, "timed_loop.cpn"), encoding="utf-8") as fh:
        text = fh.read()
    assert "x @+ x" in text
    path = tmp_path / "symmetric_loop.cpn"
    path.write_text(text.replace("x @+ x", "x @+ 2"), encoding="utf-8")
    return str(path)


# Test time equivalence composed with symmetry on a timed net.
@pytest.mark.parametrize("combo", ["equivalence+symmetry",
                                   "sweep+equivalence+symmetry",
                                   "sweep+equivalence"])
def test_time_and_symmetry_compose(tmp_path, combo):
    path = _symmetric_loop(tmp_path)
    exact = check_cpn(path, properties=LOOP_PROPS, reduction="equivalence")
    both = check_cpn(path, properties=LOOP_PROPS, reduction=combo,
                     symmetry="TOKEN=all")
    for pid in ("D", "A", "E", "N", "T"):
        got = both.properties[pid].holds
        if pid == "T" and "sweep" in combo:
            assert got is None                  # a path property
            continue
        assert got == exact.properties[pid].holds, pid
    if "symmetry" in combo:
        assert both.stats["nodes"] < exact.stats["classes"]


# Test that an asymmetric net is refused by the composed test too.
def test_composition_refuses_an_asymmetric_net():
    # timed_loop returns a token after a delay equal to its own value.
    result = check_cpn(os.path.join(NETS, "timed_loop.cpn"),
                       properties="EF dead",
                       reduction="equivalence+symmetry", symmetry="TOKEN=all")
    assert result.properties["U1"].holds is None
    assert "not consistent" in result.properties["U1"].detail


# Test that stubborn sets are dropped, with a note, where they do not apply.
def test_stubborn_dropped_on_timed_net():
    path = os.path.join(NETS, "timed_jobs.cpn")
    result = check_cpn(path, properties="EF dead",
                       reduction="stubborn+equivalence")
    assert result.properties["U1"].holds is True
    assert any("stubborn sets dropped" in w for w in result.warnings)


# Test the home-marking property is never claimed.
def test_home_marking_not_decided():
    result = check_cpn(os.path.join(NETS, "dining.cpn"),
                       reduction="stubborn+symmetry", symmetry="PH,CS=rotation")
    assert result.properties["R3"].holds is None


# Test reading combinations.
@pytest.mark.parametrize("text, expected", [
    ("symmetry+stubborn", ("stubborn", "symmetry")),
    ("sweep + stubborn + equivalence", ("stubborn", "sweep", "equivalence")),
    (["stubborn", "sweep"], ("stubborn", "sweep")),
    ("stubborn", None),
    (None, None),
])
def test_parse_combination(text, expected):
    assert parse_combination(text) == expected


# Test the errors.
@pytest.mark.parametrize("text", ["stubborn+magic", "sweep+sweep"])
def test_parse_combination_errors(text):
    with pytest.raises(ValueError):
        parse_combination(text)


# Test that the report renders every shape of combination.
@pytest.mark.parametrize("net, combo, kw, expected", [
    ("workers", "sweep+stubborn", {"progress": "tokens(Done)"},
     "sweep(s) over deadlock successors"),
    ("workers", "stubborn+symmetry", {"symmetry": "WORKER=all"},
     "deadlock graph 13 markings"),
    ("timed_jobs", "stubborn+equivalence", {}, "stubborn sets dropped"),
])
def test_report_renders(net, combo, kw, expected):
    result = check_cpn(os.path.join(NETS, f"{net}.cpn"), reduction=combo, **kw)
    text = result.report()
    assert f"reduction        : {combo}" in text or \
        "reduction        : stubborn+sweep" in text
    assert expected in text


# Test the command line with a combination.
def test_command_line():
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "-m", "cpncheck.cli", "check",
         os.path.join(NETS, "workers.cpn"), "--reduction", "sweep+stubborn",
         "--progress", "tokens(Done)", "--prop", "EF dead"],
        capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "stubborn+sweep" in out.stdout
    bad = subprocess.run(
        [sys.executable, "-m", "cpncheck.cli", "check",
         os.path.join(NETS, "workers.cpn"), "--reduction", "sweep+magic"],
        capture_output=True, text=True)
    assert bad.returncode != 0 and "magic" in bad.stderr
