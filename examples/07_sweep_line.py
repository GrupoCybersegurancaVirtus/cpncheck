"""State explosion, part 2: the sweep-line method.

The sweep-line method explores markings in the order of a *progress measure*
and forgets the ones it has left behind, so memory holds a moving window of
the graph instead of all of it. CPNCheck uses the generalised method: an
occurrence that goes *back* in progress (a regress arc) makes its target
persistent and starts a new sweep from it. So every reachable marking is
explored whatever the measure -- a bad measure costs time, never a wrong
verdict.

What it decides: properties of single markings -- ``AG psi``, ``EF chi``,
``!EF chi`` with state predicates, which may mention ``dead`` and
``enabled``. Path properties (``AF``, ``EG``, ``AG EF``) and home markings
get no verdict, with the reason. A violation is reported as the marking
found, without a path (none is kept).

A measure is a sum of ``[k *] tokens(P)``, ``[k *] sum(P)`` (integer token
values), ``[k *] clock`` and constants -- or a Python function of the
marking. A timed net needs none: its clock never goes back.

    python examples/07_sweep_line.py
    cpncheck check examples/nets/workers.cpn --reduction sweep \\
        --progress "2*tokens(Done) + tokens(Busy)" --prop "AG tokens(Busy) <= 6"
"""

from _common import net, section

from cpncheck import CPNNet, ColouredNet, build_state_space, check_cpn
from cpncheck.sweepline import ProgressError, parse_progress, sweep

PROPS = """
    BUSY "never more than six busy": AG tokens(Busy) <= 6
    ALL "everyone can be done": EF tokens(Done) = 6
    NOT7 "seven can never be done": !EF tokens(Done) = 7
    STOP "only the end is dead": AG (dead -> tokens(Done) = 6)
    LIVE "path property, not decided": AG EF marked(Done)
"""

# ---------------------------------------------------------------------------
section("1. A good measure: work done only grows")
# ---------------------------------------------------------------------------
# Each Start adds 1 to the measure and each Finish adds 1 more: monotone.
result = check_cpn(net("workers"), properties=PROPS, reduction="sweep",
                   progress="2*tokens(Done) + tokens(Busy)")
st = result.stats
full = build_state_space(ColouredNet(CPNNet(net("workers"))))
print(f"full graph: {full.n_nodes} markings")
print(f"sweep     : {st['explored']} explored, at most {st['peak_stored']} "
      f"stored at once, {st['sweeps']} sweep(s), {st['regress']} regress arcs")
for pid in ("BUSY", "ALL", "NOT7", "STOP", "LIVE"):
    r = result.properties[pid]
    print(f"  {pid:<5} {r.status:<5} {r.detail[:70]}")

# ---------------------------------------------------------------------------
section("2. A bad measure still gives the right answer")
# ---------------------------------------------------------------------------
# Going backwards: every step *decreases* this measure, so every arc is a
# regress arc. Verdicts are unchanged; the cost is more sweeps.
for measure in ["0", "-2*tokens(Done) - tokens(Busy)",
                lambda marking: hash(marking) % 7]:
    r = check_cpn(net("workers"), properties=PROPS, reduction="sweep",
                  progress=measure)
    st = r.stats
    verdicts = {p: r.properties[p].holds for p in ("BUSY", "ALL", "NOT7", "STOP")}
    print(f"  {str(st['progress'])[:30]:<30} explored {st['explored']:>4}, "
          f"peak {st['peak_stored']:>4}, sweeps {st['sweeps']:>3}: {verdicts}")

# ---------------------------------------------------------------------------
section("3. A violation is a marking, not a path")
# ---------------------------------------------------------------------------
r = check_cpn(net("workers"), properties="AG tokens(Busy) <= 3",
              reduction="sweep", progress="2*tokens(Done) + tokens(Busy)")
print(r.properties["U1"].detail)

# ---------------------------------------------------------------------------
section("4. Timed nets: the clock is the measure")
# ---------------------------------------------------------------------------
cn = ColouredNet(CPNNet(net("timed_jobs")))
measure = parse_progress(None, cn)              # a timed net defaults to clock
res = sweep(cn, measure)
print(f"progress '{measure.text}': {res.explored} explored, "
      f"{res.distinct_bound} stored at most, regress arcs: {res.regress}, "
      f"dead markings found: {len(res.dead)}")

# ---------------------------------------------------------------------------
section("5. Measures that cannot be read are refused")
# ---------------------------------------------------------------------------
for bad in ["tokens(Nowhere)", "clock", "2 ** tokens(Done)"]:
    try:
        parse_progress(bad, ColouredNet(CPNNet(net("workers"))))
    except ProgressError as exc:
        print(f"  {bad!r}: {exc}")
