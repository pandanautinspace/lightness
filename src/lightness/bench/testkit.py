"""Helpers imported by hidden task tests.

Tests never hardcode paths: the runner sets BENCH_WORKSPACE to a scratch copy of the
agent's workspace, and tests reach the agent's code only through the task's contract.
"""

import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import httpx


def workspace() -> Path:
    return Path(os.environ["BENCH_WORKSPACE"])


def import_from_workspace(module: str):
    """Import a module from the workspace (contract-level functions)."""
    import importlib

    ws = str(workspace())
    if ws not in sys.path:
        sys.path.insert(0, ws)
    return importlib.import_module(module)


def run_cli(*args: str, cwd: Path | None = None, timeout: int = 60, input: str | None = None):
    """Run `python <args>` in the workspace. Returns CompletedProcess (text)."""
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd or workspace(),
        capture_output=True,
        text=True,
        timeout=timeout,
        input=input,
    )


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def serve(*args: str, port: int, health: str = "/", timeout: float = 30):
    """Start `python <args>` (which must listen on `port`), wait until it answers, yield a client."""
    proc = subprocess.Popen(
        [sys.executable, *args],
        cwd=workspace(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + timeout
        while True:
            if proc.poll() is not None:
                raise RuntimeError(f"server exited early:\n{proc.stdout.read()}")
            try:
                httpx.get(base + health, timeout=1)
                break
            except httpx.TransportError:
                if time.time() > deadline:
                    raise TimeoutError("server did not start")
                time.sleep(0.25)
        with httpx.Client(base_url=base, timeout=10, follow_redirects=True) as client:
            yield client
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
