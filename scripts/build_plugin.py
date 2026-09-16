#!/usr/bin/env python3
"""ساخت و اعتبارسنجی بسته قابل انتشار «لحن من»."""

from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".codex-plugin" / "plugin.json"
DIST = ROOT / "dist"
SKILL_ROOT = ROOT / "skills" / "lahne-man"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ساخت بسته افزونه لحن من")
    parser.add_argument("--check", action="store_true", help="فقط اعتبارسنجی؛ خروجی نهایی نگه داشته نشود")
    return parser.parse_args()


def validate_source(manifest: dict) -> None:
    required = ("name", "version", "description", "author", "skills", "interface")
    missing = [key for key in required if not manifest.get(key)]
    if missing:
        raise SystemExit(f"فیلدهای ضروری manifest ناقص‌اند: {', '.join(missing)}")

    if manifest["name"] != "lahne-man":
        raise SystemExit("نام فنی افزونه باید lahne-man باشد")

    interface = manifest["interface"]
    interface_required = (
        "displayName",
        "shortDescription",
        "longDescription",
        "developerName",
        "category",
        "capabilities",
        "defaultPrompt",
    )
    missing_interface = [key for key in interface_required if not interface.get(key)]
    if missing_interface:
        raise SystemExit(f"فیلدهای رابط ناقص‌اند: {', '.join(missing_interface)}")

    prompts = interface["defaultPrompt"]
    if len(prompts) > 3 or any(len(prompt) > 128 for prompt in prompts):
        raise SystemExit("حداکثر سه Prompt آغازین و هرکدام حداکثر ۱۲۸ نویسه مجاز است")

    for source in (
        SKILL_ROOT / "SKILL.md",
        SKILL_ROOT / "eval.md",
        SKILL_ROOT / "agents" / "openai.yaml",
        ROOT / "agents" / "openai.yaml",
        ROOT / "assets" / "lahne-man.png",
        ROOT / "README.md",
        ROOT / "docs" / "USAGE.md",
        ROOT / "docs" / "EXAMPLES.md",
        ROOT / "LICENSE",
        ROOT / "NOTICE.md",
        ROOT / "PRIVACY.md",
        ROOT / "TERMS.md",
    ):
        if not source.is_file():
            raise SystemExit(f"فایل لازم پیدا نشد: {source.relative_to(ROOT)}")


def build_plugin(manifest: dict) -> tuple[Path, Path]:
    DIST.mkdir(exist_ok=True)
    plugin_root = DIST / "lahne-man"
    if plugin_root.exists():
        shutil.rmtree(plugin_root)

    skill_root = plugin_root / "skills" / "lahne-man"
    (plugin_root / ".codex-plugin").mkdir(parents=True)
    (plugin_root / "assets").mkdir(parents=True)
    (plugin_root / "agents").mkdir(parents=True)
    (plugin_root / "docs").mkdir(parents=True)
    (skill_root / "agents").mkdir(parents=True)

    copies = {
        MANIFEST: plugin_root / ".codex-plugin" / "plugin.json",
        SKILL_ROOT / "SKILL.md": skill_root / "SKILL.md",
        SKILL_ROOT / "eval.md": skill_root / "eval.md",
        SKILL_ROOT / "agents" / "openai.yaml": skill_root / "agents" / "openai.yaml",
        ROOT / "agents" / "openai.yaml": plugin_root / "agents" / "openai.yaml",
        ROOT / "assets" / "lahne-man.png": plugin_root / "assets" / "lahne-man.png",
        ROOT / "README.md": plugin_root / "README.md",
        ROOT / "docs" / "USAGE.md": plugin_root / "docs" / "USAGE.md",
        ROOT / "docs" / "EXAMPLES.md": plugin_root / "docs" / "EXAMPLES.md",
        ROOT / "LICENSE": plugin_root / "LICENSE",
        ROOT / "NOTICE.md": plugin_root / "NOTICE.md",
        ROOT / "PRIVACY.md": plugin_root / "PRIVACY.md",
        ROOT / "TERMS.md": plugin_root / "TERMS.md",
    }
    for src, dst in copies.items():
        shutil.copy2(src, dst)

    archive = DIST / f"lahne-man-plugin-{manifest['version']}.zip"
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for path in sorted(plugin_root.rglob("*")):
            if path.is_file():
                output.write(path, path.relative_to(DIST))
    return plugin_root, archive


def validate_build(plugin_root: Path, archive: Path) -> None:
    expected = {
        ".codex-plugin/plugin.json",
        "assets/lahne-man.png",
        "agents/openai.yaml",
        "skills/lahne-man/SKILL.md",
        "skills/lahne-man/eval.md",
        "skills/lahne-man/agents/openai.yaml",
        "README.md",
        "docs/USAGE.md",
        "docs/EXAMPLES.md",
        "LICENSE",
        "NOTICE.md",
        "PRIVACY.md",
        "TERMS.md",
    }
    actual = {
        str(path.relative_to(plugin_root))
        for path in plugin_root.rglob("*")
        if path.is_file()
    }
    if expected != actual:
        raise SystemExit(f"محتوای بسته با انتظار هم‌خوان نیست: {sorted(actual)}")

    if not zipfile.is_zipfile(archive):
        raise SystemExit("فایل خروجی ZIP معتبر نیست")

    manifest = json.loads((plugin_root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    if manifest["name"] != "lahne-man" or manifest["interface"]["displayName"] != "لحن من":
        raise SystemExit("نام افزونه در بسته نهایی صحیح نیست")


def main() -> None:
    args = parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    validate_source(manifest)
    plugin_root, archive = build_plugin(manifest)
    validate_build(plugin_root, archive)
    print(f"بسته ساخته شد: {archive.relative_to(ROOT)}")
    if args.check:
        shutil.rmtree(plugin_root)
        archive.unlink()
        try:
            DIST.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    main()
