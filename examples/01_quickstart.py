"""Quickstart: verify a net in one call, and read the result.

CPNCheck reads the ``.cpn`` file CPN Tools would open, builds its occurrence
graph (the state space) and answers questions about it. With no question
asked, it answers the ones CPN Tools' state-space report answers: is there a
deadlock, does every run terminate, is there a home marking, can every
transition occur, is every transition live (R1-R5), plus the bounds of every
place.

    python examples/01_quickstart.py

The same from the command line:

    cpncheck check examples/nets/dining.cpn
    cpncheck check examples/nets/dining.cpn --prop "AG tokens(Eat) <= 2"
"""

import json

from _common import net, section

from cpncheck import check_cpn

# ---------------------------------------------------------------------------
section("1. The default report: CPN Tools' state-space questions")
# ---------------------------------------------------------------------------
# Five philosophers think, take both chopsticks, eat and put them back.
result = check_cpn(net("dining"))
print(result.report())

# ---------------------------------------------------------------------------
section("2. Asking your own questions")
# ---------------------------------------------------------------------------
# Properties are CTL formulas over named places and transitions (see
# 03_user_properties.py for the whole language). Here: at most two
# philosophers eat at once, and some philosopher can always eat again.
result = check_cpn(net("dining"), properties="""
    AtMostTwo "at most two eat at once": AG tokens(Eat) <= 2
    NeverStuck "someone can always eat again": AG EF marked(Eat)
    AtMostOne "at most one eats at once": AG tokens(Eat) <= 1
""")
print(result.report())

# ---------------------------------------------------------------------------
section("3. The result as data")
# ---------------------------------------------------------------------------
print("passed:", result.passed)
print("failed:", [r.id for r in result.failures])
print("skipped (no verdict):", [r.id for r in result.skipped])
for pid, r in result.properties.items():
    # holds is True, False, or None when no verdict could be reached.
    print(f"  {pid:<11} {r.status:<5} {r.spec.name}")
print("graph:", result.stats["nodes"], "markings,", result.stats["arcs"], "arcs")

# A failed property carries a counterexample: the occurrences reaching a
# marking that violates it (more in 04_counterexamples.py).
print("why AtMostOne fails:", result.properties["AtMostOne"].cex.sequence())

# Everything is also available as JSON (``cpncheck check --json FILE``).
data = result.to_dict()
print("JSON keys:", sorted(data))
print(json.dumps(data["properties"]["AtMostTwo"], indent=2, default=str)[:400])
