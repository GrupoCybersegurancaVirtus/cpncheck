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
from typing import Dict, List, Optional

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
                fusion = pl.find("fusioninfo")
                places[pl.get("id")] = {
                    "name": _name(pl),
                    "initmark": (pl.find("initmark").findtext("text")
                                 if pl.find("initmark") is not None else None),
                    "port": port.get("type") if port is not None else None,
                    "type": _inscription(pl, "type"),
                    "fusion": fusion.get("name") if fusion is not None else None,
                }
            for tr in page.iter("trans"):
                sub = tr.find("subst")
                trans[tr.get("id")] = {
                    "name": _name(tr),
                    "guard": (tr.find("cond").findtext("text")
                              if tr.find("cond") is not None else None),
                    "subpage": sub.get("subpage") if sub is not None else None,
                    # (socket id, port id) pairs binding this substitution
                    # transition's sockets to the ports of its subpage.
                    "portsock": re.findall(r"\(([^,]+),([^)]+)\)",
                                           sub.get("portsock") or "")
                    if sub is not None else [],
                    # Inscriptions the state-space semantics depends on but
                    # that are not supported; read so that they are refused
                    # rather than ignored.
                    "time": _inscription(tr, "time"),
                    "code": _inscription(tr, "code"),
                    "priority": _inscription(tr, "priority"),
                    "channel": _inscription(tr, "channel"),
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

        self.prime_ids = self._prime_page_ids()

    # -- helpers ---------------------------------------------------------

    # Method to list the pages instantiated at the top of the hierarchy.
    def _prime_page_ids(self) -> List[str]:
        """Ids of the prime page instances, in file order.

        CPN Tools records the instance hierarchy in ``<instances>``: each
        top-level ``<instance page=...>`` is a prime page instance, and every
        one of them is part of the model. A file without that element (written
        by another tool) falls back to the pages that no substitution
        transition refers to.

        Returns:
            list: Page ids; a page instantiated twice appears twice.
        """
        instances = self.cpnet.find("instances")
        if instances is not None:
            ids = [inst.get("page") for inst in instances.findall("instance")
                   if inst.get("page") in self.page_by_id]
            if ids:
                return ids
        used = {tr["subpage"] for page in self.page_by_id.values()
                for tr in page["transitions"].values() if tr["subpage"]}
        return [pid for pid in self.page_by_id if pid not in used]

    # Method to return the prime pages of the net.
    def prime_pages(self) -> List[Dict]:
        """Every prime page instance, in file order.

        Returns:
            list: Page entries.
        """
        return [self.page_by_id[pid] for pid in self.prime_ids]

    # Method to return the first prime page.
    def top_page(self) -> Dict:
        """The first prime page: *the* top page of a net that has one.

        Returns:
            dict: The page entry.

        Raises:
            ValueError: If the file has no page at all.
        """
        primes = self.prime_pages()
        if not primes:
            raise ValueError(f"{self.path}: the net has no page")
        return primes[0]

    # Method to list the fusion sets declared in the file.
    def fusion_sets(self) -> Dict[str, List[str]]:
        """Fusion set name -> ids of its member places.

        Returns:
            dict: The sets, from the ``fusioninfo`` of every place.
        """
        sets: Dict[str, List[str]] = {}
        for page in self.page_by_id.values():
            for pid, pl in page["places"].items():
                if pl["fusion"]:
                    sets.setdefault(pl["fusion"], []).append(pid)
        return sets


# Function to read the name of a place or transition on one line.
def _name(element) -> str:
    """The element's name, with line breaks and runs of spaces collapsed.

    CPN Tools lets a name wrap over several lines in the drawing; the line
    breaks are layout, not part of the name.

    Args:
        element (Element): A place or transition.

    Returns:
        str: The name.
    """
    return " ".join((element.findtext("text") or "").split())


# Function to read the text of an inscription child of a net element.
def _inscription(element, tag: str) -> Optional[str]:
    """The stripped text of ``<tag><text>...</text></tag>``, or None if empty.

    Args:
        element (Element): A place or transition.
        tag (str): The inscription element.

    Returns:
        str|None: The text, or None when absent or blank.
    """
    child = element.find(tag)
    if child is None:
        return None
    text = child.find("text")
    if text is None:
        return None
    value = "".join(text.itertext()).strip()
    return value or None
