#!/usr/bin/env bash
# Build standalone lanbox-tui / lanbox-simulator binaries with PyInstaller,
# smoke-test them, and pack them as dist/lanbox-tui-<version>-<platform>.tar.gz.
#
# Used by .github/workflows/release-binaries.yml, but runs locally too:
#   pip install -e ".[dev]" pyinstaller && packaging/build.sh linux-x86_64
set -euo pipefail
cd "$(dirname "$0")/.."

platform="${1:?usage: packaging/build.sh <platform-label, e.g. linux-x86_64>}"
version="$(python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"

rm -rf build dist
for app in lanbox-tui lanbox-simulator; do
  # Textual loads widgets and stylesheets lazily and rich loads its unicode
  # tables by name, so PyInstaller's import scan alone misses some of them.
  python -m PyInstaller --noconfirm --clean --onefile --name "$app" \
    --distpath dist --workpath build/work --specpath build \
    --collect-all textual \
    --collect-submodules rich \
    --collect-submodules lanbox_tui \
    "$PWD/packaging/$app.py"
done

python packaging/smoke_test.py dist

archive="lanbox-tui-${version}-${platform}.tar.gz"
tar -czf "dist/$archive" -C dist lanbox-tui lanbox-simulator -C .. README.md
echo "Built dist/$archive"
