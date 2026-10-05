"""Profiles shipped with CPNCheck.

Importing this package registers the built-in profile -- the state-space
report, for any net -- so that :func:`cpncheck.profile.detect` can find it.
Profiles for particular kinds of nets come from other packages as plugins
(entry-point group ``cpncheck.profiles``); pyruleanalyzer's tree profile is
one.
"""

from . import statespace_report  # noqa: F401  (the default, for any net)

__all__ = ["statespace_report"]
