# Changelog

## 0.2.0

The first release as a model checker for any `.cpn`, independent of
pyruleanalyzer (see [ROADMAP.md](ROADMAP.md) for the phases).

**Reading nets**
* The model is every prime page instance (`<instances>`); double arcs, fusion
  sets, hierarchy with port/socket assignments.
* CPN ML: CPN Tools' standard library (`cpncheck/mllib.py`) checked against
  CPN Tools on 236 expressions; multisets anywhere, characters and escapes,
  `SOME`/`NONE`, `datatype`, `exception`/`raise`/`handle`, `local`,
  references, sequences, curried functions by cases, flexible records,
  operator sections, composition.
* Colour sets: enumerations, `index`, `unit with`, `bool with`, products,
  records, lists, `union`, `subset by`/`with`, aliases, and colour sets
  given only as text.
* Timed nets with integer time, priorities, guard-bound variables, code
  segments without side effects, inhibitor and reset arcs, `@+` on input
  arcs, transitions without input arcs.
* Anything else is refused by name (`UnsupportedNet`), never misread.

**Checking**
* A default profile for any net: CPN Tools' state-space report (deadlock,
  termination, home marking, dead and live transitions, integer and multiset
  place bounds, impartial/fair/just transitions).
* User properties as text (`--prop`, `--props`): CTL over named places and
  transitions; counterexamples that replay.
* ASK-CTL query files as input (`--askctl`, `askctl=`): the SML a CPN Tools
  user already wrote, with CPN Tools' state-space functions, evaluated with
  ASKCTL.sml's own semantics (two sorts, rewriting, the SCC fast paths);
  49 queries agree with CPN Tools.
* State-space reduction: stubborn sets, generalised sweep-line, time
  equivalence and user equivalences, symmetry -- each declares what it
  preserves and is validated against the full graph.
* Combined reductions (`--reduction stubborn+symmetry`, `sweep+stubborn`,
  `equivalence+symmetry`, ...): each property is decided by what every
  part preserves; the rest gets no verdict, with the reason.
* The default budget is 1 000 000 markings (was 200 000).
* Profiles as plugins (entry point `cpncheck.profiles`), with options,
  inputs, conformance tests and mutation operators.

**Validation**
* An optional oracle runs CPN Tools 4.0.1 headless (Windows) and compares
  state spaces, verdicts and report figures; timed nets by containment.
* The CPN Tools samples and a corpus of 48 nets other people wrote
  (`tests/corpus`): no reader bugs; every explored net CPN Tools compiles
  agrees with it, on the state space and on every report figure.
* Exploration about 40% faster on timed nets (bindings counted once per
  marking, timestamps cached).

**Packaging**
* Python 3.8-3.13, no dependencies; CI on Linux, macOS and Windows; API
  reference on GitHub Pages; release to PyPI from a version tag.
* The oracle's cache moved to `%LOCALAPPDATA%/cpncheck`, and its components
  may be located with `CPNCHECK_*` environment variables.

## 0.1.0.dev0

Extracted from pyruleanalyzer ([docs/history](docs/history/extraction-from-pyruleanalyzer.md)).
