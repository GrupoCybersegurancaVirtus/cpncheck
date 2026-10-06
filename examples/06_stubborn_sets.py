"""State explosion, part 1: stubborn sets (partial-order reduction).

Components that do not interact produce every interleaving of their moves.
Eight workers that each go Idle -> Busy -> Done on their own give 3**8 =
6561 markings, although every order leads to the same end.

With ``reduction="stubborn"`` each property is decided on a reduced graph
that provably gives the same verdict as the full one. Which reduced graph
depends on what the property needs:

* ``deadlock`` -- keeps every dead marking (and whether some run is infinite);
* ``safety``   -- keeps a violation of ``AG psi`` when there is one;
* ``stutter``  -- keeps every CTL-X verdict (``AF``, ``AG EF``, ``EU``...);
* ``full``     -- for whatever the theorems do not cover.

    python examples/06_stubborn_sets.py
    cpncheck check examples/nets/pipelines.cpn --reduction stubborn
"""

import time

from _common import net, section

from cpncheck import check_cpn

# Function to check with and without the reduction, and compare.
def compare(name: str, props: str) -> None:
    """Check a net both ways and print sizes, times and verdicts.

    Args:
        name (str): The example net.
        props (str): Properties.
    """
    t0 = time.perf_counter()
    full = check_cpn(net(name), properties=props)
    t_full = time.perf_counter() - t0
    t0 = time.perf_counter()
    reduced = check_cpn(net(name), properties=props, reduction="stubborn")
    t_red = time.perf_counter() - t0
    st = reduced.stats
    print(f"full graph   : {full.stats['nodes']} markings ({t_full:.2f}s)")
    print(f"reduced      : deadlock graph {st['nodes']} markings, largest "
          f"graph {st['nodes_max']}, graphs {st['per_kind']} ({t_red:.2f}s)")
    for pid, r in full.properties.items():
        print(f"  {pid:<5} full {r.status:<5} reduced "
              f"{reduced.properties[pid].status:<5} decided on "
              f"{st['plans'][pid]}")
        assert reduced.properties[pid].holds == r.holds


# ---------------------------------------------------------------------------
section("1. Eight independent workers, one sub-net each")
# ---------------------------------------------------------------------------
props = """
    END "every run ends with worker 1 done": AF marked("Done 1")
    EXCL "worker 1 is never busy and done": AG !(marked("Busy 1") & marked("Done 1"))
    PAIR "workers 1 and 2 can be busy together": EF (marked("Busy 1") & marked("Busy 2"))
    BACK "worker 1 can always finish": AG (marked("Busy 1") -> EF marked("Done 1"))
"""
compare("pipelines", props)

# ---------------------------------------------------------------------------
section("2. The report says which graph decided each property")
# ---------------------------------------------------------------------------
result = check_cpn(net("pipelines"), properties=props, reduction="stubborn")
print("\n".join(result.report().splitlines()[:16]))

# ---------------------------------------------------------------------------
section("3. The same workers folded into one sub-net")
# ---------------------------------------------------------------------------
# workers.cpn has the same behaviour with colours: one Start and one Finish
# transition, each with a binding per worker. Independence is computed from
# the arcs, per transition, so bindings of one transition are not separated
# -- the reduction gains much less. Unfold independent components when you
# want this reduction to bite.
compare("workers", """
    END "every run ends with everyone done": AF tokens(Done) = 6
    BUSY "never more than six busy": AG tokens(Busy) <= 6
""")

# ---------------------------------------------------------------------------
section("4. When it does not apply")
# ---------------------------------------------------------------------------
# Timed nets and nets with priorities are always checked on the full graph:
# the clock and the priorities make transitions depend on each other in ways
# the arcs do not show.
timed = check_cpn(net("timed_jobs"), reduction="stubborn")
print("timed net, graphs used:", sorted(set(timed.stats["plans"].values())))
