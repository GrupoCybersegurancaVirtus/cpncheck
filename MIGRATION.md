# Extraction from pyruleanalyzer — state and plan

CPNCheck was extracted from `pyruleanalyzer`.

* **Phase 1 — done.** Mechanical extraction: code moved and split, imports
  rewritten, nothing redesigned.
* **Phase 2 — done.** Selectors, formulas as data, profiles, and one AST
  rendered to both backends. The checker no longer contains any knowledge of
  what the nets compute.

`pyruleanalyzer` is **not yet modified** and does not depend on CPNCheck; it
still carries its own copy. Nothing there breaks until step 6 below is done
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
| `cpncheck/profiles/ml_trees.py` | **phase 2**, from `model_checker.py` | everything ML-specific, in one place |
| `cpncheck/properties.py` | `model_checker.py` 115–239 | the property descriptors |
| `cpncheck/result.py` | `model_checker.py` 241–525, 1476–1515 | verdicts, text/JSON/LaTeX reports |
| `cpncheck/checker.py` | `model_checker.py` 631–1473 | orchestration; profile-driven |
| `cpncheck/oracle.py` | `cpntools_oracle.py` | run CPN Tools 4.0.1 headless |
| `cpncheck/mutation.py` | `cpn_mutants.py` | mutants: every property must be able to fail |
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

* **it explains itself.** `AG` reports the shortest occurrence sequence to a
  violating marking and asks the operand *why that marking is bad*; `AF`
  reports a maximal sequence that never reaches the goal; `Not(EU(...))`
  reports the sequence witnessing the until. This is where counterexamples will
  be built out (phase 4).
* **it renders to ASK-CTL.** `cpncheck/askctl.py` turns the same tree into the
  CPN ML query, so the Python check and the CPN Tools script cannot be asked
  different questions. Before phase 2 they were written by hand side by side.

## 3. What is still domain-specific

Phase 2 moved the property catalog, the structure and the four techniques out
of the checker. What remains, and where it goes:

| Where | What | Step |
|---|---|---|
| `coloured.py` `ColouredNet.__init__` | `self.family = net.family()`, and the evaluation environment injects `vadd`, `vsum`, `argmax`, `allzero`, `decide` | 5 |
| `coloured.py` `initial_marking` | now takes `places=`; the name-based `Input` fallback is still there for callers that do not pass it | 5 |
| `net.py` | `family`, `sample_from_initial_marking`, `leaf_outputs`, `eval_subpage` | 5 |
| `properties.py` | the built-in catalog is still the ML one, and its `families` field names ML model families — but it is now only a *default*, overridable per profile | 4 |
| `profiles/ml_trees.py` `_check_b4`, `_check_pc` | the structural and conformance techniques, still written against tree nets | 4 |
| `mutation.py` | 16 mutation operators written against those nets | 4 |

### Step 4 — generalise the two non-CTL techniques

Neither is really ML-specific:

* `_check_b4`/`_guard_box` is "do the guards of a group of transitions
  overlap", with an interval backend today and room for an SMT one. It should
  take a transition group and return the overlapping pairs.
* `_check_pc` is "run to a dead marking with this token in this place, compare
  a projection of the terminal marking with `f(input)`". pyruleanalyzer
  supplies `f`; CPNCheck does not need to know what it is.

Mutation operators generalise the same way: an operator is an edit to a guard,
an inscription or an arc, selected by the same selectors the properties use.

### Step 5 — a pluggable ML prelude

`vadd`/`vsum`/`argmax`/`decide` become functions a profile registers, and
ideally are read from the net's own `<ml>` block. That is the same parser work
as §4 below, so the two land together.

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
* `properties.AF_PROPERTIES` is dead (it was already unused in pyruleanalyzer);
  the same information now lives in `MLTreeProfile.ev_variants`. Delete it or
  make it the documented way to declare an ASK-CTL variant.
* `ForEach` renders to a right-folded `AND`, so a forest with many trees
  produces a deep expression. Fine so far; revisit if it becomes a problem.

## 6. Order of work

1. ~~Mechanical extraction, package, CLI, tests.~~ **done**
2. ~~Selectors, formulas as data, profiles, one AST with two backends.~~ **done**
3. Re-confirm the ASK-CTL agreement with CPN Tools, then delete
   `_legacy_ml_program`.
4. Generalise the structural and conformance techniques, and the mutation
   operators (§3 step 4).
5. Pluggable ML prelude; widen the CPN ML fragment (§3 step 5, §4).
6. **Counterexamples** — structured objects, bindings and markings along the
   trace, lasso witnesses for the `AF` properties, a witness point for guard
   overlap, `replay()` as a certificate. The explanations built in phase 2 are
   the hook: every operator already knows what a counterexample to it looks
   like, it just returns a string today.
7. Switch pyruleanalyzer over and delete its copy:

```python
# pyruleanalyzer/model_checker.py
from cpncheck import CPNModelChecker, check_cpn, compare_results  # noqa: F401
from cpncheck.profiles.ml_trees import MLTreeProfile              # noqa: F401
```

`pyruleanalyzer` declares `cpncheck` as a normal dependency (it has none of its
own, so this is free) and keeps the exporter, `evaluate` and the conformance
reference function.
