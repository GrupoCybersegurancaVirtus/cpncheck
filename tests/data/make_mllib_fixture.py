"""Record what CPN Tools answers for every case in mllib_cases.txt.

The CPN ML library of CPNCheck is checked against CPN Tools itself: this
script writes ``tests/nets/mllib.cpn`` (declarations only, and one transition
that never fires), has CPN Tools 4.0.1 evaluate each case in that net's
environment, and stores the answers -- value and type as the SML REPL prints
them -- in ``mllib_expected.json``. ``tests/test_mllib.py`` then compares
CPNCheck's results with them, without needing CPN Tools.

    python tests/data/make_mllib_fixture.py        # needs CPN Tools 4.0.1
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
NET = os.path.join(ROOT, "tests", "nets", "mllib.cpn")
CASES = os.path.join(HERE, "mllib_cases.txt")
EXPECTED = os.path.join(HERE, "mllib_expected.json")

#: Declarations, as CPN Tools writes them. Ids avoid the letters P and F,
#: which CPN Tools' state-space generator would split names on.
GLOBBOX = """<globbox>
  <color id="ID101"><id>INT</id><int/></color>
  <color id="ID102"><id>BOOL</id><bool/></color>
  <color id="ID103"><id>STRING</id><string/></color>
  <color id="ID104"><id>E</id><enum><id>a</id><id>b</id><id>c</id></enum></color>
  <ml id="ID105">val N = 4;</ml>
  <color id="ID106"><id>U</id><index><ml>1</ml><ml>N</ml><id>u</id></index></color>
  <color id="ID107"><id>PR</id><product><id>U</id><id>E</id></product></color>
  <color id="ID108"><id>SMALL</id><int><with><ml>1</ml><ml>5</ml></with></int></color>
  <color id="ID109"><id>NAME</id><string/></color>
  <color id="ID110"><id>IL</id><list><id>INT</id></list></color>
  <color id="ID111"><id>R</id><record><recordfield><id>x</id><id>INT</id></recordfield><recordfield><id>y</id><id>E</id></recordfield></record></color>
  <var id="ID112"><type><id>INT</id></type><id>n</id></var>
</globbox>"""

PAGE = """<page id="ID1">
  <pageattr name="Top"/>
  <place id="ID1001"><text>Q</text><type><text>INT</text></type><initmark><text>1`0</text></initmark></place>
  <trans id="ID2001"><text>T</text><cond><text>[n &lt; 0]</text></cond></trans>
  <arc id="ID3001" orientation="PtoT"><transend idref="ID2001"/><placeend idref="ID1001"/><annot><text>n</text></annot></arc>
  <arc id="ID3002" orientation="TtoP"><transend idref="ID2001"/><placeend idref="ID1001"/><annot><text>n</text></annot></arc>
</page>"""

#: Printing limits high enough that no answer is cut short.
SETUP = ("val _ = Control.Print.printDepth := 100; "
         "val _ = Control.Print.printLength := 1000; "
         "val _ = Control.Print.stringDepth := 1000;")


# Function to read the cases.
def read_cases(path: str = CASES):
    """The case lines, with their comparison mode.

    Args:
        path (str): The case file.

    Returns:
        list: ``(mode, expression)``; mode is ``"exact"`` or ``"bag"``.
    """
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            mode = "exact"
            if line.startswith("bag:"):
                mode, line = "bag", line[4:].strip()
            out.append((mode, line))
    return out


# Function to write the declarations net.
def write_net(path: str = NET) -> str:
    """Write ``tests/nets/mllib.cpn``.

    Args:
        path (str): Where.

    Returns:
        str: The path.
    """
    text = ('<?xml version="1.0" encoding="iso-8859-1"?>\n'
            "<workspaceElements><cpnet>" + GLOBBOX + PAGE +
            '<instances><instance id="ID2" page="ID1"/></instances>'
            "</cpnet></workspaceElements>\n")
    with open(path, "w", encoding="iso-8859-1") as fh:
        fh.write(text)
    return path


# Function to ask CPN Tools for every case.
def main() -> int:
    """Write the net, evaluate the cases in CPN Tools, store the answers.

    Returns:
        int: Process exit status.
    """
    sys.path.insert(0, ROOT)
    from cpncheck.oracle import CPNToolsOracle

    write_net()
    cases = read_cases()
    oracle = CPNToolsOracle()
    missing = oracle.missing()
    if missing:
        print("CPN Tools is not available:", ", ".join(missing))
        return 1
    answer = oracle.run(NET, SETUP, {}, raw={str(i): e for i, (_m, e)
                                             in enumerate(cases)},
                        timeout=1200, state_space=False)
    if answer["errors"]:
        print("errors:", answer["errors"])
        return 1
    records = []
    for i, (mode, expr) in enumerate(cases):
        records.append({"expr": expr, "mode": mode,
                        "cpntools": answer["raw"].get(str(i), "").strip()})
    with open(EXPECTED, "w", encoding="utf-8") as fh:
        json.dump({"banner": answer.get("banner"), "cases": records}, fh,
                  indent=1)
    bad = [r for r in records if "Error" in r["cpntools"]]
    print(f"{len(records)} cases recorded in {os.path.relpath(EXPECTED, ROOT)}; "
          f"{len(bad)} do not compile in CPN Tools")
    for r in bad:
        print("  ", r["expr"], "->", r["cpntools"][:160].replace("\n", " "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
