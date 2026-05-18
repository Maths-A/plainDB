#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
install_script="$repo_root/scripts/install-to-dbeaver.sh"
dbeaver_app="${DBEAVER_APP:-/Applications/DBeaver.app}"

bash "$install_script"

osascript -e 'tell application "DBeaver" to quit' >/dev/null 2>&1 || true
sleep 2
"$dbeaver_app/Contents/MacOS/dbeaver" >/dev/null 2>&1 &
