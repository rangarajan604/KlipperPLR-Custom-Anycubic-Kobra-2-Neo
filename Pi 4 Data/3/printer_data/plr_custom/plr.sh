#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VARIABLES_FILE="${USER_HOME:-$HOME}/printer_data/config/variables.cfg"

exec python3 "$SCRIPT_DIR/plr.py" generate \
  --variables "$VARIABLES_FILE" \
  --z "${1:?missing saved Z}" \
  --file "${2:?missing print filename}" \
  --bed-factor "${3:-1.05}" \
  --nozzle-factor "${4:-1.05}" \
  --z-lift "${5:-2}" \
  --dwell-ms "${6:-0}"
