# CPNCheck

Model checking for Coloured Petri Nets, from Python, on the `.cpn` file CPN
Tools itself would open — and cross-checked against CPN Tools.

CPN Tools answers verification questions interactively: enter the state-space
tool, calculate the occurrence graph and the SCC graph, paste an ASK-CTL script
into an auxiliary box, evaluate it, read the answer. CPNCheck answers the same
questions from a script, so verification can run on every build of every model,
and then it can run CPN Tools headlessly and check that the two engines agree.

Zero dependencies: the Python standard library is enough.

## Install

```bash
pip install -e .
```

## Use

```bash
cpncheck check model.cpn --labels 0,1,2      # verify and print the report
cpncheck check model.cpn --json verdicts.json --latex
cpncheck askctl model.cpn -o askctl.sml      # the same questions, for CPN Tools
cpncheck mutants model.cpn mutants/          # one mutant per property
cpncheck oracle model.cpn                    # run CPN Tools and compare
```

```python
from cpncheck import check_cpn

result = check_cpn("model.cpn", class_labels=[0, 1, 2])
print(result.report())
assert result.passed
for r in result.failures:
    print(r.id, r.detail)        # the counterexample
```

`ModelCheckResult` exposes `passed`, `failures`, `skipped`, `properties`,
`stats`, `oracle`, `report()`, `to_dict()`, `latex_rows()` and `latex_table()`.

## What it does

Four techniques, kept apart because they establish different things:

| Technique | What a verdict means |
|---|---|
| `ctl` | Explicit-state CTL on the occurrence graph. Real token values, no abstraction. True *for the initial marking it was given*. |
| `scc` | Home markings from the SCC decomposition — what CPN Tools' `ListHomeMarkings` computes. |
| `structural` | Static analysis of guards that are conjunctions of bounds. Holds for **every** input, which no single state space can show. |
| `testing` | Conformance with a reference function on a set of inputs. Not a temporal property. |

Dead markings are given a self-loop, so a maximal path that ends before φ is a
counterexample to `AF φ`. CPN Tools' ASK-CTL reads `EV` as vacuously true at a
dead marking; both readings are computed, and the generated ASK-CTL encodes
`AF φ` as `EV(φ) AND NOT E[¬φ U (dead ∧ ¬φ)]` so CPN Tools answers the textbook
question.

## Two claims, and how they are held up

**Sensitivity.** `cpncheck mutants` derives one mutant per property — a small
edit of a guard, an inscription or an arc that makes exactly that property
false. Agreement on correct nets alone would also be reached by two checkers
that always answer "true". The test suite runs every mutant and requires the
targeted property to fail.

**Agreement.** `cpncheck oracle` runs the CPN Tools 4.0.1 simulator headlessly
through Access/CPN, enters the state-space tool the way the GUI's *Enter State
Space* does, builds the occurrence and SCC graphs and evaluates the ASK-CTL
queries. Every statistic and every verdict is compared. Requires CPN Tools,
CPN IDE (for its bundled Access/CPN) and a 32-bit Java 8 with `jjs`;
`CPNToolsOracle().missing()` lists anything absent.

## Verifying your own nets

Properties are data, not code. A *profile* says which places and transitions
play which role in your nets and which properties they should satisfy; the
checker knows only markings, arcs and formulas.

```python
import collections
from cpncheck import CPNModelChecker
from cpncheck.formula import AF, AG, Dead, MaxTokens
from cpncheck.profile import Profile
from cpncheck.selectors import Places

class MyProfile(Profile):
    name = "my nets"
    catalog = my_property_descriptors

    def matches(self, net):
        return any(p["name"] == "Done" for p in net.places)

    def ctl_formulas(self, net, groups, labels):
        return collections.OrderedDict([
            ("T1", AF(Dead().phrased("the end"))),
            ("T2", AG(MaxTokens(Places(name="Done"), 1))),
        ])

print(CPNModelChecker("mine.cpn", profile=MyProfile()).check().report())
```

Available: `Dead`, `Marked`, `AllMarked`, `MaxTokens`, `TokensIn`, `Enabled`,
`EnabledCount`; `Not`, `And`, `Or`, `Implies`; `AG`, `AF`, `EF`, `EU`; and
`ForEach`, which quantifies over a group of pages and blames the one that
failed. Register a profile with `cpncheck.profile.register` and it is detected
automatically.

Each formula does two things beyond being true or false: **it explains itself**
when it fails (the shortest occurrence sequence to the violation, and why that
marking is bad), and **it renders to ASK-CTL**, so the Python check and the CPN
Tools script are the same question by construction.

The other three techniques are equally yours to use. A profile's
`static_checks` can call `cpncheck.structural.overlapping_guards` to ask
whether two branches of a choice are ever satisfiable together — an answer that
covers *every* input; `conformance` can call
`cpncheck.conformance.check_conformance` with any reference implementation; and
`mutation_operators` supplies the faults your properties must catch, built from
`cpncheck.mutation.CPNDocument`.

## Status

Pre-release, extracted from
[pyruleanalyzer](https://github.com/GrupoCybersegurancaVirtus/pyruleanalyzer),
where it verifies Hierarchical CPN models generated from decision trees, random
forests and gradient boosting — now one profile among others
(`cpncheck/profiles/ml_trees.py`).

The main limitation is that the **supported CPN ML fragment is narrow** — no
`if`/`case`/`let`/`fn`, no colour-set-driven binding enumeration, no timed
nets. Anything outside it raises `UnsupportedNet` instead of being silently
mis-read. See [MIGRATION.md](MIGRATION.md) for that and the rest of the plan.

MIT licensed.
