"""State explosion, part 5: combining reductions.

Stubborn sets choose which successors to explore, the sweep-line method
chooses which markings to keep, and an equivalence chooses which markings to
tell apart. They act on different things, so they compose: name several,
joined with ``+``. Each property is decided by what *every* part preserves;
the others get no verdict, with the reason.

    python examples/15_combined_reductions.py
    cpncheck check examples/nets/workers.cpn --reduction stubborn+symmetry --symmetry WORKER=all
"""

import os
import tempfile

from _common import net, section

from cpncheck import check_cpn

PROPS = """
    NODL "no deadlock": AG !dead
    BUSY "never more than six busy": AG tokens(Busy) <= 6
    END "every run ends": AF dead
"""

# ---------------------------------------------------------------------------
section("1. Six identical workers: stubborn sets and symmetry together")
# ---------------------------------------------------------------------------
full = check_cpn(net("workers"), properties=PROPS)
stub = check_cpn(net("workers"), properties=PROPS, reduction="stubborn")
sym = check_cpn(net("workers"), properties=PROPS, reduction="symmetry",
                symmetry="WORKER=all")
both = check_cpn(net("workers"), properties=PROPS,
                 reduction="stubborn+symmetry", symmetry="WORKER=all")
print("full graph:        ", full.stats["nodes"], "markings")
print("stubborn alone:    ", stub.stats["nodes"], "markings (deadlock graph)")
print("symmetry alone:    ", sym.stats["classes"], "classes")
print("stubborn+symmetry: ", both.stats["graphs"]["deadlock"],
      "classes (deadlock graph)")
# The other graphs: per kind, markings (the report's liveness properties
# need the plain quotient).
print("  all graphs:", both.stats["graphs"])
for pid in ("NODL", "BUSY", "END"):
    print(f"  {pid:<5} full {full.properties[pid].status:<5} "
          f"combined {both.properties[pid].status}")

# ---------------------------------------------------------------------------
section("2. The sweep over stubborn successors: little stored at once")
# ---------------------------------------------------------------------------
# Eight pipelines that never interact: 3^8 = 6561 markings in full. The
# stubborn sets fire one pipeline at a time, and the sweep forgets what it
# has left behind. Any progress measure is sound.
swept = check_cpn(net("pipelines"), properties="AG !dead\nEF dead\nAF dead",
                  reduction="sweep+stubborn", progress='tokens("Done 1")')
# One sweep per stubborn graph: the deadlock graph, and one safety graph per
# invariant (the report's own properties add one per transition).
kinds = {}
for sweep in swept.stats["sweeps"]:
    k = kinds.setdefault(sweep["successors"], [0, 0])
    k[0] += 1
    k[1] = max(k[1], sweep["peak_stored"])
for kind, (count, peak) in kinds.items():
    print(f"  {count} sweep(s) over {kind} successors, at most {peak} "
          "markings stored at once")
for pid, r in swept.properties.items():
    if pid.startswith("U"):
        print(f"  {pid}: {r.status:<5} {r.detail[:70]}")
# AF dead is a property of paths: the sweep keeps none, so no verdict.

# ---------------------------------------------------------------------------
section("3. Time and symmetry: one canonical form")
# ---------------------------------------------------------------------------
# Two tokens go away and come back after a fixed delay. Time grows forever,
# so the occurrence graph is infinite; the time equivalence makes it finite
# and the symmetry halves it again.
with open(net("timed_loop"), encoding="utf-8") as fh:
    text = fh.read().replace("x @+ x", "x @+ 2")   # same delay for every token
path = os.path.join(tempfile.mkdtemp(), "symmetric_loop.cpn")
with open(path, "w", encoding="utf-8") as fh:
    fh.write(text)
props = "AWAY: AG tokens(Away) <= 2\nGO: EF marked(Away)"
time_only = check_cpn(path, properties=props, reduction="equivalence")
combined = check_cpn(path, properties=props,
                     reduction="equivalence+symmetry", symmetry="TOKEN=all")
print("time equivalence:      ", time_only.stats["classes"], "classes")
print("time+symmetry:         ", combined.stats["nodes"], "classes;",
      combined.stats["consistency"])
for pid in ("AWAY", "GO"):
    print(f"  {pid:<5} {combined.properties[pid].status}")

# ---------------------------------------------------------------------------
section("4. What is never combined, and what is dropped")
# ---------------------------------------------------------------------------
# On the original loop the delay depends on the token, so it is not
# symmetric: the composed consistency test refuses it.
refused = check_cpn(net("timed_loop"), properties="EF dead",
                    reduction="equivalence+symmetry", symmetry="TOKEN=all")
print("asymmetric loop:", refused.properties["U1"].status,
      refused.properties["U1"].detail[:70])
# Stubborn sets need transitions that interact only through their arcs; a
# timed net has a global clock, so they are dropped with a warning.
timed = check_cpn(net("timed_jobs"), properties="EF dead",
                  reduction="stubborn+equivalence")
print("timed net:", timed.properties["U1"].status, "|", timed.warnings[0][:70])
