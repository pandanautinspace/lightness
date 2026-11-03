"""Kits: a starting point per app type (see docs/kits.md).

A kit is a directory under src/lightness/kits/<category>/ with kit.toml, a shell template, design
notes, a cheat sheet and runnable parts. The harness fills the shell with names from the task's
contract and writes it into the workspace, so the model starts from a program that already runs.
"""

import ast
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

KITS_DIR = Path(__file__).parent
_BLOCK = re.compile(r"^[ \t]*# \[(?P<close>/?)(?P<name>\w+)\]\n", re.M)


@dataclass
class Part:
    name: str
    when: str
    path: Path


@dataclass
class Kit:
    category: str
    dir: Path
    meta: dict

    @property
    def parts(self) -> list[Part]:
        return [Part(p["name"], p["when"], self.dir / "parts" / f"{p['name']}.py") for p in self.meta["parts"]]

    @property
    def notes(self) -> str:
        return (self.dir / "notes.md").read_text()

    @property
    def cheatsheet(self) -> str:
        return (self.dir / "cheatsheet.md").read_text()

    @property
    def try_tool(self) -> Path | None:
        """A script that runs the app and prints what it shows, copied into the workspace."""
        path = self.dir / "try_app.py"
        return path if path.exists() else None

    @property
    def names_schema(self) -> dict:
        """JSON schema for the names the shell needs, filled from the task's contract."""
        props = {k: v["schema"] for k, v in self.meta["names"].items()}
        return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}

    def names_prompt(self, task: str) -> str:
        lines = "\n".join(f"- {k}: {v['help']}" for k, v in self.meta["names"].items())
        return (f"A new {self.category} app will be started from a template. Read the task and give the names "
                f"the template needs. Use the exact names the task's contract states; otherwise choose short, "
                f"conventional ones.\n\n{lines}\n\n## Task\n{task}")


def available() -> list[str]:
    return sorted(p.name for p in KITS_DIR.iterdir() if (p / "kit.toml").exists())


def load_kit(category: str) -> Kit | None:
    d = KITS_DIR / category
    if not (d / "kit.toml").exists():
        return None
    return Kit(category, d, tomllib.loads((d / "kit.toml").read_text()))


def _blocks(text: str, keep: set[str]) -> str:
    """Keep or drop `# [name]` ... `# [/name]` blocks; the marker lines always go."""
    out, pos, dropping = [], 0, []
    for m in _BLOCK.finditer(text):
        if not dropping:
            out.append(text[pos:m.start()])
        if m["close"]:
            if dropping and dropping[-1] == m["name"]:
                dropping.pop()
        elif m["name"] not in keep or dropping:
            dropping.append(m["name"])
        pos = m.end()
    if not dropping:
        out.append(text[pos:])
    return "".join(out)


def render_shell(kit: Kit, names: dict) -> str:
    """The shell program for these names. Raises ValueError if the result doesn't parse."""
    values = dict(names)
    keep = set()
    if kit.category == "tui":
        storage = values.get("storage", "none")
        if storage != "none" and values.get("data_arg"):
            keep.add("path")
            if storage == "json":
                keep.add("json")
        else:
            values["data_arg"] = ""
        arg = values["data_arg"]
        values["init_params"] = f", {arg}: str = DEFAULT_DATA" if arg else ""
        values["usage_arg"] = " [DATA_PATH]" if arg else ""
        values["main_body"] = (f"{values['app_class']}(args[0] if args else DEFAULT_DATA).run()" if arg
                               else f"{values['app_class']}().run()")
    text = _blocks((kit.dir / "shell.py.tmpl").read_text(), keep)
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    left = re.findall(r"\{\{\w+\}\}", text)
    if left:
        raise ValueError(f"unfilled names in shell: {sorted(set(left))}")
    try:
        ast.parse(text)
    except SyntaxError as e:
        raise ValueError(f"shell does not parse: {e}") from e
    return text


def shell_path(kit: Kit, names: dict) -> str:
    return f"{names['module']}.py"


def trying(kit: Kit, names: dict) -> str:
    path = kit.dir / "try.md"
    return path.read_text().replace("{module}", names["module"]) + "\n\n" if kit.try_tool and path.exists() else ""


def context(kit: Kit, names: dict, parts_dir: str, chosen: list[str]) -> str:
    """Text for the task message: what was created, the design notes, the cheat sheet and the parts."""
    index = "\n".join(f"- `{p.name}`: {p.when}" for p in kit.parts)
    inline = "".join(f"\n### Part `{p.name}`\n```python\n{p.path.read_text()}```\n"
                     for p in kit.parts if p.name in chosen)
    return (f"## Starting point\n\nI created `{shell_path(kit, names)}`, a minimal {kit.category} app that already "
            f"runs. Build the task on it: keep its structure, replace the placeholder content.\n\n"
            f"{kit.notes}\n\n{trying(kit, names)}{kit.cheatsheet}\n\n"
            f"## Parts\n\nSmall, working examples of common patterns, in `{parts_dir}`. Read one with "
            f"`cat {parts_dir}/<name>.py` when you need it; copy what fits.\n\n{index}\n{inline}")
