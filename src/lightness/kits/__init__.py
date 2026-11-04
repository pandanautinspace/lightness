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


FILE_ROLES = ("data", "input")


def file_params(names: dict) -> list[dict]:
    """The App's file parameters (data and input), in order."""
    return [p for p in names.get("params") or [] if p["role"] in FILE_ROLES]


def default_file(param: dict) -> str:
    return param.get("file") or ("data.json" if param["role"] == "data" else "input.txt")


def _tui_values(values: dict) -> set[str]:
    """Fill the TUI shell's generated names from the params list; returns the blocks to keep."""
    params = values.get("params") or []
    seen = [p["name"] for p in params]
    if len(set(seen)) != len(seen) or "self" in seen:
        raise ValueError(f"bad parameter names: {seen}")
    files = file_params(values)
    store = next((p for p in params if p["role"] == "data" and default_file(p).endswith(".json")), None)
    imports = {"import sys"} | ({"import json"} if store else set())
    imports |= {"import time"} if any(p["role"] == "clock" for p in params) else set()
    imports |= {"import random"} if any(p["role"] == "seed" for p in params) else set()
    values["imports"] = "\n".join(sorted(imports) + (["from pathlib import Path"] if files else []))
    const = {p["name"]: f"DEFAULT_{p['name'].upper()}" for p in files}
    values["defaults"] = "".join(f'{const[p["name"]]} = "{default_file(p)}"\n' for p in files) + ("\n\n" if files else "")
    from textual.app import App

    attr = {p["name"]: p["name"] + "_arg" if hasattr(App, p["name"]) else p["name"] for p in params}
    sig, body = [], []
    for p in params:
        n = p["name"]
        if p["role"] in FILE_ROLES:
            sig.append(f"{n}: str = {const[n]}")
            body.append(f"self.{attr[n]} = Path({n})" + ("  # read only" if p["role"] == "input" else ""))
        elif p["role"] == "clock":
            sig.append(f"{n}=time.monotonic")
            body.append(f"self.{attr[n]} = {n}  # read the time only through this: tests pass a fake clock")
        elif p["role"] == "seed":
            sig.append(f"{n}: int | None = None")
            body.append(f"self.rng = random.Random({n})  # all randomness comes from here")
        else:
            sig.append(f"{n}=None")
            body.append(f"self.{attr[n]} = {n}" + ("  # App already has .{n}" if attr[n] != n else ""))
        if p is store:
            body.append(f"self.data = load_data(self.{attr[n]})")
    sig.insert(0, "self")
    values["init_params"] = ", ".join(sig)
    if len(values["init_params"]) > 70:
        values["init_params"] = "".join(f"\n        {x}," for x in sig) + "\n    "
    values["init_body"] = "".join(f"        {line}\n" for line in body)
    values["usage_arg"] = "".join(f" [{p['name'].upper()}]" for p in files)
    cls = values["app_class"]
    values["main_body"] = (f"    paths = dict(zip({[p['name'] for p in files]!r}, args))\n    {cls}(**paths).run()"
                           if files else f"    {cls}().run()")
    values["data_param"] = attr[store["name"]] if store else ""
    return {"json"} if store else set()


def render_shell(kit: Kit, names: dict) -> str:
    """The shell program for these names. Raises ValueError if the result doesn't parse."""
    values = dict(names)
    keep = _tui_values(values) if kit.category == "tui" else set()
    text = _blocks((kit.dir / "shell.py.tmpl").read_text(), keep)
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    text = re.sub(r"\n{4,}", "\n\n\n", text)  # blocks and empty names leave extra blank lines
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


def describe_params(names: dict) -> str:
    """How the try command starts each App parameter, for the try notes."""
    said = []
    for p in names.get("params") or []:
        if p["role"] == "data":
            said.append(f"`{p['name']}` (data file: starts with no file)")
        elif p["role"] == "input":
            said.append(f"`{p['name']}` (input file: starts as a copy of the project's {default_file(p)} "
                        f"if there is one)")
        elif p["role"] == "clock":
            said.append(f"`{p['name']}` (a fake clock: time moves only on advance:SECONDS)")
    return ("Parameters it passes: " + ", ".join(said) + ".") if said else "The app takes no file or clock parameters."


def trying(kit: Kit, names: dict) -> str:
    path = kit.dir / "try.md"
    if not (kit.try_tool and path.exists()):
        return ""
    return path.read_text().replace("{module}", names["module"]).replace("{params}", describe_params(names)) + "\n\n"


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
