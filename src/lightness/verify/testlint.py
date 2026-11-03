"""Reject model-written tests that can't catch real bugs.

M0's main non-intent failure was self-confirming verification: tests that mocked out the code
under test, or only asserted that something exists. This lint catches those shapes statically.
"""

import ast

PATCHERS = {"patch", "setattr", "object", "MagicMock", "Mock"}


def _call_name(node: ast.Call) -> str:
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""


def _imported_names(tree: ast.Module, modules: set[str]) -> set[str]:
    """Names bound by `import m` / `from m import x` for modules under test."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in modules:
                    names.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in modules:
            names.update(a.asname or a.name for a in node.names)
    return names


def _mocks_target(call: ast.Call, modules: set[str], names: set[str]) -> bool:
    if _call_name(call) not in {"patch", "setattr", "object"} or not call.args:
        return False
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value.split(".")[0] in modules
    root = first
    while isinstance(root, ast.Attribute):
        root = root.value
    return isinstance(root, ast.Name) and root.id in names


def _weak(test: ast.expr) -> bool:
    """assert x / assert x is not None / assert len(x) > 0 / assert isinstance(x, T)."""
    if isinstance(test, (ast.Name, ast.Attribute, ast.Subscript)):
        return True
    if isinstance(test, ast.Call) and _call_name(test) in {"isinstance", "hasattr", "callable", "exists", "is_file"}:
        return True
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        op, right = test.ops[0], test.comparators[0]
        if isinstance(op, ast.IsNot) and isinstance(right, ast.Constant) and right.value is None:
            return True
        left_is_len = isinstance(test.left, ast.Call) and _call_name(test.left) == "len"
        if left_is_len and isinstance(op, (ast.Gt, ast.GtE, ast.NotEq)) and isinstance(right, ast.Constant) \
                and right.value in (0, 1):
            return True
    return False


def lint_tests(source: str, modules_under_test: set[str]) -> list[str]:
    """Problems with a test file; empty list means acceptable."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [f"does not parse: line {e.lineno}: {e.msg}"]
    names = _imported_names(tree, modules_under_test)
    problems = []
    tests = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and n.name.startswith("test")]
    if not tests:
        problems.append("no test functions found (names must start with test_)")
    for t in tests:
        calls = [n for n in ast.walk(t) if isinstance(n, ast.Call)]
        if any(_mocks_target(c, modules_under_test, names) for c in calls):
            problems.append(f"{t.name}: mocks the code under test; test the real code instead")
        asserts = [n for n in ast.walk(t) if isinstance(n, ast.Assert)]
        raises = any(_call_name(c) == "raises" for c in calls)
        if not asserts and not raises:
            problems.append(f"{t.name}: has no assert")
        elif asserts and all(_weak(a.test) for a in asserts) and not raises:
            problems.append(f"{t.name}: only checks that something exists; assert the expected values")
    return problems
