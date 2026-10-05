# Examples

## `cpntools_samples.py`

CPNCheck on the example models CPN Tools ships with -- nets written by other
people for other purposes, which is the honest measure of how general it is.
Every net is read and explored, or refused with the name of what is not
supported; with `--oracle`, every one that fits the budget is compared with
CPN Tools itself.

```bash
python examples/cpntools_samples.py
python examples/cpntools_samples.py --oracle
python examples/cpntools_samples.py --samples "D:/CPN Tools/Sample CPN Models"
```

| | |
|---|---|
| `--samples DIR` | where the models are (default: CPN Tools' install folder) |
| `--max-nodes N` | occurrence-graph budget per net (default 20 000) |
| `--oracle` | compare each supported net with CPN Tools (needs CPN Tools) |

CPN Tools is needed only for `--oracle`; the sweep itself is CPNCheck alone.

## A guided walkthrough

The eleven-step walkthrough -- reading, compiling, the occurrence graph, one
run marking by marking, the verdicts, counterexamples and their replay,
guard overlaps, conformance, ASK-CTL and mutants -- is about the tree nets,
so it lives with the tree profile, in pyruleanalyzer:
`examples/cpncheck_walkthrough.py`.
