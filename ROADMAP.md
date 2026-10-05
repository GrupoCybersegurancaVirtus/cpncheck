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
  synchronous channels, unknown arc orientations.
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

Because of this, **the multiset and pattern items of phase 3 come before
phase 2**: they are what turns the samples into a measured result.

## Phase 2 -- the tree domain leaves the core

* The tree profile and its mutation operators move to pyruleanalyzer and are
  registered as a plugin (entry point `cpncheck.profiles`).
* `class_labels`, `feature_names`, `classifier`, `use_final` and `--labels`
  stop being arguments of the generic checker; they become profile options.
* A default profile for every net: the CPN Tools state-space report (dead
  markings, home markings, place bounds, live and dead transitions).
* User properties without Python: a query file or a CLI option.
* The generated ASK-CTL script stops saying "pyRuleAnalyzer".

## Phase 3 -- more of CPN ML

* Input arc expressions that are not patterns (`Chopsticks(p)`, `Mes(s)`,
  `if ... then 1`x else empty`), evaluated once the binding is known.
* Multisets inside `if`/`case` on output arcs.
* Variables bound by the guard (`[x = f(y)]`).
* `index` colour sets (`colset U = index u with 1..10`, values `u(i)`), read
  today as "unknown".
* Enumeration constants (`colset E = with e`) as values. They are unknown
  today, so every net using them is refused; once they are known, an input
  pattern naming a constant must match that constant only -- read as a
  variable it would match any token.
* Functions defined by constructor patterns (`fun f (ph(i)) = ...`).
* User-declared datatypes; transition priorities.

## Phase 4 -- timed nets

Integer global clock and token timestamps, as in CPN Tools' timed state space.
Real-valued time and random delays stay refused.

## State-space reduction

Every technique declares which properties it preserves; the checker uses it
only for those and says, per property, which one decided it. Each is validated
like the stubborn sets: every verdict against the full graph on small nets and
on mutants, and against CPN Tools.

| Technique | Status | Needs from the user | Preserves |
|---|---|---|---|
| Stubborn sets (`reduction="stubborn"`) | **done** | nothing | per property (deadlock / safety / stutter graphs) |
| Sweep-line, generalised | planned, after phase 2 | a progress measure, or the clock of a timed net, or one found in the net | safety, reachability, dead markings |
| Equivalence | planned | the equivalence relation; consistency is tested, not proved | what the relation respects; verdicts marked conditional |
| Symmetry | planned | the permutable colour sets; the soundness criteria are checked | properties invariant under the symmetry |

Combinations (sweep-line with stubborn sets, symmetry with stubborn sets) come
after each technique is validated on its own.
