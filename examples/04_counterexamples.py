"""Counterexamples: what went wrong, how to get there, and proof that it is real.

When a property fails, CPNCheck says *why*: a finite occurrence sequence to a
marking that violates a safety property (``AG``), or a lasso -- a prefix and a
cycle that repeats forever -- for a liveness property (``AF``) that never
becomes true. Every step names the transition and its binding, and the
sequence can be *replayed* on the net to confirm it is a real run.

The net: philosophers who take the left chopstick, then the right one. If all
five take their left chopstick, nobody can take a right one.

    python examples/04_counterexamples.py

From the command line, ``--trace`` prints every counterexample in full:

    cpncheck check examples/nets/dining_deadlock.cpn --prop "AG !dead" --trace
"""

from _common import net, section

from cpncheck import CPNModelChecker, CPNNet, ColouredNet

checker = CPNModelChecker(net("dining_deadlock"), properties="""
    NODL "no deadlock": AG !dead
    EAT1 "philosopher 1 eventually eats": AF has(Eat, ph(1))
    PAIR "two philosophers can eat together": EF tokens(Eat) = 2
""")
result = checker.check()

# ---------------------------------------------------------------------------
section("1. A safety violation: a finite path to a deadlock")
# ---------------------------------------------------------------------------
r = result.properties["NODL"]
cex = r.cex
print("verdict:", r.status)
print("kind:", cex.kind, "| steps:", cex.length)
print("note:", cex.note)
print("sequence:", cex.sequence())
print("with bindings:")
for step in cex.prefix:
    print("  ", step.detailed())

# The marking reached, place by place.
names = [p["name"] for p in checker.cnet.places]
print("dead marking:", {n: list(map(str, toks))
                        for n, toks in zip(names, cex.final) if toks})

# Replay: fire the steps on the net from its initial marking and check that
# each was enabled and that the end is the reported marking.
print("replays on the net:", cex.replay(checker.cnet))

# ---------------------------------------------------------------------------
section("2. A liveness violation: a lasso")
# ---------------------------------------------------------------------------
# In the philosophers who take both chopsticks at once there is no deadlock,
# but philosopher 1 can still wait forever: the others keep eating in a
# cycle. The counterexample is a prefix followed by that cycle.
fair = CPNModelChecker(net("dining"),
                       properties="AF has(Eat, ph(1))").check()
cex = fair.properties["U1"].cex
print("kind:", cex.kind)
print("prefix:", " -> ".join(s.detailed() for s in cex.prefix) or "(none)")
print("cycle :", " -> ".join(s.detailed() for s in cex.cycle))
print("replays on the net:", cex.replay(ColouredNet(CPNNet(net("dining")))))

# In the deadlocking net the same property fails with a finite sequence: a
# dead marking repeats forever (its self-loop), and philosopher 1 is not
# eating in it.
print("deadlocking net:", result.properties["EAT1"].cex.kind, "--",
      result.properties["EAT1"].detail)

# ---------------------------------------------------------------------------
section("3. A witness for a property that holds")
# ---------------------------------------------------------------------------
# EF properties that hold need no counterexample; one that fails would get a
# note saying no reachable marking satisfies it.
print("PAIR:", result.properties["PAIR"].status)

# ---------------------------------------------------------------------------
section("4. As data")
# ---------------------------------------------------------------------------
data = result.properties["NODL"].cex.to_dict()
print({k: data[k] for k in ("kind", "note", "length")})
print("first step:", data["prefix"][0])
