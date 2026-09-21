"""Reading a CPN Tools ``.cpn`` file.

:class:`CPNNet` parses the XML CPN Tools writes: the page hierarchy, the
places with their colour sets and initial markings, the transitions with their
guards, the arcs with their inscriptions, and the substitution transitions with
their port/socket assignments.

Nothing here interprets the net, and nothing here knows what any net is *for*.
Interpretation is :mod:`cpncheck.cpnml` and :mod:`cpncheck.coloured` (reading
the CPN ML, and firing binding elements), and :mod:`cpncheck.statespace` (the
occurrence graph). What a particular family of nets means is a profile's
business; see :mod:`cpncheck.profile`.
"""

import re
import xml.etree.ElementTree as ET

__all__ = ["CPNNet"]

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
