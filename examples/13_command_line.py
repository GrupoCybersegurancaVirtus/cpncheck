"""The command line, command by command.

Everything the Python API does is also available as ``cpncheck`` (installed
with the package; ``python -m cpncheck.cli`` works too). This script runs
each command on the example nets and shows its output.

    python examples/13_command_line.py

=====================================  ====================================
``cpncheck check NET``                 verify (default: CPN Tools' report)
``--prop F`` / ``--props FILE``        your properties (repeatable)
``--max-nodes N``                      occurrence-graph budget
``--reduction stubborn``               partial-order reduction
``--reduction sweep --progress M``     sweep-line method
``--reduction equivalence``            time equivalence (timed nets)
``--reduction symmetry --symmetry S``  symmetry, e.g. ``PH,CS=rotation``
``--json FILE`` / ``--latex``          machine-readable / paper output
``--trace``                            full counterexamples
``-O KEY=VALUE``                       a setting for the net's profile
``cpncheck askctl NET -o FILE``        ASK-CTL script for CPN Tools
``cpncheck mutants NET DIR``           one mutant per property (profiles
                                       with mutation operators)
``cpncheck oracle NET``                compare with CPN Tools (if installed)
=====================================  ====================================

Exit status: 0 when every requirement holds, 1 when one fails, 2 for an
unreadable property, an unsupported net or a bad reduction setting.
"""

import os
import subprocess
import sys
import tempfile

from _common import NETS, PROPERTIES, ROOT, section

OUT = tempfile.mkdtemp()


# Function to run one cpncheck command and show it.
def cpncheck(*args: str, lines: int = 14, only: tuple = ()) -> int:
    """Run ``cpncheck ARGS`` and print the command and its output.

    Args:
        *args (str): The arguments.
        lines (int): How many output lines to show.
        only (tuple): When given, show only the lines containing one of
            these strings.

    Returns:
        int: The exit status.
    """
    shown = " ".join(a if " " not in a else (f"'{a}'" if '"' in a else f'"{a}"')
                     for a in args)
    print(f"$ cpncheck {shown}".replace(NETS + os.sep, "nets/")
          .replace(PROPERTIES + os.sep, "properties/").replace(OUT + os.sep, ""))
    done = subprocess.run([sys.executable, "-m", "cpncheck.cli", *args],
                          capture_output=True, text=True, cwd=ROOT,
                          env={**os.environ, "PYTHONPATH": ROOT})
    text = (done.stdout + done.stderr).rstrip().splitlines()
    if only:
        text = [line for line in text if any(o in line for o in only)]
    for line in text[:lines]:
        print("  " + line)
    if len(text) > lines:
        print(f"  ... ({len(text) - lines} more lines)")
    print(f"  [exit status {done.returncode}]\n")
    return done.returncode


dining = os.path.join(NETS, "dining.cpn")
deadlock = os.path.join(NETS, "dining_deadlock.cpn")

section("check: the default report, and your properties")
cpncheck("check", dining, lines=20)
cpncheck("check", dining, "--props", os.path.join(PROPERTIES, "dining.props"),
         "--prop", "EF tokens(Eat) = 2", lines=30)

section("check: a violation, with the full counterexample")
cpncheck("check", deadlock, "--prop", "AG !dead", "--trace", lines=30)

section("check: reductions")
REDUCED = ("reduction  ", "consistency", "deadlock graph", " R1 ", " U1 ")
cpncheck("check", os.path.join(NETS, "pipelines.cpn"), "--reduction", "stubborn",
         "--prop", 'AF marked("Done 1")', only=REDUCED)
cpncheck("check", os.path.join(NETS, "workers.cpn"), "--reduction", "sweep",
         "--progress", "2*tokens(Done) + tokens(Busy)",
         "--prop", "AG tokens(Busy) <= 6", only=REDUCED)
cpncheck("check", os.path.join(NETS, "timed_loop.cpn"),
         "--reduction", "equivalence", "--prop", "AG !dead", only=REDUCED)
cpncheck("check", dining, "--reduction", "symmetry",
         "--symmetry", "PH,CS=rotation", "--prop", "AG tokens(Eat) <= 2", only=REDUCED)

section("check: output for other programs")
cpncheck("check", dining, "--prop", "AG tokens(Eat) <= 2",
         "--json", os.path.join(OUT, "dining.json"), "--latex", lines=8)
print("  JSON written to", os.path.join(OUT, "dining.json"), "\n")

section("errors are one line, with exit status 2")
cpncheck("check", dining, "--prop", "AG marked(Kitchen)")
cpncheck("check", dining, "--reduction", "sweep")
cpncheck("check", dining, "--reduction", "symmetry", "--symmetry", "PH=swap")

section("askctl: the same properties for CPN Tools")
cpncheck("askctl", dining, "-o", os.path.join(OUT, "dining.sml"), lines=3)

section("mutants and oracle")
# The default profile has no mutation operators (see 10_custom_profile.py
# for a profile that has); the oracle needs CPN Tools (12_cpntools_oracle.py).
cpncheck("mutants", dining, os.path.join(OUT, "mutants"), lines=3)
cpncheck("oracle", dining, lines=10)
