# CPNCheck

**Model checking for Coloured Petri Nets, from Python, on the `.cpn` file CPN
Tools itself would open -- and cross-checked against CPN Tools.**

CPN Tools answers verification questions interactively: enter the state-space
tool, calculate the occurrence graph, paste an ASK-CTL query into an auxiliary
box, evaluate it, read the answer. CPNCheck answers the same questions from a
script or the command line, so verification can run on every build of every
model -- and it can run CPN Tools headlessly to show that the two agree.

![From a .cpn file to verdicts: read, explore the occurrence graph, check, and optionally compare with CPN Tools](https://raw.githubusercontent.com/GrupoCybersegurancaVirtus/cpncheck/main/docs/figures/pipeline.png)

* **Your net as it is.** Hierarchy, colour sets, CPN ML declarations and
  functions, timed nets -- read from the file, never rewritten by hand.
* **Questions without code.** CPN Tools' state-space report for any net,
  your own CTL properties in a small text language, or the ASK-CTL queries
  you already wrote for CPN Tools.
* **Evidence, not just a verdict.** Every violation comes with an occurrence
  sequence that can be replayed on the net.
* **Big state spaces.** Stubborn sets, the sweep-line method, time
  equivalence and symmetry, alone or combined.
* **Measured against CPN Tools.** Statistics, verdicts and report figures are
  compared with CPN Tools 4.0.1 on its own samples and on 48 nets other
  people wrote.
* **No dependencies.** Pure Python 3.8+, on Linux, macOS and Windows. CPN
  Tools is never needed, only optionally used as an oracle.

**Contents:**
[Install](#install) ·
[A five-minute tour](#a-five-minute-tour) ·
[The ideas in one page](#the-ideas-in-one-page) ·
[Writing properties](#writing-properties) ·
[ASK-CTL queries](#ask-ctl-queries-you-already-have) ·
[The state-space report](#the-state-space-report) ·
[Counterexamples](#counterexamples) ·
[Large state spaces](#when-the-graph-is-too-big-reductions) ·
[Is it right?](#is-it-right-agreement-with-cpn-tools) ·
[Your own kind of nets](#your-own-kind-of-nets-profiles-and-plugins) ·
[CPN ML](#what-it-understands-of-cpn-ml) ·
[Command line](#command-line-reference) ·
[Status](#status)

## Install

```bash
pip install cpncheck
```

The latest version from GitHub, or a checkout for development:

```bash
pip install git+https://github.com/GrupoCybersegurancaVirtus/cpncheck
pip install -e ".[test]"
```

The [examples](https://github.com/GrupoCybersegurancaVirtus/cpncheck/tree/main/examples)
are a guided tour, one feature per script, on small nets shipped with them;
`python examples/run_all.py` runs them all. The API is documented in the
docstrings; `pip install pdoc` and `python -m pdoc cpncheck` render them
as a site.

## A five-minute tour

### 1. A net

Five philosophers sit around a table with a chopstick between each pair. To
eat, a philosopher takes the left chopstick, then the right one, eats, and
puts both down. As a Coloured Petri Net
([`dining_deadlock.cpn`](https://github.com/GrupoCybersegurancaVirtus/cpncheck/blob/main/examples/nets/dining_deadlock.cpn)):

![The dining philosophers net: places Think, Has Left, Eat and Unused Chopsticks; transitions Take Left, Take Right and Put Down](https://raw.githubusercontent.com/GrupoCybersegurancaVirtus/cpncheck/main/docs/figures/net.png)

*Places* (circles) hold *tokens*, here coloured values such as `ph(3)` (a
philosopher) or `cs(4)` (a chopstick). A *transition* (box) may occur when
its input places hold the tokens its arcs ask for: `Take Left` takes a
thinking philosopher `p` and the chopstick `Left(p)`. The distribution of
tokens over the places is the *marking*; at the start every philosopher
thinks and every chopstick is unused.

Is this table safe? Can everybody get stuck? Can two philosophers eat at
once?

### 2. Ask

```bash
cpncheck check dining_deadlock.cpn --prop "NODL: AG !dead" --prop "PAIR: EF tokens(Eat) = 2"
```

![The output of cpncheck check: the state-space report, NODL fails with the sequence that reaches the deadlock, PAIR passes](https://raw.githubusercontent.com/GrupoCybersegurancaVirtus/cpncheck/main/docs/figures/terminal.png)

Reading it from the top:

* the **occurrence graph** -- every marking the net can reach -- has 82
  markings and 265 arcs;
* **R1-R5** are CPN Tools' state-space report, which every net gets: here
  there is a deadlock (R1 NO), not every run ends (R2 NO), and so on. They are
  facts about the net, not requirements, so they never fail the check;
* **your properties** are requirements. `NODL` ("it never gets stuck") FAILS,
  and the line under it says how: five `Take Left` in a row. `PAIR` ("two
  philosophers can eat at the same time") PASSES;
* below come the place bounds and the rest of the report.

A failed property makes the command exit with status 1, so it can gate a
build.

### 3. What happened

CPNCheck explored the occurrence graph and looked for a marking where
nothing can occur. With three philosophers instead of five the graph is
small enough to draw:

![The occurrence graph of three philosophers: 14 markings; the path of three Take Left occurrences to the dead marking is highlighted](https://raw.githubusercontent.com/GrupoCybersegurancaVirtus/cpncheck/main/docs/figures/occurrence_graph.png)

If every philosopher takes the left chopstick, no right chopstick is left:
the dead marking. The counterexample is the shortest occurrence sequence
that reaches it, with the binding of every step (`p = ph(1)`, `ph(2)`, ...).

### 4. The same from Python

```python
from cpncheck import CPNModelChecker

checker = CPNModelChecker("dining_deadlock.cpn", properties="""
    NODL "no deadlock": AG !dead
    PAIR "two can eat at once": EF tokens(Eat) = 2
""")
result = checker.check()

r = result.properties["NODL"]
r.status                          # 'FAIL'
r.cex.sequence(bindings=True)     # 'Take Left<p = ph(1)> -> Take Left<p = ph(2)> -> ...'
r.cex.replay(checker.cnet)        # True: re-fired on the net, it really deadlocks
result.properties["PAIR"].status  # 'PASS'
print(result.report())            # the text above
```

`check_cpn(path, ...)` does the same in one call. A result exposes `passed`,
`failures`, `skipped`, `properties`, `stats`, `report()`, `to_dict()` (JSON)
and `latex_table()`.

## The ideas in one page

| Term | Meaning |
|---|---|
| **Marking** | The state of the net: which tokens are in which places (and, in a timed net, the clock). |
| **Occurrence graph** | Every marking reachable from the initial one, with an arc for every transition occurrence between them. Also called the state space. |
| **Dead marking** | A marking where nothing can occur. A deadlock, or a proper end. |
| **SCC, home marking** | Strongly connected components of the graph; a home marking can be reached from every reachable marking (CPN Tools' `ListHomeMarkings`). |
| **CTL** | The logic of the properties. A *path* is one way the net can run. |
| `AG f` | On every path, always `f`: an invariant (*"never two philosophers eating side by side"*). |
| `EF f` | On some path, eventually `f`: reachability (*"two can eat at once"*). |
| `AF f` | On every path, eventually `f`: inevitability (*"every run ends"*). |
| `EG f` | On some path, always `f`. |
| `E[f U g]`, `A[f U g]` | On some / every path, `f` until `g`. |

**Dead markings in CTL.** A run that stops is still a run: CPNCheck gives a
dead marking a loop to itself, as textbook CTL does, so `AF f` fails when a
run can stop before `f`. CPN Tools' ASK-CTL reads its "eventually" (`EV`)
differently at a dead marking, and both readings are available:

![On a graph where M0 leads to M1 (phi holds) and to a dead M2 (phi false): CPNCheck's AF phi is false, CPN Tools' EV(phi) is true](https://raw.githubusercontent.com/GrupoCybersegurancaVirtus/cpncheck/main/docs/figures/dead_markings.png)

Four techniques are kept apart, because they establish different things:

| Technique | What a verdict means |
|---|---|
| `ctl` | Explicit-state CTL on the occurrence graph, with real token values. True *for the initial marking it was given*. |
| `scc` | Home markings from the SCC decomposition, as CPN Tools computes them. |
| `structural` | Static analysis of guards (in profiles). Holds for **every** input, which no single state space can show. |
| `testing` | Conformance with a reference function on a set of inputs. Not a temporal property. |

## Writing properties

Requirements go in a file, on the command line (`--prop`) or in Python
(`properties=`), one per line, with an optional id and name:

```
# dining.props
ME "neighbours never eat together": AG !(has(Eat, ph(1)) & has(Eat, ph(2)))
NOEAT "philosopher 1 never eats":   AG !has(Eat, ph(1))
CS: AG tokens("Unused Chopsticks") <= 5
```

```bash
cpncheck check dining.cpn --props dining.props --prop "AF has(Eat, ph(3))"
```

| Proposition | True in a marking where |
|---|---|
| `dead` | nothing can occur |
| `enabled(T)` | transition `T` can occur |
| `marked(P)` / `empty(P)` | place `P` holds some token / none |
| `tokens(P) op k` | `P` holds `op k` tokens (`op`: `< <= = >= > <>`) |
| `enabled_count(T) op k` | `T` can occur in `op k` ways |
| `has(P, v)` | `P` holds the token `v`, any CPN ML value: `ph(1)`, `(1, "COL")` |

Combine them with `!`, `&`, `|`, `->` and the operators `AG AF EF EG`,
`E[f U g]`, `A[f U g]`. A name is bare (`Eat`, `Sender/Send_Packet`) or
quoted (`"Unused Chopsticks"`), and refers to a full path, every element of a
page, or every element of that name; a name that matches nothing is an error
that lists the names there are. The full grammar is in
[`cpncheck/query.py`](https://github.com/GrupoCybersegurancaVirtus/cpncheck/blob/main/cpncheck/query.py).

## ASK-CTL queries you already have

A file of ASK-CTL queries, as one would evaluate it in CPN Tools after
*Enter State Space*, is accepted as it is:

```sml
fun Eating n = Mark.Top'Eat 1 n <> empty;
val AlwaysAgain = eval_node (INV (POS (NF ("eating", Eating)))) InitNode;
eval_node (POS (EXIST_MODAL (AF ("put", fn a => ArcToTI a = TI.Top'Put_Down_Chopsticks 1), TT))) InitNode;
```

```bash
cpncheck check dining.cpn --askctl dining.sml
```

Every top-level `eval_node F InitNode` becomes a property, named after its
`val` (or `Q1`, `Q2`, ...). The rest of the file is CPN ML, with the net's
declarations and CPN Tools' state-space functions: `Mark`, `OutArcs`,
`ArcToBE`, `Bind`, `TI`, `SearchNodes`, `PredAllNodes`, `ListDeadMarkings`,
`NodesInPath`, the SCC functions and more.

The formulas mean exactly what `ASKCTL.sml`, shipped with CPN Tools, makes
them mean -- which is not always textbook CTL. `EV` holds vacuously at a dead
marking (figure above), but `POS (INV a)`, `POS (ALONG a)` and `EV (INV a)`
are decided on the SCC graph, where it does not. The tests hold 49 queries
written to tell those readings apart, and every one gets CPN Tools' verdict
([`cpncheck/askctl_input.py`](https://github.com/GrupoCybersegurancaVirtus/cpncheck/blob/main/cpncheck/askctl_input.py)).

The other way round, `cpncheck askctl model.cpn -o queries.sml` writes the
checker's questions as an ASK-CTL script to run in CPN Tools.

## The state-space report

A net no specific profile recognises -- that is, almost any net -- gets the
report CPN Tools' state-space tool produces:

| | Property | As a formula |
|---|---|---|
| R1 | Deadlock freedom | `AG !dead` |
| R2 | Termination | `AF dead` |
| R3 | Home marking | one terminal SCC |
| R4 | No dead transitions | `forall t: EF enabled(t)` |
| R5 | All transitions live | `forall t: AG EF enabled(t)` |

They are printed YES/NO and never fail a check: a protocol meant to stop has
dead markings and is not wrong for it. Then come the integer and multiset
bounds of every place, the dead and live transition instances, and the
fairness of each transition (impartial, fair, just). Every figure is compared
with CPN Tools' own functions (`ListDeadTIs`, `UpperMultiSet`,
`ListFairTIs`, ...) by the oracle tests.

## Counterexamples

A violated property hands back evidence. `result.properties[id].cex` is a
`Counterexample`:

| Kind | When | What it holds |
|---|---|---|
| `finite` | a marking breaks a safety property (`AG`) | the shortest occurrence sequence to it, with bindings |
| `lasso` | a liveness property (`AF`) never comes true | a prefix, then a cycle the net can repeat forever |
| `witness` | no path is kept (sweep-line) or none is needed | the violating marking itself |
| `structural` | a profile's static check fails | an input on which the problem really happens |
| `conformance` | the net disagrees with a reference | the input and both answers |

```python
cex.sequence(bindings=True)   # Take Left<p = ph(1)> -> ...
cex.replay(checker.cnet)      # True
cex.to_dict()                 # the whole trace, for a report or a test
```

`cpncheck check model.cpn --trace` prints them in full.

**`replay()` is a certificate.** It re-fires the sequence with the net's
firing rule -- not with the search that found it -- and checks that it ends
where the counterexample says (and, for a lasso, that the cycle closes). A bug
in the search cannot forge a trace that replays; the test suite replays every
counterexample of every mutant, and requires a tampered one to fail.

## When the graph is too big: reductions

Up to 1 000 000 markings are explored by default (`--max-nodes`,
`max_nodes=`); beyond it the state-space properties get **no verdict** rather
than a guess. That much costs memory: the queue protocol of the Coloured
Petri Nets book, cut off at a million markings (5.6 million arcs), took 279 s
and 3.9 GiB. Lower the budget on a small machine -- or reduce:

![Markings kept in memory to decide AG !dead. Six identical workers: full graph 729, sweep-line 433, stubborn sets 127, symmetry 28, stubborn plus symmetry 13, sweep plus stubborn plus symmetry 8. Eight independent pipelines: full graph 6561, sweep-line 3585, stubborn sets 17, sweep plus stubborn 4.](https://raw.githubusercontent.com/GrupoCybersegurancaVirtus/cpncheck/main/docs/figures/reductions.png)

Each reduction explores less, and each **declares what it preserves**: a
property it cannot decide gets no verdict, with the reason, never a wrong one.

| Your net... | Use | Decides |
|---|---|---|
| has parts that work independently | `--reduction stubborn` | everything (per property, the smallest graph that provably gives the same verdict) |
| makes progress (a clock, a counter, done jobs) | `--reduction sweep --progress MEASURE` | properties of single markings: `AG f`, `EF f`, `!EF f` |
| is timed, and time only moves on | `--reduction equivalence` | everything but home markings |
| treats some values alike (identical workers, a ring) | `--reduction symmetry --symmetry SETS=KIND` | everything but home markings and properties naming a permuted value |
| several of the above | join them with `+`: `stubborn+symmetry`, `sweep+stubborn`, ... | what every part preserves |

### Stubborn sets (partial-order reduction)

Components that do not interact make the graph interleave their steps in
every order: `n` independent pipelines have 3^n markings, although every
order ends in the same place. A *stubborn set* (Valmari) picks the steps that
can go first without losing anything that matters to the property, so the
reduced graph is often linear in `n`.

What matters depends on the property, so up to four graphs are built:

| Graph | Conditions | Preserves | Used for |
|---|---|---|---|
| `deadlock` | D0-D2 | every dead marking; existence of an infinite run | `AF dead`, `AG(dead -> f)`, home markings of a terminating net |
| `safety` | D0-D2 + an up-set for `!f` (Kristensen & Valmari 2000) | reachability of a marking violating `f` | `AG f`, `!EF f`, `EF f` with propositional `f` |
| `stutter` | D0-D2 + C2, C3, C4 (Gerth et al. 1999) | every CTL formula without next-time | `AF`, `EF`, `EU`, `AG EF` |
| `full` | none | everything | whatever the theorems do not cover |

A property is first split -- `forall` into instances, `AG` of a conjunction
into one `AG` per conjunct -- because a part that observes less reduces more;
the report says which graph decided each part. On the tree nets pyruleanalyzer
generates, a random forest of 100 trees has 103 markings in the deadlock
graph instead of about 1.3 × 10^30. Stubborn sets are not sound with a global
clock, priorities, inhibitor or reset arcs; such nets are always checked on
the full graph.

### The sweep-line method

The sweep explores the markings in the order of a *progress measure* and
forgets the ones it has left behind, so memory holds a moving window, not the
whole graph. The generalised method (Kristensen & Mailund 2002) is used: an
arc back to less progress starts a new sweep, so **any** measure is correct --
a bad one only costs time. A measure is a sum of `[k *] tokens(P)`,
`[k *] sum(P)`, `[k *] clock` and constants, or a Python function; a timed
net needs none, its clock never goes back. Path properties (`AF`, `EG`,
`AG EF`) get no verdict, and a violation is reported as the marking, without
a path.

### Equivalence and symmetry

Both explore one representative per class of equivalent markings (the
*quotient*), which gives the full graph's CTL verdicts when equivalent
markings reach the same classes and the property cannot tell them apart.

* **Time equivalence** (timed nets): markings equal up to a shift of time are
  one class. Exact unless an inscription reads `time()`, which is refused by
  name. A graph infinite only because time goes on gets a finite quotient.
* **Symmetry**: the colour sets whose values may be permuted, all at once
  (`WORKER=all`) or by rotation, several together (`PH,CS=rotation`). It is
  checked, not assumed: the initial marking must be invariant, and every
  representative is tested. A net that breaks the symmetry gets no verdicts;
  a property that names a permuted value (`has(Eat, ph(1))`) gets none either.
* **Your own canonical form** (`equivalence=f`): consistency is tested on
  sampled markings, and the verdicts are reported as conditional on it.

### Combining them

They act on different things -- which successors are explored, which markings
are kept, which markings are told apart -- so they compose:

```bash
cpncheck check workers.cpn --reduction stubborn+symmetry --symmetry WORKER=all
cpncheck check workers.cpn --reduction sweep+stubborn --progress 'tokens(Done)'
cpncheck check loop.cpn --reduction equivalence+symmetry --symmetry TOKEN=all
```

| Combination | How |
|---|---|
| `equivalence+symmetry` | one canonical form: the symmetry representative of the time representative (they commute) |
| `stubborn` + a quotient | the `deadlock` and `safety` stubborn graphs explored on class representatives; other properties on the plain quotient |
| `sweep` + a quotient | the sweep over representatives |
| `sweep+stubborn` | the sweep over the stubborn successors of each part |

The `stutter` stubborn graph is never combined (its cycle proviso lives on the
search stack, which neither a quotient nor the sweep keeps), and stubborn sets
are dropped with a warning where they do not apply. Every reduction and
combination is compared with the full graph by the tests
([`test_reduction.py`](https://github.com/GrupoCybersegurancaVirtus/cpncheck/blob/main/tests/test_reduction.py),
[`test_sweepline.py`](https://github.com/GrupoCybersegurancaVirtus/cpncheck/blob/main/tests/test_sweepline.py),
[`test_equivalence.py`](https://github.com/GrupoCybersegurancaVirtus/cpncheck/blob/main/tests/test_equivalence.py),
[`test_combined.py`](https://github.com/GrupoCybersegurancaVirtus/cpncheck/blob/main/tests/test_combined.py)).

## Is it right? Agreement with CPN Tools

Two claims, and how each is held up.

**Agreement.** `cpncheck oracle model.cpn` runs the CPN Tools 4.0.1 simulator
headlessly, enters the state-space tool the way *Enter State Space* does,
builds the graphs, evaluates the same questions and compares every number.

| Compared with CPN Tools | Result |
|---|---|
| CPN Tools' own sample models | 16 of 24 read and explored; the 7 compared agree on every statistic; the 8 refused are outside an occurrence graph (side effects, random values, real time) |
| [48 nets other people wrote](https://github.com/GrupoCybersegurancaVirtus/cpncheck/blob/main/tests/corpus/RESULTS.md) | no reading errors; every explored net CPN Tools compiles agrees on the graph and on every report figure (timed nets by containment) |
| The CPN ML library | 236 expressions, same value or same exception |
| ASK-CTL queries | 49 queries, same verdict |
| Constructs whose meaning the documentation leaves open | measured in CPN Tools ([`tests/nets/features`](https://github.com/GrupoCybersegurancaVirtus/cpncheck/tree/main/tests/nets/features)) |

The oracle needs CPN Tools, CPN IDE (for its Access/CPN library) and a 32-bit
Java 8 with `jjs`, on Windows; `CPNToolsOracle().missing()` lists anything
absent, and its tests skip themselves without it.

**Sensitivity.** Agreeing on correct nets would also be reached by two
checkers that always say "true". `cpncheck mutants` derives one mutant per
property -- a small edit of a guard, an inscription or an arc that makes that
property false -- and the tests require each mutant to be caught.

## Your own kind of nets: profiles and plugins

What CPNCheck asks of a net comes from a *profile*. The built-in one is the
state-space report. A profile for your own kind of nets says which places and
transitions play which role and which properties they must satisfy -- as
formulas, data rather than code:

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

Each formula explains itself when it fails and renders to ASK-CTL, so the
Python check and the CPN Tools script are the same question by construction.
A profile may also add structural checks, a conformance test against a
reference implementation and mutation operators. Published as a plugin, it
is found when installed:

```toml
[project.entry-points."cpncheck.profiles"]
my_nets = "my_package.cpn_profile:PROFILE"
```

[pyruleanalyzer](https://github.com/GrupoCybersegurancaVirtus/pyruleanalyzer)'s
profile for the nets it generates from decision trees, random forests and
gradient boosting is one such plugin; CPNCheck itself knows nothing about
trees. The example
[`10_custom_profile.py`](https://github.com/GrupoCybersegurancaVirtus/cpncheck/blob/main/examples/10_custom_profile.py)
writes one step by step.

## What it understands of CPN ML

Guards and inscriptions are parsed and compiled, not pattern-matched:
`if`, `let`, `case`, `fn`, records (flexible ones too), lists, multisets,
`SOME`/`NONE`, `datatype`, exceptions, references, operator sections and
composition, with SML's precedences.

* **The library is CPN Tools' own**
  ([`cpncheck/mllib.py`](https://github.com/GrupoCybersegurancaVirtus/cpncheck/blob/main/cpncheck/mllib.py)):
  the SML Basis functions nets use, CPN Tools' list and multiset functions,
  and per colour set `size`, `ord`, `col`, `legal`, `mkstr`, `all`, ...
* **A net describes itself**: its own `val` and `fun` declarations are read
  and used. Where it leaves a function undeclared, supply it:
  `check_cpn("model.cpn", prelude={"f": lambda x: ...})`.
* **Also read**: hierarchy and fusion sets, every kind of colour set CPN
  Tools declares, free variables enumerated over their colour set,
  priorities, guards that bind variables, code segments without side effects,
  inhibitor and reset arcs, transitions without input arcs, and timed nets
  with integer time.
* **Refused by name**: synchronous channels, code with side effects,
  real-valued time and random values. Anything outside the fragment raises
  `UnsupportedNet` rather than being misread -- a wrong reading of a guard
  would be a wrong verdict.

## Command-line reference

| Command | Does |
|---|---|
| `cpncheck check NET` | verify; exit status 1 if a property of yours fails |
| `cpncheck askctl NET -o FILE` | write the checker's questions as an ASK-CTL script for CPN Tools |
| `cpncheck mutants NET DIR` | write one mutant per property (profiles that supply mutation operators) |
| `cpncheck oracle NET` | run CPN Tools headlessly and compare |

| `check` option | |
|---|---|
| `--prop FORMULA`, `--props FILE` | your properties ([Writing properties](#writing-properties)) |
| `--askctl FILE` | ASK-CTL queries ([ASK-CTL](#ask-ctl-queries-you-already-have)) |
| `--reduction KIND[+KIND]` | `stubborn`, `sweep`, `equivalence`, `symmetry` or a combination |
| `--progress MEASURE`, `--symmetry SETS=KIND`, `--equivalence time` | settings of the reductions |
| `--max-nodes N` | the budget (default 1 000 000) |
| `--trace` | every counterexample in full |
| `--json FILE`, `--latex` | the verdicts as JSON or a LaTeX table |
| `-O KEY=VALUE` | a setting for the net's profile |

## Status

Version 0.2.1. Extracted from
[pyruleanalyzer](https://github.com/GrupoCybersegurancaVirtus/pyruleanalyzer),
which now uses it through the plugin above
([history](https://github.com/GrupoCybersegurancaVirtus/cpncheck/blob/main/docs/history/extraction-from-pyruleanalyzer.md)).
[ROADMAP.md](https://github.com/GrupoCybersegurancaVirtus/cpncheck/blob/main/ROADMAP.md)
says what is supported and what remains;
[CHANGELOG.md](https://github.com/GrupoCybersegurancaVirtus/cpncheck/blob/main/CHANGELOG.md)
what changed. The figures in this page are drawn from real runs by
[`docs/figures/make_figures.py`](https://github.com/GrupoCybersegurancaVirtus/cpncheck/blob/main/docs/figures/make_figures.py).

MIT licensed.
