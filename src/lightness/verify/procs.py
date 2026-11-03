"""Run a long-lived process (a server) for the duration of a check, then always kill it.

The model never backgrounds processes itself: M0 lost 10 turns to a stale server and 14 minutes
to `&`-started commands that blocked the shell.
"""

import os
import signal
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from lightness.bench import sandbox

BIN = Path(sys.prefix) / "bin"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class Running:
    proc: subprocess.Popen
    port: int | None
    log_path: Path
    base_url: str = ""
    client: httpx.Client | None = field(default=None, repr=False)

    def output(self, max_chars: int = 3000) -> str:
        text = self.log_path.read_text(errors="replace") if self.log_path.exists() else ""
        return text[-max_chars:]


class StartError(RuntimeError):
    def __init__(self, message: str, output: str):
        super().__init__(message)
        self.output = output


def _env(run_dir: Path | None, extra: dict[str, str]) -> dict[str, str]:
    env = os.environ | {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
                        "PATH": f"{BIN}:{os.environ['PATH']}"} | extra
    if run_dir is not None:
        env |= sandbox.sandbox_env(run_dir)
    return env


@contextmanager
def running(
    args: list[str],
    ws: Path,
    *,
    run_dir: Path | None = None,
    port: int | None = None,
    health_path: str = "/",
    startup_timeout: float = 20,
    env: dict[str, str] | None = None,
):
    """Start `python *args` in `ws` (sandboxed if run_dir), wait for `port` to answer HTTP, yield.

    `{port}` in args is replaced with the port. If port is None, waits only until the process
    has stayed up for one second. The process group is killed on exit, whatever happens.
    """
    if port is None and any("{port}" in a for a in args):
        port = free_port()
    args = [a.replace("{port}", str(port)) for a in args]
    cmd = [str(BIN / "python"), *args]
    if run_dir is not None:
        cmd = [*sandbox.sandbox_prefix(run_dir), *cmd]
    log_dir = run_dir if run_dir is not None else ws
    log_path = Path(log_dir) / f".proc-{time.time_ns()}.log"
    log = log_path.open("w")
    proc = subprocess.Popen(cmd, cwd=ws, stdout=log, stderr=subprocess.STDOUT,
                            env=_env(run_dir, (env or {}) | ({"PORT": str(port)} if port else {})),
                            start_new_session=True)
    r = Running(proc, port, log_path)
    try:
        deadline = time.time() + startup_timeout
        if port is None:
            time.sleep(1)
            if proc.poll() is not None:
                raise StartError(f"process exited with code {proc.returncode}", r.output())
        else:
            r.base_url = f"http://127.0.0.1:{port}"
            while True:
                if proc.poll() is not None:
                    raise StartError(f"server exited with code {proc.returncode} before answering", r.output())
                try:
                    httpx.get(r.base_url + health_path, timeout=1)
                    break
                except httpx.TransportError:
                    if time.time() > deadline:
                        raise StartError(f"server did not answer on port {port} within {startup_timeout:.0f}s",
                                         r.output()) from None
                    time.sleep(0.2)
            r.client = httpx.Client(base_url=r.base_url, timeout=10, follow_redirects=True)
        yield r
    finally:
        if r.client:
            r.client.close()
        _kill(proc)
        log.close()


def _kill(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(3)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(3)
