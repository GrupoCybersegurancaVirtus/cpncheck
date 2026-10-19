"""Draw the README's figures from real CPNCheck runs.

Every number and every graph in the figures is computed here by CPNCheck on
the nets in ``examples/nets``; nothing is typed in by hand. Re-run after a
change that could move them:

    python docs/figures/make_figures.py

Needs matplotlib (only for this script; CPNCheck itself has no
dependencies).
"""

import os
import subprocess
import sys
import tempfile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
NETS = os.path.join(ROOT, "examples", "nets")
sys.path.insert(0, ROOT)

from cpncheck import CPNModelChecker, check_cpn  # noqa: E402

# Colours: the reference palette's first three categorical slots (validated
# for colour-vision deficiencies), a neutral for context, and text inks.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
BLUE_LIGHT = "#86b6ef"
NEUTRAL = "#b5b3ad"
SURFACE = "#fcfcfb"
INK, INK_2, INK_3 = "#0b0b0b", "#52514e", "#8a8984"
DPI = 200

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "text.color": INK,
    "axes.edgecolor": INK_3, "axes.labelcolor": INK_2,
    "xtick.color": INK_2, "ytick.color": INK_2,
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
})


# Function to save a figure into this directory.
def save(fig, name: str) -> None:
    """Write ``name`` as a PNG and close the figure.

    Args:
        fig (Figure): The figure.
        name (str): File name.
    """
    path = os.path.join(HERE, name)
    fig.savefig(path, dpi=DPI, bbox_inches="tight", pad_inches=0.15,
                facecolor=fig.get_facecolor())
    plt.close(fig)
    print("wrote", os.path.relpath(path, ROOT))


# Function to draw a rounded box with a title and a line of detail.
def box(ax, x, y, w, h, title, detail="", edge=BLUE, fill="white",
        dashed=False):
    """A labelled box centred at ``(x, y)``.

    Args:
        ax (Axes): Where to draw.
        x, y (float): Centre.
        w, h (float): Size.
        title (str): Bold first line.
        detail (str): Smaller lines below.
        edge (str): Border colour.
        fill (str): Fill colour.
        dashed (bool): Dashed border (optional parts).
    """
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                                boxstyle="round,pad=0.02,rounding_size=0.08",
                                linewidth=1.6, edgecolor=edge, facecolor=fill,
                                linestyle="--" if dashed else "-"))
    top = y + h / 2 - 0.2
    ax.text(x, top if detail else y, title, ha="center", va="center",
            fontsize=10.5, fontweight="bold", color=INK)
    if detail:
        ax.text(x, top - 0.17, detail, ha="center", va="top", fontsize=8.3,
                color=INK_2, linespacing=1.3)


# Function to draw an arrow between two points.
def arrow(ax, a, b, color=INK_3, label="", dashed=False, rad=0.0, lw=1.4,
          label_offset=(0, 0.09), fontsize=8.3):
    """An arrow from ``a`` to ``b``, optionally labelled at its middle.

    Args:
        ax (Axes): Where to draw.
        a, b (tuple): End points.
        color (str): Colour.
        label (str): Text at the middle.
        dashed (bool): Dashed line.
        rad (float): Curvature.
        lw (float): Width.
        label_offset (tuple): Offset of the label.
        fontsize (float): Label size.
    """
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=11,
                                 color=color, linewidth=lw,
                                 linestyle="--" if dashed else "-",
                                 connectionstyle=f"arc3,rad={rad}",
                                 shrinkA=2, shrinkB=2))
    if label:
        ax.text((a[0] + b[0]) / 2 + label_offset[0],
                (a[1] + b[1]) / 2 + label_offset[1], label, ha="center",
                va="center", fontsize=fontsize, color=INK_2,
                bbox=dict(facecolor=SURFACE, edgecolor="none", pad=1.2))


# ---------------------------------------------------------------------------
# 1. How CPNCheck works
# ---------------------------------------------------------------------------

# Function to draw the overview of the pipeline.
def pipeline() -> None:
    """From the ``.cpn`` file to verdicts, with the optional oracle."""
    fig, ax = plt.subplots(figsize=(12.5, 3.9))
    ax.set_xlim(0, 12.5)
    ax.set_ylim(0, 3.9)
    ax.axis("off")
    y = 2.6
    steps = [
        (1.15, "model.cpn", "the file CPN Tools\nopens, unchanged"),
        (3.7, "Read", "pages, colour sets,\nCPN ML, hierarchy"),
        (6.25, "Explore", "the occurrence graph:\nevery reachable\nmarking"),
        (8.8, "Check", "state-space report,\nyour CTL, ASK-CTL"),
        (11.35, "Verdicts", "PASS / FAIL, and a\ncounterexample\nthat replays"),
    ]
    for x, title, detail in steps:
        box(ax, x, y, 2.15, 1.2, title, detail)
    for (x1, *_), (x2, *_) in zip(steps, steps[1:]):
        arrow(ax, (x1 + 1.1, y), (x2 - 1.1, y), color=BLUE, lw=1.8)
    box(ax, 6.25, 0.7, 3.4, 0.95, "Reductions (optional)",
        "stubborn sets, sweep-line, equivalence,\nsymmetry, or several combined",
        edge=INK_3, dashed=True)
    arrow(ax, (6.25, 1.2), (6.25, y - 0.62), color=INK_3, dashed=True)
    box(ax, 10.4, 0.7, 3.9, 0.95, "CPN Tools 4.0.1, headless",
        "optional: the same questions, answered\nby CPN Tools -- do the numbers agree?",
        edge=ORANGE, dashed=True)
    arrow(ax, (10.0, 1.2), (9.2, y - 0.62), color=ORANGE, dashed=True)
    ax.text(0.05, 3.85, "How CPNCheck works", fontsize=13, fontweight="bold",
            va="top")
    save(fig, "pipeline.png")


# ---------------------------------------------------------------------------
# 2. A net, as CPN Tools draws it
# ---------------------------------------------------------------------------

# Function to draw the dining-philosophers net of the tour.
def net() -> None:
    """``dining_deadlock.cpn``: places, transitions, arcs and inscriptions."""
    mc = CPNModelChecker(os.path.join(NETS, "dining_deadlock.cpn"))
    names = {p["name"] for p in mc.cnet.places}
    assert names == {"Think", "Has Left", "Eat", "Unused Chopsticks"}, names
    fig, ax = plt.subplots(figsize=(9, 5.7))
    ax.set_xlim(0, 9)
    ax.set_ylim(-0.3, 5.4)
    ax.set_aspect("equal")
    ax.axis("off")
    places = {"Think": (1.2, 3.6), "Has Left": (4.5, 4.4), "Eat": (7.8, 3.6),
              "Unused Chopsticks": (4.5, 1.9)}
    trans = {"Take Left": (2.85, 4.2), "Take Right": (6.15, 4.2),
             "Put Down": (4.5, 0.55)}
    marks = {"Think": "ph(1)\n...\nph(5)", "Unused Chopsticks": "cs(1)\n...\ncs(5)"}
    r = 0.42
    for name, (x, y) in places.items():
        ax.add_patch(Circle((x, y), r, facecolor="white", edgecolor=BLUE,
                            linewidth=1.8))
        if name == "Unused Chopsticks":
            ax.text(x - r - 0.18, y, "Unused\nChopsticks", ha="right",
                    va="center", fontsize=9.5, fontweight="bold")
        else:
            ax.text(x, y - r - 0.2, name, ha="center", va="top", fontsize=9.5,
                    fontweight="bold")
        if name in marks:
            ax.text(x, y, marks[name], ha="center", va="center", fontsize=7,
                    color=INK_2, linespacing=1.0)
        ax.text(x + r * 1.05, y - r * 0.75, "PH" if name != "Unused Chopsticks"
                else "CS", fontsize=7.5, color=INK_3, ha="left")
    for name, (x, y) in trans.items():
        ax.add_patch(FancyBboxPatch((x - 0.5, y - 0.17), 1.0, 0.34,
                                    boxstyle="square,pad=0", facecolor="white",
                                    edgecolor=INK, linewidth=1.6))
        ax.text(x, y, name, ha="center", va="center", fontsize=8.3,
                fontweight="bold")
    # Arcs, with their inscriptions (as in the file).
    arrow(ax, (1.62, 3.75), (2.43, 4.12), label="p", label_offset=(0, 0.12))
    arrow(ax, (3.27, 4.24), (4.08, 4.38), label="p", label_offset=(0, 0.12))
    arrow(ax, (4.92, 4.38), (5.73, 4.24), label="p", label_offset=(0, 0.12))
    arrow(ax, (6.57, 4.12), (7.38, 3.75), label="p", label_offset=(0, 0.12))
    arrow(ax, (7.7, 3.18), (4.92, 0.6), label="p", rad=-0.25,
          label_offset=(0.75, -0.2))
    arrow(ax, (4.08, 0.6), (1.3, 3.18), label="p", rad=-0.25,
          label_offset=(-0.75, -0.2))
    arrow(ax, (4.2, 2.2), (2.95, 4.02), label="Left(p)", rad=0.1,
          label_offset=(-0.35, 0.0))
    arrow(ax, (4.8, 2.2), (6.05, 4.02), label="Right(p)", rad=-0.1,
          label_offset=(0.4, 0.0))
    arrow(ax, (4.5, 0.73), (4.5, 1.48), label="Chopsticks(p)",
          label_offset=(0.75, -0.05))
    ax.text(0.0, 5.4, "The net: philosophers who take the left chopstick "
            "first", fontsize=12.5, fontweight="bold", va="top")
    ax.text(0.0, 5.05, "examples/nets/dining_deadlock.cpn  ·  circles are "
            "places (they hold tokens), boxes are transitions", fontsize=8.5,
            color=INK_2, va="top")
    ax.text(0.0, -0.25, "Initially every philosopher thinks and every "
            "chopstick is unused; PH and CS are the colour sets.",
            fontsize=8.5, color=INK_2, va="bottom")
    save(fig, "net.png")


# ---------------------------------------------------------------------------
# 3. The occurrence graph and a counterexample
# ---------------------------------------------------------------------------

# Function to write the three-philosopher variant of the tour's net.
def three_philosophers() -> str:
    """``dining_deadlock.cpn`` with ``N = 3``, small enough to draw.

    Returns:
        str: The path of the variant.
    """
    with open(os.path.join(NETS, "dining_deadlock.cpn"), encoding="utf-8") as fh:
        text = fh.read()
    assert "val N = 5;" in text
    path = os.path.join(tempfile.mkdtemp(), "dining_deadlock_3.cpn")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text.replace("val N = 5;", "val N = 3;"))
    return path


# Function to draw an occurrence graph with the counterexample highlighted.
def occurrence_graph() -> None:
    """Every reachable marking of three philosophers; the path to deadlock."""
    mc = CPNModelChecker(three_philosophers(), properties="NODL: AG !dead")
    ss = mc.state_space()
    result = mc.check()
    assert result.properties["NODL"].holds is False
    names = [t["name"] for t in mc.cnet.transitions]
    depth = [0] * ss.n_nodes
    order = sorted(range(ss.n_nodes), key=lambda v: len(ss.path(v)))
    for v in order:
        depth[v] = len(ss.path(v))
    layers = {}
    for v in range(ss.n_nodes):
        layers.setdefault(depth[v], []).append(v)
    pos = {}
    for d, nodes in layers.items():
        nodes.sort()
        for i, v in enumerate(nodes):
            pos[v] = (d * 1.55, (i - (len(nodes) - 1) / 2) * 0.95)
    dead = ss.dead[0]
    path = ss.path(dead)
    on_path = {(0 if i == 0 else path[i - 1][2], path[i][2])
               for i in range(len(path))}
    fig, ax = plt.subplots(figsize=(11, 5.4))
    ax.axis("off")
    for src, out in enumerate(ss.succ):
        for ti, _k, dst in out:
            if (src, dst) in on_path:
                continue
            arrow(ax, pos[src], pos[dst], color="#d6d4cf", lw=0.8,
                  rad=0.08 if depth[dst] <= depth[src] else 0.0)
    for i, (ti, key, dst) in enumerate(path):
        src = 0 if i == 0 else path[i - 1][2]
        who = dict(key).get("p")
        arrow(ax, pos[src], pos[dst], color=BLUE, lw=2.4,
              label=f"{names[ti]}\n{who}", label_offset=(0, 0.33),
              fontsize=7.6)
    for v, (x, y) in pos.items():
        if v == 0:
            face, edge = BLUE, BLUE
        elif v in ss.dead:
            face, edge = ORANGE, ORANGE
        else:
            face, edge = "white", INK_3
        ax.add_patch(Circle((x, y), 0.17, facecolor=face, edgecolor=edge,
                            linewidth=1.4, zorder=3))
    x0, y0 = pos[0]
    ax.text(x0, y0 - 0.34, "initial\nmarking", ha="center", va="top",
            fontsize=8.5, color=INK)
    xd, yd = pos[dead]
    ax.text(xd + 0.28, yd, "dead marking:\nevery philosopher\nholds one "
            "chopstick", ha="left", va="center", fontsize=8.5, color=INK)
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    ax.set_xlim(min(xs) - 0.6, max(xs) + 2.2)
    ax.set_ylim(min(ys) - 0.9, max(ys) + 1.1)
    ax.set_aspect("equal")
    ax.text(min(xs) - 0.6, max(ys) + 1.05,
            f"The occurrence graph: {ss.n_nodes} markings, {ss.n_arcs} arcs "
            "(three philosophers)", fontsize=12.5, fontweight="bold", va="top")
    ax.text(min(xs) - 0.6, max(ys) + 0.62,
            "Each circle is a reachable marking, each arrow one occurrence of "
            "a transition. In blue: the counterexample to AG !dead that "
            "CPNCheck reports.", fontsize=8.5, color=INK_2, va="top")
    save(fig, "occurrence_graph.png")


# ---------------------------------------------------------------------------
# 4. What the command prints
# ---------------------------------------------------------------------------

# Function to render the command's real output as a terminal.
def terminal() -> None:
    """``cpncheck check`` on the tour's net, as printed."""
    cmd = [sys.executable, "-m", "cpncheck.cli", "check",
           os.path.join("examples", "nets", "dining_deadlock.cpn"),
           "--prop", "NODL: AG !dead",
           "--prop", "PAIR: EF tokens(Eat) = 2"]
    out = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT,
                         env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    lines = out.stdout.rstrip().splitlines()
    shown = ["$ cpncheck check examples/nets/dining_deadlock.cpn \\",
             "      --prop 'NODL: AG !dead' --prop 'PAIR: EF tokens(Eat) = 2'",
             ""]
    keep = [ln for ln in lines if ln.strip()]
    shown += [ln[:104] for ln in keep[:34]]
    if len(keep) > 34:
        shown.append("  ...")
    height = 0.205 * len(shown) + 0.5
    fig = plt.figure(figsize=(11, height))
    fig.patch.set_facecolor("#1a1a19")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    ax.set_facecolor("#1a1a19")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, len(shown) + 1)
    for i, ln in enumerate(shown):
        y = len(shown) - i
        color = "#f0efec"
        if i < 2:
            color = "#c3c2b7"
        ax.text(0.015, y, ln, family="DejaVu Sans Mono", fontsize=8.4,
                color=color, va="center", ha="left")
        for word, c in (("FAIL", "#ff8a5b"), ("PASS", "#3fd39b")):
            if f" {word}" in ln and i >= 2:
                col = ln.rindex(word)
                ax.text(0.015, y, " " * col + word, family="DejaVu Sans Mono",
                        fontsize=8.4, color=c, va="center", ha="left",
                        fontweight="bold")
    save(fig, "terminal.png")


# ---------------------------------------------------------------------------
# 5. Dead markings: CTL and ASK-CTL
# ---------------------------------------------------------------------------

# Function to draw the two readings of "eventually" at a dead marking.
def dead_markings() -> None:
    """``AF phi`` (CPNCheck) against ``EV phi`` (ASK-CTL) on one graph."""
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.2))
    for ax, title, verdict, color, note in (
            (axes[0], "CPNCheck:  AF φ", "FALSE", ORANGE,
             "A dead marking keeps itself as its only successor,\nso the run "
             "M0 → M2 → M2 → ... never reaches φ."),
            (axes[1], "CPN Tools ASK-CTL:  EV(φ)", "TRUE", AQUA,
             "At M2 \"every successor satisfies EV(φ)\" holds\n"
             "vacuously: a dead marking has no successors.")):
        ax.set_xlim(0, 5.4)
        ax.set_ylim(0, 3.1)
        ax.set_aspect("equal")
        ax.axis("off")
        nodes = {"M0": (0.8, 1.5), "M1": (3.0, 2.3), "M2": (3.0, 0.7)}
        for name, (x, y) in nodes.items():
            face = "white"
            ax.add_patch(Circle((x, y), 0.3, facecolor=face,
                                edgecolor=INK_3 if name != "M2" else ORANGE,
                                linewidth=1.6))
            ax.text(x, y, name, ha="center", va="center", fontsize=9,
                    fontweight="bold")
        ax.text(3.4, 2.3, "φ holds", va="center", fontsize=8.5, color=INK)
        ax.text(3.4, 0.7, "dead, φ false", va="center", fontsize=8.5,
                color=INK)
        arrow(ax, (1.1, 1.62), (2.7, 2.2), color=INK_3)
        arrow(ax, (1.1, 1.38), (2.7, 0.8), color=INK_3)
        if verdict == "FALSE":
            # The self-loop CPNCheck gives a dead marking, drawn below it.
            ax.add_patch(FancyArrowPatch((3.2, 0.48), (2.8, 0.48),
                                         connectionstyle="arc3,rad=-1.8",
                                         arrowstyle="-|>", mutation_scale=9,
                                         color=ORANGE, linewidth=1.3))
        ax.text(0.0, 3.05, title, fontsize=11.5, fontweight="bold", va="top")
        ax.text(5.35, 3.05, verdict, fontsize=11.5, fontweight="bold",
                color=color, va="top", ha="right")
        ax.text(0.0, -0.05, note, fontsize=8.3, color=INK_2, va="top")
    save(fig, "dead_markings.png")


# ---------------------------------------------------------------------------
# 6. State explosion and the reductions
# ---------------------------------------------------------------------------

# Function to measure how many markings each reduction keeps.
def measure_reductions():
    """Markings kept in memory to decide ``AG !dead``, per reduction.

    For a graph, its markings; for a sweep, the most stored at once.

    Returns:
        list: ``(net title, [(label, value, kind)])``.
    """
    prop = "AG !dead"

    def kept(net_name, reduction=None, **kw):
        r = check_cpn(os.path.join(NETS, f"{net_name}.cpn"), properties=prop,
                      reduction=reduction, **kw)
        s = r.stats
        if isinstance(s.get("sweeps"), list):
            return max(x["peak_stored"] for x in s["sweeps"])
        if "peak_stored" in s:
            return s["peak_stored"]
        if s.get("graphs") and isinstance(s["graphs"], dict):
            return s["graphs"].get("deadlock") or s["nodes"]
        return s.get("classes") or s["nodes"]

    workers = [
        ("full graph", kept("workers"), "full"),
        ("sweep-line", kept("workers", "sweep", progress="tokens(Done)"),
         "single"),
        ("stubborn sets", kept("workers", "stubborn"), "single"),
        ("symmetry", kept("workers", "symmetry", symmetry="WORKER=all"),
         "single"),
        ("stubborn + symmetry", kept("workers", "stubborn+symmetry",
                                     symmetry="WORKER=all"), "combined"),
        ("sweep + stubborn\n+ symmetry",
         kept("workers", "sweep+stubborn+symmetry", symmetry="WORKER=all",
              progress="tokens(Done)"), "combined"),
    ]
    # Progress: how many pipelines are done, all eight counted.
    prog = " + ".join(f'tokens("Done {k}")' for k in range(1, 9))
    pipes = [
        ("full graph", kept("pipelines"), "full"),
        ("sweep-line", kept("pipelines", "sweep", progress=prog), "single"),
        ("stubborn sets", kept("pipelines", "stubborn"), "single"),
        ("sweep + stubborn", kept("pipelines", "sweep+stubborn",
                                  progress=prog), "combined"),
    ]
    return [("6 identical workers", workers),
            ("8 independent pipelines", pipes)]


# Function to draw the reductions chart.
def reductions() -> None:
    """Bars per net: markings kept, full graph against each reduction."""
    data = measure_reductions()
    colors = {"full": NEUTRAL, "single": BLUE_LIGHT, "combined": BLUE}
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.9),
                             gridspec_kw={"wspace": 0.55})
    for ax, (title, rows) in zip(axes, data):
        labels = [r[0] for r in rows][::-1]
        values = [r[1] for r in rows][::-1]
        kinds = [r[2] for r in rows][::-1]
        ys = range(len(rows))
        ax.barh(list(ys), values, color=[colors[k] for k in kinds],
                height=0.62, edgecolor=SURFACE, linewidth=2)
        top = max(values)
        for y, v in zip(ys, values):
            ax.text(v + top * 0.015, y, f"{v:,}".replace(",", " "),
                    va="center", fontsize=8.6, color=INK)
        ax.set_yticks(list(ys))
        ax.set_yticklabels(labels, fontsize=8.6)
        ax.set_xlim(0, top * 1.18)
        ax.set_title(title, loc="left", fontsize=10.5, fontweight="bold",
                     color=INK)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.tick_params(axis="y", length=0)
        ax.xaxis.grid(True, color="#e8e6e1", linewidth=0.8)
        ax.set_axisbelow(True)
        ax.set_xlabel("markings kept in memory", fontsize=8.6)
    handles = [plt.Rectangle((0, 0), 1, 1, color=colors[k])
               for k in ("full", "single", "combined")]
    fig.legend(handles, ["no reduction", "one reduction", "combined"],
               loc="upper right", bbox_to_anchor=(0.98, 1.06), ncol=3,
               frameon=False, fontsize=8.6)
    fig.suptitle("Deciding AG !dead: how many markings each reduction keeps",
                 x=0.01, y=1.06, ha="left", fontsize=12.5, fontweight="bold")
    save(fig, "reductions.png")
    return data


# Function to draw every figure.
def main() -> None:
    """Draw them all."""
    pipeline()
    net()
    occurrence_graph()
    terminal()
    dead_markings()
    data = reductions()
    for title, rows in data:
        print(title, [(r[0].replace("\n", " "), r[1]) for r in rows])


if __name__ == "__main__":
    main()
