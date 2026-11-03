import os
from pathlib import Path

import pytest

from lightness.verify.procs import StartError, running


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def test_server_killed_even_when_check_raises(tmp_path: Path):
    (tmp_path / "srv.py").write_text(
        "import http.server, sys\n"
        "http.server.HTTPServer(('127.0.0.1', int(sys.argv[1])), http.server.SimpleHTTPRequestHandler).serve_forever()\n")
    with pytest.raises(RuntimeError, match="check failed"):
        with running(["srv.py", "{port}"], tmp_path, run_dir=tmp_path) as srv:
            pid = srv.proc.pid
            assert srv.client.get("/").status_code == 200
            raise RuntimeError("check failed")
    assert not alive(pid)


def test_never_answering_server_times_out(tmp_path: Path):
    (tmp_path / "hang.py").write_text("import time\ntime.sleep(60)\n")
    with pytest.raises(StartError, match="did not answer"):
        with running(["hang.py", "{port}"], tmp_path, startup_timeout=2):
            pass
