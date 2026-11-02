#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
# Private Python, used only when no supported copy is installed. Keep in step with start.bat.
PY_RELEASE=20261013
PY_VERSION=3.13.16
PY_SHA256=16a5332fb0dcb77f163fc8f8cbccd95be1644cc53e68e5d2a79f50afd6680a0e
PY_FILE="cpython-$PY_VERSION+$PY_RELEASE-aarch64-apple-darwin-install_only_stripped.tar.gz"
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/$PY_RELEASE/$PY_FILE"

if [ "$(uname -s)" != Darwin ]; then
    echo 'This release supports Windows 10/11 on x64 computers and Apple silicon Macs. Linux is not supported.'
    exit 1
fi
if [ "$(uname -m)" != arm64 ]; then
    echo 'This release requires an Apple silicon Mac. Intel Macs and terminals running under Rosetta are not supported.'
    exit 1
fi
if [ "$(sw_vers -productVersion | cut -d. -f1)" -lt 14 ]; then
    echo 'This release requires macOS 14 or later. Update macOS before installing.'
    exit 1
fi

supported() {
    "$1" -c 'import platform,sys;sys.exit(not ((3,11)<=sys.version_info[:2]<=(3,13) and sys.maxsize>2**32 and platform.machine()=="arm64"))' >/dev/null 2>&1
}
for candidate in .runtime/python/bin/python3 python3.13 python3.12 python3.11 python3; do
    found="$(command -v "$candidate" || true)"
    # macOS's /usr/bin/python3 is too old and can open a developer tools dialog.
    if [ -n "$found" ] && [ "$found" != /usr/bin/python3 ] && supported "$found"; then
        exec "$found" setup_local.py "$@"
    fi
done

manual() {
    echo 'Python could not be set up automatically. Check your internet connection and run this again.'
    echo 'If it still stops here, install Python 3.13 from https://www.python.org/downloads/release/python-31317/'
    echo 'using the macOS installer, then run this again.'
    exit 1
}
echo 'Setting up a private copy of Python for this app, about 25 MB. Nothing else on your computer changes.'
mkdir -p .runtime
curl -fL --retry 3 --retry-delay 3 --connect-timeout 30 --progress-bar -o .runtime/python.tar.gz "$PY_URL" || manual
if [ "$(shasum -a 256 .runtime/python.tar.gz | cut -d' ' -f1)" != "$PY_SHA256" ]; then
    rm -f .runtime/python.tar.gz
    echo 'The Python download was damaged or incomplete. Run this again to retry.'
    exit 1
fi
rm -rf .runtime/incoming
mkdir .runtime/incoming
tar -xzf .runtime/python.tar.gz -C .runtime/incoming || manual
supported .runtime/incoming/python/bin/python3 || manual
mv .runtime/incoming/python .runtime/python
rm -rf .runtime/incoming .runtime/python.tar.gz
exec .runtime/python/bin/python3 setup_local.py "$@"
