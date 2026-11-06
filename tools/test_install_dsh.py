#!/usr/bin/env python3
"""Тесты DSH-интеграции: скан компонентов, правила, пресеты, установка."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import dsh_presets  # noqa: E402
import dsh_rules  # noqa: E402
import install  # noqa: E402

FRAMEWORK = ROOT / "framework"
MIRROR = ROOT / "framework_eng"


class DshIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.gettempdir()) / f"dsh-test-{uuid.uuid4().hex}"
        self.tmp.mkdir()
        (self.tmp / ".git").mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_component_scan_excludes_reference_files(self) -> None:
        graph = install.FrameworkGraph(FRAMEWORK, MIRROR)
        self.assertNotIn("skill/analyst", graph.components)
        self.assertNotIn("skill/architect", graph.components)
        self.assertNotIn("skill/reviewer", graph.components)
        self.assertIn("skill/quick-fix", graph.components)
        self.assertEqual(len(graph.components), 160)

    def test_skill_names_are_kebab_case(self) -> None:
        graph = install.FrameworkGraph(FRAMEWORK, MIRROR)
        pattern = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
        for comp_id, comp in graph.components.items():
            if comp.type != "skill":
                continue
            fm = install.parse_frontmatter(comp.filepath) or {}
            name = str(fm.get("name") or "").strip("'\"")
            self.assertRegex(name, pattern, f"{comp_id} has invalid DSH name")

    def test_rules_render_and_check(self) -> None:
        data = dsh_rules.render_rules(self.tmp, FRAMEWORK, MIRROR, None, "parity", "en")
        self.assertEqual(len(data["rules"]), 41)
        rules = sorted((self.tmp / ".dsh" / "rules").glob("fw-*.md"))
        self.assertTrue(rules)
        body = rules[0].read_text(encoding="utf-8")
        self.assertTrue(body.startswith("# "))
        self.assertFalse(body.startswith("---"))
        self.assertNotIn("\ndepends_on:", body)
        ok, errors = dsh_rules.check_rules(self.tmp, FRAMEWORK, MIRROR, "parity", "en")
        self.assertTrue(ok, errors)
        rules[0].write_text(body + "\nchanged\n", encoding="utf-8")
        ok, errors = dsh_rules.check_rules(self.tmp, FRAMEWORK, MIRROR, "parity", "en")
        self.assertFalse(ok)

    def test_presets_render(self) -> None:
        data = dsh_presets.render_presets(self.tmp, FRAMEWORK, MIRROR, "en")
        patch = self.tmp / ".dsh" / "presets.patch.yml"
        self.assertTrue(patch.exists())
        text = patch.read_text(encoding="utf-8")
        self.assertIn("id: 1c-lead", text)
        self.assertNotIn("{{", text)
        for role in dsh_presets.ROLES:
            self.assertIn(f"id: 1c-{role}", text)
        self.assertIn("allowedAgentPresets", text)
        self.assertEqual(len(data["roles"]), len(dsh_presets.ROLES))
        self.assertTrue((self.tmp / "dsh-1c.sh").exists())
        self.assertTrue((self.tmp / "dsh-1c.ps1").exists())

    def test_install_check_uninstall_and_gitignore(self) -> None:
        graph = install.FrameworkGraph(FRAMEWORK, MIRROR)
        installed, skipped, removed = install.install_dsh_components(
            graph,
            {"rule/coding-standards", "skill/coding-standards"},
            set(),
            self.tmp,
            force_copy=True,
            options={"profile": "parity", "lang": "en", "presets": True},
        )
        self.assertGreater(installed, 0)
        self.assertEqual(removed, 0)
        self.assertTrue((self.tmp / ".dsh" / "skills" / "coding-standards" / "SKILL.md").exists())
        self.assertTrue(list((self.tmp / ".dsh" / "rules").glob("fw-*.md")))
        self.assertTrue((self.tmp / "AGENTS.md").exists())
        manifest = json.loads((self.tmp / ".dsh" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["dsh"]["profile"], "parity")
        self.assertTrue(manifest["dsh"]["rules"])
        self.assertIn("1c-lead", (self.tmp / ".dsh" / "presets.patch.yml").read_text(encoding="utf-8"))

        ok, errors = dsh_rules.check_rules(self.tmp, FRAMEWORK, MIRROR, "parity", "en")
        self.assertTrue(ok, errors)
        self.assertEqual(install.check_dsh(graph, self.tmp), 0)

        # gitignore: links/local ignored, committed artifacts not ignored
        subprocess.run(["git", "init", "-q"], cwd=self.tmp, check=True)
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", ".dsh/skills/coding-standards"],
            cwd=self.tmp,
            check=False,
        )
        self.assertEqual(ignored.returncode, 0)
        committed = subprocess.run(
            ["git", "check-ignore", "-q", f".dsh/rules/{next((self.tmp / '.dsh' / 'rules').glob('fw-*.md')).name}"],
            cwd=self.tmp,
            check=False,
        )
        self.assertNotEqual(committed.returncode, 0)
        for path in (".dsh/manifest.json", ".dsh/presets.patch.yml"):
            result = subprocess.run(
                ["git", "check-ignore", "-q", path],
                cwd=self.tmp,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0, f"{path} must be committed, not ignored")

        # uninstall preserves user rule
        user_rule = self.tmp / ".dsh" / "rules" / "team-rules.md"
        user_rule.write_text("# Team rules\n", encoding="utf-8")
        install.install_dsh_components(
            graph,
            {"rule/coding-standards", "skill/coding-standards"},
            {"rule/coding-standards", "skill/coding-standards"},
            self.tmp,
            force_copy=True,
            options={"profile": "parity", "lang": "en", "presets": False},
        )
        user_rule.write_text("# Team rules\n", encoding="utf-8")
        install.uninstall_dsh(graph, self.tmp)
        self.assertTrue(user_rule.exists())
        self.assertFalse(list((self.tmp / ".dsh" / "rules").glob("fw-*.md")))

    def test_agents_block_is_idempotent(self) -> None:
        install._write_dsh_agents(self.tmp)
        install._write_dsh_agents(self.tmp)
        text = (self.tmp / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(text.count(install.DSH_AGENTS_BEGIN), 1)
        self.assertEqual(text.count(install.DSH_AGENTS_END), 1)

    def test_agents_block_preserves_user_content(self) -> None:
        path = self.tmp / "AGENTS.md"
        path.write_text("# User instructions\n", encoding="utf-8")
        install._write_dsh_agents(self.tmp)
        self.assertIn("# User instructions", path.read_text(encoding="utf-8"))
        install._write_dsh_agents(self.tmp, enabled=False)
        text = path.read_text(encoding="utf-8")
        self.assertIn("# User instructions", text)
        self.assertNotIn(install.DSH_AGENTS_BEGIN, text)

    def test_lite_profile_renders_34_rules(self) -> None:
        data = dsh_rules.render_rules(self.tmp, FRAMEWORK, MIRROR, None, "lite", "en")
        self.assertEqual(len(data["rules"]), 34)
        self.assertLess(data["total_bytes"], 35 * 1024)
        ok, errors = dsh_rules.check_rules(self.tmp, FRAMEWORK, MIRROR, "lite", "en")
        self.assertTrue(ok, errors)

    def test_check_detects_missing_installed_target(self) -> None:
        graph = install.FrameworkGraph(FRAMEWORK, MIRROR)
        install.install_dsh_components(
            graph,
            {"rule/coding-standards", "skill/coding-standards"},
            set(),
            self.tmp,
            force_copy=True,
            options={"profile": "parity", "lang": "en", "presets": True},
        )
        shutil.rmtree(self.tmp / ".dsh" / "skills" / "coding-standards")
        self.assertEqual(install.check_dsh(graph, self.tmp), 1)

    def test_uninstall_without_manifest_removes_links(self) -> None:
        graph = install.FrameworkGraph(FRAMEWORK, MIRROR)
        install.install_dsh_components(
            graph,
            {"skill/coding-standards"},
            set(),
            self.tmp,
            force_copy=True,
            options={"profile": "parity", "lang": "en", "presets": False},
        )
        (self.tmp / ".dsh" / "manifest.json").unlink()
        install.uninstall_dsh(graph, self.tmp)
        self.assertFalse((self.tmp / ".dsh" / "skills").exists())

    def test_directory_link_helper(self) -> None:
        source = self.tmp / "source-skill"
        source.mkdir()
        (source / "SKILL.md").write_text("# x\n", encoding="utf-8")
        target = self.tmp / "linked-skill"
        mode = install._create_dir_link(source, target, force_copy=False)
        self.assertIn(mode, ("symlink", "junction"))
        self.assertTrue((target / "SKILL.md").exists())
        install._remove_dsh_path(target)


if __name__ == "__main__":
    unittest.main(verbosity=2)
