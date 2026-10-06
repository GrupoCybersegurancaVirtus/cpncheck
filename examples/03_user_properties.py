"""Writing your own properties, in text, without Python.

A property is a CTL formula over the places and transitions of the net, by
name. The full language:

====================================  ========================================
``dead``                              no binding element is enabled
``enabled(T)``                        some transition named ``T`` is enabled
``marked(P)`` / ``empty(P)``          a place named ``P`` has / has no token
``tokens(P) op k``                    number of tokens, ``op`` in
                                      ``< <= = >= > <>``
``enabled_count(T) op k``             number of enabled binding elements
``has(P, v)``                         ``P`` holds the CPN ML value ``v``
``!f  f & g  f | g  f -> g``          Boolean connectives
``AG f  AF f  EF f  EG f``            CTL operators
``E[f U g]  A[f U g]``                until
====================================  ========================================

Names are bare (``Eat``, ``Top/Eat``) or quoted (``"Unused Chopsticks"``).
Dead markings have a self-loop: ``AF f`` fails on a run that stops before
``f`` holds.

    python examples/03_user_properties.py

From the command line, the same file and an extra one-off property:

    cpncheck check examples/nets/dining.cpn --props examples/properties/dining.props
    cpncheck check examples/nets/dining.cpn --prop "EF tokens(Eat) = 2"
"""

import os

from _common import PROPERTIES, net, section

from cpncheck import CPNModelChecker, check_cpn
from cpncheck.query import QueryError, load_properties, parse_properties

PROPS = os.path.join(PROPERTIES, "dining.props")

# ---------------------------------------------------------------------------
section("1. A property file")
# ---------------------------------------------------------------------------
for p in load_properties(PROPS):
    print(f"  {p.id:<8} {p.name:<44} {p.text}")

# ---------------------------------------------------------------------------
section("2. Checking it")
# ---------------------------------------------------------------------------
# User properties are requirements (PASS/FAIL); the R1-R5 facts of the
# default profile are reported beside them (YES/NO) and never fail a check.
result = check_cpn(net("dining"), properties=load_properties(PROPS))
for pid, r in result.properties.items():
    print(f"  {pid:<8} {r.status:<5} {r.spec.ctl}")
fair = result.properties["FAIR"]
print("\nFAIR fails with a cycle (a lasso):")
print(" ", fair.detail)

# ---------------------------------------------------------------------------
section("3. Properties from a string, or a list")
# ---------------------------------------------------------------------------
text = """
    TWO: EF tokens(Eat) = 2
    THREE: EF tokens(Eat) = 3
"""
result = check_cpn(net("dining"), properties=text)
print({pid: result.properties[pid].holds for pid in ("TWO", "THREE")})

# A list mixes parsed properties and strings; ids continue from U1.
mixed = parse_properties("AG tokens(Think) >= 3") + ["EF empty(Eat)"]
result = CPNModelChecker(net("dining"), properties=mixed).check()
print({p: result.properties[p].holds for p in ("U1", "U2")})

# ---------------------------------------------------------------------------
section("4. Mistakes are reported, not guessed at")
# ---------------------------------------------------------------------------
for bad in ["AG marked(Kitchen)", "AG tokens(Eat) <=", "EF has(Eat, ph(9 +))"]:
    try:
        check_cpn(net("dining"), properties=bad)
    except QueryError as exc:
        print(f"  {bad!r}: {str(exc)[:110]}")
