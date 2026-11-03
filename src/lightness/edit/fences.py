"""Extract the code block a model was asked to write, tolerating chatter around it."""

import ast
import re


class FenceError(ValueError):
    pass


_OPEN = re.compile(r"^(?P<fence>`{3,}|~{3,})(?P<info>[^\n`]*)$")


def blocks(text: str) -> list[tuple[str, str]]:
    """All fenced blocks as (info string, body). Raises FenceError on an unterminated fence."""
    out, lines, i = [], text.splitlines(), 0
    while i < len(lines):
        m = _OPEN.match(lines[i].strip())
        if not m:
            i += 1
            continue
        fence, info = m["fence"], m["info"].strip()
        body, i = [], i + 1
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.startswith(fence[0] * len(fence)) and set(stripped) == {fence[0]}:
                break
            body.append(lines[i])
            i += 1
        else:
            raise FenceError("unterminated code block (output was probably cut off)")
        out.append((info, "\n".join(body)))
        i += 1
    return out


_FILENAME_LINE = re.compile(r"^\s*(file:\s*)?[\w./-]+\.py\s*$")


def _drop_filename_echo(body: str) -> str:
    """Drop a first line that only names the file (`ingest.py`), which some models echo."""
    lines = body.splitlines()
    if lines and _FILENAME_LINE.match(lines[0]):
        return "\n".join(lines[1:])
    return body


def extract_code(text: str, filename: str | None = None) -> str:
    """Return the single code block in `text`.

    With several blocks, prefer the one whose info string names `filename`, else the one with
    the most lines if every other block is short (≤3 lines, e.g. a shell command). With no
    fences, accept the whole text only if it parses as Python.
    """
    found = blocks(text)
    if not found:
        candidate = text.strip()
        try:
            ast.parse(candidate)
        except SyntaxError:
            raise FenceError("no code block found") from None
        return candidate + "\n"
    found = [(info, _drop_filename_echo(b)) for info, b in found]
    if len(found) == 1:
        return found[0][1].rstrip() + "\n"
    if filename:
        named = [b for info, b in found if filename in info]
        if len(named) == 1:
            return named[0].rstrip() + "\n"
    found.sort(key=lambda b: len(b[1].splitlines()), reverse=True)
    if all(len(b.splitlines()) <= 3 for _, b in found[1:]):
        return found[0][1].rstrip() + "\n"
    raise FenceError(f"{len(found)} code blocks found; expected exactly one")
