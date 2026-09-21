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
    print(r.id, r.detail)        # the counterexample, rendered
```

`ModelCheckResult` exposes `passed`, `failures`, `skipped`, `properties`,
`stats`, `oracle`, `report()`, `to_dict()`, `latex_rows()` and `latex_table()`.

`python examples/walkthrough.py` runs all of it on the nets under `tests/nets`
and prints what each layer produced, step by step — the XML, the compiled
guards, the occurrence graph, one run marking by marking, the verdicts, the
counterexamples and the mutants. See [examples/](examples/).

## Counterexamples

A violated property hands back evidence, not a sentence. `r.cex` is a
`Counterexample`: the occurrence sequence, the binding of every step, the
marking it ends in, and the input the net was given.

```python
cex = result.properties["A3"].cex
cex.kind                      # finite | lasso | witness | structural | conformance
cex.sequence(bindings=True)   # Distribute<x = (2, 7)> -> Init<...> -> ...
cex.input                     # the input this violation needs
cex.replay(checker.cnet)      # True: it really does what it says
cex.to_dict()                 # the whole trace, for a report or a test
```

`cpncheck check model.cpn --trace` prints all of it.

Three things worth knowing:

**A liveness property can fail with no finite witness at all.** If the net can
run forever without ever reaching the goal, the evidence has to include the
repeating part. That is the `lasso` shape: a prefix, then a cycle the net can
take indefinitely — `... -> Feed_1 then forever [Rule2]`.

**`replay()` is a certificate.** It re-fires the sequence using the net's
firing rule, not the search that produced it, and checks it ends where the
counterexample claims (and, for a lasso, returns to where the cycle began). A
bug in the fixpoints cannot forge a trace that replays. The test suite requires
every sequence from every mutant to replay, and requires a tampered one not to.

**A structural finding comes with an input.** Guard disjointness holds or fails
for *every* input, so a failure names no particular run — but the intersection
of the two guards is a box, and a point in it is an input on which the overlap
really happens. Feed it back and the per-input check fails too, on the same
pair:

```python
witness = result.properties["B4"].cex.input
again = check_cpn("model.cpn", samples=[witness], class_labels=[0, 1, 2])
assert again.properties["B1"].holds is False     # now it is reachable
```

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

## What it understands of CPN ML

Guards and inscriptions are parsed, not pattern-matched: `if`/`then`/`else`,
`let`/`in`/`end`, `case`/`of`, `fn`, function application, the operators with
their SML precedences and associativities, lists, tuples, records, multisets
and type annotations. The expression compiles to a closure, so firing stays
fast.

A net's own `val` and `fun` declarations are read and used, which means **a net
describes itself**. Nothing about what the tree nets compute is built into the
checker: their soft voting and `argmax` come from the `<ml>` blocks of the
`.cpn` file. Where a net leaves a function undeclared, supply it:

```python
check_cpn("model.cpn", prelude={"myFunction": lambda x: ...})
```

**Binding elements.** A variable that no input arc binds is enumerated over its
declared colour set, the way CPN Tools does it — `unit`, `bool`, enumerations,
index ranges and the products, records, subsets and aliases built from them. A
free variable whose colour set is infinite makes the net unexplorable and is
refused by name, never quietly ignored.

Still missing: timed nets, fusion sets beyond port/socket fusion, and
user-declared datatypes. Anything outside the fragment raises `UnsupportedNet`
rather than being mis-read — a wrong reading of a guard is a wrong verdict.

## Status

Pre-release, extracted from
[pyruleanalyzer](https://github.com/GrupoCybersegurancaVirtus/pyruleanalyzer),
where it verifies Hierarchical CPN models generated from decision trees, random
forests and gradient boosting — now one profile among others
(`cpncheck/profiles/ml_trees.py`).

Agreement with CPN Tools is measured, not assumed: 28 nets — two correct ones
and every mutant of each — agree on every statistic and every verdict, with 81
*false* verdicts confirmed by CPN Tools itself. See [MIGRATION.md](MIGRATION.md)
for what remains.

MIT licensed.
