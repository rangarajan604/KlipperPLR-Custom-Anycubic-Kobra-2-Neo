#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VARIABLES_FILE="${USER_HOME:-$HOME}/printer_data/config/variables.cfg"

exec python3 "$SCRIPT_DIR/plr.py" clear \
  --variables "$VARIABLES_FILE"
