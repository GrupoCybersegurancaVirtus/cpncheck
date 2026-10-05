# Roadmap: a model checker for any `.cpn`

CPNCheck was extracted from pyruleanalyzer (see [MIGRATION.md](MIGRATION.md)).
The goal now is a tool that model checks the `.cpn` files CPN Tools itself can
analyse, whatever they model, with pyruleanalyzer as one client among others.

The yardstick is the 24 nets CPN Tools ships in `Sample CPN Models`: every one
must either be verified, agreeing with CPN Tools on its state space, or be
refused with the name of what is not supported. Never read wrongly in silence.

The target is not "any CPN". A net with an infinite state space, one whose
CPN ML needs the whole of SML, or one that draws random numbers has no finite
occurrence graph to check -- CPN Tools cannot check it either. The target is
the nets the CPN Tools state-space tool can analyse, with the agreement
measured by the oracle rather than assumed.

## Phase 1 -- read real nets correctly (done)

* The top level is what the file's `<instances>` element says: every prime
  page instance is part of the model. It used to be "the page with a place
  called `Prediction`", a convention of the tree nets.
* Double arcs (`orientation="BOTHDIR"`) are an input and an output arc. They
  used to be read as an output arc only, which silently changes the net.
  Checked against CPN Tools on a forest net with a tested place added.
* Fusion sets: the places of one set are one place; members that disagree on
  colour set or initial marking are refused.
* Names that wrap over several lines in the drawing are read on one line.
* Refused by name instead of ignored: timed colour sets and time
  inscriptions, code segments, transition priorities other than `P_NORMAL`,
  synchronous channels, unknown arc orientations. (Phases 3 and 4 have since
  lifted all but channels, impure code and real or random time.)
* `tests/test_net_reading.py` checks each construct against the plain net it
  abbreviates; `tests/test_cpntools_samples.py` runs every sample (skipped
  when CPN Tools is not installed) and, with `CPNCHECK_CPNTOOLS=1`, compares
  the supported ones with CPN Tools (`oracle.compare_state_space`, which needs
  no profile). `examples/cpntools_samples.py` prints the coverage table.

Result: no sample is read wrongly any more -- 24 of 24 are refused with a
reason, 0 reader errors. None is checked yet: what blocks them is CPN ML, not
the reader. The table, by roadmap item:

| Refusals | Cause | Lifted by |
|---|---|---|
| 6 | non-pattern input arc expressions | phase 3 |
| 6 | timed nets | phase 4 |
| 5 | variables not bound by an input arc (index colour sets, enumeration constants, constructor functions) | phase 3 |
| 4 | multisets inside `if`/`case` | phase 3 |
| 3 | code segments | not planned |

Because of this, **the multiset and pattern items of phase 3 came before
phase 2**: they are what turns the samples into a measured result.

## Phase 2 -- the tree domain leaves the core

* **Done:** a default profile for every net, the CPN Tools state-space report
  (`cpncheck/profiles/statespace_report.py`): R1 deadlock freedom, R2
  termination, R3 home marking, R4 no dead transitions, R5 all transitions
  live, reported as YES/NO facts that never fail a check, plus the integer
  bounds of every place and the dead and live transition instances. On the 7
  samples that fit the budget, **every one of those figures agrees with CPN
  Tools** (191 values), asked through CPN Tools' own functions. Getting there
  fixed two things in the ASK-CTL generator: names are spelled as CPN Tools
  spells them (each character an identifier cannot hold becomes `_`, in the
  name as drawn) with their instance number, and the oracle no longer loses an
  answer SML prints over several lines, nor all answers after one that fails.
* CPN Tools is not needed to use CPNCheck; a test runs the checker with the
  oracle module blocked.
* **Done:** the tree profile, its mutation operators, its tests and the
  walkthrough moved to pyruleanalyzer, which publishes the profile as a plugin
  (entry point `cpncheck.profiles`; one that fails to load is a warning). The
  generic checker no longer takes `class_labels`, `feature_names`,
  `classifier` or `use_final`: a profile gets `options` (`-O key=value` on the
  command line) and conformance a `reference`. CPNCheck's own tests run with
  no plugin, so they show what a standalone install does; a verdict the
  profile's catalog does not describe is now reported instead of dropped.
* **Done:** user properties without Python (`cpncheck/query.py`): a property
  file (`--props`) or `--prop`, with `dead`, `enabled`, `marked`, `empty`,
  `tokens(P) op k`, `enabled_count(T) op k`, `has(P, v)` over CPN ML values,
  `! & | ->`, `AG AF EF EG`, `E[U]`, `A[U]`. They are requirements (PASS/FAIL)
  beside the profile's facts, go through the reduction, and render to ASK-CTL;
  on DiningPhilosophers and SimpleProtocol_OG every one agrees with CPN Tools.
  A bad property or an unsupported net is one line on stderr (exit 2), not a
  traceback.
* **Done:** the generated ASK-CTL script says CPNCheck (`CPNCHECK_REPORT`).

## Phase 3 -- more of CPN ML (done)

Done, each pinned down in `tests/test_cpnml_nets.py`:

* Multisets are values anywhere in an expression: `n`x`, `++`, `--`, `empty`,
  so `if ok then 1`x else empty` works on any arc and in declarations.
* Input arcs that are not patterns (`Chopsticks(p)`, `Mes(s)`, `case x of p =>
  2`e | q => 1`e`) are evaluated once the binding is complete, and the
  transition is enabled only if the place holds that multiset on top of what
  the pattern arcs take.
* Enumeration constants are values, and a pattern naming one matches that
  constant only (a mutation test checks that reading it as a variable is
  caught).
* `index` colour sets (`index u with 1..NoOfU`, bounds may be declared names),
  `u(i)` as value and as pattern, and functions defined over such patterns.
* `subset B by f` and `subset B with [...]` range over their members only; one
  that cannot be evaluated has no domain. (Before, a subset silently ranged
  over all of `B`.)
* `CS.all()`, `CS.mult` for products, list concatenation `^^`.

Result on the samples: **15 of 24 read and explored, 0 reader errors; the 7
whose occurrence graph fits in 20 000 markings agree with CPN Tools on nodes,
arcs, SCCs, dead and home markings** (DiningPhilosophers, its ASK-CTL variant,
DistributedDataBase and its OG variant, both ResourceAllocation OG variants,
SimpleProtocol_OG). Of the other 8 explored, 7 exceed the budget (some are
infinite, like SimpleProtocol without its limit place) and one,
DiningPhilosophers_COMM_Mon, cannot be run by CPN Tools headless. Refused: 6
timed nets, 3 with code segments.

Then the rest of the phase, in `tests/test_timed.py`:

* Variables defined by the guard (`[y = x * 2]` with `y` on no input arc).
* Transition priorities (`P_HIGH`, `P_NORMAL`, `P_LOW` or any integer
  expression): only the most urgent enabled binding elements may occur.
* Code segments without side effects: `input (...); output (...); action
  e;` binds its outputs when the transition occurs. Code that prints, reads
  files, draws random numbers or uses a library CPNCheck does not have stays
  refused, naming what it uses.
* User datatypes: what CPN Tools' samples declare (enumerations, products,
  records, lists, index and subset colour sets) is covered; no sample is
  blocked by a datatype any more.

## Phase 4 -- timed nets (done)

Integer model time, as in CPN Tools: tokens of a timed colour set carry
timestamps, the marking carries the global clock, and the enabled binding
elements are those enabled at the earliest time at which any is (the clock
then moves to it). Output tokens get the occurrence time plus the
transition's delay plus the arc's (`@+`); `time()` reads the clock; a
timestamp in an initial marking (`1`x@3 +++ 1`y@0`) is read. A delay on an
arc covers its whole inscription, as CPN Tools reads it (`if b then 1`x else
empty @+7` delays both branches). Real-valued time (`@++`) and random delays
(`CS.ran()`, `exponential`) stay refused: such a net has no occurrence graph.

Two findings from validating against CPN Tools 4.0.1 (now possible: its
oracle failed on every timed net because Access/CPN's Java view of the
marking types timed places as untimed; the oracle skips that step):

* **Which token goes.** When a timed place holds several ready tokens of the
  value a binding takes, CPNCheck makes each choice its own successor (the
  binding records it). CPN Tools explores some of these choices, and not
  always the same ones: its node and arc counts for one net vary from run to
  run. So timed nets are checked by **containment**
  (`oracle.compare_graph_containment`): every node and arc CPN Tools finds is
  in CPNCheck's graph. On two finite variants of TimedResourceAlloc (336 and
  3 270 nodes in CPN Tools, 344 and 3 313 in CPNCheck) nothing is missing and
  the dead markings agree (48 and 246).
* **CPN Tools 4.0.1 expands timed nodes in a shifted frame.** Before computing
  a node's successors its state-space tool subtracts the node's creation time
  from every timestamp (`CPN'subtract`, `OGToSimDataGen.sml`) but leaves the
  clock where it was, so tokens become ready early (a token stamped 21 is
  taken at 13). This is the creation-time reduction half applied while it is
  off. CPNCheck follows the timed semantics of the literature (and of CPN
  Tools' simulator); `ColouredNet(..., compat="cpntools-4.0.1")` reproduces
  the shift, and only the comparison uses it.

Partial-order reduction is not sound with a global clock or priorities, so a
timed net, or one using priorities, is always checked on the full graph
(`net.reducible`).

Result on the samples: **16 of 24 explored, 0 reader errors**;
ProtocolWithTimer and TimedResourceAlloc (both infinite) are explored now.
The 8 refusals are all outside the target: 4 code segments with side effects
or full SML, 3 random values, 1 real-valued time.

## State-space reduction

Every technique declares which properties it preserves; the checker uses it
only for those and says, per property, which one decided it. Each is validated
like the stubborn sets: every verdict against the full graph on small nets and
on mutants, and against CPN Tools.

| Technique | Status | Needs from the user | Preserves |
|---|---|---|---|
| Stubborn sets (`reduction="stubborn"`) | **done** | nothing | per property (deadlock / safety / stutter graphs) |
| Sweep-line, generalised (`reduction="sweep"`) | **done** | a progress measure (`--progress`), or nothing for a timed net (its clock) | `AG ψ`, `EF χ`, `!EF χ` of state predicates, dead markings; any measure is sound |
| Equivalence | planned | the equivalence relation; consistency is tested, not proved | what the relation respects; verdicts marked conditional |
| Symmetry | planned | the permutable colour sets; the soundness criteria are checked | properties invariant under the symmetry |

Combinations (sweep-line with stubborn sets, symmetry with stubborn sets) come
after each technique is validated on its own.
