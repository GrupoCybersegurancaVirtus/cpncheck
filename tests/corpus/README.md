# The corpus: nets other people wrote

The CPN Tools samples show CPN Tools' features; they do not show what people
actually draw. This corpus does: 48 nets from 11 sources -- the models of the
Coloured Petri Nets book (Jensen & Kristensen, 2009), protocols, workflows,
simulations, course assignments and generated nets from public repositories.
`manifest.json` lists each one with the commit it was taken from and its
SHA-256.

The files are **not** in this repository: most come with no license that
would allow redistributing them. They are downloaded on demand and checked
against their hashes:

```bash
python tests/corpus/corpus.py fetch            # into tests/corpus/cache (ignored by git)
python tests/corpus/corpus.py run              # read and explore every net
python tests/corpus/corpus.py run --oracle     # and compare with CPN Tools
```

`run` sorts every net into **explored**, **over budget** (read and explored,
larger than the budget), **refused** (a construct CPNCheck does not support,
named) or **reader bug** (anything else -- always a bug). With `--oracle`
each explored net is compared with CPN Tools 4.0.1: statistic by statistic,
or by containment for a timed net. The outcome is written to
[RESULTS.md](RESULTS.md); `tests/test_corpus.py` runs the same checks under
pytest once the corpus is fetched.

## What the corpus found

Running it is how the gaps were found and closed, each checked against CPN
Tools itself:

* colour sets given only as text (`<index/>` with the definition in
  `<layout>`), `unit with e`, `bool with (no, yes)`, `union`;
* declarations read twice when repeated in `<layout>`;
* references (`globref`, `!`), curried functions by cases, sequences
  `(e1; e2)`, flexible record patterns `{data, ...}`, record patterns in
  function parameters;
* inhibitor and reset arcs, `x @+ d` on input arcs, transitions without
  input arcs -- their meaning measured in CPN Tools (`tests/nets/features`);
* lists on arcs of non-list places, which CPN Tools reads as multisets;
* in the oracle: generated ASK-CTL whose variable names clashed with a net's
  constants, string answers with escaped quotes.

What stays refused is outside what an occurrence graph can express: random
draws (`discrete`, `exponential`, `ran()`), real-valued time, code that
talks to the outside world, and files CPN Tools itself does not compile
(arcs without inscriptions, `!=`, which is not CPN ML).
