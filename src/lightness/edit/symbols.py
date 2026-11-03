"""Symbol-level views and edits of Python source (functions, classes, methods).

Uses `ast` line ranges and re-indentation, so everything outside the edited symbol stays
byte-for-byte unchanged.
"""

import ast
import textwrap


class SymbolError(ValueError):
    pass


def _defs(tree: ast.Module):
    """Yield (qualified name, node) for top-level defs/classes and methods."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield node.name, node
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        yield f"{node.name}.{sub.name}", sub


def list_symbols(source: str) -> list[str]:
    return [name for name, _ in _defs(ast.parse(source))]


def _span(node: ast.AST) -> tuple[int, int]:
    """0-based [start, end) line span including decorators."""
    start = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))]) - 1
    return start, node.end_lineno


def _find(source: str, name: str):
    tree = ast.parse(source)
    for qual, node in _defs(tree):
        if qual == name:
            return tree, node
    raise SymbolError(f"symbol {name!r} not found; available: {', '.join(list_symbols(source)) or 'none'}")


def get_symbol(source: str, name: str) -> str:
    _, node = _find(source, name)
    start, end = _span(node)
    return "\n".join(source.splitlines()[start:end]) + "\n"


def outline(source: str) -> str:
    """Imports, module-level names, and signatures with first docstring line; bodies elided."""
    tree, lines, out = ast.parse(source), source.splitlines(), []

    def sig(node, indent=""):
        start, _ = _span(node)
        header_end = node.body[0].lineno - 1
        header = [line.rstrip() for line in lines[start:header_end]]
        doc = ast.get_docstring(node)
        out.extend(indent + h.strip() if i else indent + h.lstrip() for i, h in enumerate(header))
        if doc:
            out.append(f'{indent}    """{doc.splitlines()[0]}"""')
        if not isinstance(node, ast.ClassDef):
            out.append(f"{indent}    ...")

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            out.append(ast.get_source_segment(source, node))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            seg = ast.get_source_segment(source, node).splitlines()[0]
            out.append(seg if len(seg) <= 100 else seg[:97] + "...")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sig(node)
        elif isinstance(node, ast.ClassDef):
            sig(node)
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    sig(sub, "    ")
    return "\n".join(out) + "\n"


def _split_new_code(new_code: str) -> tuple[list[str], ast.AST, str]:
    """Separate leading imports from the single def/class in `new_code`."""
    code = textwrap.dedent(new_code).strip("\n") + "\n"
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise SymbolError(f"new code does not parse: line {e.lineno}: {e.msg}") from None
    imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    defs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    others = [n for n in tree.body if n not in imports and n not in defs]
    if len(defs) != 1 or others:
        raise SymbolError("new code must contain exactly one function or class (plus optional imports)")
    import_lines = [ast.get_source_segment(code, n) for n in imports]
    start, end = _span(defs[0])
    body = "\n".join(code.splitlines()[start:end]) + "\n"
    return import_lines, defs[0], body


def _add_imports(source: str, imports: list[str]) -> str:
    if not imports:
        return source
    lines = source.splitlines(keepends=True)
    existing = {line.strip() for line in lines}
    new = [imp + "\n" for imp in imports if imp.strip() not in existing]
    if not new:
        return source
    tree = ast.parse(source)
    insert_at = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (
            isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) and node is tree.body[0]
        ):
            insert_at = node.end_lineno
        else:
            break
    return "".join(lines[:insert_at] + new + lines[insert_at:])


def replace_symbol(source: str, name: str, new_code: str) -> str:
    """Replace symbol `name` (e.g. "parse" or "Store.add") with the def/class in `new_code`."""
    _, node = _find(source, name)
    imports, new_node, body = _split_new_code(new_code)
    if new_node.name != name.split(".")[-1]:
        raise SymbolError(f"new code defines {new_node.name!r}, expected {name.split('.')[-1]!r}")
    lines = source.splitlines(keepends=True)
    start, end = _span(node)
    indent = " " * node.col_offset
    replacement = textwrap.indent(body, indent, lambda line: line.strip() != "")
    result = "".join(lines[:start]) + replacement + "".join(lines[end:])
    ast.parse(result)
    return _add_imports(result, imports)


def insert_symbol(source: str, new_code: str, *, after: str | None = None, in_class: str | None = None) -> str:
    """Insert a new def/class at module end, after symbol `after`, or at the end of `in_class`."""
    imports, new_node, body = _split_new_code(new_code)
    existing = list_symbols(source)
    qual = f"{in_class}.{new_node.name}" if in_class else new_node.name
    if qual in existing:
        raise SymbolError(f"{qual!r} already exists; use replace instead")
    lines = source.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    if in_class:
        _, cls = _find(source, in_class)
        anchor = _span(cls)[1]
        indent = " " * (cls.body[0].col_offset)
        block = "\n" + textwrap.indent(body, indent, lambda line: line.strip() != "")
    else:
        anchor = _span(_find(source, after)[1])[1] if after else len(lines)
        block = "\n\n" + body
    result = "".join(lines[:anchor]) + block + "".join(lines[anchor:])
    ast.parse(result)
    return _add_imports(result, imports)
