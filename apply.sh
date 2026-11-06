#!/bin/sh
# Synchronize overlay-owned boards; preserve OpenWrt's upstream H5000M.
# All anchors and source files are validated before the source tree is changed.
set -eu
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec python3 "$HERE/scripts/apply_overlay.py" "${1:-.}"
