#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ -n "${SUDO_USER:-}" ]]; then
  PRINTER_USER="$SUDO_USER"
else
  PRINTER_USER="$USER"
fi
USER_HOME="$(getent passwd "$PRINTER_USER" | cut -d: -f6)"
if [[ -z "$USER_HOME" || ! -d "$USER_HOME" ]]; then
  echo "Cannot determine home directory for user $PRINTER_USER" >&2
  exit 1
fi

cd -- "$USER_HOME"
python3 "$PROJECT_DIR/uninstall.py" \
  "$USER_HOME" "$PROJECT_DIR/gcode_shell_command.py"
