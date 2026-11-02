"""Run untrusted commands under macOS sandbox-exec (see sandbox.sb).

Stopgap until runs move into Docker/OrbStack: nothing under $HOME is readable except the run
directory, the bench venv and the lightness package; writes are confined to the run directory;
outbound network is localhost only.
"""

import os
import shlex
from pathlib import Path

from lightness.bench.tasks import REPO_ROOT

PROFILE = Path(__file__).with_name("sandbox.sb")


def sandbox_prefix(run_dir: Path) -> list[str]:
    return [
        "sandbox-exec", "-f", str(PROFILE),
        "-D", f"RUN_DIR={run_dir.resolve()}",
        "-D", f"HOME={Path.home()}",
        "-D", f"REPO={REPO_ROOT}",
    ]


def sandbox_env(run_dir: Path) -> dict[str, str]:
    """Point temp dirs inside the run dir so tools that write to $TMPDIR stay allowed.

    Also drops an empty pytest.ini so pytest's rootdir search stops here instead of walking
    up into the (unreadable) repo.
    """
    tmp = run_dir.resolve() / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    (run_dir / "pytest.ini").write_text("[pytest]\n")
    return {"TMPDIR": str(tmp), "TMP": str(tmp), "TEMP": str(tmp)}


def wrap_shell(command: str, run_dir: Path) -> str:
    """Wrap a shell command string so it runs inside the sandbox."""
    return shlex.join([*sandbox_prefix(run_dir), "/bin/bash", "-c", command])


def available() -> bool:
    return os.path.exists("/usr/bin/sandbox-exec")
