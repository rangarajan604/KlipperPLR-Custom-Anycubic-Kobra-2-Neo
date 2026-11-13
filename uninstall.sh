#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail

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

CONFIG_DIR="$USER_HOME/printer_data/config"
python3 - "$CONFIG_DIR/printer.cfg" "$CONFIG_DIR/moonraker.conf" <<'PY'
from pathlib import Path
import sys

for filename, line_to_remove in (
    (sys.argv[1], "[include plr_custom.cfg]"),
    (sys.argv[2], "[include update_plr_custom.cfg]"),
):
    path = Path(filename)
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text(
            "\n".join(line for line in lines if line.strip() != line_to_remove)
            + "\n",
            encoding="utf-8",
        )
PY

rm -f "$CONFIG_DIR/plr_custom.cfg" "$CONFIG_DIR/update_plr_custom.cfg"
rm -f "$USER_HOME/printer_data/plr_custom/plr.py"
rm -f "$USER_HOME/printer_data/plr_custom/plr.sh"
rm -f "$USER_HOME/printer_data/plr_custom/clear_plr.sh"
rm -f "$USER_HOME/printer_data/gcodes/plr_custom/"*.gcode
rmdir "$USER_HOME/printer_data/plr_custom" 2>/dev/null || true

echo "Custom PLR config and generated files removed."
echo "The shared gcode_shell_command.py extra and variables.cfg data were left in place."
