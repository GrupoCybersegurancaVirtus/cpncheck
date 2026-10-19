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
cpncheck check model.cpn                     # the state-space report
cpncheck check model.cpn --props my.props    # plus your own properties
cpncheck check model.cpn --json verdicts.json --latex
cpncheck askctl model.cpn -o askctl.sml      # the same questions, for CPN Tools
cpncheck mutants model.cpn mutants/          # one mutant per property (profiles
                                             # that supply mutation operators)
cpncheck oracle model.cpn                    # run CPN Tools and compare
```

```python
from cpncheck import check_cpn

result = check_cpn("model.cpn", properties="AG !(has(Eat, ph(1)) & has(Eat, ph(2)))")
print(result.report())
assert result.passed
for r in result.failures:
    print(r.id, r.detail)        # the counterexample, rendered
```

`ModelCheckResult` exposes `passed`, `failures`, `skipped`, `properties`,
`stats`, `oracle`, `report_data`, `report()`, `to_dict()`, `latex_rows()` and
`latex_table()`.

**CPNCheck does not need CPN Tools.** It is pure Python with no dependencies:
reading the `.cpn`, the CPN ML, the occurrence graph, CTL, reduction and
counterexamples are all its own. CPN Tools is only used by `cpncheck oracle`,
the optional cross-check that proves the answers right; those tests skip
themselves when it is not installed, and a test runs the checker with the
oracle module blocked so that this cannot change by accident.

### Any net: the state-space report

A net that no specific profile recognises gets the default one, which reports
what CPN Tools' state-space report does:

```bash
cpncheck check SimpleProtocol.cpn
```

| | | |
|---|---|---|
| R1 | Deadlock freedom | `AG !dead` |
| R2 | Termination | `AF dead` |
| R3 | Home marking | one terminal SCC |
| R4 | No dead transitions | `forall t: EF EN(t)` |
| R5 | All transitions live | `forall t: AG EF EN(t)` |

They are facts, printed YES/NO, and never fail a check -- a protocol meant to
stop has dead markings and is not wrong for it.

### Your own properties, without Python

Requirements go in a file (or on the command line) and fail the check when
violated, with a counterexample:

```
# dining.props
ME "neighbours never eat together": AG !(has(Eat, ph(1)) & has(Eat, ph(2)))
NOEAT "philosopher 1 never eats":   AG !has(Eat, ph(1))
CS: AG tokens("Unused Chopsticks") <= 5
```

```bash
cpncheck check DiningPhilosophers.cpn --props dining.props --prop "AF has(Eat, ph(3))"
```

Propositions: `dead`, `enabled(T)`, `marked(P)`, `empty(P)`,
`tokens(P) op k`, `enabled_count(T) op k`, `has(P, v)` with `v` any CPN ML
value; connectives `! & | ->`; operators `AG AF EF EG`, `E[f U g]`,
`A[f U g]`. Names are bare or quoted and refer to a full path, a page's
element or every element of that name. The full grammar is in
[`cpncheck/query.py`](cpncheck/query.py); from Python, pass
`properties=` to `check_cpn` or `CPNModelChecker`. Every user property on two
CPN Tools samples is checked against CPN Tools' own ASK-CTL by the tests. Below them come the integer
bounds of every place and the dead and live transition instances. Every figure
is compared with CPN Tools' own functions (`ListDeadTIs`, `ListLiveTIs`,
`UpperInteger`, `LowerInteger`) by the oracle tests.

**Examples.** [examples/](examples/) is a guided tour, one feature per
script, on small nets shipped with them: the quickstart, the layers under
`check_cpn`, the property language, counterexamples, timed nets, the four
reductions, writing a profile with mutation operators and a conformance
test, ASK-CTL and report formats, the CPN Tools oracle and the command line.
`python examples/run_all.py` runs them all.

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

**A structural finding comes with an input.** A profile's structural check
(guard disjointness, for the tree profile) holds or fails for *every* input,
so a failure names no particular run — but it hands back a point on which the
problem really happens, as the counterexample's `input`, to be checked with
`samples=[...]`.

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

## State explosion: partial-order reduction

A net made of components that do not interact until the end has an occurrence
graph that interleaves them in every order. A random forest of `n` trees has
exactly `2^n + 2` markings, although every order leads to the same vote.

```bash
cpncheck check model.cpn --reduction stubborn
```

```python
result = check_cpn("model.cpn", properties="AF dead", reduction="stubborn")
```

With `reduction="stubborn"` every property is decided on a *stubborn-set*
reduced graph (`cpncheck/reduction.py`) that provably gives the full graph's
verdict. Which reduced graph depends on what the property needs:

| Graph | Conditions | Preserves | Used for |
|---|---|---|---|
| `deadlock` | D0–D2 (Valmari) | every dead marking; existence of an infinite run | `AF dead`, `AG(dead → ψ)`, home markings of a terminating net |
| `safety` | D0–D2 + an up-set for `¬ψ` (Kristensen & Valmari 2000) | reachability of a marking violating `ψ` | `AG ψ`, `!EF χ`, `EF χ` with `ψ`, `χ` propositional |
| `stutter` | D0–D2 + C2 (one invisible element or all), C3 (cycle proviso), C4 (Gerth et al. 1999) | every CTL-X formula | `AF`, `EF`, `EU`, `AG EF` |
| `full` | none | everything | whatever the theorems do not cover |

A property is first split — `forall` into its instances, `AG` of a conjunction
or of a bound on many places into one `AG` per conjunct or per place — because
a part that observes fewer places reduces more. The report says, per property,
which graph decided it.

On the tree nets the deadlock graph has `n + 3` markings for `n` trees (a
forest of 100 trees: 103 instead of about 1.3 × 10^30). One property does not
reduce: `AF EN(Vote)` observes the output place of every tree, so every leaf is
visible and none can be reordered — for large forests it is reported without a
verdict, and the report says why. The reduction is checked the hard way: on
both fixture nets and all their mutants, every verdict equals the full graph's
and every reduced counterexample replays (`tests/test_reduction.py`). CPN Tools
has no such reduction, so `oracle` values are only produced without it.

## State explosion: the sweep-line method

```bash
cpncheck check model.cpn --reduction sweep --progress "tokens(Done) - tokens(Todo)"
```

```python
result = check_cpn("model.cpn", properties="AG tokens(Buffer) <= 3",
                   reduction="sweep", progress="tokens(Done) - tokens(Todo)")
```

The sweep-line method (`cpncheck/sweepline.py`) explores the markings in the
order of a *progress measure* and forgets the ones it has left behind, so it
needs memory for a moving window of the graph, not for all of it. The
generalised form is used (Kristensen & Mailund 2002): an arc to a marking with
less progress makes it *persistent* and starts a new sweep from it, so every
reachable marking is explored with **any** measure. A bad measure costs time
(markings explored again), never a wrong verdict.

It decides properties of single markings: `AG ψ`, `EF χ` and `!EF χ` for
state predicates, which may mention `dead` and `enabled`. Path properties
(`AF`, `EG`, `AG EF`, home markings) get no verdict, with the reason, because
the arcs are not kept; a violation is reported as the marking, not a path.

A measure is a sum of `[k *] tokens(P)`, `[k *] sum(P)` (the integer values of
the tokens), `[k *] clock` and constants, or a Python function of the marking.
A timed net needs none: its clock never goes back. On a finite variant of CPN
Tools' TimedResourceAlloc, 16 114 markings are explored with at most 2 293
stored, in one sweep. `tests/test_sweepline.py` compares every verdict with
the full graph on both fixture nets and all their mutants, under no measure, a
token count and an arbitrary non-monotone function.

## State explosion: equivalence and symmetry

```bash
cpncheck check timed.cpn --reduction equivalence            # time equivalence
cpncheck check dining.cpn --reduction symmetry --symmetry PH,CS=rotation
```

```python
check_cpn("dining.cpn", reduction="symmetry", symmetry={"PH,CS": "rotation"})
check_cpn("model.cpn", reduction="equivalence", equivalence=my_canonical_form)
```

Both explore one representative per class of equivalent markings — the
*quotient* graph (`cpncheck/equivalence.py`, `cpncheck/symmetry.py`). It
gives the full graph's CTL verdicts when the equivalence is *consistent*
(equivalent markings reach the same classes) and the property cannot tell
equivalent markings apart.

* **Time equivalence** (timed nets): markings equal up to a shift of time are
  one class. Exact unless an inscription reads `time()`, in which case it is
  refused by name. A net whose graph is infinite only because time goes on
  gets a finite quotient; on the TimedResourceAlloc variant, 16 114 markings
  become 970 classes.
* **Symmetry**: the colour sets whose values may be permuted, all at once or
  by rotation, several together by position (`PH,CS=rotation`). The
  conditions are checked, not assumed: the initial marking must be invariant
  under each generator, and every explored representative is tested — the
  successors of `g(M)` must be the images of those of `M`. A guard that breaks
  the symmetry fails the test and the verdicts are withheld; a property that
  singles out a permuted value (`has(Eat, ph(1))`) gets no verdict. Dining
  philosophers: 11 markings, 3 classes; DistributedDataBase: 109 markings, 11
  classes.
* **Your own canonical form**: consistency is tested on sampled markings,
  not proved, and the verdicts are reported as conditional on the test.

Not preserved by any of them: the home-marking property (a class can be a
home class while none of its markings is a home marking) and the graph
statistics. `tests/test_equivalence.py` compares every verdict with the full
graph, and checks that a symmetry the net does not have, an equivalence that
merges different behaviours, and a property naming a permuted value all end
without a verdict rather than with a wrong one.

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
their SML precedences and associativities, lists, tuples, records (including
flexible patterns `{data, ...}`), multisets, characters, string escapes,
sequences `(e1; e2)`, `SOME`/`NONE`, operator sections `(op +)`, composition
`o`, references (`globref`, `!`) and type annotations. The expression compiles
to a closure, so firing stays fast.

**The standard library is CPN Tools' own** (`cpncheck/mllib.py`): the SML
Basis functions nets use (`Int`, `Real`, `Math`, `String`, `Char`, `Option`,
`List`, `ListPair`), CPN Tools' list functions (`mem`, `rm`, `contains`,
`intersect`, `listsub`, `ins_new`, `sort`...), its multiset functions (`cf`,
`size`, `ms_to_col`, `ext_col`, `filter`, `==`, `<<=`...) and, per colour
set, `size`, `ord`, `col`, `legal`, `mkstr`, `mkstr_ms`, `all`, `mult`. Each
name follows SML's calling convention (`Int.max (a, b)` takes a pair), and
each is checked against CPN Tools: `tests/data/mllib_cases.txt` was
evaluated by CPN Tools itself and `tests/test_mllib.py` requires the same
value -- or the same exception -- from CPNCheck. As in CPN Tools, a multiset
is also a list (`map f (CS.all ())`), and a list on an arc of a place that
does not hold lists is the multiset of its elements.

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

Also read: multisets anywhere in an expression, input arcs that are
expressions rather than patterns, enumeration constants, `index` colour sets,
`unit with e`, `bool with (no, yes)`, `union`, `subset ... by`/`with`, colour
sets written only as text, fusion sets, double arcs and several prime pages,
variables defined by a guard, transition priorities, transitions without
input arcs, code segments without side effects (`input`/`output`/`action`),
inhibitor and reset arcs, and timed nets with integer time (timestamps, `@+`
delays on arcs and transitions, `@+` on input arcs, `time()`, the
earliest-time rule). Where CPN Tools' documentation leaves a meaning open, it
was measured in CPN Tools (`tests/nets/features`). Not supported: synchronous
channels, code with side effects, real-valued time (`@++`) and random values
(`CS.ran()`, `discrete`, `exponential`) — the last two have no occurrence
graph. Anything outside the
fragment raises `UnsupportedNet` rather than being mis-read — a wrong reading
of a guard is a wrong verdict.

**Timed nets.** When a timed place holds several ready tokens of the value a
binding takes, each choice of token is its own successor. CPN Tools 4.0.1
explores a subset of those choices (not the same one on every run), so timed
nets are compared with it by containment: `oracle.compare_graph_containment`
checks that every node and arc it finds is in CPNCheck's graph. Stubborn-set
reduction is not sound with a global clock or with priorities; such nets are
always checked on the full graph.

How far this reaches is measured on the 24 example models CPN Tools ships
with: `python examples/cpntools_samples.py --oracle`. Today 16 are read and
explored, the 7 whose occurrence graph fits the budget agree with CPN Tools
on every statistic, and the 8 refused are all outside the target (side
effects, random values, real time). The plan to make CPNCheck check any net CPN Tools can
analyse is in [ROADMAP.md](ROADMAP.md).

## Profiles and plugins

What CPNCheck asks of a net comes from a *profile*. The built-in one, the
state-space report, applies to every net. A package can publish a profile for
its own kind of nets as a plugin, and CPNCheck picks it up when it is
installed:

```toml
[project.entry-points."cpncheck.profiles"]
my_nets = "my_package.cpn_profile:PROFILE"
```

A profile receives its settings as `options`, which CPNCheck hands on without
reading them -- `CPNModelChecker(path, options={...})`, or `-O key=value` on
the command line. A plugin that fails to load is reported as a warning and
skipped. pyruleanalyzer's profile for the nets it generates from decision
trees, random forests and gradient boosting is one such plugin: CPNCheck itself
knows nothing about trees, and its tests run with no plugin at all.

## Status

Pre-release, extracted from
[pyruleanalyzer](https://github.com/GrupoCybersegurancaVirtus/pyruleanalyzer),
which now uses it through the plugin above.

Agreement with CPN Tools is measured, not assumed: 28 nets — two correct ones
and every mutant of each — agree on every statistic and every verdict, with 81
*false* verdicts confirmed by CPN Tools itself. See [MIGRATION.md](MIGRATION.md)
for what remains.

MIT licensed.
