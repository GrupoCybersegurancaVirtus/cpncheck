"""Run every numbered example in order and report which ones failed.

    python examples/run_all.py              # all of them
    python examples/run_all.py 05 08        # only those whose name starts so
    python examples/run_all.py --quiet      # only the summary
"""

import glob
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


# Function to run the examples.
def main(argv) -> int:
    """Run the selected examples.

    Args:
        argv (list): Prefixes of the examples to run, and ``--quiet``.

    Returns:
        int: 0 when every example ran cleanly, 1 otherwise.
    """
    quiet = "--quiet" in argv
    prefixes = [a for a in argv if not a.startswith("--")]
    scripts = sorted(glob.glob(os.path.join(HERE, "[0-9][0-9]_*.py")))
    if prefixes:
        scripts = [s for s in scripts
                   if any(os.path.basename(s).startswith(p) for p in prefixes)]
    failed = []
    for script in scripts:
        name = os.path.basename(script)
        t0 = time.perf_counter()
        done = subprocess.run([sys.executable, script], capture_output=True,
                              text=True, cwd=HERE)
        took = time.perf_counter() - t0
        status = "ok" if done.returncode == 0 else "FAILED"
        print(f"{'=' * 20} {name} ({took:.1f}s): {status}")
        if not quiet or done.returncode:
            print(done.stdout)
            if done.returncode:
                print(done.stderr)
        if done.returncode:
            failed.append(name)
    print(f"{len(scripts) - len(failed)} of {len(scripts)} examples ran cleanly"
          + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
