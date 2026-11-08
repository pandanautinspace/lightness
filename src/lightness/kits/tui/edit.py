"""Change part of a file without writing all of it again.

    python .lightness/kit/edit.py FILE <<'EOF'
    <<<<<<< SEARCH
    lines now in the file (copied exactly, a few whole lines)
    =======
    the lines to put there instead
    >>>>>>> REPLACE
    EOF

Several SEARCH/REPLACE blocks may follow each other. Each SEARCH must match exactly one place in
FILE; if any block doesn't, nothing is changed and the closest lines are shown. A Python file that
compiled before must still compile after the change, or nothing is changed.
"""

import difflib
import sys
from pathlib import Path

SEARCH, SEP, REPLACE = "<<<<<<< SEARCH", "=======", ">>>>>>> REPLACE"


def parse(text: str) -> list[tuple[list[str], list[str]]]:
    """The (search lines, replace lines) blocks; ValueError on a malformed block."""
    blocks, state, old, new = [], None, [], []
    for line in text.splitlines():
        mark = line.strip()
        if mark == SEARCH and state is None:
            state, old, new = "old", [], []
        elif mark == SEP and state == "old":
            state = "new"
        elif mark == REPLACE and state == "new":
            blocks.append((old, new))
            state = None
        elif state == "old":
            old.append(line)
        elif state == "new":
            new.append(line)
        elif mark:
            raise ValueError(f"text outside a block: {line[:80]!r} (each block is {SEARCH} / old lines / "
                             f"{SEP} / new lines / {REPLACE})")
    if state is not None:
        missing = SEP if state == "old" else REPLACE
        raise ValueError(f"the last block has no {missing} line")
    if not blocks:
        raise ValueError(f"no blocks: give {SEARCH} / old lines / {SEP} / new lines / {REPLACE} on stdin")
    return blocks


def find(lines: list[str], old: list[str]) -> list[int]:
    """Start indexes where old matches: exactly, else ignoring trailing spaces."""
    n = len(old)
    hits = [i for i in range(len(lines) - n + 1) if lines[i:i + n] == old]
    if not hits:
        strip = [x.rstrip() for x in old]
        hits = [i for i in range(len(lines) - n + 1) if [x.rstrip() for x in lines[i:i + n]] == strip]
    return hits


def closest(lines: list[str], old: list[str]) -> str:
    """The stretch of the file most like old, numbered, to copy from."""
    n = max(len(old), 1)
    best, at = 0.0, 0
    for i in range(max(len(lines) - n + 1, 1)):
        r = difflib.SequenceMatcher(None, "\n".join(old), "\n".join(lines[i:i + n])).ratio()
        if r > best:
            best, at = r, i
    lo, hi = max(at - 1, 0), min(at + n + 1, len(lines))
    return "\n".join(f"{k + 1:4}| {lines[k]}" for k in range(lo, hi))


def replace_text(spec: dict) -> int:
    """The edit_file tool (the harness turns its call into `edit.py --json` with this JSON on stdin):
    old_text must occur exactly once in path; empty old_text with a missing path creates the file."""
    path, old, new = Path(spec.get("path", "")), spec.get("old_text", ""), spec.get("new_text", "")
    if not spec.get("path"):
        print("Nothing changed: edit_file needs a path.")
        return 1
    if not path.exists():
        if old:
            print(f"Nothing changed: {path} doesn't exist. To create it, call edit_file with empty old_text.")
            return 1
        path.write_text(new)
        print(f"Created {path} ({len(new.splitlines())} lines).")
        return 0
    text = path.read_text()
    if not old:
        print(f"Nothing changed: old_text is empty; copy the exact text to replace from {path}.")
        return 1
    count = text.count(old)
    if count == 0 and old.strip() and text.count(old.strip("\n")) == 1:
        old = old.strip("\n")  # a stray leading/trailing newline
        new = new.strip("\n") if new.strip("\n") != new else new
        count = 1
    if count == 0:
        print(f"Nothing changed: old_text is not in {path} (it must match exactly, spaces included). Closest "
              "lines now in the file:\n" + closest(text.splitlines(), old.splitlines()))
        return 1
    if count > 1:
        starts, at = [], -1
        while (at := text.find(old, at + 1)) >= 0:
            starts.append(text.count("\n", 0, at) + 1)
        print(f"Nothing changed: old_text occurs {count} times in {path} (lines {', '.join(map(str, starts[:6]))}); "
              "include a line before or after to pick one.")
        return 1
    lines, gone = len(text.splitlines()), len(old.splitlines()) - len(new.splitlines())
    if lines > 10 and not new.strip() and gone > lines // 2:
        # the 35B, meaning to submit, once sent the whole of browse.py as old_text with empty new_text
        print(f"Nothing changed: that would delete {gone} of the {lines} lines of {path}. To delete code, give just "
              f"those lines as old_text; to replace the whole file, write it with cat > {path}.")
        return 1
    result = text.replace(old, new, 1)
    if path.suffix == ".py" and compiles(text, path) is True and (why := compiles(result, path)) is not True:
        print(why)  # a file that compiled must still compile
        return 1
    path.write_text(result)
    line = text[:text.find(old)].count("\n") + 1
    print(f"Edited {path}: lines {line}-{line + max(new.count(chr(10)), 0)} ({len(result.splitlines())} lines now).")
    return 0


def compiles(text: str, path: Path) -> bool | str:
    """True, or why it doesn't compile (a numbered excerpt)."""
    try:
        compile(text, str(path), "exec")
        return True
    except SyntaxError as e:
        lines = text.splitlines()
        at = e.lineno or 1
        return (f"Nothing changed: after this edit {path} would not compile: {e.msg} at line {at}:\n"
                + "\n".join(f"{k + 1:4}| {lines[k]}" for k in range(max(at - 3, 0), min(at + 2, len(lines)))))


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[1] == "--json":
        import json

        try:
            return replace_text(json.loads(sys.stdin.read()))
        except json.JSONDecodeError as e:
            print(f"Nothing changed: bad edit_file arguments ({e}).")
            return 1
    if len(argv) != 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 2
    path = Path(argv[1])
    if not path.exists():
        print(f"{path} doesn't exist. To create a file, write it whole: cat > {path} <<'EOF' ... EOF")
        return 1
    try:
        blocks = parse(sys.stdin.read())
    except ValueError as e:
        print(f"Nothing changed: {e}")
        return 1
    text = path.read_text()
    lines = text.splitlines()
    problems, edits = [], []
    for k, (old, new) in enumerate(blocks, 1):
        if not any(x.strip() for x in old):
            problems.append(f"block {k}: SEARCH is empty; copy the lines to replace from the file")
            continue
        hits = find(lines, old)
        if not hits:
            problems.append(f"block {k}: SEARCH matches nothing in {path}. Closest lines now in the file:\n"
                            + closest(lines, old))
        elif len(hits) > 1:
            problems.append(f"block {k}: SEARCH matches {len(hits)} places (lines "
                            f"{', '.join(str(h + 1) for h in hits[:6])}); add a line before or after to pick one")
        else:
            edits.append((hits[0], len(old), new, k))
    spans = sorted((at, at + n, k) for at, n, _, k in edits)
    for (a0, a1, ka), (b0, b1, kb) in zip(spans, spans[1:]):
        if b0 < a1:
            problems.append(f"blocks {ka} and {kb} change the same lines; merge them into one block")
    if problems:
        print("Nothing changed.\n" + "\n".join(problems))
        return 1
    out = list(lines)
    for at, n, new, _ in sorted(edits, reverse=True):
        out[at:at + n] = new
    result = "\n".join(out) + ("\n" if text.endswith("\n") or not text else "")
    if path.suffix == ".py":
        try:
            compile(text, str(path), "exec")
            was_ok = True
        except SyntaxError:
            was_ok = False
        if was_ok:
            try:
                compile(result, str(path), "exec")
            except SyntaxError as e:
                print(f"Nothing changed: after this edit {path} would not compile: {e.msg} at line {e.lineno}:\n"
                      + "\n".join(f"{k + 1:4}| {out[k]}" for k in range(max((e.lineno or 1) - 3, 0),
                                                                          min((e.lineno or 1) + 2, len(out)))))
                return 1
    path.write_text(result)
    shift, report = 0, []
    for at, n, new, k in sorted(edits):
        report.append(f"lines {at + shift + 1}-{at + shift + max(len(new), 1)}" if new else f"removed at line {at + shift + 1}")
        shift += len(new) - n
    print(f"Edited {path}: " + "; ".join(report) + f" ({len(out)} lines now).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
