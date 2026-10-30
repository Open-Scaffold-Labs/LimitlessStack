#!/usr/bin/env python3
"""Network-free tests: the refresh and `nlm` put themselves inside a managed NotebookLM session (2026-10-30).

No real credentials or CLI: a fake runner and a fake `notebooklm` record how they were called.
"""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
REFRESH = HERE / "notebooklm-wiki-refresh.py"
NLM = HERE / "nlm"

spec = importlib.util.spec_from_file_location("selfwrap_refresh", REFRESH)
rf = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = rf
spec.loader.exec_module(rf)

# Records its argv; answers --check-managed-env with FAKE_MANAGED_RC; otherwise exits FAKE_RC.
FAKE_RUNNER = r'''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"who": "runner", "argv": sys.argv[1:]}) + "\n")
if sys.argv[1:] == ["--check-managed-env"]:
    sys.exit(int(os.environ.get("FAKE_MANAGED_RC", "0")))
sys.exit(int(os.environ.get("FAKE_RC", "0")))
'''
FAKE_CLI = r'''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"who": "cli", "argv": sys.argv[1:]}) + "\n")
'''


def write_exec(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.agents = self.home / ".notebooklm-agents"
        (self.agents / "profiles" / "bootstrap").mkdir(parents=True)
        self.token = self.agents / "profiles" / "bootstrap" / "master_token.json"
        self.token.write_text("{}")
        self.runner = self.root / "fake-runner.py"
        write_exec(self.runner, FAKE_RUNNER)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        write_exec(self.bin / "notebooklm", FAKE_CLI)
        self.log = self.root / "log.jsonl"
        self.env = {"HOME": str(self.home), "PATH": f"{self.bin}:{os.environ['PATH']}",
                    "FAKE_LOG": str(self.log), "NOTEBOOKLM_AGENT_RUNNER": str(self.runner)}

    def tearDown(self):
        self.tmp.cleanup()

    def calls(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []


class RefreshDecision(Base):
    def test_restarts_inside_a_session_when_a_bootstrap_exists(self):
        cmd = rf.managed_command(["--only", "openfirehouse"], self.env)
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd[1], str(self.runner))
        self.assertEqual(cmd[cmd.index("--home") + 1], str(self.agents))
        self.assertEqual(cmd[cmd.index("--agent") + 1], "wiki-refresh")
        self.assertEqual(cmd[-3:], [str(REFRESH), "--only", "openfirehouse"], "the same script, the same arguments")

    def test_a_named_refresh_agent_is_honoured(self):
        cmd = rf.managed_command(["--only", "wiki"], {**self.env, "NOTEBOOKLM_REFRESH_AGENT_ID": "nightly-selfheal"})
        self.assertEqual(cmd[cmd.index("--agent") + 1], "nightly-selfheal")

    def test_filesystem_only_flags_never_take_a_session(self):
        for argv in (["--count-routed", "openfirehouse"], ["--count-routed=wiki"], ["--newest-routed", "x"], ["--help"], ["-h"]):
            self.assertIsNone(rf.managed_command(argv, self.env), argv)

    def test_already_inside_a_session_runs_here(self):
        self.assertIsNone(rf.managed_command(["--only", "wiki"], {**self.env, "NOTEBOOKLM_AGENT_ACTIVE": "agent-x"}))

    def test_no_bootstrap_yet_runs_here(self):
        self.token.unlink()
        self.assertIsNone(rf.managed_command(["--only", "wiki"], self.env))

    def test_inline_credentials_run_here(self):
        self.assertIsNone(rf.managed_command(["--only", "wiki"], {**self.env, "NOTEBOOKLM_AUTH_JSON": "{}"}))

    def test_an_invalid_session_is_refused(self):
        env = {**self.env, "NOTEBOOKLM_AGENT_ACTIVE": "agent-x", "FAKE_MANAGED_RC": "2"}
        self.assertIsNotNone(rf.managed_context_problem(env))
        self.assertIsNone(rf.managed_context_problem({**env, "FAKE_MANAGED_RC": "0"}))
        self.assertIsNone(rf.managed_context_problem(self.env), "outside a session there is nothing to check")


class RefreshEndToEnd(Base):
    def run_refresh(self, *argv, **extra):
        return subprocess.run([sys.executable, str(REFRESH), *argv], env={**self.env, **extra},
                              capture_output=True, text=True, timeout=60)

    def test_the_script_hands_itself_to_the_runner_and_returns_its_exit_code(self):
        r = self.run_refresh("--only", "openfirehouse", FAKE_RC="7")
        self.assertEqual(r.returncode, 7, r.stderr)
        runner_calls = [c for c in self.calls() if c["who"] == "runner"]
        self.assertEqual(len(runner_calls), 1)
        argv = runner_calls[0]["argv"]
        self.assertEqual(argv[argv.index("--agent") + 1], "wiki-refresh")
        self.assertEqual(argv[-3:], [str(REFRESH), "--only", "openfirehouse"])

    def test_an_invalid_session_stops_before_any_work(self):
        r = self.run_refresh("--only", "openfirehouse", NOTEBOOKLM_AGENT_ACTIVE="agent-x", FAKE_MANAGED_RC="2")
        self.assertEqual(r.returncode, 2)
        self.assertIn("invalid managed NotebookLM context", r.stderr)
        self.assertEqual([c["argv"] for c in self.calls()], [["--check-managed-env"]], "only the check ran")


class RealRunner(unittest.TestCase):
    """The real runner around the refresh's own check: the profile lock it hands down must reach the check
    (2026-10-30, live: a plain subprocess closed it and every self-wrapped refresh refused its own session)."""
    FAKE_CLI = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
s = Path(os.environ["NOTEBOOKLM_HOME"]) / "profiles" / os.environ["NOTEBOOKLM_PROFILE"] / "storage_state.json"
a = sys.argv[1:]
if a[:2] == ["auth", "check"]:
    print(json.dumps({"status": "ok" if s.exists() else "error", "checks": {"token_fetch": s.exists()}}))
    sys.exit(0 if s.exists() else 1)
if a[:2] == ["auth", "refresh"]:
    s.write_text("{}"); s.chmod(0o600); print(json.dumps({"status": "ok"})); sys.exit(0)
'''
    CHILD = ("import importlib.util, sys; "
             "spec = importlib.util.spec_from_file_location('r', sys.argv[1]); m = importlib.util.module_from_spec(spec); "
             "spec.loader.exec_module(m); print(repr(m.managed_context_problem()))")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name).resolve()
        self.home = root / "managed"
        seed = self.home / "profiles" / "bootstrap"
        seed.mkdir(parents=True)
        for p in (self.home, self.home / "profiles", seed):
            p.chmod(0o700)
        (seed / "master_token.json").write_text('{"master_token":"fake-for-test"}\n')
        (seed / "master_token.json").chmod(0o600)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        write_exec(bin_dir / "notebooklm", self.FAKE_CLI)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith("NOTEBOOKLM_") and k != "NLM_AGENT"}
        self.env["PATH"] = f"{bin_dir}:{os.environ['PATH']}"

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_check_inside_a_real_session_passes(self):
        r = subprocess.run([sys.executable, str(HERE / "notebooklm-agent.py"), "--home", str(self.home),
                            "--agent", "selfwrap-real", "--", sys.executable, "-c", self.CHILD, str(REFRESH)],
                           env=self.env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "None", "a genuine session passes its own check")

    def test_a_copied_marker_outside_the_runner_still_fails(self):
        env = {**self.env, "NOTEBOOKLM_HOME": str(self.home), "NOTEBOOKLM_PROFILE": "agent-x",
               "NOTEBOOKLM_AGENT_ACTIVE": "agent-x", "NOTEBOOKLM_AGENT_LOCK_FD": "9"}
        r = subprocess.run([sys.executable, "-c", self.CHILD, str(REFRESH)], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertIn("invalid managed NotebookLM context", r.stdout)


class Nlm(Base):
    def run_nlm(self, *argv, **extra):
        env = {**self.env, "NLM_RUNNER": str(self.runner), **extra}
        for k in ("NLM_AGENT", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "NOTEBOOKLM_AGENT_ACTIVE"):
            if k not in extra:
                env.pop(k, None)
        return subprocess.run(["bash", str(NLM), *argv], env=env, capture_output=True, text=True, timeout=60)

    def agent_of(self):
        argv = [c for c in self.calls() if c["who"] == "runner"][-1]["argv"]
        return argv[argv.index("--agent") + 1], argv

    def test_a_claude_session_gets_its_own_profile(self):
        self.assertEqual(self.run_nlm("list", "--json", CLAUDE_CODE_SESSION_ID="abc-123").returncode, 0)
        agent, argv = self.agent_of()
        self.assertEqual(agent, "claude-abc-123")
        self.assertEqual(argv[argv.index("--") + 1:], ["notebooklm", "list", "--json"])
        self.assertEqual(argv[argv.index("--home") + 1], str(self.agents))

    def test_nlm_agent_wins_then_codex_then_shared(self):
        self.run_nlm("list", NLM_AGENT="handoff-1", CLAUDE_CODE_SESSION_ID="abc")
        self.assertEqual(self.agent_of()[0], "handoff-1")
        self.run_nlm("list", CODEX_THREAD_ID="t9")
        self.assertEqual(self.agent_of()[0], "codex-t9")
        self.run_nlm("list")
        self.assertTrue(self.agent_of()[0].startswith("shared-"))

    def test_inside_a_session_it_is_the_plain_cli(self):
        self.assertEqual(self.run_nlm("ask", "-n", "9c8f", "q", NOTEBOOKLM_AGENT_ACTIVE="agent-x").returncode, 0)
        self.assertEqual(self.calls(), [{"who": "cli", "argv": ["ask", "-n", "9c8f", "q"]}], "no second runner")

    def test_the_runner_s_exit_code_comes_back(self):
        self.assertEqual(self.run_nlm("list", FAKE_RC="3").returncode, 3)


if __name__ == "__main__":
    unittest.main()
