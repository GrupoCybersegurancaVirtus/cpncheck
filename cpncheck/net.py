"""Reading a CPN Tools ``.cpn`` file.

:class:`CPNNet` parses the XML CPN Tools writes: the page hierarchy, the
places with their colour sets and initial markings, the transitions with their
guards, the arcs with their inscriptions, and the substitution transitions with
their port/socket assignments.

Nothing here interprets the net. Interpretation is
:mod:`cpncheck.coloured` (compiling the CPN ML fragment and firing binding
elements) and :mod:`cpncheck.statespace` (the occurrence graph).

.. note::
   ``CPNNet.family``, ``CPNNet.leaf_outputs``, ``CPNNet.eval_subpage`` and
   ``CPNNet.sample_from_initial_marking`` are domain methods inherited from
   pyruleanalyzer and are scheduled to move out; see ``MIGRATION.md``.
"""

import re
import xml.etree.ElementTree as ET

__all__ = ["CPNNet", "sml_to_python"]

# ---------------------------------------------------------------------------
# SML -> Python
# ---------------------------------------------------------------------------

# Function to translate the SML subset emitted by the exporter into Python.
def sml_to_python(expr):
    """Translate the SML subset the exporter emits into a Python expression.

    Handles record field access (``#f0 x``), the boolean operators, and SML's
    ``~`` negation prefix.

    Args:
        expr (str): SML source as written in a guard or arc inscription.

    Returns:
        str: An equivalent Python expression over a dict named ``x``.
    """
    out = expr.strip()
    # CPN Tools writes guards wrapped in brackets: [ ... ]. Left in place they
    # would parse as a Python list literal, which is always truthy.
    if out.startswith("[") and out.endswith("]"):
        out = out[1:-1].strip()
    out = re.sub(r"#(f\d+)\s+x", r"x['\1']", out)
    out = out.replace("andalso", " and ").replace("orelse", " or ")
    # ~1.5 / ~2.0E~3 -> -1.5 / -2.0E-3 (SML negation, also inside exponents)
    out = re.sub(r"~(?=[\d.])", "-", out)
    out = out.replace("not (", " not (")
    out = re.sub(r"\btrue\b", "True", out)
    out = re.sub(r"\bfalse\b", "False", out)
    return out or "True"


# Function to evaluate a translated SML expression against a sample.
def _eval(expr, x):
    """Evaluate a translated SML expression against a sample.

    Args:
        expr (str): SML expression.
        x (dict): Sample keyed by record field name (``f0``, ``f1``, ...).

    Returns:
        The Python value of the expression.
    """
    return eval(sml_to_python(expr), {"__builtins__": {}}, {"x": x})  # noqa: S307


# ---------------------------------------------------------------------------
# .cpn parsing
# ---------------------------------------------------------------------------

# Class holding the parsed contents of a .cpn file.
class CPNNet:
    """The parsed contents of a ``.cpn`` file, as pages of guards and arcs."""

    # Method to parse a .cpn file into pages of places, transitions and arcs.
    def __init__(self, path):
        """Parse a ``.cpn`` file.

        Args:
            path (str): Path to the exported ``.cpn``.
        """
        self.path = path
        root = ET.parse(path).getroot()
        self.cpnet = root.find("cpnet")
        self.pages = {}          # page name -> dict(places, transitions, arcs)
        self.page_by_id = {}

        for page in self.cpnet.iter("page"):
            name_el = page.find("pageattr")
            pname = name_el.get("name") if name_el is not None else page.get("id")
            places, trans, arcs = {}, {}, []

            for pl in page.iter("place"):
                port = pl.find("port")
                places[pl.get("id")] = {
                    "name": (pl.findtext("text") or "").strip(),
                    "initmark": (pl.find("initmark").findtext("text")
                                 if pl.find("initmark") is not None else None),
                    "port": port.get("type") if port is not None else None,
                }
            for tr in page.iter("trans"):
                sub = tr.find("subst")
                trans[tr.get("id")] = {
                    "name": (tr.findtext("text") or "").strip(),
                    "guard": (tr.find("cond").findtext("text")
                              if tr.find("cond") is not None else None),
                    "subpage": sub.get("subpage") if sub is not None else None,
                    # (socket id, port id) pairs binding this substitution
                    # transition's sockets to the ports of its subpage.
                    "portsock": re.findall(r"\(([^,]+),([^)]+)\)",
                                           sub.get("portsock") or "")
                    if sub is not None else [],
                }
            for ar in page.iter("arc"):
                arcs.append({
                    "orient": ar.get("orientation"),
                    "trans": ar.find("transend").get("idref"),
                    "place": ar.find("placeend").get("idref"),
                    "expr": (ar.find("annot").findtext("text")
                             if ar.find("annot") is not None else "").strip(),
                })

            entry = {"id": page.get("id"), "name": pname, "places": places,
                     "transitions": trans, "arcs": arcs}
            self.pages[pname] = entry
            self.page_by_id[page.get("id")] = entry

    # -- helpers ---------------------------------------------------------

    # Method to return the top-level page, i.e. the one carrying Prediction.
    def top_page(self):
        """The top-level page of the net.

        Returns:
            dict: The page entry holding the ``Prediction`` place.

        Raises:
            ValueError: If no page carries a ``Prediction`` place.
        """
        for page in self.pages.values():
            if any(pl["name"] == "Prediction" for pl in page["places"].values()):
                return page
        raise ValueError("no page with a Prediction place")

    # Method to detect which model family the net encodes.
    def family(self):
        """Identify the model family from the shape of the top page.

        Returns:
            str: ``"Decision Tree"``, ``"Random Forest"`` or
            ``"Gradient Boosting Decision Trees"``.
        """
        top = self.top_page()
        subst = [tr for tr in top["transitions"].values() if tr["subpage"]]
        if not subst:
            return "Decision Tree"
        if all(tr["name"].startswith("Tree_") for tr in subst):
            return "Random Forest"
        return "Gradient Boosting Decision Trees"

    # Method to read the sample encoded in the input place's initial marking.
    def sample_from_initial_marking(self):
        """Read the sample encoded in the input place's initial marking.

        Returns:
            dict: Sample keyed by record field name, or None if absent.
        """
        for page in self.pages.values():
            for pl in page["places"].values():
                if pl["initmark"] and pl["name"] in ("Input",):
                    fields = re.findall(r"(f\d+)\s*=\s*\(?(~?[\d.eE~+-]+)\)?",
                                        pl["initmark"])
                    return {k: float(v.replace("~", "-")) for k, v in fields}
        return None

    # Method to list the guard/output pairs of every leaf transition on a page.
    def leaf_outputs(self, page):
        """Guard/output pairs of every leaf transition on a page.

        Args:
            page (dict): A page entry from `self.pages`.

        Returns:
            list: (transition name, guard string, output arc expression).
        """
        out = []
        for tid, tr in page["transitions"].items():
            if tr["subpage"]:
                continue
            outgoing = [a for a in page["arcs"]
                        if a["trans"] == tid and a["orient"] == "TtoP"]
            if not outgoing:
                continue
            out.append((tr["name"], tr["guard"] or "true", outgoing[0]["expr"]))
        return out

    # Method to evaluate one base-learner subpage by picking the enabled leaf.
    def eval_subpage(self, page_name, x):
        """Evaluate one base-learner subpage: pick the enabled leaf.

        Args:
            page_name (str): Name of the subpage.
            x (dict): Sample keyed by record field name.

        Returns:
            The leaf's output expression, or None if no leaf is enabled.

        Raises:
            AssertionError: If more than one leaf is enabled, i.e. the guards
                are not mutually exclusive for this sample.
        """
        enabled = [(n, e) for n, g, e in self.leaf_outputs(self.pages[page_name])
                   if _eval(g, x)]
        assert len(enabled) <= 1, (
            f"{page_name}: {len(enabled)} leaves enabled at once "
            f"({[n for n, _ in enabled]}) -- guards are not mutually exclusive"
        )
        return enabled[0][1] if enabled else None

