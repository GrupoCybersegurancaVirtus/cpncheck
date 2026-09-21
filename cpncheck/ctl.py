"""CTL over an occurrence graph.

The occurrence graph is read as a Kripke structure ``K = (S, s0, R, L)``: ``S``
the reachable markings, ``s0`` the initial marking, ``R`` the occurrences of
binding elements, ``L`` whatever atomic propositions the caller supplies as sets
of nodes. The operators are the standard fixpoint characterisations (Clarke,
Grumberg, Kroening, Peled & Veith, *Model Checking*, 2nd ed., 2018; Baier &
Katoen, *Principles of Model Checking*, 2008).

Dead markings
-------------
Textbook CTL assumes a total transition relation, and the nets checked here are
meant to stop. A dead marking is given a self-loop (Baier & Katoen, Sec. 3.1),
which makes a finite maximal path a counterexample to ``AF phi`` when it ends
before ``phi``. CPN Tools' ASK-CTL reads it the other way: its ``FORALL_UNTIL``
(and so ``EV``) is vacuously true at a dead marking, so ``EV(phi)`` means
``AF(phi or dead)``. Both readings are available through the ``semantics``
argument of :func:`_af`.
"""

import collections
from typing import Optional

from .statespace import StateSpace

__all__ = []

# ---------------------------------------------------------------------------
# CTL on an occurrence graph
# ---------------------------------------------------------------------------

# Function to compute the nodes satisfying E[hold U target].
def _eu(ss: StateSpace, hold: set, target: set) -> set:
    """Least fixpoint of ``target or (hold and EX Z)``, by backward search.

    Args:
        ss (StateSpace): The graph.
        hold (set): Nodes satisfying the left operand.
        target (set): Nodes satisfying the right operand.

    Returns:
        set: Nodes satisfying ``E[hold U target]``.
    """
    sat = set(target)
    stack = list(target)
    while stack:
        v = stack.pop()
        for _ti, u in ss.pred[v]:
            if u not in sat and u in hold:
                sat.add(u)
                stack.append(u)
    return sat


# Function to compute the nodes satisfying AF target under a chosen semantics.
def _af(ss: StateSpace, target: set, semantics: str = "textbook") -> set:
    """Least fixpoint of ``target or AX Z``.

    Args:
        ss (StateSpace): The graph.
        target (set): Nodes satisfying the operand.
        semantics (str): ``"textbook"`` -- a dead marking has a self-loop, so a
            dead marking outside ``target`` falsifies ``AF`` -- or ``"askctl"``
            -- ASK-CTL's ``EV``, where a dead marking satisfies it vacuously.

    Returns:
        set: Nodes satisfying the formula.
    """
    n = ss.n_nodes
    sat = [False] * n
    remaining = [0] * n
    queue = collections.deque()
    for v in range(n):
        if v in target:
            sat[v] = True
            queue.append(v)
        elif not ss.succ[v]:
            if semantics == "askctl":
                sat[v] = True
                queue.append(v)
            else:
                remaining[v] = -1
        else:
            remaining[v] = len(ss.succ[v])
    while queue:
        w = queue.popleft()
        for _ti, u in ss.pred[w]:
            if sat[u] or remaining[u] < 0:
                continue
            remaining[u] -= 1
            if remaining[u] == 0:
                sat[u] = True
                queue.append(u)
    return {v for v in range(n) if sat[v]}


# Function to find a path witnessing E[hold U target] from the initial node.
def _eu_path(ss, hold: set, target: set):
    """Shortest occurrence sequence through ``hold`` nodes into ``target``.

    Args:
        ss (StateSpace): The graph.
        hold (set): Nodes the path may pass through.
        target (set): Goal nodes.

    Returns:
        list|None: ``(transition index, binding key, node)`` per step, or None
        when no such path leaves the initial marking.
    """
    back = {0: None}
    queue = collections.deque([0])
    while queue:
        v = queue.popleft()
        if v in target:
            steps = []
            while back[v] is not None:
                src, ti, key = back[v]
                steps.append((ti, key, v))
                v = src
            steps.reverse()
            return steps
        if v not in hold:
            continue
        for ti, key, w in ss.succ[v]:
            if w not in back:
                back[w] = (v, ti, key)
                queue.append(w)
    return None


# Function to find a path witnessing E[hold U target] as readable text.
def _eu_witness(ss, hold: set, target: set) -> Optional[str]:
    """The occurrence sequence of :func:`_eu_path`, as text.

    Args:
        ss (StateSpace): The graph.
        hold (set): Nodes allowed before the target.
        target (set): Goal nodes.

    Returns:
        str|None: The transition sequence, or None if there is no witness.
    """
    steps = _eu_path(ss, hold, target)
    if steps is None:
        return None
    names = [ss.net.transitions[ti]["name"] for ti, _key, _dst in steps]
    if not names:
        return "(initial marking)"
    if len(names) > 12:
        names = names[:3] + [f"... {len(names) - 6} more ..."] + names[-3:]
    return " -> ".join(names)


# Function to find a run that avoids the target forever.
def _af_lasso(ss, target: set):
    """A prefix into a cycle on which the target is never reached.

    ``AF phi`` fails in one of two ways: the run stops before ``phi``, which
    :func:`_eu_path` exhibits as a path to a dead marking outside it, or the
    run goes on forever without reaching it. The second has no finite witness
    unless the repeating part is produced -- which is what this returns.

    Soundness. Let ``S`` be the nodes that do not satisfy ``AF phi``. No node
    of ``S`` satisfies ``phi``; and every node of ``S`` with successors has one
    in ``S``, since otherwise all of them would satisfy ``AF phi`` and so would
    it. A walk from the initial marking inside ``S`` therefore only halts at a
    dead marking, so when no dead marking of ``S`` is reachable -- which is
    exactly the case where :func:`_eu_path` found nothing -- the walk must
    repeat a node, and the repetition is the cycle.

    Args:
        ss (StateSpace): The graph.
        target (set): Nodes satisfying the operand.

    Returns:
        tuple|None: ``(prefix, cycle)``, each a list of
        ``(transition index, binding key, node)``; the prefix ends where the
        cycle begins. None when the initial marking satisfies the formula, or
        when every way of avoiding the target reaches a dead marking instead.
    """
    inside = set(range(ss.n_nodes)) - _af(ss, target, "textbook")
    if 0 not in inside:
        return None
    path: list = []                 # steps from the initial marking
    position = {0: 0}               # node currently on the path -> path length
    explored = {0}                  # nodes whose subtree held no cycle
    stack = [(0, iter(ss.succ[0]))]
    while stack:
        node, successors = stack[-1]
        descended = False
        for ti, key, w in successors:
            if w not in inside:
                continue
            if w in position:                       # back edge: the cycle
                cut = position[w]
                return path[:cut], path[cut:] + [(ti, key, w)]
            if w in explored:                       # no cycle down there
                continue
            explored.add(w)
            path.append((ti, key, w))
            position[w] = len(path)
            stack.append((w, iter(ss.succ[w])))
            descended = True
            break
        if not descended:
            stack.pop()
            if path:
                _ti, _key, left = path.pop()
                del position[left]
    return None
