#!/usr/bin/env python3
"""ساخت و اعتبارسنجی بسته قابل انتشار «لحن من»."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
import zipfile
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
PORTABLE_MANIFEST = ROOT / "plugin.json"
CODEX_MANIFEST = ROOT / ".codex-plugin" / "plugin.json"
DIST = ROOT / "dist"
SKILL_ROOT = ROOT / "skills" / "lahne-man"

VALID_CATEGORIES = {
    "Productivity",
    "Creativity",
    "Developer Tools",
    "Business & Operations",
    "Data & Analytics",
    "Communication",
    "Education & Research",
    "Security",
    "Finance",
    "Healthcare",
    "Travel",
    "Entertainment",
    "Other",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ساخت بسته افزونه لحن من")
    parser.add_argument(
        "--check",
        action="store_true",
        help="فقط اعتبارسنجی؛ خروجی نهایی نگه داشته نشود",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"فایل لازم پیدا نشد: {path.relative_to(ROOT)}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"JSON نامعتبر در {path.relative_to(ROOT)}: line {exc.lineno}, column {exc.colno}"
        ) from exc


def require_https(value: str, field: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise SystemExit(f"{field} باید URL معتبر HTTPS و بدون credential باشد")


def relative_asset(value: str, field: str) -> Path:
    if not value.startswith("./") or ".." in Path(value).parts:
        raise SystemExit(f"{field} باید مسیر نسبی امن با ./ باشد")
    path = ROOT / value[2:]
    if not path.is_file():
        raise SystemExit(f"فایل asset پیدا نشد: {value}")
    return path


def luminance(hex_color: str) -> float:
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", hex_color):
        raise SystemExit(f"رنگ نامعتبر است: {hex_color}")
    values = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]

    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(value) for value in values)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(first: str, second: str) -> float:
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def validate_png_icon(path: Path) -> None:
    if path.stat().st_size > 5 * 1024 * 1024:
        raise SystemExit(f"آیکن بیش از 5 MiB است: {path.relative_to(ROOT)}")

    data = path.read_bytes()
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise SystemExit(f"آیکن PNG معتبر نیست: {path.relative_to(ROOT)}")

    width, height = struct.unpack(">II", data[16:24])
    if width != height:
        raise SystemExit(f"آیکن باید مربع باشد: {width}x{height}")
    if width < 48 or width > 4096:
        raise SystemExit(f"ابعاد آیکن باید بین 48 و 4096 پیکسل باشد: {width}x{height}")


def validate_interface(interface: dict) -> None:
    required = (
        "displayName",
        "shortDescription",
        "longDescription",
        "developerName",
        "category",
        "capabilities",
    )
    missing = [key for key in required if not interface.get(key)]
    if missing:
        raise SystemExit(f"فیلدهای رابط ناقص‌اند: {', '.join(missing)}")

    limits = {
        "displayName": 30,
        "shortDescription": 30,
        "longDescription": 4000,
        "developerName": 80,
    }
    for key, limit in limits.items():
        value = interface[key]
        if not isinstance(value, str) or not value.strip():
            raise SystemExit(f"{key} باید متن غیرخالی باشد")
        if len(value) > limit:
            raise SystemExit(f"{key} از سقف انتشار عمومی ({limit} نویسه) بیشتر است")

    if interface["category"] not in VALID_CATEGORIES:
        raise SystemExit(f"category نامعتبر است: {interface['category']}")

    capabilities = interface["capabilities"]
    if not isinstance(capabilities, list) or len(capabilities) > 20:
        raise SystemExit("capabilities باید فهرستی با حداکثر 20 مورد باشد")
    for capability in capabilities:
        if not isinstance(capability, str) or not capability.strip() or len(capability) > 120:
            raise SystemExit("هر capability باید متن غیرخالی با حداکثر 120 نویسه باشد")

    prompts = interface.get("defaultPrompt", [])
    if isinstance(prompts, str):
        prompts = [prompts]
    if not isinstance(prompts, list) or len(prompts) > 3:
        raise SystemExit("حداکثر سه Prompt آغازین مجاز است")
    for prompt in prompts:
        if (
            not isinstance(prompt, str)
            or not prompt.strip()
            or len(prompt) > 128
            or "\n" in prompt
            or "\r" in prompt
        ):
            raise SystemExit("هر Prompt آغازین باید تک‌خطی، غیرخالی و حداکثر 128 نویسه باشد")

    for field in ("websiteURL", "supportURL", "privacyPolicyURL", "termsOfServiceURL"):
        if field in interface:
            require_https(interface[field], field)

    brand = interface.get("brandColor")
    if brand and contrast_ratio(brand, "#FFFFFF") < 2:
        raise SystemExit("brandColor کنتراست حداقل 2:1 با سفید ندارد")

    brand_dark = interface.get("brandColorDark")
    if brand_dark and contrast_ratio(brand_dark, "#212121") < 2:
        raise SystemExit("brandColorDark کنتراست حداقل 2:1 با #212121 ندارد")

    for field in ("composerIcon", "logo"):
        if not interface.get(field):
            raise SystemExit(f"{field} برای بسته Codex/Public لازم است")
        asset = relative_asset(interface[field], field)
        if asset.suffix.lower() == ".png":
            validate_png_icon(asset)


def validate_source(portable: dict, codex: dict) -> None:
    if portable.get("$schema") != "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json":
        raise SystemExit("plugin.json باید schema استاندارد Agent Plugins 1.0.0 را داشته باشد")

    for manifest, label in ((portable, "plugin.json"), (codex, ".codex-plugin/plugin.json")):
        for key in ("name", "version", "description"):
            if not manifest.get(key):
                raise SystemExit(f"{key} در {label} ناقص است")
        if manifest["name"] != "lahne-man":
            raise SystemExit(f"name در {label} باید lahne-man باشد")

    if portable["version"] != codex["version"]:
        raise SystemExit("نسخه plugin.json و .codex-plugin/plugin.json یکسان نیست")
    if codex.get("skills") != "./skills/":
        raise SystemExit("skills در manifest سازگاری Codex باید ./skills/ باشد")

    try:
        portable_openai = portable["extensions"]["com.openai"]
        portable_interface = portable_openai["interface"]
    except (KeyError, TypeError) as exc:
        raise SystemExit("extensions.com.openai.interface در plugin.json ناقص است") from exc

    codex_interface = codex.get("interface")
    if portable_interface != codex_interface:
        raise SystemExit("interface در manifest قابل‌حمل و Codex باید یکسان باشد")

    validate_interface(portable_interface)

    for source in (
        PORTABLE_MANIFEST,
        CODEX_MANIFEST,
        SKILL_ROOT / "SKILL.md",
        SKILL_ROOT / "eval.md",
        SKILL_ROOT / "agents" / "openai.yaml",
        ROOT / "assets" / "lahne-man.png",
        ROOT / "assets" / "lahne-man-cover.jpg",
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


def build_plugin(portable: dict) -> tuple[Path, Path]:
    DIST.mkdir(exist_ok=True)
    plugin_root = DIST / "lahne-man"
    if plugin_root.exists():
        shutil.rmtree(plugin_root)

    skill_root = plugin_root / "skills" / "lahne-man"
    (plugin_root / ".codex-plugin").mkdir(parents=True)
    (plugin_root / "assets").mkdir(parents=True)
    (skill_root / "agents").mkdir(parents=True)
    (plugin_root / "docs").mkdir(parents=True)

    copies = {
        PORTABLE_MANIFEST: plugin_root / "plugin.json",
        CODEX_MANIFEST: plugin_root / ".codex-plugin" / "plugin.json",
        SKILL_ROOT / "SKILL.md": skill_root / "SKILL.md",
        SKILL_ROOT / "eval.md": skill_root / "eval.md",
        SKILL_ROOT / "agents" / "openai.yaml": skill_root / "agents" / "openai.yaml",
        ROOT / "assets" / "lahne-man.png": plugin_root / "assets" / "lahne-man.png",
        ROOT / "assets" / "lahne-man-cover.jpg": plugin_root / "assets" / "lahne-man-cover.jpg",
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

    archive = DIST / f"lahne-man-plugin-{portable['version']}.zip"
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for path in sorted(plugin_root.rglob("*")):
            if path.is_file():
                output.write(path, path.relative_to(DIST))
    return plugin_root, archive


def validate_build(plugin_root: Path, archive: Path) -> None:
    expected = {
        "plugin.json",
        ".codex-plugin/plugin.json",
        "assets/lahne-man.png",
        "assets/lahne-man-cover.jpg",
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

    portable = load_json(plugin_root / "plugin.json")
    codex = load_json(plugin_root / ".codex-plugin" / "plugin.json")
    if portable["name"] != "lahne-man" or codex["name"] != "lahne-man":
        raise SystemExit("نام افزونه در بسته نهایی صحیح نیست")


def main() -> None:
    args = parse_args()
    portable = load_json(PORTABLE_MANIFEST)
    codex = load_json(CODEX_MANIFEST)
    validate_source(portable, codex)
    plugin_root, archive = build_plugin(portable)
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
