"""The nets CPN Tools ships with: read correctly, or refused by name.

CPN Tools installs a set of example models under ``Sample CPN Models``. They
were written by other people for other purposes, which makes them the honest
measure of how general CPNCheck is. Every one must either load or raise
:class:`UnsupportedNet` with a reason -- any other exception is a bug in the
reader. With ``CPNCHECK_CPNTOOLS=1``, every one that loads must also have the
occurrence graph CPN Tools computes.

Skipped when CPN Tools is not installed. ``python examples/cpntools_samples.py``
prints the same sweep as a table.
"""

import glob
import os

import pytest

from cpncheck.coloured import ColouredNet, UnsupportedNet
from cpncheck.net import CPNNet

SAMPLES_DIR = os.environ.get(
    "CPNTOOLS_SAMPLES",
    r"C:\Program Files (x86)\CPN Tools\Sample CPN Models")
SAMPLES = sorted(glob.glob(os.path.join(SAMPLES_DIR, "**", "*.cpn"),
                           recursive=True))
IDS = [os.path.relpath(p, SAMPLES_DIR) for p in SAMPLES]

pytestmark = pytest.mark.skipif(not SAMPLES,
                                reason="CPN Tools sample models not found")


@pytest.mark.parametrize("path", SAMPLES, ids=IDS)
def test_a_sample_is_read_or_refused_by_name(path):
    try:
        ColouredNet(CPNNet(path))
    except UnsupportedNet as exc:
        assert str(exc).strip(), "a refusal must say why"


@pytest.mark.skipif(os.environ.get("CPNCHECK_CPNTOOLS") != "1",
                    reason="set CPNCHECK_CPNTOOLS=1 to compare with CPN Tools")
@pytest.mark.parametrize("path", SAMPLES, ids=IDS)
def test_a_supported_sample_agrees_with_cpntools(path):
    from cpncheck.oracle import CPNToolsOracle, compare_state_space

    try:
        ColouredNet(CPNNet(path))
    except UnsupportedNet:
        pytest.skip("not supported yet")
    oracle = CPNToolsOracle()
    if oracle.missing():
        pytest.skip("CPN Tools engine incomplete")
    report = compare_state_space(path, oracle=oracle)
    assert not report["errors"], report["errors"]
    assert report["agree"], report["rows"]
