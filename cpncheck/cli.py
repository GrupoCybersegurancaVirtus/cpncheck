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


# Function to parse the -O KEY=VALUE settings for the profile.
def _options(pairs):
    """Turn ``-O class_labels=0,1,2 -O use_final=false`` into a dict.

    Values are strings, except ``true``/``false``; a profile parses the rest
    (the tree profile reads ``class_labels=0,1,2`` as a list).

    Args:
        pairs (list): ``KEY=VALUE`` strings, or None.

    Returns:
        dict: The options.

    Raises:
        SystemExit: On an item without ``=``.
    """
    out = {}
    for item in pairs or []:
        if "=" not in item:
            raise SystemExit(f"cpncheck: -O expects KEY=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        lowered = value.strip().lower()
        out[key.strip()] = ({"true": True, "false": False}.get(lowered,
                                                                value.strip()))
    return out


# Function to run the check command.
def _cmd_check(args):
    """Verify a net and print the report.

    Args:
        args (Namespace): Parsed options.

    Returns:
        int: Process exit status.
    """
    from .checker import check_cpn

    from .query import load_properties, parse_properties

    props = []
    for path in args.props or []:
        props.extend(load_properties(path))
    for text in args.prop or []:
        props.extend(parse_properties(text, first=len(props) + 1))
    # Automatic ids must not collide when several sources are mixed.
    ids = [p.id for p in props]
    if len(ids) != len(set(ids)):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        raise SystemExit(f"duplicate property ids: {', '.join(dup)}")
    result = check_cpn(args.net, options=_options(args.option),
                       max_nodes=args.max_nodes, verbose=args.verbose,
                       reduction=args.reduction, properties=props or None,
                       progress=args.progress,
                       equivalence=args.equivalence,
                       symmetry=args.symmetry,
                       askctl=args.askctl or None)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result.to_dict(), fh, indent=2)
    if args.latex:
        print(result.latex_table())
    else:
        print(result.report())
        if args.trace:
            print(_traces(result))
    return 0 if result.passed else 1


# Function to render the full counterexample of every violated property.
def _traces(result):
    """Full occurrence sequences, with bindings, for the failed properties.

    The report elides long traces; this prints them whole, with the variable
    binding of every occurrence, and says whether each one replays.

    Args:
        result (ModelCheckResult): The verdicts.

    Returns:
        str: The section, or a note that there is nothing to show.
    """
    failures = [r for r in result.failures if r.cex is not None]
    if not failures:
        return "  no counterexamples to show"
    lines = ["  Counterexamples", "  " + "-" * 78]
    for r in failures:
        cex = r.cex
        lines.append(f"  {r.id}  [{cex.kind}] {cex.note}")
        if cex.input is not None:
            lines.append(f"        input   : {cex.input}")
        if cex.prefix or cex.cycle:
            lines.append(f"        sequence: "
                         f"{cex.sequence(limit=10 ** 6, bindings=True)}")
        for key, value in sorted(cex.data.items()):
            if key != "input_places":
                lines.append(f"        {key:<8}: {value}")
        lines.append("")
    return "\n".join(lines)


# Function to run the askctl command.
def _cmd_askctl(args):
    """Write the ASK-CTL script for CPN Tools.

    Args:
        args (Namespace): Parsed options.

    Returns:
        int: Process exit status.
    """
    from .checker import CPNModelChecker

    mc = CPNModelChecker(args.net, options=_options(args.option))
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
    written = make_mutants(args.net, args.out_dir, names=only)
    for m in written:
        print(f"{m['name']:<16} must fail {','.join(m['targets']):<12} {m['path']}")
    if not written:
        # Saying nothing would look like success.
        print("no mutants written: the net's profile has no mutation operator "
              "that applies to it" + (f" among {', '.join(only)}" if only else ""),
              file=sys.stderr)
        return 1
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
                                 options=_options(args.option))
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
    p.add_argument("-O", "--option", action="append", metavar="KEY=VALUE",
                   help="a setting for the net's profile, e.g. "
                        "class_labels=0,1,2; repeatable")
    p.add_argument("--max-nodes", type=int, default=DEFAULT_MAX_NODES)
    p.add_argument("--reduction",
                   choices=["stubborn", "sweep", "equivalence", "symmetry"],
                   default=None,
                   help="stubborn: stubborn-set reduced graphs; sweep: the "
                        "sweep-line method (properties of single markings); "
                        "equivalence: the quotient by time equivalence "
                        "(timed nets); symmetry: the quotient by --symmetry")
    p.add_argument("--equivalence", choices=["time"], default=None,
                   help="the equivalence of --reduction equivalence")
    p.add_argument("--symmetry", action="append", metavar="SETS=KIND",
                   help="colour sets permuted together and how, e.g. "
                        "PH,CS=rotation or PH=all; repeatable")
    p.add_argument("--progress", metavar="MEASURE",
                   help='sweep-line progress measure, e.g. "tokens(Done) - '
                        'tokens(Todo)" or "clock" (the default of a timed net)')
    p.add_argument("--props", action="append", metavar="FILE",
                   help="a file of properties to check (see cpncheck.query); "
                        "repeatable")
    p.add_argument("--prop", action="append", metavar="FORMULA",
                   help='one property, e.g. \'AG !(has(Eat, ph(1)) & '
                        'has(Eat, ph(2)))\'; repeatable')
    p.add_argument("--askctl", action="append", metavar="FILE",
                   help="ASK-CTL queries as CPN Tools takes them (.sml); each "
                        "top-level eval_node F InitNode is a property; "
                        "repeatable")
    p.add_argument("--json", help="also write the verdicts as JSON")
    p.add_argument("--latex", action="store_true", help="print a LaTeX table")
    p.add_argument("--trace", action="store_true",
                   help="print the full counterexample of every violation")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=_cmd_check)

    p = sub.add_parser("askctl", help="write the ASK-CTL script for CPN Tools")
    p.add_argument("net")
    p.add_argument("-o", "--out", default="askctl.sml")
    p.add_argument("-O", "--option", action="append", metavar="KEY=VALUE")
    p.set_defaults(func=_cmd_askctl)

    p = sub.add_parser("mutants", help="derive one mutant per property")
    p.add_argument("net")
    p.add_argument("out_dir")
    p.add_argument("--only", help="restrict to these operators")
    p.set_defaults(func=_cmd_mutants)

    p = sub.add_parser("oracle", help="cross-check against CPN Tools")
    p.add_argument("net")
    p.add_argument("-O", "--option", action="append", metavar="KEY=VALUE")
    p.set_defaults(func=_cmd_oracle)
    return parser


# Function to run the command line interface.
def main(argv=None):
    """Entry point.

    Args:
        argv (list, optional): Arguments; ``sys.argv[1:]`` when omitted.

    A property that does not parse and a net outside the supported fragment
    are the user's to fix, so they are reported as one message, not as a
    Python traceback.

    Returns:
        int: Process exit status (2 for those two errors).
    """
    from .coloured import UnsupportedNet
    from .query import QueryError
    from .equivalence import EquivalenceError
    from .sweepline import ProgressError

    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except QueryError as exc:
        print(f"cpncheck: property error: {exc}", file=sys.stderr)
    except ProgressError as exc:
        print(f"cpncheck: progress measure: {exc}", file=sys.stderr)
    except EquivalenceError as exc:
        print(f"cpncheck: reduction: {exc}", file=sys.stderr)
    except UnsupportedNet as exc:
        print(f"cpncheck: the net is not supported: {exc}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
