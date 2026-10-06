"""State explosion, part 4: symmetry reduction.

Many nets treat the values of a colour set alike: every philosopher behaves
the same way. Renaming them maps a reachable marking to a reachable marking
with the same behaviour, so only one marking per *orbit* needs exploring.

The specification names the colour sets that may be permuted and how:

* ``"WORKER=all"``      -- every permutation of the workers;
* ``"PH,CS=rotation"``  -- philosophers and chopsticks rotated *together*,
  by position (philosopher i uses chopsticks i and i+1, so they must move
  in step).

The conditions are checked, not assumed: the initial marking must be
invariant under the group, and for every explored marking M and generator g
the successors of g(M) must be the images of those of M. A net that breaks
the symmetry fails the test and its verdicts are withheld. A property that
singles out a permuted value (``has(Eat, ph(1))``) gets no verdict.

    python examples/09_symmetry.py
    cpncheck check examples/nets/dining.cpn --reduction symmetry --symmetry PH,CS=rotation
"""

from _common import net, section

from cpncheck import check_cpn
from cpncheck.symmetry import SymmetryError

# ---------------------------------------------------------------------------
section("1. Identical workers: all permutations")
# ---------------------------------------------------------------------------
props = """
    BUSY "never more than six busy": AG tokens(Busy) <= 6
    END "every run ends with everyone done": AF tokens(Done) = 6
    BACK "someone can always finish": AG (marked(Busy) -> EF marked(Done))
"""
full = check_cpn(net("workers"), properties=props)
sym = check_cpn(net("workers"), properties=props, reduction="symmetry",
                symmetry="WORKER=all")
print(f"{full.stats['nodes']} markings -> {sym.stats['classes']} orbits;",
      sym.stats["consistency"])
for pid in ("BUSY", "END", "BACK"):
    print(f"  {pid:<5} full {full.properties[pid].status:<5} "
          f"symmetry {sym.properties[pid].status}")

# ---------------------------------------------------------------------------
section("2. Philosophers: rotations, two colour sets together")
# ---------------------------------------------------------------------------
props = """
    PAIR "two can eat at once": EF tokens(Eat) = 2
    THREE "three never eat at once": AG tokens(Eat) <= 2
    LIVE "someone can always eat again": AG EF marked(Eat)
    ONE "philosopher 1 can eat": EF has(Eat, ph(1))
"""
sym = check_cpn(net("dining"), properties=props, reduction="symmetry",
                symmetry="PH,CS=rotation")
print(f"11 markings -> {sym.stats['classes']} orbits;", sym.stats["consistency"])
for pid in ("PAIR", "THREE", "LIVE", "ONE"):
    r = sym.properties[pid]
    print(f"  {pid:<5} {r.status:<5} {r.detail[:90]}")
# ONE names philosopher 1, whom the rotation moves: no verdict, by design.

# ---------------------------------------------------------------------------
section("3. A symmetry the net does not have is caught")
# ---------------------------------------------------------------------------
# Philosophers are only *rotation* symmetric: swapping 1 and 2 does not
# preserve who sits next to whom. And rotating philosophers without their
# chopsticks breaks the Chopsticks(p) function.
for spec in ("PH,CS=all", "PH=rotation"):
    r = check_cpn(net("dining"), properties=props, reduction="symmetry",
                  symmetry=spec)
    print(f"  {spec:<12} {r.stats['consistency'][:70]}")
    print(f"  {'':<12} verdicts: "
          f"{sorted({p.status for p in r.properties.values()})}")

# ---------------------------------------------------------------------------
section("4. Specifications that cannot apply are refused")
# ---------------------------------------------------------------------------
for spec in ("PLATES=all", "PH=swap"):
    try:
        check_cpn(net("dining"), reduction="symmetry", symmetry=spec)
    except SymmetryError as exc:
        print(f"  {spec!r}: {str(exc)[:90]}")
