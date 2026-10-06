"""State explosion, part 3: equivalence reduction (quotient graphs).

An *equivalence* groups markings that behave alike; exploring one
representative per class gives the *quotient* graph. It gives the full
graph's CTL verdicts when the equivalence is *consistent* (equivalent
markings reach the same classes) and the property cannot tell equivalent
markings apart. An equivalence is given as a *canonical form*: a function
from a marking to its class representative.

* **Time equivalence** (built in, timed nets): markings equal up to a shift
  of time are one class. Exact, unless an inscription reads ``time()`` --
  then it is refused by name.
* **Your own canonical form**: consistency is *tested* on sampled markings,
  not proved, and the verdicts are reported as conditional on the test.

Not preserved by any equivalence: the home-marking property, and the graph
statistics (they describe the quotient).

    python examples/08_equivalence.py
    cpncheck check examples/nets/timed_loop.cpn --reduction equivalence
"""

from _common import net, section

from cpncheck import CPNNet, ColouredNet, build_state_space, check_cpn
from cpncheck.cpnml import TimedToken
from cpncheck.equivalence import build_quotient, time_equivalence

# ---------------------------------------------------------------------------
section("1. A timed net whose occurrence graph is infinite")
# ---------------------------------------------------------------------------
# Two tokens circulate between Ready and Away forever, and the clock grows
# without bound: every marking is new, because its clock is.
cn = ColouredNet(CPNNet(net("timed_loop")))
ss = build_state_space(cn, max_nodes=5_000)
print(f"full graph after 5000 markings: complete = {ss.complete}")
print("an occurrence graph that never ends gives no verdicts:")
r = check_cpn(net("timed_loop"), properties="AG !dead", max_nodes=5_000)
print("  ", r.properties["U1"].status, "-", r.properties["U1"].detail)

# ---------------------------------------------------------------------------
section("2. Time equivalence makes it finite")
# ---------------------------------------------------------------------------
eq = time_equivalence(cn)
# The canonical form moves a marking to clock 0; each timestamp becomes the
# delay from the clock (0 for a token already ready).
m = ((TimedToken(1, 103),), (TimedToken(2, 110),), 100)
print("marking at clock 100:", m, "-> representative:", eq.canonical(m))

quotient, report = build_quotient(cn, eq)
print(f"quotient: {quotient.n_nodes} classes, complete = {quotient.complete};",
      report.summary())

result = check_cpn(net("timed_loop"), reduction="equivalence", properties="""
    NODL "never stuck": AG !dead
    BACK "both tokens can be ready again": AG EF tokens(Ready) = 2
    AWAY "both can be away at once": EF tokens(Away) = 2
""")
for pid, r in result.properties.items():
    print(f"  {pid:<5} {r.status:<5} {r.detail[:80]}")
# R3 (home marking) is reported without a verdict: a class can be reachable
# from all others while none of its markings is.

# ---------------------------------------------------------------------------
section("3. Your own canonical form")
# ---------------------------------------------------------------------------
# Example: in the folded workers, the identity of a worker does not matter,
# only how many are in each state. Representative: replace every worker by
# the first ones, keeping the counts. (09_symmetry.py does this properly;
# here it shows a user equivalence.)
workers = ColouredNet(CPNNet(net("workers")))
order = workers.initial[0]          # w(1) .. w(6), all idle at the start


# Function to keep only how many workers are in each place.
def by_counts(marking):
    """Representative: the same counts, the lowest-numbered workers.

    Args:
        marking (tuple): Idle, Busy, Done.

    Returns:
        tuple: The representative.
    """
    out, k = [], 0
    for tokens in marking:
        out.append(tuple(order[k:k + len(tokens)]))
        k += len(tokens)
    return tuple(out)


props = "AG tokens(Busy) <= 6\nEF tokens(Done) = 6\nAF tokens(Done) = 6"
r = check_cpn(net("workers"), reduction="equivalence", equivalence=by_counts,
              properties=props)
print(f"{r.stats['classes']} classes instead of 729;", r.stats["consistency"])
for pid in ("U1", "U2", "U3"):
    print(f"  {pid} {r.properties[pid].status:<5} {r.properties[pid].detail[:90]}")

# ---------------------------------------------------------------------------
section("4. An inconsistent equivalence is caught")
# ---------------------------------------------------------------------------
# Forgetting who is busy merges markings that behave differently (a marking
# with a busy worker can Finish; its representative cannot).
r = check_cpn(net("workers"), reduction="equivalence",
              equivalence=lambda m: (m[0], (), m[2]), properties=props)
print(r.stats["consistency"])
print("verdicts:", {pid: r.properties[pid].status for pid in ("U1", "U2", "U3")})

# ---------------------------------------------------------------------------
section("5. Time equivalence needs a timed net that does not read time()")
# ---------------------------------------------------------------------------
try:
    check_cpn(net("workers"), reduction="equivalence")
except ValueError as exc:
    print("untimed net:", exc)
