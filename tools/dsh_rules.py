#!/usr/bin/env python3
"""Генератор always-on правил для DeepSeek Harness + RuleBase.

RuleBase читает только плоские *.md и НЕ следует симлинкам, поэтому правила
для DSH нельзя установить ссылками. Этот модуль вырезает frontmatter/backmatter
из framework/rules/<id>/SKILL.md и пишет реальные файлы .dsh/rules/fw-*.md.

Использование:
  python tools/dsh_rules.py render --project-dir .
  python tools/dsh_rules.py check  --project-dir .
  python tools/dsh_rules.py clean  --project-dir .

Модуль не зависит от install.py и может использоваться в CI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)
BACKMATTER_KEYS = ("depends_on", "requires", "metadata", "category", "version")
TECHNICAL_KEYS = {"depends_on", "requires", "metadata", "category", "version"}
MAX_TOTAL_BYTES = 256 * 1024
WARN_TOTAL_BYTES = 200 * 1024
FAIL_TOTAL_BYTES = 240 * 1024


@dataclass
class RuleSource:
    id: str
    name: str
    description: str
    always_apply: bool
    source_file: Path
    source_label: str
    body: str
    sha256: str

    @property
    def display_title(self) -> str:
        return self.name or self.id


def _simple_yaml_values(block: str) -> dict:
    """Плоский разбор frontmatter: name/description/alwaysApply."""
    data: dict[str, str] = {}
    current_key: Optional[str] = None
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" in stripped and not stripped.startswith("-"):
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            data[key] = value
            current_key = key
        elif stripped.startswith("- ") and current_key:
            data[current_key] = (data.get(current_key, "") + " " + stripped[2:].strip()).strip()
    return data


def _strip_terminal_backmatter(body: str) -> str:
    """Удаляет хвостовой технический ---блок--- (depends_on/requires/...)."""
    lines = body.rstrip().splitlines()
    if not lines or lines[-1].strip() != "---":
        return body
    closing = len(lines) - 1
    opening = None
    for idx in range(closing - 1, -1, -1):
        if lines[idx].strip() == "---":
            opening = idx
            break
    if opening is None:
        return body
    block = "\n".join(lines[opening + 1:closing])
    if not any(re.match(rf"^\s*{re.escape(key)}\s*:", block, re.M) for key in BACKMATTER_KEYS):
        return body
    return "\n".join(lines[:opening]).rstrip() + "\n"


def _ensure_h1(body: str, title: str) -> str:
    stripped = body.lstrip("\ufeff \t\r\n")
    if re.match(r"^#\s+\S", stripped):
        return stripped
    return f"# {title}\n\n{stripped}"


def read_rule_file(path: Path, source_label: str, rule_id: Optional[str] = None) -> Optional[RuleSource]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None
    fm = _simple_yaml_values(match.group(1))
    name = (fm.get("name") or "").strip().strip("'\"")
    description = (fm.get("description") or "").strip().strip("'\"")
    if not name:
        return None
    body = text[match.end():]
    body = _strip_terminal_backmatter(body)
    body = _ensure_h1(body, name)
    body = body.strip() + "\n"
    rid = rule_id or path.parent.name
    return RuleSource(
        id=rid,
        name=name,
        description=description,
        always_apply=str(fm.get("alwaysApply", "")).strip().lower() == "true",
        source_file=path,
        source_label=source_label,
        body=body,
        sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
    )


def _source_label(base: Path, source: Path) -> str:
    """Портируемая метка источника: framework/... или framework_eng/..."""
    try:
        rel = source.relative_to(base)
    except ValueError:
        return source.name
    prefix = "framework_eng" if base.name == "framework_eng" else "framework"
    return f"{prefix}/{rel.as_posix()}"


def discover_rules(
    framework_dir: Path,
    mirror_dir: Optional[Path] = None,
    lang: str = "en",
) -> list[RuleSource]:
    """Возвращает все правила из EN-зеркала (или RU) с alwaysApply-флагом."""
    base = framework_dir
    if lang != "ru" and mirror_dir and mirror_dir.is_dir():
        base = mirror_dir
    rules_dir = base / "rules"
    if not rules_dir.is_dir():
        return []
    result: list[RuleSource] = []
    for path in sorted(rules_dir.glob("*/SKILL.md")):
        rule = read_rule_file(path, _source_label(base, path), path.parent.name)
        if rule:
            result.append(rule)
    return result


def _lite_ids() -> set[str]:
    config = Path(__file__).resolve().parent / "dsh-rules.json"
    if not config.exists():
        return set()
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    return set(data.get("lite", []))


def select_rules(
    rules: Iterable[RuleSource],
    selected_ids: Optional[set[str]] = None,
    profile: str = "parity",
) -> list[RuleSource]:
    """Фильтрует always-on и явно выбранные правила.

    selected_ids — comp_id вида ``rule/<id>``; None = все always-on.
    profile=lite дополнительно ограничивает набор tools/dsh-rules.json.
    """
    selected_short: Optional[set[str]] = None
    if selected_ids is not None:
        selected_short = {cid.split("/", 1)[1] for cid in selected_ids if cid.startswith("rule/")}
    lite = _lite_ids() if profile == "lite" else None
    chosen = []
    for rule in rules:
        if not rule.always_apply:
            continue
        if selected_short is not None and rule.id not in selected_short:
            continue
        if lite is not None and rule.id not in lite:
            continue
        chosen.append(rule)
    chosen.sort(key=lambda r: (0 if r.id == "framework-bootstrap" else 1, r.id))
    return chosen


def _file_name(order_index: int, rule_id: str) -> str:
    if rule_id == "framework-bootstrap":
        return f"fw-000-{rule_id}.md"
    return f"fw-{order_index:03d}-{rule_id}.md"


def _ordered_rules(rules: Iterable[RuleSource]) -> list[tuple[RuleSource, str]]:
    """Детерминированный порядок и имена: bootstrap 000, остальные 101+."""
    ordered: list[tuple[RuleSource, str]] = []
    bootstrap = next((r for r in rules if r.id == "framework-bootstrap"), None)
    if bootstrap:
        ordered.append((bootstrap, _file_name(0, bootstrap.id)))
    rest = sorted((r for r in rules if r.id != "framework-bootstrap"), key=lambda r: r.id)
    for idx, rule in enumerate(rest, start=1):
        ordered.append((rule, _file_name(100 + idx, rule.id)))
    return ordered


def render_rules(
    project_dir: Path,
    framework_dir: Path,
    mirror_dir: Optional[Path] = None,
    selected_ids: Optional[set[str]] = None,
    profile: str = "parity",
    lang: str = "en",
) -> dict:
    """Пишет .dsh/rules/fw-*.md и возвращает фрагмент манифеста."""
    rules = select_rules(discover_rules(framework_dir, mirror_dir, lang), selected_ids, profile)
    rules_dir = project_dir / ".dsh" / "rules"
    if not rules:
        if rules_dir.is_dir():
            for old in rules_dir.glob("fw-*.md"):
                old.unlink()
        return {"rules": [], "total_bytes": 0, "profile": profile, "lang": lang}
    rules_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    total_bytes = 0
    for rule, file_name in _ordered_rules(rules):
        target = rules_dir / file_name
        target.write_text(rule.body, encoding="utf-8")
        size = len(rule.body.encode("utf-8"))
        total_bytes += size
        manifest.append({
            "id": rule.id,
            "file": file_name,
            "source": rule.source_label,
            "sha256": rule.sha256,
            "bytes": size,
        })

    # Удаляем только свои fw-*.md, которых нет в новом наборе.
    keep = {item["file"] for item in manifest}
    for old in rules_dir.glob("fw-*.md"):
        if old.name not in keep:
            old.unlink()

    if total_bytes > FAIL_TOTAL_BYTES:
        raise ValueError(
            f"DSH rules exceed safe limit: {total_bytes} bytes > {FAIL_TOTAL_BYTES} "
            f"({MAX_TOTAL_BYTES} hard RuleBase limit)"
        )
    return {
        "rules": manifest,
        "total_bytes": total_bytes,
        "profile": profile,
        "lang": "en" if lang != "ru" and mirror_dir and mirror_dir.is_dir() else "ru",
    }


def _manifest_rules(project_dir: Path) -> list[dict]:
    path = project_dir / ".dsh" / "manifest.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return list((data.get("dsh") or {}).get("rules") or [])


def check_rules(
    project_dir: Path,
    framework_dir: Path,
    mirror_dir: Optional[Path] = None,
    profile: str = "parity",
    lang: str = "en",
) -> tuple[bool, list[str]]:
    """Сверяет закоммиченные fw-*.md с текущим framework_eng/rules."""
    errors: list[str] = []
    manifest_path = project_dir / ".dsh" / "manifest.json"
    manifest_rules = _manifest_rules(project_dir)
    if manifest_path.exists():
        selected = {f"rule/{item.get('id')}" for item in manifest_rules if item.get("id")}
    else:
        selected = None
    expected = select_rules(discover_rules(framework_dir, mirror_dir, lang), selected, profile)
    expected_by_file = {file_name: rule for rule, file_name in _ordered_rules(expected)}
    rules_dir = project_dir / ".dsh" / "rules"
    actual_files = {p.name for p in rules_dir.glob("fw-*.md")} if rules_dir.is_dir() else set()
    missing = sorted(set(expected_by_file) - actual_files)
    extra = sorted(actual_files - set(expected_by_file))
    if missing:
        errors.append(f"missing generated rules: {', '.join(missing)}")
    if extra:
        errors.append(f"stale generated rules: {', '.join(extra)}")
    for file_name, rule in expected_by_file.items():
        path = rules_dir / file_name
        if not path.exists():
            continue
        try:
            actual = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"{file_name}: read failed: {exc}")
            continue
        if actual != rule.body:
            errors.append(f"{file_name}: content differs from {rule.source_label}")
    return (not errors), errors


def clean_rules(project_dir: Path, keep_manifest: bool = False) -> int:
    rules_dir = project_dir / ".dsh" / "rules"
    removed = 0
    if rules_dir.is_dir():
        for path in rules_dir.glob("fw-*.md"):
            path.unlink()
            removed += 1
    if not keep_manifest:
        manifest = project_dir / ".dsh" / "manifest.json"
        if manifest.exists():
            manifest.unlink()
    return removed


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="DSH RuleBase rules generator")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--project-dir", type=Path, default=Path("."))
        p.add_argument("--framework-dir", type=Path, default=Path("framework"))
        p.add_argument("--mirror-dir", type=Path, default=Path("framework_eng"))
        p.add_argument("--profile", choices=("parity", "lite"), default="parity")
        p.add_argument("--lang", choices=("en", "ru"), default="en")
        p.add_argument("--include", nargs="*", default=None, help="comp_id list, e.g. rule/framework-bootstrap")

    p_render = sub.add_parser("render")
    add_common(p_render)
    p_check = sub.add_parser("check")
    add_common(p_check)
    p_clean = sub.add_parser("clean")
    p_clean.add_argument("--project-dir", type=Path, default=Path("."))
    p_clean.add_argument("--keep-manifest", action="store_true")

    args = parser.parse_args(argv)
    project_dir = args.project_dir.resolve()
    if args.command == "clean":
        removed = clean_rules(project_dir, keep_manifest=args.keep_manifest)
        print(f"removed {removed} generated rule file(s)")
        return 0

    framework_dir = args.framework_dir.resolve()
    mirror_dir = args.mirror_dir.resolve() if args.mirror_dir else None
    selected = set(args.include) if args.include else None
    if args.command == "render":
        data = render_rules(project_dir, framework_dir, mirror_dir, selected, args.profile, args.lang)
        print(
            f"rendered {len(data['rules'])} rule(s), {data['total_bytes']} bytes, "
            f"profile={data['profile']}, lang={data['lang']}"
        )
        if data["total_bytes"] > WARN_TOTAL_BYTES:
            print(f"warning: rules exceed {WARN_TOTAL_BYTES} bytes; RuleBase limit is {MAX_TOTAL_BYTES}", file=sys.stderr)
        return 0

    ok, errors = check_rules(project_dir, framework_dir, mirror_dir, args.profile, args.lang)
    for err in errors:
        print(err, file=sys.stderr)
    print("OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
