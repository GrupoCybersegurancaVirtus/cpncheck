# Extraction from pyruleanalyzer — state and plan

> **Later (step 8, see ROADMAP.md):** the tree profile and its mutation
> operators -- `cpncheck/profiles/ml_trees.py` and `ml_trees_mutants.py` below
> -- left CPNCheck for pyruleanalyzer (`pyruleanalyzer/cpn_profile.py`,
> `pyruleanalyzer/cpn_mutants.py`), which publishes the profile as a
> `cpncheck.profiles` plugin. The checker's `class_labels`, `feature_names`,
> `classifier` and `use_final` became profile `options` and a `reference`. This
> file describes the extraction as it was done and is not updated further.

CPNCheck was extracted from `pyruleanalyzer`.

* **Phase 1 — done.** Mechanical extraction: code moved and split, imports
  rewritten, nothing redesigned.
* **Phase 2 — done.** Selectors, formulas as data, profiles, and one AST
  rendered to both backends. The checker no longer contains any knowledge of
  what the nets compute.
* **Step 4 — done.** The structural and conformance techniques, the mutation
  operators and the property catalog are all generic or profile-supplied. The
  only ML left in the package is under `cpncheck/profiles/`.
* **Step 6 — done.** Counterexamples are objects: bindings and markings along
  the trace, lassos for the liveness properties, a witness input for guard
  overlap, and `replay()` as a certificate.
* **Step 3 — done.** The generated ASK-CTL was checked against CPN Tools on 28
  nets, and the hand-written generator deleted.
* **Step 5 — done.** A real CPN ML parser, colour sets, binding enumeration,
  and a net that declares its own functions.

`pyruleanalyzer` is **not yet modified** and does not depend on CPNCheck; it
still carries its own copy. Nothing there breaks until step 7 below -- the only one left -- is done
deliberately.

## 1. The modules

| CPNCheck module | Origin | What it does |
|---|---|---|
| `cpncheck/net.py` | `cpn_semantics.py` 27–225 | parse the `.cpn` XML, and nothing else |
| `cpncheck/coloured.py` | `cpn_statespace.py` 48–674 | the CPN ML fragment; flatten; fire |
| `cpncheck/statespace.py` | `cpn_statespace.py` 676–893 | occurrence graph, SCCs |
| `cpncheck/ctl.py` | `model_checker.py` 528–628 | the CTL fixpoints |
| `cpncheck/selectors.py` | **new (phase 2)** | name places/transitions by pattern |
| `cpncheck/formula.py` | **new (phase 2)** | CTL formulas as data; they explain themselves |
| `cpncheck/askctl.py` | **new (phase 2)** | render a formula as an ASK-CTL query |
| `cpncheck/profile.py` | **new (phase 2)** | the caller's side of the interface |
| `cpncheck/structural.py` | **step 4**, from `model_checker.py` | guard boxes: what holds for every input |
| `cpncheck/conformance.py` | **step 4**, from `model_checker.py` | run to a dead marking, compare with a reference |
| `cpncheck/counterexample.py` | **new (step 6)** | the evidence a violated property hands back |
| `cpncheck/cpnml.py` | **new (step 5)** | lexer, parser and compiler for CPN ML |
| `cpncheck/colourset.py` | **new (step 5)** | colour sets, their domains, and a net's declarations |
| `cpncheck/profiles/ml_trees.py` | **phase 2**, from `model_checker.py` | the tree nets: structure, catalog, formulas |
| `cpncheck/profiles/ml_trees_mutants.py` | **step 4**, from `cpn_mutants.py` | the sixteen tree mutation operators |
| `cpncheck/properties.py` | `model_checker.py` 115–239 | the property descriptors; no catalog of its own |
| `cpncheck/result.py` | `model_checker.py` 241–525, 1476–1515 | verdicts, text/JSON/LaTeX reports |
| `cpncheck/checker.py` | `model_checker.py` 631–1473 | orchestration; profile-driven |
| `cpncheck/oracle.py` | `cpntools_oracle.py` | run CPN Tools 4.0.1 headless |
| `cpncheck/mutation.py` | `cpn_mutants.py` | `CPNDocument`, the operator framework and the driver |
| `cpncheck/cli.py` | new | `cpncheck check / askctl / mutants / oracle` |

Not extracted, staying in pyruleanalyzer: `cpn_tools_exporter.py` (it *builds*
nets out of rules) and `cpn_semantics.evaluate` (the per-family reference
evaluator).

## 2. How a caller states their own properties

A `Profile` answers what the generic layer cannot. `CPNModelChecker` asks it
for the groups to quantify over, the formulas to evaluate, the token domain,
and how an input is written into the initial marking; then it evaluates and
reports. It never looks at a place name itself.

```python
from cpncheck import CPNModelChecker
from cpncheck.formula import AF, AG, Dead, MaxTokens
from cpncheck.profile import Profile
from cpncheck.selectors import Places

class MyProfile(Profile):
    name = "my nets"
    catalog = my_property_descriptors        # ids of my own choosing

    def matches(self, net):
        return any(p["name"] == "Done" for p in net.places)

    def ctl_formulas(self, net, groups, labels):
        return collections.OrderedDict([
            ("T1", AF(Dead().phrased("the end"))),
            ("T2", AG(MaxTokens(Places(name="Done"), 1))),
        ])

    def scc_properties(self, net, groups):
        return collections.OrderedDict((("T3", "home"),))

CPNModelChecker("mine.cpn", profile=MyProfile()).check().report()
```

A profile registered with `cpncheck.profile.register` is found automatically by
`detect`, most specific first. `tests/test_generic.py` drives the whole checker
with a profile defined inside the test, which is the standing proof that this
works.

### What formulas are available

`Dead`, `Marked`, `AllMarked`, `MaxTokens`, `TokensIn`, `Enabled`,
`EnabledCount`; `Not`, `And`, `Or`, `Implies`; `AG`, `AF`, `EF`, `EU`; and
`ForEach`, which quantifies over a group and attributes a violation to the
member that failed. All twenty catalog properties are written with these in
`profiles/ml_trees.py`.

Two things every formula does:

* **it explains itself.** `counterexample(ctx)` returns a
  `Counterexample`: `AG` the shortest occurrence sequence to a violating
  marking, asking the operand *why that marking is bad*; `AF` a maximal
  sequence that never reaches the goal, as a lasso when the run is infinite;
  `Not(EU(...))` the sequence witnessing the until. `explain(ctx)` is just its
  rendering.
* **it renders to ASK-CTL.** `cpncheck/askctl.py` turns the same tree into the
  CPN ML query, so the Python check and the CPN Tools script cannot be asked
  different questions. Before phase 2 they were written by hand side by side.

## 3. What is still domain-specific

Phase 2 moved the catalog, the structure and the formulas out of the checker;
step 4 did the same for the two non-CTL techniques, the mutation operators and
the property descriptors. What a profile now supplies, all of it optional:

| Hook | What it answers |
|---|---|
| `matches` / `family` | is this one of my nets, and what do I call it |
| `unavailable` | properties this net has that this run cannot decide |
| `resolve_groups` | the domains `ForEach` quantifies over |
| `ctl_formulas` | the temporal properties, as formulas |
| `scc_properties` | the properties answered from the SCC decomposition |
| `static_checks` | verdicts that need no occurrence graph |
| `conformance` | comparison with a reference implementation |
| `label_domain` | the admissible output tokens |
| `as_input_token` / `input_places` | how another input is written into the net |
| `mutation_operators` / `analyse_for_mutation` | the faults that must be caught |
| `catalog` | the descriptors verdicts are reported under |

Nothing domain-specific remains in the generic layer. Step 5 removed the last
of it:

* `net.py` is a parser and only a parser — the SML-to-Python translator and the
  four methods that knew about trees and samples are gone, and it is 97 lines
  where it was 221.
* `ColouredNet` no longer knows what a model family is, nor that a place called
  `Input` is special. Which places carry the input is the caller's to say, via
  `initial_marking(token, places=...)`.
* The evaluation environment is no longer a hardcoded `vadd`/`argmax`/`decide`.
  Those come from the net's own `<ml>` declarations, which the parser now
  reads; `detect_family` moved to the tree profile.

## 4. What is understood of CPN ML, and what is not

`cpncheck/cpnml.py` is a lexer, a precedence-climbing parser and a compiler to
Python closures. What it covers:

| | |
|---|---|
| expressions | `if`/`then`/`else`, `let`/`in`/`end`, `case`/`of`, `fn`, application |
| operators | the SML table, with precedence and associativity: `orelse`, `andalso`, the comparisons, `::`, `@`, `+ - ^`, `* / div mod`, unary `~` and `not` |
| values | integers, reals (including `~` and `E~`), strings, booleans, unit, tuples, lists, records, multisets |
| patterns | variables, wildcards, literals, tuples, lists, `::`, records, type annotations |
| declarations | `val` and `fun`, including multi-clause functions and recursion |
| colour sets | `unit`, `bool`, `int`, `real`, `string`, `enum`, `index`, `product`, `record`, `list`, `subset`, `alias`, read from the XML |
| binding | variables no input arc binds, enumerated over a finite colour set |

What is not covered, and raises `UnsupportedNet` rather than being guessed at:

| Missing | Why it matters | Effort |
|---|---|---|
| Timed nets (`@+`, timestamps) | common in protocol models | medium/high |
| Fusion sets beyond port/socket fusion | common | low |
| User-declared datatypes and their constructors | common | medium |
| `ref`, exceptions, `while` | rare in a net | low, and rarely worth it |
| An input arc with a variable coefficient (`n\`x`) | rare; it is a constraint to solve, not a pattern to match | medium |

A free variable over an infinite colour set is refused by name: it is the one
case where carrying on would silently check a smaller net than the one on
screen.

## 5. Open items

* **The ASK-CTL agreement is measured.** 28 nets — `gbdt_binary` and
  `rf_multiclass`, correct and every mutant — agree with CPN Tools on every
  statistic and every verdict, including 81 *false* ones. That was confirmed
  both for the AST-generated script and again after the CPN ML engine was
  replaced, so neither change moved a verdict. `_legacy_ml_program` is gone.
  `tests/test_oracle.py` keeps a fast subset, skipped unless
  `CPNCHECK_CPNTOOLS=1`.
* **Names moved in step 4.** `PROPERTY_CATALOG` is now
  `cpncheck.profiles.ml_trees.TREE_CATALOG`, `MUTANTS` is
  `cpncheck.profiles.ml_trees_mutants.TREE_MUTANTS`, and `AF_PROPERTIES` is
  gone (it was already dead; the information lives in
  `MLTreeProfile.ev_variants`). `Mutant.families` became `Mutant.applies`, a
  predicate. The pyruleanalyzer shim must import the first two from the
  profile.
* `PropertyResult.spec` no longer falls back to a global catalog: a verdict
  carries its descriptor, and asking for one that the profile does not define
  raises `KeyError` with that message.
* Guard boxes now track strictness, so `x >= 3` and `x <= 3` are correctly
  found to overlap at the single point 3. The exporter only emits `<=` and `>`,
  so no verdict on a generated net changes.
* `StateSpace.parent` entries are now `(source, transition, binding key)`, and
  `StateSpace.path(node)` returns the arcs rather than their names; `trace()`
  is unchanged. A trace without its bindings cannot be re-fired, which is what
  `replay()` needs.
* A counterexample for a net checked with explicit `samples` renders as
  `for input=(...): ...`, so a violation that needs a particular input can no
  longer be mistaken for one that happens on all of them.
* `ForEach` renders to a right-folded `AND`, so a forest with many trees
  produces a deep expression. Fine so far; revisit if it becomes a problem.

## 6. Order of work

1. ~~Mechanical extraction, package, CLI, tests.~~ **done**
2. ~~Selectors, formulas as data, profiles, one AST with two backends.~~ **done**
3. ~~Re-confirm the ASK-CTL agreement with CPN Tools, then delete
   `_legacy_ml_program`.~~ **done**
4. ~~Generalise the structural and conformance techniques, the mutation
   operators and the catalog.~~ **done**
5. ~~Pluggable ML prelude; widen the CPN ML fragment.~~ **done**
6. ~~**Counterexamples** — structured objects, bindings and markings along the
   trace, lasso witnesses for the `AF` properties, a witness point for guard
   overlap, `replay()` as a certificate.~~ **done**
7. ~~Switch pyruleanalyzer over and delete its copy.~~ **done**

```python

# pyruleanalyzer/model_checker.py
from cpncheck import CPNModelChecker, check_cpn, compare_results  # noqa: F401
from cpncheck.profiles.ml_trees import TREE_CATALOG, MLTreeProfile  # noqa: F401
```

`pyruleanalyzer` declares `cpncheck` as a normal dependency (it has none of its
own, so this is free) and keeps the exporter, `evaluate` and the four methods
of `CPNNet` that read a net as a tree ensemble. Its `cpn_statespace`,
`model_checker`, `cpn_mutants` and `cpntools_oracle` are re-exports, so no
import of theirs changed.

Three things the switch turned up, all fixed here:

* a property that *applies but cannot be decided* was being left out of the
  report rather than reported as skipped, which reads as if it had passed. A
  profile now says so through `unavailable`; the tree profile uses it for the
  valid-label property of a decision tree, whose label domain it cannot read.
* `PropertyResult.spec` raised for a verdict built by hand. It synthesises a
  bare descriptor instead: a report must be printable whatever it contains.
* `initial_marking(token)` with no `places` quietly ignored the token, so a
  caller checked every input against the net's own initial marking and was
  never told. It raises now.
