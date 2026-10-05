"""The default profile: CPN Tools' state-space report, for any net.

A net no other profile recognises gets this one. Its five properties are facts
(YES/NO) and never make a check fail; beside them come the place bounds and
the dead and live transition instances. The figures are compared with CPN
Tools' own state-space functions in ``tests/test_cpntools_samples.py``.

The last test runs the checker with the oracle module blocked: CPNCheck itself
must never need CPN Tools.
"""

import glob
import os
import subprocess
import sys

import pytest

from cpncheck import CPNModelChecker, check_cpn
from cpncheck.net import CPNNet
from cpncheck.profiles.statespace_report import ml_name

from test_net_reading import write_net

HERE = os.path.dirname(__file__)
SAMPLES_DIR = os.environ.get(
    "CPNTOOLS_SAMPLES", r"C:\Program Files (x86)\CPN Tools\Sample CPN Models")


def _stop_net(tmp_path):
    """Count to 2 and stop; 'Never' needs a token that never comes."""
    return write_net(str(tmp_path / "stop.cpn"), {"Top": {
        "places": [("C", "C", "INT", "1`0", None),
                   ("Z", "Z", "INT", None, None)],
        "trans": [("T", "Tick", "[n < 2]", None), ("N", "Never", None, None)],
        "arcs": [("T", "C", "PtoT", "n"), ("T", "C", "TtoP", "n + 1"),
                 ("N", "Z", "PtoT", "x")]}})


def _cycle_net(tmp_path):
    """A token going round two places forever."""
    return write_net(str(tmp_path / "cycle.cpn"), {"Top": {
        "places": [("A", "A", "INT", "1`1", None), ("B", "B", "INT", None, None)],
        "trans": [("T", "Go", None, None), ("U", "Back", None, None)],
        "arcs": [("T", "A", "PtoT", "x"), ("T", "B", "TtoP", "x"),
                 ("U", "B", "PtoT", "x"), ("U", "A", "TtoP", "x")]}},
        variables=("x",))


def test_any_net_gets_the_default_profile(tmp_path):
    mc = CPNModelChecker(_stop_net(tmp_path))
    assert mc.family == "CPN"
    assert mc.profile.name == "state-space report"


def test_without_its_plugin_a_tree_net_is_just_a_net():
    """CPNCheck knows nothing of trees: pyruleanalyzer's profile is a plugin."""
    mc = CPNModelChecker(os.path.join(HERE, "nets", "rf_multiclass.cpn"))
    assert mc.profile.name == "state-space report"


class _FakeEntryPoint:
    """What importlib.metadata hands back for one published plugin."""

    def __init__(self, name, target):
        self.name, self.value, self._target = name, f"fake:{name}", target

    def load(self):
        if isinstance(self._target, Exception):
            raise self._target
        return self._target


def _with_plugins(monkeypatch, *eps):
    import importlib.metadata as md
    import cpncheck.profile as P

    class Found(list):
        def select(self, group):
            return [ep for ep in self if group == "cpncheck.profiles"]

    monkeypatch.setattr(md, "entry_points", lambda: Found(eps))
    monkeypatch.setattr(P, "_PLUGINS_LOADED", False)
    monkeypatch.setattr(P, "_REGISTRY", list(P._REGISTRY))


def test_a_plugin_profile_is_found_through_its_entry_point(tmp_path,
                                                          monkeypatch):
    from cpncheck.profile import Profile

    class Counters(Profile):
        name = "counters"
        priority = 5

        def matches(self, net):
            return any(p["name"] == "C" for p in net.places)

    _with_plugins(monkeypatch, _FakeEntryPoint("counters", Counters))
    assert CPNModelChecker(_stop_net(tmp_path)).profile.name == "counters"


def test_a_broken_plugin_warns_and_is_skipped(tmp_path, monkeypatch):
    _with_plugins(monkeypatch,
                  _FakeEntryPoint("broken", ImportError("no module x")),
                  _FakeEntryPoint("not_a_profile", object()))
    with pytest.warns(RuntimeWarning, match="could not be loaded"):
        mc = CPNModelChecker(_stop_net(tmp_path))
    assert mc.profile.name == "state-space report"


def test_a_net_that_stops(tmp_path):
    result = check_cpn(_stop_net(tmp_path))
    status = {pid: r.status for pid, r in result.properties.items()}
    assert status == {"R1": "NO", "R2": "YES", "R3": "YES", "R4": "NO",
                      "R5": "NO"}
    # Facts are reported, not failed: the check passes.
    assert result.passed and not result.failures
    rep = result.report_data
    assert dict((gid, (lo, hi)) for gid, lo, hi in rep["bounds"]) == {
        "Top/C": (1, 1), "Top/Z": (0, 0)}
    assert rep["dead_transitions"] == ["Top/Never"]
    assert rep["live_transitions"] == []
    text = result.report()
    assert "State space report" in text and "facts reported" in text
    assert "R4" in text and "Top/Never" in text


def test_a_net_that_cycles_forever(tmp_path):
    result = check_cpn(_cycle_net(tmp_path))
    status = {pid: r.status for pid, r in result.properties.items()}
    assert status == {"R1": "YES", "R2": "NO", "R3": "YES", "R4": "YES",
                      "R5": "YES"}
    assert result.properties["R2"].cex.kind == "lasso"
    assert sorted(result.report_data["live_transitions"]) == ["Top/Back",
                                                              "Top/Go"]


def test_the_report_is_also_asked_of_cpntools(tmp_path):
    mc = CPNModelChecker(_stop_net(tmp_path))
    result = mc.check()
    _decl, queries = mc.ml_program()
    for key in ("dead_tis", "live_tis", "bound_lo_0", "bound_up_0"):
        assert key in queries and key in result.oracle
    assert result.oracle["dead_tis"] == "1"


def test_ml_names_follow_cpntools_one_character_at_a_time():
    assert ml_name("Send an Acknowledg-\nment") == "Send_an_Acknowledg__ment"
    assert ml_name("Receive Acknow.") == "Receive_Acknow_"


def test_ml_names_are_read_from_the_raw_name(tmp_path):
    path = write_net(str(tmp_path / "names.cpn"), {"Top": {
        "places": [("P", "Packets\nTo Send", "INT", "1`1", None)],
        "trans": [("T", "Send-\nPacket", None, None)],
        "arcs": [("T", "P", "PtoT", "x")]}}, variables=("x",))
    from cpncheck.coloured import ColouredNet
    net = ColouredNet(CPNNet(path))
    assert net.places[0]["ml"] == "Top'Packets_To_Send"
    assert net.transitions[0]["ml"] == "Top'Send__Packet"


SMALL_SAMPLES = [os.path.join(SAMPLES_DIR, n) for n in (
    "DiningPhilosophers/DiningPhilosophers.cpn",
    "DistributedDataBase/DistributedDataBase.cpn",
    "SimpleProtocol/SimpleProtocol_OG.cpn")]


@pytest.mark.skipif(not all(os.path.exists(p) for p in SMALL_SAMPLES),
                    reason="CPN Tools sample models not found")
@pytest.mark.parametrize("path", SMALL_SAMPLES,
                         ids=[os.path.basename(p) for p in SMALL_SAMPLES])
def test_the_reduction_gives_the_same_facts_on_samples(path):
    mc = CPNModelChecker(path)
    full = mc.check()
    reduced = mc.check(reduction="stubborn")
    assert {p: r.holds for p, r in full.properties.items()} == \
        {p: r.holds for p, r in reduced.properties.items()}


def test_cpncheck_runs_without_cpntools(tmp_path):
    """Block the oracle module outright: checking must not touch it."""
    net = _stop_net(tmp_path)
    tree = os.path.join(HERE, "nets", "gbdt_binary.cpn")
    script = (
        "import sys\n"
        "sys.modules['cpncheck.oracle'] = None\n"      # any import now fails
        "from cpncheck import check_cpn\n"
        f"a = check_cpn({net!r})\n"
        f"b = check_cpn({tree!r}, properties='AF dead')\n"
        f"c = check_cpn({tree!r}, properties='AF dead', reduction='stubborn')\n"
        "assert a.properties and b.passed and c.passed\n"
        "print('ok')\n")
    root = os.path.abspath(os.path.join(HERE, ".."))
    done = subprocess.run([sys.executable, "-c", script], capture_output=True,
                          text=True, cwd=root,
                          env={**os.environ, "PYTHONPATH": root})
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip().endswith("ok")
