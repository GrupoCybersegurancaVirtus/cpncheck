"""Nets other people wrote: read and explored, or refused by name.

The corpus (``tests/corpus/manifest.json``) is downloaded, not committed:
run ``python tests/corpus/corpus.py fetch`` first, or these tests skip. Every
net must either be explored or be refused with :class:`UnsupportedNet` and
a reason -- any other exception is a bug in CPNCheck. With
``CPNCHECK_CPNTOOLS=1``, every net whose graph fits the budget must also
agree with CPN Tools (``corpus.py run --oracle`` writes the full table to
``tests/corpus/RESULTS.md``).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "corpus"))
import corpus  # noqa: E402

ENTRIES = corpus.load_manifest()
FETCHED = [e for e in ENTRIES if corpus.verified(e)]

pytestmark = pytest.mark.skipif(
    not FETCHED, reason="corpus not fetched (python tests/corpus/corpus.py fetch)")


@pytest.mark.parametrize("entry", FETCHED, ids=[e["id"] for e in FETCHED])
def test_a_net_is_explored_or_refused_by_name(entry):
    result = corpus.explore(corpus.cached_path(entry), max_nodes=2_000)
    assert result["status"] != "reader bug", result.get("trace")
    if result["status"] == "refused":
        assert result["reason"].strip()


@pytest.mark.skipif(os.environ.get("CPNCHECK_CPNTOOLS") != "1",
                    reason="set CPNCHECK_CPNTOOLS=1 to compare with CPN Tools")
@pytest.mark.parametrize("entry", FETCHED, ids=[e["id"] for e in FETCHED])
def test_an_explored_net_agrees_with_cpntools(entry):
    from cpncheck.oracle import CPNToolsOracle

    path = corpus.cached_path(entry)
    result = corpus.explore(path, max_nodes=20_000)
    if result["status"] != "explored":
        pytest.skip(result["status"])
    oracle = CPNToolsOracle()
    if oracle.missing():
        pytest.skip("CPN Tools engine incomplete")
    verdict = corpus.against_cpntools(path, result["timed"], 20_000, oracle)
    if verdict["oracle"] == "rejected by CPN Tools":
        pytest.skip("CPN Tools' own compiler rejects the file")
    assert verdict["oracle"] in ("agree", "contained"), verdict
