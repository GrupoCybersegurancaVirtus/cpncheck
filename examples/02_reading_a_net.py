"""Under the hood: read a net, fire it by hand, build its occurrence graph.

``check_cpn`` is three layers stacked; each can be used on its own:

* :class:`cpncheck.CPNNet` parses the ``.cpn`` XML (pages, places,
  transitions, arcs, declarations);
* :class:`cpncheck.ColouredNet` compiles the CPN ML inscriptions, flattens the
  hierarchy and fires binding elements;
* :func:`cpncheck.build_state_space` explores every reachable marking.

The net used here is ``ml_features.cpn``, which exercises more of CPN ML than
the philosophers do: a product colour set, a guard that *defines* a variable,
a code segment, transition priorities and a multiset inside ``if``.

    python examples/02_reading_a_net.py
"""

import os

from _common import net, section

from cpncheck import CPNNet, ColouredNet, UnsupportedNet, build_state_space

# ---------------------------------------------------------------------------
section("1. The parsed file")
# ---------------------------------------------------------------------------
doc = CPNNet(net("ml_features"))
for page in doc.prime_pages():
    print("prime page:", page["name"])

# ---------------------------------------------------------------------------
section("2. The compiled net")
# ---------------------------------------------------------------------------
cn = ColouredNet(doc)
print("timed:", cn.timed, "| priorities:", cn.uses_priorities,
      "| stubborn reduction applicable:", cn.reducible)
for p in cn.places:
    print(f"  place {p['gid']:<16} colour set {p['colset']}")
for t in cn.transitions:
    print(f"  transition {t['gid']:<12} guard {t['guard_text'] or '-':<34}"
          f" priority {t.get('priority_text') or 'P_NORMAL'}"
          f"{'  code: ' + t['code_text'] if t.get('code_text') else ''}")

# A marking is a tuple with one sorted tuple of tokens per place (and, in a
# timed net, the clock at the end).
m0 = cn.initial
names = [p["name"] for p in cn.places]
print("initial marking:", dict(zip(names, m0)))

# ---------------------------------------------------------------------------
section("3. Firing by hand")
# ---------------------------------------------------------------------------
# enabled() lists the binding elements that may occur: (transition index,
# binding key, binding). Rush has priority P_HIGH, so while a rush order is
# waiting the normal ones may not go -- and the guard [k = rush, total = q*2]
# both filters and *computes* total, which is on no input arc.
for ti, _key, binding in cn.enabled(m0):
    print("enabled:", cn.transitions[ti]["name"], binding)
ti, _key, binding = cn.enabled(m0)[0]
m1 = cn.fire(m0, ti, binding)
print("after Rush:", dict(zip(names, m1)))

# run() fires the first enabled element until nothing is enabled: one
# maximal run, cheap enough to test many inputs.
final = cn.run()
print("end of one run:", dict(zip(names, final)))
# Invoice's code segment computed fee = total + 1 for every order, and the
# order over 10 went to Big Orders through `if q > 10 then 1`(k,q) else empty`.

# ---------------------------------------------------------------------------
section("4. The occurrence graph")
# ---------------------------------------------------------------------------
ss = build_state_space(cn, max_nodes=10_000)
print(f"{ss.n_nodes} markings, {ss.n_arcs} arcs, complete: {ss.complete}")
print(f"{ss.n_sccs} strongly connected components, "
      f"{len(ss.dead)} dead marking(s), {len(ss.home)} home marking(s)")
dead = ss.dead[0]
print("shortest way to the dead marking:", ss.trace(dead))
for ti, key, node in ss.succ[0]:
    print(f"  arc from the initial marking: {cn.transitions[ti]['name']} "
          f"{dict(key)} -> node {node}")

# ---------------------------------------------------------------------------
section("5. What is not supported is refused by name")
# ---------------------------------------------------------------------------
# A construct CPNCheck cannot evaluate is never skipped silently: reading
# the net wrongly would mean checking a different net. Here a CPN Tools
# sample with a random delay, if CPN Tools is installed.
sample = (r"C:\Program Files (x86)\CPN Tools\Sample CPN Models"
          r"\TimedProtocol\TimedProtocol.cpn")
if os.path.exists(sample):
    try:
        build_state_space(ColouredNet(CPNNet(sample)), max_nodes=100)
    except UnsupportedNet as exc:
        print("refused:", str(exc)[:150])
else:
    print("(CPN Tools samples not installed; see examples/cpntools_samples.py)")
