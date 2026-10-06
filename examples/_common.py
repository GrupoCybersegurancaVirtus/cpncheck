"""Helpers shared by the example scripts: where the nets are, and headings."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NETS = os.path.join(HERE, "nets")
PROPERTIES = os.path.join(HERE, "properties")
ROOT = os.path.dirname(HERE)

# Let the examples run from a checkout without installing the package.
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# Function to give the path of an example net.
def net(name: str) -> str:
    """Path of ``examples/nets/<name>.cpn``.

    Args:
        name (str): The net's file stem.

    Returns:
        str: The path.
    """
    return os.path.join(NETS, f"{name}.cpn")


# Function to print a section heading.
def section(title: str) -> None:
    """Print a heading, so the output reads as a walkthrough.

    Args:
        title (str): The heading.
    """
    print()
    print(title)
    print("-" * len(title))
