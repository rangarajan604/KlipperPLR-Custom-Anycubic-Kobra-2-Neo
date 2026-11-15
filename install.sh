#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
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
PLR_DIR="$USER_HOME/printer_data/plr_custom"
KLIPPER_EXTRAS="$USER_HOME/klipper/klippy/extras"
GCODE_DIR="$USER_HOME/printer_data/gcodes/plr_custom"
PRINTER_CFG="$CONFIG_DIR/printer.cfg"
MOONRAKER_CONF="$CONFIG_DIR/moonraker.conf"
ACTIVE_CFG="$CONFIG_DIR/plr_custom.cfg"
UPDATE_CFG="$CONFIG_DIR/update_plr_custom.cfg"
SHELL_EXTRA="$KLIPPER_EXTRAS/gcode_shell_command.py"
REPO_URL="https://github.com/rangarajan604/KlipperPLR-Custom-Anycubic-Kobra-2-Neo.git"

if [[ ! -d "$CONFIG_DIR" || ! -f "$PRINTER_CFG" ]]; then
  echo "Expected Klipper config directory and printer.cfg under $CONFIG_DIR" >&2
  exit 1
fi
ACTIVE_ALREADY_INSTALLED=false
if [[ -f "$ACTIVE_CFG" ]]; then
  if grep -Fq "Managed by KlipperPLR-Custom-Anycubic-Kobra-2-Neo." "$ACTIVE_CFG"; then
    ACTIVE_ALREADY_INSTALLED=true
    echo "Preserving existing Mainsail-edited custom PLR config."
  else
    echo "$ACTIVE_CFG already exists and is not managed by this project; refusing to overwrite it." >&2
    exit 1
  fi
fi
if [[ "$ACTIVE_ALREADY_INSTALLED" == false ]] && \
  grep -R -E '^\[include[[:space:]]+plr\.cfg\]|^\[gcode_macro[[:space:]]+(RESUME_INTERRUPTED|G31|save_last_file|clear_last_file|LOG_Z)\]' \
  "$CONFIG_DIR" --include='*.cfg' >/dev/null 2>&1; then
  echo "An existing PLR include or RESUME_INTERRUPTED macro was found." >&2
  echo "Back up and disable the existing PLR before installing this project." >&2
  exit 1
fi
if [[ "$ACTIVE_ALREADY_INSTALLED" == false ]] && \
  grep -R -E '^\[gcode_macro[[:space:]]+(EXCLUDE_OBJECT|EXCLUDE_OBJECT_DEFINE)\]' \
  "$CONFIG_DIR" --include='*.cfg' >/dev/null 2>&1; then
  echo "An existing object-exclusion wrapper was found." >&2
  echo "Remove or merge it before installing this project's exclusion persistence macros." >&2
  exit 1
fi

mkdir -p "$PLR_DIR" "$KLIPPER_EXTRAS" "$GCODE_DIR"
if [[ "$ACTIVE_ALREADY_INSTALLED" == false ]]; then
  cp "$PROJECT_DIR/plr_custom.cfg" "$ACTIVE_CFG"
fi
cp "$PROJECT_DIR/plr.py" "$PLR_DIR/plr.py"
cp "$PROJECT_DIR/plr.sh" "$PLR_DIR/plr.sh"
cp "$PROJECT_DIR/clear_plr.sh" "$PLR_DIR/clear_plr.sh"
chmod 755 "$PLR_DIR/plr.py" "$PLR_DIR/plr.sh" "$PLR_DIR/clear_plr.sh"

if [[ "$ACTIVE_ALREADY_INSTALLED" == false ]]; then
  sed -i "s|{PLR_DIR}|$PLR_DIR|g" "$ACTIVE_CFG"
fi
python3 - "$CONFIG_DIR" "$ACTIVE_CFG" "$ACTIVE_ALREADY_INSTALLED" <<'PY'
from pathlib import Path
import re
import sys

config_dir = Path(sys.argv[1])
active_cfg = Path(sys.argv[2])
already_installed = sys.argv[3] == "true"
sections = {}
for path in config_dir.rglob("*.cfg"):
    text = path.read_text(encoding="utf-8", errors="replace")
    for match in re.finditer(
        r"(?ms)^\s*\[([^\]]+)\]\s*\n(.*?)(?=^\s*\[|\Z)", text
    ):
        sections.setdefault(match.group(1).strip().lower(), (path, match.group(2)))

prefix = []
force_move = sections.get("force_move")
if force_move:
    if not re.search(
        r"(?mi)^\s*enable_force_move\s*:\s*true\s*$", force_move[1]
    ):
        raise SystemExit(
            f"{force_move[0]} already has [force_move] but does not enable it; "
            "configure this deliberately before installing PLR"
        )
else:
    prefix.extend(["[force_move]", "enable_force_move: True", ""])

if "exclude_object" not in sections:
    prefix.extend(["[exclude_object]", ""])
if "save_variables" not in sections:
    prefix.extend(
        ["[save_variables]", f"filename: {config_dir}/variables.cfg", ""]
    )
if prefix and not already_installed:
    active_cfg.write_text(
        "\n".join(prefix) + active_cfg.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
PY

python3 - "$PRINTER_CFG" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
include = "[include plr_custom.cfg]"
if include not in text.splitlines():
    path.write_text(include + "\n" + text, encoding="utf-8")
PY

if [[ ! -f "$MOONRAKER_CONF" ]]; then
  touch "$MOONRAKER_CONF"
fi
python3 - "$MOONRAKER_CONF" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
include = "[include update_plr_custom.cfg]"
if include not in text.splitlines():
    path.write_text(include + "\n" + text, encoding="utf-8")
PY

cat > "$UPDATE_CFG" <<EOF
[update_manager KlipperPLR-Custom]
type: git_repo
path: ~/KlipperPLR-Custom-Anycubic-Kobra-2-Neo
origin: $REPO_URL
primary_branch: main
install_script: install.sh
is_system_service: False
EOF

if [[ -f "$SHELL_EXTRA" ]] && ! cmp -s "$PROJECT_DIR/gcode_shell_command.py" "$SHELL_EXTRA"; then
  cp "$SHELL_EXTRA" "$SHELL_EXTRA.pre-custom-plr"
  cp "$PROJECT_DIR/gcode_shell_command.py" "$SHELL_EXTRA"
elif [[ ! -f "$SHELL_EXTRA" ]]; then
  cp "$PROJECT_DIR/gcode_shell_command.py" "$SHELL_EXTRA"
else
  echo "Matching gcode_shell_command.py already installed."
fi

if [[ "$PRINTER_USER" != "$USER" ]]; then
  PRINTER_GROUP="$(id -gn "$PRINTER_USER")"
  chown "$PRINTER_USER:$PRINTER_GROUP" "$ACTIVE_CFG" "$UPDATE_CFG" \
    "$PRINTER_CFG" "$MOONRAKER_CONF" "$SHELL_EXTRA"
  chown -R "$PRINTER_USER:$PRINTER_GROUP" "$PLR_DIR" "$GCODE_DIR"
fi

echo "Installation complete."
echo "Review $ACTIVE_CFG, then run RESTART in Mainsail."
echo "If your printer.cfg already loads another PLR include, resolve that before restarting."
