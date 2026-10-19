# Examples

A guided tour of CPNCheck, one feature per script. Each script runs on its
own, prints a walkthrough of what it does, and needs nothing but CPNCheck
(CPN Tools only for `12_cpntools_oracle.py`, which says so and exits when it
is missing).

```bash
python examples/01_quickstart.py        # one at a time
python examples/run_all.py              # all of them, in order
python examples/run_all.py 06 07 --quiet
```

| Script | What it shows |
|---|---|
| [`01_quickstart.py`](01_quickstart.py) | `check_cpn` in one call; the default report (CPN Tools' R1-R5 and place bounds); your own properties; the result as data and JSON |
| [`02_reading_a_net.py`](02_reading_a_net.py) | The layers under `check_cpn`: `CPNNet`, `ColouredNet` (enabling, firing, one run), `build_state_space` (SCCs, dead and home markings, traces); guard-defined variables, code segments, priorities; unsupported constructs refused by name |
| [`03_user_properties.py`](03_user_properties.py) | The property language (`dead`, `enabled`, `marked`, `tokens`, `enabled_count`, `has`, `AG AF EF EG`, `E[U]`, `A[U]`); property files; error messages |
| [`04_counterexamples.py`](04_counterexamples.py) | Finite counterexamples and lassos, bindings, the violating marking, replaying a counterexample on the net, as data |
| [`05_timed_nets.py`](05_timed_nets.py) | Timestamps, transition and arc delays, the global clock, the earliest-time rule, properties of timed nets |
| [`06_stubborn_sets.py`](06_stubborn_sets.py) | Partial-order reduction: 6561 markings decided on 17; which reduced graph decides which property; why folded colours reduce less; when it does not apply |
| [`07_sweep_line.py`](07_sweep_line.py) | The sweep-line method: progress measures, regress arcs, what it decides, the clock of a timed net |
| [`08_equivalence.py`](08_equivalence.py) | Quotient graphs: time equivalence turning an infinite timed graph finite; your own canonical form; an inconsistent one caught |
| [`09_symmetry.py`](09_symmetry.py) | Symmetry reduction: all permutations, rotations of linked colour sets, a wrong symmetry caught, properties it cannot decide |
| [`10_custom_profile.py`](10_custom_profile.py) | Your own profile: a property catalog in Python formulas, quantification over groups, options, SCC properties, mutation operators; inputs and a conformance test against a reference function |
| [`11_askctl_and_reports.py`](11_askctl_and_reports.py) | ASK-CTL scripts for CPN Tools, JSON, LaTeX tables, comparing two versions of a net |
| [`12_cpntools_oracle.py`](12_cpntools_oracle.py) | Cross-checking against CPN Tools: state-space statistics, every verdict, graph containment for timed nets |
| [`13_command_line.py`](13_command_line.py) | Every `cpncheck` command and option, run on the example nets |
| [`14_askctl_queries.py`](14_askctl_queries.py) | ASK-CTL query files as input, as written for CPN Tools; where ASK-CTL is not textbook CTL |
| [`cpntools_samples.py`](cpntools_samples.py) | CPNCheck on the 24 models CPN Tools ships with (`--oracle` to compare each with CPN Tools) |

## The nets

[`nets/`](nets) holds small nets, each chosen to show one thing, and small
enough for the full occurrence graph to exist so that every reduction can be
compared with it. [`nets/build_nets.py`](nets/build_nets.py) writes them
(`python examples/nets/build_nets.py` regenerates them); they contain the
declarations, places, transitions and arcs, without the drawing, which is
what CPN Tools' simulator and CPNCheck read.

| Net | Markings | What it is for |
|---|---|---|
| `dining.cpn` | 11 | five philosophers taking both chopsticks at once: properties, symmetry, lassos |
| `dining_deadlock.cpn` | 82 | taking left, then right: a deadlock and its counterexample |
| `workers.cpn` | 729 | six identical workers in one coloured sub-net: sweep-line, symmetry, a user equivalence |
| `pipelines.cpn` | 6561 | eight workers, one sub-net each: stubborn sets |
| `timed_jobs.cpn` | 21 | three timed jobs on two machines: timed semantics |
| `timed_loop.cpn` | infinite | tokens circulating while time grows: time equivalence |
| `ml_features.cpn` | 10 | order processing with a guard-defined variable, a code segment, priorities and multisets in `if`; a function net for inputs and conformance |

[`properties/dining.props`](properties/dining.props) is a property file for
the philosophers, used by `03_user_properties.py` and
`cpncheck check examples/nets/dining.cpn --props examples/properties/dining.props`.

## The tree nets

The walkthrough of pyruleanalyzer's tree nets (decision trees, random
forests and boosting exported as CPNs) lives with that profile, in
pyruleanalyzer: `examples/cpncheck_walkthrough.py`.
