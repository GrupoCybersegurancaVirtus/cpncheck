"""Command line interface: ``cpncheck <command> ...``.

Commands:

``check``
    Verify a ``.cpn`` file and print the report.
``askctl``
    Write the ASK-CTL script that asks CPN Tools the same questions.
``mutants``
    Derive one mutant per property, each a net that must fail that property.
``oracle``
    Run CPN Tools headless on the file and compare its answers with ours.
"""

import argparse
import json
import sys


# Function to parse a comma-separated list of integers.
def _labels(text):
    """Parse ``--labels 0,1,2``.

    Args:
        text (str): The option value, or None.

    Returns:
        list|None: The labels.
    """
    return None if not text else [int(v) for v in text.split(",")]


# Function to run the check command.
def _cmd_check(args):
    """Verify a net and print the report.

    Args:
        args (Namespace): Parsed options.

    Returns:
        int: Process exit status.
    """
    from .checker import check_cpn

    result = check_cpn(args.net, class_labels=_labels(args.labels),
                       max_nodes=args.max_nodes, verbose=args.verbose)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result.to_dict(), fh, indent=2)
    if args.latex:
        print(result.latex_table())
    else:
        print(result.report())
    return 0 if result.passed else 1


# Function to run the askctl command.
def _cmd_askctl(args):
    """Write the ASK-CTL script for CPN Tools.

    Args:
        args (Namespace): Parsed options.

    Returns:
        int: Process exit status.
    """
    from .checker import CPNModelChecker

    mc = CPNModelChecker(args.net, class_labels=_labels(args.labels))
    path = mc.export_askctl(args.out)
    print(path)
    return 0


# Function to run the mutants command.
def _cmd_mutants(args):
    """Derive the mutants of a correct net.

    Args:
        args (Namespace): Parsed options.

    Returns:
        int: Process exit status.
    """
    from .mutation import make_mutants

    only = args.only.split(",") if args.only else None
    for m in make_mutants(args.net, args.out_dir, names=only):
        print(f"{m['name']:<16} must fail {','.join(m['targets']):<12} {m['path']}")
    return 0


# Function to run the oracle command.
def _cmd_oracle(args):
    """Compare our answers with CPN Tools'.

    Args:
        args (Namespace): Parsed options.

    Returns:
        int: Process exit status.
    """
    from .oracle import CPNToolsOracle, compare_with_oracle

    oracle = CPNToolsOracle()
    missing = oracle.missing()
    if missing:
        print("CPN Tools engine not available: " + ", ".join(missing),
              file=sys.stderr)
        return 2
    report = compare_with_oracle(args.net, oracle=oracle,
                                 class_labels=_labels(args.labels))
    bad = 0
    for key, ours, theirs, agree in report["rows"]:
        if not agree:
            bad += 1
        print(f"  {key:<12}{str(ours):<10}{str(theirs):<10}"
              f"{'ok' if agree else 'DISAGREE'}")
    print("agreement" if report["agree"] else f"{bad} disagreement(s)")
    return 0 if report["agree"] else 1


# Function to build the argument parser.
def build_parser():
    """Assemble the command line parser.

    Returns:
        ArgumentParser: The parser.
    """
    from .statespace import DEFAULT_MAX_NODES

    parser = argparse.ArgumentParser(
        prog="cpncheck", description="Model checking for Coloured Petri Nets.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check", help="verify a .cpn file")
    p.add_argument("net")
    p.add_argument("--labels", help="label domain, e.g. 0,1,2")
    p.add_argument("--max-nodes", type=int, default=DEFAULT_MAX_NODES)
    p.add_argument("--json", help="also write the verdicts as JSON")
    p.add_argument("--latex", action="store_true", help="print a LaTeX table")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=_cmd_check)

    p = sub.add_parser("askctl", help="write the ASK-CTL script for CPN Tools")
    p.add_argument("net")
    p.add_argument("-o", "--out", default="askctl.sml")
    p.add_argument("--labels")
    p.set_defaults(func=_cmd_askctl)

    p = sub.add_parser("mutants", help="derive one mutant per property")
    p.add_argument("net")
    p.add_argument("out_dir")
    p.add_argument("--only", help="restrict to these operators")
    p.set_defaults(func=_cmd_mutants)

    p = sub.add_parser("oracle", help="cross-check against CPN Tools")
    p.add_argument("net")
    p.add_argument("--labels")
    p.set_defaults(func=_cmd_oracle)
    return parser


# Function to run the command line interface.
def main(argv=None):
    """Entry point.

    Args:
        argv (list, optional): Arguments; ``sys.argv[1:]`` when omitted.

    Returns:
        int: Process exit status.
    """
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
