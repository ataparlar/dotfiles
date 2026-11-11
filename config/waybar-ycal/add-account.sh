#!/usr/bin/env bash
# Quick wrapper to add or manage Google accounts for hypr-ycal / waybar-ycal
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
exec /usr/bin/python3 "$DIR/add-account.py" "$@"
