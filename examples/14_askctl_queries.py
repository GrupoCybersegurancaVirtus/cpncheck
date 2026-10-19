"""ASK-CTL queries as input: the queries a CPN Tools user already wrote.

A ``.sml`` file of ASK-CTL queries, the one evaluated in CPN Tools after
*Enter State Space*, is checked as it is. Every top-level
``eval_node F InitNode`` becomes a property; everything else in the file is
CPN ML, with the net's declarations and CPN Tools' state-space functions
(``Mark``, ``OutArcs``, ``ArcToBE``, ``SearchNodes``, ...).

The formulas mean exactly what ``ASKCTL.sml`` makes them mean, which is not
always textbook CTL; section 3 shows the two places where it matters.

    python examples/14_askctl_queries.py

From the command line:

    cpncheck check examples/nets/dining.cpn --askctl examples/properties/dining.sml
"""

import os

from _common import HERE, net, section

from cpncheck import check_cpn

# ---------------------------------------------------------------------------
section("1. A query file, as written for CPN Tools")
# ---------------------------------------------------------------------------
queries = os.path.join(HERE, "properties", "dining.sml")
result = check_cpn(net("dining"), askctl=queries)
for pid in ("AlwaysAgain", "NeverTwo", "CanPut1", "Q1", "Q2"):
    r = result.properties[pid]
    print(f"{pid:12} {r.status:5}  {r.detail[:60] if not r.holds else ''}")

# ---------------------------------------------------------------------------
section("2. Queries as text, beside CPNCheck's own properties")
# ---------------------------------------------------------------------------
result = check_cpn(net("dining_deadlock"), properties="AF has(Eat, ph(1))",
                   askctl="""
fun Dead n = OutArcs n = [];
fun Deadlocks n = length (ListDeadMarkings ()) > 0;
val Stuck = eval_node (POS (NF ("dead", Dead))) InitNode;
val Report = eval_node (NF ("deadlocks", Deadlocks)) InitNode;
""")
for pid in ("Stuck", "Report", "U1"):
    print(f"{pid:12} {result.properties[pid].status}")

# ---------------------------------------------------------------------------
section("3. Where ASK-CTL is not textbook CTL")
# ---------------------------------------------------------------------------
# EV holds vacuously at a dead marking: from a deadlock "every path" has no
# step left, so philosopher 1 "eventually eats" there. CPNCheck's own AF
# (textbook CTL, dead markings loop) says no.
result = check_cpn(net("dining_deadlock"), properties="AF marked(Eat)",
                   askctl="""
fun Eating n = Mark.Top'Eat 1 n <> empty;
val EvEats = eval_node (EV (NF ("eating", Eating))) InitNode;
fun Done n = Mark.Top'Eat 1 n = empty andalso Mark.Top'Has_Left 1 n <> empty;
fun Never n = false;
val Fast = eval_node (POS (ALONG (NF ("stuck", Done)))) InitNode;
val Basic = eval_node (POS (OR (ALONG (NF ("stuck", Done)), NF ("never", Never)))) InitNode;
""")
print("EV eating (ASK-CTL):", result.properties["EvEats"].status)
print("AF eating (textbook):", result.properties["U1"].status)
# POS (ALONG a) is decided on the SCC graph, where a deadlock that satisfies
# a counts; hidden from that pattern by a harmless OR, the basic evaluator
# says ALONG never holds at a dead marking. CPN Tools answers both ways too.
print("POS (ALONG a), fast path:     ", result.properties["Fast"].status)
print("POS (ALONG a OR false), basic:", result.properties["Basic"].status)
