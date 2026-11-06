"""Transcript agent: the bare agent's loop (one bash tool, full history), with middleware hooks.

Same shape and prompt as mini-swe-agent's default config, so with no middleware it should match
the bare baseline. Middleware adds harness work around that loop: things the model doesn't have
to remember or decide (workshop, automatic checks after writes, a submit gate, compaction).
"""

import json
import platform
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from lightness.bench import sandbox
from lightness.provider import Client, ContextOverflow, Reply

SUBMIT = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
SUBMIT_MARK = SUBMIT.split()[1]
SUBMIT_HINT = f"[note] That was not a submit. To submit, run exactly `{SUBMIT}` as a command of its own."
_CD_PREFIX = re.compile(r"^(?:cd\s+\S+\s*&&\s*)+")


def is_submit(command: str) -> bool:
    """The submit command, also with leading `cd DIR &&` and the marker in quotes."""
    rest = _CD_PREFIX.sub("", command.strip())
    return rest in (SUBMIT, f'echo "{SUBMIT_MARK}"', f"echo '{SUBMIT_MARK}'")

SYSTEM = "You are a helpful assistant that can interact with a computer."

INSTANCE = """Please solve this issue: {task}

You can execute bash commands and edit files to implement the necessary changes.

## Recommended Workflow

This workflow should be done step-by-step so that you can iterate on your changes and any possible problems.

1. Analyze the codebase by finding and reading relevant files
2. Create a script to reproduce the issue
3. Edit the source code to resolve the issue
4. Verify your fix works by running your script again
5. Test edge cases to ensure your fix is robust
6. Submit your changes and finish your work by issuing the following command: `{submit}`.
   Do not combine it with any other command. <important>After this command, you cannot continue working on this task.</important>

## Command Execution Rules

You are operating in an environment where

1. You issue at least one command
2. The system executes the command(s) in a subshell
3. You see the result(s)
4. You write your next command(s)

Each response should include:

1. **Reasoning text** where you explain your analysis and plan
2. At least one tool call with your command

**CRITICAL REQUIREMENTS:**

- Your response SHOULD include reasoning text explaining what you're doing
- Your response MUST include AT LEAST ONE bash tool call
- Directory or environment variable changes are not persistent. Every action is executed in a new subshell.
- However, you can prefix any action with `MY_ENV_VAR=MY_VALUE cd /path/to/working/dir && ...` or write/load environment variables from files
- Submit your changes and finish your work by issuing the following command: `{submit}`.
  Do not combine it with any other command. <important>After this command, you cannot continue working on this task.</important>

<system_information>
{system}
</system_information>

## Useful command examples

### Create a new file:

```bash
cat <<'EOF' > newfile.py
import numpy as np
hello = "world"
print(hello)
EOF
```

### Edit files with sed:
<important>
You are on MacOS. For all the below examples, you need to use `sed -i ''` instead of `sed -i`.
</important>

```bash
# Replace all occurrences
sed -i '' 's/old_string/new_string/g' filename.py
```

### View file content:

```bash
# View specific lines with numbers
nl -ba filename.py | sed -n '10,20p'
```
"""

FORMAT_ERROR = """Tool call error: your response had no bash tool call.

Every response needs to use the 'bash' tool at least once to execute commands.
Call the bash tool with your command as the argument, for example: {example}"""
TRY_COMMAND = "python .lightness/kit/try_app.py"


def format_error(ws: Path) -> str:
    """The reply to a response without a tool call. Its example is a useful next step, not a way out."""
    command = TRY_COMMAND if (ws / ".lightness" / "kit" / "try_app.py").exists() else "ls"
    return FORMAT_ERROR.format(example=json.dumps({"command": command}))


BASH_TOOL = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Execute a bash command",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "The bash command to execute"}},
            "required": ["command"],
        },
    },
}


@dataclass
class Ctx:
    """What middleware can see and change."""

    client: Client
    ws: Path
    run_dir: Path
    task: str
    env: dict[str, str]
    messages: list[dict] = field(default_factory=list)
    step: int = 0
    last_prompt_tokens: int = 0
    data: dict = field(default_factory=dict)  # per-middleware state

    def log(self, event: str, **kw) -> None:
        with (self.run_dir / "events.jsonl").open("a") as f:
            f.write(json.dumps({"ts": time.time(), "step": self.step, "event": event, **kw}) + "\n")


class Middleware:
    """Hooks run by the loop. Every hook is optional; text returned is shown to the model."""

    name = "base"

    def start(self, ctx: Ctx) -> str | None:
        """Extra text for the task message (e.g. the spec)."""

    def before_command(self, ctx: Ctx, command: str) -> None:
        """Called before each command runs (e.g. snapshot files)."""

    def after_command(self, ctx: Ctx, command: str, output: dict) -> str | None:
        """Note appended to the command's observation."""

    def on_submit(self, ctx: Ctx) -> str | None:
        """Return text to refuse the submission (the text explains why); None to accept."""

    def before_call(self, ctx: Ctx) -> None:
        """Called before every model call; may rewrite ctx.messages (compaction)."""


def observation(output: dict) -> str:
    """mini-swe-agent's observation format."""
    text = output["output"]
    if len(text) < 10000:
        return json.dumps({"returncode": output["returncode"], "output": text}, indent=2)
    return json.dumps({"returncode": output["returncode"], "output_head": text[:5000], "output_tail": text[-5000:],
                       "elided_chars": len(text) - 10000, "warning": "Output too long."}, indent=2)


ALT_SCREEN = "\x1b[?1049h"  # a full-screen terminal app (Textual, curses) has started
INTERACTIVE_NOTE = ("\n(stopped by the harness: this started an interactive full-screen app, and commands have no "
                    "terminal, so it would wait forever. Test Textual apps headlessly with App.run_test().)")
TRY_NOTE = ("\n(stopped by the harness: this started an interactive full-screen app, and commands have no "
            "terminal, so it would wait forever. To see what the app does, run "
            "`python .lightness/kit/try_app.py STEP ...`: it runs the app headless and prints the screen.)")
BACKGROUND_NOTE = ("\n(the harness stopped processes this command left running in the background; each command "
                   "runs on its own, so start a server and query it within the same command)")


def run_command_guarded(command: str, ctx: Ctx, timeout: int = 120) -> dict:
    """Like run_command, but never hangs on interactive apps or background processes: output goes to a
    file (a background process can't hold a pipe open), stdin is closed, a full-screen app is stopped
    as soon as it draws, and whatever the command left running is stopped when it exits."""
    import os
    import signal
    import tempfile

    with tempfile.TemporaryFile(mode="w+b", dir=ctx.run_dir) as out:
        proc = subprocess.Popen(sandbox.wrap_shell(command, ctx.run_dir), shell=True, cwd=ctx.ws, env=ctx.env,
                                stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                start_new_session=True)
        start, note = time.time(), ""
        while proc.poll() is None:
            if time.time() - start > timeout:
                note = f"\n(command timed out after {timeout}s)"
                break
            out.seek(0)
            if ALT_SCREEN.encode() in out.read():
                note = INTERACTIVE_NOTE
                break
            time.sleep(0.25)
        try:  # stop the command if still running, and anything it started in the background
            os.killpg(proc.pid, 0)
            os.killpg(proc.pid, signal.SIGKILL)
            if not note:
                note = BACKGROUND_NOTE
        except ProcessLookupError:
            pass
        proc.wait()
        out.seek(0)
        text = out.read().decode(errors="replace")
    if note == INTERACTIVE_NOTE:
        text = text.split(ALT_SCREEN)[0]  # drop the escape-code soup the app drew
        if (ctx.ws / ".lightness" / "kit" / "try_app.py").exists():
            note = TRY_NOTE
    returncode = -1 if note and note != BACKGROUND_NOTE else proc.returncode
    return {"output": text + note, "returncode": returncode}


def run_command(command: str, ctx: Ctx, timeout: int = 120) -> dict:
    try:
        proc = subprocess.run(sandbox.wrap_shell(command, ctx.run_dir), shell=True, cwd=ctx.ws, env=ctx.env,
                              capture_output=True, text=True, errors="replace", timeout=timeout,
                              check=False)
        return {"output": proc.stdout + proc.stderr, "returncode": proc.returncode}
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return {"output": out + f"\n(command timed out after {timeout}s)", "returncode": -1}


@dataclass
class Result:
    status: str
    steps: int
    submitted: bool


_FENCE = re.compile(r"```(\w*)[ \t]*\n(.*?)```", re.DOTALL)


def text_tool_call(text: str) -> str | None:
    """The command of a bash call written as text: one {"command": ...} JSON object (bare, fenced,
    or wrapped as {"name": "bash", "parameters": {...}}), else one ```bash block. None if unclear."""
    found = []
    decoder = json.JSONDecoder()
    i = text.find("{")
    while i != -1:
        try:
            obj, end = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            i = text.find("{", i + 1)
            continue
        if isinstance(obj, dict):
            inner = obj.get("parameters") or obj.get("arguments") or obj
            if isinstance(inner, dict) and isinstance(inner.get("command"), str):
                found.append(inner["command"])
        i = text.find("{", end)
    if not found:
        found = [body.strip() for lang, body in _FENCE.findall(text) if lang in ("bash", "sh", "shell")]
    return found[0] if len(found) == 1 and found[0].strip() else None


class TranscriptAgent:
    def __init__(self, client: Client, ws: Path, run_dir: Path, env: dict[str, str], *,
                 middleware: list[Middleware] = (), step_limit: int = 150, wall_limit: float = 1800,
                 guard_commands: bool = False):
        self.client, self.ws, self.run_dir, self.env = client, ws, run_dir, env
        self.runner = run_command_guarded if guard_commands else run_command
        self.middleware = list(middleware)
        self.step_limit, self.wall_limit = step_limit, wall_limit

    def run(self, task: str) -> Result:
        ctx = Ctx(self.client, self.ws, self.run_dir, task, self.env)
        extras = [x for m in self.middleware if (x := m.start(ctx))]
        full_task = task + "".join("\n\n" + x for x in extras)
        system = f"{platform.system()} {platform.release()} {platform.machine()}"
        ctx.messages = [{"role": "system", "content": SYSTEM},
                        {"role": "user", "content": INSTANCE.format(task=full_task, submit=SUBMIT, system=system)}]
        try:
            return self._loop(ctx)
        except Exception:
            (self.run_dir / "messages.json").write_text(json.dumps(ctx.messages, indent=1))  # for analysis
            raise

    def _loop(self, ctx: Ctx) -> Result:
        start = time.time()
        while True:
            if ctx.step >= self.step_limit:
                return self._end(ctx, "LimitsExceeded", False)
            if time.time() - start > self.wall_limit:
                return self._end(ctx, "TimeExceeded", False)
            ctx.step += 1
            for m in self.middleware:
                m.before_call(ctx)
            try:
                for _ in range(5):  # an empty reply (e.g. a proxy's moderation block) is asked again
                    reply = self.client.chat(ctx.messages, purpose="agent", thinking=True, max_tokens=16384,
                                             tools=[BASH_TOOL])
                    if reply.tool_calls or reply.text.strip():
                        break
                    ctx.log("empty_reply", finish=reply.finish_reason, refusal=reply.refusal[:120])
            except ContextOverflow:
                return self._end(ctx, "ContextOverflow", False)
            ctx.last_prompt_tokens = reply.usage.get("prompt_tokens") or 0
            if reply.reasoning:  # kept out of the transcript, saved for failure analysis
                with (self.run_dir / "reasoning.jsonl").open("a") as f:
                    f.write(json.dumps({"step": ctx.step, "reasoning": reply.reasoning}) + "\n")
            if not reply.tool_calls and (command := text_tool_call(reply.text)) is not None:
                # The model wrote the call as text instead of calling the tool: take it as the call.
                reply.tool_calls = [{"id": f"text-{ctx.step}", "type": "function",
                                     "function": {"name": "bash", "arguments": json.dumps({"command": command})}}]
                reply.text = ""  # some APIs (Bedrock) reject text and a tool call in one message
                ctx.log("text_tool_call")
            ctx.messages.append(self._assistant(reply))
            calls = [c for c in reply.tool_calls if c.get("function", {}).get("name") == "bash"]
            if not calls:
                ctx.messages.append({"role": "user", "content": format_error(ctx.ws)})
                ctx.log("format_error", finish=reply.finish_reason)
                continue
            for call in calls:
                command = _command(call)
                if is_submit(command):
                    refusal = next((x for m in self.middleware if (x := m.on_submit(ctx))), None)
                    if refusal is None:
                        ctx.messages.append(self._tool(call, "Submitted."))
                        return self._end(ctx, "Submitted", True)
                    ctx.log("submit_refused", by=refusal[:200])
                    ctx.messages.append(self._tool(call, refusal))
                    continue
                for m in self.middleware:
                    m.before_command(ctx, command)
                output = self.runner(command, ctx)
                notes = [x for m in self.middleware if (x := m.after_command(ctx, command, output))]
                if SUBMIT_MARK in command:
                    notes.append(SUBMIT_HINT)
                ctx.messages.append(self._tool(call, observation(output) + "".join("\n\n" + n for n in notes)))
                with (self.run_dir / "steps.jsonl").open("a") as f:  # live view of a run (watch_run.py)
                    f.write(json.dumps({"step": ctx.step, "t": round(time.time() - start), "command": command,
                                        "output": _ends(ctx.messages[-1]["content"]),
                                        "notes": [n.splitlines()[0][:200] for n in notes]}) + "\n")

    def _end(self, ctx: Ctx, status: str, submitted: bool) -> Result:
        (self.run_dir / "messages.json").write_text(json.dumps(ctx.messages, indent=1))
        return Result(status, ctx.step, submitted)

    @staticmethod
    def _assistant(reply: Reply) -> dict:
        empty = not reply.text.strip() and not reply.tool_calls
        msg: dict = {"role": "assistant", "content": "(empty response)" if empty else reply.text}  # APIs reject empty text
        if reply.tool_calls:
            msg["tool_calls"] = reply.tool_calls
        return msg

    @staticmethod
    def _tool(call: dict, content: str) -> dict:
        return {"role": "tool", "tool_call_id": call.get("id", ""), "content": content}


def _command(call: dict) -> str:
    try:
        return str(json.loads(call["function"].get("arguments") or "{}").get("command", ""))
    except json.JSONDecodeError:
        return ""


def _ends(text: str, head: int = 600, tail: int = 900) -> str:
    """Both ends of a long output (the checks summary is at the start, failures at the end)."""
    return text if len(text) <= head + tail else text[:head] + "\n…\n" + text[-tail:]
