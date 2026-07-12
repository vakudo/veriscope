import hashlib
import json
import re
import zipfile

from app import __version__
from scripts.package_extension import EXTENSION_DIR, package_extension


def test_extension_manifest_matches_application_version():
    manifest = json.loads((EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == __version__
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])
    assert "*://*/*" not in manifest["host_permissions"]


def test_extension_package_is_complete_and_reproducible(tmp_path):
    first = package_extension(tmp_path / "first.zip")
    second = package_extension(tmp_path / "second.zip")
    assert hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(second.read_bytes()).digest()
    with zipfile.ZipFile(first) as archive:
        names = set(archive.namelist())
    assert names == {
        "background.js",
        "icons/icon16.png",
        "icons/icon32.png",
        "icons/icon48.png",
        "icons/icon128.png",
        "manifest.json",
        "popup.css",
        "popup.html",
        "popup.js",
    }
