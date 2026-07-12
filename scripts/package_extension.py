import argparse
import json
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = PROJECT_ROOT / "extension"
DIST_DIR = PROJECT_ROOT / "dist"
PACKAGE_SUFFIXES = {".css", ".html", ".js", ".json", ".png"}
ZIP_TIMESTAMP = (2020, 1, 1, 0, 0, 0)


def extension_version() -> str:
    manifest = json.loads((EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8"))
    return manifest["version"]


def package_extension(output: Path | None = None) -> Path:
    target = output or DIST_DIR / f"veriscope-extension-{extension_version()}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(
        path
        for path in EXTENSION_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in PACKAGE_SUFFIXES
    )
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(EXTENSION_DIR).as_posix()
            info = zipfile.ZipInfo(relative, ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a deterministic Chrome extension archive")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(package_extension(args.output))


if __name__ == "__main__":
    main()
