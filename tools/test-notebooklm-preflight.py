#!/usr/bin/env python3
"""Offline tests of the real preflight routing block with fake NotebookLM auth."""
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parent
FAKE = runpy.run_path(str(TOOLS / "test-notebooklm-agent.py"))["FAKE"]
SOURCE = (TOOLS / "limitless-preflight.sh").read_text()
START = "# ── Managed NotebookLM routing"
END = "# ── End managed NotebookLM routing"
ROUTING = SOURCE[SOURCE.index(START):SOURCE.index(END)]


class PreflightRouting(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "managed"
        self.tools = self.root / "vault/tools"
        self.tools.mkdir(parents=True)
        self.runner = self.tools / "notebooklm-agent.py"
        shutil.copyfile(TOOLS / "notebooklm-agent.py", self.runner)
        self.cli = self.root / "notebooklm"
        self.cli.write_text(FAKE)
        self.cli.chmod(0o700)
        self.script = self.tools / "limitless-preflight.sh"
        self.script.write_text(
            '#!/bin/bash\nset -u\nPREFLIGHT_ORIGINAL_ARGS=("$@")\n'
            'PREFLIGHT_SCRIPT="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"\n'
            'VAULT="$(cd "$(dirname "$0")/.." && pwd)"\n'
            'PREFLIGHT_COMPLETED=false\n'
            'network_probe() { [ "${FAKE_NETWORK_DOWN:-0}" = 0 ]; }\n'
            'network_abort() { exit 3; }\n' + ROUTING +
            '\npython3 - "$@" <<\'REPORT\'\n'
            'import json,os,sys\n'
            'print(json.dumps({"profile":os.getenv("NOTEBOOKLM_PROFILE"),'
            '"home":os.getenv("NOTEBOOKLM_HOME"),"args":sys.argv[1:]}))\n'
            'REPORT\nexit "${FIXTURE_EXIT:-0}"\n')
        self.env = os.environ.copy()
        for key in ("NOTEBOOKLM_AUTH_JSON", "NOTEBOOKLM_AGENT_ACTIVE", "NOTEBOOKLM_AGENT_LOCK_FD",
                    "NOTEBOOKLM_PREFLIGHT_AGENT_ID", "NOTEBOOKLM_HOME", "NOTEBOOKLM_PROFILE",
                    "FAKE_AUTH_FAIL", "FAKE_EXPIRE", "FAKE_NETWORK_DOWN", "FIXTURE_EXIT"):
            self.env.pop(key, None)
        self.env.update(HOME=str(self.root), NOTEBOOKLM_AGENT_HOME=str(self.home),
                        PATH=str(self.root) + os.pathsep + self.env["PATH"])

    def tearDown(self):
        self.temp.cleanup()

    def bootstrap(self):
        profile = self.home / "profiles/bootstrap"
        profile.mkdir(parents=True, mode=0o700)
        for path in (self.home, self.home / "profiles", profile):
            path.chmod(0o700)
        seed = profile / "master_token.json"
        seed.write_text('{"master_token":"fake-offline-token"}')
        seed.chmod(0o600)
        return seed

    def run_preflight(self, args=(), env=None):
        return subprocess.run(["bash", str(self.script), *args], env=env or self.env,
                              capture_output=True, text=True, timeout=10)

    def profiles(self):
        return [p.name for p in (self.home / "profiles").iterdir() if p.name != "bootstrap"]

    def test_no_bootstrap_preserves_existing_diagnostics_context(self):
        result = self.run_preflight(env=self.env | {"NOTEBOOKLM_HOME": "/legacy", "NOTEBOOKLM_PROFILE": "default"})
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual((data["home"], data["profile"]), ("/legacy", "default"))
        self.assertFalse(self.home.exists())

    def test_bootstrap_routes_once_and_reuses_stable_role(self):
        self.bootstrap()
        first = self.run_preflight()
        self.assertEqual(first.returncode, 0, first.stderr)
        profile = json.loads(first.stdout)["profile"]
        self.assertTrue(profile.startswith("agent-system-roll-call-"))
        second = self.run_preflight(["--findings-out=/example path/result.json"])
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout)["args"], ["--findings-out=/example path/result.json"])
        self.assertEqual(json.loads(second.stdout)["profile"], profile)
        self.assertEqual(len(self.profiles()), 1)

    def test_relative_invocation_keeps_absolute_reentry_path(self):
        self.bootstrap()
        result = subprocess.run(["bash", self.script.name], cwd=self.tools, env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["profile"].startswith("agent-system-roll-call-"))

    def test_explicit_role_and_child_exit_are_preserved(self):
        self.bootstrap()
        result = self.run_preflight(env=self.env | {"NOTEBOOKLM_PREFLIGHT_AGENT_ID": "role-two", "FIXTURE_EXIT": "1"})
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertTrue(json.loads(result.stdout)["profile"].startswith("agent-role-two-"))

    def test_already_managed_child_reuses_inherited_lock_and_profile(self):
        self.bootstrap()
        result = subprocess.run([sys.executable, str(self.runner), "--home", str(self.home),
                                 "--agent", "existing-task", "--", "bash", str(self.script)],
                                env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["profile"].startswith("agent-existing-task-"))
        self.assertEqual(len(self.profiles()), 1)

    def test_forged_marker_does_not_bypass_auth(self):
        self.bootstrap()
        result = self.run_preflight(env=self.env | {"NOTEBOOKLM_AGENT_ACTIVE": "fake", "NOTEBOOKLM_PROFILE": "fake"})
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid managed", result.stderr)
        self.assertEqual(self.profiles(), [])

    def test_auth_failure_and_unsafe_bootstrap_fail_closed(self):
        seed = self.bootstrap()
        result = self.run_preflight(env=self.env | {"FAKE_AUTH_FAIL": "1"})
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("DO-NOT-LEAK-SECRET", result.stderr)
        seed.chmod(0o644)
        result = self.run_preflight()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")

    def test_offline_gate_runs_before_auth(self):
        self.bootstrap()
        result = self.run_preflight(env=self.env | {"FAKE_NETWORK_DOWN": "1"})
        self.assertEqual(result.returncode, 3)
        self.assertEqual(self.profiles(), [])
        self.assertFalse((self.home / "locks").exists())

    def test_installer_deploys_runner_and_both_fences(self):
        installer = (TOOLS.parent / "install.sh").read_text()
        for name in ("notebooklm-agent.py", "test-notebooklm-agent.py", "test-notebooklm-preflight.py"):
            self.assertIn('cp "$SCRIPT_DIR/tools/' + name + '" "$TARGET/tools/' + name + '"', installer)


if __name__ == "__main__":
    unittest.main(verbosity=2)
