"""Write the example nets used by the scripts in ``examples/``.

The nets are small on purpose: each shows one feature, and each is small
enough for its full occurrence graph to be built, so a reduction can be
compared with it. They are written as the subset of the ``.cpn`` format that
CPN Tools' simulator (and CPNCheck) reads: declarations, pages, places,
transitions and arcs, without the drawing.

Run it again to regenerate them::

    python examples/nets/build_nets.py
"""

import os
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))


# Class collecting the declarations of a net.
class Declarations:
    """Colour sets, variables and ML declarations, as ``<globbox>`` XML."""

    # Method to start an empty declaration block.
    def __init__(self):
        """Create the block."""
        self.root = ET.Element("globbox")
        self._n = 0

    # Method to give the next element id.
    def _id(self) -> str:
        """A fresh id, in CPN Tools' style.

        Returns:
            str: The id.
        """
        self._n += 1
        return f"ID{100 + self._n}"

    # Method to declare a colour set.
    def colset(self, name: str, kind: str, *parts: str, timed: bool = False,
               bounds: Optional[Tuple[str, str]] = None,
               constructor: Optional[str] = None) -> "Declarations":
        """Declare ``colset name = ...``.

        Args:
            name (str): The colour set.
            kind (str): ``int``, ``unit``, ``bool``, ``string``, ``enum``
                (parts are the constants), ``product`` (parts are colour
                sets) or ``index`` (``index constructor with bounds``).
            *parts (str): Constants or components.
            timed (bool): Whether the colour set is timed.
            bounds (tuple, optional): For ``int with a..b`` and ``index``.
            constructor (str, optional): For ``index``.

        Returns:
            Declarations: Itself, to chain calls.
        """
        color = ET.SubElement(self.root, "color", id=self._id())
        ET.SubElement(color, "id").text = name
        if timed:
            ET.SubElement(color, "timed")
        body = ET.SubElement(color, kind)
        if kind in ("enum", "product"):
            for part in parts:
                ET.SubElement(body, "id").text = part
        elif kind == "index":
            for bound in bounds:
                ET.SubElement(body, "ml").text = bound
            ET.SubElement(body, "id").text = constructor
        elif bounds:
            with_ = ET.SubElement(body, "with")
            for bound in bounds:
                ET.SubElement(with_, "ml").text = bound
        return self

    # Method to declare variables.
    def var(self, colset: str, *names: str) -> "Declarations":
        """Declare ``var names : colset``.

        Args:
            colset (str): Their colour set.
            *names (str): The variables.

        Returns:
            Declarations: Itself.
        """
        var = ET.SubElement(self.root, "var", id=self._id())
        ET.SubElement(ET.SubElement(var, "type"), "id").text = colset
        for name in names:
            ET.SubElement(var, "id").text = name
        return self

    # Method to add an ML declaration.
    def ml(self, text: str) -> "Declarations":
        """Add a ``val``/``fun`` declaration.

        Args:
            text (str): The declaration.

        Returns:
            Declarations: Itself.
        """
        ET.SubElement(self.root, "ml", id=self._id()).text = text
        return self


# Function to add an element holding a text inscription.
def _text(parent, tag: str, value: str):
    """``<tag><text>value</text></tag>``.

    Args:
        parent: The parent element.
        tag (str): The element.
        value (str): The text.

    Returns:
        The new element.
    """
    el = ET.SubElement(parent, tag)
    ET.SubElement(el, "text").text = value
    return el


# Function to write a one-page net.
def write_net(name: str, decl: Declarations, places: Sequence[Tuple],
              transitions: Sequence[Tuple], arcs: Sequence[Tuple],
              page: str = "Top") -> str:
    """Write ``examples/nets/<name>.cpn``.

    Args:
        name (str): File stem.
        decl (Declarations): The declarations.
        places (sequence): ``(name, colset, initial marking or None)``.
        transitions (sequence): ``(name, guard or None, {inscription: text})``
            with inscriptions ``time``, ``code``, ``priority``.
        arcs (sequence): ``(transition, place, "in"|"out", inscription)``.
        page (str): The page name.

    Returns:
        str: The path written.
    """
    root = ET.Element("workspaceElements")
    cpnet = ET.SubElement(root, "cpnet")
    cpnet.append(decl.root)
    # Ids as CPN Tools writes them ("ID" and a number): its state-space
    # generator splits generated names on the letters P and F, so an id
    # such as "P0" would break it.
    pel = ET.SubElement(cpnet, "page", id="ID1")
    ET.SubElement(pel, "pageattr", name=page)
    pid: Dict[str, str] = {}
    for i, (pname, colset, initmark) in enumerate(places):
        pid[pname] = f"ID{1000 + i}"
        pl = ET.SubElement(pel, "place", id=pid[pname])
        ET.SubElement(pl, "text").text = pname
        _text(pl, "type", colset)
        if initmark:
            _text(pl, "initmark", initmark)
    tid: Dict[str, str] = {}
    for i, (tname, guard, extras) in enumerate(transitions):
        tid[tname] = f"ID{2000 + i}"
        tr = ET.SubElement(pel, "trans", id=tid[tname])
        ET.SubElement(tr, "text").text = tname
        _text(tr, "cond", guard or "")
        for tag, value in (extras or {}).items():
            _text(tr, tag, value)
    for i, (tname, pname, direction, text) in enumerate(arcs):
        arc = ET.SubElement(pel, "arc", id=f"ID{3000 + i}",
                            orientation="PtoT" if direction == "in" else "TtoP")
        ET.SubElement(arc, "transend", idref=tid[tname])
        ET.SubElement(arc, "placeend", idref=pid[pname])
        _text(arc, "annot", text)
    instances = ET.SubElement(cpnet, "instances")
    ET.SubElement(instances, "instance", id="ID2", page="ID1")
    path = os.path.join(HERE, f"{name}.cpn")
    ET.ElementTree(root).write(path, encoding="iso-8859-1",
                               xml_declaration=True)
    return path


# Function to write the dining philosophers.
def dining(name: str = "dining", one_at_a_time: bool = False) -> str:
    """Five philosophers, five chopsticks.

    With ``one_at_a_time`` a philosopher takes the left chopstick and then
    the right one, which can deadlock; otherwise both at once, which cannot.

    Args:
        name (str): File stem.
        one_at_a_time (bool): The deadlocking variant.

    Returns:
        str: The path written.
    """
    decl = (Declarations()
            .ml("val N = 5;")
            .colset("PH", "index", bounds=("1", "N"), constructor="ph")
            .colset("CS", "index", bounds=("1", "N"), constructor="cs")
            .var("PH", "p")
            .ml("fun Left(ph(i)) = cs(i);")
            .ml("fun Right(ph(i)) = cs(if i = N then 1 else i + 1);")
            .ml("fun Chopsticks(p) = 1`Left(p) ++ 1`Right(p);"))
    if not one_at_a_time:
        return write_net(name, decl, [
            ("Think", "PH", "PH.all()"), ("Eat", "PH", None),
            ("Unused Chopsticks", "CS", "CS.all()")], [
            ("Take Chopsticks", None, None), ("Put Down Chopsticks", None, None)], [
            ("Take Chopsticks", "Think", "in", "p"),
            ("Take Chopsticks", "Unused Chopsticks", "in", "Chopsticks(p)"),
            ("Take Chopsticks", "Eat", "out", "p"),
            ("Put Down Chopsticks", "Eat", "in", "p"),
            ("Put Down Chopsticks", "Unused Chopsticks", "out", "Chopsticks(p)"),
            ("Put Down Chopsticks", "Think", "out", "p")])
    return write_net(name, decl, [
        ("Think", "PH", "PH.all()"), ("Has Left", "PH", None), ("Eat", "PH", None),
        ("Unused Chopsticks", "CS", "CS.all()")], [
        ("Take Left", None, None), ("Take Right", None, None),
        ("Put Down", None, None)], [
        ("Take Left", "Think", "in", "p"),
        ("Take Left", "Unused Chopsticks", "in", "Left(p)"),
        ("Take Left", "Has Left", "out", "p"),
        ("Take Right", "Has Left", "in", "p"),
        ("Take Right", "Unused Chopsticks", "in", "Right(p)"),
        ("Take Right", "Eat", "out", "p"),
        ("Put Down", "Eat", "in", "p"),
        ("Put Down", "Unused Chopsticks", "out", "Chopsticks(p)"),
        ("Put Down", "Think", "out", "p")])


# Function to write independent workers.
def workers(n: int = 6) -> str:
    """``n`` workers, each going Idle -> Busy -> Done on its own.

    Nothing connects them, so the occurrence graph is every interleaving:
    ``3**n`` markings for one outcome. It is the textbook case for stubborn
    sets, for a progress measure and for symmetry.

    Args:
        n (int): How many workers.

    Returns:
        str: The path written.
    """
    decl = (Declarations()
            .ml(f"val W = {n};")
            .colset("WORKER", "index", bounds=("1", "W"), constructor="w")
            .var("WORKER", "x"))
    return write_net("workers", decl, [
        ("Idle", "WORKER", "WORKER.all()"), ("Busy", "WORKER", None),
        ("Done", "WORKER", None)], [
        ("Start", None, None), ("Finish", None, None)], [
        ("Start", "Idle", "in", "x"), ("Start", "Busy", "out", "x"),
        ("Finish", "Busy", "in", "x"), ("Finish", "Done", "out", "x")])


# Function to write independent workers, each with its own places.
def pipelines(n: int = 8) -> str:
    """The workers of :func:`workers`, unfolded: one sub-net per worker.

    Worker ``i`` has its own places ``Idle i``, ``Busy i``, ``Done i`` and
    transitions ``Start i``, ``Finish i``. Same behaviour, same ``3**n``
    markings -- but now the independence is visible in the arcs, which is
    what stubborn sets exploit.

    Args:
        n (int): How many workers.

    Returns:
        str: The path written.
    """
    decl = Declarations().colset("INT", "int").var("INT", "x")
    places, transitions, arcs = [], [], []
    for i in range(1, n + 1):
        places += [(f"Idle {i}", "INT", f"1`{i}"), (f"Busy {i}", "INT", None),
                   (f"Done {i}", "INT", None)]
        transitions += [(f"Start {i}", None, None), (f"Finish {i}", None, None)]
        arcs += [(f"Start {i}", f"Idle {i}", "in", "x"),
                 (f"Start {i}", f"Busy {i}", "out", "x"),
                 (f"Finish {i}", f"Busy {i}", "in", "x"),
                 (f"Finish {i}", f"Done {i}", "out", "x")]
    return write_net("pipelines", decl, places, transitions, arcs)


# Function to write a timed job shop.
def timed_jobs() -> str:
    """Three jobs share two machines; machine time depends on the job.

    Timed colour set ``JOB``: a job is ready when its timestamp is reached.
    Starting takes a machine (an untimed token) and stamps the job with its
    processing time; finishing frees the machine after a one-unit cleanup.

    Returns:
        str: The path written.
    """
    decl = (Declarations()
            .colset("JOB", "int", timed=True, bounds=("1", "3"))
            .colset("M", "enum", "m")
            .var("JOB", "j"))
    return write_net("timed_jobs", decl, [
        ("Waiting", "JOB", "1`1 ++ 1`2 ++ 1`3"), ("Machines", "M", "2`m"),
        ("Processing", "JOB", None), ("Finished", "JOB", None)], [
        ("Start", None, None), ("Finish", None, {"time": "@+1"})], [
        ("Start", "Waiting", "in", "j"), ("Start", "Machines", "in", "m"),
        ("Start", "Processing", "out", "j @+ (2 * j)"),
        ("Finish", "Processing", "in", "j"), ("Finish", "Machines", "out", "m"),
        ("Finish", "Finished", "out", "j")])


# Function to write a timed loop whose clock grows forever.
def timed_loop() -> str:
    """Two tokens circulate between two places, each round taking time.

    The clock grows without bound, so the occurrence graph is infinite --
    but every round looks like the previous one shifted in time, so the
    quotient by time equivalence is finite.

    Returns:
        str: The path written.
    """
    decl = (Declarations()
            .colset("TOKEN", "int", timed=True, bounds=("1", "2"))
            .var("TOKEN", "x"))
    return write_net("timed_loop", decl, [
        ("Ready", "TOKEN", "1`1 ++ 1`2"), ("Away", "TOKEN", None)], [
        ("Go", None, None), ("Return", None, None)], [
        ("Go", "Ready", "in", "x"), ("Go", "Away", "out", "x @+ 3"),
        ("Return", "Away", "in", "x"), ("Return", "Ready", "out", "x @+ x")])


# Function to write a net using more of CPN ML.
def ml_features() -> str:
    """A small order-processing net using several CPN ML features.

    * a guard that *defines* a variable (``total`` is on no input arc);
    * a code segment without side effects that computes an output;
    * priorities: ``Rush`` (``P_HIGH``) goes before ``Normal``;
    * a multiset inside ``if``, and a record-free product colour set.

    Returns:
        str: The path written.
    """
    # CPN Tools puts these "standard priorities" in every new net; they are
    # declarations, not built-ins.
    decl = (Declarations()
            .ml("val P_HIGH = 100;").ml("val P_NORMAL = 1000;")
            .ml("val P_LOW = 10000;")
            .colset("QTY", "int", bounds=("0", "20"))
            .colset("KIND", "enum", "rush", "normal")
            .colset("ORDER", "product", "KIND", "QTY")
            .colset("INT", "int")
            .var("KIND", "k").var("QTY", "q").var("INT", "total", "fee"))
    return write_net("ml_features", decl, [
        ("Orders", "ORDER", "1`(rush, 3) ++ 1`(normal, 5) ++ 1`(normal, 12)"),
        ("Priced", "INT", None), ("Big Orders", "ORDER", None),
        ("Invoices", "INT", None)], [
        ("Rush", "[k = rush, total = q * 2]", {"priority": "P_HIGH"}),
        ("Normal", "[k = normal, total = q]", {"priority": "P_LOW"}),
        ("Invoice", None, {"code": "input (total); output (fee); action (total + 1);"})], [
        ("Rush", "Orders", "in", "(k, q)"), ("Rush", "Priced", "out", "total"),
        ("Rush", "Big Orders", "out", "if q > 10 then 1`(k, q) else empty"),
        ("Normal", "Orders", "in", "(k, q)"), ("Normal", "Priced", "out", "total"),
        ("Normal", "Big Orders", "out", "if q > 10 then 1`(k, q) else empty"),
        ("Invoice", "Priced", "in", "total"), ("Invoice", "Invoices", "out", "fee")])


if __name__ == "__main__":
    for path in [dining(), dining("dining_deadlock", one_at_a_time=True),
                 workers(), pipelines(), timed_jobs(), timed_loop(),
                 ml_features()]:
        print("wrote", os.path.relpath(path))
