"""CPNCheck -- a model checker for Coloured Petri Nets.

CPN Tools answers verification questions interactively: enter the state-space
tool, calculate the occurrence graph and the SCC graph, paste an ASK-CTL script
into an auxiliary box and evaluate it. CPNCheck answers the same questions from
Python, on the very ``.cpn`` file CPN Tools would open, and cross-checks its
answers against CPN Tools itself.

    >>> from cpncheck import check_cpn
    >>> result = check_cpn("model.cpn", properties="AG !dead")
    >>> print(result.report())

Layers, bottom up:

=========================  ====================================================
:mod:`cpncheck.net`        parse the ``.cpn`` XML
:mod:`cpncheck.coloured`   compile the CPN ML fragment; flatten; fire
:mod:`cpncheck.statespace` occurrence graph, SCCs, home markings
:mod:`cpncheck.reduction`  stubborn-set reduced graphs (partial-order reduction)
:mod:`cpncheck.ctl`        CTL fixpoints over the occurrence graph
:mod:`cpncheck.properties` the property catalog
:mod:`cpncheck.result`     verdicts and reports (text, JSON, LaTeX)
:mod:`cpncheck.checker`    the four techniques, and the public entry points
:mod:`cpncheck.oracle`     run CPN Tools 4.0.1 headless and compare
:mod:`cpncheck.mutation`   mutants: every property must be able to fail
=========================  ====================================================
"""

from .checker import CPNModelChecker, check_cpn
from .coloured import ColouredNet, UnsupportedNet
from .net import CPNNet
from .properties import METHODS, Property, catalog
from .result import ModelCheckResult, PropertyResult, compare_results
from .statespace import DEFAULT_MAX_NODES, StateSpace, build_state_space

__version__ = "0.1.0.dev0"

__all__ = [
    "CPNModelChecker",
    "CPNNet",
    "ColouredNet",
    "DEFAULT_MAX_NODES",
    "METHODS",
    "ModelCheckResult",
    "catalog",
    "Property",
    "PropertyResult",
    "StateSpace",
    "UnsupportedNet",
    "__version__",
    "build_state_space",
    "check_cpn",
    "compare_results",
]
