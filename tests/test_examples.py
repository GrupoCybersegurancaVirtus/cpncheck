"""The examples run, and the example nets are what build_nets.py writes.

The examples are documentation that executes; a change that breaks one
breaks the documentation, so each is run here. The CPN Tools oracle example
and the command-line tour (which also calls the oracle) only with
``CPNCHECK_CPNTOOLS=1``.
"""

import filecmp
import glob
import importlib.util
import os
import subprocess
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EXAMPLES = os.path.join(ROOT, "examples")
SCRIPTS = sorted(glob.glob(os.path.join(EXAMPLES, "[0-9][0-9]_*.py")))
NEEDS_CPNTOOLS = {"12_cpntools_oracle.py", "13_command_line.py"}


@pytest.mark.parametrize("script", SCRIPTS, ids=os.path.basename)
def test_the_example_runs(script):
    if os.path.basename(script) in NEEDS_CPNTOOLS and \
            os.environ.get("CPNCHECK_CPNTOOLS") != "1":
        pytest.skip("set CPNCHECK_CPNTOOLS=1 to run the examples that call "
                    "CPN Tools")
    done = subprocess.run([sys.executable, script], capture_output=True,
                          text=True, cwd=EXAMPLES, timeout=900,
                          env={**os.environ, "PYTHONPATH": ROOT})
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-3000:]
    assert done.stdout.strip()


def test_the_example_nets_are_up_to_date(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "build_nets", os.path.join(EXAMPLES, "nets", "build_nets.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "HERE", str(tmp_path))
    written = [module.dining(), module.dining("dining_deadlock", True),
               module.workers(), module.pipelines(), module.timed_jobs(),
               module.timed_loop(), module.ml_features()]
    for path in written:
        committed = os.path.join(EXAMPLES, "nets", os.path.basename(path))
        assert filecmp.cmp(path, committed, shallow=False), \
            f"{os.path.basename(path)} is stale: run examples/nets/build_nets.py"
