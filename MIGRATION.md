# Extraction from pyruleanalyzer — state and plan

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

`pyruleanalyzer` is **not yet modified** and does not depend on CPNCheck; it
still carries its own copy. Nothing there breaks until step 7 below is done
deliberately.

## 1. The modules

| CPNCheck module | Origin | What it does |
|---|---|---|
| `cpncheck/net.py` | `cpn_semantics.py` 27–225 | parse the `.cpn` XML |
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
| `resolve_groups` | the domains `ForEach` quantifies over |
| `ctl_formulas` | the temporal properties, as formulas |
| `scc_properties` | the properties answered from the SCC decomposition |
| `static_checks` | verdicts that need no occurrence graph |
| `conformance` | comparison with a reference implementation |
| `label_domain` | the admissible output tokens |
| `as_input_token` / `input_places` | how another input is written into the net |
| `mutation_operators` / `analyse_for_mutation` | the faults that must be caught |
| `catalog` | the descriptors verdicts are reported under |

What remains in the generic layer, and is the subject of step 5:

| Where | What |
|---|---|
| `coloured.py` `ColouredNet.__init__` | `self.family = net.family()`, and the evaluation environment injects `vadd`, `vsum`, `argmax`, `allzero`, `decide` |
| `coloured.py` `initial_marking` | takes `places=`; the name-based `Input` fallback is kept for callers that do not pass it |
| `net.py` | `family`, `sample_from_initial_marking`, `leaf_outputs`, `eval_subpage` |

### Step 5 — a pluggable ML prelude

`vadd`/`vsum`/`argmax`/`decide` become functions a profile registers, and
ideally are read from the net's own `<ml>` block. That is the same parser work
as §4, so the two land together.

## 4. What is missing for arbitrary `.cpn` files

The supported CPN ML fragment is narrow. Everything outside it raises
`UnsupportedNet` rather than being mis-read, which is the right failure mode,
but a net drawn by hand in CPN Tools will usually be rejected.

| Missing | Why it matters | Effort |
|---|---|---|
| `if` / `case` / `let` / `fn` / `val` / `fun` / `div` / `mod` — rejected outright in `coloured.py` `sml_expr_to_python` | ubiquitous in real nets | high: needs a real CPN ML parser |
| Colour sets are not interpreted at all — tokens are untyped Python values | no type checking, and no domain to enumerate | high |
| Variables not bound by an input arc (binding enumerated from the colour set) | this is *the* binding mechanism of CPN Tools | high |
| User-declared `fun` in the `<ml>` block | falls out of the parser work | medium |
| Multiset on an **input** arc (`1\`x ++ 1\`y`); `parse_pattern` takes a single pattern | common | medium |
| Fusion sets (only port/socket fusion is handled) | common | low |
| Timed nets (`@+`, timestamps) | common | medium/high |

## 5. Open items

* **The ASK-CTL script changed shape.** It is now generated from the formula
  tree, so a quantified property folds into one `AND` instead of an ML
  `List.all`, and `AF` always goes through `AFmax`. The queries are
  semantically the same and the *keys* are asserted equal to the hand-written
  generator's in `tests/test_generic.py`, but **the agreement of the answers
  has not been re-confirmed against CPN Tools** — run `cpncheck oracle` on a
  machine with the engine installed before relying on it. The old generator is
  kept as `CPNModelChecker._legacy_ml_program` until that is done, and should
  be deleted afterwards.
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
3. Re-confirm the ASK-CTL agreement with CPN Tools, then delete
   `_legacy_ml_program`.
4. ~~Generalise the structural and conformance techniques, the mutation
   operators and the catalog.~~ **done**
5. Pluggable ML prelude; widen the CPN ML fragment (§3 step 5, §4).
6. ~~**Counterexamples** — structured objects, bindings and markings along the
   trace, lasso witnesses for the `AF` properties, a witness point for guard
   overlap, `replay()` as a certificate.~~ **done**
7. Switch pyruleanalyzer over and delete its copy:

```python
# pyruleanalyzer/model_checker.py
from cpncheck import CPNModelChecker, check_cpn, compare_results  # noqa: F401
from cpncheck.profiles.ml_trees import TREE_CATALOG, MLTreeProfile  # noqa: F401
```

`pyruleanalyzer` declares `cpncheck` as a normal dependency (it has none of its
own, so this is free) and keeps the exporter, `evaluate` and the conformance
reference function.
