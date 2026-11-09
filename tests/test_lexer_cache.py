"""The single-pattern lexer, the token and tree caches, and the paused collector."""

import gc
import glob
import os
import random
import xml.etree.ElementTree as ET

import pytest

from cpncheck import cpnml
from cpncheck.net import paused_gc

HERE = os.path.dirname(os.path.abspath(__file__))


def _run(fn, text):
    try:
        return ("ok", fn(text))
    except Exception as exc:  # noqa: BLE001
        return ("err", type(exc).__name__, str(exc))


def _net_texts():
    texts = set()
    for path in glob.glob(os.path.join(HERE, "**", "*.cpn"), recursive=True):
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        texts.update(el.text for el in root.iter() if el.text and el.text.strip())
    return sorted(texts)


@pytest.mark.parametrize("text", _net_texts())
def test_lexer_matches_reference_on_net_texts(text):
    cpnml._TOKEN_CACHE.clear()
    expected = _run(cpnml._tokenize_slow, text)
    assert _run(cpnml.tokenize, text) == expected
    assert _run(cpnml.tokenize, text) == expected    # served from the cache


def test_lexer_matches_reference_on_random_sources():
    rng = random.Random(1)
    alphabet = list(" \t\n()[]{}#\"\\~.,;:=<>+-*/^@`_!|eE0123456789abcXYZ'") + [
        "(*", "*)", "andalso", "if", "then", "1.5e~3", "~12", '#"a"', '"s\\n"',
        "List.nth", "<=", "::", "++", "@+", "<<=", "..."]
    for _ in range(20000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 25)))
        cpnml._TOKEN_CACHE.clear()
        assert _run(cpnml.tokenize, text) == _run(cpnml._tokenize_slow, text), text


def test_cached_tokens_are_private_copies():
    cpnml._TOKEN_CACHE.clear()
    first = cpnml.tokenize("x <= 3")
    first.append(("id", "junk", 99))
    assert cpnml.tokenize("x <= 3") == cpnml._tokenize_slow("x <= 3")


def test_tree_cache_keys_on_symbols():
    cpnml._TREE_CACHE.clear()
    plain = cpnml.parse_expression("red")
    assert cpnml.parse_expression("red") is plain                 # cached
    sym = {"red": cpnml.EnumValue("red")}
    other = cpnml.parse_expression("red", sym)
    assert cpnml.parse_expression("red", dict(sym)) is other      # same content
    with pytest.raises(cpnml.MLError):
        cpnml.parse_expression("x +")                             # errors are not cached
    with pytest.raises(cpnml.MLError):
        cpnml.parse_expression("x +")


def test_paused_gc_restores_the_previous_state():
    assert gc.isenabled()
    with paused_gc():
        assert not gc.isenabled()
        with paused_gc():
            assert not gc.isenabled()
        assert not gc.isenabled()
    assert gc.isenabled()
    gc.disable()
    try:
        with paused_gc():
            pass
        assert not gc.isenabled()
    finally:
        gc.enable()
