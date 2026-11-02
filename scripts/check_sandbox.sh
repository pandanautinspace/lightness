#!/usr/bin/env bash
# Check the bench sandbox profile allows and blocks what it should. Run from the repo root.
set -u
R=$(mktemp -d "$PWD/runs/sbtest.XXXX"); printf "[pytest]\n" > $R/pytest.ini; P=src/lightness/bench/sandbox.sb
S=(sandbox-exec -f "$P" -D "RUN_DIR=$R" -D "HOME=$HOME" -D "REPO=$PWD")
chk(){ "${S[@]}" /bin/bash -c "$2" >/dev/null 2>&1 && echo "$1: ALLOWED" || echo "$1: blocked"; }
chk "write run dir      " "echo hi > $R/ok.txt"
chk "write repo         " "echo hi > $PWD/escape.txt"
chk "read run dir       " "cat $R/ok.txt"
chk "read task tests    " "cat $PWD/bench/tasks/file-organizer/tests/test_organize.py"
chk "read task solution " "ls $PWD/bench/tasks/file-organizer/solution"
chk "read other runs    " "ls $PWD/runs"
chk "read ~/Documents   " "ls $HOME/Documents"
chk "read ~/.ssh        " "ls $HOME/.ssh"
chk "external network   " "curl -s -m 5 https://example.com"
chk "localhost network  " "curl -s -m 5 127.0.0.1:8080/health"
chk "venv python+flask  " "cd $R && TMPDIR=$R $PWD/.venv/bin/python -c 'import flask, textual, httpx, sqlite3; import lightness.bench.testkit'"
chk "pytest runs        " "cd $R && printf 'def test_x():\n    assert 1\n' > test_a.py && TMPDIR=$R $PWD/.venv/bin/python -m pytest -q -p no:cacheprovider test_a.py"
chk "git in run dir     " "cd $R && git init -q x && cd x && git status"
chk "flask server bind  " "cd $R && (TMPDIR=$R $PWD/.venv/bin/python -c 'from flask import Flask; a=Flask(\"a\"); a.get(\"/\")(lambda: \"up\"); a.run(port=5799)' & p=\$!; sleep 3; curl -s 127.0.0.1:5799/ | grep -q up; r=\$?; kill \$p; exit \$r)"
rm -rf "$R"
