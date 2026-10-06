"""Optional: cross-check CPNCheck against CPN Tools itself.

CPNCheck does not need CPN Tools. When CPN Tools 4.0.1 is installed (with
the CPN IDE, which ships the Access/CPN libraries, and a 32-bit Java 8), the
oracle runs CPN Tools' own simulator headless, builds the state space the
way the GUI does, and asks it the same questions -- so every CPNCheck answer
can be compared with CPN Tools' answer on the same file.

* ``compare_state_space``: nodes, arcs, SCCs, dead and home markings;
* ``compare_with_oracle``: every verdict and figure of the report, user
  properties included (rendered to ASK-CTL);
* ``compare_graph_containment``: for timed nets, where an occurrence may
  take any of several equally ready tokens and CPN Tools 4.0.1 explores only
  some of those choices, every node and arc CPN Tools finds must be in
  CPNCheck's graph.

    python examples/12_cpntools_oracle.py
    cpncheck oracle examples/nets/dining.cpn
"""

import sys

from _common import net, section

from cpncheck.coloured import CPNTOOLS_401
from cpncheck.oracle import (CPNToolsOracle, compare_graph_containment,
                             compare_state_space, compare_with_oracle)

oracle = CPNToolsOracle()
missing = oracle.missing()
if missing:
    print("CPN Tools is not available here, so there is nothing to compare "
          "with. Missing:", ", ".join(missing))
    print("Everything else in examples/ runs without it.")
    sys.exit(0)

# ---------------------------------------------------------------------------
section("1. The state space, statistic by statistic")
# ---------------------------------------------------------------------------
for name in ("dining", "dining_deadlock", "ml_features"):
    report = compare_state_space(net(name), oracle=oracle, timeout=600)
    rows = ", ".join(f"{k} {ours}" + ("" if same else f"/{theirs}")
                     for k, ours, theirs, same in report["rows"])
    print(f"  {name:<16} {'agree' if report['agree'] else 'DIFFER'}: {rows}")

# ---------------------------------------------------------------------------
section("2. Every verdict, user properties included")
# ---------------------------------------------------------------------------
report = compare_with_oracle(net("dining"), oracle=oracle, timeout=600,
                             properties="""
    PAIR: EF tokens(Eat) = 2
    EAT1: AF has(Eat, ph(1))
    ME12: AG !(has(Eat, ph(1)) & has(Eat, ph(2)))
""")
print(f"  {len(report['rows'])} values compared; all agree: {report['agree']}")
for key, ours, theirs, same in report["rows"][:12]:
    print(f"    {key:<34} CPNCheck {str(ours):<8} CPN Tools {str(theirs):<8}"
          f"{'' if same else '  <-- differs'}")

# ---------------------------------------------------------------------------
section("3. A timed net: containment")
# ---------------------------------------------------------------------------
# compat reproduces how CPN Tools 4.0.1's state-space tool expands a timed
# marking (it shifts timestamps by the node's creation time); only the
# comparison uses it.
report = compare_graph_containment(net("timed_jobs"), oracle=oracle,
                                   compat=CPNTOOLS_401, timeout=600)
print(f"  nodes (CPNCheck, CPN Tools): {report['nodes']}")
print(f"  arcs  (CPNCheck, CPN Tools): {report['arcs']}")
print(f"  dead  (CPNCheck, CPN Tools): {report['dead']}")
print(f"  every CPN Tools node and arc is in CPNCheck's graph: "
      f"{report['contained']}")
