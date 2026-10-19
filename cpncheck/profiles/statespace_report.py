"""The default profile: CPN Tools' state-space report, for any net.

When no other profile recognises a net, this one does. It asks what CPN Tools'
*Save Report* answers for every net, whatever the net models:

====  =====================  ===============================================
R1    Deadlock freedom       no reachable marking is dead
R2    Termination            every occurrence sequence is finite
R3    Home marking           some marking is reachable from every marking
R4    No dead transitions    every transition instance can occur
R5    All transitions live   from every marking, every transition instance
                             can still occur
====  =====================  ===============================================

These are *facts about the net*, not requirements: a protocol that terminates
by design has dead markings and no live transitions, and is not wrong for it.
So they are reported as YES/NO (property kind ``"report"``) and never make a
check fail. Properties a user wants to *require* are stated as formulas of
their own.

Beside the verdicts the profile produces the rest of the report: the integer
bounds of every place and the dead and live transition instances. Each figure
is also asked of CPN Tools by the oracle, through its own state-space
functions (``UpperInteger``, ``ListDeadTIs``, ``ListLiveTIs``), so that the
comparison does not rest on a translation of ours.
"""

import collections
import re
from typing import Any, Dict, List, Optional

from ..formula import AF, AG, EF, Dead, Enabled, ForEach, Not
from ..profile import Profile, register
from ..properties import Property, catalog
from ..selectors import Explicit

__all__ = ["REPORT_CATALOG", "StateSpaceReportProfile", "ml_name"]

#: The properties of the default profile, in report order.
REPORT_CATALOG = catalog(
    Property("R1", "Deadlock freedom", "AG !dead", "report", (),
             "No reachable marking is dead. A net meant to stop has dead "
             "markings; this states the fact, it does not judge it."),
    Property("R2", "Termination", "AF dead", "report", (),
             "Every occurrence sequence is finite: the occurrence graph has "
             "no reachable cycle."),
    Property("R3", "Home marking", "one terminal SCC", "report", (),
             "Some marking is reachable from every reachable marking.",
             method="scc"),
    Property("R4", "No dead transitions", "forall t: EF EN(t)", "report", (),
             "Every transition instance is enabled in some reachable marking."),
    Property("R5", "All transitions live", "forall t: AG EF EN(t)", "report",
             (), "From every reachable marking, every transition instance can "
             "still become enabled."),
)


# Function to turn a page, place or transition name into its CPN ML form.
def ml_name(name: str) -> str:
    """The identifier CPN Tools uses for a name in ``Mark.`` and ``Bind.``.

    Every character that cannot appear in an ML identifier becomes ``_``, one
    for one, as CPN Tools does.

    Args:
        name (str): The name as drawn.

    Returns:
        str: The ML identifier part.
    """
    return re.sub(r"[^A-Za-z0-9_']", "_", name.strip())


# Class describing every net to the checker by CPN Tools' standard report.
class StateSpaceReportProfile(Profile):
    """The profile used for any net no more specific profile recognises."""

    name = "state-space report"
    priority = -100
    catalog = REPORT_CATALOG

    # Method to accept every net.
    def matches(self, net) -> bool:
        """Every net has a state-space report.

        Args:
            net (ColouredNet): The flattened net.

        Returns:
            bool: Always True.
        """
        return True

    # Method to name the family shown in reports.
    def family(self, net) -> str:
        """``CPN`` -- the net is reported on as such, not as a model family.

        Args:
            net (ColouredNet): The flattened net.

        Returns:
            str: The family name.
        """
        return "CPN"

    # Method to give one quantification member per transition instance.
    def resolve_groups(self, net):
        """Every transition instance, for R4 and R5.

        Args:
            net (ColouredNet): The flattened net.

        Returns:
            dict: ``{"transitions": {label: {"t": (index,)}}}``.
        """
        members = collections.OrderedDict(
            (t["gid"], {"t": (i,)}) for i, t in enumerate(net.transitions))
        return {"transitions": members}

    # Method to build the temporal properties.
    def ctl_formulas(self, net, groups, labels):
        """R1, R2, R4 and R5 as formulas; R3 is the SCC test.

        Args:
            net (ColouredNet): The flattened net.
            groups (dict): The resolved groups.
            labels (list, optional): Unused.

        Returns:
            OrderedDict: ``property id -> Formula``.
        """
        out = collections.OrderedDict()
        # Unphrased: a violation then reads "dead holds after: ...".
        out["R1"] = AG(Not(Dead()))
        out["R2"] = AF(Dead().phrased("termination"))
        if net.transitions:
            out["R4"] = ForEach("transitions", self._can_occur)
            out["R5"] = ForEach("transitions", self._is_live)
        return out

    # Method to build "this transition can occur".
    @staticmethod
    def _can_occur(roles, label):
        """``EF EN(t)``.

        Args:
            roles (dict): ``{"t": (index,)}``.
            label (str): The transition instance.

        Returns:
            Formula: The instance.
        """
        return EF(Enabled(Explicit(roles["t"], "transition", label),
                          note=f"{label} enabled"))

    # Method to build "this transition is live".
    @staticmethod
    def _is_live(roles, label):
        """``AG EF EN(t)``.

        Args:
            roles (dict): ``{"t": (index,)}``.
            label (str): The transition instance.

        Returns:
            Formula: The instance.
        """
        return AG(EF(Enabled(Explicit(roles["t"], "transition", label),
                             note=f"{label} enabled")))

    # Method to name the property answered from the SCC decomposition.
    def scc_properties(self, net, groups):
        """R3.

        Args:
            net (ColouredNet): The flattened net.
            groups (dict): The resolved groups.

        Returns:
            OrderedDict: ``{"R3": "home"}``.
        """
        return collections.OrderedDict((("R3", "home"),))

    # Method to compute the rest of the state-space report.
    def state_space_report(self, net, ss) -> Optional[Dict[str, Any]]:
        """Place bounds, dead and live transition instances.

        A transition instance is *dead* when no reachable marking enables it.
        It is *live* when every terminal strong component contains a marking
        enabling it: every marking reaches some terminal component, and inside
        one every marking reaches every other.

        Args:
            net (ColouredNet): The flattened net.
            ss (StateSpace): The complete occurrence graph.

        Returns:
            dict: ``{"report": {...}, "oracle": {key: value}}``.
        """
        enabled_somewhere = set()
        enabled_in_scc: Dict[int, set] = collections.defaultdict(set)
        for v, out in enumerate(ss.succ):
            for ti, _key, _dst in out:
                enabled_somewhere.add(ti)
                enabled_in_scc[ss.scc[v]].add(ti)
        names = [t["gid"] for t in net.transitions]
        dead = [names[ti] for ti in range(len(names))
                if ti not in enabled_somewhere]
        live = [names[ti] for ti in range(len(names))
                if all(ti in enabled_in_scc[c] for c in ss.terminal_sccs)]
        bounds, ms_bounds = [], []
        sets = net.declarations.colsets
        for i, p in enumerate(net.places):
            sizes = [len(m[i]) for m in ss.markings]
            bounds.append((p["gid"], min(sizes), max(sizes)))
            upper, lower = _multiset_bounds(net, ss, i)
            colset = sets.get(p.get("colset"))
            ms_bounds.append((p["gid"], _ms_text(upper, colset, sets),
                              _ms_text(lower, colset, sets)))
        fairness, infinite = _fairness(ss, len(net.transitions))
        report = {"bounds": bounds, "multiset_bounds": ms_bounds,
                  "dead_transitions": dead, "live_transitions": live,
                  "infinite_runs": infinite,
                  "fairness": [(names[ti], kind) for ti, kind in enumerate(fairness)]}
        oracle = {"dead_tis": str(len(dead)), "live_tis": str(len(live))}
        # As CPN Tools lists them: each list includes the stronger classes.
        order = ("impartial", "fair", "just")
        for level, key in enumerate(order):
            oracle[f"{key}_tis"] = str(sum(1 for k in fairness
                                           if k in order[:level + 1]))
        for i, (_gid, low, high) in enumerate(bounds):
            if self._unambiguous(net, i):
                oracle[f"bound_lo_{i}"] = str(low)
                oracle[f"bound_up_{i}"] = str(high)
                if i not in net.timed_places:
                    oracle[f"ms_up_{i}"] = ms_bounds[i][1]
                    oracle[f"ms_lo_{i}"] = ms_bounds[i][2]
        return {"report": report, "oracle": oracle}

    # Method to tell whether a place can be named in CPN Tools' Mark structure.
    @staticmethod
    def _unambiguous(net, pidx: int) -> bool:
        """Whether ``Mark.Page'Place 1`` denotes exactly this place.

        Only for a place on a page instantiated once: the instance numbering
        of a page used several times is CPN Tools' own and is not compared.

        Args:
            net (ColouredNet): The flattened net.
            pidx (int): Place index.

        Returns:
            bool: True when the place can be asked about by name.
        """
        return net.page_instances.get(net.places[pidx]["page"], 0) == 1

    # Method to give the CPN Tools queries matching the report.
    def oracle_queries(self, net) -> Dict[str, str]:
        """The CPN Tools expressions for the figures of the report.

        Args:
            net (ColouredNet): The flattened net.

        Returns:
            dict: ``{key: string-valued ML expression}``.
        """
        q = collections.OrderedDict()
        q["dead_tis"] = "Int.toString (length (ListDeadTIs ()))"
        q["live_tis"] = "Int.toString (length (ListLiveTIs ()))"
        q["impartial_tis"] = "Int.toString (length (ListImpartialTIs ()))"
        q["fair_tis"] = "Int.toString (length (ListFairTIs ()))"
        q["just_tis"] = "Int.toString (length (ListJustTIs ()))"
        for i, p in enumerate(net.places):
            if not self._unambiguous(net, i):
                continue
            mark = f"Mark.{p.get('ml') or ml_name(p['page']) + chr(39) + ml_name(p['name'])} 1"
            q[f"bound_lo_{i}"] = f"Int.toString (LowerInteger ({mark}))"
            q[f"bound_up_{i}"] = f"Int.toString (UpperInteger ({mark}))"
            if i not in net.timed_places and p.get("colset"):
                cs = p["colset"]
                q[f"ms_up_{i}"] = f"{cs}.mkstr_ms (UpperMultiSet ({mark}))"
                q[f"ms_lo_{i}"] = f"{cs}.mkstr_ms (LowerMultiSet ({mark}))"
        return q


# Function to compute a place's multiset bounds.
def _multiset_bounds(net, ss, pidx: int):
    """The best upper and lower multiset bounds of a place.

    For every colour, the most and the fewest tokens of it the place holds
    in any reachable marking (timestamps aside).

    Args:
        net (ColouredNet): The net.
        ss (StateSpace): The complete occurrence graph.
        pidx (int): The place.

    Returns:
        tuple: ``(upper, lower)``, each ``{value: count}``.
    """
    upper: Dict[Any, int] = {}
    lower: Optional[Dict[Any, int]] = None
    for m in ss.markings:
        counts = collections.Counter(net.values_of(pidx, m[pidx]))
        for value, n in counts.items():
            if n > upper.get(value, 0):
                upper[value] = n
        if lower is None:
            lower = dict(counts)
        else:
            lower = {v: min(n, counts.get(v, 0)) for v, n in lower.items()
                     if counts.get(v, 0)}
    return upper, lower or {}


# Function to write a multiset as CPN Tools does, in canonical term order.
def _ms_text(counts: Dict[Any, int], colset, sets) -> str:
    """``1`a++2`b`` with terms sorted, ``empty`` for none.

    Args:
        counts (dict): ``{value: count}``.
        colset (ColourSet, optional): The place's colour set.
        sets (dict): Every colour set.

    Returns:
        str: The canonical text (compared term by term with CPN Tools').
    """
    from ..colourset import mkstr

    terms = sorted(f"{n}`{mkstr(v, colset, sets)}" for v, n in counts.items() if n)
    return "++".join(terms) if terms else "empty"


# Function to classify the transitions by fairness.
def _fairness(ss, n_transitions: int):
    """Impartial, fair, just or no fairness, per transition (as CPN Tools).

    Without the arcs of ``t``, a non-trivial strongly connected component is
    an infinite run avoiding ``t``. ``t`` is *impartial* when there is none,
    *fair* when none has ``t`` enabled at one of its markings, *just* when
    none has a cycle of markings that all enable ``t``.

    Args:
        ss (StateSpace): The complete occurrence graph.
        n_transitions (int): How many transitions.

    Returns:
        tuple: ``(kinds, infinite)``: one of ``"impartial"``, ``"fair"``,
        ``"just"``, ``"none"`` per transition, and whether the graph has an
        infinite occurrence sequence at all.
    """
    nodes = range(ss.n_nodes)
    enabled = [set(ti for ti, _k, _d in out) for out in ss.succ]
    all_arcs = [[(ti, d) for ti, _k, d in out] for out in ss.succ]
    infinite = bool(_cyclic_components(nodes, lambda v: [d for _t, d in all_arcs[v]]))
    kinds = []
    for t in range(n_transitions):
        def without_t(v, t=t):
            return [d for ti, d in all_arcs[v] if ti != t]
        comps = _cyclic_components(nodes, without_t)
        if not comps:
            kinds.append("impartial")
            continue
        if not any(t in enabled[v] for comp in comps for v in comp):
            kinds.append("fair")
            continue
        just = True
        for comp in comps:
            inside = [v for v in comp if t in enabled[v]]
            keep = set(inside)
            if _cyclic_components(inside, lambda v, keep=keep: [
                    d for d in without_t(v) if d in keep]):
                just = False
                break
        kinds.append("just" if just else "none")
    return kinds, infinite


# Function to find the strongly connected components that contain a cycle.
def _cyclic_components(nodes, successors) -> List[List[int]]:
    """Tarjan's algorithm, keeping components with a cycle.

    A component has a cycle when it has more than one node, or one node
    with an arc to itself (CPN Tools' non-trivial components).

    Args:
        nodes (iterable): The nodes to consider.
        successors (callable): ``node -> list of nodes``.

    Returns:
        list: The non-trivial components, as node lists.
    """
    index: Dict[int, int] = {}
    low: Dict[int, int] = {}
    on_stack = set()
    stack: List[int] = []
    out: List[List[int]] = []
    counter = 0
    for root in nodes:
        if root in index:
            continue
        work = [(root, iter(successors(root)))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(successors(w))))
                    advanced = True
                    break
                if w in on_stack:
                    low[v] = min(low[v], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1 or v in successors(v):
                    out.append(comp)
    return out


register(StateSpaceReportProfile())
