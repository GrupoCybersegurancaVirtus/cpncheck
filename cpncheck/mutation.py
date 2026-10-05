"""Mutants: every property must be able to fail.

A checker that answers "true" on correct nets has shown nothing until it is
also seen answering "false" on incorrect ones. A *mutation operator* derives,
from a correct net, one that a named property must reject -- a small edit of a
guard, an inscription or an arc, chosen so that exactly that property breaks.

This module holds the machinery: :class:`CPNDocument`, which edits a ``.cpn``
in place while keeping it a file CPN Tools can open, and the driver that writes
one mutant per operator. The operators themselves are supplied by the profile,
because what a meaningful fault *is* depends on what the net is for; see
pyruleanalyzer's ``cpn_mutants`` for a worked set of sixteen.

Edits only touch guards, inscriptions and arcs (copies of existing arcs), so a
mutant is still a loadable net, and the same mutants can be given to both
engines in the cross-check.
"""

import copy
import os
import re
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .coloured import ColouredNet, UnsupportedNet
from .net import CPNNet

__all__ = ["CPNDocument", "Mutant", "make_mutants"]


# Class wrapping a .cpn file for in-place edits that keep it loadable.
class CPNDocument:
    """A ``.cpn`` file opened for editing.

    The XML prologue (declaration and CPN Tools DOCTYPE) is kept verbatim, and
    new elements get fresh identifiers.
    """

    # Method to open a .cpn file.
    def __init__(self, path: str):
        """Parse the file.

        Args:
            path (str): The ``.cpn`` to edit.
        """
        with open(path, "rb") as fh:
            raw = fh.read().decode("iso-8859-1")
        start = raw.index("<workspaceElements")
        self.prologue = raw[:start]
        self.root = ET.fromstring(raw[start:].encode("iso-8859-1"))
        self.pages = {p.find("pageattr").get("name"): p for p in self.root.iter("page")}
        ids = [int(m.group(1)) for el in self.root.iter()
               for m in [re.fullmatch(r"ID(\d+)", el.get("id") or "")] if m]
        self._next_id = max(ids, default=1000000) + 1

    # Method to allocate an unused element identifier.
    def new_id(self) -> str:
        """A fresh ``ID<n>`` identifier.

        Returns:
            str: The identifier.
        """
        self._next_id += 1
        return f"ID{self._next_id}"

    # Method to find a transition element by page and name.
    def trans(self, page: str, name: str):
        """The ``<trans>`` element named ``name`` on ``page``.

        Args:
            page (str): Page name.
            name (str): Transition name.

        Returns:
            Element: The transition.
        """
        for t in self.pages[page].findall("trans"):
            if (t.findtext("text") or "").strip() == name:
                return t
        raise KeyError(f"{page}/{name}")

    # Method to find a place element by page and name.
    def place(self, page: str, name: str):
        """The ``<place>`` element named ``name`` on ``page``.

        Args:
            page (str): Page name.
            name (str): Place name.

        Returns:
            Element: The place.
        """
        for p in self.pages[page].findall("place"):
            if (p.findtext("text") or "").strip() == name:
                return p
        raise KeyError(f"{page}/{name}")

    # Method to list the arcs of a transition.
    def arcs(self, page: str, trans_name: str, orientation: Optional[str] = None):
        """Arcs attached to a transition.

        Args:
            page (str): Page name.
            trans_name (str): Transition name.
            orientation (str, optional): ``"PtoT"`` or ``"TtoP"``.

        Returns:
            list: The ``<arc>`` elements.
        """
        tid = self.trans(page, trans_name).get("id")
        return [a for a in self.pages[page].findall("arc")
                if a.find("transend").get("idref") == tid
                and (orientation is None or a.get("orientation") == orientation)]

    # Method to replace a transition guard.
    def set_guard(self, page: str, trans_name: str, text: str):
        """Replace a transition's guard.

        Args:
            page (str): Page name.
            trans_name (str): Transition name.
            text (str): New guard, e.g. ``"[false]"``.
        """
        self.trans(page, trans_name).find("cond/text").text = text

    # Method to read a transition guard.
    def guard(self, page: str, trans_name: str) -> str:
        """A transition's guard text.

        Args:
            page (str): Page name.
            trans_name (str): Transition name.

        Returns:
            str: The guard.
        """
        return self.trans(page, trans_name).findtext("cond/text") or ""

    # Method to replace the inscription of an arc.
    @staticmethod
    def set_inscription(arc, text: str):
        """Replace an arc's inscription.

        Args:
            arc (Element): The arc.
            text (str): New inscription.
        """
        arc.find("annot/text").text = text

    # Method to remove an arc.
    def remove_arc(self, page: str, arc):
        """Delete an arc from a page.

        Args:
            page (str): Page name.
            arc (Element): The arc to remove.
        """
        self.pages[page].remove(arc)

    # Method to add an arc as a copy of an existing one.
    def add_arc(self, page: str, template, orientation: str, trans_el, place_el,
                text: str):
        """Add an arc, cloned from ``template`` so every attribute CPN Tools
        expects is present.

        Args:
            page (str): Page name.
            template (Element): Arc to clone.
            orientation (str): ``"PtoT"`` or ``"TtoP"``.
            trans_el (Element): Transition end.
            place_el (Element): Place end.
            text (str): Inscription.

        Returns:
            Element: The new arc.
        """
        arc = copy.deepcopy(template)
        for el in arc.iter():
            if el.get("id"):
                el.set("id", self.new_id())
        arc.set("orientation", orientation)
        arc.find("transend").set("idref", trans_el.get("id"))
        arc.find("placeend").set("idref", place_el.get("id"))
        arc.find("annot/text").text = text
        self.pages[page].append(arc)
        return arc

    # Method to change the place an arc is attached to.
    def retarget(self, arc, place_el):
        """Attach an arc to another place of the same page.

        Args:
            arc (Element): The arc.
            place_el (Element): New place end.
        """
        arc.find("placeend").set("idref", place_el.get("id"))

    # Method to name the place an arc is attached to.
    def place_of(self, page: str, arc) -> str:
        """Name of the place at the end of an arc.

        Args:
            page (str): Page name.
            arc (Element): The arc.

        Returns:
            str: The place name.
        """
        pid = arc.find("placeend").get("idref")
        for p in self.pages[page].findall("place"):
            if p.get("id") == pid:
                return (p.findtext("text") or "").strip()
        raise KeyError(pid)

    # Method to write the edited document.
    def save(self, path: str) -> str:
        """Write the document, keeping the original prologue.

        Args:
            path (str): Destination.

        Returns:
            str: The path written.
        """
        body = ET.tostring(self.root, encoding="unicode")
        with open(path, "wb") as fh:
            fh.write((self.prologue + body + "\n").encode("iso-8859-1",
                                                          "xmlcharrefreplace"))
        return path


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

# Class describing one mutation operator.
class Mutant:
    """A mutation operator: an edit, and the properties it must break.

    Attributes:
        name (str): Identifier used in file names and reports.
        targets (tuple): Properties the mutant must make fail.
        applies (callable): ``info -> bool``; whether the operator suits this
            net, given whatever the profile's analysis produced.
        description (str): What the edit does.
        build (callable): ``build(doc, info) -> bool``; returns False when the
            net has nothing to mutate this way.
    """

    __slots__ = ("name", "targets", "applies", "description", "build")

    # Method to create a mutation operator.
    def __init__(self, name, targets, applies, description, build):
        """Create the operator.

        Args:
            name (str): Identifier.
            targets (tuple): Properties that must fail.
            applies (callable): Applicability test.
            description (str): The edit.
            build (callable): The edit itself.
        """
        self.name = name
        self.targets = targets
        self.applies = applies
        self.description = description
        self.build = build

    # Method to render the operator for debugging.
    def __repr__(self):
        """Return a short representation.

        Returns:
            str: ``<Mutant deadlock -> A2, A3>``.
        """
        return f"<Mutant {self.name} -> {', '.join(self.targets)}>"


# ---------------------------------------------------------------------------
# The driver
# ---------------------------------------------------------------------------

# Function to write every applicable mutant of a net.
def make_mutants(path: str, out_dir: str, names: Optional[List[str]] = None,
                 profile=None) -> List[Dict[str, object]]:
    """Derive the mutants of a correct net, one file per operator.

    Args:
        path (str): The correct ``.cpn``.
        out_dir (str): Where the mutants are written.
        names (list, optional): Restrict to these operators.
        profile (Profile, optional): The profile supplying the operators;
            detected from the net when omitted.

    Returns:
        list: ``{"name", "targets", "description", "path", "options"}`` per
        mutant written. ``options`` are the profile settings the mutant has to
        be checked with, when the profile's analysis gives any.

    Raises:
        UnsupportedNet: When no profile recognises the net.
    """
    from . import profiles as _profiles      # noqa: F401  (registers built-ins)
    from .profile import detect

    if profile is None:
        profile = detect(ColouredNet(CPNNet(path)))
    if profile is None:
        raise UnsupportedNet(f"{os.path.basename(path)}: no profile recognises "
                             "this net, so there are no mutation operators")
    operators = profile.mutation_operators()
    info = profile.analyse_for_mutation(path) or {}
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    written = []
    for op in operators:
        if names and op.name not in names:
            continue
        if not op.applies(info):
            continue
        doc = CPNDocument(path)
        if not op.build(doc, info):
            continue
        dst = os.path.join(out_dir, f"{stem}__{op.name}.cpn")
        doc.save(dst)
        written.append({"name": op.name, "targets": op.targets,
                        "description": op.description, "path": dst,
                        "options": dict(info.get("options") or {})})
    return written
