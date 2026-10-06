"""Taking the results elsewhere: ASK-CTL for CPN Tools, JSON, LaTeX, diffs.

* ``export_askctl`` writes the same properties as an ASK-CTL script (SML) to
  paste into CPN Tools' state-space tool, so every verdict can be checked
  there by hand;
* ``to_dict`` / ``--json`` gives every verdict as data;
* ``latex_table`` / ``--latex`` gives a table for a paper;
* ``compare_results`` lines up two versions of a net, property by property
  -- e.g. a model before and after a change.

    python examples/11_askctl_and_reports.py
    cpncheck askctl examples/nets/dining.cpn -o dining.sml
    cpncheck check examples/nets/dining.cpn --json result.json --latex
"""

import json
import os
import tempfile

from _common import net, section

from cpncheck import CPNModelChecker, compare_results

PROPS = """
    NODL "no deadlock": AG !dead
    PAIR "two can eat at once": EF tokens(Eat) = 2
    EAT1 "philosopher 1 eventually eats": AF has(Eat, ph(1))
"""
out = tempfile.mkdtemp()

# ---------------------------------------------------------------------------
section("1. An ASK-CTL script for CPN Tools")
# ---------------------------------------------------------------------------
checker = CPNModelChecker(net("dining"), properties=PROPS)
path = checker.export_askctl(os.path.join(out, "dining.sml"))
script = open(path, encoding="utf-8").read()
print(f"wrote {path} ({len(script.splitlines())} lines); excerpt:")
for line in script.splitlines():
    if "NODL" in line or "PAIR" in line or line.startswith("(*"):
        print("  ", line[:100])
# In CPN Tools: Enter State Space, Calculate State Space, then evaluate the
# script in an auxiliary text box. It prints one true/false per property.

# The same program as data: the declarations and one ML expression per key.
declarations, queries = checker.ml_program()
print("query for PAIR:", queries.get("PAIR", "")[:100])

# ---------------------------------------------------------------------------
section("2. JSON")
# ---------------------------------------------------------------------------
result = checker.check()
data = result.to_dict()
with open(os.path.join(out, "dining.json"), "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2, default=str)
print("properties:", {pid: p["status"] for pid, p in data["properties"].items()})
print("EAT1 counterexample:", data["properties"]["EAT1"]["counterexample"]["kind"])

# ---------------------------------------------------------------------------
section("3. LaTeX")
# ---------------------------------------------------------------------------
print(result.latex_table(label="tab:dining", caption="Dining philosophers"))

# ---------------------------------------------------------------------------
section("4. Comparing two versions of a net")
# ---------------------------------------------------------------------------
# Taking chopsticks one at a time (dining_deadlock.cpn) is a "change" to the
# model: which properties did it break?
after = CPNModelChecker(net("dining_deadlock"), properties=PROPS).check()
print(compare_results(result, after, names=("before", "after")))
