"""How much of CPN Tools' own example models CPNCheck can check.

Runs every net under CPN Tools' ``Sample CPN Models`` through the reader and,
when it loads, through the occurrence graph; prints one line per net and a
summary of why the others are refused. With ``--oracle`` the occurrence graph
of every supported net is also compared with the one CPN Tools computes.

    python examples/cpntools_samples.py
    python examples/cpntools_samples.py --oracle
    python examples/cpntools_samples.py --samples "D:/CPN Tools/Sample CPN Models"
"""

import argparse
import collections
import glob
import os
import re
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from cpncheck.coloured import ColouredNet, UnsupportedNet  # noqa: E402
from cpncheck.net import CPNNet                            # noqa: E402
from cpncheck.statespace import build_state_space          # noqa: E402

DEFAULT_SAMPLES = r"C:\Program Files (x86)\CPN Tools\Sample CPN Models"

#: Samples CPN Tools itself cannot run headless, and why.
CANNOT_RUN = {
    "DiningPhilosophers_COMM_Mon.cpn":
        "opens a Comms/CPN connection when it is loaded",
}

#: Refusal messages grouped into the roadmap item that would lift them.
CATEGORIES = [
    (r"random|exponential|uniform", "random values (no occurrence graph)"),
    (r"@\+\+|real-valued|integer delays", "real-valued time"),
    (r"code segment", "code segments with side effects or full SML"),
    (r"priority", "transition priorities (phase 3)"),
    (r"channel", "synchronous channels"),
    (r"fusion", "fusion set conflict"),
    (r"expected 'else', found '`'", "multisets inside if/case (phase 3)"),
    (r"input arc .*(unexpected '\('|cannot start a pattern)",
     "non-pattern input arc expressions (phase 3)"),
    (r"not bound by an input arc", "variables not bound by input arcs (phase 3)"),
]


# Function to name the roadmap item a refusal belongs to.
def categorise(message: str) -> str:
    """Map a refusal message to a short category.

    Args:
        message (str): The :class:`UnsupportedNet` message.

    Returns:
        str: The category, or ``"other"``.
    """
    for pattern, label in CATEGORIES:
        if re.search(pattern, message, re.S):
            return label
    return "other"


# Function to run the sweep and print the table.
def main(argv=None) -> int:
    """Check every sample and print the coverage.

    Args:
        argv (list, optional): Command-line arguments.

    Returns:
        int: Process exit status (1 when a net failed with something other
        than a refusal, which is a reader bug).
    """
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--samples", default=DEFAULT_SAMPLES)
    ap.add_argument("--max-nodes", type=int, default=20_000)
    ap.add_argument("--oracle", action="store_true",
                    help="compare every supported net with CPN Tools")
    args = ap.parse_args(argv)

    paths = sorted(glob.glob(os.path.join(args.samples, "**", "*.cpn"),
                             recursive=True))
    if not paths:
        print(f"no .cpn files under {args.samples}")
        return 1
    oracle = None
    if args.oracle:
        from cpncheck.oracle import CPNToolsOracle
        oracle = CPNToolsOracle()
        if oracle.missing():
            print("CPN Tools engine incomplete:", ", ".join(oracle.missing()))
            return 1

    reasons = collections.Counter()
    supported = bugs = over_budget = agreed = 0
    for path in paths:
        name = os.path.relpath(path, args.samples)
        try:
            net = ColouredNet(CPNNet(path))
        except UnsupportedNet as exc:
            message = " ".join(str(exc).split())
            reasons[categorise(message)] += 1
            print(f"  refused   {name:52s} {message[:90]}")
            continue
        except Exception as exc:                      # noqa: BLE001
            bugs += 1
            print(f"  BUG       {name:52s} {type(exc).__name__}: {exc}")
            continue
        t0 = time.perf_counter()
        try:
            ss = build_state_space(net, args.max_nodes)
        except UnsupportedNet as exc:
            # Some constructs only show when an expression is evaluated.
            message = " ".join(str(exc).split())
            reasons[categorise(message)] += 1
            print(f"  refused   {name:52s} {message[:90]}")
            continue
        supported += 1
        line = (f"  checked   {name:52s} {ss.n_nodes} nodes"
                f"{'' if ss.complete else ' (budget)'}, {ss.n_arcs} arcs, "
                f"{len(ss.dead)} dead, {time.perf_counter() - t0:.1f}s")
        if not ss.complete:
            over_budget += 1
        if oracle is not None and not ss.complete:
            line += "  CPN Tools: not compared (over budget)"
        elif oracle is not None and os.path.basename(path) in CANNOT_RUN:
            line += f"  CPN Tools: cannot run it ({CANNOT_RUN[os.path.basename(path)]})"
        elif oracle is not None:
            from cpncheck.oracle import compare_state_space
            report = compare_state_space(path, oracle=oracle,
                                         max_nodes=args.max_nodes)
            if report["agree"]:
                agreed += 1
            line += "  CPN Tools: " + ("agrees" if report["agree"] else
                                       f"DISAGREES {report['rows']}")
        print(line)

    print()
    print(f"{supported} of {len(paths)} sample nets explored "
          f"({over_budget} over the budget of {args.max_nodes} markings), "
          f"{len(paths) - supported - bugs} refused, {bugs} reader bug(s)")
    if oracle is not None:
        print(f"{agreed} agree with CPN Tools")
    for label, count in reasons.most_common():
        print(f"  {count:3d}  {label}")
    return 1 if bugs else 0


if __name__ == "__main__":
    sys.exit(main())
