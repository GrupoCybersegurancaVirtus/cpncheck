"""Timed nets: timestamps, delays and the global clock.

In a timed CPN, tokens of a ``timed`` colour set carry a timestamp: the
earliest model time at which they can be taken. CPNCheck follows CPN Tools'
semantics with integer time:

* the marking includes a global clock;
* the binding elements that may occur are those enabled at the *earliest*
  time anything is enabled -- the clock then moves to that time;
* tokens produced get the occurrence time plus the transition's delay
  (``@+d`` on the transition) plus the arc's (``x @+ d`` on the arc);
* ``time()`` reads the clock.

The net: three jobs (1, 2, 3) share two machines. Job ``j`` is processed for
``2*j`` time units, then the machine needs one unit of cleanup.

    python examples/05_timed_nets.py
"""

from _common import net, section

from cpncheck import CPNNet, ColouredNet, build_state_space, check_cpn

cn = ColouredNet(CPNNet(net("timed_jobs")))
names = [p["name"] for p in cn.places]


# Function to print a marking with its clock.
def show(marking):
    """Print the tokens of each marked place and the clock.

    Args:
        marking (tuple): A timed marking; the clock is its last element.
    """
    tokens = {n: " ".join(map(str, t)) for n, t in zip(names, marking[:-1]) if t}
    print(f"  clock {marking[-1]:>2}: {tokens}")


# ---------------------------------------------------------------------------
section("1. The timed marking")
# ---------------------------------------------------------------------------
print("timed places:", [names[i] for i in sorted(cn.timed_places)])
show(cn.initial)
# A token prints as value@timestamp; Machines is untimed (colour set M).

# ---------------------------------------------------------------------------
section("2. One run, step by step")
# ---------------------------------------------------------------------------
m = cn.initial
while True:
    options = cn.enabled(m)
    if not options:
        break
    ti, _key, binding = options[0]
    when = cn.ready_time(m, ti, binding)
    print(f"{cn.transitions[ti]['name']} j={binding['j']} at time {when}")
    m = cn.fire(m, ti, binding)
    show(m)
# Jobs 1 and 2 start at 0; Finish of job 1 waits until its token is ready
# (time 2) and puts the machine back at 2 + 1 (the transition's @+1).

# ---------------------------------------------------------------------------
section("3. The earliest-time rule")
# ---------------------------------------------------------------------------
# After both machines are taken nothing is enabled at time 0: the clock jumps
# to the first time something is.
m = cn.initial
for _ in range(2):
    ti, _key, binding = cn.enabled(m)[0]
    m = cn.fire(m, ti, binding)
show(m)
for ti, _key, binding in cn.enabled(m):
    print("  enabled:", cn.transitions[ti]["name"], binding["j"],
          "at", cn.ready_time(m, ti, binding))

# ---------------------------------------------------------------------------
section("4. The occurrence graph and properties")
# ---------------------------------------------------------------------------
ss = build_state_space(cn)
print(f"{ss.n_nodes} timed markings, {len(ss.dead)} dead")
for d in ss.dead:
    show(ss.markings[d])
# Different orders finish at different times: each end is its own marking,
# because the clock and the timestamps are part of the state.

result = check_cpn(net("timed_jobs"), properties="""
    ALLDONE "every run ends with all jobs finished":
        AF tokens(Finished) = 3
    MACHINES "never more than two jobs in process":
        AG tokens(Processing) <= 2
""")
for pid in ("ALLDONE", "MACHINES"):
    print(pid, result.properties[pid].status)

# Properties observe token *values*, not timestamps: has(Finished, 2) is
# true whatever time job 2 finished at.
print("has(Finished, 2) reachable:",
      check_cpn(net("timed_jobs"), properties="EF has(Finished, 2)")
      .properties["U1"].holds)

# ---------------------------------------------------------------------------
section("5. Notes")
# ---------------------------------------------------------------------------
print("""\
* When a place holds several ready tokens of the same value with different
  timestamps, an occurrence may take any of them: each choice is its own
  successor.
* Real-valued time (@++) and random delays (ran(), exponential) are refused:
  such a net has no occurrence graph to check.
* Stubborn-set reduction is not used on timed nets (the clock couples every
  transition); see 07_sweep_line.py and 08_equivalence.py for the reductions
  that suit them.""")
