# Examples

## `walkthrough.py`

A guided run of CPNCheck on the nets under `tests/nets`, printing what each
layer produced before it hands the result to the next one. The README says
what the checker does; this prints it.

```bash
python examples/walkthrough.py
```

| | |
|---|---|
| `--net PATH` | the `.cpn` to walk through (default `tests/nets/gbdt_binary.cpn`) |
| `--labels 0,1,2` | the label domain, when the net does not declare one |
| `--only 4,5,6` | run only those steps |
| `--keep DIR` | keep the mutants and the exports instead of discarding them |

Nothing is written unless `--keep` asks for it, and nothing outside the Python
standard library is needed.

### The eleven steps

The first six follow the pipeline, bottom up — each one is the input of the
next:

| # | Step | Module | What it shows |
|---|---|---|---|
| 1 | Reading the `.cpn` file | `cpncheck.net` | pages, places, transitions and one transition as the file writes it |
| 2 | Compiling the CPN ML | `cpncheck.coloured` | colour sets, the net's own `<ml>` declarations, and a tree's guards evaluated on the file's own input |
| 3 | Recognising the net | `cpncheck.profile` | the profile that matched, the roles it assigned, the properties it selected |
| 4 | Building the occurrence graph | `cpncheck.statespace` | nodes, arcs, SCCs, dead and home markings |
| 5 | One run, occurrence by occurrence | `cpncheck.coloured` | the firing rule unrolled: a table of transition → marking, from the initial marking to the dead one |
| 6 | Verifying the properties | `cpncheck.ctl` | the report, one verdict per property, grouped by technique |

The last five are what those verdicts are worth anything *because* of:

| # | Step | Module | What it shows |
|---|---|---|---|
| 7 | Evidence, and its certificate | `cpncheck.counterexample` | three mutants and the two sequence shapes (`lasso`, `finite`), each replayed — and a tampered trace that does not replay |
| 8 | A finding about every input | `cpncheck.structural` | a guard overlap, the input it extracts, and that input making the per-input property fail on the same pair |
| 9 | Conformance with a reference | `cpncheck.conformance` | the net against a reference on twelve inputs it has never seen, and a mutant that disagrees on several of them |
| 10 | Exporting the same questions | `cpncheck.askctl` | the ASK-CTL script for CPN Tools, the JSON, the LaTeX rows |
| 11 | Sensitivity | `cpncheck.mutation` | every mutant, and whether it falsified the property it was built to violate |

### What to read it for

**Step 5 is the whole mechanism.** Everything above it — CTL fixpoints, SCCs,
counterexamples — is bookkeeping over this one table: a marking, the binding
elements enabled in it, one of them occurring, tokens moving.

**Step 7 is why a `FAIL` is believable.** `replay()` re-fires the trace using
the net's firing rule, not the search that produced it, so a bug in the
fixpoints cannot forge one. The step then reverses a trace and truncates
another to show the certificate rejecting both.

**Step 8 is the one verdict a state space cannot give.** Guard disjointness is
about every input, so its failure names no run — but it hands back a point in
the overlap, and step 8 feeds that point back in and watches the per-input
property fail on exactly the pair that was reported.

**Step 9 uses the verified net as the reference**, which keeps the example
dependency-free and makes the point directly: none of the temporal properties
says the answer is *right*, so that is asked separately. With a real model,
pass it instead:

```python
check_cpn("model.cpn", classifier=clf, test_samples=X)
```

### Running it on your own net

`--net` takes any `.cpn` a registered profile recognises. For a net of your
own, write a profile (see "Verifying your own nets" in the top-level README),
register it, and the walkthrough will pick it up — steps 1 to 6 and 10 to 11
need nothing else. Steps 7 to 9 need the profile to supply mutation operators
and a structure, which `cpncheck.profile.Profile` documents.
