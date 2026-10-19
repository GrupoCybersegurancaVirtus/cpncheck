"""A corpus of nets other people wrote, to measure how general CPNCheck is.

The CPN Tools samples were the first yardstick; they are few and were
written to demonstrate CPN Tools. This corpus is nets from the Coloured
Petri Nets book and from public repositories -- protocols, workflows,
simulations -- listed in ``manifest.json`` with the commit they were taken
from and their SHA-256. The files are *not* in this repository (most come
with no license that would allow it); ``fetch`` downloads them into
``tests/corpus/cache``, checking each against its hash.

``run`` reads and explores every net and sorts it into:

* **explored** -- the occurrence graph fits the budget;
* **over budget** -- read and explored, but larger than the budget;
* **refused** -- a construct CPNCheck does not support, named;
* **reader bug** -- any other failure: always a bug to fix.

With ``--oracle``, every explored net is also compared with CPN Tools:
statistic by statistic, or by containment for a timed net. The outcome is
written to ``RESULTS.md``.

    python tests/corpus/corpus.py fetch
    python tests/corpus/corpus.py run [--oracle] [--max-nodes N]
"""

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
MANIFEST = os.path.join(HERE, "manifest.json")
CACHE = os.path.join(HERE, "cache")
RESULTS_JSON = os.path.join(HERE, "results.json")
RESULTS_MD = os.path.join(HERE, "RESULTS.md")

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# Function to read the manifest.
def load_manifest() -> List[Dict[str, Any]]:
    """The corpus entries.

    Returns:
        list: One dict per net (id, repo, commit, path, sha256, license...).
    """
    with open(MANIFEST, encoding="utf-8") as fh:
        return json.load(fh)["nets"]


# Function to give where a net is cached.
def cached_path(entry: Dict[str, Any]) -> str:
    """The local file of an entry.

    Args:
        entry (dict): A manifest entry.

    Returns:
        str: The path under ``cache/``.
    """
    return os.path.join(CACHE, entry["repo"].replace("/", "__"),
                        *entry["path"].split("/"))


# Function to check a cached file against its hash.
def verified(entry: Dict[str, Any]) -> bool:
    """Whether the cached file exists and has the recorded SHA-256.

    Args:
        entry (dict): A manifest entry.

    Returns:
        bool: True when it does.
    """
    path = cached_path(entry)
    if not os.path.exists(path):
        return False
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest() == entry["sha256"]


# Function to download the corpus.
def fetch(entries: List[Dict[str, Any]]) -> int:
    """Download every net not yet cached, checking its hash.

    Args:
        entries (list): Manifest entries.

    Returns:
        int: How many could not be fetched or did not match.
    """
    bad = 0
    for entry in entries:
        if verified(entry):
            continue
        url = (f"https://raw.githubusercontent.com/{entry['repo']}/"
               f"{entry['commit']}/{urllib.parse.quote(entry['path'])}")
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read()
        except OSError as exc:
            print(f"  could not fetch {entry['id']}: {exc}")
            bad += 1
            continue
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            print(f"  {entry['id']}: content differs from the manifest; not kept")
            bad += 1
            continue
        path = cached_path(entry)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        print(f"  fetched {entry['id']}")
    print(f"{len(entries) - bad} of {len(entries)} nets in {CACHE}")
    return bad


# Function to read and explore one net.
def explore(path: str, max_nodes: int) -> Dict[str, Any]:
    """Read a net and build its occurrence graph within a budget.

    Args:
        path (str): The ``.cpn`` file.
        max_nodes (int): The budget.

    Returns:
        dict: ``status``, ``reason``, and the graph's figures when explored.
    """
    from cpncheck.coloured import ColouredNet, UnsupportedNet
    from cpncheck.net import CPNNet
    from cpncheck.statespace import build_state_space

    t0 = time.perf_counter()
    try:
        net = ColouredNet(CPNNet(path))
        ss = build_state_space(net, max_nodes)
    except UnsupportedNet as exc:
        return {"status": "refused", "reason": " ".join(str(exc).split()),
                "seconds": time.perf_counter() - t0}
    except Exception as exc:                                  # noqa: BLE001
        return {"status": "reader bug",
                "reason": f"{type(exc).__name__}: {' '.join(str(exc).split())}",
                "trace": traceback.format_exc()[-1500:],
                "seconds": time.perf_counter() - t0}
    return {"status": "explored" if ss.complete else "over budget",
            "nodes": ss.n_nodes, "arcs": ss.n_arcs, "dead": len(ss.dead),
            "timed": net.timed, "places": len(net.places),
            "transitions": len(net.transitions),
            "seconds": time.perf_counter() - t0}


# Function to compare an explored net with CPN Tools.
def against_cpntools(path: str, timed: bool, max_nodes: int, oracle) -> Dict[str, Any]:
    """CPN Tools' verdict on the net's occurrence graph.

    Args:
        path (str): The ``.cpn`` file.
        timed (bool): Whether the net is timed (then: containment).
        max_nodes (int): The budget.
        oracle (CPNToolsOracle): The oracle.

    Returns:
        dict: ``oracle`` (``agree``, ``contained``, ``DIFFER``, ``error``),
        and the details.
    """
    from cpncheck.coloured import CPNTOOLS_401
    from cpncheck.oracle import compare_graph_containment, compare_state_space

    try:
        if timed:
            r = compare_graph_containment(path, oracle=oracle, max_nodes=max_nodes,
                                          timeout=900, compat=CPNTOOLS_401)
            return {"oracle": "contained" if r["contained"] else "DIFFER",
                    "oracle_detail": {k: r.get(k) for k in
                                      ("nodes", "arcs", "dead", "missing_arcs")},
                    "oracle_errors": r.get("errors")}
        r = compare_state_space(path, oracle=oracle, max_nodes=max_nodes,
                                timeout=900)
        if "CheckerException" in str(r.get("errors")):
            # CPN Tools' own compiler refuses the file: nothing to compare.
            return {"oracle": "rejected by CPN Tools",
                    "oracle_errors": r.get("errors")}
        return {"oracle": "agree" if r["agree"] else (
                    "error" if r["errors"] else "DIFFER"),
                "oracle_detail": {k: (ours, theirs) for k, ours, theirs, _ in r["rows"]},
                "oracle_errors": r.get("errors")}
    except Exception as exc:                                  # noqa: BLE001
        return {"oracle": "error", "oracle_errors": {"driver": str(exc)[:500]}}


# Function to run the corpus.
def run(entries: List[Dict[str, Any]], max_nodes: int, use_oracle: bool,
        only: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Explore every cached net (and compare with CPN Tools).

    Args:
        entries (list): Manifest entries.
        max_nodes (int): Occurrence-graph budget.
        use_oracle (bool): Also compare with CPN Tools.
        only (list, optional): Substrings of the ids to run.

    Returns:
        list: One result per net.
    """
    oracle = None
    if use_oracle:
        from cpncheck.oracle import CPNToolsOracle
        oracle = CPNToolsOracle()
        missing = oracle.missing()
        if missing:
            print("CPN Tools is not available:", ", ".join(missing))
            oracle = None
    results = []
    for entry in entries:
        if only and not any(o in entry["id"] for o in only):
            continue
        if not verified(entry):
            results.append({"id": entry["id"], "status": "not fetched"})
            continue
        path = cached_path(entry)
        result = {"id": entry["id"], **explore(path, max_nodes)}
        if oracle is not None and result["status"] == "explored":
            result.update(against_cpntools(path, result["timed"], max_nodes, oracle))
        results.append(result)
        tail = (f"{result.get('nodes')} nodes" if "nodes" in result
                else result.get("reason", ""))[:110]
        print(f"  {result['status']:<12} {entry['id']:<48} {tail}"
              f"{'  [' + result['oracle'] + ']' if 'oracle' in result else ''}")
    return results


# Function to write the results as Markdown.
def write_report(entries, results, max_nodes: int, use_oracle: bool) -> str:
    """``RESULTS.md``: a table per outcome and a summary.

    Args:
        entries (list): Manifest entries.
        results (list): From :func:`run`.
        max_nodes (int): The budget used.
        use_oracle (bool): Whether CPN Tools was asked.

    Returns:
        str: The report's text.
    """
    by_id = {e["id"]: e for e in entries}
    counts: Dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    lines = ["# Corpus results", "",
             f"{len(results)} nets from {len({e['repo'] for e in entries})} "
             f"sources (see `manifest.json`), budget {max_nodes} markings"
             f"{', compared with CPN Tools 4.0.1' if use_oracle else ''}. "
             "Regenerate with `python tests/corpus/corpus.py run"
             f"{' --oracle' if use_oracle else ''}`.", "",
             "| Outcome | Nets |", "|---|---|"]
    for status in ("explored", "over budget", "refused", "reader bug",
                   "not fetched"):
        if counts.get(status):
            lines.append(f"| {status} | {counts[status]} |")
    if use_oracle:
        verdicts: Dict[str, int] = {}
        for r in results:
            if "oracle" in r:
                verdicts[r["oracle"]] = verdicts.get(r["oracle"], 0) + 1
        lines += ["", "Against CPN Tools: " + ", ".join(
            f"{n} {v}" for v, n in sorted(verdicts.items())) + "."]
    lines += ["", "| Net | Source | Outcome | Detail |", "|---|---|---|---|"]
    for r in results:
        e = by_id[r["id"]]
        if "nodes" in r:
            detail = (f"{r['nodes']} nodes, {r['arcs']} arcs, {r['dead']} dead"
                      f"{', timed' if r.get('timed') else ''}")
            if "oracle" in r:
                detail += f"; CPN Tools: {r['oracle']}"
        else:
            detail = r.get("reason", "").replace("|", "\\|")[:160]
        lines.append(f"| {r['id']} | {e['about']} | {r['status']} | {detail} |")
    text = "\n".join(lines) + "\n"
    with open(RESULTS_MD, "w", encoding="utf-8") as fh:
        fh.write(text)
    return text


# Function to run the command line.
def main(argv=None) -> int:
    """``fetch`` or ``run``.

    Args:
        argv (list, optional): Arguments.

    Returns:
        int: Exit status (1 when a net hit a reader bug).
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=["fetch", "run"])
    parser.add_argument("--oracle", action="store_true")
    parser.add_argument("--max-nodes", type=int, default=20_000)
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args(argv)
    entries = load_manifest()
    if args.command == "fetch":
        return 1 if fetch(entries) else 0
    results = run(entries, args.max_nodes, args.oracle, args.only)
    if not args.only:
        with open(RESULTS_JSON, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=1, default=str)
        write_report(entries, results, args.max_nodes, args.oracle)
    bugs = [r["id"] for r in results if r["status"] == "reader bug"]
    print(f"{len(results)} nets; reader bugs: {len(bugs)}")
    return 1 if bugs else 0


if __name__ == "__main__":
    sys.exit(main())
