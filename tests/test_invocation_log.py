"""Invocation-log adoption tests (erg-tebapi).

accomplis vendors the estate invocation-log shim as src/accomplis/_invlog.py —
canonical copy and the cross-estate conformance test live in
spm1001/harness-ergonomics (shim/invocation_log.py, tests/test_conformance.py).
These tests pin the adoption facts locally: every invocation of BOTH console
scripts (accomplis, accomplis-flatten) appends exactly one caller-stamped JSONL
line — success and failure alike — and a broken log path never breaks the CLI.

All probes here are offline by construction (version, bare invocation,
argparse failures, --list-backups) so the suite never needs a Todoist token.
"""

import json
import os
import subprocess
import sys


def _run(module, *argv, env):
    return subprocess.run(
        [sys.executable, "-m", module, *argv],
        capture_output=True, text=True, env=env,
        stdin=subprocess.DEVNULL,
    )


def _env(tmp_path, **overrides):
    """Env with a hermetic log dir and a deterministic model caller stamp."""
    env = dict(os.environ)
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)
    env["XDG_DATA_HOME"] = str(tmp_path / "xdg")
    env.update(overrides)
    return env


def _log_lines(tmp_path, tool="accomplis"):
    log = tmp_path / "xdg" / tool / "invocations.jsonl"
    assert log.exists(), f"no invocation log at {log}"
    return [json.loads(l) for l in log.read_text().splitlines() if l.strip()]


class TestInvocationLog:
    def test_ok_invocation_logs_one_line(self, tmp_path):
        env = _env(tmp_path, CLAUDECODE="1", CLAUDE_CODE_ENTRYPOINT="cli")
        result = _run("accomplis.cli", "version", env=env)
        assert result.returncode == 0, result.stderr
        (line,) = _log_lines(tmp_path)
        assert line["tool"] == "accomplis"
        assert line["subcommand"] == "version"
        assert line["argv"] == ["version"]
        assert line["parsed"]["command"] == "version"
        assert line["outcome"] == "ok" and line["exit_code"] == 0
        assert line["caller"] == "model" and line["caller_detail"] == "cli"
        assert line["duration_ms"] >= 0
        assert line["version"]  # whatever the CLI reports, non-empty

    def test_no_command_error_logged_with_parsed_args(self, tmp_path):
        """Bare `accomplis` prints help and exits 1 — post-parse, so parsed
        is present with command=None."""
        env = _env(tmp_path, CLAUDECODE="1", CLAUDE_CODE_ENTRYPOINT="cli")
        result = _run("accomplis.cli", env=env)
        assert result.returncode == 1
        (line,) = _log_lines(tmp_path)
        assert line["outcome"] == "error" and line["exit_code"] == 1
        assert line["subcommand"] is None
        assert line["parsed"] is not None and line["parsed"]["command"] is None

    def test_misinvocation_dies_in_argparse_still_logged(self, tmp_path):
        """An invented subcommand never reaches post-parse — raw argv is the
        evidence."""
        env = _env(tmp_path, CLAUDECODE="1")
        result = _run("accomplis.cli", "definitely-not-a-command", env=env)
        assert result.returncode == 2
        (line,) = _log_lines(tmp_path)
        assert line["outcome"] == "error" and line["exit_code"] == 2
        assert line["argv"] == ["definitely-not-a-command"]
        assert line["subcommand"] is None and line["parsed"] is None

    def test_robot_stamp_without_cc_env_or_tty(self, tmp_path):
        env = _env(tmp_path)  # no CC env; stdin/stdout/stderr are pipes
        result = _run("accomplis.cli", "version", env=env)
        assert result.returncode == 0
        (line,) = _log_lines(tmp_path)
        assert line["caller"] == "robot"
        assert line["caller_detail"]  # parent process name, non-empty

    def test_unwritable_log_path_never_breaks_cli(self, tmp_path):
        blocker = tmp_path / "xdg"
        blocker.write_text("occupied")  # a file where the data dir should be
        env = dict(os.environ, XDG_DATA_HOME=str(blocker), CLAUDECODE="1")
        result = _run("accomplis.cli", "version", env=env)
        assert result.returncode == 0, result.stderr
        assert "Traceback" not in result.stderr


class TestFlattenInvocationLog:
    """accomplis-flatten is a second console script in this package — it logs
    under its own tool name so per-binary denominators stay clean."""

    def test_ok_invocation_logs_with_derived_mode(self, tmp_path):
        env = _env(tmp_path, CLAUDECODE="1", CLAUDE_CODE_ENTRYPOINT="cli",
                   HOME=str(tmp_path / "home"))  # no real backups dir: still ok
        result = _run("accomplis.flatten", "--list-backups", env=env)
        assert result.returncode == 0, result.stderr
        (line,) = _log_lines(tmp_path, tool="accomplis-flatten")
        assert line["tool"] == "accomplis-flatten"
        assert line["subcommand"] == "list-backups"
        assert line["outcome"] == "ok" and line["exit_code"] == 0
        assert line["caller"] == "model" and line["caller_detail"] == "cli"

    def test_no_project_error_logged(self, tmp_path):
        env = _env(tmp_path, CLAUDECODE="1")
        result = _run("accomplis.flatten", env=env)
        assert result.returncode == 1
        (line,) = _log_lines(tmp_path, tool="accomplis-flatten")
        assert line["outcome"] == "error" and line["exit_code"] == 1
        assert line["subcommand"] == "flatten"  # the mode dispatch would take
