#!/usr/bin/env python3.11
"""Network-free tests for trust-anchor-check.py Check H — one shared rules file, linked into every checkout.

Added 2026-10-30 with `link_names`: OpenFirehouse's AGENTS.md (what Codex reads) was a hand copy that fell ~50
rulings behind CLAUDE.md before Matt ruled "Link it to CLAUDE.md". These tests build a real git repo with a real
worktree and a throwaway vault, so the check runs exactly as Roll Call runs it.
"""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class SharedRules(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name).resolve()
        self.vault = root / "vault"
        (self.vault / "tools").mkdir(parents=True)
        shutil.copy(HERE / "trust-anchor-check.py", self.vault / "tools" / "trust-anchor-check.py")
        self.repo = root / "repo"
        self.repo.mkdir()
        git("init", "-q", "-b", "main", cwd=self.repo)
        (self.repo / "README").write_text("x\n")
        git("add", "README", cwd=self.repo)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init", cwd=self.repo)
        self.wt = root / "wt"
        git("worktree", "add", "-q", str(self.wt), cwd=self.repo)
        self.canon = self.repo / "CLAUDE.md"
        self.canon.write_text("# rules\n")

    def tearDown(self):
        self.tmp.cleanup()

    def configure(self, link_names=None):
        entry = {"canonical": str(self.canon), "repo": str(self.repo), "extra_checkouts": []}
        if link_names is not None:
            entry["link_names"] = link_names
        (self.vault / ".limitless-project.py").write_text(f"SHARED_RULES_FILES = [{entry!r}]\n")

    def findings(self):
        spec = importlib.util.spec_from_file_location("ta_check", self.vault / "tools" / "trust-anchor-check.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.check_shared_rules()
        return [m for m, _ in mod.findings]

    def link(self, path, target=None):
        os.symlink(target or self.canon, path)

    def test_every_name_linked_everywhere_is_clean(self):
        self.configure(["CLAUDE.md", "AGENTS.md"])
        self.link(self.repo / "AGENTS.md")
        self.link(self.wt / "CLAUDE.md")
        self.link(self.wt / "AGENTS.md")
        self.assertEqual(self.findings(), [])

    def test_a_real_agents_file_in_the_home_checkout_is_a_copy(self):
        self.configure(["CLAUDE.md", "AGENTS.md"])
        (self.repo / "AGENTS.md").write_text("# an old hand copy\n")
        self.link(self.wt / "CLAUDE.md")
        self.link(self.wt / "AGENTS.md")
        found = self.findings()
        self.assertEqual(len(found), 1, found)
        self.assertIn(f"{self.repo / 'AGENTS.md'} is its own copy", found[0])

    def test_a_tool_rewriting_the_link_as_a_file_is_caught(self):
        self.configure(["CLAUDE.md", "AGENTS.md"])
        self.link(self.repo / "AGENTS.md")
        self.link(self.wt / "CLAUDE.md")
        (self.wt / "AGENTS.md").write_text("# rules\n")  # identical text, but a file: it will drift
        found = self.findings()
        self.assertEqual(len(found), 1, found)
        self.assertIn(f"{self.wt / 'AGENTS.md'} is its own copy", found[0])

    def test_a_missing_or_misdirected_agents_link_is_caught(self):
        self.configure(["CLAUDE.md", "AGENTS.md"])
        other = self.repo / "OTHER.md"
        other.write_text("x\n")
        self.link(self.repo / "AGENTS.md", other)
        self.link(self.wt / "CLAUDE.md")
        found = self.findings()
        self.assertTrue(any(f"{self.wt} has no AGENTS.md" in m for m in found), found)
        self.assertTrue(any(f"{self.repo / 'AGENTS.md'} links to {other}" in m for m in found), found)
        self.assertEqual(len(found), 2, found)

    def test_without_link_names_only_the_rules_file_is_checked_as_before(self):
        self.configure()
        (self.repo / "AGENTS.md").write_text("not checked\n")
        (self.wt / "AGENTS.md").write_text("not checked\n")
        self.assertEqual(self.findings(), [f"{self.wt} has no CLAUDE.md — a session that reads CLAUDE.md there gets none of the rules"])


if __name__ == "__main__":
    unittest.main()
