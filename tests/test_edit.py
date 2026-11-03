import pytest

from lightness.edit.fences import FenceError, extract_code
from lightness.edit.symbols import (
    SymbolError,
    get_symbol,
    insert_symbol,
    list_symbols,
    outline,
    replace_symbol,
)

SRC = '''"""Module doc."""
import json

RATE = 3  # keep me


def parse(s: str) -> float:
    """Parse a currency string."""
    return float(s)


class Store:
    """Holds things."""

    def __init__(self, path):
        self.path = path

    @property
    def size(self) -> int:
        return 0


# trailing comment
'''


# --- fences -----------------------------------------------------------------

def test_single_block_with_chatter():
    text = "Sure! Here it is:\n```python\nx = 1\n```\nHope that helps."
    assert extract_code(text) == "x = 1\n"


def test_no_language_tag_and_tildes():
    assert extract_code("~~~\nx = 1\n~~~") == "x = 1\n"


def test_prefers_named_block():
    text = "```python a.py\nx = 1\ny = 2\nz = 3\nw = 4\n```\n```python b.py\nq = 1\nr = 2\ns = 3\nt = 4\n```"
    assert extract_code(text, "b.py").startswith("q = 1")


def test_ignores_short_shell_snippet():
    text = "```bash\npython app.py\n```\n```python\nimport os\n\n\ndef main():\n    pass\n```"
    assert extract_code(text).startswith("import os")


def test_ambiguous_blocks_raise():
    big = "a = 1\nb = 2\nc = 3\nd = 4\n"
    with pytest.raises(FenceError):
        extract_code(f"```python\n{big}```\n```python\n{big}```")


def test_unterminated_block_raises():
    with pytest.raises(FenceError, match="cut off"):
        extract_code("```python\nx = 1\n")


def test_bare_code_accepted_only_if_python():
    assert extract_code("x = 1\nprint(x)") == "x = 1\nprint(x)\n"
    with pytest.raises(FenceError):
        extract_code("I could not do that, sorry.")


def test_longer_fence_allows_inner_backticks():
    text = '````python\ns = """\n```\nnot a fence\n```\n"""\n````'
    assert "not a fence" in extract_code(text)


# --- symbols ----------------------------------------------------------------

def test_list_and_get():
    assert list_symbols(SRC) == ["parse", "Store", "Store.__init__", "Store.size"]
    assert get_symbol(SRC, "Store.size").startswith("    @property")


def test_outline_elides_bodies():
    o = outline(SRC)
    assert "def parse(s: str) -> float:" in o and "return float(s)" not in o
    assert "RATE = 3" in o and "import json" in o and "    def size(self) -> int:" in o


def test_replace_top_level_function_keeps_rest():
    new = 'def parse(s: str) -> float:\n    return float(s.replace(",", ""))\n'
    out = replace_symbol(SRC, "parse", new)
    assert 'replace(",", "")' in out
    assert out.replace(get_symbol(out, "parse"), "") == SRC.replace(get_symbol(SRC, "parse"), "")


def test_replace_method_reindents_and_keeps_decorator_replacement():
    new = "@property\ndef size(self) -> int:\n    return 42\n"
    out = replace_symbol(SRC, "Store.size", new)
    assert "    @property\n    def size(self) -> int:\n        return 42\n" in out
    assert "# trailing comment" in out and "RATE = 3  # keep me" in out


def test_replace_accepts_indented_input_and_adds_imports():
    new = "    import re\n\n    def parse(s):\n        return float(re.sub('[^0-9.]', '', s))\n"
    out = replace_symbol(SRC, "parse", new)
    assert "import re\n" in out and out.index("import re") < out.index("def parse")


def test_replace_rejects_wrong_name_and_bad_code():
    with pytest.raises(SymbolError, match="must define 'parse'"):
        replace_symbol(SRC, "parse", "def other():\n    pass\n")
    with pytest.raises(SymbolError, match="does not parse"):
        replace_symbol(SRC, "parse", "def parse(:\n")
    with pytest.raises(SymbolError, match="not found"):
        replace_symbol(SRC, "nope", "def nope():\n    pass\n")


def test_insert_at_end_after_and_in_class():
    out = insert_symbol(SRC, "def total(xs):\n    return sum(xs)\n")
    assert out.rstrip().endswith("return sum(xs)")
    out = insert_symbol(SRC, "def helper():\n    return 1\n", after="parse")
    assert out.index("def helper") < out.index("class Store")
    out = insert_symbol(SRC, "def clear(self):\n    pass\n", in_class="Store")
    assert "Store.clear" in list_symbols(out) and "    def clear(self):\n        pass" in out
    with pytest.raises(SymbolError, match="already exists"):
        insert_symbol(SRC, "def parse():\n    pass\n")


def test_replace_with_new_helper_inserts_it_after_target():
    new = "def parse(s):\n    return _clean(s)\n\n\ndef _clean(s):\n    return float(s.strip())\n"
    out = replace_symbol(SRC, "parse", new)
    assert list_symbols(out)[:2] == ["parse", "_clean"] and "RATE = 3  # keep me" in out


def test_replace_with_existing_helper_replaces_it_in_place():
    src = SRC + "\n\ndef helper():\n    return 1\n"
    new = "def parse(s):\n    return helper() + float(s)\n\n\ndef helper():\n    return 2\n"
    out = replace_symbol(src, "parse", new)
    assert out.count("def helper") == 1 and "return 2" in out and out.index("def helper") > out.index("class Store")


def test_replace_with_constants():
    new = "RATE = 5\nSEP = ','\n\n\ndef parse(s):\n    return float(s.replace(SEP, ''))\n"
    out = replace_symbol(SRC, "parse", new)
    assert "RATE = 5" in out and "RATE = 3" not in out
    assert out.index("SEP = ','") < out.index("def parse")


def test_replace_method_with_sibling_helper():
    new = "@property\ndef size(self) -> int:\n    return self._count()\n\ndef _count(self):\n    return 0\n"
    out = replace_symbol(SRC, "Store.size", new)
    assert "Store._count" in list_symbols(out) and "        return 0" in out


def test_replace_rejects_constants_in_method_edit_and_stray_code():
    with pytest.raises(SymbolError, match="constants"):
        replace_symbol(SRC, "Store.size", "X = 1\n\n\ndef size(self):\n    return X\n")
    with pytest.raises(SymbolError, match="only contain"):
        replace_symbol(SRC, "parse", "def parse(s):\n    return 1\n\n\nprint(parse('x'))\n")
