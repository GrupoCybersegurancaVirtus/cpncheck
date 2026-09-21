"""Profiles shipped with CPNCheck.

Importing this package registers every built-in profile, so that
:func:`cpncheck.profile.detect` can find them.
"""

from . import ml_trees  # noqa: F401  (registers the profile)
from . import ml_trees_mutants  # noqa: F401

__all__ = ["ml_trees", "ml_trees_mutants"]
