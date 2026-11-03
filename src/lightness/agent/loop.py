"""Transcript agent: the bare agent's loop (one bash tool, full history), with middleware hooks.

Same shape and prompt as mini-swe-agent's default config, so with no middleware it should match
the bare baseline. Middleware adds harness work around that loop: things the model doesn't have
to remember or decide (workshop, automatic checks after writes, a submit gate, compaction).
"""

import json
import platform
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from lightness.bench import sandbox
from lightness.provider import Client, ContextOverflow, Reply

SUBMIT = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"

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
Call the bash tool with your command as the argument: {"command": "your_command_here"}
If you want to end the task, issue the command `""" + SUBMIT + "` without any other command."

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


class TranscriptAgent:
    def __init__(self, client: Client, ws: Path, run_dir: Path, env: dict[str, str], *,
                 middleware: list[Middleware] = (), step_limit: int = 100, wall_limit: float = 1800):
        self.client, self.ws, self.run_dir, self.env = client, ws, run_dir, env
        self.middleware = list(middleware)
        self.step_limit, self.wall_limit = step_limit, wall_limit

    def run(self, task: str) -> Result:
        ctx = Ctx(self.client, self.ws, self.run_dir, task, self.env)
        extras = [x for m in self.middleware if (x := m.start(ctx))]
        full_task = task + "".join("\n\n" + x for x in extras)
        system = f"{platform.system()} {platform.release()} {platform.machine()}"
        ctx.messages = [{"role": "system", "content": SYSTEM},
                        {"role": "user", "content": INSTANCE.format(task=full_task, submit=SUBMIT, system=system)}]
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
                reply = self.client.chat(ctx.messages, purpose="agent", thinking=True, max_tokens=16384,
                                         tools=[BASH_TOOL])
            except ContextOverflow:
                return self._end(ctx, "ContextOverflow", False)
            ctx.last_prompt_tokens = reply.usage.get("prompt_tokens") or 0
            if reply.reasoning:  # kept out of the transcript, saved for failure analysis
                with (self.run_dir / "reasoning.jsonl").open("a") as f:
                    f.write(json.dumps({"step": ctx.step, "reasoning": reply.reasoning}) + "\n")
            ctx.messages.append(self._assistant(reply))
            calls = [c for c in reply.tool_calls if c.get("function", {}).get("name") == "bash"]
            if not calls:
                ctx.messages.append({"role": "user", "content": FORMAT_ERROR})
                ctx.log("format_error", finish=reply.finish_reason)
                continue
            for call in calls:
                command = _command(call)
                if command.strip() == SUBMIT:
                    refusal = next((x for m in self.middleware if (x := m.on_submit(ctx))), None)
                    if refusal is None:
                        ctx.messages.append(self._tool(call, "Submitted."))
                        return self._end(ctx, "Submitted", True)
                    ctx.log("submit_refused", by=refusal[:200])
                    ctx.messages.append(self._tool(call, refusal))
                    continue
                for m in self.middleware:
                    m.before_command(ctx, command)
                output = run_command(command, ctx)
                notes = [x for m in self.middleware if (x := m.after_command(ctx, command, output))]
                ctx.messages.append(self._tool(call, observation(output) + "".join("\n\n" + n for n in notes)))

    def _end(self, ctx: Ctx, status: str, submitted: bool) -> Result:
        (self.run_dir / "messages.json").write_text(json.dumps(ctx.messages, indent=1))
        return Result(status, ctx.step, submitted)

    @staticmethod
    def _assistant(reply: Reply) -> dict:
        msg: dict = {"role": "assistant", "content": reply.text}
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
