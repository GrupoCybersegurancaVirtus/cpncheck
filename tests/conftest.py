"""Make the package importable from a checkout without installing it."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# CPNCheck's own tests run as a standalone install would: no profile plugins
# (pyruleanalyzer's tree profile may be installed on the developer's machine,
# and must not make a test pass that would fail without it).
import cpncheck.profile as _profile  # noqa: E402

_profile._PLUGINS_LOADED = True
